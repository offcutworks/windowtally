"""Claude Code's own session registry: which Claude Code sessions on this machine have a turn in progress.

Source — Claude Code's, undocumented, read as measured on the development machine (2026-11-11, the CLI's build 2.1.310
and the desktop app's 2.1.321): every running Claude Code process keeps one file, ``<claude home>/sessions/<pid>.json``,
a desktop app's session, a terminal's and a scripted run alike, which it deletes when it ends. The fields read:

    pid          the process's id, the file's own name
    sessionId    the session's id, its transcript's own
    procStartFt  the process's creation time as a decimal Windows FILETIME; older builds write it as ``procStart``
    status       ``busy`` while a turn runs or work it delegated still runs; ``waiting`` while it waits on the person (a
                 permission prompt, a question); ``idle`` otherwise, ``shell`` when idle with a background shell left
                 running; absent for the moments before the process first reports
    entrypoint   ``claude-desktop`` for a session the desktop app hosts; ``cli``, ``sdk-cli`` and others otherwise
    statusUpdatedAt
                 epoch milliseconds of the last change of ``status``, which is written only when it changes

Every other field is left alone. Beside the files Claude Code keeps ``<pid>.<hash>.key`` files, which may hold secrets:
only a name of digits ending in ``.json`` is ever opened, so no other file of the folder is read.

A session is at work while its status is ``busy`` and its process is the one that wrote the file: a live process of that
id created at that time. A process that died leaves its file behind until something cleans it up, and the next look no
longer counts it; there is no time limit, since a busy status is not renewed while a turn runs. A file this reader cannot
read — not JSON, a field missing or of another kind, a status it does not know — is a problem named in the reading
(``Reading.problems``), which the pass puts among the status file's source problems, and that session counts as not at
work: an update of Claude Code that changes the file is then said, not met with silence.

Windows only: a process's creation time is asked of Windows (``WindowsProcesses``); a test passes a stand-in table.
"""

from __future__ import annotations

import ctypes
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SOURCE = "Claude Code's session registry"
DESKTOP_ENTRYPOINT = "claude-desktop"
WORKING_STATUS = "busy"
KNOWN_STATUSES = frozenset({"busy", "idle", "waiting", "shell"})
PROBLEMS_SPELT_OUT = 3   # files of the registry whose problem the reading spells out; the rest are counted
_FILE_NAME = re.compile(r"^(\d+)\.json$")
_FILETIME = re.compile(r"^\d+$")


class Processes(Protocol):
    def created(self, pid: int) -> int | None:
        """The creation time, as a Windows FILETIME, of the live process ``pid``; None where none runs."""


@dataclass(frozen=True)
class Session:
    pid: int
    session_id: str
    status: str | None              # one of KNOWN_STATUSES, None before the process first reports
    entrypoint: str
    status_changed: float | None    # epoch seconds of the status's last change, where the file says

    @property
    def working(self) -> bool:
        return self.status == WORKING_STATUS

    @property
    def desktop(self) -> bool:
        """Whether the desktop app hosts the session: only its sessions end when the app is closed."""
        return self.entrypoint == DESKTOP_ENTRYPOINT


@dataclass(frozen=True)
class Reading:
    sessions: tuple[Session, ...] = ()   # the live sessions, each of a process that still runs
    problems: tuple[str, ...] = ()       # source problems, each "<source>: <problem>", for status.json's sourceErrors

    def working(self) -> tuple[Session, ...]:
        """Every session with a turn in progress, the desktop app's, a terminal's and a scripted run's alike."""
        return tuple(s for s in self.sessions if s.working)

    def desktop_working_ids(self) -> frozenset[str]:
        """The sessions the desktop app hosts that have a turn in progress, by their session ids."""
        return frozenset(s.session_id for s in self.sessions if s.desktop and s.working)

    def last_desktop_change(self) -> float | None:
        """When a session the desktop app hosts last changed its status, epoch seconds; None while none says."""
        times = [s.status_changed for s in self.sessions if s.desktop and s.status_changed is not None]
        return max(times) if times else None


