"""The account sync script, run as a process of its own. No toolkit.

The window never touches a credential. Switching the desktop app or the CLI to another account, adding an account
(storing the login the app holds and leaving the app at its sign-in page), starting the app where it is not running
and turning the sync's two switches are all the work of ``sync/WindowTallySync.ps1``, which the window starts with the installed copy's path and whose answer it
reads: the exit code and the notes the script writes to stderr, one line each, behind ``[windowtally-sync] ``. The run's
pipes are read on a thread of its own and handed over by ``poll`` on the window's thread, as ``background`` hands over
a job.

The script's exit codes: 0 done, 2 refused with no login changed (an app the script had told to close, and that did
not close in time, may be partly closed, which its note says), 3 no stored login of the account asked for (for a CLI
switch, also the CLI signed out of that account, whose stored sign-in is then not put back), 4 a CLI is
running (a CLI switch refused for that alone, which the window offers to wait out), 5 the desktop app was switched but
came up signed out (it refused the stored login, which the script set aside), 1 an error, an add whose app came up
signed in all the same among them. A start of the app ends 0 whether it started the app or found it running, 2 while
another of the sync's acts stays busy.

Before a desktop mode closes the app it waits, up to 35 seconds, for a sign-in the app has just made to reach its
Cookies file, and says so (``SAVING``); the run can still be called off then. It can be called off until the script
says it is closing the desktop app (``CLOSING``): from then on the account's login files are being exchanged, and
ending the script would leave them half done. Once the script says it is starting the app (``STARTING``) it
watches the app's log for its word on its sign-in, signed in after a switch or at its sign-in page after an add, which
takes seconds and up to a minute.
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable

from windowtally.paths import MachinePaths

EXIT_OK, EXIT_ERROR, EXIT_REFUSED, EXIT_NO_LOGIN, EXIT_CLI_RUNNING, EXIT_SIGNED_OUT = 0, 1, 2, 3, 4, 5

NOTE_PREFIX = "[windowtally-sync] "
SAVING = "Waiting for the desktop app to save its sign-in"
CLOSING = "Closing the desktop app"
STARTING = "Starting the desktop app"

# A console program the window starts shows no console window of its own; the one terminal it opens is the exception.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


def powershell() -> str:
    """Windows PowerShell by its path: the script is written for 5.1, and a bare name would resolve on the PATH."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def command(paths: MachinePaths, mode: str, *, account: str | None = None, follows: bool | None = None,
            one_click: bool | None = None) -> list[str]:
    """The command line that runs the installed sync script in ``mode``; every location is the script's own default."""
    argv = [powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
            str(paths.sync_script), "-Mode", mode]
    if account is not None:
        argv += ["-Account", account]
    if follows is not None:
        argv += ["-Follows", "On" if follows else "Off"]
    if one_click is not None:
        argv += ["-OneClick", "On" if one_click else "Off"]
    return argv


@dataclass(frozen=True)
class Result:
    code: int
    notes: tuple[str, ...]


def reason(result: Result) -> str:
    """The script's verdict on a run that did not finish: its last note, without the word that marks it a refusal or an
    error, else the exit code."""
    if not result.notes:
        return f"the sync script ended with exit code {result.code}"
    note = result.notes[-1]
    for prefix in ("Refused: ", "Error: "):
        if note.startswith(prefix):
            return note[len(prefix):]
    return note


class SyncRun:
    """One run of the sync script. ``popen`` is a parameter so a test can run a program of its own."""

    def __init__(self, argv: list[str], *, popen: Callable[..., subprocess.Popen] = subprocess.Popen):
        self.argv = argv
        self.notes: list[str] = []
        self.cancelled = False
        self._lines: queue.Queue = queue.Queue()
        self._streamed = False
        self.process = popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             text=True, errors="replace", creationflags=_NO_WINDOW)
        threading.Thread(target=self._read, name="window-sync-run", daemon=True).start()

    def _read(self) -> None:
        try:
            for line in self.process.stderr:
                self._lines.put(line.rstrip("\r\n"))
        finally:
            self.process.stderr.close()
            self._lines.put(None)

    @property
    def saving(self) -> bool:
        """The script waits for the desktop app to save a sign-in it has just made before closing it."""
        return any(note.startswith(SAVING) for note in self.notes)

    @property
    def closing(self) -> bool:
        """The script has begun to close the desktop app."""
        return any(note.startswith(CLOSING) for note in self.notes)

    @property
    def starting(self) -> bool:
        """The script has started the desktop app again and watches it sign in."""
        return any(note.startswith(STARTING) for note in self.notes)

    def poll(self) -> Result | None:
        """The run's result once it has ended and all it wrote is read; None while it runs."""
        while True:
            try:
                line = self._lines.get_nowait()
            except queue.Empty:
                break
            if line is None:
                self._streamed = True
            elif line.strip():
                self.notes.append(line[len(NOTE_PREFIX):] if line.startswith(NOTE_PREFIX) else line)
        code = self.process.poll()
        if code is None or not self._streamed:
            return None
        return Result(code, tuple(self.notes))

    def cancel(self) -> bool:
        """Ends the run, unless it is over or past the point where ending it would leave work half done."""
        if self.closing or self.process.poll() is not None:
            return False
        self.cancelled = True
        self.process.terminate()
        return True


def open_login_terminal(paths: MachinePaths, *, popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> None:
    """A terminal of its own running ``claude auth login`` through the installed launcher, which stores the sign-in
    once it ends, and stays open to show how the login went."""
    launcher = paths.claude_home / "bin" / "claude.cmd"
    popen([powershell(), "-NoProfile", "-NoExit", "-Command", f"& '{launcher}' auth login"],
          creationflags=_NEW_CONSOLE)
