"""The ledger: one SQLite file holding every fact WindowTally has read, kept after its sources expire.

Tables
    meta            schema version and small bookkeeping values: which accounts' profiles the last pass read, what
                    the last attribution saw (its rule, the timelines, the owner lines), and which kinds of transcript
                    line every transcript has been read for
    accounts        the registry as last seen, so history keeps its labels after a profile folder is gone
    cursors         how far each source file has been read (offset, size, mtime)
    responses       one row per model response: usage as finally reported, cost, and the derived account
    session_owners  each account a session's transcript names as its owner
    prompts         one row per user prompt of a main session
    session_titles  each session's title as its transcript last gave it, the title the desktop app shows (``custom``)
                    standing before the one Claude Code makes up itself (``ai``)
    session_modes   each main session's permission mode as its transcript last named it
    limit_stops     one row per turn of a main session that a plan limit refused: when, the window that refused it and
                    that window's reset where the transcript says, and the derived account
    background_tasks  one row per background task a transcript names, a command or a subagent a main session started
                    to run on beside it: the session and when it started, where a transcript says, and when it ended,
                    where one says, the latest of each; a row with a start and no end after it is work that never
                    reported back
    observations    plan-limit percentages at a moment, from the app's samples, the plugin's readings or the browser
                    extension's
    product_shares  the share of an account's weekly window each product took, as claude.ai reported it to the browser
                    extension, one row per product of a report (``products``)
    scoped_windows  an account's per-model weekly windows at a moment — a model's own allowance inside the weekly
                    window, as Fable's is — as claude.ai reported them to the browser extension: the window's percentage
                    and reset, and its allowance as a share of the weekly window where claude.ai gave it
                    (``limits.scoped_standings``)
    account_events  changes of the desktop app's account and of the CLI's, by kind; a ``desktop_signed_out`` row is the
                    app left at its sign-in page, naming the account it was signed out of, not one it uses

Times are epoch seconds (UTC). Raw facts are written by the ingesters; ``account_uuid`` / ``account_source`` on
responses, limit stops and plugin observations are derived columns that the attribution step rewrites as evidence
improves.

The ledger is the only lasting copy of expired sources, so a schema change must migrate the file in place; a
version this code does not know is refused rather than rebuilt. A table that only adds facts no other figure rests on
(``product_shares``, ``scoped_windows``, ``session_titles``, ``session_modes``, ``limit_stops``, ``background_tasks``)
is created by ``open`` without changing the version, so a ledger it was added to still opens in code that predates it,
which never reads it; a reader that does read it asks ``has_table`` first, since a read-only reader may meet a ledger
no pass of this code has opened yet.

A pass opens the ledger with ``open``, which creates the schema of a new file and sets its journal mode — both writes.
A process that only reads it (the window) opens it with ``open_readonly``, through which nothing can be written.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .accounts import Account

SCHEMA_VERSION = 1
_BY_ORG = ("observations", "product_shares", "scoped_windows")   # the tables whose rows a source names by organization

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    uuid TEXT PRIMARY KEY,
    email TEXT,
    org_uuid TEXT,
    org_name TEXT,
    rate_limit_tier TEXT
);
CREATE TABLE IF NOT EXISTS cursors (
    path TEXT PRIMARY KEY,
    offset INTEGER NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS responses (
    message_id TEXT PRIMARY KEY,
    request_id TEXT,
    t REAL NOT NULL,
    session_id TEXT NOT NULL,
    agent_id TEXT,
    entrypoint TEXT,
    version TEXT,
    cwd TEXT,
    model TEXT,
    requested_model TEXT,
    effort TEXT,
    speed TEXT,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    thinking_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    cache_write_5m_tokens INTEGER NOT NULL,
    cache_write_1h_tokens INTEGER NOT NULL,
    web_search_requests INTEGER NOT NULL,
    web_fetch_requests INTEGER NOT NULL,
    cost_usd REAL,
    account_uuid TEXT,
    account_source TEXT
);
CREATE INDEX IF NOT EXISTS responses_t ON responses(t);
CREATE INDEX IF NOT EXISTS responses_session ON responses(session_id);
CREATE INDEX IF NOT EXISTS responses_account_t ON responses(account_uuid, t);
CREATE TABLE IF NOT EXISTS session_owners (
    session_id TEXT NOT NULL,
    account_uuid TEXT NOT NULL,
    PRIMARY KEY (session_id, account_uuid)
);
CREATE TABLE IF NOT EXISTS prompts (
    prompt_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    t REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS prompts_session ON prompts(session_id);
CREATE TABLE IF NOT EXISTS observations (
    source TEXT NOT NULL,
    ref TEXT NOT NULL,
    t REAL NOT NULL,
    kind TEXT NOT NULL,
    percent REAL NOT NULL,
    resets_at REAL,
    account_uuid TEXT,
    account_source TEXT,
    PRIMARY KEY (source, ref, t, kind)
);
CREATE INDEX IF NOT EXISTS observations_account ON observations(account_uuid, kind, t);
CREATE TABLE IF NOT EXISTS product_shares (
    source TEXT NOT NULL,
    ref TEXT NOT NULL,
    t REAL NOT NULL,
    as_of REAL NOT NULL,
    window_start REAL NOT NULL,
    position INTEGER NOT NULL,
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    percent REAL NOT NULL,
    account_uuid TEXT,
    account_source TEXT,
    PRIMARY KEY (source, ref, as_of, key)
);
CREATE INDEX IF NOT EXISTS product_shares_account ON product_shares(account_uuid, as_of);
CREATE TABLE IF NOT EXISTS scoped_windows (
    source TEXT NOT NULL,
    ref TEXT NOT NULL,
    t REAL NOT NULL,
    name TEXT NOT NULL,
    percent REAL NOT NULL,
    resets_at REAL,
    allowance REAL,
    account_uuid TEXT,
    account_source TEXT,
    PRIMARY KEY (source, ref, t, name)
);
CREATE INDEX IF NOT EXISTS scoped_windows_account ON scoped_windows(account_uuid, name, t);
CREATE TABLE IF NOT EXISTS session_titles (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS session_modes (
    session_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS limit_stops (
    line_uuid TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    t REAL NOT NULL,
    kind TEXT,
    resets_at REAL,
    entrypoint TEXT,
    account_uuid TEXT,
    account_source TEXT
);
CREATE INDEX IF NOT EXISTS limit_stops_session ON limit_stops(session_id);
CREATE INDEX IF NOT EXISTS limit_stops_account_t ON limit_stops(account_uuid, t);
CREATE TABLE IF NOT EXISTS background_tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT,
    kind TEXT,
    started REAL,
    ended REAL
);
CREATE INDEX IF NOT EXISTS background_tasks_session ON background_tasks(session_id);
CREATE TABLE IF NOT EXISTS account_events (
    t REAL NOT NULL,
    kind TEXT NOT NULL,
    account_uuid TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (t, kind, account_uuid)
);
"""


