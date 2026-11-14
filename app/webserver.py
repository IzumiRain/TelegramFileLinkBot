"""HTTP server that turns stored files back into download links.

Runs in the same process/event loop as the Telegram bot (aiohttp).
Routes:
    GET /health                 -> {"status": "ok"}
    GET /d/<token>              -> the file, as an attachment
    GET /d/<token>/<filename>   -> same; the filename segment is cosmetic
                                   (nice links), the token is what counts
"""
from __future__ import annotations

from urllib.parse import quote

from aiohttp import web

from .storage import FileStore


def create_web_app(store: FileStore) -> web.Application:
    app = web.Application()
    app["store"] = store
    app.router.add_get("/health", _health)
    app.router.add_get("/d/{token}", _serve_file)
    app.router.add_get("/d/{token}/{filename:.*}", _serve_file)
    return app


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def _serve_file(request: web.Request) -> web.Response:
    store: FileStore = request.app["store"]
    record = store.get(request.match_info["token"])
    if record is None:
        raise web.HTTPNotFound(text="File not found (unknown or expired link).")
    try:
        path = store.absolute_path(record)
    except ValueError:
        raise web.HTTPNotFound(text="File not found.")
    if not path.is_file():
        raise web.HTTPNotFound(text="File not found (already deleted).")
    disposition = f"attachment; filename*=UTF-8''{quote(record.filename)}"
    return web.FileResponse(path, headers={"Content-Disposition": disposition})
