"""The service keeps the computer awake while a Claude Code session works.

While Claude Code's session registry (``registry``) names at least one live session with a turn in progress — the
desktop app's, a terminal's or a scripted run's alike — and the user has not turned the keep-awake off (``settings``,
``keepAwakeOff``), the service holds a Windows power request that keeps the system from sleeping on its idle timer;
otherwise it holds none. A session waiting on the person, at a permission prompt or a question, or idle, holds nothing.
The display is not held: the screen still turns off, and locks, on its own timer. The request is the same on battery as
on mains, and Windows names it, with the service's process, in ``powercfg /requests``.

``KeepAwake`` looks every ``LOOK_INTERVAL`` seconds on a thread of its own, beside the passes, so a hold starts within
seconds of a turn's start and ends within seconds of the last one's end whatever a pass is doing, a first import that
takes minutes included. Settings that cannot be read keep the computer awake, the default, as the pass names them among
the source problems; a registry that cannot be read holds nothing, the pass naming that too, and the look logs each
change of what it met.

Windows releases a power request when the process holding it ends, so a service that is stopped or dies leaves
nothing held. What a lid, the power button or the Start menu's Sleep does is the user's and Windows', and no request
stands against it.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from pathlib import Path
from typing import Callable, Protocol

from .registry import Processes, Reading, WindowsProcesses, read_registry
from .settings import keeps_awake

log = logging.getLogger(__name__)

LOOK_INTERVAL = 2.0   # seconds between two looks at the registry and the setting
REASON = "WindowTally: a Claude Code session is working"


class _Detailed(ctypes.Structure):
    _fields_ = [("module", ctypes.c_void_p), ("reason_id", ctypes.c_ulong), ("count", ctypes.c_ulong),
                ("strings", ctypes.POINTER(ctypes.c_wchar_p))]


class _Reason(ctypes.Union):
    _fields_ = [("detailed", _Detailed), ("simple", ctypes.c_wchar_p)]


class ReasonContext(ctypes.Structure):
    """Windows' REASON_CONTEXT, the words a power request carries, which ``powercfg /requests`` shows."""
    _fields_ = [("version", ctypes.c_ulong), ("flags", ctypes.c_ulong), ("reason", _Reason)]


class PowerRequests(Protocol):
    """The system's power requests: ``hold`` keeps the system from sleeping until ``release``; OSError where Windows
    refuses."""

    def hold(self, reason: str) -> None: ...

    def release(self) -> None: ...


class WindowsPowerRequests:
    """One Windows power request (``PowerCreateRequest``), set for the system and for execution, never for the display.
    The system request keeps the system from sleeping on its idle timer; the execution request is the kind the desktop
    app holds while its own Code sessions work (``powercfg /requests`` lists it under EXECUTION), which Windows takes for
    a system request on a computer that sleeps to S3. Whether either keeps Claude Code running on a computer with modern
    standby once its screen turns off has not been measured."""

    _SYSTEM_REQUIRED = 1        # POWER_REQUEST_TYPE.PowerRequestSystemRequired
    _EXECUTION_REQUIRED = 3     # POWER_REQUEST_TYPE.PowerRequestExecutionRequired
    _SIMPLE_STRING = 0x1        # POWER_REQUEST_CONTEXT_SIMPLE_STRING
    _INVALID_HANDLE = ctypes.c_void_p(-1).value

    def __init__(self, kernel32: object | None = None):
        """``kernel32`` is Windows' own, loaded here where not given; a test passes a stand-in."""
        if kernel32 is None:
            if sys.platform != "win32":
                raise OSError("the computer is kept awake on Windows only")
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.PowerCreateRequest.restype = wintypes.HANDLE
            kernel32.PowerCreateRequest.argtypes = (ctypes.POINTER(ReasonContext),)
            kernel32.PowerSetRequest.restype = wintypes.BOOL
            kernel32.PowerSetRequest.argtypes = (wintypes.HANDLE, ctypes.c_int)
            kernel32.PowerClearRequest.restype = wintypes.BOOL
            kernel32.PowerClearRequest.argtypes = (wintypes.HANDLE, ctypes.c_int)
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._k = kernel32
        self._handle = None
        self._reason: ReasonContext | None = None   # kept while the request stands, its string with it

    def hold(self, reason: str) -> None:
        if self._handle is not None:
            return
        context = ReasonContext(0, self._SIMPLE_STRING)
        context.reason.simple = reason
        handle = self._k.PowerCreateRequest(ctypes.byref(context))
        if not handle or handle == self._INVALID_HANDLE:
            raise ctypes.WinError(ctypes.get_last_error())
        for kind in (self._SYSTEM_REQUIRED, self._EXECUTION_REQUIRED):
            if not self._k.PowerSetRequest(handle, kind):
                error = ctypes.WinError(ctypes.get_last_error())
                self._close(handle)
                raise error
        self._handle, self._reason = handle, context

    def release(self) -> None:
        if self._handle is None:
            return
        handle, self._handle, self._reason = self._handle, None, None
        self._close(handle)

    def _close(self, handle) -> None:
        for kind in (self._SYSTEM_REQUIRED, self._EXECUTION_REQUIRED):
            self._k.PowerClearRequest(handle, kind)
        self._k.CloseHandle(handle)


