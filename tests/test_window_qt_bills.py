"""The Bills and sources window on an invented machine, headless: its lists, its form, what its buttons write, the
sources and the reminder, and how the shell reaches it. Every rule is WindowTally's own, reached through the models the
window draws from; the file dialog and the questions are stand-ins, so no test shows a dialog."""

import json
import time
import unittest
from datetime import date
from decimal import Decimal
from unittest import mock

from qt_support import APP

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QAbstractItemView, QApplication, QComboBox, QFileDialog, QLabel, QPushButton, QWidget

from fixtures import ACCOUNT_A, EMAIL_A, EMAIL_B, Machine, bill, manifest_rows
from test_window_qt_shell import ShellCase, spin
from windowtally.bills import read_bills_file
from windowtally.service import run_pass
from windowtally.settings import REMINDER_DAYS_LIMITS, load_settings
from windowtally_gui import bills_view
from windowtally_gui.actions_model import Outcome
from windowtally_gui.bills_view import (BILL_COLUMNS, BILL_ROWS, DAYS_SETTLE_MS, FIELD_HINTS, SOURCE_ROWS, BillsWindow,
                                        DaysBox, ask_open_path)
from windowtally_gui.common_view import Hint, RowList, em
from windowtally_gui.theme_view import Theme, style_sheet
from windowtally_gui.theme_model import colours

TODAY = date.today().isoformat()


def press(widget, key=Qt.Key.Key_Return) -> None:
    APP.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def texts(table: RowList) -> list[list[str]]:
    return [[table.topLevelItem(row).text(column) for column in range(table.columnCount())]
            for row in range(table.topLevelItemCount())]


def pick(box, text: str) -> None:
    """A pick from a drop-down's list."""
    box.setCurrentIndex(box.findText(text))
    box.activated.emit(box.currentIndex())


class WindowCase(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.addCleanup(self.machine.close)
        self.paths = self.machine.paths
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.theme = Theme(APP, "light")
        self.changes: list[Outcome] = []
        self.chosen = ""
        self.window = None

    def seed(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-09-07", 180, period="2026-09-07..2026-10-07", reference="A-0"),
                                 bill(EMAIL_A, "2026-10-07", 180, period="2026-10-07..2026-11-07", reference="A-1")])
        self.manifest = self.machine.manifest(manifest_rows(EMAIL_B, "B01", "2026-09-23", "100.00", "Max plan - 5x",
                                                            "2026-09-23..2026-10-23", invoice="B-1", currency="USD"))
        self.machine.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(self.manifest)}],
                               "renewalReminderDays": 3})

    def open(self, *, record=False) -> BillsWindow:
        self.window = BillsWindow(self.theme, self.paths, lambda: ("Gamma@Example.com",), self.changes.append,
                                  choose_file=lambda _parent, _filters: self.chosen)
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.hide)
        self.window.open(record=record)
        spin()
        return self.window

    def row(self, window: BillsWindow, day: str, source: str = "bills.json") -> str:
        return next(key for key, row in window._rows.items() if row.date == day and row.source == source)

    def select(self, window: BillsWindow, day: str, source: str = "bills.json") -> None:
        window.bills.setCurrentItem(window.bills.item_of(self.row(window, day, source)))

    def fill_form(self, window: BillsWindow, **values) -> None:
        for key, value in values.items():
            window._set(key, value)


