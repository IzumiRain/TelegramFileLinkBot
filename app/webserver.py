"""HTTP server: download links + the web admin panel.

Runs in the same process/event loop as the Telegram bot (aiohttp).
Routes:
    GET  /health                    -> {"status": "ok"}
    GET  /d/<token>[/<filename>]    -> the stored file, as an attachment
    GET  /admin                     -> web admin panel (single-page GUI)
    POST /admin/api/login|logout    -> panel session (WEB_ADMIN_PASSWORD)
    GET  /admin/api/status          -> version, limits, counts
    GET|POST|DELETE /admin/api/users[/<id>]   -> the allow-list
    GET|DELETE /admin/api/files[/<token>]     -> stored files
    GET|POST /admin/api/settings    -> read/save .env settings
    POST /admin/api/update/check|apply        -> GitHub self-update

The panel is disabled unless WEB_ADMIN_PASSWORD is set in .env.
Sessions are random tokens kept in memory (a restart logs everyone out).
"""
from __future__ import annotations

import asyncio
import hmac
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from .config import Config, read_version
from .envfile import parse_env_file, update_env_file
from .storage import FileStore
from .updater import Updater
from .utils import parse_user_id

_ADMIN_HTML = Path(__file__).with_name("admin_ui.html")
_SECRET_KEYS = {"BOT_TOKEN", "GITHUB_TOKEN", "WEB_ADMIN_PASSWORD"}
_EDITABLE_KEYS = {
    "BASE_URL", "APP_PORT", "OWNER_IDS", "BOT_API_URL", "BOT_API_LOCAL_MODE",
    "BOT_API_PORT", "MAX_URL_DOWNLOAD_MB", "FILE_TTL_HOURS", "AUTO_UPDATE",
    "GIT_PULL", "GITHUB_REPO", "GITHUB_TOKEN", "BOT_TOKEN",
    "WEB_ADMIN_PASSWORD", "STORAGE_DIR",
}


def create_web_app(
    store: FileStore, config: Config | None = None
) -> web.Application:
    app = web.Application()
    app["store"] = store
    app["config"] = config
    app["sessions"] = set()
    app["started_at"] = time.time()
    app["update_running"] = False
    app.router.add_get("/health", _health)
    app.router.add_get("/d/{token}", _serve_file)
    app.router.add_get("/d/{token}/{filename:.*}", _serve_file)
    if config is not None:
        app.router.add_get("/admin", _admin_page)
        app.router.add_post("/admin/api/login", _api_login)
        app.router.add_post("/admin/api/logout", _api_logout)
        app.router.add_get("/admin/api/status", _api_status)
        app.router.add_get("/admin/api/users", _api_users_list)
        app.router.add_post("/admin/api/users", _api_users_add)
        app.router.add_delete(r"/admin/api/users/{user_id:\d+}", _api_users_remove)
        app.router.add_get("/admin/api/files", _api_files_list)
        app.router.add_delete("/admin/api/files/{token}", _api_files_delete)
        app.router.add_get("/admin/api/settings", _api_settings_get)
        app.router.add_post("/admin/api/settings", _api_settings_save)
        app.router.add_post("/admin/api/update/check", _api_update_check)
        app.router.add_post("/admin/api/update/apply", _api_update_apply)
    return app


# ---------------------------------------------------------------------------
# download links
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# admin panel — auth
# ---------------------------------------------------------------------------
def _panel_enabled(request: web.Request) -> bool:
    cfg: Config = request.app["config"]
    return bool(cfg and cfg.web_admin_password)


def _authed(request: web.Request) -> bool:
    token = request.cookies.get("tflb_admin", "")
    return bool(token) and token in request.app["sessions"]


def _require_auth(request: web.Request) -> None:
    if not _panel_enabled(request):
        raise web.HTTPForbidden(
            text="Admin panel is disabled — set WEB_ADMIN_PASSWORD in .env."
        )
    if not _authed(request):
        raise web.HTTPUnauthorized(text="Login required.")


async def _admin_page(request: web.Request) -> web.Response:
    if not _panel_enabled(request):
        return web.Response(
            text=(
                "<h1>Admin panel disabled</h1><p>Set "
                "<code>WEB_ADMIN_PASSWORD</code> in the bot's <code>.env</code> "
                "and restart to enable the web panel.</p>"
            ),
            content_type="text/html",
        )
    return web.Response(
        text=_ADMIN_HTML.read_text(encoding="utf-8"), content_type="text/html"
    )


async def _api_login(request: web.Request) -> web.Response:
    if not _panel_enabled(request):
        raise web.HTTPForbidden(text="Admin panel is disabled.")
    cfg: Config = request.app["config"]
    body = await request.json()
    if not hmac.compare_digest(
        str(body.get("password", "")), cfg.web_admin_password
    ):
        raise web.HTTPUnauthorized(text="Wrong password.")
    token = secrets.token_urlsafe(32)
    request.app["sessions"].add(token)
    response = web.json_response({"ok": True})
    response.set_cookie(
        "tflb_admin", token, httponly=True, samesite="Lax", max_age=7 * 24 * 3600
    )
    return response


