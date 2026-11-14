"""Config tests: port priority (APP_PORT), GitHub/updater/GUI settings."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config, read_version  # noqa: E402

BASE_ENV = {"BOT_TOKEN": "123:abc", "BASE_URL": "http://example.test:8080"}


def load(env):
    with patch.dict(os.environ, {**BASE_ENV, **env}, clear=True):
        return Config.from_env()


class TestPortPriority(unittest.TestCase):
    def test_app_port_wins(self):
        cfg = load({"APP_PORT": "2020", "PORT": "1111", "SERVER_PORT": "2222"})
        self.assertEqual(cfg.port, 2020)

    def test_port_beats_server_port(self):
        cfg = load({"PORT": "1111", "SERVER_PORT": "2222"})
        self.assertEqual(cfg.port, 1111)

    def test_server_port_fallback(self):
        cfg = load({"SERVER_PORT": "62001"})
        self.assertEqual(cfg.port, 62001)

    def test_default_8080(self):
        self.assertEqual(load({}).port, 8080)


class TestNewSettings(unittest.TestCase):
    def test_github_and_gui_settings(self):
        cfg = load(
            {
                "GITHUB_TOKEN": "ghp_x",
                "AUTO_UPDATE": "1",
                "WEB_ADMIN_PASSWORD": "pw",
                "OWNER_IDS": "10, 20",
            }
        )
        self.assertEqual(cfg.github_token, "ghp_x")
        self.assertTrue(cfg.auto_update)
        self.assertEqual(cfg.web_admin_password, "pw")
        self.assertEqual(cfg.owner_ids, frozenset({10, 20}))
        self.assertEqual(cfg.github_repo, "IzumiRain/TelegramFileLinkBot")

    def test_version_file(self):
        version = read_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
