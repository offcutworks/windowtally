"""A switch from the window's side: asking, waiting, running, answering. No toolkit.

One job at a time, driven by the window's clock through ``tick``. A job is one run of the sync script (``sync_model``)
that may be preceded by a wait:

    switch the desktop app   waits first, if the user chose to, until no Code session is at work
    add an account           the same wait; the script stores the app's login and leaves the app at its sign-in page
    switch the CLI           runs at once; a CLI that is running refuses it, the window asks whether to wait, and the
                             wait tries the switch again every ``RETRY_SECONDS`` until it goes through
    turn a switch            runs at once
    start the desktop app    runs at once; it closes nothing and cannot be called off, the script only starting an app
                             that is not running

``progress`` is what the header says while a job is not over, and whether the user can still call it off: a wait can
always be, a run until the script begins to close the desktop app, which includes the seconds it may first wait for
the app to save a sign-in just made. ``tick`` returns what the window must answer: a job's end, the question whether
to wait for a running CLI, or the news that the CLI has no stored login, for which the window opens a terminal. A
switch of the app that ends with the app signed out, because it refused the stored login, ends as not done, in the
script's words, which say why the app refused it where the app said: the app is on the account but the user must
sign in there, and a pass shows the app at its sign-in page at once. An add that ends is said in the script's words
too, which say whether the sign-in page was reached and whose login was stored.

A switch of the app may carry sessions of the account it leaves (``carry_model``). Only a switch that ends done, the
app signed in, hands them on to be opened (``OpenSessions``, after its ``Done``), its words saying so; one that leaves
the app at its sign-in page says they were not opened, and a switch not made, or called off, leaves them where they
were, on the account still in use.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Callable

from windowtally.paths import MachinePaths

from .actions_model import Outcome
from .carry_model import not_opened_words, opening_words
from .formatting import plural
from .sync_model import (EXIT_CLI_RUNNING, EXIT_NO_LOGIN, EXIT_OK, EXIT_SIGNED_OUT, Result, SyncRun, command,
                         reason)

RETRY_SECONDS = 5.0

# What a job is.
APP, CLI, ADD, SETTINGS, START = "app", "cli", "add", "settings", "start"

# Where a job is.
_WAIT_SESSIONS, _WAIT_CLI, _ASKING, _RUN, _FAILED = "wait-sessions", "wait-cli", "asking", "run", "failed"


@dataclass(frozen=True)
class Progress:
    text: str
    cancellable: bool


# What the header says while the desktop app starts: through the start's run, and after it until a status says whether
# the app runs (``live_model.still_starting``).
STARTING = Progress("Starting the desktop app…", False)


@dataclass(frozen=True)
class Done:
    """A job has ended; ``refresh`` says WindowTally's figures changed, so a pass should read them. ``kind`` is the job's,
    which says where the window answers, never what the end was, so two ends are equal whatever job ended."""

    outcome: Outcome
    refresh: bool
    kind: str = field(default="", compare=False)


@dataclass(frozen=True)
class AskCliIdle:
    """A CLI is running, so the switch could not be made: shall the window wait for it?"""

    label: str


@dataclass(frozen=True)
class NeedsCliLogin:
    """The account has no stored CLI sign-in: the window opens a terminal to sign in."""

    label: str


@dataclass(frozen=True)
class OpenSessions:
    """The switch of the app is done, the app signed in to ``label``: the window opens ``sessions`` there, each a
    session's id and its title."""

    sessions: tuple[tuple[str, str], ...]
    label: str


Event = Done | AskCliIdle | NeedsCliLogin | OpenSessions


@dataclass(frozen=True)
class _Job:
    kind: str
    argv: list[str]
    label: str = ""          # the account the job is for, in the words of the window
    follows: bool = True     # APP: the CLI follows the app, so it is switched too
    switch: str = ""         # SETTINGS: which switch, "follows" or "one-click", and the value it was given
    value: bool = False
    carry: tuple[tuple[str, str], ...] = ()   # APP: the sessions to open once it is done, each its id and title


