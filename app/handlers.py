"""Telegram handlers — the two directions of the bot.

File -> Link : user sends any file, bot stores it and replies with a
               direct download link served by the built-in web server.
Link -> File : user sends an http(s) link, bot downloads it (streaming,
               with progress) and sends it back as a Telegram document.
"""
from __future__ import annotations

import mimetypes
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import BOT_API_MAX_DOWNLOAD, BOT_API_MAX_UPLOAD, Config
from .downloader import DownloadError, download_url
from .storage import FileStore
from .utils import extract_urls, human_size, sanitize_filename

HELP_TEXT = (
    "<b>File ⇄ Link Bot</b>\n\n"
    "📥 <b>File → Link</b>\n"
    "Send me any file (document, video, audio, photo…) and I'll give you "
    "a direct download link for it.\n\n"
    "📤 <b>Link → File</b>\n"
    "Send me a direct http(s) download link and I'll download it and "
    "send the file back to you here in Telegram.\n\n"
    "Commands:\n"
    "/start, /help — this message\n"
    "/myfiles — your 10 most recent links\n\n"
    f"Bot API limits: I can receive files up to {human_size(BOT_API_MAX_DOWNLOAD)} "
    f"and send files up to {human_size(BOT_API_MAX_UPLOAD)}. "
    "See the README for the self-hosted Bot API server trick to raise both."
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _cfg(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["config"]


def _store(context: ContextTypes.DEFAULT_TYPE) -> FileStore:
    return context.application.bot_data["store"]


def _authorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    allowed = _cfg(context).allowed_user_ids
    if not allowed:
        return True
    user = update.effective_user
    return user is not None and user.id in allowed


async def _deny(update: Update) -> None:
    if update.effective_message:
        user = update.effective_user
        uid = user.id if user else "?"
        await update.effective_message.reply_text(
            f"⛔ This bot is private. Your Telegram ID is {uid} — "
            "ask the owner to add it to ALLOWED_USER_IDS."
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
        HELP_TEXT, parse_mode=ParseMode.HTML
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

    if size and size > BOT_API_MAX_DOWNLOAD:
        await message.reply_text(
            f"⚠️ That file is {human_size(size)}. The public Telegram Bot API "
            f"only lets bots download files up to {human_size(BOT_API_MAX_DOWNLOAD)}. "
            "Run a local telegram-bot-api server to lift this to 2 GB (see README)."
        )
        return

    cfg, store = _cfg(context), _store(context)
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

    if result.size > BOT_API_MAX_UPLOAD:
        link = cfg.public_link(record.token, record.filename)
        await status.edit_text(
            f"⚠️ Downloaded <b>{record.filename}</b> ({human_size(record.size)}), "
            f"but Telegram bots can only send files up to "
            f"{human_size(BOT_API_MAX_UPLOAD)} through the public Bot API.\n\n"
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
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("myfiles", cmd_myfiles))
    app.add_handler(MessageHandler(filters.ATTACHMENT, handle_file))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
