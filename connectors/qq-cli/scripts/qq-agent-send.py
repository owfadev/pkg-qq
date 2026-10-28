#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Restricted passive-reply sender for the unattended QQ agent (cross-platform
twin of qq-agent-send.sh).

Exactly one event id; the reply text can only come from stdin. This prevents the
agent from using --text-file <path> to exfiltrate arbitrary local files.
"""
import shutil
import subprocess
import sys


def qq_cli() -> list:
    exe = shutil.which("qq-cli")
    return [exe] if exe else [sys.executable, "-m", "qqcli"]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: qq-agent-send <event-id> (reply text on stdin)", file=sys.stderr)
        return 2
    cmd = qq_cli() + ["reply", sys.argv[1], "--text-file", "-", "--ack"]
    return subprocess.call(cmd, stdin=sys.stdin)


if __name__ == "__main__":
    raise SystemExit(main())
