"""The Qt Bills and sources window.

On the left the bills — newest first, every source's — with Change and Remove for a bill of WindowTally's own file, then
the sources with Add and Stop reading, then the renewal reminder. On the right the form a bill is recorded through, or
changed through once Change put a bill in it. Fields a kind does not take are disabled, not hidden, so the form keeps its
shape; what a field takes is its hint (``FIELD_HINTS``), shown while the pointer rests on its name or the field and while
the field has the focus. What a change did is written under the part it was made in — a refusal in WindowTally's own
words, the fields keeping what was typed — and a change that took reloads the lists and asks the window to read every
source again, so the figures follow at once; the window's status line keeps the change's words ahead of the pass's. A
step of the reminder's days is written once the steps stop, not at each.

A drop-down changes the form when an entry is picked from its list, and the wheel turning over it picks as the list does,
save over the account's: a pick of an account fills the form anew for it, so a notch of the wheel there would lose what
was typed, and only a pick from its list counts, the turn going on to what is around the box. Return in one does
nothing, as in every other field, Down opens its list and Up does nothing. Closing the window hides it; it reads every
source's bills afresh each time it is shown.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout, QWidget)

from windowtally.bills import PLANS
from windowtally.paths import MachinePaths
from windowtally.settings import REMINDER_DAYS_LIMITS

from . import actions_model
from .actions_model import Outcome
from .bills_model import (KIND_NAMES, BillForm, BillRow, BillsList, SourceRow, blank_form, form_of, read_list, takes_period,
                          takes_plan, with_kind)
from .common_view import Hint, RowList, WholeRows, card_margins, digits, em, plain_label, size_to_content
from .switch_view import ask
from .theme_view import Theme

KIND_KEYS = {name: key for key, name in KIND_NAMES.items()}
# What a field takes, behind its name: the form carries no explanation at rest.
FIELD_HINTS = {"date": "The day it was charged, YYYY-MM-DD; for a refund, the day it was issued",
               "amount": "What was charged, tax included, and its currency; for a refund, the sum returned",
               "start": "YYYY-MM-DD to YYYY-MM-DD; a period ends on the day the next would start",
               "reference": "The invoice number; a refund gives the invoice of the bill it credits"}
DAYS_SETTLE_MS = 800   # a step of the reminder's days is written this long after the last step
# Each column's width in characters of the default font, so the table scales with the display. The Amount column holds a
# sum in the thousands after its currency's code, such as EUR 1,408.63 (``billing.money_text``), whose capitals are wider
# than digits.
BILL_COLUMNS = (("date", "Date", 11), ("account", "Account", 22), ("what", "What", 10), ("amount", "Amount", 14),
                ("period", "Period", 24), ("reference", "Invoice", 10), ("source", "From", 13))
# The Bills column holds a source read in part, such as 350 bills, 25 left out.
SOURCE_COLUMNS = (("path", "File", 46), ("format", "Kind", 9), ("bills", "Bills", 20))
BILL_ROWS, SOURCE_ROWS = 10, 3
FORM_WORDS = 20        # lines of the default font what the form did runs to before it wraps
SOURCE_FILTERS = {"manifest": "A bill archive's manifest (*.csv);;Every file (*.*)",
                  "bills": "A bills file (*.json);;Every file (*.*)"}


def ask_open_path(parent: QWidget, filters: str) -> str:
    """The file the user chooses as a bill source, or "" if they did not. The dialog is Windows' own (measured with Qt
    6.12.0 on the development machine, 2026-11-07), so it follows Windows, not the window's palette."""
    dialog = QFileDialog(parent, "Add a bill source", "", filters)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
    chosen = dialog.selectedFiles()[0] if dialog.exec() else ""
    dialog.deleteLater()
    return chosen


