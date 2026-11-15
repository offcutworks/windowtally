"""The Arrange accounts window on an invented machine, headless: the list in the user's order, the moves, the names held
to WindowTally's rules as they are typed, hiding, the answer, and how the shell reaches it. The order, the names and the
writing are ``arrange_model``'s; the shell's writes go to the invented machine's settings."""

import unittest
from unittest import mock

from qt_support import APP

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from fixtures import ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, Machine
from test_window_arrange import ACCOUNT_C, EMAIL_C, three
from test_window_qt_shell import ShellCase, spin
from windowtally.settings import Settings, load_settings
from windowtally_gui import actions_model, app_view, arrange_view
from windowtally_gui.actions_model import Outcome
from windowtally_gui.arrange_model import Arrangement
from windowtally_gui.arrange_view import (COLUMNS, HIDDEN_HINT, MOST_ROWS, ORDER_HINT, ArrangeWindow, ask_arrangement)
from windowtally_gui.common_view import Hint
from windowtally_gui.theme_view import Theme


def press(widget, key=Qt.Key.Key_Return) -> None:
    APP.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


class WindowCase(unittest.TestCase):
    def setUp(self):
        self.theme = Theme(APP, "light")
        self.saved: list[Arrangement] = []
        self.answer = Outcome(True, "Accounts saved.")

    def save(self, arrangement: Arrangement) -> Outcome:
        self.saved.append(arrangement)
        return self.answer

    def open(self, order=(), names=None, hidden=()) -> ArrangeWindow:
        settings = Settings(account_order=tuple(order), account_names=tuple((names or {}).items()),
                            hidden_accounts=tuple(hidden))
        window = ArrangeWindow(None, self.theme, Arrangement.of(three(), settings), self.save)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.hide)
        return window

    def rows(self, window: ArrangeWindow) -> list[list[str]]:
        tree = window.tree
        return [[tree.topLevelItem(r).text(c) for c in range(tree.columnCount())] for r in range(tree.topLevelItemCount())]

    def names(self, window: ArrangeWindow) -> list[str]:
        return [row[0] for row in self.rows(window)]

    def choose(self, window: ArrangeWindow, uuid: str) -> None:
        window.tree.setCurrentItem(window.tree.item_of(uuid))


