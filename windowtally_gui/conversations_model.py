"""The Conversations window's logic: every account's Code sessions as its list shows them, the search by title and the
filters by account and by project, the line naming the account a session opens on, and the command that resumes a
session in a terminal. No toolkit.

The list is read from the ledger, opened read-only (``windowtally.sessions.conversations``): each session with its
title — *Untitled session in* its folder where its transcript gives none, as the switch's dialog names it — its project,
the account it is (its latest answer's, or a standing stop's), its last activity, what its answers would have cost at
API prices and what it last ran with, its effort and permission mode (``carry_model.ran_with``), which the desktop app
does not carry to a session it opens for another account. Every account's sessions are listed, an account hidden from
the main window's lists among them, as the History window keeps every account; an account is named as the user named it
in the settings, and a session no account could be given to as the History window says it. The read can stall the
window over a large ledger, so it runs off the window's thread, one at a time (``Refresh``).

A session's project is the folder it was started in; where that folder is a working copy that Claude Code made inside a
repository, ``<repository>\\.claude\\worktrees\\<name>``, the project is the repository, so every working copy of one
stands under one name in the filter.

A session opens on the account the desktop app is signed in to, through the app's resume link
(``carry_model.resume_link``), or with the resume command, on the account the CLI is signed in to. Only a session the
app's Code tab ran is opened through the link: the link was measured adopting such sessions only (desktop app
3.6556.2.0, 2026-11-07), and a session the CLI alone ran has no card in the app. Nothing is opened through the link
while the app is not running, at its sign-in page or being switched, since the link would start the app around the
account sync, whose work starting it is, or land on no account. A session Claude Code's session registry says is working is in the
app already: the link shows it, and no resume command is offered for it, since a second Claude Code writing beside it
would interleave the transcript. A session handed to the app opens there at the app's own effort for its model and,
where its transcript's last lines name no mode, in the settings' default mode, so the words that say it was handed name
what it ran with.

The resume command is PowerShell's: ``Set-Location`` to the session's folder, then ``claude --resume <id>``, so the
session goes on in its own folder; where that folder is gone it is ``claude --resume <id>`` alone, run wherever the
user starts it, never in another folder of the project. Claude Code finds the session by its id wherever its transcript
lies (2.1.310 looks beyond the current folder's), so the folder is for the work, not for the finding. The command goes
on at the effort and in the permission mode the session last ran with, through ``--effort`` and ``--permission-mode``,
each only where it is known and among the values Claude Code 2.1.310 takes for it. The default mode is passed as the
transcript names it, ``default`` or ``manual``, which 2.1.310 takes, the first unlisted, so a setting naming another
default mode does not change the mode a session goes on in; a CLI that refuses it says so rather than going on in
another mode. A bypass is lowered to accept edits, as the desktop app lowers it on taking a session in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from windowtally.accounts import name_key, named
from windowtally.billing import usd_text
from windowtally.history import UNATTRIBUTED
from windowtally.ledger import Ledger
from windowtally.paths import MachinePaths
from windowtally.sessions import Conversation, conversations
from windowtally.settings import load_settings
from windowtally.timeutil import MONTHS, local_datetime

from .carry_model import STOP_WORDS, ran_with, shown_title
from .formatting import ago, when
from .status_model import Status

UNKNOWN_ACCOUNT = ""      # the account filter's key for the sessions no account could be given to
RECENT = 24 * 3600.0      # a last activity within this long is said as an age, an older one as a date
DATED = 300 * 86400.0     # one older than this is said with its year

NO_STATUS = "No status yet, so which account the desktop app is on is not known."
NOT_RUNNING = "The desktop app is not running: start it from the main window to open a session there."
SIGNED_OUT = "The desktop app is at its sign-in page: sign in, or switch it to an account, to open a session there."
SWITCHING = "A switch of account is under way: a session opens in the desktop app once it is over."
APP_UNKNOWN = "The account the desktop app is on is not known, so no session opens there."
# The values Claude Code 2.1.310 takes for ``--effort``, and the ``--permission-mode`` the command passes for each mode
# a transcript names; a mode not here passes none.
CLI_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CLI_MODES = {"default": "default", "manual": "manual", "acceptEdits": "acceptEdits", "auto": "auto", "plan": "plan",
             "dontAsk": "dontAsk", "bypassPermissions": "acceptEdits"}


@dataclass(frozen=True)
class Row:
    session_id: str
    title: str             # as the list names it
    project: str           # the project's name as the list shows it
    project_key: str       # the project the filter matches: its folder, case folded
    project_folder: str    # the project's folder in full
    folder: str | None     # the folder the session was started in
    folder_exists: bool    # whether that folder still exists
    account: str           # the account's name, or the History window's word for none
    account_key: str       # the account's UUID, or UNKNOWN_ACCOUNT
    last_activity: float
    used: str              # what its answers would have cost at API prices, in dollars
    desktop: bool          # the desktop app's Code tab ran it
    stop_kind: str | None  # the window of the stop that stands, or None
    effort: str | None = None  # the effort its latest main answer ran at, or None
    mode: str | None = None    # the permission mode its transcript last named, or None
    ran_with: str = ""         # both as the list says them (``carry_model.ran_with``)


@dataclass(frozen=True)
class Listing:
    rows: tuple[Row, ...]                     # the latest activity first
    accounts: tuple[tuple[str, str], ...]     # (key, name) the account filter offers after every account, by name
    projects: tuple[tuple[str, str], ...]     # (key, name) the project filter offers after every project, by name
    computed_at: float


def project_of(folder: str) -> PureWindowsPath:
    """The project a folder is part of: the repository of a working copy Claude Code made inside it, else the folder."""
    path = PureWindowsPath(folder)
    parts = path.parts
    for index in range(1, len(parts) - 2):
        if parts[index].casefold() == ".claude" and parts[index + 1].casefold() == "worktrees":
            return PureWindowsPath(*parts[:index])
    return path


def _project_name(path: PureWindowsPath) -> str:
    return path.name or str(path)


def last_text(t: float, now: float) -> str:
    """A last activity as the list says it: ``49m ago`` within a day, ``Mon 26 Oct 01:07`` within the months before,
    ``26 Oct 2025`` before them."""
    if now - t < RECENT:
        return ago(now - t)
    if now - t < DATED:
        return when(t, with_date=True)
    moment = local_datetime(t)
    return f"{moment.day} {MONTHS[moment.month - 1]} {moment.year}"


def rows_of(found: list[Conversation], names: dict[str, str], exists: dict[str, bool]) -> tuple[Row, ...]:
    """The list's rows, in ``found``'s order; ``names`` gives each account's name, ``exists`` whether a folder does."""
    rows = []
    for c in found:
        project = project_of(c.folder) if c.folder else None
        rows.append(Row(
            session_id=c.session_id, title=shown_title(c.title, c.folder),
            project=_project_name(project) if project else "", project_key=str(project).casefold() if project else "",
            project_folder=str(project) if project else "", folder=c.folder,
            folder_exists=bool(c.folder) and exists.get(c.folder, False),
            account=names.get(c.account_uuid, c.account_uuid[:8]) if c.account_uuid else UNATTRIBUTED.label,
            account_key=c.account_uuid or UNKNOWN_ACCOUNT, last_activity=c.last_activity, used=usd_text(c.used_usd),
            desktop=c.desktop, stop_kind=c.stop_kind, effort=c.effort, mode=c.mode,
            ran_with=ran_with(c.effort, c.mode)))
    return tuple(rows)