class LedgerVersionError(RuntimeError):
    """The file was written by a schema this code does not know; it is left untouched."""


@dataclass(frozen=True)
class Cursor:
    offset: int
    size: int
    mtime: float


@dataclass(frozen=True)
class Observation:
    source: str
    ref: str
    t: float
    kind: str
    percent: float
    resets_at: float | None
    account_uuid: str | None


@dataclass(frozen=True)
class ScopedObservation:
    """A per-model weekly window's percentage at a moment (``scoped_windows``)."""

    t: float
    name: str
    percent: float
    resets_at: float | None
    allowance: float | None   # the model's allowance as a percentage of the weekly window; None where unsaid


class Ledger:
    """A thin wrapper over the connection: schema, transactions, and the queries the other modules share."""

    def __init__(self, connection: sqlite3.Connection):
        self.db = connection

    # --- lifecycle ------------------------------------------------------------------------------------------

    @classmethod
    def open(cls, path: Path) -> Ledger:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path), timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        ledger = cls(connection)
        ledger._ensure_schema()
        return ledger

    @classmethod
    def open_readonly(cls, path: Path) -> Ledger:
        """The ledger for reading only: no schema is created and every write is refused by SQLite itself.
        FileNotFoundError while there is no ledger; LedgerVersionError for a file of a schema this code does not
        know, or one that is not a ledger at all."""
        if not path.is_file():
            raise FileNotFoundError(f"no ledger at {path}")
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
        try:
            connection.execute("PRAGMA busy_timeout=30000")
            row = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        except sqlite3.DatabaseError as exc:
            connection.close()
            raise LedgerVersionError(f"{path} is not a ledger this code reads ({exc}).") from None
        found = int(row[0]) if row else None
        if found != SCHEMA_VERSION:
            connection.close()
            raise LedgerVersionError(f"Ledger schema {found} is not the {SCHEMA_VERSION} this code reads.")
        return cls(connection)

    def close(self) -> None:
        self.db.close()

    def has_table(self, name: str) -> bool:
        return self.db.execute("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name=?)",
                               (name,)).fetchone()[0] == 1

    def _ensure_schema(self) -> None:
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "meta" in tables:
            row = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            found = int(row[0]) if row else None
            if found != SCHEMA_VERSION:
                raise LedgerVersionError(
                    f"Ledger schema {found} is not the {SCHEMA_VERSION} this code reads; the file was left as it is.")
        with self.transaction():
            self.db.executescript(_SCHEMA)
            self.db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.db
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    # --- meta -----------------------------------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))

    # --- accounts -------------------------------------------------------------------------------------------

    def upsert_accounts(self, accounts: dict[str, Account]) -> None:
        for a in accounts.values():
            self.db.execute(
                "INSERT INTO accounts(uuid, email, org_uuid, org_name, rate_limit_tier) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(uuid) DO UPDATE SET email=excluded.email, org_uuid=excluded.org_uuid, "
                "org_name=excluded.org_name, rate_limit_tier=excluded.rate_limit_tier",
                (a.uuid, a.email, a.org_uuid.lower() if a.org_uuid else None, a.org_name, a.rate_limit_tier))

    def known_accounts(self) -> dict[str, Account]:
        rows = self.db.execute("SELECT uuid, email, org_uuid, org_name, rate_limit_tier FROM accounts ORDER BY email")
        return {r[0]: Account(uuid=r[0], email=r[1], org_uuid=r[2], org_name=r[3], rate_limit_tier=r[4]) for r in rows}

    def set_profiles_on_machine(self, uuids: Iterable[str]) -> None:
        """Records the accounts whose profile a pass read from the sync's store, so a reader that never opens that
        store (the window) knows them; kept in the meta table, beside the registry the pass upserted."""
        self.set_meta("profiles_on_machine", json.dumps(sorted(uuids)))

    def profiles_on_machine(self) -> frozenset[str]:
        """The accounts whose profile the last pass read; empty before any pass recorded them."""
        value = self.get_meta("profiles_on_machine")
        return frozenset(json.loads(value)) if value else frozenset()

    # --- cursors --------------------------------------------------------------------------------------------

    def cursor(self, path: str) -> Cursor | None:
        row = self.db.execute("SELECT offset, size, mtime FROM cursors WHERE path=?", (path,)).fetchone()
        return Cursor(*row) if row else None

    def set_cursor(self, path: str, cursor: Cursor) -> None:
        self.db.execute(
            "INSERT INTO cursors(path, offset, size, mtime) VALUES (?, ?, ?, ?) ON CONFLICT(path) DO UPDATE SET "
            "offset=excluded.offset, size=excluded.size, mtime=excluded.mtime",
            (path, cursor.offset, cursor.size, cursor.mtime))

    # --- observations ---------------------------------------------------------------------------------------

    def observations(self, account_uuid: str, kind: str, since: float | None = None) -> list[Observation]:
        """One account's observations of one window, oldest first."""
        query = ("SELECT source, ref, t, kind, percent, resets_at, account_uuid FROM observations "
                 "WHERE account_uuid=? AND kind=?")
        params: list[object] = [account_uuid, kind]
        if since is not None:
            query += " AND t>=?"
            params.append(since)
        query += " ORDER BY t, source"
        return [Observation(*row) for row in self.db.execute(query, params)]

    def scoped_observations(self, account_uuid: str, since: float | None = None) -> list[ScopedObservation]:
        """One account's readings of its per-model weekly windows, every model's, oldest first; none where the ledger
        predates the table (a read-only reader may meet one no pass of this code has opened)."""
        if not self.has_table("scoped_windows"):
            return []
        query = "SELECT t, name, percent, resets_at, allowance FROM scoped_windows WHERE account_uuid=?"
        params: list[object] = [account_uuid]
        if since is not None:
            query += " AND t>=?"
            params.append(since)
        query += " ORDER BY t, source"
        return [ScopedObservation(*row) for row in self.db.execute(query, params)]

    def attribute_by_org(self, source: str, org_to_account: dict[str, str], table: str = "observations") -> None:
        """Gives a source's rows in ``table`` — observations, product shares or per-model windows — that name an
        organization (their ``ref``) but no account the account the registry now gives that organization: those read
        before the account's profile was stored."""
        if table not in _BY_ORG:
            raise ValueError(f"{table} holds no rows named by organization")
        if not self.db.execute(f"SELECT EXISTS(SELECT 1 FROM {table} WHERE source=? AND account_uuid IS NULL)",
                               (source,)).fetchone()[0]:
            return
        for org, account in org_to_account.items():
            self.db.execute(f"UPDATE {table} SET account_uuid=?, account_source='org' "
                            "WHERE source=? AND ref=? AND account_uuid IS NULL", (account, source, org))

    # --- responses ------------------------------------------------------------------------------------------

    def response_times(self, account_uuid: str, since: float) -> list[float]:
        """When the account answered a request since ``since``, oldest first — its activity."""
        rows = self.db.execute("SELECT t FROM responses WHERE account_uuid=? AND t>=? ORDER BY t", (account_uuid, since))
        return [r[0] for r in rows]

    def cost_between(self, account_uuid: str, start: float, end: float) -> float:
        row = self.db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM responses WHERE account_uuid=? AND t>? AND t<=?",
            (account_uuid, start, end)).fetchone()
        return float(row[0])

    def cost_in(self, account_uuid: str, start: float, end: float) -> float:
        """API-equivalent USD of the account's responses in [start, end): a half-open span, like a service period."""
        row = self.db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM responses WHERE account_uuid=? AND t>=? AND t<?",
            (account_uuid, start, end)).fetchone()
        return float(row[0])

    def total_cost_in(self, start: float, end: float) -> float:
        """API-equivalent USD of every response in [start, end), whatever its account, none included."""
        row = self.db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM responses WHERE t>=? AND t<?",
                              (start, end)).fetchone()
        return float(row[0])

    def first_response(self, account_uuid: str) -> float | None:
        """When the ledger's record of the account's responses begins."""
        return self.db.execute("SELECT MIN(t) FROM responses WHERE account_uuid=?", (account_uuid,)).fetchone()[0]
