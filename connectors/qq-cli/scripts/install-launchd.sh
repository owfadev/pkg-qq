#!/usr/bin/env bash
# Install/refresh the launchd user agents for the QQ listener and the unattended
# agent (macOS). Idempotent. Writes system state; run only after confirmation.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SRC="$ROOT/connectors/qq-cli/launchd"
DEST="$HOME/Library/LaunchAgents"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

if [ "$(uname -s)" != "Darwin" ]; then
  echo "[error] launchd installer is macOS-only; use install-executor.sh on POSIX" >&2
  exit 1
fi

QQCLI="$(command -v qq-cli || true)"
PYTHON="$(command -v python3 || true)"
if [ -z "$QQCLI" ] || [ -z "$PYTHON" ]; then
  echo "[error] qq-cli or python3 not found on PATH; install the connector first" >&2
  exit 1
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
  echo "[dry-run] would render com.qq-cli.listen.plist / com.qq-cli.agent.plist into $DEST"
  exit 0
fi

mkdir -p "$DEST" "$HOME/.qq-cli"
for f in com.qq-cli.listen.plist com.qq-cli.agent.plist; do
  render "$f" "$DEST/$f"
done

launchctl unload "$DEST/com.qq-cli.listen.plist" 2>/dev/null || true
launchctl unload "$DEST/com.qq-cli.agent.plist" 2>/dev/null || true
launchctl load -w "$DEST/com.qq-cli.listen.plist"
launchctl load -w "$DEST/com.qq-cli.agent.plist"

printf '{"kind":"launchd","root":"%s","installed_at":"%s"}\n' \
  "$ROOT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$HOME/.qq-cli/executor.json"
chmod 600 "$HOME/.qq-cli/executor.json"