def _choices(rows: tuple[Row, ...]) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    accounts = {row.account_key: row.account for row in rows if row.account_key != UNKNOWN_ACCOUNT}
    account_choices = sorted(accounts.items(), key=lambda item: (name_key(item[1]), item[0]))
    if any(row.account_key == UNKNOWN_ACCOUNT for row in rows):
        account_choices.append((UNKNOWN_ACCOUNT, UNATTRIBUTED.label))
    projects = {row.project_key: (row.project, row.project_folder) for row in rows if row.project_key}
    sharing: dict[str, int] = {}
    for name, _folder in projects.values():
        sharing[name.casefold()] = sharing.get(name.casefold(), 0) + 1
    # Two projects of one name are told apart by the folder each lies in.
    labelled = [(key, name if sharing[name.casefold()] == 1 else f"{name} ({PureWindowsPath(folder).parent})")
                for key, (name, folder) in projects.items()]
    project_choices = sorted(labelled, key=lambda item: (name_key(item[1]), item[0]))
    return tuple(account_choices), tuple(project_choices)


def compute(paths: MachinePaths, now: float | None = None) -> Listing:
    """Every account's sessions, read from the ledger opened read-only, the accounts named as the settings name them;
    settings that cannot be read name each account by its e-mail, as a pass counts them. FileNotFoundError while there
    is no ledger."""
    now = time.time() if now is None else now
    ledger = Ledger.open_readonly(paths.ledger_db)
    try:
        found = conversations(ledger)
        try:
            names = load_settings(paths.settings_file).names
        except (ValueError, OSError):   # SettingsError is a ValueError
            names = {}
        labels = {uuid: account.label for uuid, account in named(ledger.known_accounts(), names).items()}
    finally:
        ledger.close()
    exists = {folder: Path(folder).is_dir() for folder in {c.folder for c in found if c.folder}}
    rows = rows_of(found, labels, exists)
    accounts, projects = _choices(rows)
    return Listing(rows, accounts, projects, now)


