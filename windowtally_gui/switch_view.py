"""The window's menus and dialogs of switching accounts.

``fill_switch_menu`` writes the entries of a "Switch the app to" or "Switch the CLI to" menu from ``switch_model``'s
offers each time the menu is about to show, so a menu never shows accounts that were there when the window opened. The
dialogs are small modal windows sized to their content, with the question and the choices on it, which answer by the
key of the button pressed; closing one, or Escape, answers as Cancel does. A window opened from the tray, while the main
window is hidden, has no window to be modal to: it comes to the front of the screen on its own.

``CarryDialog`` is the switch of the desktop app where the account it leaves has sessions to carry (``carry_model``):
it names the account switched to and says that a session left unticked stays with the account left; above the list, a
search by title, as the Conversations window's (``conversations_model.search_words``), and how many sessions stand in
the list of how many and how many are ticked; the list, the sessions with a tick box each, its title, how a limit
stopped it, that it is working or that its background work is unfinished, its last activity, and what it ran with, its
effort and permission mode; under the list, that permission mode and effort are set again in each session opened, as
the list shows them, and, where a session's background work is unfinished, that the work is to be run again; and it
ends in Wait and switch, while a session is working, Switch and Cancel. A session the search hides keeps its tick and
is carried with the rest, which the count of the ticked keeps in sight. Space ticks the session chosen, as a click on
its box does; Ctrl+F goes to the search, and Return in it goes to the list, its first session shown chosen, never
pressing the default button.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QModelIndex, QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLayout, QLineEdit, QMenu, QPushButton, QVBoxLayout, QWidget

from .carry_model import CarryRow
from .common_view import RowList, dialog_owner, em, fixed_words, plain_label, size_to_content
from .conversations_model import count_words, search_words, title_has
from .formatting import plural
from .switch_model import SwitchEntry

WIDTH = 30   # lines of the default font a dialog's words run to before they wrap
# The carry dialog's columns, each its key, heading and width in digits of the default font, and the most rows it shows
# before it scrolls.
CARRY_COLUMNS = (("title", "Session", 40), ("state", "State", 27), ("last", "Last activity", 13),
                 ("ran", "Ran with", 20))
CARRY_ROWS = 8


def fill_switch_menu(menu: QMenu, entries: tuple[SwitchEntry, ...], empty: str,
                     choose: Callable[[str, str], None]) -> None:
    """Replaces the entries of ``menu`` with one for each account in ``entries``; ``empty`` says why there is none."""
    menu.clear()
    if not entries:
        menu.addAction(empty).setEnabled(False)
        return
    for entry in entries:
        # A menu reads & as a mark of its keyboard letter, and a name is the user's own, written as it stands.
        menu.addAction(entry.label.replace("&", "&&")).triggered.connect(
            lambda _checked=False, e=entry: choose(e.client, e.uuid))


class AskDialog(QDialog):
    """A question in a window of its own; ``answer`` is the key of the button pressed, ``cancel`` until one is."""

    def __init__(self, parent: QWidget | None, title: str, message: str, buttons: tuple[tuple[str, str], ...], *,
                 default: str, cancel: str):
        super().__init__(parent)
        self.answer = cancel
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        pad = em(0.5)
        body = QVBoxLayout(self)
        body.setContentsMargins(pad * 2, pad * 2, pad * 2, pad * 2)
        body.setSpacing(pad * 2)
        words = plain_label()
        words.setText(message)
        body.addWidget(fixed_words(words, em(WIDTH)))
        row = QHBoxLayout()
        row.setSpacing(pad)
        row.addStretch(1)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in buttons:
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, k=key: self._choose(k))
            row.addWidget(button)
            self.buttons[key] = button
        body.addLayout(row)
        self.buttons[default].setDefault(True)
        self.buttons[default].setFocus()

    def _choose(self, key: str) -> None:
        self.answer = key
        self.accept()


def ask(parent: QWidget | None, title: str, message: str, buttons: tuple[tuple[str, str], ...], *, default: str,
        cancel: str) -> str:
    """Asks ``message`` in a window of its own and returns the key of the button pressed (``buttons`` are key and text,
    left to right); ``cancel`` is the answer of Escape and of closing the window."""
    shown = dialog_owner(parent)
    window = AskDialog(shown, title, message, buttons, default=default, cancel=cancel)
    size_to_content(window, shown)
    window.setFixedSize(window.size())
    window.raise_()
    window.activateWindow()
    window.exec()
    answer = window.answer
    window.deleteLater()
    return answer


def sessions_message(sessions: int, deed: str) -> str:
    return (f"{plural(sessions, 'Code session')} {'is' if sessions == 1 else 'are'} working. {deed[0].upper()}{deed[1:]} "
            f"closes the desktop app and ends {'it' if sessions == 1 else 'them'}, without the app's own question.")


def ask_sessions(parent: QWidget | None, sessions: int, deed: str, verb: str) -> str:
    """Code sessions are at work and ``deed`` would close the desktop app, ending them: ``now``, ``wait`` or ``cancel``.
    ``verb`` is what the first two buttons call it ("Switch", "Store")."""
    return ask(parent, "Code sessions are working", sessions_message(sessions, deed),
               (("now", f"{verb} anyway"), ("wait", f"Wait and {verb.lower()}"), ("cancel", "Cancel")),
               default="wait", cancel="cancel")


def carry_lead(left: str, to: str) -> str:
    return (f"The desktop app switches from {left} to {to}. Each session of {left} ticked below opens on {to} once the "
            f"switch is done. One left unticked stays with {left}; the Conversations window opens it later.")


CARRY_NOTE = ("A session opened there goes on with its conversation, but not with its permission mode and effort: set "
              "them again in each, as Ran with shows.")
BACKGROUND_NOTE = "Background work left unfinished does not go on there: have it run again."


def carry_count(shown: int, total: int, ticked: int) -> str:
    """What the dialog says beside its search: how many sessions stand in the list, of how many, and how many are
    ticked, those the search hides among them."""
    return f"{count_words(shown, total)} · {ticked} ticked"


def carry_note(rows: tuple[CarryRow, ...]) -> str:
    """What the dialog says under the list: what a session opened there leaves behind, and, where a session offered
    has background work unfinished, whatever its state says first, that the work is to be run again."""
    return CARRY_NOTE + (" " + BACKGROUND_NOTE if any(row.background for row in rows) else "")


class CarryDialog(QDialog):
    """The switch of the desktop app from ``left`` to ``to``, with ``rows`` to carry; ``at_work`` sessions are working.
    ``answer`` is the key of the button pressed — ``wait``, ``now`` or ``cancel`` — ``cancel`` until one is, and
    ``chosen`` the sessions ticked when it was, in the order they stand."""

    def __init__(self, parent: QWidget | None, left: str, to: str, rows: tuple[CarryRow, ...], at_work: int):
        super().__init__(parent)
        self.answer, self.chosen = "cancel", ()
        self.rows = rows
        self.setWindowTitle(f"Switch the desktop app to {to}")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        pad = em(0.5)
        body = QVBoxLayout(self)
        body.setContentsMargins(pad * 2, pad * 2, pad * 2, pad * 2)
        body.setSpacing(pad * 2)
        body.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        self.lead = self._words(carry_lead(left, to))
        body.addWidget(self.lead)
        self.working = None
        if at_work > 0:
            self.working = self._words(sessions_message(at_work, f"switching the desktop app to {to}"))
            body.addWidget(self.working)
        head = QHBoxLayout()
        head.setSpacing(pad)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search titles")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self._filter())
        self.search.installEventFilter(self)
        head.addWidget(self.search, 1)
        self.count = plain_label(self)
        head.addWidget(self.count)
        body.addLayout(head)
        self.list = RowList(CARRY_COLUMNS, max(2, min(CARRY_ROWS, len(rows))), "title", self)
        self.list.fill((row.session_id, (row.title, row.state, row.last, row.ran_with)) for row in rows)
        ran = self.list.columns.index("ran")
        for row in rows:
            item = self.list.item_of(row.session_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if row.ticked else Qt.CheckState.Unchecked)
            item.setToolTip(ran, row.ran_with)
        if rows:
            self.list.setCurrentItem(self.list.item_of(rows[0].session_id))
        self.list.itemChanged.connect(lambda _item, _column: self._say_count())
        # The dialog takes the height its layout gives for its width, which falls short of what the layout asks for
        # by a row or more, and the list alone would give it up: it keeps every row it asks for.
        self.list.setMinimumHeight(self.list.sizeHint().height())
        body.addWidget(self.list)
        self.note = self._words(carry_note(rows))
        body.addWidget(self.note)
        buttons = QHBoxLayout()
        buttons.setSpacing(pad)
        buttons.addStretch(1)
        self.buttons: dict[str, QPushButton] = {}
        offered = ((("wait", "Wait and switch"),) if at_work > 0 else ()) + (("now", "Switch"), ("cancel", "Cancel"))
        for key, text in offered:
            button = QPushButton(text, self)
            button.clicked.connect(lambda _checked=False, k=key: self._choose(k))
            buttons.addWidget(button)
            self.buttons[key] = button
        body.addLayout(buttons)
        default = self.buttons["wait" if at_work > 0 else "now"]
        default.setDefault(True)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)
        self._say_count()
        self.list.setFocus()

    def _words(self, text: str):
        label = plain_label(self)
        label.setText(text)
        return fixed_words(label, em(WIDTH))

    def ticked(self) -> tuple[str, ...]:
        """The sessions ticked now, in the order they stand, those the search hides among them."""
        return tuple(row.session_id for row in self.rows
                     if self.list.item_of(row.session_id).checkState(0) == Qt.CheckState.Checked)

    def _items(self) -> list:
        return [self.list.topLevelItem(index) for index in range(self.list.topLevelItemCount())]

    def shown_keys(self) -> list[str]:
        """The sessions standing in the list, in its order."""
        return [item.data(0, Qt.ItemDataRole.UserRole) for item in self._items() if not item.isHidden()]

    def _filter(self) -> None:
        """Shows the sessions whose title holds every word of the search."""
        words = search_words(self.search.text())
        titles = {row.session_id: row.title for row in self.rows}
        for item in self._items():
            item.setHidden(not title_has(titles[item.data(0, Qt.ItemDataRole.UserRole)], words))
        self._choose_first_shown()
        self._say_count()

    def _choose_first_shown(self) -> None:
        """The first session shown chosen where the one chosen is hidden or none is; none chosen where none is shown,
        so Space ticks no session out of sight."""
        current, shown = self.list.currentItem(), self.shown_keys()
        if not shown:
            self.list.setCurrentIndex(QModelIndex())
        elif current is None or current.isHidden():
            self.list.setCurrentItem(self.list.item_of(shown[0]))

    def _say_count(self) -> None:
        items = self._items()
        shown = sum(not item.isHidden() for item in items)
        ticked = sum(item.checkState(0) == Qt.CheckState.Checked for item in items)
        self.count.setText(carry_count(shown, len(items), ticked))

    def _to_list(self) -> None:
        """Return in the search: on to the list, its first session shown chosen where none is, nothing pressed."""
        self._choose_first_shown()
        self.list.setFocus()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Return in the search goes on to the list: a dialog would otherwise take it for its default button's."""
        if (watched is self.search and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self._to_list()
            return True
        return super().eventFilter(watched, event)

    def _choose(self, key: str) -> None:
        self.answer = key
        self.chosen = self.ticked() if key != "cancel" else ()
        self.accept()


def ask_carry(parent: QWidget | None, left: str, to: str, rows: tuple[CarryRow, ...],
              at_work: int) -> tuple[str, tuple[str, ...]]:
    """Asks which sessions of ``left`` to carry to ``to`` and whether to switch now or once no session is working:
    the key of the button pressed — ``wait``, ``now`` or ``cancel`` — and the sessions ticked, none on ``cancel``."""
    shown = dialog_owner(parent)
    window = CarryDialog(shown, left, to, rows, at_work)
    size_to_content(window, shown)
    window.raise_()
    window.activateWindow()
    window.exec()
    answer = window.answer, window.chosen
    window.deleteLater()
    return answer


def ask_cli_idle(parent: QWidget | None, label: str) -> bool:
    """A CLI is running, so the CLI cannot be switched to ``label`` now: whether to wait until none is."""
    message = f"A CLI is running and holds the only current copy of its sign-in: it cannot switch to {label} until idle."
    return ask(parent, "A CLI is running", message,
               (("wait", "Switch when idle"), ("cancel", "Cancel")), default="wait", cancel="cancel") == "wait"


ADD_STEPS = ("WindowTally closes the desktop app, stores its current login and opens the app at its sign-in page "
             "without signing out, so that login keeps working.\n"
             "Sign in there to the new account; its login is stored when you next switch away from it.\n"
             "The CLI signs in on its own: sign the new account in there once, in a terminal.")


def ask_add_account(parent: QWidget | None, lead: str = "") -> str:
    """How an account is added, and the two things WindowTally can do for it: ``open`` the desktop app's sign-in page,
    ``terminal`` to sign the CLI in, or ``close``. ``lead`` says first why the window is shown, where it is shown because
    a switch could not be made."""
    return ask(parent, "Add an account", (lead + "\n\n" if lead else "") + ADD_STEPS,
               (("open", "Open the sign-in page"), ("terminal", "Sign the CLI in…"), ("close", "Close")),
               default="close", cancel="close")
