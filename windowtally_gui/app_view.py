"""The composition root: one window per user, the theme, the main window, the tray icon, the Conversations, Bills and
sources, History, Arrange accounts and About windows, the clocks, and quitting. Qt, through PySide6.

    pythonw -m windowtally_gui [--tray] [--shortcut create|remove] [--claude-home D] [--desktop-data D] [--data-dir D]

``--shortcut`` writes or removes the Start menu entry and exits, opening no window (what ``install.ps1`` runs). The three
roots default to this account's own — ``~/.claude``, ``%APPDATA%/Claude`` and ``~/.claude/windowtally`` — and a start
naming them opens the window on another machine's folders. A second start on one data folder asks the window already
running there to show itself, and exits.

Started with ``--tray`` (the logon task) the window opens hidden in the tray; started otherwise (the Start menu) it
shows. Closing the window hides it in the tray; Quit, in the tray's menu or the File menu, ends it. Where the tray icon
cannot be made, closing the window ends it, which the status line says. Whether the icon is really in the taskbar's
notification area is asked of Windows on a clock (``tray_check_model``): while it is not, the icon is made again, hiding
the window minimizes it instead, and a window started hidden shows itself once the icon has been missing for two
minutes. A notification the icon cannot carry, the icon missing or never made, is said on the status line.

The theme the user chose (in the View menu) is the window's own, kept in its record;
every window of WindowTally wears it, since they share one theme. Following Windows, the mode is read again every 3 s.

The user's setting that silences WindowTally's notifications (the View menu and the tray menu) is kept in WindowTally's
settings, which a pass carries into status.json for the desktop plugin: switching it runs a pass. While it is on, a
notice is not raised at all; what it would have said goes to the status line and the log, and it counts as said. The
settings are read again whenever their modification time changes, so a change made by hand is followed; settings that
cannot be read silence nothing, as a pass carries them to the plugin. The switch beside it, on until the user turns it
off, lets the service keep the computer awake while a Claude Code session works; it is kept in the same settings, which
the service reads within seconds, so switching it runs no pass, and settings that cannot be read leave it on, as the
service takes them.

Work off the window's thread runs in three lanes: a pass in one, the History window's computation in another, the
Conversations window's read of the sessions in the third, so none waits for another — the history and the sessions only
read the ledger, which a pass writing it beside them never blocks. Only the window's thread touches a widget:
``Background`` hands each job's end back to the quick clock.

The Conversations window (the main window's Conversations button, the File menu and the tray menu) lists every account's
Code sessions and opens one on the account the desktop app is signed in to through the app's resume link, the shell's
opener the switch's sessions go through; while a switch is being prepared or runs it opens none, since the app may be
closing under it. Its line follows the status each second, and its list is read again with each status, while it shows.

The order the accounts stand in and the names they are shown by are the user's, kept in WindowTally's settings and set in
the Arrange accounts window (the Accounts menu and the tray menu); the service writes status.json in that order and
with those names, so the window shows them as every other surface does, after a pass that follows the change.

Switching an account — the cards' buttons, the Accounts menu, the tray menu — is the account sync's work: the window
starts the installed sync script as a process of its own and reads its answer (``flow_model``, ``sync_model``), and never
touches a credential. It asks first where closing the desktop app would end Code sessions at work, or WindowTally holds no
login to put back; it shows what a switch is doing at the top of the window, with the button that calls it off while it
can be, and says how it ended on the status line, or in a notification where the window is hidden in the tray. The sync's
two switches are shown as the user last set them until a status written after the change confirms them.

A switch of the desktop app offers the sessions of the account it leaves to go on with on the account switched to
(``carry_model``, ``switch_view.CarryDialog``), in place of the question about sessions at work, which it asks too.
Where a Code session of the app is at work, or its status in Claude Code's session registry changed after the last pass,
the ledger has not read all that session did, a turn a limit just stopped among it, so the window first runs a pass with no history page, the header saying so until it ends
and Cancel calling the switch off; a pass already running is not waited for. The sessions chosen are opened in the app
through its resume link once the switch is done (``LinkQueue``, on the quick clock), and a link the shell cannot open
is said. While the sessions are read or chosen no other of the sync's jobs begins, since it would take the flow the
switch is about to need; while they are opened no switch or add of the app begins, since it would close the app under
them, but a switch of the CLI, a turn of the sync's switches and a start of the app may.

Starting the desktop app, where the status reports it not running — the header's button and the tray menu's entry,
enabled only then — is the sync's work too, run as a switch is, and never called off. The window then shows the app as
starting until a status says whether it runs (``live_model.still_starting``). A start asked for from the tray, with the
window hidden, raises a notification only where it was not done: the app's own window is the answer otherwise.

The clocks run whatever a look did, so a look that failed is never the last:

    every 0.5 s   results of work done off the window's thread, in every lane; the switch in progress, and the sessions
                  it carries; a second start's request to show the window
    every 1 s     the countdowns and ages, from the status already read; the Conversations window's line, and its list's
                  ages every 30 s
    every 2 s     status.json, read again only when its modification time changed; the notices; the settings, read again
                  only when their modification time changed
    every 3 s     Windows' light or dark mode, while the theme follows it
    every 5 s     whether Windows holds the tray icon, while it does not; every 60 s while it does
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sqlite3
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu

from windowtally.history import account_slots
from windowtally.ledger import Ledger, LedgerVersionError
from windowtally.palette import ACCOUNT_SLOTS
from windowtally.paths import MachinePaths, default_paths

from . import actions_model, instance_model, shortcut, sync_model
from .about_view import open_about
from .actions_model import Outcome
from .arrange_view import ask_arrangement
from .background import Background
from .bills_view import BillsWindow
from .carry_model import CarryRow, LinkQueue, carry_rows
from .common_view import claim_identity, clock, em, image_of, place_of_window, put_window, set_on_top, work_areas
from .conversations_view import ConversationsWindow
from .flow_model import START, STARTING, AskCliIdle, Done, NeedsCliLogin, OpenSessions, Progress, SwitchFlow
from .history_view import HistoryWindow
from .live_model import live_view, still_starting, tray_view
from .logo_model import logo_rows
from .main_view import SWITCH_LABELS, MainWindow
from .notices_model import Notices
from .state_model import WindowState, fitted_geometry, geometry_text, load_state, place_of, save_state
from .status_model import Account, Status, StatusReader
from .switch_model import (APP, CLI, CONFIRM_SESSIONS, NEEDS_LOGIN, Switches, plan_app_switch, plan_close,
                           switch_entries, switches_to_show)
from .switch_view import ask_add_account, ask_carry, ask_cli_idle, ask_sessions, fill_switch_menu
from .sync_model import SyncRun
from .theme_model import THEME_CHOICES, chosen_mode
from .theme_view import Theme
from .tray_check_model import CHECK_PRESENT_S, TrayWatch
from .tray_view import Tray, TrayUnavailable, icon_sizes

log = logging.getLogger(__name__)

QUICK_MS, TICK_MS, LOOK_MS, MODE_MS = 500, 1000, 2000, 3000
SAVE_DELAY_MS = 1000   # a moved or resized window's place is written this long after it settles
# Lines of the default font, wide and tall: three cards abreast, the fullest among them whole, with two lines to spare
# for the header's condition and notice lines (measured at 150 % on the development machine, 2026-11-11).
DEFAULT_SIZE = (70, 30)


def open_link(link: str) -> None:
    """Hands a link to the shell, which gives a ``claude://`` link to the desktop app that registered it."""
    os.startfile(link)


