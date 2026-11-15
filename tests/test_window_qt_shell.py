"""The window's shell on an invented machine, headless: its start, the status it shows, its window record, hiding and
quitting, one offer on every surface, a switch, and its notices. The tray icon and the sync script are stand-ins
(``qt_support``)."""

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from qt_support import APP, StandInRun, StandInTray

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSystemTrayIcon

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, Machine, status_account, status_document,
                      status_subscription, status_window)
from windowtally.paths import MachinePaths
from windowtally_gui import instance_model, app_view, main_view
from windowtally_gui.flow_model import Done
from windowtally_gui.actions_model import Outcome
from windowtally_gui.notices_model import Notice
from windowtally_gui.app_view import App, arguments
from windowtally_gui.cards_view import Chips
from windowtally_gui.common_view import em
from windowtally_gui.tray_view import TrayUnavailable
from windowtally_gui.state_model import load_state, place_of, save_state, WindowState
from windowtally_gui.switch_model import APP as APP_CLIENT, CLI

TOOL = Path(__file__).resolve().parent.parent
ACCOUNT_C = "cccccccc-0000-4000-8000-000000000003"
ACCOUNT_D = "dddddddd-0000-4000-8000-000000000004"
ACCOUNT_E = "eeeeeeee-0000-4000-8000-000000000005"


def spin() -> None:
    APP.processEvents()


class StartTest(unittest.TestCase):
    def test_the_package_starts_this_window(self):
        from windowtally_gui import __main__
        self.assertIs(__main__.main, app_view.main)

    def test_the_start_menu_entry_is_written_or_removed_and_no_window_opens(self):
        for request in ("create", "remove"):
            with mock.patch.object(app_view.shortcut, "main", return_value=0) as entry, \
                    mock.patch.object(app_view.instance_model, "claim") as claim:
                self.assertEqual(app_view.main(["--shortcut", request]), 0)
            entry.assert_called_once_with(request)
            claim.assert_not_called()

    def test_each_root_left_out_is_this_account_s_own(self):
        own = MachinePaths(claude_home=Path("c"), desktop_data=Path("d"), data_dir=Path("e"))
        with mock.patch.object(app_view, "default_paths", return_value=own):
            self.assertEqual(app_view.machine_paths(arguments([])), own)
            self.assertEqual(app_view.machine_paths(arguments(["--tray"])), own)
            named = app_view.machine_paths(arguments(["--claude-home", "x", "--data-dir", "z"]))
        self.assertEqual(named, MachinePaths(claude_home=Path("x"), desktop_data=Path("d"), data_dir=Path("z")))

    def test_a_second_start_on_one_data_folder_asks_the_first_to_show_itself_and_opens_nothing(self):
        roots = ["--claude-home", "c", "--desktop-data", "d", "--data-dir", "e"]
        with mock.patch.object(app_view.instance_model, "claim", return_value=None), \
                mock.patch.object(app_view.instance_model, "ask_to_show") as ask, \
                mock.patch.object(app_view, "QApplication") as application:
            self.assertEqual(app_view.main(roots), 0)
        ask.assert_called_once_with(MachinePaths(claude_home=Path("c"), desktop_data=Path("d"), data_dir=Path("e")))
        application.assert_not_called()


