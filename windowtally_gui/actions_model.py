"""What the window's buttons do, each through WindowTally's own code and each answering in an Outcome the window shows:
nothing a button does is new logic, and none fails without saying so.

    refresh        one pass now, as ``python -m windowtally once`` runs it, under the pass lock the service holds for
                   its own passes
    export_history the history the History window shows, as one HTML file where the user saves it
                   (``windowtally.dashboard.render_history``), then that file in the default browser
    data_folder    WindowTally's data folder in Explorer
    record_bill, replace_bill, remove_bill
                   WindowTally's own bills file, through ``windowtally.bills``
    add_source, remove_source, set_reminder
                   the settings, through the functions the command line's ``bills source`` and ``bills remind`` use
    set_silenced   the setting that silences WindowTally's notifications, through ``windowtally.settings``; the window
                   reads it back with ``silenced``
    set_keep_awake the setting that lets the service keep the computer awake while Claude Code works, through
                   ``windowtally.settings``, which the service reads within seconds; the window reads it back with
                   ``keep_awake``
    arrangement, set_arrangement
                   the accounts' order, the user's names for them and which are hidden, read for the Arrange accounts
                   window and written together through ``windowtally.settings``, what the window changed laid onto the
                   settings as they stand when it writes
    working_sessions, working_ids
                   the desktop-hosted Code sessions at work now, counted, or named, off Claude Code's session registry
                   through ``windowtally.registry`` and not taken from the last status, which can be a minute old: the
                   question before the client is closed must not miss a session that began working since
    read_sources   one pass with no history page, before a switch offers the sessions of the account it leaves, so a
                   turn a limit stopped since the service's last pass is among them
    carry_lines    the sessions of the account the desktop app leaves that a switch can carry, read from the ledger
                   opened read-only (``windowtally.sessions``)

A pass reads every source and can take a minute on a first import, so ``refresh`` and ``read_sources`` run off the
window's thread (``background``); the others are quick and run on it, the export among them, since it writes what is
already computed. The openers are parameters so the tests can see what would be opened; the window passes the shell's
own (a browser, Explorer), never a console program.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from windowtally import bills as bill_store
from windowtally.billing import money_text
from windowtally.bills import PLANS, Bill, BillsError
from windowtally.dashboard import render_history
from windowtally.files import write_text_atomically
from windowtally.history import History, reminder_text
from windowtally.ledger import Ledger
from windowtally.paths import MachinePaths
from windowtally.registry import read_registry
from windowtally.service import run_pass
from windowtally.sessions import SessionLine, sessions_of
from windowtally.settings import (edit_account_arrangement, keeps_awake, load_settings,
                                  set_keep_awake as save_keep_awake, set_notifications_silenced, set_renewal_reminder)

from .arrange_model import Arrangement, Conflict
from .bills_model import BillForm, check
from .formatting import plural
from .status_model import Status


@dataclass(frozen=True)
class Outcome:
    ok: bool
    message: str


def _describe(bill: Bill) -> str:
    what = PLANS[bill.plan] if bill.plan else {"topup": "top-up", "usage": "usage settled"}.get(bill.kind, bill.kind)
    if bill.kind == "refund":
        what += f" of the bill {bill.reference}"
    period = f", {bill.start}..{bill.end}" if bill.start and bill.end else ""
    return f"{bill.account}: {bill.date} {what} {money_text(bill.amount, bill.currency)}{period}"


def _checked(paths: MachinePaths, form: BillForm, replacing: Bill | None = None) -> Bill:
    """The bill the form describes, set against its refund or, for a refund, the bill it credits, as the command line
    sets it (``windowtally.bills.check_refund_pairing``); ``replacing`` is the bill it is to replace."""
    bill = check(form)
    bill_store.check_refund_pairing(paths, bill, replacing)
    return bill


def refresh(paths: MachinePaths) -> Outcome:
    try:
        report = run_pass(paths)
    except Exception as exc:  # a pass that fails is said, never dropped
        return Outcome(False, f"Not refreshed: {exc}")
    problems = len(report.errors)
    return Outcome(True, f"Refreshed in {report.duration:.1f} s"
                   + (f"; {plural(problems, 'source problem')}." if problems else "."))


def read_sources(paths: MachinePaths) -> Outcome:
    """One pass that leaves the history page to the service: what a switch waits for, the page adding seconds to it."""
    try:
        report = run_pass(paths, dashboard=False)
    except Exception as exc:  # a pass that fails is said, never dropped
        return Outcome(False, f"Not read: {exc}")
    return Outcome(True, f"Read every source in {report.duration:.1f} s.")


def ledger_behind(paths: MachinePaths, status: Status) -> bool:
    """Whether a Code session of the desktop app is at work now, or its status changed after the pass that wrote
    ``status``, as Claude Code's session registry says: that session's transcript holds what the ledger has not read,
    a turn a limit stopped among it."""
    registry = read_registry(paths.registry_dir)
    if registry.desktop_working_ids():
        return True
    changed = registry.last_desktop_change()
    return changed is not None and (status.generated_at is None or changed > status.generated_at)


def carry_lines(paths: MachinePaths, account_uuid: str, now: float) -> list[SessionLine]:
    """The sessions of ``account_uuid`` a switch of the desktop app can carry, from the ledger opened read-only;
    FileNotFoundError while there is no ledger, LedgerVersionError or sqlite3.Error where it cannot be read."""
    ledger = Ledger.open_readonly(paths.ledger_db)
    try:
        return sessions_of(ledger, account_uuid, now)
    finally:
        ledger.close()


def after(lead: Outcome | None, outcome: Outcome) -> Outcome:
    """What the status line says of a pass that follows a change: the change's own words first, so the pass's do not
    replace them, and the warning colour where either did not go as asked, so a change that was not done keeps it."""
    if lead is None:
        return outcome
    return Outcome(lead.ok and outcome.ok, f"{lead.message} {outcome.message}")


def export_history(shown: History, path: Path, open_url: Callable[[str], object],
                   chosen: Mapping[str, str] | None = None) -> Outcome:
    """The history the History window shows, written to ``path`` as one HTML file, then opened in the browser, each
    switch at the view ``chosen`` names as the window does. It runs on the window's thread, so a file another program
    holds is refused at once rather than waited for."""
    try:
        write_text_atomically(path, render_history(shown, chosen), patience=0.0)
    except Exception as exc:  # the markup or the write: said, never dropped
        return Outcome(False, f"Not exported: {exc}")
    try:
        open_url(path.resolve().as_uri())
    except Exception as exc:  # the file is written; only showing it failed, and that is said
        return Outcome(False, f"Exported to {path}, but it was not opened: {exc}")
    return Outcome(True, f"Exported to {path}.")


def data_folder(paths: MachinePaths, open_folder: Callable[[Path], object]) -> Outcome:
    try:
        paths.data_dir.mkdir(parents=True, exist_ok=True)
        open_folder(paths.data_dir)
    except OSError as exc:
        return Outcome(False, f"The data folder was not opened: {exc}")
    return Outcome(True, f"Opened {paths.data_dir}.")


def record_bill(paths: MachinePaths, form: BillForm) -> Outcome:
    try:
        bill = _checked(paths, form)
        bill_store.add_bill(paths.bills_file, bill)
    except (ValueError, OSError) as exc:  # BillsError is a ValueError
        return Outcome(False, f"Not recorded: {exc}")
    return Outcome(True, f"Recorded {_describe(bill)}.")


def replace_bill(paths: MachinePaths, bill: Bill, form: BillForm) -> Outcome:
    try:
        replacement = _checked(paths, form, bill)
        bill_store.replace_bill(paths.bills_file, bill, replacement)
    except (ValueError, OSError) as exc:
        return Outcome(False, f"Not changed: {exc}")
    return Outcome(True, f"Changed: {_describe(replacement)}.")


def remove_bill(paths: MachinePaths, bill: Bill) -> Outcome:
    try:
        bill_store.remove_bill(paths.bills_file, bill)
    except (ValueError, OSError) as exc:
        return Outcome(False, f"Not removed: {exc}")
    return Outcome(True, f"Removed {_describe(bill)}.")


def add_source(paths: MachinePaths, format: str, path: Path) -> Outcome:
    try:
        settings, count = bill_store.add_source(paths, format, path)
    except BillsError as exc:
        return Outcome(False, f"Not added: {exc}")
    except ValueError as exc:  # the settings, or WindowTally's own bills file named
        return Outcome(False, f"Not changed: {exc}")
    except OSError as exc:
        return Outcome(False, f"Not added: {exc}")
    return Outcome(True, f"Added {settings.bill_sources[-1].path}: {plural(count, 'bill')}.")


def remove_source(paths: MachinePaths, path: Path) -> Outcome:
    try:
        bill_store.remove_source(paths, path)
    except (ValueError, OSError) as exc:
        return Outcome(False, f"Not changed: {exc}")
    return Outcome(True, f"Stopped reading {path}.")


def set_reminder(paths: MachinePaths, days: int | None) -> Outcome:
    try:
        set_renewal_reminder(paths.settings_file, days)
    except (ValueError, OSError) as exc:  # SettingsError is a ValueError
        return Outcome(False, f"Not changed: {exc}")
    return Outcome(True, reminder_text(days))


def set_silenced(paths: MachinePaths, silenced: bool) -> Outcome:
    try:
        set_notifications_silenced(paths.settings_file, silenced)
    except (ValueError, OSError) as exc:  # SettingsError is a ValueError
        return Outcome(False, f"Not changed: {exc}")
    if silenced:
        return Outcome(True, "WindowTally's notifications are silenced: what they would say goes to this line and the "
                             "window's log, and Code sessions raise no limit toast.")
    return Outcome(True, "WindowTally's notifications are raised again.")


def arrangement(paths: MachinePaths, status: Status) -> Arrangement | Outcome:
    """The accounts ``status`` lists, as the settings arrange and name them; an Outcome saying why where the settings
    cannot be read, since an arrangement written over them would have to replace what was not read."""
    try:
        settings = load_settings(paths.settings_file)
    except (ValueError, OSError) as exc:  # SettingsError is a ValueError
        return Outcome(False, f"Cannot arrange the accounts: {exc}")
    return Arrangement.of(status, settings)


def set_arrangement(paths: MachinePaths, arranged: Arrangement) -> Outcome:
    """Writes what the window changed onto the settings as they stand; where they changed meanwhile what the window
    changed too, nothing is written, the Outcome says what, and the window's next try saves over it."""
    try:
        edit_account_arrangement(paths.settings_file, arranged.onto)
    except Conflict as conflict:
        arranged.acknowledge(conflict)
        return Outcome(False, f"Not changed: {conflict}")
    except (ValueError, OSError) as exc:  # SettingsError is a ValueError
        return Outcome(False, f"Not changed: {exc}")
    return Outcome(True, "Accounts saved.")


def working_sessions(paths: MachinePaths) -> int:
    return len(working_ids(paths))


def working_ids(paths: MachinePaths) -> frozenset[str]:
    return read_registry(paths.registry_dir).desktop_working_ids()


def set_keep_awake(paths: MachinePaths, on: bool) -> Outcome:
    try:
        save_keep_awake(paths.settings_file, on)
    except (ValueError, OSError) as exc:  # SettingsError is a ValueError
        return Outcome(False, f"Not changed: {exc}")
    if on:
        return Outcome(True, "The computer is kept awake while a Claude Code session works; the screen still turns "
                             "off on its own timer.")
    return Outcome(True, "The computer may sleep while Claude Code sessions work.")


def keep_awake(paths: MachinePaths) -> bool | None:
    """Whether the settings let the service keep the computer awake while Claude Code works; None when they cannot
    be read, which the service takes for on and the next pass reports among the source problems."""
    return keeps_awake(paths.settings_file)


def silenced(paths: MachinePaths) -> bool | None:
    """Whether the settings silence WindowTally's notifications; None when they cannot be read, which the next pass
    reports among the source problems."""
    try:
        return load_settings(paths.settings_file).silence_notifications
    except (ValueError, OSError):  # SettingsError is a ValueError
        return None
