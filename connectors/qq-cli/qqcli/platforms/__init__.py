# -*- coding: utf-8 -*-
"""Resolve the platform adapter for the current process.

``detect()`` is pure and accepts an explicit ``platform.system()`` value so it
can be exercised for every OS from any host (used by ``qq-cli selftest``).
``current()`` caches the adapter; call it at use sites instead of branching on
``os.name`` / ``sys.platform`` directly.
"""
import platform as _platform

from .base import PlatformAdapter
from .posix import PosixAdapter
from .windows import WindowsAdapter

__all__ = ["PlatformAdapter", "PosixAdapter", "WindowsAdapter", "detect", "current"]

_current = None


def detect(system: str | None = None) -> PlatformAdapter:
    system = system or _platform.system()
    if system == "Windows":
        return WindowsAdapter()
    return PosixAdapter(system)


def current() -> PlatformAdapter:
    global _current
    if _current is None:
        _current = detect()
    return _current