def read_registry(sessions_dir: Path, processes: Processes | None = None) -> Reading:
    """The registry as it stands: its live sessions and the problems met. A folder that does not exist holds no
    session — Claude Code has not run under this home — and is no problem."""
    processes = WindowsProcesses() if processes is None else processes
    try:
        names = sorted(entry.name for entry in sessions_dir.iterdir() if _FILE_NAME.match(entry.name))
    except FileNotFoundError:
        return Reading()
    except OSError as exc:
        return Reading(problems=(f"{SOURCE}: the folder {sessions_dir} cannot be read ({exc})",))
    sessions: list[Session] = []
    problems: list[str] = []
    for name in names:
        try:
            session = _session(sessions_dir / name, processes)
        except _Unrecognised as exc:
            problems.append(f"{name} {exc}")
            continue
        if session is not None:
            sessions.append(session)
    return Reading(tuple(sessions), _problem_lines(problems))


class _Unrecognised(ValueError):
    """A registry file this reader does not recognise; the message says why, after the file's name."""


def _session(path: Path, processes: Processes) -> Session | None:
    """The session ``path`` describes while its process lives; None where the file went meanwhile or its process is
    gone. _Unrecognised where the file is not what this reader knows."""
    data = _load(path)
    if data is None:
        return None
    if not isinstance(data, dict):
        raise _Unrecognised("is not a JSON object")
    pid = data.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or str(pid) != _FILE_NAME.match(path.name).group(1):
        raise _Unrecognised("does not name its own process id")
    session_id = data.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        raise _Unrecognised("names no session id")
    start = data.get("procStartFt")
    if start is None:
        start = data.get("procStart")
    if not isinstance(start, str) or not _FILETIME.match(start):
        raise _Unrecognised("names no process creation time")
    status = data.get("status")
    if status is not None and status not in KNOWN_STATUSES:
        raise _Unrecognised(f"has the status {status!r}, which this version of WindowTally does not know")
    entrypoint = data.get("entrypoint")
    if not isinstance(entrypoint, str):
        raise _Unrecognised("names no entrypoint")
    changed = data.get("statusUpdatedAt")
    if changed is not None and (isinstance(changed, bool) or not isinstance(changed, (int, float))):
        raise _Unrecognised("has a statusUpdatedAt that is not a time")
    if processes.created(pid) != int(start):
        return None
    return Session(pid, session_id, status, entrypoint, changed / 1000.0 if changed is not None else None)


def _load(path: Path) -> object | None:
    """The file's JSON; None where it went meanwhile. A file caught while Claude Code rewrites it is read a second
    time before it counts as not JSON."""
    for attempt in (1, 2):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            if attempt == 2:
                raise _Unrecognised(f"cannot be read as JSON ({exc})") from None
    return None


def _problem_lines(problems: list[str]) -> tuple[str, ...]:
    """One source problem for the registry, its first files' problems spelt out and the rest counted, so a change of
    Claude Code's that makes every file unrecognised names it once rather than once a file."""
    if not problems:
        return ()
    shown = "; ".join(problems[:PROBLEMS_SPELT_OUT])
    more = len(problems) - PROBLEMS_SPELT_OUT
    if more > 0:
        shown += f"; and {more} more file{'' if more == 1 else 's'}"
    return (f"{SOURCE}: {shown}; such a session counts as not at work",)


class WindowsProcesses:
    """The live processes as Windows reports them: a process's creation time through ``GetProcessTimes``, asked with
    the least access Windows grants, which reads another program's process without any right over it."""

    _QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259

    def __init__(self, kernel32: object | None = None):
        if kernel32 is None:
            if sys.platform != "win32":
                raise OSError("Claude Code's session registry is read on Windows only")
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
            kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._k = kernel32

    def created(self, pid: int) -> int | None:
        from ctypes import wintypes
        handle = self._k.OpenProcess(self._QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            if not self._k.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != self._STILL_ACTIVE:
                return None
            times = [wintypes.FILETIME() for _ in range(4)]
            if not self._k.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return None
            return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        finally:
            self._k.CloseHandle(handle)
