# -*- coding: utf-8 -*-
"""Windows adapter: native CPython on Windows.

Two rules differ from POSIX:

* ``os.kill(pid, 0)`` does **not** probe liveness on Windows — any signal other
  than CTRL_C/CTRL_BREAK terminates the target. Liveness therefore goes through
  OpenProcess/GetExitCodeProcess.
* File modes are advisory: ``os.chmod`` only toggles the read-only bit, so 0600
  cannot be enforced with a POSIX mode. The spool stays under the user's own
  profile; a real ACL pass is still pending.

Self-detached listening uses ``DETACHED_PROCESS``; the Task Scheduler recipe ships
as ``windows/install-taskscheduler.ps1`` (experimental until verified on a Windows
host).
"""
import ctypes
import subprocess
from pathlib import Path

from .base import PlatformAdapter

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_TERMINATE = 0x0001
_STILL_ACTIVE = 259


class WindowsAdapter(PlatformAdapter):
    key = "windows"
    os_name = "Windows"
    executor = "taskscheduler"
    supports_detach = True

    def popen_kwargs(self) -> dict:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": flags}

    def pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    def stop_process(self, pid: int) -> None:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(_PROCESS_TERMINATE, False, int(pid))
        if not handle:
            raise OSError(f"cannot open pid {pid}")
        try:
            if not kernel32.TerminateProcess(handle, 1):
                raise OSError(f"cannot terminate pid {pid}")
        finally:
            kernel32.CloseHandle(handle)

    def secure_permissions(self, path: Path, mode: int = 0o600) -> None:
        # No POSIX mode equivalent; leave the file under the user profile's ACL.
        _ = (path, mode)