async def _api_logout(request: web.Request) -> web.Response:
    request.app["sessions"].discard(request.cookies.get("tflb_admin", ""))
    response = web.json_response({"ok": True})
    response.del_cookie("tflb_admin")
    return response


# ---------------------------------------------------------------------------
# admin panel — API
# ---------------------------------------------------------------------------
async def _api_status(request: web.Request) -> web.Response:
    _require_auth(request)
    cfg: Config = request.app["config"]
    store: FileStore = request.app["store"]
    commit = None
    try:
        info = await asyncio.to_thread(
            Updater(
                Path(__file__).resolve().parent.parent,
                cfg.github_token,
                cfg.github_repo,
            ).status,
            False,
        )
        commit = info.get("current_short")
    except Exception:
        pass
    return web.json_response(
        {
            "version": read_version(),
            "commit": commit,
            "base_url": cfg.base_url,
            "port": cfg.port,
            "local_bot_api": cfg.use_local_bot_api,
            "max_download_bytes": cfg.max_download_bytes,
            "max_upload_bytes": cfg.max_upload_bytes,
            "files_count": store.count_files(),
            "allowed_count": len(store.allowed_user_ids()),
            "uptime_s": int(time.time() - request.app["started_at"]),
        }
    )


async def _api_users_list(request: web.Request) -> web.Response:
    _require_auth(request)
    cfg: Config = request.app["config"]
    store: FileStore = request.app["store"]
    return web.json_response(
        {
            "owners": sorted(cfg.owner_ids),
            "allowed": sorted(store.allowed_user_ids()),
        }
    )


async def _api_users_add(request: web.Request) -> web.Response:
    _require_auth(request)
    body = await request.json()
    uid = parse_user_id(str(body.get("user_id", "")))
    if uid is None:
        return web.json_response(
            {"error": "That is not a valid numeric Telegram user ID."}, status=400
        )
    added = request.app["store"].add_allowed_user(uid)
    return web.json_response({"ok": True, "added": added, "user_id": uid})


async def _api_users_remove(request: web.Request) -> web.Response:
    _require_auth(request)
    removed = request.app["store"].remove_allowed_user(
        int(request.match_info["user_id"])
    )
    return web.json_response({"ok": True, "removed": removed})


async def _api_files_list(request: web.Request) -> web.Response:
    _require_auth(request)
    cfg: Config = request.app["config"]
    store: FileStore = request.app["store"]
    files = [
        {
            "token": rec.token,
            "filename": rec.filename,
            "size": rec.size,
            "owner_id": rec.owner_id,
            "created_at": rec.created_at,
            "link": cfg.public_link(rec.token, rec.filename),
        }
        for rec in store.list_recent(100)
    ]
    return web.json_response({"files": files})


async def _api_files_delete(request: web.Request) -> web.Response:
    _require_auth(request)
    store: FileStore = request.app["store"]
    record = store.get(request.match_info["token"])
    if record is None:
        raise web.HTTPNotFound(text="Unknown token.")
    store.delete(record)
    return web.json_response({"ok": True})


async def _api_settings_get(request: web.Request) -> web.Response:
    _require_auth(request)
    cfg: Config = request.app["config"]
    values = parse_env_file(cfg.env_file)
    visible = {k: v for k, v in values.items() if k not in _SECRET_KEYS}
    secrets_set = {k: bool(values.get(k)) for k in sorted(_SECRET_KEYS)}
    return web.json_response({"values": visible, "secrets_set": secrets_set})


async def _api_settings_save(request: web.Request) -> web.Response:
    _require_auth(request)
    cfg: Config = request.app["config"]
    body = await request.json()
    updates = body.get("updates", {})
    if not isinstance(updates, dict):
        return web.json_response({"error": "updates must be an object"}, status=400)
    clean: dict[str, str] = {}
    for key, value in updates.items():
        if key not in _EDITABLE_KEYS:
            return web.json_response({"error": f"{key} is not editable"}, status=400)
        value = str(value)
        if key == "APP_PORT":
            try:
                port = int(value)
            except ValueError:
                return web.json_response(
                    {"error": "APP_PORT must be a number"}, status=400
                )
            if not 1 <= port <= 65535:
                return web.json_response(
                    {"error": "APP_PORT must be between 1 and 65535"}, status=400
                )
        clean[key] = value
    await asyncio.to_thread(update_env_file, cfg.env_file, clean)
    return web.json_response({"ok": True, "restart_required": True})


def _make_updater(request: web.Request) -> Updater:
    cfg: Config = request.app["config"]
    return Updater(
        Path(__file__).resolve().parent.parent, cfg.github_token, cfg.github_repo
    )


async def _api_update_check(request: web.Request) -> web.Response:
    _require_auth(request)
    info = await asyncio.to_thread(_make_updater(request).status, True)
    return web.json_response(info)


async def _api_update_apply(request: web.Request) -> web.Response:
    _require_auth(request)
    if request.app["update_running"]:
        return web.json_response(
            {"ok": False, "error": "An update is already running."}, status=409
        )
    request.app["update_running"] = True
    try:
        report = await asyncio.to_thread(_make_updater(request).apply)
    finally:
        request.app["update_running"] = False
    return web.json_response(report)