class RowListTest(unittest.TestCase):
    def test_a_row_is_known_by_its_key_wherever_it_stands(self):
        table = RowList((("a", "A", 4), ("b", "B", 4)), 3, "b")
        self.addCleanup(table.deleteLater)
        table.fill([("one", ("1", "x")), ("two", ("2", "y"))], "two")
        self.assertEqual(table.key_chosen(), "two")
        table.fill([("two", ("2", "y")), ("one", ("1", "x"))], "two")
        self.assertEqual(table.currentItem().text(0), "2")
        self.assertEqual(table.indexOfTopLevelItem(table.item_of("one")), 1)
        table.set_cell("one", "b", "z")
        self.assertEqual(table.item_of("one").text(1), "z")

    def test_a_list_filled_says_nothing_of_a_selection_and_one_is_chosen_at_a_time(self):
        table = RowList((("a", "A", 4),), 3, "a")
        self.addCleanup(table.deleteLater)
        heard = []
        table.itemSelectionChanged.connect(lambda: heard.append(1))
        table.fill([("one", ("1",))], "one")
        self.assertEqual(heard, [])
        self.assertEqual(table.selectionMode(), QAbstractItemView.SelectionMode.SingleSelection)
        table.fill([])
        self.assertIsNone(table.key_chosen())

    def test_columns_dragged_past_the_edge_can_still_be_reached(self):
        table = RowList((("a", "A", 10), ("b", "B", 20), ("c", "C", 10)), 3, "b")
        self.addCleanup(table.deleteLater)
        table.resize(300, 200)
        table.show()
        spin()
        table.setColumnWidth(0, 500)
        spin()
        self.assertGreater(table.horizontalScrollBar().maximum(), 0)
        table.hide()

    def test_it_asks_for_room_for_its_rows_and_its_columns(self):
        table = RowList((("a", "A", 10), ("b", "B", 20)), 5, "b")
        self.addCleanup(table.deleteLater)
        self.assertGreaterEqual(table.sizeHint().width(), sum(table.widths))
        self.assertGreaterEqual(table.sizeHint().height(), 5 * em(1))

    def test_both_modes_draw_the_list_on_the_field_under_a_hairline_the_chosen_row_in_the_selection_s_role(self):
        for mode in ("light", "dark"):
            c = colours(mode)
            sheet = style_sheet(c)
            rule = next(line for line in sheet.splitlines() if line.startswith("QTreeWidget"))
            self.assertIn(c["field"], rule)
            self.assertIn(c["baseline"], rule)
            self.assertIn(f'QTreeWidget::item:selected {{ background: {c["selection"]}; color: {c["ink"]}; }}', sheet)
            self.assertIn(f'QTreeWidget:focus {{ border-color: {c["focus"]}; }}', sheet)