class ShellCase(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.addCleanup(self.machine.close)
        self.paths = self.machine.paths
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.tray = StandInTray()
        StandInRun.runs, StandInRun.code, StandInRun.notes = [], 0, ()
        self.shell = None

    def tearDown(self):
        if self.shell is not None:
            self.shell.stop()
            self.shell.main.hide()
            self.shell.main.deleteLater()
            self.shell.tray_menu.deleteLater()
            spin()

    def status(self, **changes):
        now = time.time()
        accounts = [status_account(ACCOUNT_A, EMAIL_A, at=now),
                    status_account(ACCOUNT_B, EMAIL_B, at=now, desktop=False, cli=False,
                                   five_hour=status_window(resets=now + 3600, as_of=now - 60, percent=10.0))]
        accounts[1]["desktopArchived"] = True
        document = status_document(accounts, at=now, **{"syncFollows": True, "oneClickDesktop": True,
                                                        "desktopRunning": True, **changes})
        self.paths.status_file.write_text(json.dumps(document), encoding="utf-8")

    def open(self, *, hidden=False, tray=True):
        def no_tray(*_):
            raise TrayUnavailable("none here")

        self.shell = App(APP, self.paths, start_hidden=hidden, make_tray=self.tray if tray else no_tray,
                         start_sync=StandInRun)
        spin()
        return self.shell


class ShowsTest(ShellCase):
    def test_a_status_reaches_the_header_the_band_the_cards_and_the_tray_from_one_snapshot(self):
        self.status()
        shell = self.open()
        main = shell.main
        self.assertEqual(set(main.cards), {ACCOUNT_A, ACCOUNT_B})
        self.assertTrue(main.next.text().startswith("Next: "))
        self.assertIn("the CLI follows the app", main.status_line.labels[1].text())
        card = main.cards[ACCOUNT_A]
        self.assertEqual(card.windows[0].name.text(), "5-hour")
        self.assertEqual(card.windows[0].figure.text(), "82%")
        self.assertEqual(self.tray.icon.tooltip.split("\n")[0].split(" ")[0], card.label.text())
        def problems_line():
            return main.problem_count.text(), main.problem_count.isHidden(), main.problem_toggle.isHidden()

        self.assertEqual(problems_line(), ("", True, True), "no source problem: no line and no button for one")
        self.status(sourceErrors=["bills: unreadable"])
        shell._look()
        self.assertEqual(problems_line(), ("1 source problem", False, False))
        self.status()
        shell._look()
        self.assertEqual(problems_line(), ("", True, True), "the next status names none: the line goes with them")

    def test_with_no_status_the_cards_place_says_why(self):
        shell = self.open()
        self.assertIn("No status file yet", shell.main.notice.text())
        self.assertFalse(shell.main.notice.isHidden())
        self.assertEqual(shell.main.cards, {})

    def test_the_source_problems_are_counted_and_listed_behind_their_button(self):
        self.status(sourceErrors=["bills: unreadable", "ledger: locked"])
        main = self.open().main
        self.assertEqual(main.problem_count.text(), "2 source problems")
        self.assertTrue(main.problem_frame.isHidden())
        main.problem_toggle.click()
        self.assertFalse(main.problem_frame.isHidden())
        self.assertIn("• ledger: locked", main.problem_list.text())
        self.assertEqual(main.problem_toggle.text(), "Hide")

    def test_a_long_list_of_problems_scrolls_rather_than_makes_the_window_taller(self):
        self.status(sourceErrors=[f"bills: file {n} cannot be read" for n in range(80)])
        main = self.open().main
        before = main.minimumSizeHint().height()
        main.problem_toggle.click()
        spin()
        self.assertLessEqual(main.problem_frame.height(), em(main_view.PROBLEM_LINES))
        self.assertLess(main.minimumSizeHint().height(), before + em(main_view.PROBLEM_LINES) + em(1))

    def test_a_name_that_looks_like_markup_is_written_as_it_stands(self):
        self.status()
        document = json.loads(self.paths.status_file.read_text(encoding="utf-8"))
        document["accounts"][0]["label"] = "<b>Work</b>"
        self.paths.status_file.write_text(json.dumps(document), encoding="utf-8")
        card = self.open().main.cards[ACCOUNT_A]
        self.assertEqual(card.label.text(), "<b>Work</b>")
        self.assertEqual(card.label.textFormat(), Qt.TextFormat.PlainText)

    def test_cards_stand_as_many_abreast_as_the_width_holds(self):
        self.status()
        main = self.open().main
        main.resize(3000, 800)
        spin()
        self.assertEqual(main._columns, 2)
        with mock.patch.object(main_view, "em", return_value=2000):
            main._columns = 0
            main._reflow()
        self.assertEqual(main._columns, 1)
        self.assertEqual(main.cards_grid.getItemPosition(main.cards_grid.indexOf(main.cards[ACCOUNT_B]))[:2], (1, 0))

    def with_ended_plans(self, *, cards: bool = True) -> None:
        """The status with gamma, delta and epsilon after the cards, their plans ended and no client using them; with
        no ``cards``, they are the only accounts."""
        self.status()
        document = json.loads(self.paths.status_file.read_text(encoding="utf-8"))
        if not cards:
            document["accounts"] = []
        ended = {"state": "ended", "plan": None, "planName": None, "paidUntil": "2026-10-01", "daysLeft": None}
        for uuid, email in ((ACCOUNT_C, "gamma@example.com"), (ACCOUNT_D, "delta@example.com"),
                            (ACCOUNT_E, "epsilon@example.com")):
            document["accounts"].append(status_account(uuid, email, at=time.time(), desktop=False, cli=False,
                                                       plan=status_subscription(**ended)))
        self.paths.status_file.write_text(json.dumps(document), encoding="utf-8")

    def ended_places(self, main) -> list[tuple[int, int, int, int]]:
        grid = main.cards_grid
        return [grid.getItemPosition(grid.indexOf(main.ended[uuid])) for uuid in (ACCOUNT_C, ACCOUNT_D, ACCOUNT_E)]

    def test_an_ended_plan_s_line_is_a_column_wide_its_switch_button_ending_where_the_card_s_above_does(self):
        self.with_ended_plans()
        main = self.open().main
        main.resize(3000, 800)
        spin()
        self.assertEqual(main._columns, 2)
        self.assertEqual(self.ended_places(main), [(1, 0, 1, 1), (1, 1, 1, 1), (2, 0, 1, 1)],
                         "abreast as the cards stand, a column each")

        def right(widget) -> int:
            return widget.mapTo(main, widget.rect().topRight()).x()

        def shown(widget):
            return next(b for b in widget.switches.buttons.values() if not b.isHidden())

        for uuid, above in ((ACCOUNT_C, ACCOUNT_A), (ACCOUNT_D, ACCOUNT_B)):
            line, card = main.ended[uuid], main.cards[above]
            self.assertEqual((line.x(), line.width()), (card.x(), card.width()))
            self.assertLess(right(card) - right(shown(line)), em(2), "the button ends at its own column's edge")
        # beta's card, which no client uses, has the switch button the line under it lines up with.
        self.assertLess(abs(right(shown(main.ended[ACCOUNT_D])) - right(shown(main.cards[ACCOUNT_B]))), em(1))
        # A line beside one whose words wrap keeps its own height at the top of the row.
        gamma, delta = main.ended[ACCOUNT_C], main.ended[ACCOUNT_D]
        gamma.words.set("gamma", "plan ended " + "and its words run long " * 40, "")
        for _ in range(5):
            spin()
        self.assertGreater(gamma.height(), delta.height())
        self.assertEqual(delta.y(), gamma.y())

    def test_with_no_card_the_ended_plans_lines_take_the_columns(self):
        self.with_ended_plans(cards=False)
        main = self.open().main
        main.resize(3000, 800)
        spin()
        self.assertEqual(main.cards, {})
        self.assertEqual(main._columns, 3, "three lines, and room for three columns")
        self.assertEqual(self.ended_places(main), [(0, 0, 1, 1), (0, 1, 1, 1), (0, 2, 1, 1)])

    def test_a_card_whose_chips_and_words_take_two_lines_gives_each_its_height(self):
        self.status()
        main = self.open().main
        main.resize(em(68), em(40))
        spin()
        card = main.cards[ACCOUNT_A]
        with mock.patch.object(Chips, "needs", return_value=10 ** 6):
            card.heading._layout()
            for _ in range(5):
                spin()
        heading, chips, words = card.heading, card.heading.first, card.heading.labels[1]
        self.assertEqual(heading.grid.getItemPosition(heading.grid.indexOf(words))[0], 1)
        self.assertGreaterEqual(heading.height(), heading.minimumSizeHint().height())
        self.assertGreaterEqual(chips.height(), chips.minimumSizeHint().height())
        self.assertLessEqual(chips.geometry().bottom(), words.y())
        beside = main.cards[ACCOUNT_B]
        self.assertEqual((beside.y(), beside.height()), (card.y(), card.height()), "cards abreast stand level, one height")
        self.assertEqual(beside.label.parentWidget().layout().itemAtPosition(1, 0).widget().y(), heading.y(),
                         "the shorter card's lines keep to the top")

    def test_each_window_s_entry_opens_it_and_says_nothing_on_the_status_line(self):
        self.status()
        shell = self.open()
        with mock.patch.object(app_view, "HistoryWindow") as history, \
                mock.patch.object(app_view, "BillsWindow") as bills, \
                mock.patch.object(app_view, "ask_arrangement", return_value=None) as arrange, \
                mock.patch.object(app_view, "open_about") as about, \
                mock.patch.object(app_view, "set_on_top"):
            for key, opener in (("history_view", history.return_value.open), ("bills", bills.return_value.open),
                                ("record", bills.return_value.open), ("arrange", arrange), ("about", about)):
                with self.subTest(key=key):
                    opener.reset_mock()
                    shell.main.say("")
                    shell.main.actions[key]()
                    opener.assert_called_once()
                    self.assertEqual(shell.main.said.text(), "")


class RecordTest(ShellCase):
    def test_the_window_opens_at_its_remembered_place_and_keeps_it_as_window_json_holds_it(self):
        save_state(self.paths.window_state, WindowState(geometry="900x600+100+80"))
        shell = self.open()
        spin()
        self.assertEqual(shell.main.height(), 600)
        self.assertEqual(place_of(shell.state.geometry)[1], 600)
        shell._save_now()
        state, problem = load_state(self.paths.window_state)
        self.assertIsNone(problem)
        self.assertEqual(state.geometry, shell.state.geometry)

    def test_keep_on_top_is_one_state_in_the_menu_and_stands_across_starts(self):
        shell = self.open()
        self.assertFalse(shell.main.keep_on_top.isChecked())
        shell.main.keep_on_top.trigger()
        self.assertTrue(shell.main.keep_on_top.isChecked())
        shell._save_now()
        self.assertTrue(load_state(self.paths.window_state)[0].keep_on_top)
        shell.main.keep_on_top.trigger()
        self.assertFalse(shell.main.keep_on_top.isChecked())
        shell._save_now()
        self.assertFalse(load_state(self.paths.window_state)[0].keep_on_top)

    def test_the_theme_chosen_in_the_menu_shows_there_alone_and_is_kept(self):
        shell = self.open()
        shell.main.theme_actions["dark"].trigger()
        self.assertEqual([c for c, a in shell.main.theme_actions.items() if a.isChecked()], ["dark"])
        self.assertEqual(shell.theme.mode, "dark")
        shell.main.theme_actions["light"].trigger()
        self.assertEqual([c for c, a in shell.main.theme_actions.items() if a.isChecked()], ["light"])
        self.assertEqual(shell.theme.mode, "light")
        shell._save_now()
        self.assertEqual(load_state(self.paths.window_state)[0].theme, "light")

    def test_a_record_that_cannot_be_read_is_said_and_the_window_starts_afresh(self):
        self.paths.window_state.write_text("{", encoding="utf-8")
        shell = self.open()
        self.assertIn("could not be read", shell.main.said.text())


class HidingTest(ShellCase):
    def test_started_for_the_tray_the_window_stays_hidden_until_the_icon_is_clicked(self):
        shell = self.open(hidden=True)
        self.assertTrue(shell.main.isHidden())
        self.tray.icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
        self.assertFalse(shell.main.isHidden())

    def test_a_second_start_shows_the_first(self):
        shell = self.open(hidden=True)
        instance_model.ask_to_show(self.paths)
        shell._quick()
        self.assertFalse(shell.main.isHidden())
        self.assertFalse(self.paths.window_request.exists())

    def test_closing_hides_the_window_in_the_tray_while_windows_holds_the_icon(self):
        shell = self.open()
        shell.main.close()
        self.assertTrue(shell.main.isHidden())

    def test_closing_minimizes_the_window_while_the_icon_is_missing(self):
        shell = self.open()
        self.tray.held = False
        shell.main.close()
        self.assertFalse(shell.main.isHidden())
        self.assertTrue(shell.main.isMinimized())

    def test_with_no_tray_icon_the_window_shows_says_so_and_closing_quits(self):
        shell = self.open(hidden=True, tray=False)
        self.assertFalse(shell.main.isHidden())
        self.assertIn("could not be made", shell.main.said.text())
        with mock.patch.object(shell.app, "quit") as quit_app:
            shell.main.close()
        quit_app.assert_called_once()

    def test_a_quit_ends_the_event_loop_though_closing_the_window_only_hides_it(self):
        # In a process of its own: a quit asks every window to close, and only a real event loop can show one refusing.
        script = (
            "import sys, tempfile; from pathlib import Path\n"
            "sys.path[:0] = ['tests', '.']\n"
            "from qt_support import APP, StandInTray, StandInRun\n"
            "from PySide6.QtCore import QTimer\n"
            "from fixtures import Machine\n"
            "from windowtally_gui.app_view import App\n"
            "machine = Machine()\n"
            "shell = App(APP, machine.paths, start_hidden=False, make_tray=StandInTray(), start_sync=StandInRun)\n"
            "QTimer.singleShot(50, shell.quit)\n"
            "QTimer.singleShot(20000, lambda: sys.exit(9))\n"
            "print('ended', APP.exec())\n"
            "machine.close()\n")
        done = subprocess.run([sys.executable, "-c", script], cwd=TOOL, capture_output=True, text=True, timeout=60)
        self.assertIn("ended 0", done.stdout, done.stderr)

    def test_quitting_writes_the_record_and_takes_the_icon_down(self):
        shell = self.open()
        with mock.patch.object(shell.app, "quit"):
            shell._remember(load_state(self.paths.window_state)[0].__class__(keep_on_top=True))
            shell.quit()
        self.assertTrue(load_state(self.paths.window_state)[0].keep_on_top)
        self.assertFalse(self.tray.icon.shown)

    def test_an_icon_missing_is_made_again_and_a_hidden_window_shows_itself_at_the_bound(self):
        shell = self.open(hidden=True)
        self.tray.held = False
        shell._check_tray()
        shell._check_tray()
        self.assertEqual(self.tray.icon.shows, 2)
        self.assertTrue(shell.tray_watch.missing)
        shell.tray_watch.missing_since -= 3600
        shell._check_tray()
        self.assertFalse(shell.main.isHidden())
        self.assertIn("so the window shows itself", shell.main.said.text())


class OffersTest(ShellCase):
    def offers(self, menu):
        return [action.text() for action in menu.actions()]

    def test_the_cards_the_accounts_menu_and_the_tray_s_menu_offer_the_same_switches(self):
        self.status()
        shell = self.open()
        shell.main._fill_switch_menus()
        shell._fill_tray_switch_menus()
        main_offers = self.offers(shell.main.switch_menus[APP_CLIENT])
        self.assertEqual(main_offers, self.offers(shell.tray_switch_menus[APP_CLIENT]))
        self.assertEqual(len(main_offers), 1)
        self.assertIn(EMAIL_B.split("@")[0], main_offers[0])
        self.assertEqual([b.text() for b in shell.main.cards[ACCOUNT_B].switches.buttons.values() if not b.isHidden()],
                         ["Switch here"])
        self.assertEqual(self.offers(shell.main.switch_menus[CLI]), ["The CLI follows the desktop app"])

    def test_the_recommended_account_s_first_button_alone_is_the_primary(self):
        self.status(recommended={"account": ACCOUNT_B, "reason": "room left.", "reliefAt": None, "reliefExact": False})
        shell = self.open()
        button = shell.main.cards[ACCOUNT_B].switches.buttons[APP_CLIENT]
        self.assertIs(button.property("primary"), True)

    def test_the_tray_offers_a_start_of_the_desktop_app_only_while_it_is_not_running(self):
        self.status()
        shell = self.open()
        shell._fill_tray_switch_menus()
        self.assertFalse(shell._tray_start.isEnabled())
        self.status(desktopRunning=False)
        shell._look()
        shell._fill_tray_switch_menus()
        self.assertTrue(shell._tray_start.isEnabled())
        self.assertFalse(shell.main.closed_row.isHidden())


class SwitchTest(ShellCase):
    def test_a_switch_runs_the_sync_shows_progress_and_says_how_it_ended(self):
        self.status()
        shell = self.open()
        shell.main.cards[ACCOUNT_B].switches.buttons[APP_CLIENT].click()
        self.assertTrue(StandInRun.runs[0][-1] == ACCOUNT_B and "SwitchDesktop" in StandInRun.runs[0])
        self.assertFalse(shell.main.progress_row.isHidden())
        with mock.patch.object(shell, "refresh") as refresh:
            shell._quick()
        self.assertIn("Switched the desktop app", refresh.call_args.kwargs["after"].message)
        self.assertTrue(shell.main.progress_row.isHidden())

    def test_sessions_at_work_are_asked_about_and_cancel_starts_nothing(self):
        self.status(workingSessions=2)
        shell = self.open()
        with mock.patch.object(app_view, "ask_sessions", return_value="cancel") as asked:
            shell.switch_to(APP_CLIENT, ACCOUNT_B)
        self.assertEqual(asked.call_args.args[1], 2)
        self.assertEqual(StandInRun.runs, [])

    def test_no_stored_login_leads_to_how_an_account_is_added(self):
        self.status()
        shell = self.open()
        document = json.loads(self.paths.status_file.read_text(encoding="utf-8"))
        document["accounts"][1]["desktopArchived"] = False
        self.paths.status_file.write_text(json.dumps(document), encoding="utf-8")
        shell._look()
        with mock.patch.object(app_view, "ask_add_account", return_value="close") as asked:
            shell.switch_to(APP_CLIENT, ACCOUNT_B)
        self.assertIn("No stored desktop login", asked.call_args.args[1])
        self.assertEqual(StandInRun.runs, [])

    def test_a_running_cli_is_asked_about_and_declining_calls_the_switch_off(self):
        self.status(syncFollows=False)
        StandInRun.code = 4
        shell = self.open()
        shell._adopt_switches()
        shell.switch_to(CLI, ACCOUNT_B)
        with mock.patch.object(app_view, "ask_cli_idle", return_value=False) as asked:
            shell._quick()
        asked.assert_called_once()
        self.assertFalse(shell.flow.busy)

    def test_a_switch_turned_in_a_menu_stands_at_once_and_is_refused_while_one_runs(self):
        self.status()
        shell = self.open()
        shell.main.follows.trigger()
        self.assertFalse(shell.switches.follows)
        self.assertIn("Settings", StandInRun.runs[0])
        shell.main.one_click.trigger()
        self.assertTrue(shell.main.one_click.isChecked())
        self.assertIn("A switch is under way", shell.main.said.text())

    def test_a_switch_ended_with_the_window_hidden_is_answered_by_a_notification(self):
        self.status()
        shell = self.open(hidden=True)
        shell._flow_event(Done(Outcome(False, "Not done: no."), False, "app"))
        self.assertEqual(self.tray.icon.messages, [("WindowTally", "Not done: no.")])

    def test_a_start_of_the_desktop_app_shows_the_app_as_starting(self):
        self.status(desktopRunning=False)
        shell = self.open()
        shell.main.closed_row.findChildren(type(shell.main.cancel))[0].click()
        self.assertIn("StartDesktop", StandInRun.runs[0])
        self.assertEqual(shell.main.progress.text(), "Starting the desktop app…")
        self.assertTrue(shell.main.closed_row.isHidden())


class NoticesTest(ShellCase):
    NOTICES = [Notice("relief", "Room again", "alpha is usable."), Notice("problem", "A problem", "bills.")]

    def test_a_notice_goes_through_the_tray_icon(self):
        shell = self.open()
        shell._notify(self.NOTICES[:1])
        self.assertEqual(self.tray.icon.messages, [("Room again", "alpha is usable.")])

    def test_silenced_every_notice_of_a_look_goes_to_the_status_line_together(self):
        self.machine.settings({"v": 1, "silenceNotifications": True})
        shell = self.open()
        self.assertTrue(shell.main.silenced.isChecked())
        shell._notify(self.NOTICES)
        self.assertEqual(self.tray.icon.messages, [])
        self.assertEqual(shell.main.said.text(), "Room again. alpha is usable. A problem. bills.")

    def test_with_the_icon_missing_a_notice_goes_to_the_status_line(self):
        shell = self.open()
        self.tray.held = False
        shell._notify(self.NOTICES[:1])
        self.assertEqual(self.tray.icon.messages, [])
        self.assertIn("Room again", shell.main.said.text())

    def test_a_change_of_the_setting_by_hand_is_followed(self):
        shell = self.open()
        self.assertFalse(shell.main.silenced.isChecked())
        self.machine.settings({"v": 1, "silenceNotifications": True})
        shell._follow_settings()
        self.assertTrue(shell.main.silenced.isChecked())


if __name__ == "__main__":
    unittest.main()
