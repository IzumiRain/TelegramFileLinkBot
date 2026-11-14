"""Streaming URL -> file downloader (Link-to-File direction).

Downloads in chunks so multi-GB files never sit in memory, reports
progress through an async callback, and enforces a hard size cap both
from the Content-Length header and while streaming (servers lie).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import aiohttp

from .utils import resolve_download_filename

CHUNK_SIZE = 256 * 1024
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 TelegramFileLinkBot/1.0"
)

ProgressCallback = Callable[[int, int | None], Awaitable[None]]


class DownloadError(Exception):
    """A user-facing download failure (bad URL, HTTP error, too large...)."""


class FileTooLarge(DownloadError):
    pass


@dataclass
class DownloadedFile:
    path: Path
    filename: str
    size: int
    content_type: str | None


async def download_url(
    url: str,
    dest_dir: Path,
    token: str,
    max_bytes: int,
    on_progress: ProgressCallback | None = None,
) -> DownloadedFile:
    """Download `url` into dest_dir/<token>/<resolved filename>."""
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=120)
    headers = {"User-Agent": USER_AGENT}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    raise DownloadError(f"The server answered HTTP {resp.status}.")
                total = resp.content_length
                if total is not None and total > max_bytes:
                    raise FileTooLarge(
                        f"That file is {total} bytes, over the "
                        f"{max_bytes} byte limit set in .env."
                    )
                filename = resolve_download_filename(
                    str(resp.url),
                    resp.headers.get("Content-Disposition"),
                    resp.headers.get("Content-Type"),
                )
                dest_dir.mkdir(parents=True, exist_ok=True)
                path = dest_dir / filename
                downloaded = 0
                with open(path, "wb") as fh:
                    async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            fh.close()
                            path.unlink(missing_ok=True)
                            raise FileTooLarge(
                                f"Download passed the {max_bytes} byte limit "
                                "set in .env and was aborted."
                            )
                        if on_progress is not None:
                            await on_progress(downloaded, total)
                return DownloadedFile(
                    path=path,
                    filename=filename,
                    size=downloaded,
                    content_type=resp.headers.get("Content-Type"),
                )
    except aiohttp.ClientError as exc:
        raise DownloadError(f"Could not reach that URL: {exc}") from exc
    except TimeoutError as exc:
        raise DownloadError("The download timed out.") from exc
