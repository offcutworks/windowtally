"""What each product took of an account's weekly window, as claude.ai's usage page reports it under "This week's usage
by product" — Claude Code, Chats, Cowork, Other — read by the browser extension from the usage response the page itself
receives, written by its host (``browser_host``) and kept by the ledger (``product_shares``, one row per product).

A report is the week's use so far split by product: shares in whole percents as claude.ai gives them, summing to about
100, each named by claude.ai's key and by the words its page shows. Which products there are is claude.ai's, so a
product it adds is carried and shown under its own name, in the page's order. The shares are cumulative over the
weekly window the report names by its start, so the last report of a window stands for that window. claude.ai's
window start jitters below a second between two responses (measured in Chrome on the development machine,
2026-11-02), so two reports are of one window when their starts lie within ``SAME_WINDOW`` of each other, never by
equality.

The shares are an addition to the weekly window and never a part of it: no figure, warning, recommendation or measure
rests on them, and every reader goes on unchanged without them — a ledger with no report, a ledger no pass of this code
has opened yet (``Ledger.has_table``), an account whose browser has no extension or whose claude.ai page has not asked
for its usage since the window began. A report is only as fresh as the page's last request, made on opening the usage
settings and after a message, so every surface that shows one says how old it is.

An account's current report (``current``) is its latest one whose window has not ended; where the account's weekly
reset time was read rather than inferred, the report's window must also be the one that reset time ends, so a reset
time that has moved retires the report of the window before it. An inferred reset time may be hours off and
would retire a current report, so it is not compared.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .ledger import Ledger
from .limits import WEEK, AccountStanding

TABLE = "product_shares"
SAME_WINDOW = 3600.0   # two window starts this close name one weekly window; real windows are a week apart


@dataclass(frozen=True)
class Share:
    key: str            # claude.ai's key: claude_code, chat, cowork, other, or one it adds
    name: str           # the words claude.ai's page shows for it
    percent: float      # of the window's use up to the report


@dataclass(frozen=True)
class Report:
    account_uuid: str | None
    ref: str            # the organization claude.ai reported for
    t: float            # when the page received the report
    as_of: float        # when claude.ai computed it
    window_start: float
    shares: tuple[Share, ...]   # in the page's order
    weekly: float | None        # the weekly figure the same response carried, where the reading kept one

    @property
    def used(self) -> tuple[Share, ...]:
        """The shares above zero, in the page's order: what a surface lists."""
        return tuple(share for share in self.shares if share.percent > 0)


def shares_text(shares: Iterable[Share]) -> str:
    """``Claude Code 99%, Chats 1%``."""
    return ", ".join(f"{share.name} {share.percent:.0f}%" for share in shares)


def reports(ledger: Ledger, account: str, since: float | None = None, until: float | None = None) -> list[Report]:
    """The account's reports computed from ``since`` up to ``until``, oldest first; none where the ledger has no table
    for them.

    A report is one moment claude.ai computed (``as_of``) for one organization, its rows kept once each by product. A
    report received again keeps the rows first received, so it stands as the first reading that carried it: that
    reading's time, its weekly figure, its rows in their order and after them any product a later reading of the same
    moment added."""
    if not ledger.has_table(TABLE):
        return []
    query = ("SELECT p.ref, p.t, p.as_of, p.window_start, p.key, p.name, p.percent, "
             "(SELECT o.percent FROM observations o WHERE o.source=p.source AND o.ref=p.ref AND o.t=p.t "
             "AND o.kind='seven_day') FROM product_shares p WHERE p.account_uuid=?")
    params: list[object] = [account]
    if since is not None:
        query += " AND p.as_of>=?"
        params.append(since)
    if until is not None:
        query += " AND p.as_of<=?"
        params.append(until)
    query += " ORDER BY p.as_of, p.ref, p.t, p.position"
    found: list[Report] = []
    for ref, t, as_of, window_start, key, name, percent, weekly in ledger.db.execute(query, params):
        if not found or (found[-1].ref, found[-1].as_of) != (ref, as_of):
            found.append(Report(account, ref, t, as_of, window_start, (), weekly))
        last = found[-1]
        found[-1] = Report(account, ref, last.t, as_of, last.window_start, last.shares + (Share(key, name, percent),),
                           last.weekly)
    return found


def current(ledger: Ledger, account: str, now: float, resets_at: float | None = None,
            reset_exact: bool = False) -> Report | None:
    """The account's current report: its latest whose window has not ended at ``now`` and, where the weekly reset
    time ``resets_at`` was read (``reset_exact``), whose window that reset time ends; None where there is none."""
    for report in reversed(reports(ledger, account, since=now - WEEK)):
        if report.window_start + WEEK <= now:
            return None
        if reset_exact and resets_at is not None and abs(resets_at - WEEK - report.window_start) > SAME_WINDOW:
            return None
        return report
    return None


def current_reports(ledger: Ledger, standings: Iterable[AccountStanding], now: float) -> dict[str, Report]:
    """Every account's current report, by UUID, judged against its weekly standing; an account with none is absent."""
    found = {}
    for standing in standings:
        weekly = standing.weekly
        report = current(ledger, standing.account.uuid, now, weekly.resets_at, weekly.reset_exact)
        if report is not None:
            found[standing.account.uuid] = report
    return found


def last_of_windows(ledger: Ledger, account: str, since: float, until: float) -> list[Report]:
    """The last report of each of the account's weekly windows with a report computed from ``since`` up to ``until``,
    oldest first."""
    windows: list[Report] = []
    for report in reports(ledger, account, since=since, until=until):
        if windows and abs(report.window_start - windows[-1].window_start) <= SAME_WINDOW:
            windows[-1] = report
        else:
            windows.append(report)
    return windows
