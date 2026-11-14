"""Web admin panel API tests (aiohttp test client, no network)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from app.config import Config  # noqa: E402
from app.envfile import parse_env_file  # noqa: E402
from app.storage import FileStore  # noqa: E402
from app.webserver import create_web_app  # noqa: E402


class TestWebAdmin(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.env_file = root / ".env"
        self.config = Config(
            bot_token="123:abc",
            base_url="http://panel.test:2020",
            port=2020,
            storage_dir=root / "storage",
            owner_ids=frozenset({111}),
            web_admin_password="pw123",
            env_file=self.env_file,
            github_repo="x/y",
        )
        self.store = FileStore(root / "storage")
        self.client = TestClient(
            TestServer(create_web_app(self.store, self.config))
        )
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self._tmp.cleanup()

    async def _login(self):
        resp = await self.client.post(
            "/admin/api/login", json={"password": "pw123"}
        )
        self.assertEqual(resp.status, 200)

    async def test_panel_page_served(self):
        resp = await self.client.get("/admin")
        self.assertEqual(resp.status, 200)
        self.assertIn("Admin login", await resp.text())

    async def test_api_requires_login(self):
        resp = await self.client.get("/admin/api/status")
        self.assertEqual(resp.status, 401)

    async def test_wrong_password(self):
        resp = await self.client.post(
            "/admin/api/login", json={"password": "nope"}
        )
        self.assertEqual(resp.status, 401)

    async def test_status_and_users_flow(self):
        await self._login()
        resp = await self.client.get("/admin/api/status")
        data = await resp.json()
        self.assertEqual(resp.status, 200)
        self.assertEqual(data["port"], 2020)
        self.assertEqual(data["files_count"], 0)

        resp = await self.client.post(
            "/admin/api/users", json={"user_id": "555555555"}
        )
        self.assertTrue((await resp.json())["added"])
        resp = await self.client.post(
            "/admin/api/users", json={"user_id": "not-a-number"}
        )
        self.assertEqual(resp.status, 400)

        resp = await self.client.get("/admin/api/users")
        data = await resp.json()
        self.assertEqual(data["owners"], [111])
        self.assertEqual(data["allowed"], [555555555])

        resp = await self.client.delete("/admin/api/users/555555555")
        self.assertTrue((await resp.json())["removed"])

    async def test_files_flow(self):
        await self._login()
        token = self.store.new_token()
        path = self.store.path_for(token, "hello.txt")
        path.write_bytes(b"hello world")
        self.store.register(token, "hello.txt", 11, "text/plain", 111)
        resp = await self.client.get("/admin/api/files")
        files = (await resp.json())["files"]
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0]["link"].endswith("/d/" + token + "/hello.txt"))
        resp = await self.client.delete(f"/admin/api/files/{token}")
        self.assertEqual(resp.status, 200)
        self.assertIsNone(self.store.get(token))

    async def test_settings_save_and_validation(self):
        await self._login()
        resp = await self.client.post(
            "/admin/api/settings",
            json={"updates": {"APP_PORT": "62001", "BASE_URL": "http://n:62001"}},
        )
        self.assertEqual(resp.status, 200)
        values = parse_env_file(self.env_file)
        self.assertEqual(values["APP_PORT"], "62001")

        resp = await self.client.post(
            "/admin/api/settings", json={"updates": {"APP_PORT": "99999"}}
        )
        self.assertEqual(resp.status, 400)
        resp = await self.client.post(
            "/admin/api/settings", json={"updates": {"EVIL_KEY": "x"}}
        )
        self.assertEqual(resp.status, 400)

    async def test_update_check_returns_json(self):
        await self._login()
        resp = await self.client.post("/admin/api/update/check")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("ok", data)  # real GitHub reachability not asserted


class TestPanelDisabled(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_without_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = Config(
                bot_token="123:abc",
                base_url="http://x",
                storage_dir=root / "storage",
                env_file=root / ".env",
            )
            store = FileStore(root / "storage")
            client = TestClient(TestServer(create_web_app(store, config)))
            await client.start_server()
            try:
                resp = await client.get("/admin")
                self.assertIn("disabled", (await resp.text()).lower())
                resp = await client.get("/admin/api/status")
                self.assertEqual(resp.status, 403)
            finally:
                await client.close()


if __name__ == "__main__":
    unittest.main()
