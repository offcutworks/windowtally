"""What a switch of the desktop app offers to carry to the account switched to, and the links that carry it. No toolkit.

The desktop app lists a Code session only while it is signed in to the account the session was filed under, so a switch
leaves the account's sessions out of sight. Before the app is switched, the window offers the sessions of the account
it leaves (``windowtally.sessions``) with those at work now (Claude Code's session registry), one row each: a session a plan limit
stopped first, its stop the newest first, then those working, then those with background work that never reported
back, then the rest by their last activity. A stopped or working session is ticked at the start, and so are one whose
background work is unfinished, whose turn is over while its work is not, and one active within ``JUST_USED`` before
the switch, being what the user was working in; the rest are not. Background work does not go on with the session: the
task went with the app, so the row says only that it is unfinished and the dialog that it is to be run again.

Once the switch has ended with the app signed in, each session ticked is opened through the app's resume link,
``claude://resume?session=<id>``, ``id`` being the session's own (its transcript's, which the app keeps as its card's
``cliSessionId``), the links ``LINK_GAP`` seconds apart (``LinkQueue``). Measured on the development machine,
2026-11-07, desktop app 3.6556.2.0: the link has the app adopt a session of another account under the account it is
signed in to, which then answers there; the card it makes keeps the title but not the session's effort, and its
permission mode may fall back to the default. Read in desktop app 4.23118.1.0, 2026-11-11: the link carries the
session's id alone, and the app takes the session's model and permission mode from its transcript's last lines, the
mode from the settings' default where those lines name none and a bypass lowered to accept edits, and its effort from
nothing. So each row says what the session ran with (``ran_with``), in the app's own words, and the user is told to set
both again. The link right after a switch, the app just started, was not measured; the gap leaves the app a moment
between two.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Callable
from urllib.parse import quote

from windowtally.sessions import SessionLine

from .formatting import ago, plural

RESUME_LINK = "claude://resume?session={}"
LINK_GAP = 2.0       # seconds between two links, and from the switch's end to the first
JUST_USED = 15 * 60.0  # seconds before the switch within which a session's last activity has it ticked at the start

STOP_WORDS = {"five_hour": "Stopped by the 5-hour limit", "seven_day": "Stopped by the weekly limit",
              "": "Stopped by a limit"}
WORKING = "Working"
UNFINISHED = "Background work unfinished"
LEFT_BEHIND = "set the permission mode and effort again in each"
# The permission modes as the desktop app names them (desktop app 4.23118.1.0); ``manual`` is the CLI's later name for
# ``default``. An effort, or a mode of other letters, is shown as it is written, and one of anything else not at all.
MODE_WORDS = {"default": "Manual", "manual": "Manual", "acceptEdits": "Accept edits", "plan": "Plan", "auto": "Auto",
              "bypassPermissions": "Bypass permissions", "dontAsk": "Don't ask"}
RAN_WITH_GAP = " · "


@dataclass(frozen=True)
class CarryRow:
    session_id: str
    title: str           # the session as the list names it
    state: str           # how a limit stopped it, that it is working or has background work unfinished, or nothing
    last: str            # its last activity, as an age
    ticked: bool         # ticked at the start
    background: bool = False   # background work of its own is unfinished, whatever its state says first
    ran_with: str = ""   # the effort and permission mode it last ran with (``ran_with``), or nothing where unknown


def resume_link(session_id: str) -> str:
    return RESUME_LINK.format(quote(session_id, safe=""))


def _word(value: str | None) -> str | None:
    """``value`` where it is one word of letters, as every effort and mode Claude Code writes is; None otherwise."""
    return value if value and value.isascii() and value.isalpha() and len(value) <= 32 else None


def mode_word(mode: str | None) -> str | None:
    """A permission mode as the desktop app names it, or None where there is none to name."""
    return MODE_WORDS[mode] if mode in MODE_WORDS else _word(mode)


def ran_with(effort: str | None, mode: str | None) -> str:
    """What a session last ran with, as both lists say it: its effort as Claude Code writes it, then its permission
    mode in the app's words, ``max · Auto``; either alone where the other is unknown, nothing where both are."""
    return RAN_WITH_GAP.join(part for part in (_word(effort), mode_word(mode)) if part)


