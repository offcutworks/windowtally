"""The main window.

From the top: the menu bar (File, Accounts, Bills, View, Help); on one line, how long ago the status was written, which
account the desktop app and the CLI use and whether the CLI follows the app, with the actions — Refresh now,
Conversations, History, Bills, Data folder — at the line's right end, each with its hint; where the window is too narrow
for the words' widest piece beside them, the actions stand on a row of their own under the words, at its right end
still; this month's totals across the accounts,
and what keeps the CLI from following; while the desktop app is not running, a line saying so with the button that starts
it; what a switch of an account, or a start of the app, is doing, with the button that calls a switch off, while one
runs; the recommendation, on a band of its own; one card per account, as many abreast as the width holds, each with the
buttons that switch the desktop app or the CLI to it, and under the cards a line for each account whose plan has ended
and that no client uses, a column wide and as many abreast as the cards; while there are any, the source problems,
counted, their list behind a button; and a status line saying what the last action did. While there is no status to
show, the cards' place says why. Below the menu bar everything stands on the page ground (``theme_view.Ground``).

The Accounts menu holds the two switches of the account sync (the CLI follows the desktop app; one-click switching of
the app), Add an account, Arrange accounts, and one menu for each client with the accounts it can be switched to, written
afresh each time the menu is about to show. The menus and the cards take their offers from ``switch_model``, so they
never disagree, and stand in status.json's order, so a switch moves the cards: the accounts in use stand first.

The checkable entries are one ``QAction`` each, a menu of the window and the tray's showing the same one, so no two
surfaces can disagree. Keep on top and the theme are set in the View menu alone, the theme among its radio items, bound
to the one choice the window keeps.

The actions are buttons and menu entries of their own, always there and always enabled: one pressed while a pass already
runs says so in the status line rather than vanishing or greying out.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton, QVBoxLayout,
                               QWidget)

from .cards_view import AccountCard, EndedLine, Flow
from .common_view import Hint, ScrollFrame, em, plain_label
from .flow_model import Progress
from .live_model import NOT_RUNNING, LiveView
from .switch_model import APP, CLI, SwitchEntry
from .switch_view import fill_switch_menu
from .theme_model import THEME_CHOICES, THEME_LABELS
from .theme_view import Ground, Theme

# A card's least width, in lines of the default font: what holds, cutting no word, a card's title row with a name of
# eight letters, its two switch buttons and their gaps, and keeps each window's line — when it resets, the pace and the
# reading — on one row at its usual length (measured at 150 % on the development machine, 2026-11-11).
CARD_WIDTH = 22
PROBLEM_LINES = 8    # lines of the default font the source problems' list stands in before it scrolls

SWITCH_LABELS = {APP: "Switch the desktop app to", CLI: "Switch the CLI to"}
# The actions at the right end of the header's line: each one's key in the window's actions, its words and its hint.
ACTIONS = (
    ("refresh", "Refresh now", "Read every source now, as the service does each minute (F5)"),
    ("conversations", "Conversations", "Every account's Code sessions, each opened from there on the account in use"),
    ("history_view", "History", "The history over 7 days, 30 days, 6 months or all, in a window of its own, exported "
                                "from there as HTML"),
    ("bills", "Bills", "Record a bill, every bill recorded, the bill files read, the renewal reminder"),
    ("folder", "Data folder", "Open WindowTally's data folder"))


def _wrapped(ink: str, theme: Theme, parent: QWidget) -> QLabel:
    label = plain_label(parent)
    label.setWordWrap(True)
    theme.ink(label, ink)
    return label


class MainWindow(QMainWindow):
    def __init__(self, theme: Theme, actions: dict[str, Callable[[], None]], *, keep_on_top: bool, silenced: bool,
                 theme_choice: str, entries: Callable[[str], tuple[tuple[SwitchEntry, ...], str]],
                 switch_to: Callable[[str, str], None], on_close: Callable[[], None],
                 on_place: Callable[[], None], keep_awake: bool):
        super().__init__()
        self.theme, self.actions = theme, actions
        self.entries, self.switch_to = entries, switch_to
        self.on_close, self.on_place = on_close, on_place
        self.quitting = False    # Qt closes every window as it quits, and one that refuses calls the quit off
        self.setWindowTitle("WindowTally")
        pad = em(0.5)
        self.pad = pad
        self.theme_choice = theme_choice
        self.keep_on_top = self._switch("Keep on top", keep_on_top, "keep_on_top")
        self.silenced = self._switch("Silence notifications", silenced, "silence")
        self.keep_awake = self._switch("Keep the computer awake while Claude Code works", keep_awake, "keep_awake")
        self.follows = self._switch("The CLI follows the desktop app", True, "follows")
        self.one_click = self._switch("One-click switching of the desktop app", True, "one_click")
        self.theme_actions: dict[str, QAction] = {}
        self.switch_menus: dict[str, QMenu] = {}
        self._menu_bar()

        central = Ground(theme, self)
        self.setCentralWidget(central)
        page = QVBoxLayout(central)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)

        head = QVBoxLayout()
        head.setContentsMargins(pad * 2, pad, pad * 2, 0)
        head.setSpacing(pad // 2)
        # The status's age, the warning colour while it is stale, and the accounts in use, on one line while they fit;
        # at the line's right end the actions (``_place_actions``).
        self.head_line = QGridLayout()
        self.head_line.setContentsMargins(0, 0, 0, 0)
        self.head_line.setHorizontalSpacing(pad)
        self.head_line.setVerticalSpacing(pad // 2)
        self.head_line.setColumnStretch(0, 1)
        self.status_line = Flow(theme, ("ink-2", "ink-2"), ("", " · "), parent=central)
        self.head_line.addWidget(self.status_line, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        self.actions_bar = QWidget(central)
        bar = QHBoxLayout(self.actions_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(pad)
        self.action_buttons: dict[str, QPushButton] = {}
        for key, text, hint in ACTIONS:
            button = QPushButton(text, self.actions_bar)
            button.clicked.connect(lambda _checked=False, k=key: actions[k]())
            bar.addWidget(button)
            Hint(button, hint)
            self.action_buttons[key] = button
        self._actions_under: bool | None = None    # whether the actions stand under the words rather than beside them
        self._actions_key: tuple | None = None      # the words and the width the actions were last placed for
        self._place_actions()
        head.addLayout(self.head_line)
        self.totals = _wrapped("ink-2", theme, central)
        self.totals.hide()
        head.addWidget(self.totals)
        self.condition = _wrapped("warning-text", theme, central)
        self.condition.hide()
        head.addWidget(self.condition)
        # The desktop app not running, with the button that starts it; there only while the status reports it.
        self.closed_row = QWidget(central)
        closed = QHBoxLayout(self.closed_row)
        closed.setContentsMargins(0, 0, 0, 0)
        closed.addWidget(_wrapped("warning-text", theme, self.closed_row), 1)
        closed.itemAt(0).widget().setText(NOT_RUNNING)
        start = QPushButton("Start the desktop app", self.closed_row)
        start.clicked.connect(lambda: actions["start_desktop"]())
        closed.addWidget(start)
        self.closed_row.hide()
        head.addWidget(self.closed_row)
        # What a switch is doing, with the button that calls it off while it can be; there only while one runs.
        self.progress_row = QWidget(central)
        progress = QHBoxLayout(self.progress_row)
        progress.setContentsMargins(0, 0, 0, 0)
        self.progress = _wrapped("ink", theme, self.progress_row)
        progress.addWidget(self.progress, 1)
        self.cancel = QPushButton("Cancel", self.progress_row)
        self.cancel.clicked.connect(lambda: actions["cancel_switch"]())
        progress.addWidget(self.cancel)
        self.progress_row.hide()
        head.addWidget(self.progress_row)
        page.addLayout(head)

        band = QFrame(central)
        band.setProperty("surface", "band")
        banded = QHBoxLayout(band)
        banded.setContentsMargins(0, 0, pad, 0)
        banded.setSpacing(pad)
        self.accent = QFrame(band)
        self.accent.setFixedWidth(3)
        theme.mark(self.accent, "surface", "accent")
        banded.addWidget(self.accent)
        self.next = _wrapped("ink", theme, band)
        self.next.setContentsMargins(0, pad // 2, 0, pad // 2)
        banded.addWidget(self.next, 1)
        spaced = QHBoxLayout()
        spaced.setContentsMargins(pad * 2, pad, pad * 2, 0)
        spaced.addWidget(band)
        page.addLayout(spaced)

        self.notice = _wrapped("ink-2", theme, central)
        self.notice.setContentsMargins(pad * 2, pad, pad * 2, 0)
        self.notice.hide()
        page.addWidget(self.notice)

        self.scroll = ScrollFrame(central)
        # The space beyond the cards lies under them, in a stretch: an alignment on the grid would size it for the width it
        # asks rather than the one it has, and squeeze a card whose line takes a second line at that width.
        column = QVBoxLayout(self.scroll.body)
        column.setContentsMargins(0, 0, 0, 0)
        self.cards_grid = QGridLayout()
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.cards_grid.setHorizontalSpacing(pad)
        self.cards_grid.setVerticalSpacing(pad)
        column.addLayout(self.cards_grid)
        column.addStretch(1)
        wrapper = QVBoxLayout()
        wrapper.setContentsMargins(pad * 2, pad, pad * 2, pad)
        wrapper.addWidget(self.scroll)
        page.addLayout(wrapper, 1)
        self.cards: dict[str, AccountCard] = {}
        self.ended: dict[str, EndedLine] = {}
        self._order: list[str] = []
        self._ended_order: list[str] = []
        self._columns = 0
        self._configured = 0
        self.scroll.viewport().installEventFilter(self)

        problems = QGridLayout()
        problems.setContentsMargins(pad * 2, 0, pad * 2, 0)
        problems.setColumnStretch(0, 1)
        self.problem_count = plain_label(central)
        theme.ink(self.problem_count, "ink-2")
        problems.addWidget(self.problem_count, 0, 0)
        self.problem_toggle = QPushButton("Show", central)
        self.problem_toggle.clicked.connect(self._toggle_problems)
        problems.addWidget(self.problem_toggle, 0, 1)
        self.problem_count.hide()     # until a status names a problem
        self.problem_toggle.hide()
        # A list in a scrolling frame of its own, so however long it runs it takes room from the cards and never makes
        # the window taller than the screen.
        self.problem_frame = ScrollFrame(central)
        listed = QVBoxLayout(self.problem_frame.body)
        listed.setContentsMargins(0, 0, 0, 0)
        self.problem_list = _wrapped("ink", theme, self.problem_frame.body)
        listed.addWidget(self.problem_list)
        listed.addStretch(1)
        self.problem_frame.hide()
        problems.addWidget(self.problem_frame, 1, 0, 1, 2)
        self._problems_open = False
        page.addLayout(problems)
        self.show_theme(theme_choice)

        self.said = _wrapped("ink-2", theme, central)
        self.said.setContentsMargins(pad * 2, pad // 2, pad * 2, pad // 2)
        page.addWidget(self.said)
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, activated=lambda: actions["refresh"]())

    def _switch(self, text: str, checked: bool, key: str) -> QAction:
        action = QAction(text, self, checkable=True)
        action.setChecked(checked)
        action.triggered.connect(lambda _checked=False: self.actions[key]())
        return action

    def _entry(self, menu: QMenu, text: str, key: str) -> QAction:
        action = menu.addAction(text)
        action.triggered.connect(lambda _checked=False: self.actions[key]())
        return action

    def _menu_bar(self) -> None:
        bar = self.menuBar()
        file = bar.addMenu("File")
        for text, key in (("Refresh now", "refresh"), ("Show the conversations", "conversations"),
                          ("Show the history", "history_view"), ("Open the data folder", "folder")):
            self._entry(file, text, key)
        file.addSeparator()
        self._entry(file, "Hide the window", "hide")
        self._entry(file, "Quit", "quit")

        accounts = bar.addMenu("Accounts")
        accounts.aboutToShow.connect(self._fill_switch_menus)
        accounts.addAction(self.follows)
        accounts.addAction(self.one_click)
        accounts.addSeparator()
        self._entry(accounts, "Add an account…", "add_account")
        self._entry(accounts, "Arrange accounts…", "arrange")
        accounts.addSeparator()
        for client in (APP, CLI):
            self.switch_menus[client] = accounts.addMenu(SWITCH_LABELS[client])

        bills = bar.addMenu("Bills")
        self._entry(bills, "Record a bill", "record")
        self._entry(bills, "Bills and sources", "bills")

        view = bar.addMenu("View")
        view.addAction(self.keep_on_top)
        view.addAction(self.silenced)
        view.addAction(self.keep_awake)
        view.addSeparator()
        group = QActionGroup(self)
        for choice in THEME_CHOICES:
            action = QAction(THEME_LABELS[choice], self, checkable=True)
            action.triggered.connect(lambda _checked=False, c=choice: self.choose_theme(c))
            group.addAction(action)
            view.addAction(action)
            self.theme_actions[choice] = action

        self._entry(bar.addMenu("Help"), "About WindowTally", "about")

    def choose_theme(self, choice: str) -> None:
        """The View menu's choice: the menu shows it, and the window takes it up."""
        changed = choice != self.theme_choice
        self.show_theme(choice)
        if changed:
            self.actions["theme"]()

    def show_theme(self, choice: str) -> None:
        self.theme_choice = choice
        if choice in self.theme_actions:
            self.theme_actions[choice].setChecked(True)

    def _fill_switch_menus(self) -> None:
        """The two switch menus, written afresh from what the status offers whenever the Accounts menu is about to show."""
        for client, sub in self.switch_menus.items():
            entries, empty = self.entries(client)
            fill_switch_menu(sub, entries, empty, self.switch_to)

    # --- the window itself ----------------------------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self.quitting:
            event.accept()
            return
        event.ignore()
        self.on_close()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self.on_place()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.on_place()
        self._size_problems()
        self._place_actions()

    def _place_actions(self) -> None:
        """The actions at the right end of the header's line beside the words while the room left of them holds the
        words' widest piece, so the words wrap only between their pieces; else on a row of their own under the words,
        still at the right end, the words taking the line's whole width."""
        # Measured again only when the words or the width change: the header is rewritten every second.
        key = (self.status_line.texts, self.width())
        if key == self._actions_key:
            return
        self._actions_key = key
        room = self.width() - self.pad * 4 - self.actions_bar.sizeHint().width() - self.head_line.horizontalSpacing()
        under = room < self.status_line.widest()
        if under == self._actions_under:
            return
        self._actions_under = under
        self.head_line.removeWidget(self.actions_bar)
        self.head_line.removeWidget(self.status_line)
        if under:
            self.head_line.addWidget(self.status_line, 0, 0, 1, 2, Qt.AlignmentFlag.AlignVCenter)
            self.head_line.addWidget(self.actions_bar, 1, 0, 1, 2, Qt.AlignmentFlag.AlignRight)
        else:
            self.head_line.addWidget(self.status_line, 0, 0, Qt.AlignmentFlag.AlignVCenter)
            self.head_line.addWidget(self.actions_bar, 0, 1, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._reflow()
        return False

    # --- what the window shows ------------------------------------------------------------------------------------

    def show_view(self, view: LiveView, colour_of: dict[str, str]) -> None:
        """Shows ``view``; ``colour_of`` gives each account's palette role."""
        header = view.header
        self.status_line.colour(0, "warning-text" if header and header.stale else "ink-2")
        self.status_line.set(*((header.status_line, header.in_use_line) if header else ("", "")))
        self._place_actions()
        self.totals.setText(header.totals_line if header and header.totals_line else "")
        self.totals.setVisible(bool(header and header.totals_line))
        if header and header.cli_condition:
            self.condition.setText(f"The CLI does not follow the desktop app: {header.cli_condition}")
        self.condition.setVisible(bool(header and header.cli_condition))
        self.closed_row.setVisible(bool(header and header.not_running))
        self.next.setText(header.next_line if header else "")
        blocked = bool(header and header.all_blocked)
        self.theme.ink(self.next, "critical-text" if blocked else "ink")
        self.theme.mark(self.accent, "surface", "accent-critical" if blocked else "accent")
        if view.problem:
            self.notice.setText(view.problem)
        self.notice.setVisible(bool(view.problem))
        self._cards(view, colour_of)
        self._problems(view.problems)

    def _cards(self, view: LiveView, colour_of: dict[str, str]) -> None:
        order = [card.uuid for card in view.cards]
        ended_order = [row.uuid for row in view.ended]
        for uuid in list(self.cards):
            if uuid not in order:
                self.cards.pop(uuid).deleteLater()
        for uuid in list(self.ended):
            if uuid not in ended_order:
                self.ended.pop(uuid).deleteLater()
        for card in view.cards:
            if card.uuid not in self.cards:
                self.cards[card.uuid] = AccountCard(self.theme, self.switch_to, self.scroll.body)
            self.cards[card.uuid].update_from(card, colour_of.get(card.uuid, "muted"))
        for row in view.ended:
            if row.uuid not in self.ended:
                self.ended[row.uuid] = EndedLine(self.theme, self.switch_to, self.scroll.body)
            self.ended[row.uuid].update_from(row, colour_of.get(row.uuid, "muted"))
        if (order, ended_order) != (self._order, self._ended_order):
            self._order, self._ended_order = order, ended_order
            self._columns = 0
            self._reflow()

    def _reflow(self) -> None:
        width = self.scroll.viewport().width()
        # With no card the lines of the accounts whose plan has ended take the columns, so none spans the whole width.
        columns = max(1, min(len(self._order) or len(self._ended_order) or 1, width // max(1, em(CARD_WIDTH))))
        if columns == self._columns:
            return
        self._columns = columns
        grid = self.cards_grid
        # Every column ever used is set again, so one left from a wider layout stops taking space.
        self._configured = max(self._configured, columns)
        for column in range(self._configured):
            grid.setColumnStretch(column, 1 if column < columns else 0)
        for widget in (*self.cards.values(), *self.ended.values()):
            grid.removeWidget(widget)
        for index, uuid in enumerate(self._order):
            grid.addWidget(self.cards[uuid], index // columns, index % columns)
            self.cards[uuid].show()
        # The accounts whose plan has ended follow the cards, a column wide each and abreast as the cards stand, so a
        # line's switch buttons end where the card's above them do; each keeps its own height at the top of its row, a
        # line beside one whose words wrap never stretched to match it.
        rows = -(-len(self._order) // columns)
        for index, uuid in enumerate(self._ended_order):
            grid.addWidget(self.ended[uuid], rows + index // columns, index % columns, Qt.AlignmentFlag.AlignTop)
            self.ended[uuid].show()

    def _problems(self, problems: tuple[str, ...]) -> None:
        """The source problems' line and its Show button, standing only while there are problems."""
        count = len(problems)
        self.problem_count.setText(f"{count} source problem{'' if count == 1 else 's'}" if count else "")
        self.theme.ink(self.problem_count, "warning-text")
        self.problem_list.setText("\n".join(f"• {p}" for p in problems))
        self._size_problems()
        self.problem_count.setVisible(bool(count))
        self.problem_toggle.setVisible(bool(count))
        if not count and self._problems_open:
            self._toggle_problems()

    def _toggle_problems(self) -> None:
        self._problems_open = not self._problems_open
        self._size_problems()
        self.problem_frame.setVisible(self._problems_open)
        self.problem_toggle.setText("Hide" if self._problems_open else "Show")

    def _size_problems(self) -> None:
        """The list's frame as tall as its words at the window's width, up to ``PROBLEM_LINES`` lines."""
        if self._problems_open:
            height = self.problem_list.heightForWidth(max(1, self.width() - self.pad * 4))
            self.problem_frame.setFixedHeight(min(em(PROBLEM_LINES), max(1, height)))

    def show_progress(self, progress: Progress | None) -> None:
        """What a switch is doing, with its Cancel button enabled while it can still be called off; nothing while no
        switch runs."""
        if progress is None:
            self.progress_row.hide()
            return
        self.progress.setText(progress.text)
        self.cancel.setEnabled(progress.cancellable)
        self.progress_row.show()

    def say(self, text: str, ok: bool = True) -> None:
        """The status line: what the last action did."""
        self.said.setText(text)
        self.theme.ink(self.said, "ink-2" if ok else "critical-text")
