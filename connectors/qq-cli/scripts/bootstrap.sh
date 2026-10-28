#!/usr/bin/env bash
# First-run bootstrap for the qq connector.
#
# Installs the Python package into the current interpreter (falling back to a
# user install on externally-managed systems), runs the offline doctor, and
# prints the human steps that cannot be automated (QQ platform bot, secret,
# allowlist).
#
# It never starts the listener or installs a service; those stay explicit.
#   scripts/bootstrap.sh [--dry-run]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # connectors/qq-cli
PYTHON="${PYTHON:-python3}"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "[error] $PYTHON not found; install Python 3.10+ first" >&2
  exit 1
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[dry-run] $PYTHON -m pip install -e $HERE"
  echo "[dry-run] $PYTHON -m pip install --user --break-system-packages -e $HERE   # fallback"
  echo "[dry-run] $PYTHON -m qqcli doctor --offline"
else
  if ! "$PYTHON" -m pip install -e "$HERE"; then
    echo "[bootstrap] first attempt failed; retrying as a user install" >&2
    "$PYTHON" -m pip install --user --break-system-packages -e "$HERE"
  fi
  echo
  "$PYTHON" -m qqcli doctor --offline || true
fi

cat <<'EOF'

[bootstrap] remaining human steps (the agent can guide, but cannot do these):
  1. Create an official QQ Bot at https://q.qq.com, enable the C2C and group @
     scenarios, and copy the AppID.
  2. In your own terminal (needs a TTY):
       qq-cli secret set --app-id <AppID>
  3. Send one private message and one group @ to the bot, then:
       qq-cli requests                 # human-only, prints raw ids
       qq-cli allow user|group <id> --label <name> --yes
  4. Refresh the token:
       qq-cli ensure
  5. Start the listener:
       qq-cli listen --detach
     or install the every-minute agent executor (after confirmation):
       connectors/qq-cli/scripts/install-executor.sh
EOF
