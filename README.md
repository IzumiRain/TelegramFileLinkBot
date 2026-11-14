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
- `/admin` — owners-only menu to add/remove allowed users right inside
  Telegram (see [Managing allowed users](#managing-allowed-users-admin-menu))
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
limits to 2 GB, run the official
[`telegram-bot-api`](https://github.com/tdlib/telegram-bot-api) server
and set `BOT_API_URL` — see
[Local Bot API server](#local-bot-api-server-2-gb-limits) below.

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
| `OWNER_IDS` | Your own Telegram ID(s) — owners can use the bot and open the `/admin` menu. **Set this** (get your ID from [@userinfobot](https://t.me/userinfobot)) |
| `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs allowed to use the bot — a first-boot seed only; afterwards manage the list from the `/admin` menu |
| `BOT_API_URL` | Address of a local `telegram-bot-api` server (e.g. `http://127.0.0.1:8081`) to raise the Telegram limits to 2 GB; empty = public Bot API |
| `PORT` | Web server port (default `8080`; on Pterodactyl the panel's `SERVER_PORT` is used automatically) |
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

## Managing allowed users (admin menu)

Set `OWNER_IDS` in `.env` to your own Telegram ID (comma-separated if
there are several owners) and restart the bot. Then, in Telegram:

- Send **`/admin`** — an inline-button menu opens:
  - **👥 List allowed users** — owners + everyone currently allowed
  - **➕ Add user** — the bot asks for a numeric Telegram ID; send it and
    that user can use the bot immediately
  - **➖ Remove user** — tap a user in the list to revoke access
- Shortcuts that do the same without the menu: `/adduser <id>`,
  `/removeuser <id>`, `/users`

The list lives in SQLite (`storage/files.db`, table `allowed_users`), so
it survives restarts. `ALLOWED_USER_IDS` in `.env` is only used to seed
it on first boot. Owners are always allowed and can't be removed from
the menu — change `OWNER_IDS` and restart to change owners. People who
are not allowed get a reply showing their own Telegram ID, so they can
send it to you to be added.

## Local Bot API server (2 GB limits)

Run Telegram's own [`telegram-bot-api`](https://github.com/tdlib/telegram-bot-api)
server and point the bot at it — both Telegram-side limits become
2000 MB. You need an `api_id` / `api_hash` pair from
[my.telegram.org](https://my.telegram.org) → *API development tools*.

Two ways to run it:

**A. Same machine/container as the bot (e.g. inside the DanBot server).**
Put the `telegram-bot-api` binary at `bin/telegram-bot-api`, set
`TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in `.env`, and `start.sh` will
launch it automatically (port `BOT_API_PORT`, default 8081) and set
`BOT_API_URL` + `BOT_API_LOCAL_MODE=1` for the bot. Because both share a
filesystem, files the bot receives are copied locally instead of being
downloaded over HTTP.

**B. Separate server.** Run `telegram-bot-api` wherever you like
(`--local` flag included), then set in the bot's `.env`:

```ini
BOT_API_URL=http://<that-server>:8081
BOT_API_LOCAL_MODE=0
```

One bot token can be logged in on only one Bot API server at a time —
when you first switch to a local server, the bot is logged out from the
public API automatically (and back when you remove `BOT_API_URL`).

## Deploy on DanBot Hosting (Pterodactyl, AIO egg)

[DanBot Hosting](https://danbot.host) runs on Pterodactyl with an
all-in-one (AIO) egg whose only setting is a free-form **Startup
Command** — `start.sh` in this repo is built for exactly that:

1. Create a server with the **AIO** egg and clone this repo into it
   (panel file manager / SFTP, or `git clone` from the console).
2. Create `.env` from `.env.example` and fill in at least `BOT_TOKEN`,
   `OWNER_IDS` (your Telegram ID) and `BASE_URL`:
   `BASE_URL=http://<node-address>:<your allocated port>` — the port is
   the one the panel assigned to the server; the bot listens on it
   automatically (Pterodactyl passes it as `SERVER_PORT`).
3. In the panel's **Startup** tab set the Startup Command to:

   ```
   bash start.sh
   ```

4. Start the server. `start.sh` creates the virtualenv, installs
   dependencies, optionally starts the local Bot API server (option A
   above), prints the egg's *SERVER MARKED AS RUNNING* banner, and runs
   the bot.
5. Set `GIT_PULL=1` in `.env` if you want each restart to `git pull`
   the latest code first.

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
- Set `OWNER_IDS` (and add people via `/admin`) so strangers can't use
  your disk and bandwidth.
- Filenames are sanitised and stored paths are verified to stay inside
  the storage directory (no path traversal), in both directions.

## Project structure

```
bot.py               entry point — runs bot + web server together
start.sh             Pterodactyl/DanBot (AIO egg) startup script
app/
  config.py          environment / .env configuration + Bot API limits
  handlers.py        Telegram handlers (file->link, link->file, /admin menu)
  downloader.py      streaming URL downloader with progress + size cap
  storage.py         disk layout + SQLite index, allow-list, expiry sweep
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
