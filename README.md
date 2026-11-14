# TelegramFileLinkBot

A personal Telegram bot that converts **files to download links** and
**download links back to files** — written in Python.

> Built for one annoying workflow: a file lives in Telegram and you need it
> somewhere else (or the other way round) without downloading it to your
> phone first and re-uploading it by hand.

**فارسی:** [README.fa.md](README.fa.md)

---

## What it does

| You send | Bot replies |
|---|---|
| 📎 Any file (document, video, audio, photo, voice…) | 🔗 A direct download link |
| 🔗 A direct http(s) download link | 📎 The file, as a Telegram document |

Plus:

- `/start`, `/help` — how it works
- `/myfiles` — your 10 most recent files and their links
- Live progress while it downloads from a link
- Files are stored on **your own server** — nobody else's cloud

## How it works

```
   FILE -> LINK                                LINK -> FILE
 ┌──────────┐  file   ┌──────────────┐  link   ┌──────────┐
 │ Telegram │ ──────► │  this bot +  │ ──────► │  anyone  │
 │  user    │ ◄────── │  web server  │         │ (browser,│
 └──────────┘  link   │  (one proc.) │         │  wget…)  │
                      └──────────────┘         └──────────┘
 ┌──────────┐  link   ┌──────────────┐  file   ┌──────────┐
 │ Telegram │ ──────► │  streaming   │ ──────► │ Telegram │
 │  user    │ ◄────── │  downloader  │         │  user    │
 └──────────┘  file   └──────────────┘         └──────────┘
```

One Python process runs both parts on a single asyncio event loop:

- **Bot** — `python-telegram-bot` in long-polling mode (no webhook, no
  public HTTPS endpoint needed for the bot itself)
- **Web server** — `aiohttp`, serves stored files at
  `GET /d/<token>/<filename>` where `<token>` is a random unguessable id
- **Storage** — plain files on disk under `storage/files/<token>/` with a
  small SQLite index (`storage/files.db`)

## Limits (Telegram Bot API — read this)

These are limits of Telegram's public Bot API, not of this code:

| Direction | Public Bot API | With a local Bot API server |
|---|---|---|
| Bot downloads a file from Telegram | **20 MB** | 2000 MB |
| Bot sends a file to Telegram | **50 MB** | 2000 MB |
| Bot downloads from a URL | only your disk / `MAX_URL_DOWNLOAD_MB` | same |

If a URL download is larger than 50 MB, the bot keeps the file and sends
you its download link instead of failing. To lift both Telegram-side
limits, run the official
[`telegram-bot-api`](https://github.com/tdlib/telegram-bot-api) server
locally and point `python-telegram-bot` at it
(`Application.builder().base_url(...)`) — the rest of the code is unchanged.

## Setup

### 1. Create the bot

Talk to [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the
token it gives you.

### 2. Get the code and install

```bash
git clone https://github.com/IzumiRain/TelegramFileLinkBot.git
cd TelegramFileLinkBot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
nano .env
```

| Variable | Meaning |
|---|---|
| `BOT_TOKEN` | The token from BotFather (**required**) |
| `BASE_URL` | Public address of this server — download links start with it, e.g. `http://203.0.113.10:8080` or `https://files.example.com` (**required for links to work outside this machine**) |
| `PORT` | Web server port (default `8080`) |
| `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs allowed to use the bot. **Set this** — otherwise anyone who finds the bot can store files on your server. Get your ID from [@userinfobot](https://t.me/userinfobot) |
| `STORAGE_DIR` | Where files are kept (default `./storage`) |
| `MAX_URL_DOWNLOAD_MB` | Refuse URL downloads larger than this (default `2048`) |
| `FILE_TTL_HOURS` | Auto-delete stored files after N hours; `0` = keep forever (default) |

### 4. Run

```bash
python bot.py
```

Open Telegram, message your bot, drop a file in — you'll get a link back.
Send it a link — you'll get the file back.

### Run with Docker instead

```bash
cp .env.example .env   # fill it in
docker compose up -d --build
```

### Run it 24/7 with systemd

```ini
# /etc/systemd/system/tg-file-link.service
[Unit]
Description=Telegram File Link Bot
After=network.target

[Service]
WorkingDirectory=/opt/TelegramFileLinkBot
ExecStart=/opt/TelegramFileLinkBot/.venv/bin/python bot.py
Restart=always
User=YOUR_USER

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now tg-file-link
```

## Putting links on a domain (HTTPS)

The bot's links are plain HTTP on `PORT`. For a proper domain + HTTPS,
put a reverse proxy in front and set `BASE_URL=https://files.example.com`:

```nginx
# nginx
server {
    server_name files.example.com;
    location / {
        proxy_pass http://127.0.0.1:8080;
    }
}
```

(then `certbot --nginx -d files.example.com` for the certificate)

No server/domain? Any always-on machine works — even a home PC, as long as
`BASE_URL` points at an address that can reach the bot's port (a tunnel
such as Cloudflare Tunnel or Tailscale Funnel also works).

## Security notes

- Download links are **capability URLs**: the random token in
  `/d/<token>/…` *is* the password. Don't post links publicly for files
  you care about; set `FILE_TTL_HOURS` if you want links to expire.
- Set `ALLOWED_USER_IDS` so strangers can't use your disk and bandwidth.
- Filenames are sanitised and stored paths are verified to stay inside
  the storage directory (no path traversal), in both directions.

## Project structure

```
bot.py               entry point — runs bot + web server together
app/
  config.py          environment / .env configuration + Bot API limits
  handlers.py        Telegram handlers (file->link, link->file, commands)
  downloader.py      streaming URL downloader with progress + size cap
  storage.py         disk layout + SQLite index, expiry sweep
  webserver.py       aiohttp app serving /d/<token>/<filename>
  utils.py           filename sanitising, URL extraction, size formatting
tests/
  test_utils.py      unit tests for the helpers (python -m unittest discover -s tests)
```

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall .
```
