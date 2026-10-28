#!/usr/bin/env bash
# Dispatch to the executor installer for this POSIX environment.
# Native Windows: run connectors/qq-cli/windows/install-taskscheduler.ps1 instead.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$(uname -s)" in
  Linux)
    exec "$HERE/install-systemd.sh" "$@"
    ;;
  Darwin)
    exec "$HERE/install-launchd.sh" "$@"
    ;;
  MINGW*|MSYS*|CYGWIN*)
    echo "[error] native Windows: run connectors/qq-cli/windows/install-taskscheduler.ps1 in PowerShell" >&2
    exit 1
    ;;
  *)
    echo "[error] no executor recipe for $(uname -s); see connectors/qq-cli/README.md" >&2
    exit 1
    ;;
esac
