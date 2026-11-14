"""Downloader tests against a hand-rolled raw HTTP server, so the
drop/resume behaviour is fully deterministic: the first response is
cut mid-body, and the test then watches how the client recovers.
"""
import asyncio
import tempfile
import unittest
from pathlib import Path

from app.downloader import download_url

PAYLOAD = bytes(range(256)) * 1200  # 307_200 bytes
CUT = 100_000


class _Server:
    """mode 'resume': honours Range. mode 'ignore': always answers 200."""

    def __init__(self, mode: str):
        self.mode = mode
        self.requests: list[str] = []

    async def handle(self, reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter) -> None:
        try:
            data = await reader.readuntil(b"\r\n\r\n")
        except Exception:
            writer.close()
            return
        head = data.decode("latin1").lower()
        self.requests.append(head)
        range_start = None
        for line in head.split("\r\n"):
            if line.startswith("range: bytes="):
                range_start = int(line.split("=", 1)[1].split("-", 1)[0])
        if self.mode == "resume" and range_start:
            rest = PAYLOAD[range_start:]
            writer.write(
                b"HTTP/1.1 206 Partial Content\r\n"
                b"Content-Type: application/octet-stream\r\n"
                + f"Content-Length: {len(rest)}\r\n".encode()
                + f"Content-Range: bytes {range_start}-"
                  f"{len(PAYLOAD) - 1}/{len(PAYLOAD)}\r\n".encode()
                + b"Connection: close\r\n\r\n"
                + rest
            )
            await writer.drain()
            writer.close()
            return
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/octet-stream\r\n"
            + f"Content-Length: {len(PAYLOAD)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
        )
        if len(self.requests) == 1:
            # First response dies mid-body — the flaky-route case.
            writer.write(PAYLOAD[:CUT])
            await writer.drain()
            writer.close()
            return
        writer.write(PAYLOAD)
        await writer.drain()
        writer.close()


class TestDownloaderResume(unittest.IsolatedAsyncioTestCase):
    async def _run(self, mode: str):
        srv = _Server(mode)
        server = await asyncio.start_server(srv.handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as td:
                result = await download_url(
                    f"http://127.0.0.1:{port}/file.bin",
                    Path(td), "tok", max_bytes=10_000_000,
                )
                self.assertEqual(result.size, len(PAYLOAD))
                self.assertEqual(result.path.read_bytes(), PAYLOAD)
        finally:
            server.close()
        return srv

    async def test_resumes_with_range_after_drop(self):
        srv = await self._run("resume")
        self.assertEqual(len(srv.requests), 2)
        self.assertIn("range: bytes=", srv.requests[1])

    async def test_restarts_when_server_ignores_range(self):
        srv = await self._run("ignore")
        self.assertEqual(len(srv.requests), 2)


if __name__ == "__main__":
    unittest.main()