class ListTest(WindowCase):
    def test_the_accounts_stand_in_the_user_s_order_each_with_its_name_e_mail_and_state(self):
        window = self.open(order=(ACCOUNT_C, ACCOUNT_A, ACCOUNT_B), names={ACCOUNT_A: "Work"}, hidden=(ACCOUNT_B,))
        self.assertEqual(self.rows(window), [["gamma", EMAIL_C, "shown"], ["Work", EMAIL_A, "shown"],
                                             ["beta", EMAIL_B, "hidden"]])

    def test_the_first_account_opens_selected_and_the_list_has_the_focus(self):
        window = self.open()
        self.assertEqual(window.selected, window.arrangement.rows[0].uuid)
        self.assertIs(window.focusWidget(), window.tree)
        self.assertEqual(window.default.text(), f"default: {window.arrangement.rows[0].default}")

    def test_the_list_shows_at_least_three_rows_and_at_most_ten(self):
        window = self.open()
        self.assertEqual(window.tree.rows_shown, 3)
        self.assertEqual(MOST_ROWS, 10)
        self.assertEqual([c[1] for c in COLUMNS], ["Name", "E-mail", "In lists"])

    def test_the_order_s_and_the_hiding_s_hints_stand_on_the_pointer_and_on_the_focus(self):
        window = self.open()
        for widget, words in ((window.up, ORDER_HINT), (window.down, ORDER_HINT), (window.listed, HIDDEN_HINT)):
            self.assertEqual([(h.text, h.focus) for h in widget.findChildren(Hint)], [(words, True)])
        self.assertEqual([(h.text, h.focus) for h in window.by_name.findChildren(Hint)],
                         [("Default order, by name", False)])

    def test_the_window_keeps_to_its_content_and_stays_on_top(self):
        window = self.open()
        self.assertTrue(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        window.show()
        spin()
        height = window.height()
        window.problem.setText("A refusal long enough to take a line and then another line of the window's words, "
                               "so the window must find room for it under the name.")
        spin()
        self.assertGreater(window.height(), height)


class MovesTest(WindowCase):
    def test_up_and_down_move_the_selected_account_and_it_stays_selected(self):
        window = self.open(order=(ACCOUNT_A, ACCOUNT_B, ACCOUNT_C))
        self.choose(window, ACCOUNT_B)
        window.up.click()
        self.assertEqual(self.names(window), ["beta", "alpha", "gamma"])
        self.assertEqual(window.tree.key_chosen(), ACCOUNT_B)
        window.down.click()
        window.down.click()
        self.assertEqual(self.names(window), ["alpha", "gamma", "beta"])
        self.assertEqual(window.selected, ACCOUNT_B)

    def test_each_end_of_the_list_closes_its_button(self):
        window = self.open(order=(ACCOUNT_A, ACCOUNT_B, ACCOUNT_C))
        self.choose(window, ACCOUNT_A)
        self.assertFalse(window.up.isEnabled())
        self.assertTrue(window.down.isEnabled())
        self.choose(window, ACCOUNT_C)
        self.assertTrue(window.up.isEnabled())
        self.assertFalse(window.down.isEnabled())

    def test_by_name_puts_every_account_back_and_waits_while_the_order_is_that(self):
        window = self.open(order=(ACCOUNT_C, ACCOUNT_B, ACCOUNT_A))
        self.assertTrue(window.by_name.isEnabled())
        window.by_name.click()
        self.assertEqual(self.names(window), ["alpha", "beta", "gamma"])
        self.assertFalse(window.by_name.isEnabled())
        self.assertEqual(window.arrangement.order(), ())

    def test_a_button_that_reaches_its_end_hands_the_focus_to_the_list_and_return_from_there_is_ok(self):
        window = self.open(order=(ACCOUNT_A, ACCOUNT_B, ACCOUNT_C))
        window.show()
        window.activateWindow()
        spin()
        self.choose(window, ACCOUNT_B)
        window.up.setFocus()
        spin()
        window.up.click()
        spin()
        self.assertFalse(window.up.isEnabled())
        self.assertIs(window.focusWidget(), window.tree)
        press(window.focusWidget())
        self.assertEqual(len(self.saved), 1)


class NameTest(WindowCase):
    def test_a_usable_name_follows_in_the_list_as_it_is_typed(self):
        window = self.open(order=(ACCOUNT_A, ACCOUNT_B, ACCOUNT_C))
        self.choose(window, ACCOUNT_A)
        window.name.setText("Work")
        self.assertEqual(self.names(window)[0], "Work")
        self.assertEqual(window.problem.text(), "")
        window.name.setText("")
        self.assertEqual(self.names(window)[0], "alpha")

    def test_a_name_refused_is_said_ok_waits_and_the_selection_stays(self):
        window = self.open(order=(ACCOUNT_A, ACCOUNT_B, ACCOUNT_C))
        self.choose(window, ACCOUNT_A)
        window.name.setText("beta")
        self.assertEqual(window.problem.text(), f"Not usable: another account ({EMAIL_B}) is shown as beta.")
        self.assertEqual(window.problem.property("ink"), "critical-text")
        self.assertEqual(self.names(window)[0], "alpha")
        self.assertFalse(window.ok.isEnabled())
        with mock.patch.object(QApplication, "beep") as beep:
            self.choose(window, ACCOUNT_C)
        beep.assert_called_once()
        self.assertEqual(window.tree.key_chosen(), ACCOUNT_A)
        window._ok()
        self.assertEqual(self.saved, [])
        window.name.setText("Work")
        self.assertTrue(window.ok.isEnabled())
        self.choose(window, ACCOUNT_C)
        self.assertEqual(window.selected, ACCOUNT_C)

    def test_a_name_longer_than_a_field_is_refused_in_windowtally_s_words(self):
        window = self.open()
        window.name.setText("x" * 40)
        self.assertTrue(window.problem.text().startswith("Not usable: "))


class HidingTest(WindowCase):
    def test_the_check_box_hides_the_selected_account_and_the_list_says_so(self):
        window = self.open(order=(ACCOUNT_A, ACCOUNT_B, ACCOUNT_C))
        self.choose(window, ACCOUNT_B)
        self.assertTrue(window.listed.isChecked())
        window.listed.click()
        self.assertEqual(self.rows(window)[1][2], "hidden")
        self.assertEqual(window.arrangement.hidden(), (ACCOUNT_B,))
        self.choose(window, ACCOUNT_A)
        self.assertTrue(window.listed.isChecked())
        self.choose(window, ACCOUNT_B)
        self.assertFalse(window.listed.isChecked())
        window.listed.click()
        self.assertEqual(self.rows(window)[1][2], "shown")

    def test_with_nothing_selected_the_field_and_the_box_wait(self):
        window = self.open()
        window.tree.clearSelection()
        self.assertIsNone(window.selected)
        self.assertFalse(window.name.isEnabled())
        self.assertFalse(window.listed.isEnabled())
        self.assertFalse(window.up.isEnabled())
        self.assertEqual(window.default.text(), "")


class AnswerTest(WindowCase):
    def test_ok_with_nothing_changed_closes_writing_nothing(self):
        window = self.open()
        window.show()
        window.ok.click()
        self.assertEqual(self.saved, [])
        self.assertIsNone(window.outcome)
        self.assertFalse(window.isVisible())

    def test_ok_writes_and_closes_with_what_it_did(self):
        window = self.open(order=(ACCOUNT_A, ACCOUNT_B, ACCOUNT_C))
        window.show()
        self.choose(window, ACCOUNT_B)
        window.up.click()
        window.ok.click()
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(window.outcome, self.answer)
        self.assertFalse(window.isVisible())

    def test_a_write_refused_is_said_and_the_window_stays_with_what_was_arranged(self):
        window = self.open(order=(ACCOUNT_A, ACCOUNT_B, ACCOUNT_C))
        window.show()
        self.choose(window, ACCOUNT_B)
        window.up.click()
        self.answer = Outcome(False, "Not changed: settings.json changed meanwhile.")
        window.ok.click()
        self.assertEqual(window.problem.text(), self.answer.message)
        self.assertTrue(window.isVisible())
        self.assertIsNone(window.outcome)
        self.assertEqual(self.names(window), ["beta", "alpha", "gamma"])

    def test_cancel_and_escape_leave_everything(self):
        for leave in (lambda w: w.cancel.click(), lambda w: press(w, Qt.Key.Key_Escape), lambda w: w.close()):
            window = self.open(order=(ACCOUNT_A, ACCOUNT_B, ACCOUNT_C))
            window.show()
            self.choose(window, ACCOUNT_B)
            window.up.click()
            leave(window)
            self.assertFalse(window.isVisible())
            self.assertIsNone(window.outcome)
        self.assertEqual(self.saved, [])

    def test_return_on_a_button_presses_it_and_from_elsewhere_is_ok(self):
        window = self.open(order=(ACCOUNT_A, ACCOUNT_B, ACCOUNT_C))
        window.show()
        self.choose(window, ACCOUNT_B)
        press(window.cancel)
        self.assertFalse(window.isVisible())
        self.assertEqual(self.saved, [])
        window = self.open(order=(ACCOUNT_A, ACCOUNT_B, ACCOUNT_C))
        window.show()
        self.choose(window, ACCOUNT_B)
        press(window.up)
        self.assertEqual(self.names(window), ["beta", "alpha", "gamma"])
        self.assertTrue(window.isVisible())
        press(window.name)
        self.assertEqual(len(self.saved), 1)
        self.assertFalse(window.isVisible())

    def test_return_waits_while_a_name_cannot_be_used(self):
        window = self.open(order=(ACCOUNT_A, ACCOUNT_B, ACCOUNT_C))
        window.show()
        self.choose(window, ACCOUNT_A)
        window.name.setText("beta")
        press(window.name)
        self.assertEqual(self.saved, [])
        self.assertTrue(window.isVisible())


class ThroughTheSettingsTest(WindowCase):
    def setUp(self):
        super().setUp()
        self.machine = Machine()
        self.addCleanup(self.machine.close)
        self.paths = self.machine.paths
        self.machine.settings({"v": 1})

    def real(self) -> ArrangeWindow:
        arrangement = actions_model.arrangement(self.paths, three())
        window = ArrangeWindow(None, self.theme, arrangement, lambda a: actions_model.set_arrangement(self.paths, a))
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.hide)
        window.show()
        return window

    def test_the_arrangement_written_is_what_the_settings_hold(self):
        window = self.real()
        self.choose(window, ACCOUNT_C)
        window.up.click()
        window.name.setText("Spare")
        window.listed.click()
        window.ok.click()
        self.assertEqual(window.outcome, Outcome(True, "Accounts saved."))
        settings = load_settings(self.paths.settings_file)
        self.assertEqual(settings.account_order, (ACCOUNT_A, ACCOUNT_C, ACCOUNT_B))
        self.assertEqual(settings.names, {ACCOUNT_C: "Spare"})
        self.assertEqual(settings.hidden_accounts, (ACCOUNT_C,))

    def test_a_change_by_hand_meanwhile_is_undone_only_after_the_window_has_said_so(self):
        window = self.real()
        self.choose(window, ACCOUNT_A)
        window.name.setText("Mine")
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_A: "Theirs"}})
        window.ok.click()
        self.assertTrue(window.isVisible())
        self.assertIn("settings.json changed meanwhile", window.problem.text())
        self.assertIn("OK again overwrites it", window.problem.text())
        self.assertEqual(load_settings(self.paths.settings_file).names, {ACCOUNT_A: "Theirs"})
        window.ok.click()
        self.assertFalse(window.isVisible())
        self.assertEqual(load_settings(self.paths.settings_file).names, {ACCOUNT_A: "Mine"})


