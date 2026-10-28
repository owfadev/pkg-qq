#!/usr/bin/env bash
# Compatibility shim: the watcher lives in qq-agent-watch.py (one implementation
# for systemd, launchd and Task Scheduler). Kept so existing unit files and
# operator habits keep working.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/qq-agent-watch.py" "$@"
