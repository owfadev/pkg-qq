# -*- coding: utf-8 -*-
"""Cross-platform advisory file locks.

The qq-cli spool is shared by the listener and the agent process. POSIX uses
fcntl.flock; Windows uses msvcrt.locking on a one-byte range. The lock file is
created with a NUL byte because msvcrt needs a byte range (locking zero bytes or
a range past EOF is a known trap).
"""
import os
import time


class FileLock:
    def __init__(self, path, timeout: float = 10.0, poll: float = 0.05):
        self.path = str(path)
        self.timeout = max(0.0, float(timeout))
        self.poll = max(0.01, float(poll))
        self.fh = None

    def _acquire(self):
        self.fh.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release(self):
        if self.fh is None:
            return
        try:
            self.fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass

    def __enter__(self):
        self.fh = open(self.path, "a+b")
        self.fh.seek(0, os.SEEK_END)
        if self.fh.tell() == 0:
            self.fh.write(b"\0")
            self.fh.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._acquire()
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.fh.close()
                    self.fh = None
                    raise TimeoutError(f"lock timeout: {self.path}")
                time.sleep(self.poll)

    def __exit__(self, exc_type, exc, tb):
        if self.fh is None:
            return False
        self._release()
        self.fh.close()
        self.fh = None
        return False
