"""The desktop notifications the window raises: only what the desktop plugin never says, so none repeats a toast a Code
session already gave (the maintainer's decision, 2026-10-21). The plugin warns as the account a session uses crosses
its limits; the window says instead:

    relief      every account was at its limit, with a moment the first opens, and one is usable again
    stopped     the service has written no status for ``STALE_AFTER``, counted from when this window started, so a
                status left from before a logon is not taken for a stopped service while the service starts up
    renewal     a listed account's recorded period ends within the user's renewal reminder — once per period; an
                account the user hid raises none
    problem     a source problem that has stood through two status files in a row, not one pass's blip — once until
                it clears

What was already said lives in the window's own record (``state_model``), so a renewal or a standing problem is not
said again at the next logon; a relief or a stopped service is said once per occurrence the window sees.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .formatting import day_text, plural, span, when
from .live_model import STALE_AFTER
from .state_model import WindowState
from .status_model import Snapshot, Status


@dataclass(frozen=True)
class Notice:
    kind: str          # relief | stopped | renewal | problem
    title: str
    message: str


def _blocked(status: Status) -> bool:
    """Every account at its limit, as the header judges it (``live_model.header``): none recommended and a moment the
    first opens. None recommended with no such moment may be every account hidden or its plan ended, which no reset
    relieves."""
    return bool(status.accounts) and status.recommended_account is None and status.relief_at is not None


def _renewal_key(uuid: str, paid_until: str) -> str:
    return f"{uuid} {paid_until}"


class Notices:
    """Decides which notices are due. ``on_status`` judges each new status file once — a relief, a renewal and a
    problem are about what the files say — and returns the notices with the record as it now stands; ``on_clock``
    judges, as time passes, whether the files have stopped coming."""

    def __init__(self, started: float):
        self.started = started
        self._was_blocked = False
        self._stopped_said = False
        self._last_problems: frozenset[str] | None = None

    def on_status(self, snapshot: Snapshot, state: WindowState) -> tuple[list[Notice], WindowState]:
        status = snapshot.status if snapshot.kind == "ok" else None
        if status is None:
            return [], state
        notices = self._relief(status)
        renewals, state = self._renewals(status, state)
        problems, state = self._problems(status, state)
        return notices + renewals + problems, state

    def on_clock(self, snapshot: Snapshot | None, now: float) -> list[Notice]:
        # A file of another version is the window's own trouble, which the window says; it is not a stopped service.
        if snapshot is None or snapshot.kind not in ("ok", "missing"):
            return []
        written = snapshot.status.generated_at if snapshot.kind == "ok" else None
        quiet_since = max(self.started, written or 0.0)
        if now - quiet_since <= STALE_AFTER:
            self._stopped_said = False
            return []
        if self._stopped_said:
            return []
        self._stopped_said = True
        if written is None:
            return [Notice("stopped", "WindowTally is not writing its status",
                           f"No status for {span(now - quiet_since)}. Is the WindowTally service running?")]
        return [Notice("stopped", "WindowTally stopped writing its status",
                       f"The last status was written {when(written)}, {span(now - written)} ago. "
                       "Is the WindowTally service running?")]

    def _relief(self, status: Status) -> list[Notice]:
        blocked = _blocked(status)
        was_blocked, self._was_blocked = self._was_blocked, blocked
        if not was_blocked or blocked:
            return []
        account = status.account(status.recommended_account)
        name = account.label if account else "An account"
        return [Notice("relief", f"{name} can be used again", status.recommended_reason)]

    def _renewals(self, status: Status, state: WindowState) -> tuple[list[Notice], WindowState]:
        due = {}
        for account in status.listed:
            s = account.subscription
            if s is not None and s.renew_soon and s.paid_until:
                due[_renewal_key(account.uuid, s.paid_until)] = (account, s)
        notices = []
        for key, (account, s) in due.items():
            if key in state.renewals_notified:
                continue
            left = "today" if (s.days_left or 0) <= 0 else f"in {plural(s.days_left, 'day')}"
            notices.append(Notice("renewal", f"{account.label}: the plan ends {left}",
                                  f"{s.plan_name or 'The recorded plan'} is paid until {day_text(s.paid_until)}. "
                                  "Record the next bill once it is charged."))
        # Keep only the keys still due: a period renewed, or a reminder turned off, is forgotten.
        kept = tuple(sorted(due))
        if kept != state.renewals_notified:
            state = replace(state, renewals_notified=kept)
        return notices, state

    def _problems(self, status: Status, state: WindowState) -> tuple[list[Notice], WindowState]:
        present = frozenset(status.source_errors)
        last, self._last_problems = self._last_problems, present
        notified = set(state.problems_notified) & present
        confirmed = present & last if last is not None else frozenset()
        new = sorted(confirmed - notified)
        notices = []
        if new:
            title = "A new source problem" if len(new) == 1 else f"{len(new)} new source problems"
            notices.append(Notice("problem", title, new[0] if len(new) == 1 else "; ".join(new)))
        recorded = tuple(sorted(notified | set(new)))
        if recorded != state.problems_notified:
            state = replace(state, problems_notified=recorded)
        return notices, state
