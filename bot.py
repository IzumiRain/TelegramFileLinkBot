#!/usr/bin/env python3
"""TelegramFileLinkBot — entry point.

Runs the Telegram bot (long polling) and the file-serving web server
in one process, on one asyncio event loop.

    File -> Link : send the bot a file, get a direct download link
    Link -> File : send the bot a URL,   get the file back in Telegram

Setup: copy .env.example to .env, put in your BOT_TOKEN and BASE_URL,
then run `python bot.py`. See README.md for the full guide.
"""
from __future__ import annotations

import asyncio
import signal

from aiohttp import web
from telegram.ext import Application
from telegram.request import HTTPXRequest

from app.config import Config
from app.handlers import register_handlers
from app.storage import FileStore
from app.webserver import create_web_app


async def _cleanup_loop(store: FileStore, ttl_hours: int) -> None:
    """Hourly sweep of expired files (only when FILE_TTL_HOURS > 0)."""
    while True:
        await asyncio.sleep(3600)
        removed = store.delete_expired(ttl_hours)
        if removed:
            print(f"[cleanup] removed {removed} expired file(s)")


async def _run() -> None:
    config = Config.from_env()
    store = FileStore(config.storage_dir)
    # ALLOWED_USER_IDS from .env is only a seed: the live allow-list lives
    # in SQLite and is managed from the in-bot /admin menu (owners only).
    store.seed_allowed_users(config.allowed_user_ids)
    if config.owner_ids:
        print(f"[bot] owners (admin menu): {sorted(config.owner_ids)}")
    else:
        print("[bot] OWNER_IDS is not set — the /admin menu is disabled.")
    print(f"[bot] allowed users: {sorted(store.allowed_user_ids())}")

    # Generous request timeouts: PTB's defaults (5 s read/write) kill
    # large-file transfers. A local Bot API server in --local mode only
    # answers getFile after it has pulled the WHOLE file from Telegram's
    # servers (700 MB–2 GB can take minutes), and uploading a big file
    # back has the same problem — so the bot must be willing to wait.
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=1800.0,
        write_timeout=1800.0,
        pool_timeout=30.0,
    )
    updates_request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=30.0,
    )
    builder = (
        Application.builder()
        .token(config.bot_token)
        .request(request)
        .get_updates_request(updates_request)
    )
    if config.use_local_bot_api:
        builder = builder.base_url(f"{config.bot_api_url}/bot").base_file_url(
            f"{config.bot_api_url}/file/bot"
        )
        if config.bot_api_local_mode:
            builder = builder.local_mode(True)
        print(f"[bot] using local Bot API server at {config.bot_api_url} "
              f"(limits up to 2 GB, local_mode={config.bot_api_local_mode})")
    application = builder.build()
    application.bot_data["config"] = config
    application.bot_data["store"] = store
    register_handlers(application)

    # Web server (download links + admin panel) on the same event loop.
    runner = web.AppRunner(create_web_app(store, config))
    await runner.setup()
    site = web.TCPSite(runner, config.host, config.port)
    await site.start()
    print(f"[web] download server listening on {config.host}:{config.port}")
    print(f"[web] public base URL for links: {config.base_url}")
    if config.web_admin_password:
        print(f"[web] admin panel enabled: {config.base_url}/admin")
    else:
        print("[web] admin panel disabled (set WEB_ADMIN_PASSWORD to enable)")

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    me = await application.bot.get_me()
    print(f"[bot] @{me.username} is running — send it a file or a link.")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # e.g. Windows
            pass

    cleanup_task = None
    if config.file_ttl_hours > 0:
        cleanup_task = asyncio.create_task(
            _cleanup_loop(store, config.file_ttl_hours)
        )

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        print("[bot] shutting down…")
        if cleanup_task:
            cleanup_task.cancel()
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await runner.cleanup()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
