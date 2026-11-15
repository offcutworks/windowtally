"""Assigns an account to every response, every limit stop and every plugin reading, from the best evidence the ledger
holds.

A request runs on the account its client is signed in to at that moment:
    cli-timeline      a CLI session's response: the CLI's account at that moment, from the sync's events and log
    desktop-timeline  every other response: the desktop app's account at that moment, from the sync's events and the
                      app's samples; also a CLI response's before the first CLI event, the CLI following the app
    owner             where no timeline names an account — before either has a point, or while the desktop app was at
                      its sign-in page: the account the session's transcript names (desktop sessions), the last one
                      the ledger recorded where it names several

While the desktop app is at its sign-in page it is no account's, and its timeline names none from the sync's
``desktop_signed_out`` event until the app is signed in again. The app then hosts no session and sends no request, so
no response is expected in such a stretch; one that falls there takes the owner line, if its session has one.

A desktop session's transcript names an owning account on its bridge lines, and that name lags the desktop app: on
the development machine (2026-09-21 to 2026-10-21) sessions opened minutes to a day after the app switched account
still named the old one, while the plan figures that rose with their use were the new account's. So a timeline
outranks the owner line, which only fills in before the timelines begin.

A limit stop — a turn a plan limit refused — is the refusal of a request, so it takes the account a response of its
session would take at that moment, by the same evidence and revisited with the responses.

A plugin reading takes the account a response of its session would take at that moment, and its weekly reset time
then checks the answer. Each account's weekly window resets at its own instant, so a reading whose reset lies on
another account's weekly schedule and not on the answer's is that account's (``fingerprint``): a switch the timeline
recorded late. An account's schedule is the weekly reset most of the readings answered for it carry, so a few
misread readings never redefine it; a reset on no account's schedule — a schedule moved, an account with no readings
yet — leaves the answer standing.

Every assignment is derived again when its evidence changes — a timeline point, an owner line, a new reading — and
all of them when the rule itself changes (``RULE``), so no guess becomes permanent.
"""

from __future__ import annotations

import bisect
import logging
from collections import Counter
from dataclasses import dataclass

from .ledger import Ledger
from .limits import WEEK

log = logging.getLogger(__name__)

CLI_ENTRYPOINTS = ("cli", "sdk-cli", "sdk-ts", "sdk-py")
# Weekly reset times within this many seconds are the same reset (Claude Code reports them with jitter).
RESET_MATCH_TOLERANCE = 3600.0
# The rule the ledger's assignments were derived under, kept in its meta table: a ledger derived under another rule
# is derived again whole on its next attribution.
RULE = "2"


@dataclass
class Timeline:
    """Points (t, account) sorted by time; the account at x is that of the last point at or before x. A point whose
    account is None begins a stretch with no account: the desktop app at its sign-in page."""

    times: list[float]
    accounts: list[str | None]

    @classmethod
    def from_points(cls, points: list[tuple[float, str | None]]) -> Timeline:
        points = sorted(points, key=lambda p: (p[0], p[1] or ""))
        return cls([p[0] for p in points], [p[1] for p in points])

    def at(self, moment: float) -> str | None:
        index = bisect.bisect_right(self.times, moment) - 1
        return self.accounts[index] if index >= 0 else None


def desktop_timeline(ledger: Ledger) -> Timeline:
    points: list[tuple[float, str | None]] = [(t, a) for t, a in ledger.db.execute(
        "SELECT t, account_uuid FROM account_events WHERE kind='desktop_account'")]
    points += [(t, None) for (t,) in ledger.db.execute(
        "SELECT t FROM account_events WHERE kind='desktop_signed_out'")]
    points += [(t, a) for t, a in ledger.db.execute(
        "SELECT t, account_uuid FROM observations WHERE source='app' AND kind='seven_day' AND account_uuid IS NOT NULL")]
    return Timeline.from_points(points)


def cli_timeline(ledger: Ledger) -> Timeline:
    return Timeline.from_points([(t, a) for t, a in ledger.db.execute(
        "SELECT t, account_uuid FROM account_events WHERE kind='cli_account'")])


_TIMELINE_POINTS = ("SELECT t FROM account_events UNION ALL "
                    "SELECT t FROM observations WHERE source='app' AND account_uuid IS NOT NULL")


