"""Cross-platform non-blocking single-instance lock.

Used to stop two runs overlapping. POSIX uses fcntl; Windows uses msvcrt.
Both lock an open file handle; the OS releases it if the process dies.
"""

from __future__ import annotations

import sys


class LockBusy(Exception):
    """Another process already holds the lock."""


if sys.platform == "win32":
    import msvcrt

    def acquire(fh) -> None:
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as err:
            raise LockBusy from err

    def release(fh) -> None:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def acquire(fh) -> None:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as err:
            raise LockBusy from err

    def release(fh) -> None:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        except OSError:
            pass
