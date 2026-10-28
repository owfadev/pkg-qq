#!/usr/bin/env bash
# Restricted inbox reader for the unattended QQ agent.
# The watcher sets QQ_AGENT_KIND (group|c2c) and QQ_AGENT_LIMIT; the agent cannot
# pass arbitrary flags or file paths. The lease is bounded so a crashed run can be
# retried within the passive window.
set -euo pipefail
kind="${QQ_AGENT_KIND:-}"
limit="${QQ_AGENT_LIMIT:-20}"
if [ -n "$kind" ]; then
  exec qq-cli inbox --unread --claim --lease 180 --format json --limit "$limit" --kind "$kind"
fi
exec qq-cli inbox --unread --claim --lease 180 --format json --limit "$limit"
