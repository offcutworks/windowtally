"""The Conversations window: every account's sessions read off the window's thread and listed, searched and filtered;
the line naming the account a session opens on; Open session handing a session to the desktop app and Copy resume
command giving the terminal's command; and the three places the main window opens it from. The tray icon, the sync
script and the shell's opener of links are stand-ins (``qt_support``)."""

import json
import time
import unittest
from unittest import mock

from qt_support import APP, StandInRun, StandInTray

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QPushButton

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, status_account,
                      status_document)
from test_conversations import in_folder
from test_sessions import prompt_line, stop_line, title_line
from windowtally.service import run_pass
from windowtally_gui import app_view
from windowtally_gui.app_view import App
from windowtally_gui.background import Background
from windowtally_gui.conversations_model import NOT_RUNNING, SWITCHING
from windowtally_gui.conversations_view import ConversationsWindow
from windowtally_gui.status_model import parse_status
from windowtally_gui.theme_view import Theme


def spin() -> None:
    APP.processEvents()


class Seeded(unittest.TestCase):
    """Alpha's app until an hour ago, then beta's: four sessions, one of the CLI alone, one a limit stopped."""

    def setUp(self):
        self.machine = Machine()
        self.addCleanup(self.machine.close)
        self.paths = self.machine.paths
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        now = self.now = time.time()
        self.folder = self.paths.claude_home.parent / "Parser"
        self.folder.mkdir()
        lexing = self.paths.claude_home.parent / "Lexer"
        lexing.mkdir()
        self.machine.sync_events([(now - 7200, "desktop_account", ACCOUNT_A), (now - 7200, "cli_account", ACCOUNT_A),
                                  (now - 3600, "desktop_account", ACCOUNT_B), (now - 3600, "cli_account", ACCOUNT_B)])
        self.machine.transcript("parser", [title_line("parser", "Refactor the parser")]
                                + in_folder(assistant_lines("m1", now - 5400, "parser"), str(self.folder)))
        self.machine.transcript("lexer", [title_line("lexer", "Lexer tests")]
                                + in_folder(assistant_lines("m2", now - 4800, "lexer"), str(lexing)))
        self.machine.transcript("terminal", [title_line("terminal", "Terminal work")]
                                + assistant_lines("m3", now - 1200, "terminal", entrypoint="cli"))
        self.machine.transcript("waiting", [title_line("waiting", "Waiting on the week")]
                                + assistant_lines("m4", now - 900, "waiting")
                                + [stop_line("waiting", now - 600, "u1", kind="seven_day", resets=now + 86400)])
        run_pass(self.paths, dashboard=False)
        self.write_status()

    def write_status(self, **changes):
        accounts = [status_account(ACCOUNT_B, EMAIL_B, at=self.now), status_account(ACCOUNT_A, EMAIL_A, at=self.now,
                                                                                    desktop=False, cli=False)]
        document = status_document(accounts, at=self.now, **{"syncFollows": True, "oneClickDesktop": True,
                                                             "desktopRunning": True, **changes})
        self.paths.status_file.write_text(json.dumps(document), encoding="utf-8")
        return parse_status(json.loads(json.dumps(document)))


