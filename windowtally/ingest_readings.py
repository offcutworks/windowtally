"""Reads the desktop plugin's plan readings into the ledger.

Contract (version 1) — the plugin keeps one file per Claude Code session, ``<data>/readings/<sessionId>.json``,
overwritten with the latest reading Claude Code received with a response in that session:

    {"v": 1, "t": <epoch ms of the reading>, "sessionId": "<id>",
     "windows": [{"kind": "five_hour", "percentUsed": 26, "resetsAt": "2026-10-21T01:10:00.086Z"},
                 {"kind": "seven_day", "percentUsed": 60, "resetsAt": "2026-10-25T22:00:00.086Z"}]}

``kind`` is Claude Code's window name; windows other than five_hour and seven_day are kept but not interpreted.
The reading names no account: attribution assigns it the account its session's client was signed in to at that
moment (``attribution``). A file in another version, or one that does not parse, is skipped with a warning and read
again only when it changes.

Files whose last change is older than ``RETENTION_SECONDS`` are deleted once ingested: the folder is WindowTally's
own, and every reading in it already lives in the ledger.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Callable

from .ledger import Cursor, Ledger
from .timeutil import parse_iso

log = logging.getLogger(__name__)

READINGS_VERSION = 1
RETENTION_SECONDS = 7 * 24 * 3600


def ingest_readings(ledger: Ledger, readings_dir: Path, now: float | None = None) -> int:
    """Adds readings not yet in the ledger; returns how many observations were new."""
    return ingest_folder(ledger, readings_dir, now, _ingest_file)


def ingest_folder(ledger: Ledger, folder: Path, now: float | None,
                  ingest_file: Callable[[Ledger, Path, str, int, float], int]) -> int:
    """Reads every ``*.json`` in one of WindowTally's own reading folders through ``ingest_file`` when it changed since
    its cursor, and deletes a file older than ``RETENTION_SECONDS`` once read; how many observations were new. The
    plugin's readings and the browser extension's share it."""
    if not folder.is_dir():
        return 0
    now = time.time() if now is None else now
    added = 0
    for path in sorted(folder.glob("*.json")):
        try:
            status = path.stat()
        except FileNotFoundError:
            continue
        key = str(path)
        previous = ledger.cursor(key)
        if not (previous and previous.size == status.st_size and previous.mtime == status.st_mtime):
            added += ingest_file(ledger, path, key, status.st_size, status.st_mtime)
        if now - status.st_mtime > RETENTION_SECONDS:
            try:
                path.unlink()
                with ledger.transaction():
                    ledger.db.execute("DELETE FROM cursors WHERE path=?", (key,))
            except OSError as exc:
                log.warning("Cannot remove old reading %s: %s", path, exc)
    return added


def _ingest_file(ledger: Ledger, path: Path, key: str, size: int, mtime: float) -> int:
    added = 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("v") != READINGS_VERSION:
            raise ValueError(f"version {data.get('v') if isinstance(data, dict) else None!r}, expected {READINGS_VERSION}")
        t = float(data["t"]) / 1000.0
        session = str(data["sessionId"])
        windows = data["windows"]
        if not isinstance(windows, list):
            raise ValueError("windows is not a list")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("Skipping plugin reading %s: %s", path, exc)
        windows = []
        t = session = None
    with ledger.transaction():
        for window in windows:
            if not isinstance(window, dict):
                log.warning("Skipping a malformed window in plugin reading %s", path)
                continue
            kind, percent = window.get("kind"), window.get("percentUsed")
            if not kind or not isinstance(percent, (int, float)):
                continue
            cursor = ledger.db.execute(
                "INSERT OR IGNORE INTO observations(source, ref, t, kind, percent, resets_at) "
                "VALUES ('plugin', ?, ?, ?, ?, ?)",
                (session, t, str(kind), float(percent), parse_iso(window.get("resetsAt"))))
            added += cursor.rowcount
        ledger.set_cursor(key, Cursor(offset=0, size=size, mtime=mtime))
    return added