class App(QObject):
    """``make_tray``, ``start_sync`` and ``open_links`` stand in for the real tray, the real sync script and the shell's
    opener of links in a test."""

    def __init__(self, app: QApplication, paths: MachinePaths, *, start_hidden: bool,
                 make_tray: Callable[..., Tray] = Tray, start_sync: Callable[[list[str]], SyncRun] = SyncRun,
                 open_links: Callable[[str], object] = open_link):
        super().__init__()
        self.app, self.paths = app, paths
        self.open_links = open_links
        self.started = time.time()
        self.state, state_problem = load_state(paths.window_state)
        self.theme = Theme(app, chosen_mode(self.state.theme))
        self.background = Background()
        self.history_work = Background()
        self.conversations_work = Background()
        self.history_window: HistoryWindow | None = None
        self.bills_window: BillsWindow | None = None
        self.conversations_window: ConversationsWindow | None = None
        self.reader = StatusReader(paths.status_file)
        self.notices = Notices(self.started)
        self.colour_of: dict[str, str] = {}
        self._coloured: frozenset[str] | None = None
        self._colours_said = False
        self._settings_seen = self._settings_stamp()
        # The sync's two switches as the window shows them: the status's, except for a change the user made that no
        # status written after it has confirmed yet.
        self.flow = SwitchFlow(paths, sessions=lambda: actions_model.working_sessions(paths), start=start_sync)
        self.links = LinkQueue(open_links)
        # A switch of the app whose sessions are being read first: the account switched to, and what the header says.
        self._reading: tuple[str, Progress] | None = None
        self._choosing = False   # the sessions to carry are being chosen
        self._asked: float | None = None   # when the switch of the app being prepared was asked for
        self.switches = Switches()
        self._switches_changed_at: float | None = None
        # When the window started the desktop app, while it shows the app as starting.
        self._desktop_started_at: float | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save_now)
        self._tray_timer = QTimer(self)
        self._tray_timer.setSingleShot(True)
        self._tray_timer.timeout.connect(self._check_tray)
        actions = {"refresh": self.refresh, "history_view": self.open_history,
                   "conversations": self.open_conversations, "folder": self.data_folder,
                   "record": lambda: self.open_bills(record=True), "bills": self.open_bills,
                   "keep_on_top": self._keep_on_top_changed, "silence": self._silence_changed,
                   "keep_awake": self._keep_awake_changed, "theme": self._theme_changed,
                   "follows": lambda: self._switch_changed("follows"),
                   "one_click": lambda: self._switch_changed("one_click"),
                   "add_account": self.add_account, "arrange": self.arrange_accounts,
                   "cancel_switch": self.cancel_switch, "start_desktop": self.start_desktop,
                   "hide": self.hide, "quit": self.quit,
                   "about": self.show_about}
        self.main = MainWindow(self.theme, actions, keep_on_top=self.state.keep_on_top,
                               silenced=actions_model.silenced(paths) is True,
                               keep_awake=actions_model.keep_awake(paths) is not False, theme_choice=self.state.theme,
                               entries=self.menu_entries, switch_to=self.switch_to, on_close=self._closed,
                               on_place=self._moved)
        self._window_icon()
        self.tray = self._make_tray(actions, make_tray)
        self.tray_watch = TrayWatch()
        set_on_top(self.main, self.state.keep_on_top)
        self._place_window()
        if state_problem:
            self.main.say(state_problem, ok=False)
        if not self.tray:
            self.main.say("The tray icon could not be made: closing the window quits it, and notifications are said "
                          "here. See window.log.", ok=False)
        if not start_hidden or not self.tray:
            self.show()
        self._look()
        self._quick()
        self.render()
        self._clocks = [clock(self, QUICK_MS, self._quick), clock(self, TICK_MS, self.render),
                        clock(self, LOOK_MS, self._look), clock(self, MODE_MS, self._mode)]
        if self.tray:
            self._check_tray()

    # --- setting up ---------------------------------------------------------------------------------------------

    def _make_tray(self, actions, make_tray) -> Tray | None:
        """The tray's menu: the window's actions, then what the Accounts menu holds, its switch menus written afresh
        whenever the menu is about to show."""
        menu = QMenu()
        menu.aboutToShow.connect(self._fill_tray_switch_menus)
        for label, key in (("Show the window", None), ("Refresh now", "refresh"), ("Conversations", "conversations"),
                           ("History", "history_view"), ("Record a bill", "record"), ("Bills and sources", "bills")):
            action = menu.addAction(label)
            action.triggered.connect(lambda _checked=False, k=key: self.show() if k is None else actions[k]())
        self._tray_start: QAction = menu.addAction("Start the desktop app")
        self._tray_start.triggered.connect(lambda _checked=False: actions["start_desktop"]())
        self._tray_start.setEnabled(False)
        menu.addSeparator()
        menu.addAction(self.main.follows)
        menu.addAction(self.main.one_click)
        menu.addAction("Add an account…").triggered.connect(lambda _checked=False: actions["add_account"]())
        menu.addAction("Arrange accounts…").triggered.connect(lambda _checked=False: actions["arrange"]())
        self.tray_switch_menus: dict[str, QMenu] = {}
        for client in (APP, CLI):
            self.tray_switch_menus[client] = menu.addMenu(SWITCH_LABELS[client])
        menu.addSeparator()
        menu.addAction(self.main.silenced)
        menu.addAction(self.main.keep_awake)
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(lambda _checked=False: self.quit())
        self.tray_menu = menu
        try:
            return make_tray(self.theme, self.show, menu)
        except TrayUnavailable:
            log.exception("The tray icon could not be made")
            return None

    def _fill_tray_switch_menus(self) -> None:
        """Whenever the tray menu is about to show: the start of the desktop app, enabled only while the status reports
        the app not running, and the switch menus written afresh."""
        now = time.time()
        self._tray_start.setEnabled(tray_view(self.reader.snapshot, now, self._starting(now)).can_start)
        for client, sub in self.tray_switch_menus.items():
            entries, empty = self.menu_entries(client)
            fill_switch_menu(sub, entries, empty, self.switch_to)

    def _window_icon(self) -> None:
        """The window's own icon: the logo, drawn at each size Windows draws a window's icons at on this display, so
        none is scaled up."""
        icon = QIcon()
        for size in icon_sizes():
            icon.addPixmap(QPixmap.fromImage(image_of(logo_rows(size))))
        self.app.setWindowIcon(icon)

    def _place_window(self) -> None:
        """The remembered place, cut to the monitors attached now; else the default size."""
        ratio = QGuiApplication.primaryScreen().devicePixelRatio()
        default = (round(em(DEFAULT_SIZE[0]) * ratio), round(em(DEFAULT_SIZE[1]) * ratio))
        put_window(self.main, *place_of(fitted_geometry(self.state.geometry, work_areas(), default)))

    # --- showing and hiding ---------------------------------------------------------------------------------------

    def show(self) -> None:
        self.main.setWindowState(self.main.windowState() & ~Qt.WindowState.WindowMinimized)
        self.main.show()
        self.main.raise_()
        self.main.activateWindow()
        self._moved()

    def hide(self) -> None:
        """Into the tray; minimized instead where the icon is missing or was never made, since a window hidden then
        could be found again only by a second start."""
        if self._icon_shown():
            self.main.hide()
        else:
            self.main.showMinimized()

    def _closed(self) -> None:
        if self.tray:
            self.hide()
        else:
            self.quit()

    def _icon_shown(self) -> bool:
        """Whether the tray icon exists and Windows holds it, asked again now: the clock's last look may be a minute
        old."""
        return self.tray is not None and not self.tray_watch.missing and self.tray.present() is not False

    def quit(self) -> None:
        self._save_now()
        self.stop()
        if self.tray:
            self.tray.destroy()
        self.main.quitting = True
        self.main.hide()
        self.app.quit()

    def stop(self) -> None:
        for timer in (*self._clocks, self._tray_timer):
            timer.stop()

    # --- clocks ---------------------------------------------------------------------------------------------------

    def _quick(self) -> None:
        self.background.poll()
        self.history_work.poll()
        self.conversations_work.poll()
        for event in self.flow.tick():
            self._flow_event(event)
        for failure in self.links.tick():
            outcome = Outcome(False, f"Not opened in the desktop app: {failure.title} ({failure.error}).")
            self.main.say(outcome.message, ok=False)
            self._tell_tray(outcome)
        self._show_progress()
        if instance_model.take_request(self.paths):
            self.show()

    def _look(self) -> None:
        snapshot = self.reader.poll()
        now = time.time()
        if snapshot is not None:
            if snapshot.status is not None:
                self._colours(snapshot.status)
            said, state = self.notices.on_status(snapshot, self.state)
            self._notify(said)
            self._remember(state)
            self.render()
            if self.conversations_window is not None:
                self.conversations_window.status_changed()
        self._notify(self.notices.on_clock(self.reader.snapshot, now))
        self._follow_settings()

    def _mode(self) -> None:
        mode = chosen_mode(self.state.theme)
        if mode != self.theme.mode:
            self.theme.apply(mode)
            self.render()

    def _check_tray(self) -> None:
        """Asks Windows whether it holds the tray icon, and acts on the answer as ``tray_check_model`` says."""
        step = None
        try:
            step = self.tray_watch.on_check(self.tray.present(), time.time(), hidden=self.main.isHidden())
            if step.note:
                (log.warning if step.recreate else log.info)(step.note)
            if step.recreate:
                self.tray.recreate()
            if step.say:
                self.main.say(step.say, ok=step.ok)
            if step.show:
                self.show()
        finally:
            delay = step.next_check_s if step is not None else CHECK_PRESENT_S
            self._tray_timer.start(int(delay * 1000))

    def render(self) -> None:
        now = time.time()
        snapshot = self.reader.snapshot
        self._adopt_switches()
        starting = self._starting(now)
        self.main.show_view(live_view(snapshot, now, self.switches, starting), self.colour_of)
        if self.conversations_window is not None and self.conversations_window.isVisible():
            self.conversations_window.tick()
        if self.tray:
            view = tray_view(snapshot, now, starting)
            role = self.colour_of.get(view.account or "", "ink-2")
            self.tray.show(view, self.theme.c.get(role, self.theme.c["ink-2"]))

    def _notify(self, notices) -> None:
        if not notices:
            return    # nearly every look: Windows is asked about the icon only for something to carry
        silenced = self.main.silenced.isChecked()
        if silenced or not self._icon_shown():
            # Silenced, or with no icon in the tray to carry a notification, which Qt would drop without a word: every
            # notice of the batch goes to the status line together, so none hides another.
            why = "silenced" if silenced else "no tray icon"
            for notice in notices:
                log.info("Notice, %s: %s — %s", why, notice.title, notice.message)
            self.main.say(" ".join(f"{n.title}. {n.message}" for n in notices),
                          ok=not any(n.kind in ("stopped", "problem") for n in notices))
            return
        for notice in notices:
            log.info("Notice: %s — %s", notice.title, notice.message)
            self.tray.notify(notice.title, notice.message)

    # --- account colours ------------------------------------------------------------------------------------------

    def _colours(self, status) -> None:
        """Each account's colour as the history page gives it, read again whenever the accounts change. Where the
        ledger cannot be read (not made yet, or locked), the list's order stands in and the ledger is tried again with
        the next status file, so the page's colours arrive once it can be read."""
        accounts = frozenset(a.uuid for a in status.accounts)
        if accounts == self._coloured:
            return
        try:
            ledger = Ledger.open_readonly(self.paths.ledger_db)
            try:
                self.colour_of = {account.uuid: token for account, token in
                                  account_slots(ledger, ledger.known_accounts())}
            finally:
                ledger.close()
        except (FileNotFoundError, LedgerVersionError, sqlite3.Error) as exc:
            self.colour_of = {a.uuid: ACCOUNT_SLOTS[i] if i < len(ACCOUNT_SLOTS) else "muted"
                              for i, a in enumerate(status.accounts)}
            if not self._colours_said:
                self._colours_said = True
                self.main.say(f"The accounts' colours follow the list here until the ledger can be read ({exc}).",
                              ok=False)
            return
        self._coloured = accounts

    # --- actions --------------------------------------------------------------------------------------------------

    def _tell(self, outcome: Outcome) -> None:
        self.main.say(outcome.message, outcome.ok)

    def _deliver(self, outcome: Outcome) -> None:
        self._tell(outcome)
        self._look_now()

    def refresh(self, after: Outcome | None = None) -> None:
        """One pass now. ``after`` is what a change said — in the Bills window, the settings, a switch — kept at the
        head of the status line while the pass runs and after it, in its own colour, so the change's word is not lost
        to the pass's."""
        def led(outcome: Outcome) -> Outcome:
            return actions_model.after(after, outcome)

        if not self.background.start("refresh", lambda: actions_model.refresh(self.paths),
                                     lambda outcome: self._deliver(led(outcome)),
                                     lambda error: self._deliver(led(Outcome(False, f"Not refreshed: {error}")))):
            if after is not None:
                self._tell(led(Outcome(True, "A pass is already running; the figures follow at the service's next "
                                             "pass.")))
            else:
                self.main.say(f"Not started: a {self.background.running} is running; its result comes first.")
            return
        self._tell(led(Outcome(True, "Reading every source…")))

    def data_folder(self) -> None:
        outcome = actions_model.data_folder(self.paths, os.startfile)
        self.main.say(outcome.message, outcome.ok)

    def open_bills(self, record: bool = False) -> None:
        if self.bills_window is None:
            self.bills_window = BillsWindow(self.theme, self.paths, self._known_accounts,
                                            lambda outcome: self.refresh(after=outcome))
        # Kept on top with the main window, which would cover it: it opens from the tray while that one is hidden, so
        # it is no window of the main one's.
        set_on_top(self.bills_window, self.main.keep_on_top.isChecked())
        self.bills_window.open(self.main, record=record)

    def _known_accounts(self) -> tuple[str, ...]:
        status = self._status()
        return tuple(a.email for a in status.accounts if a.email) if status is not None else ()

    def open_history(self) -> None:
        if self.history_window is None:
            self.history_window = HistoryWindow(self.theme, self.paths, self._source_errors, self.history_work)
        # Kept on top with the main window: it opens from the tray while that one is hidden.
        set_on_top(self.history_window, self.main.keep_on_top.isChecked())
        self.history_window.open()

    def _source_errors(self) -> tuple[str, ...]:
        status = self._status()
        return status.source_errors if status is not None else ()

    def open_conversations(self) -> None:
        if self.conversations_window is None:
            self.conversations_window = ConversationsWindow(
                self.theme, self.paths, self.conversations_work, self._status, self._preparing,
                lambda: actions_model.working_ids(self.paths), self.open_links)
        # Kept on top with the main window: it opens from the tray while that one is hidden.
        set_on_top(self.conversations_window, self.main.keep_on_top.isChecked())
        self.conversations_window.open()

    def show_about(self) -> None:
        open_about(self.main, self.theme)

    def arrange_accounts(self) -> None:
        """The Arrange accounts window: the accounts' order and names, written to WindowTally's settings, then a pass, so
        every surface follows at once; the window's words stay at the head of the status line through the pass."""
        status = self._status()
        if status is None or not status.accounts:
            self.main.say("No account is known yet, so there is none to arrange.", ok=False)
            return
        arrangement = actions_model.arrangement(self.paths, status)
        if isinstance(arrangement, Outcome):
            self.main.say(arrangement.message, ok=False)
            return
        outcome = ask_arrangement(self.main, self.theme, arrangement,
                                  lambda arranged: actions_model.set_arrangement(self.paths, arranged))
        if outcome is not None:
            self.refresh(after=outcome)

    def _look_now(self) -> None:
        snapshot = self.reader.poll()
        if snapshot is not None:
            if snapshot.status is not None:
                self._colours(snapshot.status)
            said, state = self.notices.on_status(snapshot, self.state)
            self._notify(said)
            self._remember(state)
        self.render()

    # --- switching accounts ---------------------------------------------------------------------------------------

    def _status(self) -> Status | None:
        snapshot = self.reader.snapshot
        return snapshot.status if snapshot is not None else None

    def _adopt_switches(self) -> None:
        """Takes the sync's two switches from the status, except while a change the user made stands: it stands until a
        status written after it has been read, which is the first to say what the sync now holds."""
        status = self._status()
        if (status is not None and self._switches_changed_at is not None and status.generated_at is not None
                and status.generated_at >= self._switches_changed_at):
            self._switches_changed_at = None
        self.switches = switches_to_show(status, self.switches, self._switches_changed_at)
        self.main.follows.setChecked(self.switches.follows)
        self.main.one_click.setChecked(self.switches.one_click)

    def menu_entries(self, client: str):
        """The accounts a menu offers to switch ``client`` to, and what it says when there are none."""
        status = self._status()
        if status is None:
            return (), "No status yet"
        entries = switch_entries(status, client, self.switches)
        if entries:
            return entries, ""
        if client == APP and not self.switches.one_click:
            return (), "One-click switching is off"
        if client == CLI and self.switches.follows:
            return (), "The CLI follows the desktop app"
        return (), "No other account"

    def _sessions_at_work(self, status: Status) -> int:
        """The Code sessions at work as Claude Code's session registry says now, or as the last status said, whichever
        counts more: the question before the client is closed is better asked once too often than missed."""
        return max(actions_model.working_sessions(self.paths), status.working_sessions)

    def _preparing(self) -> bool:
        """Whether a job is running or a switch of the app is being prepared — its sessions read first, or chosen — so
        that the flow is taken, or about to be: no other job may begin."""
        return self.flow.busy or self._reading is not None or self._choosing

    def _switching(self) -> bool:
        """Whether anything that closes the desktop app must wait: a job, a switch being prepared, or the sessions a
        switch carries still being opened in the app."""
        return self._preparing() or self.links.pending > 0

    def switch_to(self, client: str, uuid: str) -> None:
        """A button or a menu entry: switch the desktop app or the CLI to the account. A switch of the CLI closes no
        app, so the sessions a switch of the app is opening do not hold it back."""
        status = self._status()
        account = status.account(uuid) if status is not None else None
        if account is None:
            self.main.say("That account is not in the status any more.", ok=False)
        elif self._switching() if client == APP else self._preparing():
            self.main.say("A switch is already under way; its progress is at the top.", ok=False)
        elif client == APP:
            self._switch_app(status, account)
        else:
            self.flow.switch_cli(account.uuid, account.label)
            self._show_progress()

    def _switch_app(self, status: Status, account: Account) -> None:
        plan = plan_app_switch(account, self._sessions_at_work(status))
        if plan.kind == NEEDS_LOGIN:
            self.add_account(lead=f"No stored desktop login of {account.label}: the app cannot switch to it in one step.")
            return
        self._asked = time.time()
        left = self._account_left(status)
        if left is not None and actions_model.ledger_behind(self.paths, status) and self._read_first(account, left):
            return
        self._offer(account.uuid)

    def _account_left(self, status: Status) -> Account | None:
        """The account the desktop app is signed in to, whose sessions a switch of it leaves; None at its sign-in
        page."""
        return status.account(status.desktop_account) if status.desktop_signed_in else None

    def _read_first(self, account: Account, left: Account) -> bool:
        """Runs a pass before the sessions are offered, so they hold what the ledger has not read yet; False where the
        lane is taken by a pass already running, whose ledger the offer then reads as it stands."""
        progress = Progress(f"Reading the sessions of {left.label} before switching the desktop app to "
                            f"{account.label}…", True)
        if not self.background.start("pass", lambda: actions_model.read_sources(self.paths),
                                     lambda outcome: self._read(account.uuid, outcome),
                                     lambda error: self._read(account.uuid, Outcome(False, f"Not read: {error}"))):
            return False
        self._reading = (account.uuid, progress)
        self._show_progress()
        return True

    def _read(self, uuid: str, outcome: Outcome) -> None:
        """The pass before a switch has ended: the switch goes on, unless it was called off meanwhile."""
        if self._reading is None or self._reading[0] != uuid:
            return
        self._reading = None
        if not outcome.ok:
            log.warning("The sessions to carry are read from the ledger as it stands: %s", outcome.message)
        self._look_now()
        self._offer(uuid)

    def _offer(self, uuid: str) -> None:
        """Asks what the switch of the app to ``uuid`` carries, where the account left has sessions to offer, or else
        whether to end the sessions at work, then starts it."""
        status = self._status()
        account = status.account(uuid) if status is not None else None
        if account is None:
            self.main.say("That account is not in the status any more.", ok=False)
            return
        plan = plan_app_switch(account, self._sessions_at_work(status))
        if plan.kind == NEEDS_LOGIN:   # the pass found its stored login refused meanwhile
            self.add_account(lead=f"No stored desktop login of {account.label}: the app cannot switch to it in one "
                                  f"step.")
            return
        left = self._account_left(status)
        rows = self._carry_rows(left) if left is not None else ()
        wait, carry = False, ()
        if rows:
            self._choosing = True
            try:
                answer, chosen = ask_carry(self.main, left.label, account.label, rows, plan.sessions)
            finally:
                self._choosing = False
            if answer == "cancel":
                return
            wait = answer == "wait"
            titles = {row.session_id: row.title for row in rows}
            carry = tuple((session, titles[session]) for session in chosen)
        elif plan.kind == CONFIRM_SESSIONS:
            answer = ask_sessions(self.main, plan.sessions, f"switching the desktop app to {account.label}", "Switch")
            if answer == "cancel":
                return
            wait = answer == "wait"
        if not self.flow.switch_app(account.uuid, account.label, follows=self.switches.follows, wait=wait,
                                    carry=carry):
            self.main.say("Not switched: another of the account sync's jobs began meanwhile; switch again once it is "
                          "over.", ok=False)
            return
        self._show_progress()

    def _carry_rows(self, left: Account) -> tuple[CarryRow, ...]:
        """The sessions of ``left`` a switch offers: the ledger's, and those at work; the working alone where the ledger
        cannot be read. What was just used is counted from when the switch was asked for, not from the end of the pass
        it may have waited for."""
        now = time.time()
        working = actions_model.working_ids(self.paths)
        try:
            lines = actions_model.carry_lines(self.paths, left.uuid, now)
        except FileNotFoundError:
            lines = []
        except (LedgerVersionError, sqlite3.Error) as exc:
            log.warning("The sessions of %s could not be read from the ledger: %s", left.label, exc)
            lines = []
        return carry_rows(lines, working, now, asked=self._asked)

    def add_account(self, lead: str = "") -> None:
        answer = ask_add_account(self.main, lead)
        if answer == "open":
            self._open_sign_in_page()
        elif answer == "terminal":
            try:
                sync_model.open_login_terminal(self.paths)
            except OSError as exc:
                self.main.say(f"The terminal could not be opened: {exc}", ok=False)

    def _open_sign_in_page(self) -> None:
        """Adding an account: the sync stores the login the desktop app holds and leaves the app at its sign-in page,
        which closes the app first."""
        status = self._status()
        if self._switching():
            self.main.say("A switch is already under way; its progress is at the top.", ok=False)
            return
        at_work = self._sessions_at_work(status) if status is not None else actions_model.working_sessions(self.paths)
        plan = plan_close(at_work)
        wait = False
        if plan.kind == CONFIRM_SESSIONS:
            answer = ask_sessions(self.main, plan.sessions, "opening the desktop app's sign-in page", "Open")
            if answer == "cancel":
                return
            wait = answer == "wait"
        self.flow.add_account(wait=wait)
        self._show_progress()

    def _switch_changed(self, which: str) -> None:
        """One of the two switches was turned in a menu: it stands at once, and the sync is told."""
        action = self.main.follows if which == "follows" else self.main.one_click
        wanted = action.isChecked()
        if self._preparing():
            action.setChecked(not wanted)
            self.main.say("A switch is under way; turn this one when it is over.", ok=False)
            return
        change = {"follows": wanted} if which == "follows" else {"one_click": wanted}
        self.flow.set_switch(**change)
        self.switches = replace(self.switches, **change)
        self._switches_changed_at = time.time()
        self.render()

    def _starting(self, now: float) -> bool:
        """Whether the desktop app the window started is still shown as starting; the start is forgotten once not."""
        if not still_starting(self._status(), self._desktop_started_at, now):
            self._desktop_started_at = None
        return self._desktop_started_at is not None

    def _show_progress(self) -> None:
        """What a job is doing; with none, the sessions a switch reads first or opens, or a start of the desktop app
        that no status has answered yet."""
        opening = self.links.progress_words()
        self.main.show_progress(self.flow.progress or (self._reading[1] if self._reading is not None else None)
                                or (Progress(opening, False) if opening else None)
                                or (STARTING if self._starting(time.time()) else None))

    def start_desktop(self) -> None:
        """The header's button or the tray menu's entry: start the desktop app, which the status reports not running."""
        if self._preparing():
            self.main.say("A switch is already under way; its progress is at the top.", ok=False)
            return
        self.flow.start_app()
        self._desktop_started_at = time.time()
        self._show_progress()
        self.render()

    def cancel_switch(self) -> None:
        if self._reading is not None and not self.flow.busy:
            # The pass goes on to its end, as the service's would; the switch it was run for is called off.
            self._reading = None
            self.main.say("Cancelled; nothing was changed.")
        elif not self.flow.cancel():
            self.main.say("The switch can no longer be called off: the desktop app is closing.", ok=False)
        self._show_progress()

    def _flow_event(self, event) -> None:
        if isinstance(event, Done):
            outcome = event.outcome
            if not outcome.ok:
                self._switches_changed_at = None   # a switch that was not turned goes back to what the status says
                if event.kind == START:
                    self._desktop_started_at = None   # nothing was started: the status's word stands again
                self.render()
            if event.refresh:
                self.refresh(after=outcome)
            else:
                self.main.say(outcome.message, outcome.ok)
            if event.kind != START or not outcome.ok:
                self._tell_tray(outcome)
        elif isinstance(event, OpenSessions):
            self.links.add(event.sessions)
        elif isinstance(event, AskCliIdle):
            if ask_cli_idle(self.main, event.label):
                self.flow.wait_for_cli()
            else:
                self.flow.cancel()
        elif isinstance(event, NeedsCliLogin):
            self.main.say(f"No CLI sign-in is stored for {event.label}: a terminal opens to sign in.", ok=False)
            try:
                sync_model.open_login_terminal(self.paths)
            except OSError as exc:
                self.main.say(f"The terminal could not be opened: {exc}", ok=False)

    def _tell_tray(self, outcome: Outcome) -> None:
        """A switch asked for from the tray, with the window hidden, has no status line to answer on: the notification
        does, unless the user silenced notifications or the icon is missing, the status line then being its only word."""
        viewable = self.main.isVisible() and not self.main.isMinimized()
        if self._icon_shown() and not self.main.silenced.isChecked() and not viewable:
            self.tray.notify("WindowTally", outcome.message)

    # --- the settings ---------------------------------------------------------------------------------------------

    def _settings_stamp(self) -> int | None:
        try:
            return os.stat(self.paths.settings_file).st_mtime_ns
        except OSError:
            return None

    def _follow_settings(self) -> None:
        """Takes up the silence and keep-awake settings when the settings changed by another hand. Settings that cannot
        be read count as not silencing, as a pass counts them for the plugin, so the window and the Code sessions never
        disagree, and as keeping awake, as the service counts them; the next pass names them among the source
        problems."""
        stamp = self._settings_stamp()
        if stamp == self._settings_seen:
            return
        self._settings_seen = stamp
        self.main.silenced.setChecked(actions_model.silenced(self.paths) is True)
        self.main.keep_awake.setChecked(actions_model.keep_awake(self.paths) is not False)

    def _silence_changed(self) -> None:
        on = self.main.silenced.isChecked()
        outcome = actions_model.set_silenced(self.paths, on)
        if not outcome.ok:
            self.main.silenced.setChecked(not on)
            self.main.say(outcome.message, ok=False)
            return
        self._settings_seen = self._settings_stamp()
        self.refresh(after=outcome)

    def _keep_awake_changed(self) -> None:
        """The keep-awake's switch: written to the settings, which the service reads within seconds, so no pass runs."""
        on = self.main.keep_awake.isChecked()
        outcome = actions_model.set_keep_awake(self.paths, on)
        if not outcome.ok:
            self.main.keep_awake.setChecked(not on)
        else:
            self._settings_seen = self._settings_stamp()
        self.main.say(outcome.message, ok=outcome.ok)

    # --- the window's record --------------------------------------------------------------------------------------

    def _keep_on_top_changed(self) -> None:
        on = self.main.keep_on_top.isChecked()
        set_on_top(self.main, on)
        for other in (self.bills_window, self.history_window, self.conversations_window):
            if other is not None:
                set_on_top(other, on)
        self._remember(replace(self.state, keep_on_top=on))

    def _theme_changed(self) -> None:
        choice = self.main.theme_choice
        if choice not in THEME_CHOICES:
            return
        self._remember(replace(self.state, theme=choice))
        mode = chosen_mode(choice)
        if mode != self.theme.mode:
            self.theme.apply(mode)
            self.render()

    def _remember(self, state: WindowState) -> None:
        if state != self.state:
            self.state = state
            self._save_timer.start()

    def _moved(self) -> None:
        main = self.main
        if not main.isVisible() or main.isMinimized() or main.isMaximized():
            return
        geometry = geometry_text(*place_of_window(main))
        if geometry != self.state.geometry:
            self._remember(replace(self.state, geometry=geometry))

    def _save_now(self) -> None:
        self._save_timer.stop()
        try:
            save_state(self.paths.window_state, self.state)
        except OSError as exc:
            log.warning("The window's record was not written: %s", exc)

    def callback_failed(self, kind, value, trace) -> None:
        log.error("Unexpected error", exc_info=(kind, value, trace))
        self.main.say(f"Something went wrong ({value}); the details are in {self.paths.window_log}.", ok=False)


def arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="windowtally_gui", description="The WindowTally window.")
    parser.add_argument("--tray", action="store_true", help="start hidden in the tray (what the logon task runs)")
    parser.add_argument("--shortcut", choices=("create", "remove"),
                        help="write or remove the Start menu entry, then exit (what install.ps1 runs)")
    parser.add_argument("--claude-home", help="Claude Code's folder (default ~/.claude)")
    parser.add_argument("--desktop-data", help="the desktop app's data folder (default %%APPDATA%%/Claude)")
    parser.add_argument("--data-dir", help="WindowTally's data folder (default ~/.claude/windowtally)")
    return parser.parse_args(argv)


def machine_paths(args: argparse.Namespace) -> MachinePaths:
    """The three roots the start names, each one it leaves out this account's own."""
    defaults = default_paths()
    return MachinePaths(claude_home=Path(args.claude_home) if args.claude_home else defaults.claude_home,
                        desktop_data=Path(args.desktop_data) if args.desktop_data else defaults.desktop_data,
                        data_dir=Path(args.data_dir) if args.data_dir else defaults.data_dir)


def _logging(paths: MachinePaths) -> None:
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(paths.window_log, maxBytes=256 * 1024, backupCount=1,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers[:] = [handler]


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
    if args.shortcut:
        return shortcut.main(args.shortcut)
    paths = machine_paths(args)
    lock = instance_model.claim(paths)
    if lock is None:
        instance_model.ask_to_show(paths)
        return 0
    _logging(paths)
    claim_identity()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("WindowTally")
    app.setQuitOnLastWindowClosed(False)
    shell = App(app, paths, start_hidden=args.tray)
    sys.excepthook = shell.callback_failed
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