class WindowTest(Seeded):
    def setUp(self):
        super().setUp()
        self.status = self.write_status()
        self.busy = False
        self.at_work: frozenset = frozenset()
        self.opened: list[str] = []
        self.work = Background()
        self.window = ConversationsWindow(Theme(APP, "light"), self.paths, self.work, lambda: self.status,
                                          lambda: self.busy, lambda: self.at_work, self.opened.append)
        self.addCleanup(self.window.deleteLater)

    def read(self):
        """Opens the window and waits for its read of the sessions to be shown."""
        self.window.open()
        deadline = time.monotonic() + 30
        while self.window.refresh.running:
            self.work.poll()
            spin()
            time.sleep(0.01)
            self.assertLess(time.monotonic(), deadline)
        spin()

    def cells(self):
        listed = self.window.list
        return [[listed.topLevelItem(i).text(c) for c in range(5)] for i in range(listed.topLevelItemCount())
                if not listed.topLevelItem(i).isHidden()]

    def test_it_lists_every_accounts_sessions_the_latest_first_with_their_first_five_columns(self):
        self.assertEqual(self.window.count.text(), "Not read")
        self.read()
        rows = self.cells()
        self.assertEqual([r[0] for r in rows], ["Waiting on the week", "Terminal work", "Lexer tests",
                                                "Refactor the parser"])
        self.assertEqual([r[1:3] for r in rows], [["Project", "beta"], ["Project", "beta"], ["Lexer", "alpha"],
                                                  ["Parser", "alpha"]])
        self.assertTrue(all(r[3].endswith("ago") and r[4].startswith("$") for r in rows))
        self.assertEqual(self.window.count.text(), "4 sessions")
        self.assertEqual([self.window.accounts.itemText(i) for i in range(self.window.accounts.count())],
                         ["All accounts", "alpha", "beta"])
        self.assertEqual([self.window.projects.itemText(i) for i in range(self.window.projects.count())],
                         ["All projects", "Lexer", "Parser", "Project"])
        parser = self.window.list.item_of("parser")
        self.assertEqual(parser.toolTip(1), str(self.folder))
        self.assertEqual(self.window.list.key_chosen(), "waiting", "the first session is chosen")

    def test_the_search_and_the_filters_narrow_the_list_and_keep_a_session_chosen(self):
        self.read()
        self.window.search.setText("PARSER refactor")
        self.assertEqual([r[0] for r in self.cells()], ["Refactor the parser"])
        self.assertEqual(self.window.count.text(), "1 of 4 sessions")
        self.assertEqual(self.window.list.key_chosen(), "parser")
        self.window.search.clear()
        self.window.accounts.setCurrentIndex(self.window.accounts.findText("beta"))
        self.window.accounts.activated.emit(self.window.accounts.currentIndex())
        self.assertEqual([r[0] for r in self.cells()], ["Waiting on the week", "Terminal work"])
        self.window.projects.setCurrentIndex(self.window.projects.findText("Parser"))
        self.window.projects.activated.emit(self.window.projects.currentIndex())
        self.assertEqual(self.cells(), [])
        self.assertIsNone(self.window.list.key_chosen())
        self.assertFalse(self.window.open_button.isEnabled())

    def test_a_read_again_keeps_the_search_the_filters_and_the_session_chosen(self):
        self.read()
        self.window.projects.setCurrentIndex(self.window.projects.findText("Project"))
        self.window.projects.activated.emit(self.window.projects.currentIndex())
        self.window.list.setCurrentItem(self.window.list.item_of("terminal"))
        self.read()
        self.assertEqual(self.window.projects.currentText(), "Project")
        self.assertEqual(self.window.list.key_chosen(), "terminal")
        self.assertEqual(len(self.cells()), 2)

    def test_open_session_hands_the_session_chosen_to_the_desktop_app(self):
        self.read()
        self.window.list.setCurrentItem(self.window.list.item_of("lexer"))
        self.assertEqual(self.window.line.text(), "A session opens on beta, in the desktop app or with the resume "
                                                  "command.")
        self.assertTrue(self.window.open_button.isEnabled())
        self.window.open_button.click()
        self.assertEqual(self.opened, ["claude://resume?session=lexer"])
        self.assertEqual(self.window.said.text(), "Handed to the desktop app: Lexer tests. The app does not keep its "
                                                  "effort and may not keep its permission mode: it ran with xhigh.")

    def test_a_double_click_or_return_on_a_session_opens_it_and_return_in_the_search_only_goes_to_the_list(self):
        self.read()
        item = self.window.list.item_of("lexer")
        self.window.list.setCurrentItem(item)
        self.window.list.itemActivated.emit(item, 0)
        self.assertEqual(self.opened, ["claude://resume?session=lexer"])
        self.window.search.setText("parser")
        self.window.list.clearSelection()
        self.window.search.returnPressed.emit()
        self.assertEqual(self.opened, ["claude://resume?session=lexer"], "a search opens nothing by itself")
        self.assertEqual(self.window.list.key_chosen(), "parser")

    def test_the_ages_are_written_again_between_reads_and_the_sessions_at_work_read_once_a_second(self):
        self.read()
        now = time.time()
        self.window.clock = lambda: now + 2 * 3600
        read = []
        self.window.working = lambda: read.append(1) or frozenset()
        self.window._working = None
        self.window.tick()
        self.assertEqual(self.window.list.item_of("waiting").text(3), "2h 10m ago")
        for _ in range(5):
            self.window.show_line()
        self.assertEqual(len(read), 1)

    def test_a_link_the_shell_cannot_hand_on_is_said(self):
        def refuse(_link):
            raise OSError("no application is associated")

        self.window.open_link = refuse
        self.read()
        self.window.open_button.click()
        self.assertEqual(self.window.said.text(),
                         "Not opened in the desktop app: Waiting on the week (no application is associated).")

    def test_a_session_of_the_cli_alone_and_an_app_not_running_or_switching_open_nothing_there(self):
        self.read()
        self.window.list.setCurrentItem(self.window.list.item_of("terminal"))
        self.assertFalse(self.window.open_button.isEnabled())
        self.assertTrue(self.window.copy_button.isEnabled())
        self.assertIn("The CLI alone ran it", self.window.line.text())
        self.window.open_session()
        self.assertEqual(self.opened, [])
        self.window.list.setCurrentItem(self.window.list.item_of("lexer"))
        self.busy = True
        self.window.show_line()
        self.assertTrue(self.window.line.text().startswith(SWITCHING))
        self.assertFalse(self.window.open_button.isEnabled())
        self.busy = False
        self.status = self.write_status(desktopRunning=False)
        self.window.show_line()
        self.assertTrue(self.window.line.text().startswith(NOT_RUNNING))
        self.window.open_session()
        self.assertEqual(self.opened, [])

    def test_copy_resume_command_gives_the_command_and_a_working_session_gets_none(self):
        self.read()
        self.window.list.setCurrentItem(self.window.list.item_of("parser"))
        self.window.copy_button.click()
        quoted = str(self.folder).replace("'", "''")
        self.assertEqual(QGuiApplication.clipboard().text(),
                         f"Set-Location -LiteralPath '{quoted}'; claude --resume parser --effort xhigh",
                         "its answers ran at xhigh, and no transcript line named a permission mode")
        self.assertIn("paste it into PowerShell", self.window.said.text())
        self.at_work = frozenset({"parser"})
        self.window._working = None   # the reading of the sessions at work a second ago has run out
        self.window.show_line()
        self.assertFalse(self.window.copy_button.isEnabled())
        self.assertTrue(self.window.open_button.isEnabled(), "the app shows a session it is running")

    def test_ran_with_says_what_a_session_ran_with_and_the_command_and_the_handing_over_carry_it(self):
        self.machine.transcript("parser", [prompt_line("parser", "p9", self.now - 300, "acceptEdits")], append=True)
        run_pass(self.paths, dashboard=False)
        self.read()
        self.assertEqual(self.window.list.headerItem().text(5), "Ran with")
        self.assertEqual([self.window.list.item_of(key).text(5) for key in ("parser", "terminal")],
                         ["xhigh · Accept edits", "xhigh"])
        self.window.list.setCurrentItem(self.window.list.item_of("parser"))
        self.window.copy_button.click()
        quoted = str(self.folder).replace("'", "''")
        self.assertEqual(QGuiApplication.clipboard().text(), f"Set-Location -LiteralPath '{quoted}'; claude --resume "
                                                             "parser --effort xhigh --permission-mode acceptEdits")
        self.window.open_button.click()
        self.assertEqual(self.opened, ["claude://resume?session=parser"])
        self.assertEqual(self.window.said.text(), "Handed to the desktop app: Refactor the parser. The app does not "
                                                  "keep its effort and may not keep its permission mode: it ran with "
                                                  "xhigh · Accept edits.")

    def test_a_stopped_session_says_which_limit_stopped_it(self):
        self.read()
        self.window.list.setCurrentItem(self.window.list.item_of("waiting"))
        self.assertIn("Stopped by the weekly limit.", self.window.line.text())

    def test_with_no_ledger_the_read_says_why_and_a_read_that_works_clears_it(self):
        ledger = self.paths.ledger_db
        hidden = ledger.with_name("elsewhere.sqlite3")
        ledger.rename(hidden)
        self.read()
        self.assertIn("there is no ledger yet", self.window.said.text())
        self.assertEqual(self.window.count.text(), "Not read")
        hidden.rename(ledger)
        self.read()
        self.assertTrue(self.window.said.isHidden())
        self.assertEqual(self.window.count.text(), "4 sessions")

    def test_escape_hides_the_window(self):
        self.read()
        APP.sendEvent(self.window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        spin()
        self.assertFalse(self.window.isVisible())


class ShellTest(Seeded):
    def setUp(self):
        super().setUp()
        self.tray = StandInTray()
        StandInRun.runs, StandInRun.code, StandInRun.notes = [], 0, ()
        self.opened: list[str] = []
        self.shell = App(APP, self.paths, start_hidden=False, make_tray=self.tray, start_sync=StandInRun,
                         open_links=self.opened.append)
        spin()

    def tearDown(self):
        self.shell.stop()
        if self.shell.conversations_window is not None:
            self.shell.conversations_window.hide()
            self.shell.conversations_window.deleteLater()
        self.shell.main.hide()
        self.shell.main.deleteLater()
        self.shell.tray_menu.deleteLater()
        spin()

    def read(self):
        window = self.shell.conversations_window
        deadline = time.monotonic() + 30
        while window.refresh.running:
            self.shell._quick()
            time.sleep(0.01)
            self.assertLess(time.monotonic(), deadline)

    def entries(self):
        main = self.shell.main
        button = next(b for b in main.findChildren(QPushButton) if b.text() == "Conversations")
        file_menu = main.menuBar().actions()[0].menu()
        entry = next(a for a in file_menu.actions() if a.text() == "Show the conversations")
        tray = next(a for a in self.shell.tray_menu.actions() if a.text() == "Conversations")
        return button, entry, tray

    def test_the_button_the_file_menu_and_the_tray_menu_open_it(self):
        button, entry, tray = self.entries()
        with mock.patch.object(app_view, "set_on_top"):
            for opener in (button.click, entry.trigger, tray.trigger):
                with self.subTest(opener=opener):
                    window = self.shell.conversations_window
                    if window is not None:
                        window.hide()
                    opener()
                    self.assertTrue(self.shell.conversations_window.isVisible())
        self.assertEqual(self.shell.main.said.text(), "")

    def test_it_opens_the_session_through_the_shell_and_holds_while_a_switch_is_prepared(self):
        self.shell.open_conversations()
        self.read()
        window = self.shell.conversations_window
        window.list.setCurrentItem(window.list.item_of("lexer"))
        self.shell._choosing = True
        self.shell.render()
        self.assertFalse(window.open_button.isEnabled())
        self.shell._choosing = False
        self.shell.render()
        window.open_button.click()
        self.assertEqual(self.opened, ["claude://resume?session=lexer"])

    def test_keep_on_top_reaches_it_and_a_new_status_reads_the_sessions_again(self):
        self.shell.open_conversations()
        self.read()
        with mock.patch.object(app_view, "set_on_top") as on_top:
            self.shell.main.keep_on_top.trigger()
        self.assertIn(self.shell.conversations_window, [call.args[0] for call in on_top.call_args_list])
        self.now += 5
        self.write_status()
        with mock.patch.object(self.shell.conversations_window, "recompute") as recompute:
            self.shell._look()
        recompute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