def shown_title(title: str | None, folder: str | None) -> str:
    """A session as every list names it: its title, or where its transcript gave none, the folder it was started in.
    The Conversations window names a session this way too (``conversations_model``)."""
    if title and title.strip():
        return title.strip()
    name = PureWindowsPath(folder).name if folder else ""
    return f"Untitled session in {name}" if name else "Untitled session"


def _shown(line: SessionLine | None) -> str:
    return shown_title(line.title, line.project) if line is not None else shown_title(None, None)


def _ran(line: SessionLine | None) -> str:
    return ran_with(line.effort, line.mode) if line is not None else ""


def carry_rows(lines: list[SessionLine], working: frozenset[str], now: float,
               asked: float | None = None) -> tuple[CarryRow, ...]:
    """The rows the switch offers, in the order they stand: the stopped, the working, those with background work
    unfinished, then the rest, those of the rest active within ``JUST_USED`` ticked; a working session the ledger does
    not hold yet among the working, by its id alone. ``asked`` is when the switch was asked for, ``now`` where not
    given: what was just used is counted from it, so the pass a switch may wait for first takes no session out of the
    ticked."""
    asked = now if asked is None else asked
    known = {line.session_id: line for line in lines}
    stopped = [line for line in lines if line.stopped and line.session_id not in working]
    stopped.sort(key=lambda line: (-line.last_activity, line.session_id))
    at_work = sorted(working, key=lambda session: (-(known[session].last_activity if session in known else now),
                                                    session))
    idle = [line for line in lines if not line.stopped and line.session_id not in working]
    rows = [CarryRow(line.session_id, _shown(line), STOP_WORDS.get(line.stop_kind or "", STOP_WORDS[""]),
                     ago(now - line.last_activity), True, line.unfinished > 0, _ran(line)) for line in stopped]
    rows += [CarryRow(session, _shown(known.get(session)), WORKING, "now", True,
                      session in known and known[session].unfinished > 0, _ran(known.get(session)))
             for session in at_work]
    rows += [CarryRow(line.session_id, _shown(line), UNFINISHED, ago(now - line.last_activity), True, True, _ran(line))
             for line in idle if line.unfinished]
    rows += [CarryRow(line.session_id, _shown(line), "", ago(now - line.last_activity),
                      asked - line.last_activity <= JUST_USED, False, _ran(line))
             for line in idle if not line.unfinished]
    return tuple(rows)


def opening_words(count: int) -> str:
    """What the end of a switch says of the sessions it opens."""
    return f"Opening {plural(count, 'session')} there: {LEFT_BEHIND}."


def not_opened_words(count: int) -> str:
    """What the end of a switch that left the app at its sign-in page says of the sessions chosen."""
    return f"The {plural(count, 'session')} chosen {'was' if count == 1 else 'were'} not opened."


@dataclass(frozen=True)
class Failure:
    title: str
    error: str


class LinkQueue:
    """The sessions a switch carries, opened in the desktop app one at a time, ``gap`` seconds apart and the first
    ``gap`` seconds after they are added, through ``open_link`` (the shell's own opener). ``tick`` opens the one due and
    answers each that could not be opened; an opener that fails is said and the rest go on."""

    def __init__(self, open_link: Callable[[str], object], *, clock: Callable[[], float] = time.monotonic,
                 gap: float = LINK_GAP):
        self.open_link, self._clock, self.gap = open_link, clock, gap
        self._waiting: list[tuple[str, str]] = []
        self._due = 0.0

    @property
    def pending(self) -> int:
        return len(self._waiting)

    def add(self, sessions: tuple[tuple[str, str], ...]) -> None:
        """``sessions`` are each a session's id and its title."""
        if not self._waiting:
            self._due = self._clock() + self.gap
        self._waiting.extend(sessions)

    def tick(self, now: float | None = None) -> list[Failure]:
        now = self._clock() if now is None else now
        if not self._waiting or now < self._due:
            return []
        session_id, title = self._waiting.pop(0)
        self._due = now + self.gap
        try:
            self.open_link(resume_link(session_id))
        except OSError as exc:
            return [Failure(title, str(exc))]
        return []

    def progress_words(self) -> str | None:
        """What the header says while sessions wait to be opened."""
        return f"Opening {plural(self.pending, 'session')} in the desktop app…" if self._waiting else None
