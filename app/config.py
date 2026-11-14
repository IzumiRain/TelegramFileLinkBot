"""Configuration from environment variables / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

# Telegram Bot API limits (public api.telegram.org). A self-hosted
# telegram-bot-api server raises these to 2000 MB — see README.
BOT_API_MAX_DOWNLOAD = 20 * 1024 * 1024  # getFile: files up to 20 MB
BOT_API_MAX_UPLOAD = 50 * 1024 * 1024  # sendDocument: files up to 50 MB


@dataclass
class Config:
    bot_token: str
    base_url: str
    host: str = "0.0.0.0"
    port: int = 8080
    storage_dir: Path = Path("./storage")
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    max_url_download_mb: int = 2048
    file_ttl_hours: int = 0  # 0 = keep files forever

    @property
    def max_url_download_bytes(self) -> int:
        return self.max_url_download_mb * 1024 * 1024

    def public_link(self, token: str, filename: str) -> str:
        """The download link handed to the user for a stored file."""
        return f"{self.base_url}/d/{token}/{quote(filename)}"

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise SystemExit(
                "BOT_TOKEN is missing. Copy .env.example to .env and put the "
                "token you got from @BotFather there."
            )
        port = int(os.getenv("PORT", "8080"))
        base_url = os.getenv("BASE_URL", "").strip().rstrip("/")
        if not base_url:
            base_url = f"http://127.0.0.1:{port}"
            print(
                "[config] BASE_URL is not set — download links will point to "
                f"{base_url} and only work on this machine. Set BASE_URL to "
                "your server's public address (IP or domain) in .env."
            )
        allowed: set[int] = set()
        for part in os.getenv("ALLOWED_USER_IDS", "").split(","):
            part = part.strip()
            if part:
                try:
                    allowed.add(int(part))
                except ValueError:
                    print(f"[config] ignoring non-numeric ALLOWED_USER_IDS entry: {part!r}")
        return cls(
            bot_token=token,
            base_url=base_url,
            host=os.getenv("HOST", "0.0.0.0"),
            port=port,
            storage_dir=Path(os.getenv("STORAGE_DIR", "./storage")),
            allowed_user_ids=frozenset(allowed),
            max_url_download_mb=int(os.getenv("MAX_URL_DOWNLOAD_MB", "2048")),
            file_ttl_hours=int(os.getenv("FILE_TTL_HOURS", "0")),
        )
