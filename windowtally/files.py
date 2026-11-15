"""Writing a file whole — so a reader never sees half of one — while readers come and go, and changing one file from
two processes without losing either change.

Every file WindowTally writes for another party (status.json, the history page, the user's bills file and settings, the
window's own record) is written to a temporary file beside it and moved over it in one step. On Windows that move is
refused while any process holds the destination open, whatever share mode the reader asked for (measured on the
development machine, 2026-10-21: ``os.replace`` raised PermissionError under a plain open and under one that allowed
deletion). Readers hold these files for milliseconds, so a refused move is retried for up to ``REPLACE_PATIENCE``
seconds before the error is raised; the temporary file is then removed. The temporary name carries the process and
thread, so two writers of one file never share a temporary file. The temporary file's bytes reach the disk before the
move: NTFS journals the move and the file's length but not its bytes, which Windows writes later, so a crash after the
move and before those bytes were written leaves the file its new length in zero bytes (the account sync's state.json,
on the development machine, 2026-11-05).

A change that reads a file, alters it and writes it back — a bill added or replaced, a source listed, the reminder
set — runs under ``editing(path)``, the lock on ``<file>.lock`` beside it: the window and the command line change the
same files, and two such changes made at once would otherwise each write back what the other never saw. ``FileLock``
is the one lock primitive WindowTally has; the pass lock and the single-instance locks are built on it.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

REPLACE_PATIENCE = 2.0   # seconds a move refused by a reader is retried
REPLACE_STEP = 0.05
EDIT_PATIENCE = 10.0     # seconds a change waits for another change to the same file to end


def try_lock(handle) -> bool:
    """Takes the exclusive lock on the first byte of an open lock file; False when another handle holds it."""
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def unlock(handle) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class FileLock:
    """An exclusive lock on a lock file, held for a block: a context manager that waits up to ``patience`` seconds
    for another holder to let go, then raises TimeoutError naming ``holder``."""

    def __init__(self, path: Path, patience: float, holder: str = "another process"):
        self.path, self.patience, self.holder = path, patience, holder
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+")
        deadline = time.monotonic() + self.patience
        while not try_lock(handle):
            if time.monotonic() >= deadline:
                handle.close()
                raise TimeoutError(f"{self.holder} has held {self.path} for over {self.patience:.0f} s")
            time.sleep(0.1)
        self.handle = handle
        return self

    def __exit__(self, *exc_info) -> None:
        try:
            unlock(self.handle)
        finally:
            self.handle.close()
            self.handle = None


def editing(path: Path) -> FileLock:
    """The lock a read, change and write of ``path`` holds: ``<file>.lock`` beside it."""
    return FileLock(path.with_name(path.name + ".lock"), EDIT_PATIENCE, "another change to the file")


def write_text_atomically(path: Path, text: str, *, patience: float = REPLACE_PATIENCE) -> None:
    """Writes ``text`` (UTF-8) to ``path`` through a temporary file moved over it; PermissionError when a reader still
    holds the file after ``patience`` seconds, the file then left as it was. A file the user names for a window to
    write takes no patience: what holds it is no reader of WindowTally's, and the window's thread must not wait."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    deadline = time.monotonic() + patience
    while True:
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                try:
                    temporary.unlink()
                except OSError:
                    pass
                raise
            time.sleep(REPLACE_STEP)
