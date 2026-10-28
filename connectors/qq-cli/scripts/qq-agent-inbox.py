#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Restricted inbox reader for the unattended QQ agent (cross-platform twin of
qq-agent-inbox.sh).

The watcher sets QQ_AGENT_KIND (group|c2c) and QQ_AGENT_LIMIT; the agent cannot
pass arbitrary flags or file paths. The lease is bounded so a crashed run can be
retried inside the passive window.
"""
import os
import shutil
import subprocess
import sys


def qq_cli() -> list:
    exe = shutil.which("qq-cli")
    return [exe] if exe else [sys.executable, "-m", "qqcli"]


def main() -> int:
    kind = os.environ.get("QQ_AGENT_KIND", "")
    limit = os.environ.get("QQ_AGENT_LIMIT", "20")
    cmd = qq_cli() + [
        "inbox", "--unread", "--claim", "--lease", "180",
        "--format", "json", "--limit", limit,
    ]
    if kind:
        cmd += ["--kind", kind]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
