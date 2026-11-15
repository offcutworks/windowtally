"""One window per user. The running window holds the data folder's window lock for its life; a second start finds
the lock held, asks the running window to show itself by writing the request file, and exits. The window looks for
the request on its clock. Both are plain files: the window opens no socket and no other channel.
"""

from __future__ import annotations

from windowtally.files import write_text_atomically
from windowtally.paths import MachinePaths
from windowtally.service import SingleInstance


def claim(paths: MachinePaths) -> SingleInstance | None:
    """The window lock, held until the process ends; None when another window holds it. A request left by a start
    that found no window running is cleared, so it does not show a window started into the tray."""
    lock = SingleInstance(paths.window_lock)
    if not lock.acquire():
        return None
    take_request(paths)
    return lock


def ask_to_show(paths: MachinePaths) -> None:
    write_text_atomically(paths.window_request, "show\n")


def take_request(paths: MachinePaths) -> bool:
    """Whether a second start asked the window to show itself since the last look; the request is consumed."""
    try:
        paths.window_request.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False  # still being written; the next look takes it
    return True
