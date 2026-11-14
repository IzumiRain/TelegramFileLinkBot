#!/usr/bin/env bash
# Interactive installer for TelegramFileLinkBot.
#
# One-line install (the repo is public):
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/IzumiRain/TelegramFileLinkBot/main/install.sh)
#
# or the classic way:
#
#   git clone https://github.com/IzumiRain/TelegramFileLinkBot.git
#   cd TelegramFileLinkBot && bash install.sh
#
# (If you run this script from an empty directory instead, it offers to
# clone the repo first — the repo is private, so it will ask for a
# GitHub token.)
#
# The installer asks for: bot token, owner Telegram ID, app port,
# base URL, local Bot API (on/off + api id/hash), a GitHub token for
# private-repo updates, and a password for the web admin panel.
# Answers are written to .env; dependencies go into .venv.
# Afterwards the bot starts with just:  bash start.sh
#
# Non-interactive use: pre-set any answer as an environment variable
# (BOT_TOKEN, OWNER_IDS, APP_PORT, BASE_URL, GITHUB_TOKEN, ...) and/or
# pipe answers on stdin. Set INSTALL_NO_RUN=1 to skip the final launch.
set -u
# When run from a checkout (bash install.sh) jump to the script's own
# directory. When streamed (bash <(curl ...)) there is no real directory
# behind $0 — stay in the current directory instead of failing the cd.
_SELF_DIR="$(dirname -- "${BASH_SOURCE[0]:-$0}")"
if [ -d "$_SELF_DIR" ] && [ -f "$_SELF_DIR/install.sh" ]; then
  cd "$_SELF_DIR"
fi

REPO_SLUG="${GITHUB_REPO:-IzumiRain/TelegramFileLinkBot}"
REPO_URL="https://github.com/${REPO_SLUG}.git"

# Answers are read from fd 3 for the whole script: the terminal when the
# script itself was piped in, otherwise stdin (panel consoles feed the
# process's stdin; repeatedly re-opening /dev/stdin would restart a
# redirected file from offset 0 on every question).
if [ -t 0 ]; then
  exec 3<&0
elif (exec 9< /dev/tty) 2>/dev/null; then
  exec 9<&-
  exec 3< /dev/tty
else
  exec 3<&0
fi

say()  { printf '\n\033[1;32m== %s ==\033[0m\n' "$*"; }
info() { printf '   %s\n' "$*"; }
warn() { printf '\033[1;33m   ! %s\033[0m\n' "$*"; }

# ask VAR "prompt" "default" [secret]
ask() {
  local var="$1" prompt="$2" default="${3:-}" secret="${4:-}" reply shown
  shown="$default"
  if [ "$secret" = "secret" ] && [ -n "$default" ]; then shown="•••••• (keep)"; fi
  # Prompts go to stderr so piped stdin stays purely the answers.
  if [ -n "$shown" ]; then
    printf '%s [%s]: ' "$prompt" "$shown" >&2
  else
    printf '%s: ' "$prompt" >&2
  fi
  if [ "$secret" = "secret" ]; then
    read -r -s reply <&3 || reply=""
    printf '\n' >&2
  else
    read -r reply <&3 || reply=""
  fi
  if [ -z "$reply" ]; then reply="$default"; fi
  printf -v "$var" '%s' "$reply"
}

# current value of a key: existing .env first, then the environment
cur() {
  local key="$1" val=""
  if [ -f .env ]; then
    val="$(grep -E "^${key}=" .env | tail -1 | cut -d= -f2- | tr -d '"')"
  fi
  if [ -z "$val" ]; then val="${!key:-}"; fi
  printf '%s' "$val"
}

# ---------------------------------------------------------------------------
say "TelegramFileLinkBot installer"

