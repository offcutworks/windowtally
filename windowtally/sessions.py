"""The Code sessions the ledger holds, read for the window: every account's (``conversations``), and the desktop app's
sessions of one account that a switch of the app can carry to the account switched to (``sessions_of``).

The desktop app lists a session only while it is signed in to the account the session's card is filed under, so a switch
leaves the account's sessions behind, and the app has no list across accounts. A session is an account's when the
latest thing the ledger holds of it, an answer or a turn a plan limit refused, ran on that account; one carried on since
to another account is that account's; a stop not yet given an account leaves the session its latest answer's. A stop
stands while no answer came after it: the session is waiting on the limit. Which client ran a session is read from any
of its answers or stops, a subagent's carrying its session's entry point.
A background task a session started, a command or a subagent left to run on beside it, is unfinished while no
transcript says it ended (``ingest_transcripts``): the session's work is not done, whether the task still runs or went
with a client that closed. ``sessions_of`` counts those a session started within its span.
A session's folder is the one its first main answer ran in, where it was started: the working folder an answer names
moves with every change of directory the session makes.
What a session ran with is the effort its latest main answer ran at and the permission mode its transcript last named
(``ingest_transcripts``): the desktop app, opening a session another account ran, takes its effort from nothing and its
mode only where its transcript's last lines name one, so both readers give them for the user to set again.

``conversations`` lists the sessions the desktop app's Code tab or the CLI ran — those with an answer or a stop from
either — and leaves out the runs of the SDK and of ``claude -p``, which Claude Code's own list of sessions to resume
leaves out too (Claude Code 2.1.310). A conversation the desktop app went on with in a new transcript is two sessions
here, as it is in that list: no line of either transcript names the other (measured on the development machine,
2026-11-09, Claude Code 2.1.308 and 2.1.310: no transcript held a ``continued-in`` or ``forkedFrom`` line, while some of
the app's cards named earlier transcripts of their own). Its few queries read each table once, the answers once more for
the latest main answer's effort, grouped by session, every bare column of a group taken from the row of its one ``MIN``
or ``MAX``, as SQLite defines; a large ledger still takes long enough to stall a window, so the window reads it off its
own thread.

``sessions_of`` offers only sessions the desktop app hosted — those with an answer or a stop from its Code tab — since it
is the app that opens them again. ``CARRY_SPAN`` bounds how far back a session counts: a stopped session that was gone
on with was gone on with within hours (measured on the development machine, 2026-11-08), so a day holds what a switch
is made to carry on, and an older session is not one the switch is for.

Both readers ask ``has_table`` first, the tables of titles, modes and stops being newer than the ledger's version
(``ledger``), so a ledger no pass of this code has opened gives its sessions without titles, modes or stops.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ledger import Ledger

CARRY_SPAN = 24 * 3600.0
DESKTOP_ENTRYPOINT = "claude-desktop"
CLI_ENTRYPOINT = "cli"


@dataclass(frozen=True)
class SessionLine:
    session_id: str
    title: str | None         # as its transcript last gave it; None where it gave none yet
    project: str | None       # the folder the session was started in, from its first main answer
    last_activity: float      # its latest answer, prompt or stop
    stop_kind: str | None     # the window of the stop that stands — five_hour, seven_day or unknown ("") — or None
    stop_resets: float | None  # when that window resets, where the transcript said
    unfinished: int = 0       # the background tasks it started within the span that no transcript says have ended
    effort: str | None = None  # the effort its latest main answer ran at; None where none said
    mode: str | None = None   # the permission mode its transcript last named; None where none did

    @property
    def stopped(self) -> bool:
        return self.stop_kind is not None


def _latest(answer: tuple | None, stop: tuple | None, prompted: float | None) -> tuple[bool, str | None, float]:
    """From a session's latest answer and latest stop, each ``(t, account)`` or None, and its latest prompt's time:
    whether the stop stands, whose the session is — the account of the later of the two, the answer's where a stop
    that stands has no account yet — and its last activity. Both readers decide by it, so a session is one account's
    on every surface."""
    answered_at, answered_by = answer if answer else (None, None)
    stands = stop is not None and (answered_at is None or stop[0] > answered_at)
    whose = (stop[1] or answered_by) if stands else answered_by
    last = max(t for t in (answered_at, stop[0] if stop else None, prompted) if t is not None)
    return stands, whose, last


def sessions_of(ledger: Ledger, account_uuid: str, now: float, span: float = CARRY_SPAN) -> list[SessionLine]:
    """The account's desktop sessions active within ``span`` before ``now``, the latest first."""
    since = now - span
    with_stops = ledger.has_table("limit_stops")
    with_titles = ledger.has_table("session_titles")
    with_tasks = ledger.has_table("background_tasks")
    with_modes = ledger.has_table("session_modes")
    candidates = {row[0] for row in ledger.db.execute(
        "SELECT DISTINCT session_id FROM responses WHERE account_uuid=? AND t>=? AND entrypoint=?",
        (account_uuid, since, DESKTOP_ENTRYPOINT))}
    if with_stops:
        candidates |= {row[0] for row in ledger.db.execute(
            "SELECT DISTINCT session_id FROM limit_stops WHERE account_uuid=? AND t>=? AND entrypoint=?",
            (account_uuid, since, DESKTOP_ENTRYPOINT))}
    lines = []
    for session_id in candidates:
        answer = ledger.db.execute("SELECT t, account_uuid FROM responses WHERE session_id=? "
                                   "ORDER BY t DESC LIMIT 1", (session_id,)).fetchone()
        stop = ledger.db.execute("SELECT t, account_uuid, kind, resets_at FROM limit_stops WHERE session_id=? "
                                 "ORDER BY t DESC LIMIT 1", (session_id,)).fetchone() if with_stops else None
        prompted = ledger.db.execute("SELECT MAX(t) FROM prompts WHERE session_id=?", (session_id,)).fetchone()[0]
        stands, latest_account, last = _latest(answer, stop[:2] if stop else None, prompted)
        if latest_account != account_uuid:
            continue
        started = ledger.db.execute("SELECT cwd FROM responses WHERE session_id=? AND agent_id IS NULL "
                                    "ORDER BY t LIMIT 1", (session_id,)).fetchone()
        title = ledger.db.execute("SELECT title FROM session_titles WHERE session_id=?",
                                  (session_id,)).fetchone() if with_titles else None
        unfinished = ledger.db.execute(
            "SELECT COUNT(*) FROM background_tasks WHERE session_id=? AND started>=? "
            "AND (ended IS NULL OR ended<started)", (session_id, since)).fetchone()[0] if with_tasks else 0
        effort = ledger.db.execute("SELECT effort FROM responses WHERE session_id=? AND agent_id IS NULL "
                                   "ORDER BY t DESC LIMIT 1", (session_id,)).fetchone()
        mode = ledger.db.execute("SELECT mode FROM session_modes WHERE session_id=?",
                                 (session_id,)).fetchone() if with_modes else None
        lines.append(SessionLine(session_id=session_id, title=title[0] if title else None,
                                 project=started[0] if started else None, last_activity=last,
                                 stop_kind=(stop[2] or "") if stands else None,
                                 stop_resets=stop[3] if stands else None, unfinished=unfinished,
                                 effort=effort[0] if effort else None, mode=mode[0] if mode else None))
    lines.sort(key=lambda line: (-line.last_activity, line.session_id))
    return lines


