#!/usr/bin/env bash
# Install/refresh the systemd user units for the QQ transport listener and the
# unattended agent timer. Idempotent. This writes system state; run it only after
# the operator has confirmed unattended mode.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SRC="$ROOT/connectors/qq-cli/systemd"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

QQCLI="$(command -v qq-cli || true)"
PYTHON="$(command -v python3 || true)"
if [ -z "$QQCLI" ] || [ -z "$PYTHON" ]; then
  echo "[error] qq-cli or python3 not found on PATH; install the connector first" >&2
  exit 1
fi

if [ "$DRY_RUN" -eq 0 ]; then
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "[error] systemctl not found; install the units manually from $SRC" >&2
    exit 1
  fi
  if ! systemctl --user show-environment >/dev/null 2>&1; then
    echo "[error] systemd --user is not available; install the units manually from $SRC" >&2
    exit 1
  fi
fi

render() {
  sed -e "s|@ROOT@|$ROOT|g" \
      -e "s|@HOME@|$HOME|g" \
      -e "s|@QQCLI@|$QQCLI|g" \
      -e "s|@PYTHON@|$PYTHON|g" \
      "$SRC/$1.in" > "$2"
}

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[dry-run] root=$ROOT qq-cli=$QQCLI python=$PYTHON"
  echo "[dry-run] would render qq-listen.service / qq-agent.service / qq-agent.timer into $UNIT_DIR"
  exit 0
fi

mkdir -p "$UNIT_DIR" "$HOME/.qq-cli"
for f in qq-listen.service qq-agent.service qq-agent.timer; do
  render "$f" "$UNIT_DIR/$f"
done

systemctl --user daemon-reload
systemctl --user enable --now qq-listen.service qq-agent.timer
systemctl --user list-timers qq-agent.timer --no-pager

printf '{"kind":"systemd","root":"%s","installed_at":"%s"}\n' \
  "$ROOT" "$(date -Is)" > "$HOME/.qq-cli/executor.json"
chmod 600 "$HOME/.qq-cli/executor.json"
