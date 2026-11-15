"""The Conversations window: every account's Code sessions in one list, from which a session opens on the account in use.

At its head, a search by title — every word typed found in a title, case aside — the account filter and the project
filter, then how many sessions stand in the list. Below, the list: Title, Project, Account, Last activity, Used and Ran
with, the effort and permission mode the session last ran with, the latest activity first, a project's full folder and
a title or what it ran with too long for its column in the cell's tooltip. The list takes the height the window leaves
it in whole rows (``WholeRows``), so it ends on a whole row. Under the list, the line naming the account
the session chosen opens on, or every session where none is, with why one cannot be opened where that is so; then the
last button's word — after Open session, what the session ran with, for the user to set again in the app — and the
buttons Copy resume command and Open session. A double
click or Return on a session opens it; Return in the search goes to the list, its first session chosen, so a search
never opens one by itself; Ctrl+F goes to the search, F5 reads the ledger again, Escape or closing hides the window.

The sessions are read off the window's thread (``conversations_model.compute``) when the window opens, on F5 and while
it shows after every status the window reads, the service writing one at each pass; the list shown stays, its search,
filters and the session chosen kept, until the next read replaces it. The line follows the status every second, so it
says at once that the desktop app was switched or stopped, and the ages under Last activity are written again every
``AGES_S`` seconds between reads. The sessions at work are read off Claude Code's session registry at most once a second.
"""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from windowtally.paths import MachinePaths

from . import conversations_model
from .background import Background
from .carry_model import resume_link
from .common_view import Hint, RowList, WholeRows, em, plain_label
from .conversations_model import Listing, Opening, Refresh, Row, count_words, handed_words, last_text, matches, \
    opening, resume_command, search_words
from .status_model import Status
from .theme_view import Theme

SIZE = (80, 36)        # lines of the default font, wide and tall, within 90 % of the monitor
LEAST_SIZE = (40, 18)  # lines of the default font the window can be made down to
ROWS = 16              # the rows the list asks to show
# The list's columns: each its key, heading and width in digits of the default font; the title takes the rest.
COLUMNS = (("title", "Title", 44), ("project", "Project", 18), ("account", "Account", 12),
           ("last", "Last activity", 16), ("used", "Used", 10), ("ran", "Ran with", 20))
LOOKING = "Reading the sessions…"
AGES_S = 30.0          # how often the ages under Last activity are written again between two reads
WORKING_S = 1.0        # how long one reading of the sessions at work stands for the line


