"""The Qt *Arrange accounts…* window.

A small modal window, opened from the Accounts menu and the tray's: the accounts in a list, in the user's order, each by
the name it is shown by, its e-mail and whether it is shown; beside the list Up and Down, which move the selected account
one place, and By name, which puts every account back in the default order; under it the selected account's name, the
user's own while the field holds one and the e-mail's local part once it is cleared, and a check box that shows the
account in WindowTally's lists or hides it from them. What the order and hiding do is no text at rest: it is the hint of
Up and Down and of the check box, shown on the pointer and on the focus. A name WindowTally would refuse is said under the
field as it is typed, and while it stands OK waits and the selection stays on the account being named. OK writes the
order, the names and the hidden accounts together, onto the settings as they stand, and closes; a write WindowTally
refuses is said in the window, which stays open with what was arranged — among them a change the settings took meanwhile
in something arranged here too, which OK again saves this window's over (``arrange_model``). Cancel, Escape or closing the
window leaves everything as it was. Opened from the tray while the main window is hidden, it has no window to be modal to
and comes to the front of the screen on its own, as the switch dialogs do.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLayout, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from windowtally.settings import NAME_LIMIT

from .actions_model import Outcome
from .arrange_model import Arrangement
from .common_view import Hint, RowList, dialog_owner, digits, em, plain_label, size_to_content
from .theme_view import Theme

WIDTH = 30                  # lines of the default font the window's words run to before they wrap
# Each column's width in characters of the font.
COLUMNS = (("name", "Name", NAME_LIMIT), ("email", "E-mail", 26), ("listed", "In lists", 8))
LISTED_WORDS = {False: "shown", True: "hidden"}   # the In lists column, by whether the account is hidden
MOST_ROWS = 10              # rows the list shows before it scrolls
# What the order and hiding do, behind Up and Down and the check box: the window carries no explanation at rest.
ORDER_HINT = "Every list shows the accounts in this order, after the accounts in use, and by these names"
HIDDEN_HINT = "A hidden account is left out of every list, and never recommended, while no client uses it"


class ArrangeWindow(QDialog):
    def __init__(self, parent: QWidget | None, theme: Theme, arrangement: Arrangement,
                 save: Callable[[Arrangement], Outcome]):
        """``save`` writes the arrangement and answers what it did. ``outcome`` is its answer once OK wrote, None until."""
        super().__init__(parent)
        self.theme, self.arrangement, self.save = theme, arrangement, save
        self.outcome: Outcome | None = None
        self.selected: str | None = None
        self.blocked: str | None = None     # the account whose name, as typed, cannot be used
        self.setWindowTitle("Arrange accounts")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        pad = em(0.5)
        grid = QGridLayout(self)
        grid.setContentsMargins(pad * 2, pad * 2, pad * 2, pad * 2)
        grid.setHorizontalSpacing(pad)
        grid.setVerticalSpacing(0)
        # The window keeps to its content, so a refusal's words get their lines.
        grid.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        self.tree = RowList(COLUMNS, max(3, min(MOST_ROWS, len(arrangement.rows))), "email", self, least=6)
        self._show_rows(None)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        grid.addWidget(self.tree, 0, 0)

        moves = QVBoxLayout()
        moves.setSpacing(pad // 2)
        self.up = QPushButton("Up", self)
        self.up.clicked.connect(lambda: self._move(-1))
        moves.addWidget(self.up)
        self.down = QPushButton("Down", self)
        self.down.clicked.connect(lambda: self._move(1))
        moves.addWidget(self.down)
        for button in (self.up, self.down):
            Hint(button, ORDER_HINT, focus=True)
        moves.addSpacing(pad)
        self.by_name = QPushButton("By name", self)
        self.by_name.clicked.connect(self._by_name)
        moves.addWidget(self.by_name)
        Hint(self.by_name, "Default order, by name")
        moves.addStretch(1)
        grid.addLayout(moves, 0, 1)

        naming = QGridLayout()
        naming.setContentsMargins(0, pad * 2, 0, 0)
        naming.setHorizontalSpacing(pad)
        naming.setVerticalSpacing(pad)
        naming.setColumnStretch(2, 1)
        caption = plain_label(self)
        caption.setText("Name")
        theme.ink(caption, "ink-2")
        naming.addWidget(caption, 0, 0)
        self.name = QLineEdit(self)
        self.name.setFixedWidth(digits(NAME_LIMIT + 2))
        naming.addWidget(self.name, 0, 1)
        self.default = plain_label(self)
        theme.ink(self.default, "ink-2")
        naming.addWidget(self.default, 0, 2)
        self.listed = QCheckBox("Shown in lists", self)
        self.listed.setChecked(True)
        self.listed.clicked.connect(lambda: self._listed_toggled())
        naming.addWidget(self.listed, 1, 0, 1, 3)
        Hint(self.listed, HIDDEN_HINT, focus=True)
        grid.addLayout(naming, 1, 0, 1, 2)

        self.problem = plain_label(self)
        self.problem.setWordWrap(True)
        self.problem.setMaximumWidth(em(WIDTH))
        self.problem.setContentsMargins(0, pad // 2, 0, 0)
        theme.ink(self.problem, "critical-text")
        grid.addWidget(self.problem, 2, 0, 1, 2)
        self.name.textChanged.connect(lambda _text: self._name_typed())

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, pad * 2, 0, 0)
        buttons.setSpacing(pad)
        buttons.addStretch(1)
        self.ok = QPushButton("OK", self)
        self.ok.setDefault(True)
        self.ok.clicked.connect(self._ok)
        buttons.addWidget(self.ok)
        self.cancel = QPushButton("Cancel", self)
        self.cancel.clicked.connect(self.reject)
        buttons.addWidget(self.cancel)
        grid.addLayout(buttons, 3, 0, 1, 2)

        if arrangement.rows:
            self.tree.setCurrentItem(self.tree.item_of(arrangement.rows[0].uuid))
        self._selection_changed()
        self._buttons()
        self.tree.setFocus()

    def _cells(self, uuid: str) -> tuple[str, str, str]:
        row = self.arrangement.row(uuid)
        return row.shown, row.email or "", LISTED_WORDS[row.hidden]

    def _show_rows(self, chosen: str | None) -> None:
        self.tree.fill(((row.uuid, self._cells(row.uuid)) for row in self.arrangement.rows), chosen)

    # --- the selection and the moves ------------------------------------------------------------------------------

    def _selection_changed(self) -> None:
        uuid = self.tree.key_chosen()
        if self.blocked is not None and uuid != self.blocked:
            # The name typed for the account being named cannot be used yet: the selection stays on it.
            self.tree.setCurrentItem(self.tree.item_of(self.blocked))
            QApplication.beep()
            return
        if uuid == self.selected:
            return
        self.selected = uuid
        if uuid is None:
            self.name.setText("")
            self.name.setEnabled(False)
            self.default.setText("")
            self.listed.setChecked(True)
            self.listed.setEnabled(False)
        else:
            row = self.arrangement.row(uuid)
            self.name.setEnabled(True)
            self.name.setText(row.name or "")
            self.default.setText(f"default: {row.default}")
            self.listed.setChecked(not row.hidden)
            self.listed.setEnabled(True)
        self._buttons()

    def _listed_toggled(self) -> None:
        uuid = self.selected
        if uuid is None:
            return
        self.arrangement.set_shown(uuid, self.listed.isChecked())
        self.tree.set_cell(uuid, "listed", LISTED_WORDS[self.arrangement.row(uuid).hidden])

    def _reshown(self) -> None:
        """The rows in the arrangement's order, the selected account kept selected and in view."""
        self._show_rows(self.selected)
        if self.selected is not None:
            self.tree.scrollToItem(self.tree.item_of(self.selected))
        self._buttons()

    def _move(self, step: int) -> None:
        if self.selected is None or not self.arrangement.move(self.selected, step):
            return
        self._reshown()

    def _by_name(self) -> None:
        self.arrangement.by_name()
        self._reshown()

    def _buttons(self) -> None:
        uuid = self.selected
        wanted = ((self.up, bool(uuid) and self.arrangement.can_move(uuid, -1)),
                  (self.down, bool(uuid) and self.arrangement.can_move(uuid, 1)),
                  (self.by_name, not self.arrangement.is_by_name()))
        for button, enabled in wanted:
            if button.hasFocus() and not enabled:
                self.tree.setFocus()    # a disabled button holds no focus, and Return from the list is OK
            button.setEnabled(enabled)
        self.ok.setEnabled(self.blocked is None)

    # --- the name -------------------------------------------------------------------------------------------------

    def _name_typed(self) -> None:
        uuid = self.selected
        if uuid is None:
            return
        problem = self.arrangement.rename(uuid, self.name.text())
        self.blocked = uuid if problem else None
        self.problem.setText(problem or "")
        if not problem:
            self.tree.set_cell(uuid, "name", self.arrangement.row(uuid).shown)
        self._buttons()

    # --- the answer -----------------------------------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        """Return from a button presses it, a dialog's buttons taking it themselves; from anywhere else it is OK."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._ok()
        else:
            super().keyPressEvent(event)

    def _ok(self) -> None:
        if self.blocked is not None:
            return
        if not self.arrangement.changed():
            self.reject()
            return
        outcome = self.save(self.arrangement)
        if not outcome.ok:
            self.problem.setText(outcome.message)
            return
        self.outcome = outcome
        self.accept()


def ask_arrangement(parent: QWidget | None, theme: Theme, arrangement: Arrangement,
                    save: Callable[[Arrangement], Outcome]) -> Outcome | None:
    """Lets the user arrange and name the accounts; what ``save`` answered once OK wrote them, or None where nothing was
    written: Cancel, or OK with nothing changed."""
    shown = dialog_owner(parent)
    window = ArrangeWindow(shown, theme, arrangement, save)
    size_to_content(window, shown)
    window.raise_()
    window.activateWindow()
    window.exec()
    outcome = window.outcome
    window.deleteLater()
    return outcome
