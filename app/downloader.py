"""Streaming URL -> file downloader (Link-to-File direction).

Downloads in chunks so multi-GB files never sit in memory, reports
progress through an async callback, and enforces a hard size cap both
from the Content-Length header and while streaming (servers lie).

Slow/flaky routes are the norm for this bot (e.g. an Iranian CDN read
from a US node), so a dropped or stalled connection is NOT fatal: the
download resumes with an HTTP Range request from the byte it reached,
up to MAX_ATTEMPTS times. Servers that ignore Range just restart the
file from zero on the next attempt.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import aiohttp

from .utils import resolve_download_filename

logger = logging.getLogger(__name__)

CHUNK_SIZE = 256 * 1024
MAX_ATTEMPTS = 6          # 1 initial try + up to 5 resumes
SOCK_READ_TIMEOUT = 180   # seconds of total silence before a resume
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


def _log_label(url: str) -> str:
    """scheme://host/path for logs — query strings can carry tokens."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


async def download_url(
    url: str,
    dest_dir: Path,
    token: str,
    max_bytes: int,
    on_progress: ProgressCallback | None = None,
) -> DownloadedFile:
    """Download `url` into dest_dir/<resolved filename>, resuming on drops."""
    timeout = aiohttp.ClientTimeout(
        total=None, sock_connect=30, sock_read=SOCK_READ_TIMEOUT
    )
    headers = {"User-Agent": USER_AGENT}
    label = _log_label(url)
    started = time.monotonic()
    logger.info("download start: %s (cap %d bytes)", label, max_bytes)

    downloaded = 0
    total: int | None = None
    filename: str | None = None
    content_type: str | None = None
    path: Path | None = None
    last_exc: Exception | None = None

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            req_start = downloaded
            req_headers = (
                {"Range": f"bytes={req_start}-"} if req_start else {}
            )
            try:
                async with session.get(
                    url, headers=req_headers, allow_redirects=True
                ) as resp:
                    if resp.status == 416 and total is not None \
                            and downloaded >= total:
                        last_exc = None
                        break  # server says: you already have it all
                    if downloaded and resp.status == 200:
                        logger.warning(
                            "download %s: server ignored Range on attempt "
                            "%d — restarting from zero", label, attempt,
                        )
                        downloaded = 0
                        req_start = 0
                    elif resp.status not in (200, 206):
                        raise DownloadError(
                            f"The server answered HTTP {resp.status}."
                        )
                    if resp.status == 206:
                        if resp.content_length is not None:
                            total = req_start + resp.content_length
                    else:
                        total = resp.content_length
                    if total is not None and total > max_bytes:
                        raise FileTooLarge(
                            f"That file is {total} bytes, over the "
                            f"{max_bytes} byte limit set in .env."
                        )
                    if filename is None:
                        filename = resolve_download_filename(
                            str(resp.url),
                            resp.headers.get("Content-Disposition"),
                            resp.headers.get("Content-Type"),
                        )
                        content_type = resp.headers.get("Content-Type")
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        path = dest_dir / filename
                    mode = "ab" if (downloaded and resp.status == 206) else "wb"
                    if mode == "wb":
                        downloaded = 0
                    with open(path, mode) as fh:
                        async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                            fh.write(chunk)
                            downloaded += len(chunk)
                            if downloaded > max_bytes:
                                fh.close()
                                path.unlink(missing_ok=True)
                                raise FileTooLarge(
                                    f"Download passed the {max_bytes} byte "
                                    "limit set in .env and was aborted."
                                )
                            if on_progress is not None:
                                await on_progress(downloaded, total)
                last_exc = None
                break  # streamed to completion without an exception
            except (DownloadError, asyncio.CancelledError):
                raise
            except (aiohttp.ClientError, TimeoutError, ConnectionError) as exc:
                last_exc = exc
                logger.warning(
                    "download %s: attempt %d/%d failed at %d bytes: %r",
                    label, attempt, MAX_ATTEMPTS, downloaded, exc,
                )
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(min(2 * attempt, 10))

    if last_exc is not None:
        if path is not None:
            path.unlink(missing_ok=True)
        raise DownloadError(
            f"The connection kept dropping — gave up after {MAX_ATTEMPTS} "
            f"attempts at {downloaded} bytes. Last error: {last_exc}"
        ) from last_exc
    if path is None or filename is None:
        raise DownloadError("The download failed before it started.")

    elapsed = time.monotonic() - started
    logger.info(
        "download done: %s -> %s (%d bytes in %.1fs, %.2f MB/s)",
        label, filename, downloaded, elapsed,
        (downloaded / 1048576) / elapsed if elapsed > 0 else 0.0,
    )
    return DownloadedFile(
        path=path,
        filename=filename,
        size=downloaded,
        content_type=content_type,
    )