@dataclass(frozen=True)
class Conversation:
    session_id: str
    title: str | None          # as its transcript last gave it; None where it gave none yet
    folder: str | None         # the folder it was started in, from its first main answer; None with no main answer
    last_activity: float       # its latest answer, prompt or stop
    account_uuid: str | None   # whose it is: its latest answer's or a standing stop's account; None where not known
    used_usd: float            # what its answers, its subagents' among them, would have cost at API prices
    desktop: bool              # the desktop app's Code tab ran it, so the app keeps a card of it to open
    stop_kind: str | None      # the window of the stop that stands, as ``SessionLine.stop_kind``; None where none does
    effort: str | None = None  # the effort its latest main answer ran at; None where none said
    mode: str | None = None    # the permission mode its transcript last named; None where none did

    @property
    def stopped(self) -> bool:
        return self.stop_kind is not None


def conversations(ledger: Ledger) -> list[Conversation]:
    """Every session the desktop app's Code tab or the CLI ran, whatever its account, the latest activity first."""
    ran = (DESKTOP_ENTRYPOINT, CLI_ENTRYPOINT)
    # A subagent's answer carries its session's entry point, so any answer says which client ran the session, as
    # ``sessions_of`` reads it; the folder is the first main answer's.
    answers = {row[0]: row[1:] for row in ledger.db.execute(
        "SELECT session_id, MAX(t), account_uuid, COALESCE(SUM(cost_usd), 0), SUM(entrypoint=?), SUM(entrypoint=?) "
        "FROM responses GROUP BY session_id", ran)}
    folders = {row[0]: row[2] for row in ledger.db.execute(
        "SELECT session_id, MIN(t), cwd FROM responses WHERE agent_id IS NULL GROUP BY session_id")}
    efforts = {row[0]: row[2] for row in ledger.db.execute(
        "SELECT session_id, MAX(t), effort FROM responses WHERE agent_id IS NULL GROUP BY session_id")}
    modes = dict(ledger.db.execute("SELECT session_id, mode FROM session_modes")) \
        if ledger.has_table("session_modes") else {}
    stops = {row[0]: row[1:] for row in ledger.db.execute(
        "SELECT session_id, MAX(t), account_uuid, kind, SUM(entrypoint=?), SUM(entrypoint=?) FROM limit_stops "
        "GROUP BY session_id", ran)} if ledger.has_table("limit_stops") else {}
    prompted = dict(ledger.db.execute("SELECT session_id, MAX(t) FROM prompts GROUP BY session_id"))
    titles = dict(ledger.db.execute("SELECT session_id, title FROM session_titles")) \
        if ledger.has_table("session_titles") else {}
    found = []
    for session_id in answers.keys() | stops.keys():
        answer, stop = answers.get(session_id), stops.get(session_id)
        desktop = bool(answer and answer[3]) or bool(stop and stop[3])
        if not (desktop or bool(answer and answer[4]) or bool(stop and stop[4])):
            continue
        stands, whose, last = _latest(answer[:2] if answer else None, stop[:2] if stop else None,
                                      prompted.get(session_id))
        found.append(Conversation(
            session_id=session_id, title=titles.get(session_id), folder=folders.get(session_id),
            last_activity=last, account_uuid=whose, used_usd=float(answer[2]) if answer else 0.0, desktop=desktop,
            stop_kind=(stop[2] or "") if stands else None, effort=efforts.get(session_id),
            mode=modes.get(session_id)))
    found.sort(key=lambda c: (-c.last_activity, c.session_id))
    return found
