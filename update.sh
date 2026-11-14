#!/usr/bin/env bash
# Self-update from GitHub (the repo is private — set GITHUB_TOKEN in .env).
#
#   bash update.sh          # check only (exit 3 when an update is waiting)
#   bash update.sh check    # same
#   bash update.sh apply    # fetch, fast-forward, reinstall deps if needed
#
# After applying, restart the bot/server to run the new code.
set -u
cd "$(dirname "$0")"

PY="python3"
[ -x .venv/bin/python ] && PY=".venv/bin/python"

exec $PY -m app.updater "${1:-check}"