class SwitchFlow:
    def __init__(self, paths: MachinePaths, *, sessions: Callable[[], int], start: Callable[[list[str]], SyncRun] = SyncRun,
                 clock: Callable[[], float] = time.monotonic, retry: float = RETRY_SECONDS):
        self.paths, self._sessions, self._start, self._clock, self._retry = paths, sessions, start, clock, retry
        self._job: _Job | None = None
        self._where = ""
        self._run: SyncRun | None = None
        self._next_try = 0.0
        self._at_work = 0               # Code sessions at work, as last counted while waiting for them
        self._waiting_for_cli = False   # the user chose to wait for the running CLI
        self._failure = ""

    # --- asking -----------------------------------------------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._job is not None

    def switch_app(self, uuid: str, label: str, *, follows: bool, wait: bool,
                   carry: tuple[tuple[str, str], ...] = ()) -> bool:
        """``carry`` are the sessions to open on the account once the switch is done, each its id and title."""
        return self._begin(_Job(APP, command(self.paths, "SwitchDesktop", account=uuid), label, follows,
                                carry=tuple(carry)), wait)

    def add_account(self, *, wait: bool) -> bool:
        """Stores the login the desktop app holds and leaves the app at its sign-in page, to sign in to another account
        there."""
        return self._begin(_Job(ADD, command(self.paths, "AddDesktop")), wait)

    def switch_cli(self, uuid: str, label: str) -> bool:
        return self._begin(_Job(CLI, command(self.paths, "SwitchCli", account=uuid), label), False)

    def set_switch(self, *, follows: bool | None = None, one_click: bool | None = None) -> bool:
        """Turns one of the sync's switches, the one given."""
        which, value = ("follows", follows) if follows is not None else ("one-click", one_click)
        return self._begin(_Job(SETTINGS, command(self.paths, "Settings", follows=follows, one_click=one_click),
                                switch=which, value=bool(value)), False)

    def start_app(self) -> bool:
        """Starts the desktop app, which the status reports not running; the script starts nothing where it runs."""
        return self._begin(_Job(START, command(self.paths, "StartDesktop")), False)

    def _begin(self, job: _Job, wait: bool) -> bool:
        """False, and nothing started, while another job is not over."""
        if self._job is not None:
            return False
        self._job, self._waiting_for_cli = job, False
        self._at_work = self._sessions() if wait else 0
        if self._at_work > 0:
            self._where = _WAIT_SESSIONS
        else:
            self._launch()
        return True

    def wait_for_cli(self) -> None:
        """The user chose to wait for the running CLI: the switch is tried again every few seconds."""
        if self._job is not None and self._where == _ASKING:
            self._where, self._waiting_for_cli = _WAIT_CLI, True
            self._next_try = self._clock() + self._retry

    def cancel(self) -> bool:
        """Calls the job off: always while it waits, while it runs only until the desktop app begins to close, and a
        start never. False where it cannot be, or there is no job."""
        if self._job is None or self._job.kind == START:
            return False
        if self._where == _RUN:
            return self._run is not None and self._run.cancel()
        self._job, self._where = None, ""
        return True

    # --- what the header says ---------------------------------------------------------------------------------------

    @property
    def progress(self) -> Progress | None:
        job = self._job
        if job is None or self._where in (_ASKING, _FAILED):
            return None
        if job.kind == START:
            return STARTING
        deed = {APP: f"switching the desktop app to {job.label}", CLI: f"switching the CLI to {job.label}",
                ADD: "opening the desktop app's sign-in page", SETTINGS: "saving the switch"}[job.kind]
        if self._where == _WAIT_SESSIONS:
            return Progress(f"Waiting for {plural(self._at_work, 'working session')} to finish before {deed}…", True)
        if self._where == _WAIT_CLI:
            return Progress(f"Waiting for the running CLI to exit before {deed}…", True)
        closing = self._run is not None and self._run.closing
        text = deed[0].upper() + deed[1:] + "…"
        if closing and self._run.starting:
            awaited = "its sign-in page" if job.kind == ADD else "it to sign in"
            return Progress(text + f" The desktop app is starting; waiting for {awaited}.", False)
        if closing:
            return Progress(text + " The desktop app is closing; this can no longer be called off.", False)
        if self._run is not None and self._run.saving:
            return Progress(text + " The desktop app is saving its sign-in first; this can still be called off.", True)
        return Progress(text, True)

    # --- the clock ---------------------------------------------------------------------------------------------------

    def tick(self) -> list[Event]:
        job = self._job
        if job is None or self._where == _ASKING:
            return []
        if self._where == _FAILED:
            self._job, self._where = None, ""
            return [Done(Outcome(False, f"Not done: the sync script could not be started ({self._failure})."), False,
                         job.kind)]
        if self._where == _WAIT_SESSIONS:
            self._at_work = self._sessions()
            if self._at_work == 0:
                self._launch()
        elif self._where == _WAIT_CLI:
            if self._clock() >= self._next_try:
                self._launch()
        elif self._run is not None:
            result = self._run.poll()
            if result is not None:
                return self._ended(job, result, self._run.cancelled)
        return []

    def _launch(self) -> None:
        assert self._job is not None
        try:
            self._run, self._where = self._start(self._job.argv), _RUN
        except OSError as exc:
            self._run, self._where, self._failure = None, _FAILED, str(exc)

    def _ended(self, job: _Job, result: Result, cancelled: bool) -> list[Event]:
        return [replace(event, kind=job.kind) if isinstance(event, Done) else event
                for event in self._end(job, result, cancelled)]

    def _end(self, job: _Job, result: Result, cancelled: bool) -> list[Event]:
        self._run = None
        if cancelled:
            self._job, self._where = None, ""
            return [Done(Outcome(False, "Cancelled; nothing was changed."), False)]
        if job.kind == CLI and result.code == EXIT_CLI_RUNNING:
            if self._waiting_for_cli:
                self._where, self._next_try = _WAIT_CLI, self._clock() + self._retry
                return []
            self._where = _ASKING
            return [AskCliIdle(job.label)]
        self._job, self._where = None, ""
        if job.kind == CLI and result.code == EXIT_NO_LOGIN:
            return [NeedsCliLogin(job.label)]
        if job.kind == APP and result.code == EXIT_SIGNED_OUT:
            # The script's own words, which say why the app refused the login and whether it could be set aside, kept
            # at the head of the status line in its warning colour through the pass that follows: the pass shows the
            # app at its sign-in page and the login set aside at once, rather than at the service's next pass.
            said = reason(result) + (f" {not_opened_words(len(job.carry))}" if job.carry else "")
            return [Done(Outcome(False, said), True)]
        if result.code != EXIT_OK:
            return [Done(Outcome(False, f"Not done: {reason(result)}"), False)]
        if job.kind in (ADD, START) and result.notes:
            # The script's word: for an add, whether the sign-in page was reached, or only started for, and whose login
            # was stored; for a start, whether the app was started or found running.
            return [Done(Outcome(True, result.notes[-1]), True)]
        done: list[Event] = [Done(Outcome(True, self._said(job)), True)]
        if job.kind == APP and job.carry:
            done.append(OpenSessions(job.carry, job.label))
        return done

    @staticmethod
    def _said(job: _Job) -> str:
        if job.kind == APP:
            return (f"Switched the desktop app to {job.label}." +
                    (" The CLI follows it as soon as no CLI is running." if job.follows else "") +
                    (f" {opening_words(len(job.carry))}" if job.carry else ""))
        if job.kind == CLI:
            return f"Switched the CLI to {job.label}."
        if job.kind == ADD:
            return "The desktop app is at its sign-in page: sign in there to the account to add."
        if job.kind == START:
            return "Started the desktop app."
        if job.switch == "follows":
            if job.value:
                return ("The CLI follows the desktop app again; it is aligned with the app as soon as no CLI is "
                        "running.")
            return "The CLI no longer follows the desktop app: the app and the CLI switch apart."
        if job.value:
            return "One-click switching of the desktop app is on."
        return "One-click switching of the desktop app is off; the logins already stored are kept."