# --- 0. Get the code if we are not inside the repo ---------------------------
if [ ! -f bot.py ]; then
  info "The project files are not in this directory."
  ask CLONE_FIRST "Clone ${REPO_SLUG} here? [Y/n]" "Y"
  case "$CLONE_FIRST" in
    [nN]*) echo "Aborted — run this installer from inside the project."; exit 1 ;;
  esac
  ask GH_TOKEN_CLONE "GitHub token (optional — the repo is public, just press Enter)" "" secret
  CLONE_URL="$REPO_URL"
  if [ -n "$GH_TOKEN_CLONE" ]; then
    CLONE_URL="https://x-access-token:${GH_TOKEN_CLONE}@github.com/${REPO_SLUG}.git"
  fi
  export GIT_TERMINAL_PROMPT=0
  git clone "$CLONE_URL" TelegramFileLinkBot || { echo "Clone failed."; exit 1; }
  cd TelegramFileLinkBot
  # Never keep the token in the saved remote URL.
  git remote set-url origin "$REPO_URL"
  export GITHUB_TOKEN="${GITHUB_TOKEN:-$GH_TOKEN_CLONE}"
fi

# --- 1. Questions -------------------------------------------------------------
say "Configuration (answers are saved to .env)"

ask NEW_BOT_TOKEN "Bot token (from @BotFather)" "$(cur BOT_TOKEN)" secret
if [ -z "$NEW_BOT_TOKEN" ]; then
  echo "A bot token is required — create a bot with @BotFather first."; exit 1
fi

ask NEW_OWNER_IDS "Your Telegram user ID (owner — gets the /admin menu; from @userinfobot)" "$(cur OWNER_IDS)"
if [ -z "$NEW_OWNER_IDS" ]; then
  warn "No owner ID — the /admin menu and /update command will be disabled."
fi

DEF_PORT="$(cur APP_PORT)"; [ -z "$DEF_PORT" ] && DEF_PORT="$(cur PORT)"
[ -z "$DEF_PORT" ] && DEF_PORT="${SERVER_PORT:-8080}"
ask NEW_APP_PORT "App port (the web server / download links listen here)" "$DEF_PORT"
case "$NEW_APP_PORT" in
  ''|*[!0-9]*) echo "App port must be a number."; exit 1 ;;
esac

DEF_BASE="$(cur BASE_URL)"
[ -z "$DEF_BASE" ] && DEF_BASE="http://127.0.0.1:${NEW_APP_PORT}"
ask NEW_BASE_URL "Base URL (public address for download links, no trailing /)" "$DEF_BASE"

# Local Bot API
DEF_LOCAL="N"
[ -n "$(cur BOT_API_URL)" ] || [ -n "$(cur TELEGRAM_API_ID)" ] && DEF_LOCAL="Y"
ask ENABLE_LOCAL "Enable a local Bot API server? (raises Telegram limits 20/50 MB -> 2 GB) [y/N]" "$DEF_LOCAL"
NEW_BOT_API_URL=""; NEW_BOT_API_LOCAL_MODE="0"
NEW_API_ID="$(cur TELEGRAM_API_ID)"; NEW_API_HASH="$(cur TELEGRAM_API_HASH)"
NEW_BOT_API_PORT="$(cur BOT_API_PORT)"; [ -z "$NEW_BOT_API_PORT" ] && NEW_BOT_API_PORT="8081"
case "$ENABLE_LOCAL" in
  [yY]*)
    ask SAME_MACHINE "Does the Bot API server run on THIS machine/container? [Y/n]" "Y"
    case "$SAME_MACHINE" in
      [nN]*)
        ask NEW_BOT_API_URL "Bot API server address" "$(cur BOT_API_URL)"
        NEW_BOT_API_LOCAL_MODE="0"
        ;;
      *)
        ask NEW_API_ID "Telegram API ID (from my.telegram.org)" "$NEW_API_ID"
        ask NEW_API_HASH "Telegram API hash" "$NEW_API_HASH" secret
        ask NEW_BOT_API_PORT "Bot API server port" "$NEW_BOT_API_PORT"
        NEW_BOT_API_URL="http://127.0.0.1:${NEW_BOT_API_PORT}"
        NEW_BOT_API_LOCAL_MODE="1"
        if [ ! -x bin/telegram-bot-api ]; then
          warn "No binary at bin/telegram-bot-api yet — start.sh can only"
          warn "auto-start the local server once you place the binary there"
          warn "(build it from github.com/tdlib/telegram-bot-api)."
        fi
        ;;
    esac
    ;;
esac

