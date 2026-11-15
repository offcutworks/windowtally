"""Reads the desktop app's plan-usage history into the ledger.

The app writes ``%APPDATA%/Claude/plan-usage-history.json`` as ``{"version": 2, "samples": [{"t": <epoch ms>,
"org": <organization UUID>, "u": {"fh": <5-hour %>, "sd": <weekly %>}}]}``: the signed-in account only, roughly
every 15 minutes while the app is running, about 30 days kept. The samples carry no reset times. Measured on the
development machine, the sampling also pauses for hours while the app runs, so the file is history, not a live
feed. A version other than 2 is refused with an error naming it, never guessed at.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .ledger import Cursor, Ledger

log = logging.getLogger(__name__)

KNOWN_VERSION = 2
_KINDS = (("five_hour", "fh"), ("seven_day", "sd"))


class AppHistoryFormatError(ValueError):
    """The history file is not in the format this module reads."""


def ingest_app_history(ledger: Ledger, path: Path, org_to_account: dict[str, str]) -> int:
    """Adds samples not yet in the ledger; returns how many observations were new. A missing file is no error."""
    try:
        status = path.stat()
    except FileNotFoundError:
        return 0
    key = str(path)
    previous = ledger.cursor(key)
    if previous and previous.size == status.st_size and previous.mtime == status.st_mtime:
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != KNOWN_VERSION or not isinstance(data.get("samples"), list):
        raise AppHistoryFormatError(f"{path} has version {data.get('version') if isinstance(data, dict) else None!r}; "
                                    f"this version of WindowTally reads version {KNOWN_VERSION}")
    added = 0
    with ledger.transaction():
        for sample in data["samples"]:
            t, org, values = sample.get("t"), sample.get("org"), sample.get("u")
            if not isinstance(t, (int, float)) or not org or not isinstance(values, dict):
                continue
            org = str(org).lower()
            account = org_to_account.get(org)
            for kind, field in _KINDS:
                value = values.get(field)
                if not isinstance(value, (int, float)):
                    continue
                cursor = ledger.db.execute(
                    "INSERT OR IGNORE INTO observations(source, ref, t, kind, percent, resets_at, account_uuid, "
                    "account_source) VALUES ('app', ?, ?, ?, ?, NULL, ?, ?)",
                    (org, t / 1000.0, kind, float(value), account, "org" if account else None))
                added += cursor.rowcount
        # Samples ingested while their organization was not yet in the registry get their account now.
        ledger.attribute_by_org("app", org_to_account)
        ledger.set_cursor(key, Cursor(offset=0, size=status.st_size, mtime=status.st_mtime))
    return added