class DaysBox(QAbstractSpinBox):
    """The reminder's days: the arrows step between the limits, and what is typed stands as typed, so a value out of them
    or no number at all reaches WindowTally's own rules and is refused in their words. ``stepped`` says an arrow moved it."""

    stepped = Signal()

    def __init__(self, low: int, high: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.low, self.high = low, high
        self.setKeyboardTracking(False)
        self.setFixedWidth(digits(4) + self.sizeHint().width())

    def value_typed(self) -> int | None:
        try:
            return int(self.text().strip())
        except ValueError:
            return None

    def validate(self, text: str, position: int):
        return QValidator.State.Acceptable, text, position

    def stepEnabled(self):
        value = self.value_typed()
        flags = QAbstractSpinBox.StepEnabledFlag.StepNone
        if value is None or value < self.high:
            flags |= QAbstractSpinBox.StepEnabledFlag.StepUpEnabled
        if value is None or value > self.low:
            flags |= QAbstractSpinBox.StepEnabledFlag.StepDownEnabled
        return flags

    def stepBy(self, steps: int) -> None:
        value = self.value_typed()
        self.show_days(max(self.low, min(self.high, (self.low if value is None else value) + steps)))
        self.stepped.emit()

    def show_days(self, days: int) -> None:
        self.lineEdit().setText(str(days))


class BillsWindow(QWidget):
    def __init__(self, theme: Theme, paths: MachinePaths, known_accounts: Callable[[], tuple[str, ...]],
                 changed: Callable[[Outcome], None], *, choose_file: Callable[[QWidget, str], str] = ask_open_path):
        """``changed(outcome)`` is called after each change that took, with what it did. ``choose_file`` stands in for the
        file dialog in a test."""
        super().__init__()
        self.theme, self.paths = theme, paths
        self.known_accounts, self.changed = known_accounts, changed
        self.choose_file = choose_file
        self.list: BillsList | None = None
        self.editing: BillRow | None = None
        self._rows: dict[str, BillRow] = {}
        self._sources: dict[str, SourceRow] = {}
        self._reminder_shown: int | None = None
        self._no_wheel: tuple[QWidget, ...] = ()     # the account's box and its field, where the wheel picks nothing
        self._days_timer = QTimer(self)
        self._days_timer.setSingleShot(True)
        self._days_timer.setInterval(DAYS_SETTLE_MS)
        self._days_timer.timeout.connect(self._days_settled)
        self.setWindowTitle("Bills and sources")
        theme.ground(self)
        pad = em(0.5)
        self.pad = pad
        body = QHBoxLayout(self)
        body.setContentsMargins(pad * 2, pad, pad * 2, pad)
        body.setSpacing(pad * 2)
        left = QVBoxLayout()
        left.setSpacing(0)
        self._bills_part(left)
        self._sources_part(left)
        body.addLayout(left, 1)
        right = QVBoxLayout()
        form = QFrame(self)
        theme.mark(form, "surface", "tile")
        self._form_part(form)
        right.addWidget(form)
        right.addStretch(1)
        body.addLayout(right)

    # --- the parts --------------------------------------------------------------------------------------------------

    def _heading(self, text: str) -> QLabel:
        label = plain_label(self)
        label.setText(text)
        label.setFont(self.theme.fonts["bold"])
        self.theme.ink(label, "ink")
        return label

    def _words(self, ink: str = "ink-2") -> QLabel:
        label = plain_label(self)
        label.setWordWrap(True)
        self.theme.ink(label, ink)
        return label

    def _bills_part(self, column: QVBoxLayout) -> None:
        pad = self.pad
        column.addWidget(self._heading("Bills"))
        column.addSpacing(pad // 2)
        self.bills = RowList(BILL_COLUMNS, BILL_ROWS, "account", self)
        self.bills.itemSelectionChanged.connect(self._bill_selected)
        self.bills.itemDoubleClicked.connect(lambda _item, _column: self._change())
        column.addWidget(WholeRows(self.bills, self), 1)
        column.addSpacing(pad // 2)
        actions = QHBoxLayout()
        actions.setSpacing(pad)
        self.change_button = QPushButton("Change", self)
        self.change_button.clicked.connect(lambda _checked=False: self._change())
        actions.addWidget(self.change_button)
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.clicked.connect(lambda _checked=False: self._remove())
        actions.addWidget(self.remove_button)
        self.bill_hint = plain_label(self)
        self.theme.ink(self.bill_hint, "ink-2")
        actions.addWidget(self.bill_hint, 1)
        column.addLayout(actions)

    def _sources_part(self, column: QVBoxLayout) -> None:
        pad = self.pad
        column.addSpacing(pad * 2)
        column.addWidget(self._heading("Sources"))
        column.addSpacing(pad // 2)
        self.sources = RowList(SOURCE_COLUMNS, SOURCE_ROWS, "path", self)
        self.sources.itemSelectionChanged.connect(self._source_selected)
        column.addWidget(self.sources)
        column.addSpacing(pad // 2)
        actions = QHBoxLayout()
        actions.setSpacing(pad)
        self.add_manifest = QPushButton("Add manifest…", self)
        self.add_manifest.clicked.connect(lambda _checked=False: self._add_source("manifest"))
        actions.addWidget(self.add_manifest)
        self.add_bills = QPushButton("Add bills file…", self)
        self.add_bills.clicked.connect(lambda _checked=False: self._add_source("bills"))
        actions.addWidget(self.add_bills)
        self.stop_button = QPushButton("Stop reading", self)
        self.stop_button.clicked.connect(lambda _checked=False: self._remove_source())
        actions.addWidget(self.stop_button)
        actions.addStretch(1)
        column.addLayout(actions)
        column.addSpacing(pad)
        self.problems = self._words("warning-text")
        column.addWidget(self.problems)
        column.addSpacing(pad * 2)
        reminder = QHBoxLayout()
        reminder.setSpacing(pad // 2)
        self.remind = QCheckBox("Renewal tag", self)
        self.remind.clicked.connect(lambda _checked=False: self._reminder_changed())
        reminder.addWidget(self.remind)
        self.days = DaysBox(*REMINDER_DAYS_LIMITS, self)
        self.days.show_days(3)
        self.days.stepped.connect(self._days_timer.start)
        self.days.editingFinished.connect(self._days_settled)
        reminder.addWidget(self.days)
        words = plain_label(self)
        words.setText("days before a period ends")
        self.theme.ink(words, "ink")
        reminder.addWidget(words)
        reminder.addStretch(1)
        column.addLayout(reminder)
        column.addSpacing(pad // 2)
        self.settings_said = self._words()
        column.addWidget(self.settings_said)

    def _form_part(self, frame: QFrame) -> None:
        pad = self.pad
        grid = QGridLayout(frame)
        grid.setContentsMargins(*card_margins())
        grid.setHorizontalSpacing(pad)
        grid.setVerticalSpacing(pad // 2)
        grid.setColumnStretch(1, 1)
        self.form_heading = self._heading("Record a bill")
        grid.addWidget(self.form_heading, 0, 0, 1, 2)
        rows = (("account", "Account"), ("date", "Date"), ("kind", "Kind"), ("plan", "Plan"),
                ("amount", "Amount"), ("start", "Period"), ("reference", "Invoice"), ("note", "Note"))
        self.inputs: dict[str, QWidget] = {}
        for index, (key, title) in enumerate(rows, start=1):
            label = plain_label(frame)
            label.setText(title)
            self.theme.ink(label, "ink-2")
            grid.addWidget(label, index, 0)
            cell = QHBoxLayout()
            cell.setSpacing(pad // 2)
            if key == "account":
                widget = self._choice(frame, digits(28), editable=True)
                widget.activated.connect(lambda _index: self._account_chosen())
                self._no_wheel = (widget, widget.lineEdit())
            elif key == "kind":
                widget = self._choice(frame, digits(16), values=KIND_NAMES.values())
                widget.activated.connect(lambda _index: self._kind_chosen())
            elif key == "plan":
                widget = self._choice(frame, digits(16), values=PLANS.values())
            elif key == "amount":
                widget = self._field(frame, digits(12))
                self.inputs["currency"] = self._choice(frame, digits(6), editable=True)
            elif key == "start":
                widget = self._field(frame, digits(12))
                self.inputs["end"] = self._field(frame, digits(12))
            else:
                widget = self._field(frame, digits(28))
            cell.addWidget(widget, 1)
            if key == "amount":
                cell.addWidget(self.inputs["currency"])
            elif key == "start":
                to = plain_label(frame)
                to.setText("to")
                self.theme.ink(to, "ink-2")
                cell.addWidget(to)
                cell.addWidget(self.inputs["end"], 1)
            grid.addLayout(cell, index, 1)
            self.inputs[key] = widget
            if key in FIELD_HINTS:
                Hint(label, FIELD_HINTS[key])
                Hint(widget, FIELD_HINTS[key], focus=True)
        self.form_said = self._words()
        self.form_said.setMaximumWidth(em(FORM_WORDS))
        grid.addWidget(self.form_said, len(rows) + 1, 0, 1, 2)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, pad // 2, 0, 0)
        actions.setSpacing(pad)
        actions.addStretch(1)
        self.cancel_button = QPushButton("Cancel", frame)
        self.cancel_button.clicked.connect(lambda _checked=False: self._cancel_change())
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.cancel_button)
        self.submit_button = QPushButton("Record", frame)
        self.submit_button.clicked.connect(lambda _checked=False: self._submit())
        actions.addWidget(self.submit_button)
        grid.addLayout(actions, len(rows) + 2, 0, 1, 2)

    def _field(self, parent: QWidget, width: int) -> QLineEdit:
        field = QLineEdit(parent)
        field.setMinimumWidth(width)
        return field

    def _choice(self, parent: QWidget, width: int, values=(), editable: bool = False) -> QComboBox:
        box = QComboBox(parent)
        box.setMinimumWidth(width)
        box.addItems(list(values))
        box.installEventFilter(self)
        if editable:
            box.setEditable(True)
            box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            box.setCompleter(None)     # a completer would change the case of an address as it is typed
            box.lineEdit().installEventFilter(self)
        return box

    def eventFilter(self, watched, event) -> bool:
        """Return and the arrows stay out of a drop-down, which would count them as a pick and, for an account, fill the
        form anew: Down opens the list, and only a pick from it counts. The wheel stays out of the account's, its
        field's included, for that same refill: ignored, the turn goes on to what is around the box."""
        if event.type() == QEvent.Type.Wheel:
            if watched not in self._no_wheel:
                return False
            event.ignore()
            return True
        if event.type() != QEvent.Type.KeyPress:
            return False
        if event.key() == Qt.Key.Key_Down:
            (watched if isinstance(watched, QComboBox) else watched.parentWidget()).showPopup()
        return event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Up, Qt.Key.Key_Down)

    # --- showing --------------------------------------------------------------------------------------------------

    def open(self, over: QWidget | None = None, *, record: bool = False) -> None:
        """``over`` is the window to open over the first time, where it shows."""
        first = self.list is None
        self.reload()
        if first:
            self._new_form()
            size_to_content(self, over)
        if record and self.editing is None:
            self.inputs["account"].setFocus()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def reload(self) -> None:
        previous = self._selected_bill()
        source = self._selected_source()
        self.list = read_list(self.paths, self.known_accounts())
        self._rows = {str(index): row for index, row in enumerate(self.list.rows)}
        # The selection follows its bill, never its place: a list read afresh may hold another bill there.
        chosen = next((key for key, row in self._rows.items() if previous is not None and row.bill == previous.bill), None)
        self.bills.fill(((key, (row.date, row.account, row.what, row.amount, row.period, row.reference, row.source))
                         for key, row in self._rows.items()), chosen)
        self._sources = {str(index): row for index, row in enumerate(self.list.sources)}
        # A click on Stop reading can start by leaving the days, whose write reloads: the button must outlive the reload.
        kept = next((key for key, row in self._sources.items() if source is not None and row.path == source.path), None)
        self.sources.fill(((key, (row.name, row.format, row.count)) for key, row in self._sources.items()), kept)
        self.problems.setText("\n".join(f"• {p}" for p in self.list.problems))
        self._suggest("account", self.list.accounts)
        self._suggest("currency", self.list.currencies)
        days = self.list.reminder_days
        self._reminder_shown = days
        self.remind.setChecked(days is not None)
        if days is not None:
            self.days.show_days(days)
        self.days.setEnabled(days is not None)
        self._bill_selected()
        self._source_selected()

    def _suggest(self, key: str, values: tuple[str, ...]) -> None:
        """A drop-down's list replaced, what the field holds kept."""
        box = self.inputs[key]
        typed = box.currentText()
        with QSignalBlocker(box):
            box.clear()
            box.addItems(list(values))
            box.setCurrentIndex(-1)
            box.setEditText(typed)

    def _selected_bill(self) -> BillRow | None:
        return self._rows.get(self.bills.key_chosen())

    def _bill_selected(self) -> None:
        row = self._selected_bill()
        editable = row is not None and row.editable
        self.change_button.setEnabled(editable)
        self.remove_button.setEnabled(editable)
        self.bill_hint.setText(f"From {row.source}: change it there." if row is not None and not row.editable else "")

    def _selected_source(self) -> SourceRow | None:
        return self._sources.get(self.sources.key_chosen())

    def _source_selected(self) -> None:
        source = self._selected_source()
        self.stop_button.setEnabled(source is not None and not source.own)

    # --- the form -------------------------------------------------------------------------------------------------

    def _value(self, key: str) -> str:
        field = self.inputs[key]
        return field.currentText() if isinstance(field, QComboBox) else field.text()

    def _set(self, key: str, value: str) -> None:
        field = self.inputs[key]
        if not isinstance(field, QComboBox):
            field.setText(value)
        elif field.isEditable():
            field.setEditText(value)
        else:
            field.setCurrentIndex(field.findText(value))

    def _form(self) -> BillForm:
        values = {key: self._value(key) for key in BillForm.__dataclass_fields__}
        values["kind"] = KIND_KEYS.get(values["kind"], values["kind"])
        return BillForm(**values)

    def _fill(self, form: BillForm) -> None:
        for key in BillForm.__dataclass_fields__:
            value = getattr(form, key)
            self._set(key, KIND_NAMES.get(value, value) if key == "kind" else value)
        self._fields_for_kind(form.kind)
        self.form_said.setText("")

    def _tell(self, label: QLabel, outcome: Outcome) -> None:
        """What a change did, under the part it was made in: a refusal in the error's colour."""
        label.setText(outcome.message)
        self.theme.ink(label, "ink-2" if outcome.ok else "critical-text")

    def _fields_for_kind(self, kind: str) -> None:
        self.inputs["plan"].setEnabled(takes_plan(kind))
        for key in ("start", "end"):
            self.inputs[key].setEnabled(takes_period(kind))

    def _new_form(self, account: str = "") -> None:
        if not account:
            account = self.list.accounts[0] if self.list and self.list.accounts else ""
        self._fill(blank_form(self.list, account, date.today()))

    def _account_chosen(self) -> None:
        if self.editing is None:
            self._fill(blank_form(self.list, self._value("account"), date.today()))

    def _kind_chosen(self) -> None:
        self._fill(with_kind(self._form(), KIND_KEYS.get(self._value("kind"), "subscription"), date.today()))

    def _submit(self) -> None:
        if self.editing is None:
            outcome = actions_model.record_bill(self.paths, self._form())
        else:
            outcome = actions_model.replace_bill(self.paths, self.editing.bill, self._form())
        if not outcome.ok:
            self._tell(self.form_said, outcome)
            return
        account = self._value("account")
        self._end_change()
        self.reload()
        self._new_form(account)
        self._tell(self.form_said, outcome)
        self.changed(outcome)

    def _change(self) -> None:
        row = self._selected_bill()
        if row is None or not row.editable:
            return
        self.editing = row
        self._fill(form_of(row.bill))
        self.form_heading.setText(f"Bill of {row.date}")
        self.submit_button.setText("Save")
        self.cancel_button.setEnabled(True)

    def _end_change(self) -> None:
        self.editing = None
        self.form_heading.setText("Record a bill")
        self.submit_button.setText("Record")
        self.cancel_button.setEnabled(False)

    def _cancel_change(self) -> None:
        self._end_change()
        self._new_form(self._value("account"))

    def _yes(self, title: str, message: str) -> bool:
        return ask(self, title, message, (("yes", "Yes"), ("no", "No")), default="yes", cancel="no") == "yes"

    def _remove(self) -> None:
        row = self._selected_bill()
        if row is None or not row.editable:
            return
        if not self._yes("Remove a bill", f"Remove {row.account}'s bill of {row.date}, {row.amount}?"):
            return
        outcome = actions_model.remove_bill(self.paths, row.bill)
        if self.editing is not None and self.editing.bill == row.bill:
            self._cancel_change()
        self.reload()
        self._tell(self.form_said, outcome)
        if outcome.ok:
            self.changed(outcome)

    # --- sources and the reminder ---------------------------------------------------------------------------------

    def _add_source(self, format: str) -> None:
        chosen = self.choose_file(self, SOURCE_FILTERS[format])
        if not chosen:
            return
        self._after_settings(actions_model.add_source(self.paths, format, Path(chosen)))

    def _remove_source(self) -> None:
        source = self._selected_source()
        if source is None or source.own:
            return
        if not self._yes("Stop reading a bill source", f"Stop reading {source.path}? The file stays."):
            return
        self._after_settings(actions_model.remove_source(self.paths, source.path))

    def _days_settled(self) -> None:
        self._days_timer.stop()
        self._reminder_changed(only_if_changed=True)

    def _reminder_changed(self, only_if_changed: bool = False) -> None:
        days: int | None = None
        if self.remind.isChecked():
            days = self.days.value_typed()
            if days is None:
                self.days.setEnabled(True)    # ticked over text left from before: the field must stay correctable
                self._tell(self.settings_said,
                           Outcome(False, f"Not changed: {self.days.text().strip()!r} is not a whole number."))
                return
        if only_if_changed and days == self._reminder_shown:
            return
        self._after_settings(actions_model.set_reminder(self.paths, days))

    def _after_settings(self, outcome: Outcome) -> None:
        self.reload()
        self._tell(self.settings_said, outcome)
        if outcome.ok:
            self.changed(outcome)