class KeepAwake:
    """Holds the power request while the registry names a session at work and the setting allows it. ``look`` is one
    look; ``run`` looks every ``interval`` seconds until ``stop`` is set, and releases what it holds when it ends."""

    def __init__(self, sessions_dir: Path, settings_file: Path, power: PowerRequests,
                 processes: Processes | None = None,
                 read: Callable[[Path, Processes | None], Reading] = read_registry):
        self.sessions_dir, self.settings_file = sessions_dir, settings_file
        self.power, self.processes, self._read = power, processes, read
        self.holding = False
        self._said: tuple[str, ...] = ()
        self._hold_refused = False   # Windows refused the last hold, which is logged once until one succeeds

    def look(self) -> bool:
        """One look: the request held or released as the registry and the setting now say; whether it is held."""
        allowed = self._allowed()
        reading = self._read(self.sessions_dir, self.processes)
        self._say(reading.problems)
        working = len(reading.working())
        if allowed and working:
            if not self.holding:
                try:
                    self.power.hold(REASON)
                except OSError as exc:
                    if not self._hold_refused:
                        log.warning("Windows refused the request to keep the computer awake: %s", exc)
                    self._hold_refused = True
                    return False
                self.holding, self._hold_refused = True, False
                log.info("Keeping the computer awake: %d Claude Code session%s at work.", working,
                         "" if working == 1 else "s")
        elif self.holding:
            self.release()
            log.info("The computer may sleep again: %s.",
                     "the keep-awake was turned off" if working else "no Claude Code session is at work")
        return self.holding

    def release(self) -> None:
        if self.holding:
            self.holding = False
            self.power.release()

    def run(self, stop: threading.Event, interval: float = LOOK_INTERVAL) -> None:
        try:
            while True:
                try:
                    self.look()
                except Exception:  # the look must outlive a failure; the next one retries
                    log.exception("The keep-awake's look failed")
                if stop.wait(interval):
                    return
        finally:
            self.release()

    def _allowed(self) -> bool:
        """Whether the settings let the computer be kept awake: they do unless they turn it off, settings that cannot
        be read included, which the pass names among the source problems."""
        return keeps_awake(self.settings_file) is not False

    def _say(self, problems: tuple[str, ...]) -> None:
        """Logs the registry's problems when they change, not at every look."""
        if problems != self._said:
            self._said = problems
            for problem in problems:
                log.warning("%s", problem)


def start_keep_awake(sessions_dir: Path, settings_file: Path) -> None:
    """The service's keep-awake on a daemon thread of its own, for the life of the service: it ends with the process,
    and Windows then releases the request. Where Windows' power requests or its process table cannot be reached the
    service runs without it, which is logged."""
    try:
        power, processes = WindowsPowerRequests(), WindowsProcesses()
    except OSError:
        log.exception("The computer cannot be kept awake while Claude Code works")
        return
    keeper = KeepAwake(sessions_dir, settings_file, power, processes)
    threading.Thread(target=keeper.run, args=(threading.Event(),), name="keep-awake", daemon=True).start()
