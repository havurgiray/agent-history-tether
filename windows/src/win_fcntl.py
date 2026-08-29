"""fcntl for Windows — just enough of the POSIX module for aht.py's Lock.

The shared core does exactly one thing with fcntl: flock(fh, LOCK_EX[|LOCK_NB])
and flock(fh, LOCK_UN) on a dedicated lock file.  This maps that onto a
msvcrt byte-range lock on byte 0 of the same file, which gives the identical
guarantee: advisory, exclusive across processes, released automatically when
the handle is closed (so a crashed process can never wedge the lock).

aht_main.py registers this module as sys.modules["fcntl"] before the
core is imported, so aht.py itself stays byte-identical to the macOS/Linux
original.
"""
import msvcrt
import os
import time

LOCK_SH = 1
LOCK_EX = 2
LOCK_NB = 4
LOCK_UN = 8


def _fd(fh):
    return fh.fileno() if hasattr(fh, "fileno") else fh


def flock(fh, op):
    fd = _fd(fh)
    os.lseek(fd, 0, os.SEEK_SET)
    if op & LOCK_UN:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass                     # not locked (or already released) — fine
        return
    if op & LOCK_NB:
        # non-blocking: one attempt, surface OSError exactly like fcntl does
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return
    # blocking: LK_LOCK gives up after ~10s, so emulate an indefinite wait
    while True:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            time.sleep(0.1)
