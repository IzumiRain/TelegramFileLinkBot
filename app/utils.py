"""Small dependency-free helpers: filenames, sizes, URL extraction."""
from __future__ import annotations

import mimetypes
import re
import unicodedata
from urllib.parse import unquote, urlparse

_URL_RE = re.compile(r"https?://[^\s<>\[\]\"']+", re.IGNORECASE)
_BAD_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_MAX_NAME_LEN = 180


def sanitize_filename(name: str | None, fallback: str = "file") -> str:
    """Make a filename safe to store on disk and serve over HTTP.

    Strips path separators and control characters (path-traversal safe),
    collapses whitespace, and caps the length while keeping the extension.
    """
    name = (name or "").strip()
    name = unicodedata.normalize("NFC", name)
    name = _BAD_CHARS_RE.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name or name in {".", ".."}:
        return fallback
    if len(name) > _MAX_NAME_LEN:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 10:
            name = stem[: _MAX_NAME_LEN - len(ext) - 1] + "." + ext
        else:
            name = name[:_MAX_NAME_LEN]
    return name


def filename_from_url(url: str) -> str | None:
    """Best-effort filename from the URL path (query strings ignored)."""
    path = unquote(urlparse(url).path)
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return last or None


def filename_from_content_disposition(header: str | None) -> str | None:
    """Parse `Content-Disposition`, including RFC 5987 filename* form."""
    if not header:
        return None
    match = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)", header)
    if match:
        return unquote(match.group(1).strip().strip('"'))
    match = re.search(r'filename\s*=\s*"([^"]+)"', header)
    if match:
        return match.group(1)
    match = re.search(r"filename\s*=\s*([^;]+)", header)
    if match:
        return match.group(1).strip()
    return None


def resolve_download_filename(
    url: str,
    content_disposition: str | None,
    content_type: str | None,
) -> str:
    """Decide the final filename for a URL download, in priority order:
    Content-Disposition header → URL path → generic name + extension
    guessed from the Content-Type.
    """
    ext = ""
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
    for candidate in (
        filename_from_content_disposition(content_disposition),
        filename_from_url(url),
    ):
        if candidate:
            candidate = sanitize_filename(candidate)
            # A name with no extension (e.g. /download?id=3 endpoints) gets
            # one from the Content-Type, so players/Telegram type it right.
            if ext and "." not in candidate:
                candidate += ext
            return candidate
    return f"download{ext}" if ext else "download.bin"


def extract_urls(text: str | None) -> list[str]:
    """All http(s) URLs in a text, trailing sentence punctuation trimmed."""
    if not text:
        return []
    urls = []
    for raw in _URL_RE.findall(text):
        urls.append(raw.rstrip(").,;!?»"))
    return urls


def human_size(num_bytes: int | float | None) -> str:
    """Format a byte count the way humans (and Telegram clients) expect."""
    if num_bytes is None:
        return "unknown size"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"
