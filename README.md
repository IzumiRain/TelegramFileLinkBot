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

### One-line install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/IzumiRain/TelegramFileLinkBot/main/install.sh)
```

(no `curl`? `bash <(wget -qO- https://raw.githubusercontent.com/IzumiRain/TelegramFileLinkBot/main/install.sh)`.)

That downloads and runs the interactive installer described below —
it clones the repo for you. No shell at all (panel-only hosts like
Botkeep)? Skip to
[Hosting without a shell](docs/hosting-without-shell.md).

### The easy way — the installer

```bash
git clone https://github.com/IzumiRain/TelegramFileLinkBot.git
cd TelegramFileLinkBot
bash install.sh
```

The installer asks you everything it needs — **bot token**, **owner
Telegram ID**, **app port**, **base URL**, whether to enable a **local
Bot API server** (and its api id/hash), an optional **GitHub token**
(so the updater can pull this private repo) and an optional **web panel
password** — writes `.env`, installs dependencies into `.venv`, and
offers to start the bot. From then on, starting is just:

```bash
bash start.sh
```

Prefer doing it by hand? Then:

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
| `APP_PORT` | The port the app listens on — fully custom (e.g. `2020`, `62001`). Priority: `APP_PORT` > `PORT` > Pterodactyl's `SERVER_PORT` > `8080` |
| `GITHUB_TOKEN` | Token the installer/updater use to clone & pull this **private** repo without prompting |
| `AUTO_UPDATE` | `1` = check GitHub and apply updates on every start (via `start.sh`) |
| `WEB_ADMIN_PASSWORD` | Password for the web admin panel at `/admin`; empty = panel disabled |
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

## Updating

The bot can update itself from GitHub (fast-forward only; local changes
to tracked files are never overwritten):

- **CLI:** `bash update.sh` checks, `bash update.sh apply` installs.
- **Telegram:** owners send `/update` to check, `/update apply` to install.
- **Web panel:** the *Update* card does both, with a log.
- **Automatically:** set `AUTO_UPDATE=1` and every `bash start.sh` run
  updates first.

Because the repo is private, put a `GITHUB_TOKEN` in `.env` (the
installer asks for one) — fetches then authenticate with it; the token
is never written into the git remote. After an update, restart the
server so the new code runs.

## Web admin panel (GUI)

Set `WEB_ADMIN_PASSWORD` in `.env` (the installer asks) and open
`<BASE_URL>/admin`. After logging in you get:

- **Overview** — version, commit, limits, file/user counts, uptime
- **Update** — check GitHub and install updates from the browser
- **Allowed users** — the same list the Telegram `/admin` menu manages
- **Settings** — edit `.env` (base URL, app port, owners, Bot API,
  tokens…) from the browser; applied on restart
- **Stored files** — browse, open and delete stored files

The panel is a single self-contained page (no external assets), served
by the bot's own web server. With no password set it stays disabled.

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

## Hosting without a shell (Botkeep & friends)

Panel-only application hosts — no terminal, just a repo/ZIP, a start
command and environment-variable forms — work fine too: the bot reads
all of its configuration from the environment. Full walkthrough,
including Botkeep specifics, disk limits and what doesn't work there
(no local Bot API server, updates via the panel's GitHub tab):
**[docs/hosting-without-shell.md](docs/hosting-without-shell.md)**.

## Deploy on DanBot Hosting (Pterodactyl, AIO egg)

[DanBot Hosting](https://danbot.host) runs on Pterodactyl with an
all-in-one (AIO) egg whose only setting is a free-form **Startup
Command** — `start.sh` in this repo is built for exactly that:

1. Create a server with the **AIO** egg and clone this repo into it
   (panel file manager / SFTP, or `git clone` from the console).
2. Run `bash install.sh` once in the console — it asks for everything
   and writes `.env` for you. Or create `.env` from `.env.example` by
   hand and fill in at least `BOT_TOKEN`,
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
install.sh           interactive installer (asks everything, writes .env)
start.sh             Pterodactyl/DanBot (AIO egg) startup script
update.sh            self-update from GitHub (check / apply)
VERSION              current version
app/
  config.py          environment / .env configuration + Bot API limits
  handlers.py        Telegram handlers (file->link, link->file, /admin, /update)
  downloader.py      streaming URL downloader with progress + size cap
  storage.py         disk layout + SQLite index, allow-list, expiry sweep
  webserver.py       aiohttp app: /d/<token> downloads + /admin panel
  admin_ui.html      the web admin panel (single-page GUI)
  updater.py         git-based self-updater (token-authenticated fetch)
  envfile.py         .env reader/writer that preserves comments
  utils.py           filename sanitising, URL extraction, size formatting
tests/               unit tests (python -m unittest discover -s tests)
docs/
  hosting-without-shell.md   Botkeep & panel-only application hosts guide
```

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall .
```
