# Hosting without a shell (Botkeep & other “application hosts”)

Some hosts never give you a terminal: no SSH, no console commands, no
`apt install`. You get a **panel** instead — connect a GitHub repo (or
upload a ZIP), pick a runtime, type **one start command**, and fill in
**environment variables** in a form. [Botkeep](https://botkeep.cloud)
is one of these; the same recipe works on any host with that model.

Good news: this bot was built for exactly that. It needs **one
non-interactive process**, logs to stdout, and reads **all** of its
configuration from environment variables — the `.env` file is only a
convenience for machines where you have a shell. On a panel host you
skip `install.sh` entirely and type the same values into the panel.

---

## The recipe (any application host)

1. **Source** — connect the GitHub repository
   `IzumiRain/TelegramFileLinkBot` (public — no token needed), or upload
   a ZIP of it (see below).
2. **Runtime** — Python, with `requirements.txt` at the project root
   (it is). The host installs the dependencies.
3. **Start command** — `bash start.sh`
   (it creates a virtualenv and installs anything missing, then runs the
   bot; if your host pre-installs `requirements.txt` itself,
   `python bot.py` works too).
4. **Environment variables** — set them in the panel (table below).
   Secrets go in the panel's secret/Environment store, **never** in the
   repo or the ZIP.
5. **Port** — do **not** set `APP_PORT`/`PORT`. These hosts inject their
   own port (`SERVER_PORT`, sometimes `PORT`) and route traffic to it;
   the bot already listens on it and on `0.0.0.0` automatically.
6. **Domain → `BASE_URL`** — the host assigns you a domain (Botkeep:
   the **Domains** tab, custom domains supported). Deploy once, copy
   the domain, set `BASE_URL=https://<that-domain>` and restart. Until
   then the bot works in Telegram, but its download links point nowhere
   public.

### Environment variables to set

| Variable | Value | Notes |
|---|---|---|
| `BOT_TOKEN` | your BotFather token | **secret** |
| `OWNER_IDS` | your numeric Telegram ID | enables the `/admin` menu |
| `BASE_URL` | `https://<your-domain>` | after step 6; no trailing slash |
| `WEB_ADMIN_PASSWORD` | a password you choose | **secret**; enables the web panel at `/admin` |
| `FILE_TTL_HOURS` | e.g. `168` (7 days) | recommended on small disks |
| `MAX_URL_DOWNLOAD_MB` | e.g. `500` | keep stored files within your disk quota |
| `ALLOWED_USER_IDS` | comma-separated IDs | optional first-boot seed |

Leave `BOT_API_URL` empty and `AUTO_UPDATE` unset on these hosts (see
*Limitations* below).

### ZIP instead of GitHub

From a machine that *does* have a shell, export exactly the tracked
files (no `.env`, no stored files, no venv):

```bash
git clone https://github.com/IzumiRain/TelegramFileLinkBot.git
cd TelegramFileLinkBot
git archive --format=zip HEAD -o TelegramFileLinkBot.zip
```

Upload that ZIP in the panel, then continue from step 2 above.

---

## Botkeep specifics

From Botkeep's own documentation
([docs](https://botkeep.cloud/docs),
[GitHub deploy guide](https://botkeep.cloud/docs/github),
[hosting guide](https://botkeep.cloud/docs/hosting)):

- **Sources:** GitHub (via the Botkeep GitHub App — install it for this
  repo), ZIP upload, or a blank workspace.
- **Start command** must be non-interactive; ours is (`bash start.sh`).
- **HTTP:** “listen on `0.0.0.0` and `SERVER_PORT`, then configure
  Domains” — the bot already does exactly this.
- **Free plan (Standard Free):** 512 MB RAM, 50% CPU, **1 GB storage**,
  running 24/7 with no renewal ritual. Stored files live in that 1 GB
  alongside code and dependencies — that's why the table above suggests
  a download cap and a TTL.
- **Files persist** across restarts/redeploys within your storage
  allocation, and the panel offers backups — still keep your own copy
  of anything important; deleting the server deletes its files.
- **Console:** the panel shows stdout — the bot's `[bot]`/`[web]` log
  lines appear there; check them first if a deploy misbehaves.
- **Updating:** use the panel's **GitHub tab** to preview and apply a
  repository update, then restart. (A plain *Redeploy* does **not**
  pull new code — it only reapplies configuration and dependencies.)

## Limitations on shell-less hosts

- **No local Bot API server.** It needs a separate binary/process and
  system-level setup, which these hosts don't allow (“do not assume
  root access, public ports or arbitrary system packages”). Telegram's
  public limits therefore apply: **20 MB** files in, **50 MB** out.
  For 2 GB limits, run the bot somewhere with a shell (e.g. a VPS).
- **No self-update from inside the bot.** `/update`, `AUTO_UPDATE` and
  the web panel's Update button expect a writable git checkout and a
  shell. On panel hosts, update through the host's GitHub tab as above.
- **The web admin panel still works** — it's served by the bot's own
  web server, so `https://<your-domain>/admin` works like anywhere
  else (set `WEB_ADMIN_PASSWORD`). Its *Settings* page writes a `.env`
  file, which panel environment variables override on the next start —
  prefer editing values in the host's panel.
- **One process only.** The bot and its web server already run as a
  single process, so nothing extra is needed.

## Checklist

- [ ] Repo connected (or ZIP uploaded), Python runtime, root = repo root
- [ ] Start command: `bash start.sh`
- [ ] `BOT_TOKEN` and `OWNER_IDS` set in Environment (token as secret)
- [ ] No `APP_PORT`/`PORT` set by hand
- [ ] Deployed once → domain copied → `BASE_URL` set → restarted
- [ ] `/health` answers at `https://<domain>/health`, bot replies in Telegram
- [ ] `WEB_ADMIN_PASSWORD` set if you want the `/admin` panel
