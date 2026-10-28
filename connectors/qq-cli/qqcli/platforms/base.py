# -*- coding: utf-8 -*-
"""Platform adapter contract.

The transport core (auth, API, normalization, spooling, reply splitting) is
platform-neutral. Only process lifecycle, permission enforcement and the
unattended executor differ, so those sit behind this small adapter surface.

Adapters are resolved once per process by :func:`qqcli.platforms.current` and
must stay free of protocol logic. Unattended executors (systemd / launchd /
Task Scheduler) are declared by ``executor``; their templates live outside the
Python package.
"""
import subprocess

from pathlib import Path


class PlatformAdapter:
    """Capability facts and process hooks for one operating system."""

    key = "base"
    os_name = "unknown"
    executor = "none"            # systemd | launchd | taskscheduler | none
    supports_detach = False      # self-detached listener (fork / DETACHED_PROCESS)

    def describe(self) -> dict:
        return {
            "key": self.key,
            "os": self.os_name,
            "executor": self.executor,
            "detach": self.supports_detach,
        }

    # -- process lifecycle -----------------------------------------------------
    def pid_alive(self, pid: int) -> bool:
        raise NotImplementedError(f"{self.key}: pid_alive not implemented")

    def stop_process(self, pid: int) -> None:
        raise NotImplementedError(f"{self.key}: stop_process not implemented")

    def spawn_detached(self, argv, log_path: Path) -> int:
        """Start ``argv`` detached from this process and return its pid.

        The child is a fresh interpreter (``python -m qqcli listen``), not a
        forked copy: identical behaviour on every OS and no inherited event
        loop state.
        """
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab", buffering=0) as log:
            proc = subprocess.Popen(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                close_fds=True,
                **self.popen_kwargs(),
            )
        return proc.pid

    def popen_kwargs(self) -> dict:
        """Platform-specific detach flags for :meth:`spawn_detached`."""
        return {}

    # -- permissions -----------------------------------------------------------
    # POSIX modes do not map onto Windows ACLs; adapters document the gap rather
    # than pretending 0600 is enforced.
    def secure_permissions(self, path: Path, mode: int = 0o600) -> None:
        raise NotImplementedError(f"{self.key}: secure_permissions not implemented")