class ListsTest(WindowCase):
    def test_every_source_s_bills_newest_first_with_what_the_model_gives(self):
        self.seed()
        window = self.open()
        rows = texts(window.bills)
        self.assertEqual([row[0] for row in rows], ["2026-10-07", "2026-09-23", "2026-09-07"])
        self.assertEqual(rows[0], ["2026-10-07", EMAIL_A, "Ultra", "EUR 180.00", "2026-10-07 → 2026-11-07", "A-1",
                                   "bills.json"])
        self.assertEqual([c[1] for c in BILL_COLUMNS], [window.bills.headerItem().text(i) for i in range(len(BILL_COLUMNS))])

    def test_the_amount_column_holds_a_sum_in_the_thousands_after_its_currency_s_code(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-10-07", 8888.88, period="2026-10-07..2026-11-07", reference="A-1")])
        window = self.open()
        column = window.bills.columns.index("amount")
        self.assertEqual(window.bills.topLevelItem(0).text(column), "EUR 8,888.88")
        self.assertLessEqual(window.bills.sizeHintForColumn(column), window.bills.columnWidth(column))

    def test_a_date_and_a_period_stand_whole_in_their_columns(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-10-07", 90, period="2026-10-07..2026-11-07", reference="A-1")])
        window = self.open()
        for column in ("date", "period"):
            index = window.bills.columns.index(column)
            self.assertLessEqual(window.bills.sizeHintForColumn(index), window.bills.columnWidth(index), column)

    def test_a_bill_of_a_further_source_can_be_neither_changed_nor_removed(self):
        self.seed()
        window = self.open()
        self.assertFalse(window.change_button.isEnabled())
        self.select(window, "2026-09-23", "_manifest.csv")
        self.assertEqual(window.bill_hint.text(), "From _manifest.csv: change it there.")
        self.assertFalse(window.change_button.isEnabled())
        self.assertFalse(window.remove_button.isEnabled())
        window._change()
        self.assertIsNone(window.editing)
        self.select(window, "2026-10-07")
        self.assertEqual(window.bill_hint.text(), "")
        self.assertTrue(window.change_button.isEnabled())
        self.assertTrue(window.remove_button.isEnabled())

    def test_the_selection_follows_its_bill_never_its_place(self):
        self.seed()
        window = self.open()
        self.select(window, "2026-09-07")
        chosen = window._selected_bill().bill
        recorded = json.loads(self.paths.bills_file.read_text(encoding="utf-8"))
        recorded["bills"].append(bill(EMAIL_A, "2026-11-07", 180, period="2026-11-07..2026-12-07", reference="A-2"))
        self.paths.bills_file.write_text(json.dumps(recorded), encoding="utf-8")
        window.reload()
        self.assertEqual(texts(window.bills)[0][0], "2026-11-07")
        self.assertEqual(window._selected_bill().bill, chosen)

    def test_each_show_reads_the_lists_afresh_and_keeps_the_size_it_opened_at(self):
        self.seed()
        window = self.open()
        window.resize(window.width() + 40, window.height())
        size = window.size()
        window.hide()
        self.machine.bills_file([])
        window.open()
        self.assertEqual(window.size(), size)
        self.assertEqual(len(texts(window.bills)), 1)

    def test_the_lists_show_their_rows_and_the_bills_take_the_height(self):
        self.seed()
        window = self.open()
        self.assertEqual((window.bills.rows_shown, window.sources.rows_shown), (BILL_ROWS, SOURCE_ROWS))
        self.assertGreater(window.bills.height(), window.sources.height())

    def test_closing_hides_the_window_and_never_vetoes_a_quit(self):
        self.seed()
        window = self.open()
        self.assertTrue(window.close())
        self.assertTrue(window.isHidden())

    def test_a_double_click_on_a_bill_changes_it(self):
        self.seed()
        window = self.open()
        self.select(window, "2026-10-07")
        window.bills.itemDoubleClicked.emit(window.bills.currentItem(), 0)
        self.assertEqual(window.form_heading.text(), "Bill of 2026-10-07")


class FormTest(WindowCase):
    def test_a_new_form_starts_from_the_first_account_s_latest_subscription(self):
        self.seed()
        window = self.open()
        self.assertEqual(window._value("account"), EMAIL_A)
        self.assertEqual((window._value("plan"), window._value("amount"), window._value("currency")),
                         ("Ultra", "180.00", "EUR"))
        self.assertEqual((window._value("date"), window._value("start")), (TODAY, TODAY))
        self.assertEqual(window.form_heading.text(), "Record a bill")
        self.assertEqual(window.submit_button.text(), "Record")
        self.assertFalse(window.cancel_button.isEnabled())

    def test_the_form_suggests_the_accounts_known_and_the_currencies_listed(self):
        self.seed()
        window = self.open()
        account, currency = window.inputs["account"], window.inputs["currency"]
        self.assertEqual([account.itemText(i) for i in range(account.count())],
                         [EMAIL_A, EMAIL_B, "gamma@example.com"])
        self.assertEqual([currency.itemText(i) for i in range(currency.count())], ["EUR", "USD"])

    def test_a_reload_keeps_what_the_fields_that_also_take_typing_hold(self):
        self.seed()
        window = self.open()
        window.inputs["account"].setEditText("typed@Example.com")
        window.inputs["currency"].setEditText("CHF")
        window.reload()
        self.assertEqual((window._value("account"), window._value("currency")), ("typed@Example.com", "CHF"))

    def test_picking_an_account_starts_a_new_form_for_it_but_not_while_a_bill_is_changed(self):
        self.seed()
        window = self.open()
        pick(window.inputs["account"], EMAIL_B)
        self.assertEqual((window._value("plan"), window._value("amount")), ("Max 5x", "100.00"))
        self.select(window, "2026-10-07")
        window._change()
        pick(window.inputs["account"], EMAIL_B)
        self.assertEqual(window._value("amount"), "180.00")

    def test_return_in_a_field_that_also_takes_typing_is_no_pick(self):
        self.seed()
        window = self.open()
        self.fill_form(window, amount="55.00")
        field = window.inputs["account"].lineEdit()
        field.setText(EMAIL_B)
        press(field)
        self.assertEqual(window._value("amount"), "55.00")

    def test_the_arrows_in_a_drop_down_change_nothing_and_down_opens_its_list(self):
        self.seed()
        window = self.open()
        self.fill_form(window, amount="55.00")
        for box, target in ((window.inputs["account"], window.inputs["account"].lineEdit()),
                            (window.inputs["kind"], window.inputs["kind"])):
            before = box.currentText()
            with mock.patch.object(QComboBox, "showPopup") as popped:
                press(target, Qt.Key.Key_Up)
                popped.assert_not_called()
                press(target, Qt.Key.Key_Down)
                popped.assert_called_once()
            self.assertEqual(box.currentText(), before)
        self.assertEqual(window._value("amount"), "55.00")

    def test_a_turn_of_the_wheel_over_a_drop_down_picks_as_the_list_does(self):
        self.seed()
        window = self.open()
        box = window.inputs["kind"]
        self.fill_form(window, date="2026-10-07")
        at = QPointF(5, 5)
        APP.sendEvent(box, QWheelEvent(at, box.mapToGlobal(at), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                                       Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))
        self.assertEqual(box.currentText(), "top-up")
        self.assertFalse(window.inputs["plan"].isEnabled())

    def test_a_turn_of_the_wheel_over_the_account_s_drop_down_keeps_what_was_typed(self):
        self.seed()
        window = self.open()
        box = window.inputs["account"]
        self.fill_form(window, account=EMAIL_A, date="2026-10-07", amount="55.00", reference="TYPED-1",
                       note="typed words")
        typed = {key: window._value(key) for key in ("account", "date", "amount", "reference", "note")}
        at = QPointF(5, 5)
        for target in (box, box.lineEdit()):
            for notch in (-120, 120, -120):
                turn = QWheelEvent(at, target.mapToGlobal(at), QPoint(0, 0), QPoint(0, notch), Qt.MouseButton.NoButton,
                                   Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
                APP.sendEvent(target, turn)
                self.assertEqual({key: window._value(key) for key in typed}, typed)
                # Qt hands an ignored turn on to the widget's parent only for one Windows sent, never for one made
                # here, so what is read is the flag it hands it on by.
                self.assertFalse(turn.isAccepted())

    def test_a_typed_address_keeps_its_case_and_joins_no_list(self):
        self.seed()
        window = self.open()
        box = window.inputs["account"]
        self.assertIsNone(box.completer())
        count = box.count()
        box.lineEdit().setText("ALPHA@EXAMPLE.COM")
        press(box.lineEdit())
        self.assertEqual((box.currentText(), box.count()), ("ALPHA@EXAMPLE.COM", count))

    def test_fields_a_kind_does_not_take_are_disabled_not_hidden(self):
        self.seed()
        window = self.open()
        pick(window.inputs["kind"], "top-up")
        for key in ("plan", "start", "end"):
            self.assertFalse(window.inputs[key].isEnabled(), key)
            self.assertTrue(window.inputs[key].isVisible(), key)
        pick(window.inputs["kind"], "usage settled")
        self.assertFalse(window.inputs["plan"].isEnabled())
        self.assertTrue(window.inputs["start"].isEnabled())
        pick(window.inputs["kind"], "refund")
        self.assertFalse(window.inputs["end"].isEnabled())

    def test_a_kind_that_takes_a_period_opens_one_from_the_charge_date(self):
        self.seed()
        window = self.open()
        pick(window.inputs["kind"], "refund")
        self.fill_form(window, date="2026-10-07", start="", end="")
        pick(window.inputs["kind"], "usage settled")
        self.assertEqual((window._value("start"), window._value("end")), ("2026-10-07", "2026-11-07"))

    def test_the_hints_stand_on_the_name_and_on_the_field_the_field_s_on_the_focus_too(self):
        window = self.open()
        for key, words in FIELD_HINTS.items():
            hints = window.inputs[key].findChildren(Hint)
            self.assertEqual([(h.text, h.focus) for h in hints], [(words, True)], key)
        names = [h for label in window.findChildren(QLabel) for h in label.findChildren(Hint)]
        self.assertEqual(sorted(h.text for h in names), sorted(FIELD_HINTS.values()))
        self.assertFalse(any(h.focus for h in names))

    def test_a_show_to_record_puts_the_focus_on_the_account_unless_a_bill_is_being_changed(self):
        self.seed()
        window = self.open(record=True)
        self.assertIs(window.focusWidget(), window.inputs["account"])
        window.days.setFocus()
        self.select(window, "2026-10-07")
        window._change()
        window.open(record=True)
        self.assertIsNot(window.focusWidget(), window.inputs["account"])


class RecordTest(WindowCase):
    def test_a_bill_recorded_reaches_the_file_the_lists_and_the_next_status(self):
        self.machine.add_account(ACCOUNT_A, EMAIL_A, "0a0a0a0a-0000-4000-8000-00000000000a")
        window = self.open()
        self.fill_form(window, account=EMAIL_A, date=TODAY, plan="Max 5x", amount="1,090.50", currency="eur",
                       start=TODAY, end="2099-01-01", reference=" INV-9 ", note="a note")
        window.submit_button.click()
        (recorded,) = read_bills_file(self.paths.bills_file)
        self.assertEqual((recorded.account, recorded.plan, recorded.amount, recorded.currency, recorded.reference,
                          recorded.note), (EMAIL_A, "max5x", Decimal("1090.50"), "EUR", "INV-9", "a note"))
        said = f"Recorded {EMAIL_A}: {TODAY} Max 5x EUR 1,090.50, {TODAY}..2099-01-01."
        self.assertEqual(window.form_said.text(), said)
        self.assertEqual(window.form_said.property("ink"), "ink-2")
        self.assertEqual(self.changes, [Outcome(True, said)])
        self.assertEqual(texts(window.bills)[0][3], "EUR 1,090.50")
        self.assertEqual((window._value("account"), window._value("date")), (EMAIL_A, TODAY))
        run_pass(self.paths)
        (account,) = json.loads(self.paths.status_file.read_text(encoding="utf-8"))["accounts"]
        self.assertEqual((account["subscription"]["plan"], account["subscription"]["paidUntil"]), ("max5x", "2099-01-01"))

    def test_a_refusal_is_said_in_windowtally_s_words_and_the_fields_keep_what_was_typed(self):
        window = self.open()
        self.fill_form(window, account=EMAIL_A, date="2026-13-01", amount="ten", currency="EUR")
        window.submit_button.click()
        self.assertTrue(window.form_said.text().startswith("Not recorded: "))
        self.assertIn("the date '2026-13-01' is not a calendar day", window.form_said.text())
        self.assertIn("the amount 'ten' is not a number", window.form_said.text())
        self.assertEqual(window.form_said.property("ink"), "critical-text")
        self.assertEqual((window._value("date"), window._value("amount")), ("2026-13-01", "ten"))
        self.assertEqual(self.changes, [])
        self.assertFalse(self.paths.bills_file.exists())

    def test_change_fills_the_form_and_save_replaces_the_bill(self):
        self.seed()
        window = self.open()
        self.select(window, "2026-10-07")
        window.change_button.click()
        self.assertEqual(window.form_heading.text(), "Bill of 2026-10-07")
        self.assertEqual(window.submit_button.text(), "Save")
        self.assertTrue(window.cancel_button.isEnabled())
        self.assertEqual((window._value("date"), window._value("reference")), ("2026-10-07", "A-1"))
        self.fill_form(window, amount="90")
        window.submit_button.click()
        self.assertEqual([b.amount for b in read_bills_file(self.paths.bills_file) if b.reference == "A-1"],
                         [Decimal("90")])
        self.assertEqual(window.form_heading.text(), "Record a bill")
        self.assertIsNone(window.editing)
        self.assertTrue(window.form_said.text().startswith("Changed: "))
        self.assertEqual(len(self.changes), 1)

    def test_a_save_refused_stays_on_the_bill_being_changed(self):
        self.seed()
        window = self.open()
        self.select(window, "2026-10-07")
        window._change()
        self.fill_form(window, amount="ten")
        window.submit_button.click()
        self.assertTrue(window.form_said.text().startswith("Not changed: "))
        self.assertIsNotNone(window.editing)
        self.assertEqual(window.submit_button.text(), "Save")

    def test_cancel_ends_the_change_with_a_new_form_for_the_account(self):
        self.seed()
        window = self.open()
        self.select(window, "2026-09-07")
        window._change()
        self.fill_form(window, note="not kept")
        window.cancel_button.click()
        self.assertIsNone(window.editing)
        self.assertEqual((window._value("note"), window._value("date")), ("", TODAY))
        self.assertFalse(window.cancel_button.isEnabled())

    def test_remove_asks_first_and_no_leaves_the_bill(self):
        self.seed()
        window = self.open()
        self.select(window, "2026-10-07")
        with mock.patch.object(bills_view, "ask", return_value="no") as asked:
            window.remove_button.click()
        (_parent, title, message, buttons), options = asked.call_args
        self.assertEqual(title, "Remove a bill")
        self.assertEqual(message, f"Remove {EMAIL_A}'s bill of 2026-10-07, EUR 180.00?")
        self.assertEqual((buttons, options), ((("yes", "Yes"), ("no", "No")), {"default": "yes", "cancel": "no"}))
        self.assertEqual(len(read_bills_file(self.paths.bills_file)), 2)
        self.assertEqual(self.changes, [])

    def test_yes_removes_the_bill_and_ends_a_change_of_it(self):
        self.seed()
        window = self.open()
        self.select(window, "2026-10-07")
        window._change()
        with mock.patch.object(bills_view, "ask", return_value="yes"):
            window.remove_button.click()
        self.assertEqual([b.reference for b in read_bills_file(self.paths.bills_file)], ["A-0"])
        self.assertIsNone(window.editing)
        self.assertTrue(window.form_said.text().startswith("Removed "))
        self.assertEqual(len(self.changes), 1)


class SourcesTest(WindowCase):
    def test_the_sources_say_how_much_was_read_and_only_a_further_one_can_be_stopped(self):
        self.seed()
        window = self.open()
        own, other = texts(window.sources)
        self.assertTrue(own[0].endswith("bills.json (own)"))
        self.assertEqual((own[1], own[2]), ("bills", "2 bills"))
        self.assertEqual(other, [str(self.manifest), "manifest", "1 bill"])
        self.assertFalse(window.stop_button.isEnabled())
        window.sources.setCurrentItem(window.sources.topLevelItem(0))
        self.assertFalse(window.stop_button.isEnabled())
        window.sources.setCurrentItem(window.sources.topLevelItem(1))
        self.assertTrue(window.stop_button.isEnabled())

    def test_a_source_selected_stays_selected_through_a_write_of_the_days(self):
        self.seed()
        window = self.open()
        window.sources.setCurrentItem(window.sources.topLevelItem(1))
        window.days.lineEdit().setText("7")
        window.days.editingFinished.emit()
        self.assertEqual(load_settings(self.paths.settings_file).renewal_reminder_days, 7)
        self.assertEqual(window.sources.key_chosen(), "1")
        self.assertTrue(window.stop_button.isEnabled())

    def test_a_source_added_is_listed_said_and_the_window_told(self):
        manifest = self.machine.manifest(manifest_rows(EMAIL_B, "B02", "2026-09-23", "100.00", "Max plan - 5x",
                                                       "2026-09-23..2026-10-23", invoice="B-2"), name="more.csv")
        window = self.open()
        self.chosen = str(manifest)
        window.add_manifest.click()
        self.assertEqual(window.settings_said.text(), f"Added {manifest}: 1 bill.")
        self.assertEqual(window.settings_said.property("ink"), "ink-2")
        self.assertEqual(len(self.changes), 1)
        self.assertEqual(texts(window.sources)[-1], [str(manifest), "manifest", "1 bill"])

    def test_no_file_chosen_changes_nothing(self):
        window = self.open()
        window.add_bills.click()
        self.assertEqual(window.settings_said.text(), "")
        self.assertEqual(self.changes, [])

    def test_a_source_refused_is_said_in_the_error_s_colour(self):
        window = self.open()
        self.chosen = str(self.paths.data_dir / "nothing.json")
        window.add_bills.click()
        self.assertTrue(window.settings_said.text().startswith("Not "))
        self.assertEqual(window.settings_said.property("ink"), "critical-text")
        self.assertEqual(self.changes, [])

    def test_the_filters_name_the_kind_of_file_then_every_file(self):
        heard = []
        window = self.open()
        window.choose_file = lambda _parent, filters: heard.append(filters) or ""
        window.add_manifest.click()
        window.add_bills.click()
        self.assertEqual(heard, ["A bill archive's manifest (*.csv);;Every file (*.*)",
                                 "A bills file (*.json);;Every file (*.*)"])

    def test_stop_reading_asks_first_and_keeps_the_file(self):
        self.seed()
        window = self.open()
        window.sources.setCurrentItem(window.sources.topLevelItem(1))
        with mock.patch.object(bills_view, "ask", return_value="no") as asked:
            window.stop_button.click()
        self.assertEqual(asked.call_args.args[1:3],
                         ("Stop reading a bill source", f"Stop reading {self.manifest}? The file stays."))
        self.assertEqual(len(load_settings(self.paths.settings_file).bill_sources), 1)
        window.sources.setCurrentItem(window.sources.topLevelItem(1))
        with mock.patch.object(bills_view, "ask", return_value="yes"):
            window.stop_button.click()
        self.assertEqual(load_settings(self.paths.settings_file).bill_sources, ())
        self.assertTrue(self.manifest.exists())
        self.assertEqual(window.settings_said.text(), f"Stopped reading {self.manifest}.")
        self.assertEqual(len(self.changes), 1)

    def test_the_source_problems_stand_under_the_sources_bulleted(self):
        self.seed()
        self.paths.bills_file.write_text("{ not json", encoding="utf-8")
        window = self.open()
        self.assertTrue(window.problems.text().startswith("• "))
        self.assertEqual(window.problems.property("ink"), "warning-text")


class ReminderTest(WindowCase):
    def days_set(self):
        return load_settings(self.paths.settings_file).renewal_reminder_days

    def test_the_box_shows_the_settings_and_the_days_wait_while_it_is_off(self):
        window = self.open()
        self.assertFalse(window.remind.isChecked())
        self.assertFalse(window.days.isEnabled())
        self.assertEqual(window.days.text(), "3")
        self.seed()
        window.reload()
        self.assertTrue(window.remind.isChecked())
        self.assertTrue(window.days.isEnabled())

    def test_the_check_box_sets_and_clears_the_reminder(self):
        window = self.open()
        window.remind.click()
        self.assertEqual(self.days_set(), 3)
        self.assertEqual(window.settings_said.text(), "Renewal tag: 3 days before a period ends.")
        self.assertEqual(len(self.changes), 1)
        window.remind.click()
        self.assertIsNone(self.days_set())
        self.assertFalse(window.days.isEnabled())

    def test_a_step_of_the_arrows_is_written_once_the_steps_stop(self):
        self.seed()
        window = self.open()
        window.days.stepBy(1)
        window.days.stepBy(1)
        self.assertEqual(self.days_set(), 3)
        self.assertTrue(window._days_timer.isActive())
        self.assertEqual(window._days_timer.interval(), DAYS_SETTLE_MS)
        window._days_timer.timeout.emit()
        self.assertEqual(self.days_set(), 5)
        self.assertEqual(len(self.changes), 1)

    def test_return_writes_the_days_at_once_and_leaving_them_unchanged_writes_nothing(self):
        self.seed()
        window = self.open()
        window.days.lineEdit().setText("7")
        window.days.editingFinished.emit()
        self.assertEqual(self.days_set(), 7)
        self.assertEqual(len(self.changes), 1)
        window.days.editingFinished.emit()
        self.assertEqual(len(self.changes), 1)

    def test_what_is_no_whole_number_is_refused_and_the_setting_stays(self):
        self.seed()
        window = self.open()
        window.days.lineEdit().setText("soon")
        window.days.editingFinished.emit()
        self.assertEqual(window.settings_said.text(), "Not changed: 'soon' is not a whole number.")
        self.assertEqual(window.settings_said.property("ink"), "critical-text")
        self.assertEqual(self.days_set(), 3)

    def test_text_left_refused_never_locks_the_reminder_off(self):
        self.seed()
        window = self.open()
        window.days.lineEdit().setText("soon")
        window.days.editingFinished.emit()
        window.remind.click()
        self.assertIsNone(self.days_set())
        self.assertFalse(window.days.isEnabled())
        window.remind.click()
        self.assertEqual(window.settings_said.text(), "Not changed: 'soon' is not a whole number.")
        self.assertTrue(window.days.isEnabled())
        window.days.lineEdit().setText("4")
        window.days.editingFinished.emit()
        self.assertEqual(self.days_set(), 4)

    def test_a_value_past_the_limits_reaches_windowtally_s_own_refusal(self):
        self.seed()
        window = self.open()
        window.days.lineEdit().setText(str(REMINDER_DAYS_LIMITS[1] + 1))
        window.days.editingFinished.emit()
        self.assertTrue(window.settings_said.text().startswith("Not changed: "))
        self.assertEqual(window.settings_said.property("ink"), "critical-text")
        self.assertEqual(window.days.text(), "3")
        self.assertEqual(self.changes, [])


class DaysBoxTest(unittest.TestCase):
    def setUp(self):
        self.box = DaysBox(1, 31)
        self.addCleanup(self.box.deleteLater)

    def test_the_arrows_stay_between_the_limits(self):
        self.box.show_days(30)
        self.box.stepBy(5)
        self.assertEqual(self.box.text(), "31")
        self.box.show_days(2)
        self.box.stepBy(-5)
        self.assertEqual(self.box.text(), "1")

    def test_each_end_closes_its_arrow(self):
        up, down = DaysBox.StepEnabledFlag.StepUpEnabled, DaysBox.StepEnabledFlag.StepDownEnabled
        self.box.show_days(31)
        self.assertEqual(self.box.stepEnabled(), down)
        self.box.show_days(1)
        self.assertEqual(self.box.stepEnabled(), up)

    def test_from_what_is_no_number_the_arrows_start_at_the_low_limit(self):
        self.box.lineEdit().setText("soon")
        self.assertEqual(self.box.value_typed(), None)
        self.box.stepBy(1)
        self.assertEqual(self.box.text(), "2")

    def test_what_is_typed_stands_as_typed(self):
        self.box.lineEdit().setText("99x")
        self.box.setFocus()
        self.box.clearFocus()
        self.assertEqual(self.box.text(), "99x")

    def test_an_arrow_says_it_moved_the_days(self):
        heard = []
        self.box.stepped.connect(lambda: heard.append(1))
        self.box.show_days(3)
        self.assertEqual(heard, [])
        self.box.stepBy(1)
        self.assertEqual(heard, [1])


class FileDialogTest(unittest.TestCase):
    def test_the_dialog_opens_one_existing_file_and_says_what_was_chosen(self):
        seen = []

        def chosen(dialog) -> int:
            seen.append((dialog.windowTitle(), dialog.fileMode(), dialog.acceptMode(), dialog.nameFilters()))
            return 1

        with mock.patch.object(QFileDialog, "exec", chosen), \
                mock.patch.object(QFileDialog, "selectedFiles", lambda _dialog: ["C:/a/b.csv"]):
            self.assertEqual(ask_open_path(None, "One (*.csv);;Every file (*.*)"), "C:/a/b.csv")
        self.assertEqual(seen, [("Add a bill source", QFileDialog.FileMode.ExistingFile, QFileDialog.AcceptMode.AcceptOpen,
                                 ["One (*.csv)", "Every file (*.*)"])])

    def test_the_dialog_goes_once_it_has_answered(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        with mock.patch.object(QFileDialog, "exec", lambda _dialog: 0):
            ask_open_path(parent, "One (*.csv)")
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(parent.findChildren(QFileDialog), [])

    def test_a_dialog_cancelled_chooses_nothing(self):
        with mock.patch.object(QFileDialog, "exec", lambda _dialog: 0):
            self.assertEqual(ask_open_path(None, "One (*.csv)"), "")


class ShellTest(ShellCase):
    def bills(self, shell) -> BillsWindow:
        self.addCleanup(lambda: shell.bills_window and shell.bills_window.deleteLater())
        self.addCleanup(lambda: shell.bills_window and shell.bills_window.hide())
        return shell.bills_window

    def test_every_entry_opens_one_window_for_the_run(self):
        self.status()
        shell = self.open()
        shell.main.actions["bills"]()
        window = self.bills(shell)
        self.assertTrue(window.isVisible())
        window.hide()
        shell.main.actions["record"]()
        self.assertIs(shell.bills_window, window)
        self.assertTrue(window.isVisible())
        self.assertIs(window.focusWidget(), window.inputs["account"])
        labels = {action.text(): action for action in shell.tray_menu.actions()}
        window.hide()
        labels["Bills and sources"].trigger()
        self.assertTrue(window.isVisible())
        window.hide()
        labels["Record a bill"].trigger()
        self.assertTrue(window.isVisible())

    def test_the_main_window_s_button_opens_it(self):
        self.status()
        shell = self.open()
        button = next(b for b in shell.main.findChildren(QPushButton) if b.text() == "Bills")
        button.click()
        self.assertTrue(self.bills(shell).isVisible())

    def test_it_stays_on_top_with_the_main_window_whichever_is_set_first(self):
        self.status()
        shell = self.open()
        shell.main.keep_on_top.setChecked(True)
        shell._keep_on_top_changed()
        shell.open_bills()
        window = self.bills(shell)
        self.assertTrue(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        shell.main.keep_on_top.setChecked(False)
        shell._keep_on_top_changed()
        self.assertFalse(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_it_offers_the_accounts_the_status_names(self):
        self.status()
        shell = self.open()
        shell.open_bills()
        box = self.bills(shell).inputs["account"]
        self.assertEqual([box.itemText(i) for i in range(box.count())], [EMAIL_A, EMAIL_B])
        self.assertEqual(shell._known_accounts(), (EMAIL_A, EMAIL_B))

    def test_with_no_status_it_knows_no_account_and_still_opens(self):
        shell = self.open()
        self.assertEqual(shell._known_accounts(), ())
        shell.open_bills()
        self.assertTrue(self.bills(shell).isVisible())

    def test_a_change_runs_a_pass_keeping_its_words_at_the_head_of_the_status_line(self):
        self.status()
        shell = self.open()
        shell.open_bills()
        window = self.bills(shell)
        self.addCleanup(shell.background.poll)
        with mock.patch("windowtally_gui.actions_model.refresh", return_value=Outcome(True, "Refreshed in 0.1 s.")):
            window.changed(Outcome(True, "Recorded a bill."))
            self.assertEqual(shell.main.said.text(), "Recorded a bill. Reading every source…")
            for _ in range(200):
                shell.background.poll()
                if shell.main.said.text().endswith("Refreshed in 0.1 s."):
                    break
                QApplication.processEvents()
                time.sleep(0.01)
        self.assertEqual(shell.main.said.text(), "Recorded a bill. Refreshed in 0.1 s.")

    def test_a_change_of_mode_reaches_the_window(self):
        self.status()
        shell = self.open()
        shell.open_bills()
        window = self.bills(shell)
        shell.theme.apply("dark")
        self.addCleanup(shell.theme.apply, "light")
        spin()
        self.assertEqual(window.palette().window().color().name(), colours("dark")["page"])

