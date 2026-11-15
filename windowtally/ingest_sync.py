"""Reads the account sync's records: account change events, the older sync log, and the watcher's current view.

``events.jsonl`` (and its rotated ``events.jsonl.1``) holds one ``{"t", "kind", "account"}`` object per line,
``kind`` being ``cli_account`` (the CLI's trusted account changed), ``desktop_account`` (the desktop app is signed in
to the account: the watcher saw it change, or started, a switch made it, or the sync started the app on it) or
``desktop_signed_out`` (the app is at its sign-in page: the watcher saw it, a desktop mode read it in the app's log, or
the sync started the app there; ``account`` is the account the app's storage still names, the one it was signed out
of). ``sync.log`` (and ``sync.log.1``) predates the events; its switch
and sign-in lines name the account by e-mail. ``watch.json`` is the watcher's latest view: ``desktopAccount``,
``cliAccount``, ``condition`` (what keeps the CLI from following, or null) and ``desktopSignedIn``, written only as
false, while the app is at its sign-in page and ``desktopAccount`` null; absent, the app is signed in or its sign-in
is not known, and ``desktopAccount`` is read as it stands; and ``desktopRunning``, written only as false, while none of
the app's processes runs, ``desktopAccount`` still naming the account the app's storage names; absent, the app runs or
whether it runs is not known. The watcher writes the view whenever it changes, and at every look while the app is not
running, so ``t`` stays newer than any event written before the look.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .ledger import Cursor, Ledger
from .timeutil import parse_iso

log = logging.getLogger(__name__)

EVENT_KINDS = ("cli_account", "desktop_account", "desktop_signed_out")
_LOG_LINE = re.compile(r"^(?P<t>\S+) \[[a-z]+\] (?P<text>.*)$")
_LOG_CLI_ACCOUNT = re.compile(r"^(?:Switched the CLI to (?P<switched>\S+) to match the desktop app\."
                              r"|Signed in as (?P<signed>\S+) and stored it)")


@dataclass(frozen=True)
class WatchView:
    t: float | None
    desktop_account: str | None
    cli_account: str | None
    condition: str | None
    desktop_signed_out: bool = False   # the desktop app is at its sign-in page, and so no account's
    desktop_not_running: bool = False  # none of the desktop app's processes runs


def _changed(ledger: Ledger, path: Path) -> tuple[bool, int, float]:
    try:
        status = path.stat()
    except FileNotFoundError:
        return False, 0, 0.0
    previous = ledger.cursor(str(path))
    unchanged = previous is not None and previous.size == status.st_size and previous.mtime == status.st_mtime
    return not unchanged, status.st_size, status.st_mtime


def _insert_event(ledger: Ledger, t: float, kind: str, account: str, source: str) -> int:
    cursor = ledger.db.execute(
        "INSERT OR IGNORE INTO account_events(t, kind, account_uuid, source) VALUES (?, ?, ?, ?)",
        (t, kind, account.lower(), source))
    return cursor.rowcount


def ingest_sync_events(ledger: Ledger, events_path: Path) -> int:
    added = 0
    for path in (events_path.with_name(events_path.name + ".1"), events_path):
        changed, size, mtime = _changed(ledger, path)
        if not changed:
            continue
        with ledger.transaction():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    t, kind, account = parse_iso(record["t"]), record["kind"], record["account"]
                except (ValueError, KeyError, TypeError):
                    log.warning("Skipping malformed sync event %s:%d", path, number)
                    continue
                if t is None or kind not in EVENT_KINDS or not account:
                    log.warning("Skipping sync event %s:%d with an unknown shape", path, number)
                    continue
                added += _insert_event(ledger, t, kind, account, "events")
            ledger.set_cursor(str(path), Cursor(offset=0, size=size, mtime=mtime))
    return added


def ingest_sync_log(ledger: Ledger, log_path: Path, email_to_account: dict[str, str]) -> int:
    """The CLI's account changes recorded in the sync log, by e-mail; an e-mail with no stored account is skipped."""
    added = 0
    for path in (log_path.with_name(log_path.name + ".1"), log_path):
        changed, size, mtime = _changed(ledger, path)
        if not changed:
            continue
        with ledger.transaction():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                match = _LOG_LINE.match(line)
                if not match:
                    continue
                event = _LOG_CLI_ACCOUNT.match(match["text"])
                t = parse_iso(match["t"])
                if not event or t is None:
                    continue
                email = (event["switched"] or event["signed"]).lower()
                account = email_to_account.get(email)
                if account:
                    added += _insert_event(ledger, t, "cli_account", account, "sync-log")
            ledger.set_cursor(str(path), Cursor(offset=0, size=size, mtime=mtime))
    return added


def read_watch_view(path: Path) -> WatchView | None:
    """The watcher's latest view, or None when there is none or it does not parse."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("Cannot read the sync watcher's view %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    signed_out = data.get("desktopSignedIn") is False
    return WatchView(t=parse_iso(data.get("t")),
                     desktop_account=None if signed_out else _uuid(data.get("desktopAccount")),
                     cli_account=_uuid(data.get("cliAccount")), condition=data.get("condition") or None,
                     desktop_signed_out=signed_out, desktop_not_running=data.get("desktopRunning") is False)


def _uuid(value: object) -> str | None:
    return value.lower() if isinstance(value, str) and value else None
