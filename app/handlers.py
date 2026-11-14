"""Telegram handlers — the two directions of the bot, plus the owner menu.

File -> Link : user sends any file, bot stores it and replies with a
               direct download link served by the built-in web server.
Link -> File : user sends an http(s) link, bot downloads it (streaming,
               with progress) and sends it back as a Telegram document.
Admin menu   : /admin (owners only) — inline-keyboard menu to list, add
               and remove allowed users by their numeric Telegram ID.
               Changes are stored in SQLite and apply immediately.
"""
from __future__ import annotations

import asyncio
import mimetypes
import shutil
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .config import Config
from .downloader import DownloadError, download_url
from .storage import FileStore
from .updater import Updater
from .utils import extract_urls, human_size, parse_user_id, sanitize_filename

# Conversation states for the /admin menu
ADMIN_MENU, ADMIN_ADD_USER = range(2)


def _help_text(cfg: Config) -> str:
    return (
        "<b>File ⇄ Link Bot</b>\n\n"
        "📥 <b>File → Link</b>\n"
        "Send me any file (document, video, audio, photo…) and I'll give you "
        "a direct download link for it.\n\n"
        "📤 <b>Link → File</b>\n"
        "Send me a direct http(s) download link and I'll download it and "
        "send the file back to you here in Telegram.\n\n"
        "Commands:\n"
        "/start, /help — this message\n"
        "/myfiles — your 10 most recent links\n"
        "/admin — (owners) manage allowed users\n"
        "/update — (owners) check GitHub for updates\n\n"
        f"Current limits: I can receive files up to {human_size(cfg.max_download_bytes)} "
        f"and send files up to {human_size(cfg.max_upload_bytes)}"
        + (
            " (local Bot API server)."
            if cfg.use_local_bot_api
            else ". Run a local telegram-bot-api server to raise both to 2 GB (see README)."
        )
    )


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _cfg(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["config"]


def _store(context: ContextTypes.DEFAULT_TYPE) -> FileStore:
    return context.application.bot_data["store"]


def _is_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    return user is not None and user.id in _cfg(context).owner_ids


def _authorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Owners are always in. Otherwise the SQLite allow-list decides;
    when nothing is configured at all (no owners, empty list) the bot
    stays open, like the original env-only behaviour."""
    user = update.effective_user
    if user is None:
        return False
    cfg = _cfg(context)
    if user.id in cfg.owner_ids:
        return True
    allowed = _store(context).allowed_user_ids()
    if not allowed and not cfg.owner_ids:
        return True
    return user.id in allowed


async def _deny(update: Update) -> None:
    if update.effective_message:
        user = update.effective_user
        uid = user.id if user else "?"
        await update.effective_message.reply_text(
            f"⛔ This bot is private. Your Telegram ID is {uid} — "
            "ask the owner to add it from the /admin menu."
        )


class _Progress:
    """Throttled progress-message editor (Telegram hates rapid edits)."""

    def __init__(self, message, label: str):
        self._message = message
        self._label = label
        self._last = 0.0

    async def __call__(self, done: int, total: int | None) -> None:
        now = time.monotonic()
        if now - self._last < 2.0 and (total is None or done < total):
            return
        self._last = now
        if total:
            pct = done * 100 // total
            text = f"{self._label} {pct}% — {human_size(done)} / {human_size(total)}"
        else:
            text = f"{self._label} {human_size(done)} downloaded…"
        try:
            await self._message.edit_text(text)
        except Exception:
            pass  # "message is not modified" and friends — progress is cosmetic


def _pick_attachment(message):
    """Return (file_object, filename|None, size|None, kind) for the first
    supported attachment in a message, or None."""
    if message.document:
        d = message.document
        return d, d.file_name, d.file_size, "document"
    if message.video:
        v = message.video
        return v, v.file_name, v.file_size, "video"
    if message.audio:
        a = message.audio
        return a, a.file_name or a.title, a.file_size, "audio"
    if message.animation:
        a = message.animation
        return a, a.file_name, a.file_size, "animation"
    if message.voice:
        return message.voice, None, message.voice.file_size, "voice"
    if message.video_note:
        return message.video_note, None, message.video_note.file_size, "video_note"
    if message.photo:
        p = message.photo[-1]  # largest size
        return p, None, p.file_size, "photo"
    return None


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update, context):
        return await _deny(update)
    await update.effective_message.reply_text(
        _help_text(_cfg(context)), parse_mode=ParseMode.HTML
    )


async def cmd_myfiles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update, context):
        return await _deny(update)
    cfg, store = _cfg(context), _store(context)
    records = store.list_for_owner(update.effective_user.id)
    if not records:
        await update.effective_message.reply_text("You have no stored files yet.")
        return
    lines = ["<b>Your recent files:</b>"]
    for rec in records:
        link = cfg.public_link(rec.token, rec.filename)
        lines.append(f'• <a href="{link}">{rec.filename}</a> ({human_size(rec.size)})')
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


# --------------------------------------------------------------------------
# Admin menu — manage allowed users (owners only)
# --------------------------------------------------------------------------
def _admin_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👥 List allowed users", callback_data="admin:list")],
            [
                InlineKeyboardButton("➕ Add user", callback_data="admin:add"),
                InlineKeyboardButton("➖ Remove user", callback_data="admin:remove"),
            ],
            [InlineKeyboardButton("❌ Close", callback_data="admin:close")],
        ]
    )


def _admin_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    count = len(_store(context).allowed_user_ids())
    return (
        "🛠 <b>Admin menu — allowed users</b>\n\n"
        f"Currently <b>{count}</b> user(s) are allowed (besides owners).\n"
        "Pick an action:"
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _cfg(context).owner_ids:
        if update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ No owners are configured, so the admin menu is disabled. "
                "Set OWNER_IDS in .env to your own Telegram ID and restart the bot."
            )
        return ConversationHandler.END
    if not _is_owner(update, context):
        if update.effective_message:
            await update.effective_message.reply_text(
                "⛔ The admin menu is for the bot owner only."
            )
        return ConversationHandler.END
    await update.effective_message.reply_text(
        _admin_text(context),
        parse_mode=ParseMode.HTML,
        reply_markup=_admin_menu_markup(),
    )
    return ADMIN_MENU


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    if not _is_owner(update, context):
        await query.answer("⛔ Owners only.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    store = _store(context)
    data = query.data or ""

    if data == "admin:close":
        await query.edit_message_text("🛠 Admin menu closed.")
        return ConversationHandler.END

    if data == "admin:list":
        ids = sorted(store.allowed_user_ids())
        owners = sorted(_cfg(context).owner_ids)
        lines = ["👥 <b>Allowed users</b>\n"]
        lines.append("<b>Owners</b> (from OWNER_IDS, always allowed):")
        lines += [f"• <code>{uid}</code>" for uid in owners] or ["• —"]
        lines.append("\n<b>Allowed users</b> (managed here):")
        lines += [f"• <code>{uid}</code>" for uid in ids] or ["• — none yet —"]
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data="admin:menu")]]
            ),
        )
        return ADMIN_MENU

    if data == "admin:add":
        await query.edit_message_text(
            "➕ <b>Add allowed user</b>\n\n"
            "Send me the user's <b>numeric Telegram ID</b> "
            "(they can get it from @userinfobot).\n"
            "Send /cancel to go back.",
            parse_mode=ParseMode.HTML,
        )
        return ADMIN_ADD_USER

    if data == "admin:remove":
        ids = sorted(store.allowed_user_ids())
        if not ids:
            await query.edit_message_text(
                "➖ There are no allowed users to remove.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⬅️ Back", callback_data="admin:menu")]]
                ),
            )
            return ADMIN_MENU
        buttons = [
            [InlineKeyboardButton(f"➖ {uid}", callback_data=f"admin:rm:{uid}")]
            for uid in ids
        ]
        buttons.append(
            [InlineKeyboardButton("⬅️ Back", callback_data="admin:menu")]
        )
        await query.edit_message_text(
            "➖ Tap a user to remove them:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return ADMIN_MENU

    if data.startswith("admin:rm:"):
        try:
            uid = int(data.rsplit(":", 1)[1])
        except ValueError:
            return ADMIN_MENU
        removed = store.remove_allowed_user(uid)
        await query.edit_message_text(
            f"✅ User <code>{uid}</code> removed."
            if removed
            else f"User <code>{uid}</code> was not in the list.",
            parse_mode=ParseMode.HTML,
            reply_markup=_admin_menu_markup(),
        )
        return ADMIN_MENU

    # admin:menu and anything else → back to the main menu
    await query.edit_message_text(
        _admin_text(context),
        parse_mode=ParseMode.HTML,
        reply_markup=_admin_menu_markup(),
    )
    return ADMIN_MENU


async def admin_add_user_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _is_owner(update, context):
        return ConversationHandler.END
    uid = parse_user_id(update.effective_message.text or "")
    if uid is None:
        await update.effective_message.reply_text(
            "❓ That doesn't look like a numeric Telegram ID. "
            "Send just the number (e.g. 123456789), or /cancel."
        )
        return ADMIN_ADD_USER
    store = _store(context)
    added = store.add_allowed_user(
        uid, added_by=update.effective_user.id if update.effective_user else None
    )
    text = (
        f"✅ User <code>{uid}</code> added — they can use the bot now."
        if added
        else f"ℹ️ User <code>{uid}</code> is already in the allowed list."
    )
    await update.effective_message.reply_text(
        text + "\n\n" + _admin_text(context),
        parse_mode=ParseMode.HTML,
        reply_markup=_admin_menu_markup(),
    )
    return ADMIN_MENU


async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message:
        await update.effective_message.reply_text("🛠 Admin menu closed.")
    return ConversationHandler.END


async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shortcut: /adduser <telegram_id> (owners only)."""
    if not _is_owner(update, context):
        return await _deny(update)
    uid = parse_user_id(" ".join(context.args or []))
    if uid is None:
        await update.effective_message.reply_text("Usage: /adduser <telegram_id>")
        return
    added = _store(context).add_allowed_user(uid, added_by=update.effective_user.id)
    await update.effective_message.reply_text(
        f"✅ {uid} added." if added else f"ℹ️ {uid} is already allowed."
    )


async def cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shortcut: /removeuser <telegram_id> (owners only)."""
    if not _is_owner(update, context):
        return await _deny(update)
    uid = parse_user_id(" ".join(context.args or []))
    if uid is None:
        await update.effective_message.reply_text("Usage: /removeuser <telegram_id>")
        return
    removed = _store(context).remove_allowed_user(uid)
    await update.effective_message.reply_text(
        f"✅ {uid} removed." if removed else f"ℹ️ {uid} was not in the list."
    )


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shortcut: /users — list owners + allowed users (owners only)."""
    if not _is_owner(update, context):
        return await _deny(update)
    cfg, store = _cfg(context), _store(context)
    owners = ", ".join(str(i) for i in sorted(cfg.owner_ids)) or "—"
    ids = ", ".join(str(i) for i in sorted(store.allowed_user_ids())) or "—"
    await update.effective_message.reply_text(
        f"Owners: {owners}\nAllowed users: {ids}"
    )


# --------------------------------------------------------------------------
# Self-update from GitHub (owners only)
# --------------------------------------------------------------------------
def _updater(context: ContextTypes.DEFAULT_TYPE) -> Updater:
    cfg = _cfg(context)
    root = Path(__file__).resolve().parent.parent
    return Updater(root, cfg.github_token, cfg.github_repo)


async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/update — check GitHub; /update apply — pull and install it."""
    if not _is_owner(update, context):
        return await _deny(update)
    message = update.effective_message
    updater = _updater(context)
    args = [a.lower() for a in (context.args or [])]
    if args and args[0] in ("apply", "now", "install"):
        status = await message.reply_text("⬇️ Updating from GitHub…")
        report = await asyncio.to_thread(updater.apply)
        lines = report.get("log", [])
        if report.get("ok") and report.get("updated"):
            lines.append("♻️ Restart the server to run the new code.")
            await status.edit_text("✅ Update installed.\n" + "\n".join(lines))
        elif report.get("ok"):
            await status.edit_text("✅ " + "\n".join(lines))
        else:
            await status.edit_text(f"❌ Update failed: {report.get('error')}")
        return
    status = await message.reply_text("🔍 Checking GitHub for updates…")
    info = await asyncio.to_thread(updater.status, True)
    if not info.get("ok"):
        await status.edit_text(f"❌ {info.get('error')}")
    elif info.get("up_to_date"):
        await status.edit_text(
            f"✅ Up to date — running commit <code>{info['current_short']}</code>.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await status.edit_text(
            f"🆕 Update available: <code>{info['current_short']}</code> → "
            f"<code>{info['remote_short']}</code> "
            f"({info['behind']} new commit(s)).\n"
            "Send /update apply to install it.",
            parse_mode=ParseMode.HTML,
        )


# --------------------------------------------------------------------------
# File -> Link
# --------------------------------------------------------------------------
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update, context):
        return await _deny(update)
    message = update.effective_message
    picked = _pick_attachment(message)
    if picked is None:
        await message.reply_text(
            "That attachment type isn't supported — try a document, video, "
            "audio, voice message or photo."
        )
        return
    attachment, filename, size, kind = picked

    cfg, store = _cfg(context), _store(context)
    if size and size > cfg.max_download_bytes:
        hint = (
            "even with a local Bot API server."
            if cfg.use_local_bot_api
            else "Run a local telegram-bot-api server to lift this to 2 GB (see README)."
        )
        await message.reply_text(
            f"⚠️ That file is {human_size(size)}. Telegram only lets me "
            f"download files up to {human_size(cfg.max_download_bytes)} {hint}"
        )
        return

    if not filename:
        ext = mimetypes.guess_extension(attachment.mime_type or "") or ""
        if kind == "photo" and not ext:
            ext = ".jpg"
        if kind == "voice" and not ext:
            ext = ".ogg"
        if kind == "video_note" and not ext:
            ext = ".mp4"
        filename = f"{kind}_{attachment.file_unique_id}{ext}"
    filename = sanitize_filename(filename)

    status = await message.reply_text(f"⬇️ Downloading {filename} from Telegram…")
    try:
        tg_file = await context.bot.get_file(attachment.file_id)
        token = store.new_token()
        dest = store.path_for(token, filename)
        # Local Bot API on the same filesystem: get_file returns an
        # absolute local path — just copy it, no HTTP round-trip.
        src = Path(tg_file.file_path) if tg_file.file_path else None
        if (
            cfg.bot_api_local_mode
            and src is not None
            and src.is_absolute()
            and src.exists()
        ):
            await asyncio.to_thread(shutil.copyfile, src, dest)
        else:
            await tg_file.download_to_drive(str(dest))
        saved_size = dest.stat().st_size
        record = store.register(
            token, filename, saved_size,
            getattr(attachment, "mime_type", None),
            update.effective_user.id if update.effective_user else None,
        )
    except Exception as exc:
        await status.edit_text(f"❌ Failed to download that file: {exc}")
        return

    link = cfg.public_link(record.token, record.filename)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬇️ Download", url=link)]]
    )
    await status.edit_text(
        f"✅ <b>{record.filename}</b> ({human_size(record.size)})\n\n"
        f"🔗 <code>{link}</code>\n\nTap the link to copy it.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# --------------------------------------------------------------------------
# Link -> File
# --------------------------------------------------------------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update, context):
        return await _deny(update)
    message = update.effective_message
    urls = extract_urls(message.text or message.caption or "")
    if not urls:
        await message.reply_text(
            "Send me a file to turn into a link, or a direct download "
            "link to turn into a file. /help for details."
        )
        return

    cfg, store = _cfg(context), _store(context)
    url = urls[0]
    status = await message.reply_text("⬇️ Downloading from your link…")
    progress = _Progress(status, "⬇️ Downloading…")
    token = store.new_token()
    try:
        result = await download_url(
            url,
            dest_dir=store.files_dir / token,
            token=token,
            max_bytes=cfg.max_url_download_bytes,
            on_progress=progress,
        )
    except DownloadError as exc:
        await status.edit_text(f"❌ {exc}")
        return

    record = store.register(
        token, result.filename, result.size, result.content_type,
        update.effective_user.id if update.effective_user else None,
    )

    if result.size > cfg.max_upload_bytes:
        link = cfg.public_link(record.token, record.filename)
        await status.edit_text(
            f"⚠️ Downloaded <b>{record.filename}</b> ({human_size(record.size)}), "
            f"but I can only send files up to {human_size(cfg.max_upload_bytes)} "
            f"into Telegram.\n\n"
            f"Here is a download link instead:\n🔗 <code>{link}</code>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    await status.edit_text(f"⬆️ Uploading {record.filename} to Telegram…")
    try:
        with open(result.path, "rb") as fh:
            await message.reply_document(
                document=fh,
                filename=record.filename,
                caption=(
                    f"✅ {record.filename} ({human_size(record.size)})\nSource: {url}"
                )[:1024],
            )
        await status.delete()
    except Exception as exc:
        link = cfg.public_link(record.token, record.filename)
        await status.edit_text(
            f"❌ Upload to Telegram failed: {exc}\n\n"
            f"The file is stored, grab it here:\n🔗 <code>{link}</code>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


# --------------------------------------------------------------------------
# wiring
# --------------------------------------------------------------------------
def register_handlers(app: Application) -> None:
    admin_conversation = ConversationHandler(
        entry_points=[CommandHandler("admin", cmd_admin)],
        states={
            ADMIN_MENU: [CallbackQueryHandler(admin_callback, pattern=r"^admin:")],
            ADMIN_ADD_USER: [
                CallbackQueryHandler(admin_callback, pattern=r"^admin:"),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, admin_add_user_input
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", admin_cancel),
            CallbackQueryHandler(admin_callback, pattern=r"^admin:close$"),
        ],
        per_message=False,
    )
    app.add_handler(admin_conversation)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("myfiles", cmd_myfiles))
    app.add_handler(CommandHandler("adduser", cmd_adduser))
    app.add_handler(CommandHandler("removeuser", cmd_removeuser))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(MessageHandler(filters.ATTACHMENT, handle_file))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
