"""Unit tests for the SQLite allow-list in app/storage.py.

Run with:  python -m unittest discover -s tests -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage import FileStore  # noqa: E402


class TestAllowList(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = FileStore(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_and_check(self):
        self.assertTrue(self.store.add_allowed_user(111))
        self.assertTrue(self.store.is_allowed_user(111))
        self.assertFalse(self.store.is_allowed_user(222))

    def test_add_twice_reports_not_new(self):
        self.assertTrue(self.store.add_allowed_user(111))
        self.assertFalse(self.store.add_allowed_user(111))
        self.assertEqual(self.store.allowed_user_ids(), {111})

    def test_remove(self):
        self.store.add_allowed_user(111)
        self.assertTrue(self.store.remove_allowed_user(111))
        self.assertFalse(self.store.remove_allowed_user(111))
        self.assertFalse(self.store.is_allowed_user(111))

    def test_seed_never_removes(self):
        self.store.add_allowed_user(111)
        self.store.seed_allowed_users([222, 333])
        self.assertEqual(self.store.allowed_user_ids(), {111, 222, 333})
        # Re-seeding (e.g. the next boot) is a no-op for existing rows.
        self.store.seed_allowed_users([222])
        self.assertEqual(self.store.allowed_user_ids(), {111, 222, 333})

    def test_persists_across_reopen(self):
        self.store.add_allowed_user(111)
        reopened = FileStore(Path(self._tmp.name))
        self.assertEqual(reopened.allowed_user_ids(), {111})


if __name__ == "__main__":
    unittest.main()