# --- the search and the filters ---------------------------------------------------------------------------------------

def search_words(text: str) -> tuple[str, ...]:
    """The words a search is made of, each to be found in a title, case aside. The switch's dialog searches its
    sessions the same way (``switch_view``)."""
    return tuple(word.casefold() for word in text.split())


def title_has(title: str, words: tuple[str, ...]) -> bool:
    """Whether every word of a search stands in ``title``, case aside."""
    folded = title.casefold()
    return all(word in folded for word in words)


def matches(row: Row, words: tuple[str, ...], account: str | None, project: str | None) -> bool:
    """Whether ``row`` stands in the list: every word of the search in its title, and its account and its project
    those chosen, None choosing every one."""
    if account is not None and row.account_key != account:
        return False
    if project is not None and row.project_key != project:
        return False
    return title_has(row.title, words)


def count_words(shown: int, total: int) -> str:
    if shown == total:
        return f"{total:,} session{'' if total == 1 else 's'}"
    return f"{shown:,} of {total:,} sessions"


# --- where a session opens --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Opening:
    words: str          # the line under the list
    can_open: bool      # Open session hands the session to the desktop app
    can_copy: bool      # Copy resume command gives its command


def _label(status: Status, uuid: str | None) -> str | None:
    account = status.account(uuid) if uuid else None
    return account.label if account is not None else None


def opening(row: Row | None, status: Status | None, *, switching: bool, working: frozenset[str]) -> Opening:
    """What the line under the list says of ``row``, the session chosen, or of every session where none is, and what
    its two buttons can do: the account it opens on in the desktop app, or why it opens there on none, and the
    account the resume command runs on."""
    app, why = None, None
    if status is None:
        why = NO_STATUS
    elif not status.desktop_running:
        why = NOT_RUNNING
    elif not status.desktop_signed_in:
        why = SIGNED_OUT
    elif switching:
        why = SWITCHING
    else:
        app = _label(status, status.desktop_account)
        if app is None:
            why = APP_UNKNOWN
    cli = _label(status, status.cli_account) if status is not None else None
    if app is not None and cli in (None, app):
        where = f"A session opens on {app}, in the desktop app or with the resume command."
    elif app is not None:
        where = f"A session opens on {app} in the desktop app; the resume command runs on {cli}."
    else:
        where = why + (f" The resume command runs on {cli}." if cli else "")
    if row is None:
        return Opening(where, False, False)
    notes = []
    if row.session_id in working:
        notes.append("It is working in the desktop app now, so no resume command is offered for it.")
    if not row.desktop:
        notes.append("The CLI alone ran it, so the desktop app has no card of it: it opens with the resume command.")
    if row.stop_kind is not None:
        notes.append(f"{STOP_WORDS.get(row.stop_kind, STOP_WORDS[''])}.")
    if row.folder and not row.folder_exists:
        notes.append("Its folder is gone, so the resume command runs in the folder it is started in.")
    return Opening(" ".join([where] + notes), app is not None and row.desktop, row.session_id not in working)


def handed_words(row: Row) -> str:
    """What the window says once ``row`` is handed to the desktop app: that it was, and, where known, what it ran with,
    since the app keeps no effort of it and its permission mode only where its transcript's last lines name one."""
    words = f"Handed to the desktop app: {row.title}."
    if row.ran_with:
        words += f" The app does not keep its effort and may not keep its permission mode: it ran with {row.ran_with}."
    return words


def resume_command(row: Row) -> str:
    """The PowerShell command that goes on with the session in a terminal, in its own folder where that still exists,
    at the effort and in the permission mode it last ran with where those are known."""
    command = f"claude --resume {row.session_id}"
    if row.effort in CLI_EFFORTS:
        command += f" --effort {row.effort}"
    if row.mode in CLI_MODES:
        command += f" --permission-mode {CLI_MODES[row.mode]}"
    if row.folder and row.folder_exists:
        quoted = row.folder.replace("'", "''")
        return f"Set-Location -LiteralPath '{quoted}'; {command}"
    return command


# --- one read at a time -----------------------------------------------------------------------------------------------

class Refresh:
    """Whether a read runs, and whether one more was asked for while it did: that one starts when it ends, since the
    running one read the ledger as it was before the ask."""

    def __init__(self) -> None:
        self.running = False
        self.again = False
        self.failure: str | None = None

    def want(self) -> bool:
        """A read asked for: True where it is to start now, False where one runs and is to be followed by another."""
        if self.running:
            self.again = True
            return False
        self.running = True
        return True

    def done(self, failure: str | None = None) -> bool:
        """A read ended: True where another is to start now."""
        self.failure = failure
        self.running = self.again
        self.again = False
        return self.running
