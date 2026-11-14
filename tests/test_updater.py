"""Updater tests against a local bare repo (no network, no token)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.updater import Updater  # noqa: E402


def git(cwd, *args):
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(cwd),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )


class TestUpdater(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.remote = root / "remote.git"
        self.clone = root / "clone"
        seed = root / "seed"
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(self.remote)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "clone", str(self.remote), str(seed)],
            check=True, capture_output=True,
        )
        git(seed, "config", "user.email", "t@t")
        git(seed, "config", "user.name", "t")
        (seed / "a.txt").write_text("one\n")
        git(seed, "add", ".")
        git(seed, "commit", "-m", "c1")
        git(seed, "push", "origin", "main")
        subprocess.run(
            ["git", "clone", str(self.remote), str(self.clone)],
            check=True, capture_output=True,
        )
        self.seed = seed
        self.updater = Updater(self.clone)

    def tearDown(self):
        self._tmp.cleanup()

    def _push_second_commit(self):
        (self.seed / "b.txt").write_text("two\n")
        git(self.seed, "add", ".")
        git(self.seed, "commit", "-m", "c2")
        git(self.seed, "push", "origin", "main")

    def test_up_to_date(self):
        info = self.updater.status()
        self.assertTrue(info["ok"], info)
        self.assertTrue(info["up_to_date"])
        self.assertEqual(info["behind"], 0)

    def test_detects_and_applies_update(self):
        self._push_second_commit()
        info = self.updater.status()
        self.assertEqual(info["behind"], 1)
        report = self.updater.apply()
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["updated"])
        self.assertTrue((self.clone / "b.txt").exists())
        self.assertTrue(self.updater.status()["up_to_date"])

    def test_dirty_tree_blocks_update(self):
        (self.clone / "a.txt").write_text("local edit\n")
        self._push_second_commit()
        report = self.updater.apply()
        self.assertFalse(report["ok"])
        self.assertIn("a.txt", report["error"])
        self.assertFalse((self.clone / "b.txt").exists())

    def test_not_a_repo(self):
        info = Updater(Path(self._tmp.name) / "nope").status()
        self.assertFalse(info["ok"])
        self.assertIn("error", info)

    def test_fetch_url_injects_token_only_for_github(self):
        updater = Updater(self.clone, github_token="SECRET")
        # local path remote → untouched
        self.assertNotIn("SECRET", updater._fetch_url())


if __name__ == "__main__":
    unittest.main()