def _revisit_from(ledger: Ledger) -> tuple[bool, float | None]:
    """Whether the timelines moved since the last attribution, and from when their answers can have changed.

    A timeline answers for a moment from its last point at or before it, so points added after every point seen
    last time change only the answers from the earliest new point on. Any other change — a point inserted in the
    past, a sample given its account later — revisits every timeline answer (``None``).
    """
    count, latest = ledger.db.execute(f"SELECT COUNT(*), COALESCE(MAX(t), 0) FROM ({_TIMELINE_POINTS})").fetchone()
    signature = f"{count}:{latest!r}"
    previous = ledger.get_meta("attribution_timeline")
    if previous == signature:
        return False, None
    ledger.set_meta("attribution_timeline", signature)
    if previous is None:
        return True, None
    previous_count, previous_latest = previous.split(":")
    newer, earliest = ledger.db.execute(f"SELECT COUNT(*), MIN(t) FROM ({_TIMELINE_POINTS}) WHERE t > ?",
                                        (float(previous_latest),)).fetchone()
    if earliest is not None and count - int(previous_count) == newer:
        return True, earliest
    return True, None


def _owners_changed(ledger: Ledger) -> int | None:
    """When owner lines were recorded since the last attribution, the last owner row that attribution saw (rows after
    it are new); None when none were."""
    latest = ledger.db.execute("SELECT COALESCE(MAX(rowid), 0) FROM session_owners").fetchone()[0]
    previous = int(ledger.get_meta("attribution_owners") or 0)
    if latest == previous:
        return None
    ledger.set_meta("attribution_owners", str(latest))
    return previous


def _response_condition(moved: bool, since: float | None, owners_from: int | None) -> tuple[str, list[float]]:
    """The responses, and the limit stops, a pass revisits: every unassigned one, every one a moved timeline can now
    answer otherwise, and every one of a session whose transcript named an owner since the last attribution."""
    if moved and since is None:
        return "1", []
    clauses, params = ["account_source IS NULL"], []
    if moved:
        clauses.append("t >= ?")
        params.append(since)
    if owners_from is not None:
        clauses.append("session_id IN (SELECT session_id FROM session_owners WHERE rowid > ?)")
        params.append(owners_from)
    return " OR ".join(clauses), params


@dataclass(frozen=True)
class _Evidence:
    """What names the account a request ran on: the two timelines, and each session's owner line."""

    desktop: Timeline
    cli: Timeline
    owners: dict[str, str]  # session -> the owner its transcript named, the last one recorded where it names several

    @classmethod
    def read(cls, ledger: Ledger) -> _Evidence:
        owners = dict(ledger.db.execute("SELECT session_id, account_uuid FROM session_owners ORDER BY rowid"))
        return cls(desktop_timeline(ledger), cli_timeline(ledger), owners)

    def account_at(self, session: str, moment: float, cli: bool) -> tuple[str | None, str | None]:
        """The account a request of ``session`` ran on at ``moment``, and the evidence it rests on."""
        if cli:
            account = self.cli.at(moment)
            if account:
                return account, "cli-timeline"
        account = self.desktop.at(moment)
        if account:
            return account, "desktop-timeline"
        owner = self.owners.get(session)
        return (owner, "owner") if owner else (None, None)


def attribute(ledger: Ledger) -> int:
    """Brings every derived account up to date; returns how many rows were (re)assigned."""
    with ledger.transaction():
        whole = ledger.get_meta("attribution_rule") != RULE
        moved, since = _revisit_from(ledger)
        owners_from = _owners_changed(ledger)
        if whole:
            ledger.set_meta("attribution_rule", RULE)
        condition, params = ("1", []) if whole else _response_condition(moved, since, owners_from)
        evidence = _Evidence.read(ledger)
        changed = _attribute_responses(ledger, evidence, condition, params)
        changed += _attribute_stops(ledger, evidence, condition, params)
        new_readings = ledger.db.execute(
            "SELECT EXISTS(SELECT 1 FROM observations WHERE source='plugin' AND account_source IS NULL)").fetchone()[0]
        if whole or moved or owners_from is not None or new_readings:
            changed += _attribute_readings(ledger, evidence)
    return changed


