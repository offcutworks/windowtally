"""Reads the browser extension's readings into the ledger.

Contract: ``browser_host`` (version 1) — one file per organization, ``<data>/browser/<organizationUuid>.json``,
overwritten with the latest 5-hour and weekly figures claude.ai's page received, and the week's use by product and its
per-model windows where the page had them. A file is checked by the host's own ``reading_from``, so the ledger takes
exactly what the host would have written. The windows become observations; the use by product, a report of
``products`` beside them, one row per product, taken once per moment claude.ai computed it; the per-model windows, rows
of ``scoped_windows`` at the reading's moment (``limits.scoped_standings``). A reading names its organization, so it is
given its account as the desktop app's samples are (``accounts.by_org``), and one whose organization is not yet in the
registry gets its account once it is, in every table. A file that is not a reading is skipped with a warning and read
again only when it changes.

The folder is walked as the plugin's readings are (``ingest_readings.ingest_folder``): a file older than
``RETENTION_SECONDS`` is deleted once read, every reading in it already living in the ledger.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .browser_host import BY_PRODUCT, SCOPED, reading_from
from .ingest_readings import ingest_folder
from .ledger import Cursor, Ledger
from .products import TABLE
from .timeutil import parse_iso

log = logging.getLogger(__name__)


def ingest_browser(ledger: Ledger, browser_dir: Path, org_to_account: dict[str, str], now: float | None = None) -> int:
    """Adds readings not yet in the ledger; returns how many observations were new."""
    added = ingest_folder(ledger, browser_dir, now, lambda ledger, path, key, size, mtime: _ingest_file(
        ledger, path, key, size, mtime, org_to_account))
    with ledger.transaction():
        for table in ("observations", TABLE, "scoped_windows"):
            ledger.attribute_by_org("browser", org_to_account, table)
    return added


def _ingest_file(ledger: Ledger, path: Path, key: str, size: int, mtime: float,
                 org_to_account: dict[str, str]) -> int:
    added = 0
    try:
        reading = reading_from(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:   # a ReadingError is a ValueError
        log.warning("Skipping browser reading %s: %s", path, exc)
        reading = None
    with ledger.transaction():
        if reading is not None:
            org, t = reading["org"], reading["t"] / 1000.0
            account = org_to_account.get(org)
            for window in reading["windows"]:
                cursor = ledger.db.execute(
                    "INSERT OR IGNORE INTO observations(source, ref, t, kind, percent, resets_at, account_uuid, "
                    "account_source) VALUES ('browser', ?, ?, ?, ?, ?, ?, ?)",
                    (org, t, window["kind"], float(window["percentUsed"]), parse_iso(window["resetsAt"]), account,
                     "org" if account else None))
                added += cursor.rowcount
            by_product = reading.get(BY_PRODUCT)
            if by_product is not None:
                as_of, start = parse_iso(by_product["asOf"]), parse_iso(by_product["windowStartedAt"])
                for position, row in enumerate(by_product["rows"]):
                    ledger.db.execute(
                        f"INSERT OR IGNORE INTO {TABLE}(source, ref, t, as_of, window_start, position, key, name, "
                        "percent, account_uuid, account_source) VALUES ('browser', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (org, t, as_of, start, position, row["key"], row["name"], float(row["percent"]), account,
                         "org" if account else None))
            for row in reading.get(SCOPED, ()):
                allowance = row["allowanceOfWeekly"]
                ledger.db.execute(
                    "INSERT OR IGNORE INTO scoped_windows(source, ref, t, name, percent, resets_at, allowance, "
                    "account_uuid, account_source) VALUES ('browser', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (org, t, row["name"], float(row["percentUsed"]), parse_iso(row["resetsAt"]),
                     None if allowance is None else float(allowance), account, "org" if account else None))
        ledger.set_cursor(key, Cursor(offset=0, size=size, mtime=mtime))
    return added
