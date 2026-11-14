"""Unit tests for app/envfile.py (.env editing)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.envfile import parse_env_file, update_env_file  # noqa: E402

ORIGINAL = """# a comment
BOT_TOKEN=old-token
PORT=8080

# another section
BASE_URL=http://example.com  # trailing comment in value line is kept as-is on disk
EMPTY=
"""


class TestEnvFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / ".env"
        self.path.write_text(ORIGINAL, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_parse(self):
        values = parse_env_file(self.path)
        self.assertEqual(values["BOT_TOKEN"], "old-token")
        self.assertEqual(values["PORT"], "8080")
        self.assertEqual(values["EMPTY"], "")

    def test_update_preserves_comments_and_order(self):
        update_env_file(self.path, {"PORT": "2020", "NEW_KEY": "x y"})
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("# a comment", text)
        self.assertIn("PORT=2020", text)
        self.assertIn('NEW_KEY="x y"', text)  # spaces get quoted
        self.assertLess(text.index("BOT_TOKEN"), text.index("PORT"))
        self.assertEqual(parse_env_file(self.path)["NEW_KEY"], "x y")

    def test_remove_key(self):
        update_env_file(self.path, {"PORT": None})
        self.assertNotIn("PORT", parse_env_file(self.path))

    def test_creates_file(self):
        other = Path(self._tmp.name) / "fresh.env"
        update_env_file(other, {"A": "1"})
        self.assertEqual(parse_env_file(other), {"A": "1"})

    def test_secret_with_dollar_is_quoted(self):
        update_env_file(self.path, {"GITHUB_TOKEN": "ghp_a$b"})
        self.assertEqual(parse_env_file(self.path)["GITHUB_TOKEN"], "ghp_a$b")


if __name__ == "__main__":
    unittest.main()
