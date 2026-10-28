# -*- coding: utf-8 -*-
"""POSIX adapter: Linux, WSL, macOS and other Unix-like systems.

File locking is provided by :mod:`qqcli.locks` (fcntl.flock). Process control
uses signals; self-detaching uses fork/setsid. The unattended executor differs
by OS: systemd on Linux, launchd on macOS.
"""
import os
import signal

from pathlib import Path

from .base import PlatformAdapter


class PosixAdapter(PlatformAdapter):
    key = "posix"
    supports_detach = True

    def __init__(self, os_name: str = "Linux"):
        self.os_name = os_name
        if os_name == "Darwin":
            self.executor = "launchd"
        elif os_name == "Linux":
            self.executor = "systemd"
        else:
            self.executor = "none"

    def pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def stop_process(self, pid: int) -> None:
        os.kill(pid, signal.SIGTERM)

    def popen_kwargs(self) -> dict:
        # setsid(): survive the parent shell / terminal closing.
        return {"start_new_session": True}

    def secure_permissions(self, path: Path, mode: int = 0o600) -> None:
        try:
            os.chmod(path, mode)
        except OSError:
            pass
