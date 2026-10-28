#!/usr/bin/env bash
# Restricted passive-reply sender for the unattended QQ agent.
# Exactly one event id; the reply text can only come from stdin. This prevents
# the agent from using --text-file <path> to exfiltrate arbitrary local files.
set -euo pipefail
[ "$#" -eq 1 ] || { echo "usage: qq-agent-send <event-id> (reply text on stdin)" >&2; exit 2; }
exec qq-cli reply "$1" --text-file - --ack