def _attribute_responses(ledger: Ledger, evidence: _Evidence, condition: str, params: list[float]) -> int:
    rows = ledger.db.execute(
        f"SELECT message_id, t, entrypoint, session_id, account_uuid, account_source FROM responses WHERE {condition}",
        params).fetchall()
    changed = 0
    for message_id, t, entrypoint, session, current, current_source in rows:
        account, source = evidence.account_at(session, t, entrypoint in CLI_ENTRYPOINTS)
        if (account, source) != (current, current_source):
            ledger.db.execute("UPDATE responses SET account_uuid=?, account_source=? WHERE message_id=?",
                              (account, source, message_id))
            changed += 1
    return changed


def _attribute_stops(ledger: Ledger, evidence: _Evidence, condition: str, params: list[float]) -> int:
    rows = ledger.db.execute(
        f"SELECT line_uuid, t, entrypoint, session_id, account_uuid, account_source FROM limit_stops WHERE {condition}",
        params).fetchall()
    changed = 0
    for line_uuid, t, entrypoint, session, current, current_source in rows:
        account, source = evidence.account_at(session, t, entrypoint in CLI_ENTRYPOINTS)
        if (account, source) != (current, current_source):
            ledger.db.execute("UPDATE limit_stops SET account_uuid=?, account_source=? WHERE line_uuid=?",
                              (account, source, line_uuid))
            changed += 1
    return changed


def _on_schedule(reset: float, phase: float) -> bool:
    """Whether ``reset`` is one of the weekly instants at ``phase`` (seconds into the week, modulo a week)."""
    offset = (reset - phase) % WEEK
    return min(offset, WEEK - offset) <= RESET_MATCH_TOLERANCE


def _schedules(answers: dict[tuple[str, float], tuple[str | None, str | None]],
               resets: dict[tuple[str, float], float | None]) -> dict[str, float]:
    """Each account's weekly schedule: the phase of the week, to the minute, that most of the readings answered for it
    carry as their weekly reset — the earliest such phase where two are as common."""
    counts: dict[str, Counter] = {}
    for key, (account, _) in answers.items():
        reset = resets.get(key)
        if account is not None and reset is not None:
            counts.setdefault(account, Counter())[round(reset % WEEK / 60.0) * 60.0 % WEEK] += 1
    return {account: min(phases, key=lambda phase: (-phases[phase], phase)) for account, phases in counts.items()}


def _checked(answer: tuple[str | None, str | None], reset: float | None,
             schedules: dict[str, float]) -> tuple[str | None, str | None]:
    """``answer``, unless the reading's weekly reset lies on exactly one account's schedule and not on the answer's."""
    if reset is None:
        return answer
    on = [account for account, phase in schedules.items() if _on_schedule(reset, phase)]
    if answer[0] in on or len(on) != 1:
        return answer
    return on[0], "fingerprint"


def _attribute_readings(ledger: Ledger, evidence: _Evidence) -> int:
    """Every plugin reading, derived again whole: an account's schedule rests on all the readings answered for it."""
    marks = ",".join("?" * len(CLI_ENTRYPOINTS))
    cli_sessions = {session for (session,) in ledger.db.execute(
        f"SELECT DISTINCT session_id FROM responses WHERE session_id IN "
        f"(SELECT ref FROM observations WHERE source='plugin') AND entrypoint IN ({marks})", CLI_ENTRYPOINTS)}
    rows = ledger.db.execute("SELECT ref, t, kind, resets_at, account_uuid, account_source FROM observations "
                             "WHERE source='plugin'").fetchall()
    resets = {(ref, t): resets_at for ref, t, kind, resets_at, _, _ in rows if kind == "seven_day"}
    answers: dict[tuple[str, float], tuple[str | None, str | None]] = {}
    for ref, t, *_ in rows:
        if (ref, t) not in answers:
            answers[(ref, t)] = evidence.account_at(ref, t, ref in cli_sessions)
    schedules = _schedules(answers, resets)
    changed = 0
    for ref, t, kind, _, current, current_source in rows:
        account, source = _checked(answers[(ref, t)], resets.get((ref, t)), schedules)
        if (account, source) != (current, current_source):
            ledger.db.execute("UPDATE observations SET account_uuid=?, account_source=? "
                              "WHERE source='plugin' AND ref=? AND t=? AND kind=?", (account, source, ref, t, kind))
            changed += 1
    return changed
