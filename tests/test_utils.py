"""Unit tests for the dependency-free helpers in app/utils.py.

Run with:  python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils import (  # noqa: E402
    extract_urls,
    filename_from_content_disposition,
    human_size,
    parse_user_id,
    resolve_download_filename,
    sanitize_filename,
)


class TestSanitizeFilename(unittest.TestCase):
    def test_path_traversal_is_neutralised(self):
        self.assertNotIn("/", sanitize_filename("../../etc/passwd"))
        self.assertNotIn("\\", sanitize_filename("..\\..\\win.ini"))

    def test_bad_chars_replaced(self):
        self.assertEqual(sanitize_filename('a:b*c?"d<e>f|.zip'), "a_b_c__d_e_f_.zip")

    def test_empty_falls_back(self):
        self.assertEqual(sanitize_filename(""), "file")
        self.assertEqual(sanitize_filename(None), "file")
        self.assertEqual(sanitize_filename("..."), "file")

    def test_long_name_keeps_extension(self):
        name = sanitize_filename("x" * 300 + ".pdf")
        self.assertLessEqual(len(name), 180)
        self.assertTrue(name.endswith(".pdf"))

    def test_persian_name_survives(self):
        self.assertEqual(sanitize_filename("گزارش نهایی.pdf"), "گزارش نهایی.pdf")


class TestResolveFilename(unittest.TestCase):
    def test_content_disposition_wins(self):
        name = resolve_download_filename(
            "https://example.com/get?id=3",
            'attachment; filename="report 2026.pdf"',
            "application/pdf",
        )
        self.assertEqual(name, "report 2026.pdf")

    def test_rfc5987_filename_star(self):
        header = "attachment; filename*=UTF-8''%DA%AF%D8%B2%D8%A7%D8%B1%D8%B4.pdf"
        self.assertEqual(filename_from_content_disposition(header), "گزارش.pdf")

    def test_url_path_used(self):
        name = resolve_download_filename(
            "https://example.com/files/ubuntu-24.04.iso?x=1", None, None
        )
        self.assertEqual(name, "ubuntu-24.04.iso")

    def test_fallback_uses_content_type(self):
        name = resolve_download_filename(
            "https://example.com/download", None, "application/zip"
        )
        self.assertEqual(name, "download.zip")


class TestExtractUrls(unittest.TestCase):
    def test_finds_and_trims(self):
        text = "grab this (https://example.com/a.zip), and https://x.y/b."
        self.assertEqual(
            extract_urls(text),
            ["https://example.com/a.zip", "https://x.y/b"],
        )

    def test_none_when_no_url(self):
        self.assertEqual(extract_urls("no links here"), [])
        self.assertEqual(extract_urls(""), [])


class TestParseUserId(unittest.TestCase):
    def test_bare_id(self):
        self.assertEqual(parse_user_id("123456789"), 123456789)

    def test_id_with_whitespace_and_label(self):
        self.assertEqual(parse_user_id("  id: 987654321 \n"), 987654321)

    def test_rejects_usernames_and_junk(self):
        self.assertIsNone(parse_user_id("@someuser"))
        self.assertIsNone(parse_user_id("hello"))
        self.assertIsNone(parse_user_id(""))
        self.assertIsNone(parse_user_id(None))
        self.assertIsNone(parse_user_id("42"))  # too short to be an ID


class TestHumanSize(unittest.TestCase):
    def test_units(self):
        self.assertEqual(human_size(512), "512 B")
        self.assertTrue(human_size(20 * 1024 * 1024).startswith("20"))
        self.assertEqual(human_size(None), "unknown size")


if __name__ == "__main__":
    unittest.main()
