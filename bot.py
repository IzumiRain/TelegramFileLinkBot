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

    application = Application.builder().token(config.bot_token).build()
    application.bot_data["config"] = config
    application.bot_data["store"] = store
    register_handlers(application)

    # Web server (download links) on the same event loop.
    runner = web.AppRunner(create_web_app(store))
    await runner.setup()
    site = web.TCPSite(runner, config.host, config.port)
    await site.start()
    print(f"[web] download server listening on {config.host}:{config.port}")
    print(f"[web] public base URL for links: {config.base_url}")

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
