#!/usr/bin/env bash
# Startup script for Pterodactyl-style panel hosts (all-in-one eggs).
#
# In the panel, set the server's Startup Command to:
#
#     bash start.sh
#
# What it does:
#   1. creates .venv and installs requirements.txt (only when it changed)
#   2. optionally starts a local telegram-bot-api server (2 GB limits)
#      when bin/telegram-bot-api exists and TELEGRAM_API_ID /
#      TELEGRAM_API_HASH are set in .env
#   3. prints the AIO egg's "SERVER MARKED AS RUNNING" banner
#   4. runs the bot in the foreground
#
# Pterodactyl injects the allocated port as SERVER_PORT; bot.py reads it
# automatically. Download links are built from BASE_URL in .env, so set
# that to the address your server is reachable at (node address + the
# allocated port, or your own domain).
set -u
cd "$(dirname "$0")"

# Load .env into the environment so the values below are visible too.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
else
  echo "[start] WARNING: no .env file — copy .env.example to .env and fill it in."
fi

# Optional: plain git pull on boot (set GIT_PULL=1 in .env to enable).
# The smarter updater (AUTO_UPDATE=1) runs further below, once the
# virtualenv exists, so its pip reinstalls land in the right place.
if [ -d .git ] && [ "${GIT_PULL:-0}" = "1" ]; then
  git pull --ff-only || echo "[start] git pull failed — continuing with local code"
fi

# --- Python environment ----------------------------------------------------
PYTHON="python3"
if [ ! -x .venv/bin/python ]; then
  echo "[start] creating virtualenv…"
  if python3 -m venv .venv 2>/dev/null; then
    PYTHON=".venv/bin/python"
  else
    echo "[start] venv unavailable — falling back to user site-packages"
    python3 -m pip install --user -q -r requirements.txt
  fi
fi
if [ "$PYTHON" = ".venv/bin/python" ]; then
  REQ_HASH="$(sha256sum requirements.txt | cut -d' ' -f1)"
  if [ "$(cat .venv/.requirements-hash 2>/dev/null)" != "$REQ_HASH" ]; then
    echo "[start] installing dependencies…"
    .venv/bin/python -m pip install -q -r requirements.txt \
      && echo "$REQ_HASH" > .venv/.requirements-hash
  fi
fi

# --- Self-update on boot (optional) ------------------------------------------
if [ "${AUTO_UPDATE:-0}" = "1" ] && [ -d .git ]; then
  echo "[start] AUTO_UPDATE=1 — checking GitHub for updates…"
  $PYTHON -m app.updater apply \
    || echo "[start] update failed — continuing with local code"
fi

# --- Local telegram-bot-api server (optional, raises limits to 2 GB) -------
BOTAPI_PID=""
if [ "${BOT_API_AUTOSTART:-1}" != "0" ] \
   && [ -x ./bin/telegram-bot-api ] \
   && [ -n "${TELEGRAM_API_ID:-}" ] && [ -n "${TELEGRAM_API_HASH:-}" ]; then
  BOT_API_PORT="${BOT_API_PORT:-8081}"
  mkdir -p bot-api-data
  echo "[start] starting local telegram-bot-api on port ${BOT_API_PORT}…"
  ./bin/telegram-bot-api \
    --api-id="$TELEGRAM_API_ID" \
    --api-hash="$TELEGRAM_API_HASH" \
    --http-port="$BOT_API_PORT" \
    --dir="$PWD/bot-api-data" \
    --local \
    > bot-api.log 2>&1 &
  BOTAPI_PID=$!
  # Give it a moment to come up before the bot starts polling through it.
  for _ in $(seq 1 20); do
    if (exec 3<>"/dev/tcp/127.0.0.1/${BOT_API_PORT}") 2>/dev/null; then
      exec 3>&- 3<&-
      break
    fi
    sleep 1
  done
  # Point the bot at it (same container → shared filesystem → local mode).
  export BOT_API_URL="${BOT_API_URL:-http://127.0.0.1:${BOT_API_PORT}}"
  export BOT_API_LOCAL_MODE="${BOT_API_LOCAL_MODE:-1}"
  echo "[start] BOT_API_URL=$BOT_API_URL (local mode: $BOT_API_LOCAL_MODE)"
elif [ -n "${BOT_API_URL:-}" ]; then
  echo "[start] using external Bot API server at $BOT_API_URL"
fi

# (The bot-api child started above is stopped together with the container
# when the panel stops the server.)

# All-in-one panel eggs mark the server as "running" when this exact
# banner appears in the console.
echo "======================================== SERVER MARKED AS RUNNING ========================================"

# --- Run the bot -------------------------------------------------------------
exec $PYTHON bot.py