class ConversationsWindow(QWidget):
    def __init__(self, theme: Theme, paths: MachinePaths, work: Background, status: Callable[[], Status | None],
                 switching: Callable[[], bool], working: Callable[[], frozenset[str]],
                 open_link: Callable[[str], object], *, clock: Callable[[], float] | None = None):
        """``work`` is the lane the sessions are read on, polled by the main window's clock; ``status()`` the status
        shown, ``switching()`` whether a switch of the desktop app is under way, ``working()`` the sessions at work by
        their ids. ``open_link`` is the shell's opener of links, a stand-in in a test."""
        super().__init__()
        self.theme, self.paths, self.work = theme, paths, work
        self.status, self.switching, self.working, self.open_link = status, switching, working, open_link
        self.clock = clock or time.time
        self.refresh = Refresh()
        self.listing: Listing | None = None
        self._rows: dict[str, Row] = {}
        self._sized = False
        self._failure_said = False   # the word under the line is a read's failure, cleared by the next read that works
        self._aged_at = 0.0          # when the ages under Last activity were last written
        self._working: tuple[float, frozenset[str]] | None = None   # the last reading of the sessions at work, and when
        self.setWindowTitle("WindowTally — conversations")
        theme.ground(self)
        pad = em(0.5)

        page = QVBoxLayout(self)
        page.setContentsMargins(pad * 2, pad, pad * 2, pad)
        page.setSpacing(pad)
        head = QHBoxLayout()
        head.setSpacing(pad)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search titles")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self._filter())
        self.search.returnPressed.connect(self._to_list)
        head.addWidget(self.search, 1)
        self.accounts = QComboBox(self)
        self.accounts.activated.connect(lambda _index: self._filter())
        head.addWidget(self.accounts)
        self.projects = QComboBox(self)
        self.projects.activated.connect(lambda _index: self._filter())
        head.addWidget(self.projects)
        self.count = plain_label(self)
        theme.ink(self.count, "ink-2")
        head.addWidget(self.count)
        page.addLayout(head)

        self.list = RowList(COLUMNS, ROWS, "title", self)
        self.list.itemSelectionChanged.connect(self.show_line)
        self.list.itemActivated.connect(lambda _item, _column: self.open_session())
        page.addWidget(WholeRows(self.list, self), 1)

        self.line = plain_label(self)
        self.line.setWordWrap(True)
        theme.ink(self.line, "ink")
        page.addWidget(self.line)
        self.said = plain_label(self)
        self.said.setWordWrap(True)
        theme.ink(self.said, "ink-2")
        self.said.hide()
        page.addWidget(self.said)

        buttons = QHBoxLayout()
        buttons.setSpacing(pad)
        buttons.addStretch(1)
        self.copy_button = QPushButton("Copy resume command", self)
        self.copy_button.clicked.connect(lambda _checked=False: self.copy_command())
        Hint(self.copy_button, "The PowerShell command that goes on with the session in a terminal, in its own folder")
        buttons.addWidget(self.copy_button)
        self.open_button = QPushButton("Open session", self)
        self.open_button.clicked.connect(lambda _checked=False: self.open_session())
        Hint(self.open_button, "Open it in the desktop app, on the account the app is signed in to")
        buttons.addWidget(self.open_button)
        page.addLayout(buttons)

        QShortcut(QKeySequence(Qt.Key.Key_F5), self, activated=self.recompute)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)
        self._choices()
        self._say_count()
        self.show_line()

    # --- showing --------------------------------------------------------------------------------------------------

    def open(self) -> None:
        if not self._sized:
            self._sized = True
            self._size()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()
        self.recompute()

    def _size(self) -> None:
        """Wide enough for every column of the list where the screen allows, the title's at its width or more."""
        area = QGuiApplication.primaryScreen().availableGeometry()
        width = min(max(em(SIZE[0]), self.sizeHint().width()), int(area.width() * 0.9))
        height = min(em(SIZE[1]), int(area.height() * 0.9))
        self.resize(width, height)
        self.move(area.left() + (area.width() - width) // 2, area.top() + (area.height() - height) // 3)
        self.setMinimumSize(min(width, em(LEAST_SIZE[0])), min(height, em(LEAST_SIZE[1])))

    # --- reading ----------------------------------------------------------------------------------------------------

    def recompute(self) -> None:
        """Reads the sessions again, now or once the read running ends."""
        if self.refresh.want():
            self._start()
        self._say_count()

    def status_changed(self) -> None:
        """A status was read: the passes that write one also write the ledger, so the list is read again while shown."""
        if self.isVisible():
            self.recompute()

    def _start(self) -> None:
        started = self.work.start("conversations", lambda: conversations_model.compute(self.paths), self._finished,
                                  lambda error: self._finished(failure=str(error) or type(error).__name__))
        if not started:   # cannot happen while this window owns the lane; said rather than lost
            self.refresh.done("another read is running")

    def _finished(self, listing: Listing | None = None, failure: str | None = None) -> None:
        if failure is None and listing is not None:
            self.listing = listing
            self._fill()
            if self._failure_said:
                self._failure_said = False
                self.said.hide()
        else:
            if failure.startswith("no ledger at"):
                failure = "there is no ledger yet; the service writes it at its first pass"
            self._tell(f"The sessions could not be read: {failure}.", failed=True)
            self._failure_said = True
        if self.refresh.done(failure):
            self._start()
        self._say_count()

    # --- the list ---------------------------------------------------------------------------------------------------

    def _choices(self) -> None:
        """The two filters' entries from the listing, the one chosen kept while the listing still offers it."""
        listing = self.listing
        for box, every, offered in ((self.accounts, "All accounts", listing.accounts if listing else ()),
                                    (self.projects, "All projects", listing.projects if listing else ())):
            chosen = box.currentData()
            box.blockSignals(True)
            box.clear()
            box.addItem(every, None)
            for key, name in offered:
                box.addItem(name, key)
            index = box.findData(chosen) if chosen is not None else 0
            box.setCurrentIndex(index if index >= 0 else 0)
            box.blockSignals(False)

    def _fill(self) -> None:
        """The listing's rows, the session chosen kept while it is still among them."""
        chosen = self.list.key_chosen()
        listing = self.listing
        now = self._aged_at = self.clock()
        self._rows = {row.session_id: row for row in listing.rows}
        self._choices()
        self.list.fill(((row.session_id, (row.title, row.project, row.account, last_text(row.last_activity, now),
                                          row.used, row.ran_with)) for row in listing.rows), chosen)
        self._tooltips()
        self._filter()

    def _ages(self) -> None:
        """The ages under Last activity written again for now."""
        now = self._aged_at = self.clock()
        column = self.list.columns.index("last")
        for index in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(index)
            item.setText(column, last_text(self._rows[item.data(0, Qt.ItemDataRole.UserRole)].last_activity, now))

    def _tooltips(self) -> None:
        columns = self.list.columns
        for index in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(index)
            row = self._rows[item.data(0, Qt.ItemDataRole.UserRole)]
            item.setToolTip(columns.index("title"), row.title)
            item.setToolTip(columns.index("project"), row.folder or row.project_folder)
            item.setToolTip(columns.index("ran"), row.ran_with)
            item.setTextAlignment(columns.index("used"), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _filter(self) -> None:
        """Shows the rows the search and the filters keep, and keeps a session chosen among them."""
        words = search_words(self.search.text())
        account, project = self.accounts.currentData(), self.projects.currentData()
        chosen = self.list.key_chosen()
        first = None
        for index in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(index)
            row = self._rows[item.data(0, Qt.ItemDataRole.UserRole)]
            hidden = not matches(row, words, account, project)
            item.setHidden(hidden)
            if not hidden and first is None:
                first = item
            if hidden and row.session_id == chosen:
                chosen = None
        if chosen is None:
            self.list.clearSelection()
            if first is not None:
                self.list.setCurrentItem(first)
        self._say_count()
        self.show_line()

    def shown_keys(self) -> list[str]:
        """The sessions standing in the list, in its order."""
        return [self.list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                for i in range(self.list.topLevelItemCount()) if not self.list.topLevelItem(i).isHidden()]

    def _say_count(self) -> None:
        if self.listing is not None:
            self.count.setText(count_words(len(self.shown_keys()), len(self.listing.rows)))
        else:
            self.count.setText(LOOKING if self.refresh.running else "Not read")

    def chosen(self) -> Row | None:
        key = self.list.key_chosen()
        return self._rows.get(key) if key is not None else None

    def _to_list(self) -> None:
        """Return in the search: on to the list, its first session chosen where none is, nothing opened."""
        if self.list.key_chosen() is None:
            shown = self.shown_keys()
            if shown:
                self.list.setCurrentItem(self.list.item_of(shown[0]))
        self.list.setFocus()

    # --- the line and the buttons -----------------------------------------------------------------------------------

    def tick(self) -> None:
        """The window's second, while it shows: the line from the status now, and the ages once ``AGES_S`` passed."""
        if self.listing is not None and self.clock() - self._aged_at >= AGES_S:
            self._ages()
        self.show_line()

    def _working_now(self) -> frozenset[str]:
        now = self.clock()
        if self._working is None or not 0 <= now - self._working[0] < WORKING_S:
            self._working = (now, self.working())
        return self._working[1]

    def current_opening(self) -> Opening:
        return opening(self.chosen(), self.status(), switching=self.switching(), working=self._working_now())

    def show_line(self) -> None:
        """The line under the list and what the two buttons can do, from the status and the session chosen now."""
        shown = self.current_opening()
        if self.line.text() != shown.words:
            self.line.setText(shown.words)
        self.open_button.setEnabled(shown.can_open)
        self.copy_button.setEnabled(shown.can_copy)

    def open_session(self) -> None:
        """Hands the session chosen to the desktop app through its resume link; said under the line either way."""
        row, shown = self.chosen(), self.current_opening()
        if row is None or not shown.can_open:
            self.show_line()
            return
        try:
            self.open_link(resume_link(row.session_id))
        except OSError as exc:
            self._tell(f"Not opened in the desktop app: {row.title} ({exc}).", failed=True)
            return
        self._tell(handed_words(row))

    def copy_command(self) -> None:
        row, shown = self.chosen(), self.current_opening()
        if row is None or not shown.can_copy:
            self.show_line()
            return
        QGuiApplication.clipboard().setText(resume_command(row))
        self._tell(f"Copied the resume command of {row.title}: paste it into PowerShell.")

    def _tell(self, text: str, failed: bool = False) -> None:
        self._failure_said = False
        self.said.setText(text)
        self.theme.ink(self.said, "critical-text" if failed else "ink-2")
        self.said.show()