ask NEW_GITHUB_TOKEN "GitHub token (optional — only raises GitHub rate limits now the repo is public)" "$(cur GITHUB_TOKEN)" secret
ask NEW_GUI_PASSWORD "Web admin panel password (optional — empty disables the panel at /admin)" "$(cur WEB_ADMIN_PASSWORD)" secret
DEF_AUTO="N"
case "$(cur AUTO_UPDATE)" in 1|true|yes) DEF_AUTO="Y" ;; esac
ask NEW_AUTO_UPDATE "Auto-update from GitHub on every start? [y/N]" "$DEF_AUTO"
case "$NEW_AUTO_UPDATE" in [yY]*) NEW_AUTO_UPDATE="1" ;; *) NEW_AUTO_UPDATE="0" ;; esac

# --- 2. Write .env --------------------------------------------------------------
say "Writing .env"
export \
  W_BOT_TOKEN="$NEW_BOT_TOKEN" \
  W_OWNER_IDS="$NEW_OWNER_IDS" \
  W_APP_PORT="$NEW_APP_PORT" \
  W_BASE_URL="$NEW_BASE_URL" \
  W_BOT_API_URL="$NEW_BOT_API_URL" \
  W_BOT_API_LOCAL_MODE="$NEW_BOT_API_LOCAL_MODE" \
  W_TELEGRAM_API_ID="$NEW_API_ID" \
  W_TELEGRAM_API_HASH="$NEW_API_HASH" \
  W_BOT_API_PORT="$NEW_BOT_API_PORT" \
  W_GITHUB_TOKEN="$NEW_GITHUB_TOKEN" \
  W_GITHUB_REPO="$REPO_SLUG" \
  W_WEB_ADMIN_PASSWORD="$NEW_GUI_PASSWORD" \
  W_AUTO_UPDATE="$NEW_AUTO_UPDATE"
python3 - <<'PYEOF'
import os
from pathlib import Path
from app.envfile import update_env_file

keys = [
    "BOT_TOKEN", "OWNER_IDS", "APP_PORT", "BASE_URL", "BOT_API_URL",
    "BOT_API_LOCAL_MODE", "TELEGRAM_API_ID", "TELEGRAM_API_HASH",
    "BOT_API_PORT", "GITHUB_TOKEN", "GITHUB_REPO", "WEB_ADMIN_PASSWORD",
    "AUTO_UPDATE",
]
updates = {k: os.environ.get("W_" + k, "") for k in keys}
update_env_file(Path(".env"), updates)
print("   .env saved")
PYEOF
chmod 600 .env 2>/dev/null || true

# --- 3. Dependencies --------------------------------------------------------------
say "Installing dependencies"
if [ ! -x .venv/bin/python ]; then
  if python3 -m venv .venv 2>/dev/null; then
    info "virtualenv created"
  else
    warn "venv unavailable — installing into user site-packages"
    python3 -m pip install --user -q -r requirements.txt
  fi
fi
if [ -x .venv/bin/python ]; then
  .venv/bin/python -m pip install -q -r requirements.txt
  sha256sum requirements.txt | cut -d' ' -f1 > .venv/.requirements-hash
fi
info "dependencies installed"

# --- 4. Summary + launch --------------------------------------------------------------
say "Done"
info "Base URL:      $NEW_BASE_URL"
info "App port:      $NEW_APP_PORT"
info "Owner IDs:     ${NEW_OWNER_IDS:-—}"
info "Local Bot API: ${NEW_BOT_API_URL:-off}"
info "Web panel:     ${NEW_BASE_URL}/admin $([ -n "$NEW_GUI_PASSWORD" ] && echo '(password set)' || echo '(disabled — no password)')"
info "GitHub token:  $([ -n "$NEW_GITHUB_TOKEN" ] && echo 'set (updater can use the private repo)' || echo 'not set')"
info ""
info "From now on, starting is just:  bash start.sh"
info "(On panel hosts (Pterodactyl-style), set the Startup Command to exactly that.)"

if [ "${INSTALL_NO_RUN:-0}" = "1" ]; then
  exit 0
fi
ask RUN_NOW "Start the bot now? [Y/n]" "Y"
case "$RUN_NOW" in
  [nN]*) info "OK — start it any time with: bash start.sh" ;;
  *) exec bash start.sh ;;
esac
