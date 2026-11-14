"""Configuration from environment variables / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

# Telegram Bot API limits (public api.telegram.org). A local
# telegram-bot-api server raises these to 2000 MB — see README.
BOT_API_MAX_DOWNLOAD = 20 * 1024 * 1024  # getFile: files up to 20 MB
BOT_API_MAX_UPLOAD = 50 * 1024 * 1024  # sendDocument: files up to 50 MB
LOCAL_BOT_API_MAX = 2000 * 1024 * 1024  # local server: up to 2000 MB both ways


def read_version() -> str:
    """App version from the VERSION file at the project root."""
    try:
        return (
            (Path(__file__).resolve().parent.parent / "VERSION")
            .read_text(encoding="utf-8")
            .strip()
            or "dev"
        )
    except OSError:
        return "dev"


def _parse_id_list(raw: str, var_name: str) -> set[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                print(f"[config] ignoring non-numeric {var_name} entry: {part!r}")
    return ids


@dataclass
class Config:
    bot_token: str
    base_url: str
    host: str = "0.0.0.0"
    port: int = 8080
    storage_dir: Path = Path("./storage")
    # Seed for the allow-list (stored in SQLite afterwards and manageable
    # from the in-bot /admin menu). Owners are always allowed and are the
    # only ones who can open that menu.
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    owner_ids: frozenset[int] = field(default_factory=frozenset)
    # Local telegram-bot-api server, e.g. http://127.0.0.1:8081
    # Empty = use the public api.telegram.org.
    bot_api_url: str = ""
    # True only when the bot and the local bot-api server share a
    # filesystem (same machine/container): file downloads become local
    # copies and uploads can reference local paths.
    bot_api_local_mode: bool = False
    max_url_download_mb: int = 2048
    file_ttl_hours: int = 0  # 0 = keep files forever
    # GitHub access for the updater. The repo is private, so a token is
    # needed for the installer/updater to clone/pull without interaction.
    github_token: str = ""
    github_repo: str = "IzumiRain/TelegramFileLinkBot"
    auto_update: bool = False  # check & apply updates on start (start.sh)
    # Web admin panel (/admin). Empty password = panel disabled.
    web_admin_password: str = ""
    env_file: Path = Path(".env")

    @property
    def max_url_download_bytes(self) -> int:
        return self.max_url_download_mb * 1024 * 1024

    @property
    def use_local_bot_api(self) -> bool:
        return bool(self.bot_api_url)

    @property
    def max_download_bytes(self) -> int:
        """Largest file this bot can receive from Telegram."""
        return LOCAL_BOT_API_MAX if self.use_local_bot_api else BOT_API_MAX_DOWNLOAD

    @property
    def max_upload_bytes(self) -> int:
        """Largest file this bot can send into Telegram."""
        return LOCAL_BOT_API_MAX if self.use_local_bot_api else BOT_API_MAX_UPLOAD

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
        # Listening port, most specific first: APP_PORT is the explicit
        # setting (installer / .env / panel), then PORT, then the port
        # Pterodactyl (DanBot) injects as SERVER_PORT.
        port = int(
            os.getenv("APP_PORT")
            or os.getenv("PORT")
            or os.getenv("SERVER_PORT")
            or "8080"
        )
        base_url = os.getenv("BASE_URL", "").strip().rstrip("/")
        if not base_url:
            base_url = f"http://127.0.0.1:{port}"
            print(
                "[config] BASE_URL is not set — download links will point to "
                f"{base_url} and only work on this machine. Set BASE_URL to "
                "your server's public address (IP or domain) in .env."
            )
        owners = _parse_id_list(os.getenv("OWNER_IDS", ""), "OWNER_IDS")
        allowed = _parse_id_list(
            os.getenv("ALLOWED_USER_IDS", ""), "ALLOWED_USER_IDS"
        )
        bot_api_url = os.getenv("BOT_API_URL", "").strip().rstrip("/")
        return cls(
            bot_token=token,
            base_url=base_url,
            host=os.getenv("HOST", "0.0.0.0"),
            port=port,
            storage_dir=Path(os.getenv("STORAGE_DIR", "./storage")),
            allowed_user_ids=frozenset(allowed),
            owner_ids=frozenset(owners),
            bot_api_url=bot_api_url,
            bot_api_local_mode=os.getenv("BOT_API_LOCAL_MODE", "").strip()
            in ("1", "true", "yes"),
            max_url_download_mb=int(os.getenv("MAX_URL_DOWNLOAD_MB", "2048")),
            file_ttl_hours=int(os.getenv("FILE_TTL_HOURS", "0")),
            github_token=os.getenv("GITHUB_TOKEN", "").strip(),
            github_repo=os.getenv(
                "GITHUB_REPO", "IzumiRain/TelegramFileLinkBot"
            ).strip(),
            auto_update=os.getenv("AUTO_UPDATE", "").strip()
            in ("1", "true", "yes"),
            web_admin_password=os.getenv("WEB_ADMIN_PASSWORD", ""),
            env_file=Path(os.getenv("ENV_FILE", ".env")),
        )