class AskTest(WindowCase):
    def arrangement(self) -> Arrangement:
        return Arrangement.of(three(), Settings())

    def test_with_the_main_window_hidden_it_has_no_window_to_be_modal_to(self):
        hidden = arrange_view.QWidget()
        self.addCleanup(hidden.deleteLater)
        with mock.patch.object(ArrangeWindow, "exec") as run, \
                mock.patch.object(arrange_view, "ArrangeWindow", wraps=ArrangeWindow) as made:
            ask_arrangement(hidden, self.theme, self.arrangement(), self.save)
        self.assertIsNone(made.call_args.args[0])
        run.assert_called_once()

    def test_over_the_main_window_it_is_that_window_s(self):
        shown = arrange_view.QWidget()
        self.addCleanup(shown.deleteLater)
        self.addCleanup(shown.hide)
        shown.show()
        with mock.patch.object(ArrangeWindow, "exec"), \
                mock.patch.object(arrange_view, "ArrangeWindow", wraps=ArrangeWindow) as made:
            ask_arrangement(shown, self.theme, self.arrangement(), self.save)
        self.assertIs(made.call_args.args[0], shown)

    def test_it_answers_what_the_window_ended_with(self):
        def ends(window) -> None:
            window.outcome = self.answer

        with mock.patch.object(ArrangeWindow, "exec", ends):
            self.assertEqual(ask_arrangement(None, self.theme, self.arrangement(), self.save), self.answer)
        with mock.patch.object(ArrangeWindow, "exec"):
            self.assertIsNone(ask_arrangement(None, self.theme, self.arrangement(), self.save))


class ShellTest(ShellCase):
    def test_with_no_account_known_it_says_so(self):
        shell = self.open()
        with mock.patch.object(app_view, "ask_arrangement") as asked:
            shell.main.actions["arrange"]()
        asked.assert_not_called()
        self.assertEqual(shell.main.said.text(), "No account is known yet, so there is none to arrange.")

    def test_settings_that_cannot_be_read_are_not_arranged_over(self):
        self.status()
        self.paths.settings_file.write_text("{ not json", encoding="utf-8")
        shell = self.open()
        with mock.patch.object(app_view, "ask_arrangement") as asked:
            shell.main.actions["arrange"]()
        asked.assert_not_called()
        self.assertTrue(shell.main.said.text().startswith("Cannot arrange the accounts: "))
        self.assertEqual(shell.main.said.property("ink"), "critical-text")

    def test_the_menu_and_the_tray_open_it_and_nothing_written_runs_no_pass(self):
        self.status()
        shell = self.open()
        labels = {action.text(): action for action in shell.tray_menu.actions()}
        with mock.patch.object(app_view, "ask_arrangement", return_value=None) as asked, \
                mock.patch.object(shell, "refresh") as refresh:
            shell.main.actions["arrange"]()
            labels["Arrange accounts…"].trigger()
        self.assertEqual(asked.call_count, 2)
        self.assertEqual({r.uuid for r in asked.call_args.args[2].rows}, {ACCOUNT_A, ACCOUNT_B})
        refresh.assert_not_called()

    def test_a_save_runs_a_pass_with_its_words_ahead(self):
        self.status()
        shell = self.open()
        saved = Outcome(True, "Accounts saved.")
        with mock.patch.object(app_view, "ask_arrangement", return_value=saved), \
                mock.patch.object(shell, "refresh") as refresh:
            shell.arrange_accounts()
        refresh.assert_called_once_with(after=saved)

