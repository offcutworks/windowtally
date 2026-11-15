"""A switch of the desktop app that carries sessions of the account it leaves to the account switched to: the rows it
offers, the links that open them, the flow that hands them on, the dialog that asks, and the window that does it all.
The tray icon, the sync script and the shell's opener of links are stand-ins (``qt_support``)."""

import json
import os
import time
import unittest
from unittest import mock

from qt_support import APP, StandInRun, StandInTray

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QKeySequence, QPainter, QPalette, QShortcut

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, Machine, assistant_lines, register_session,
                      status_account, status_document, status_window)
from test_sessions import RESETS, stop_line, title_line
from windowtally.attribution import attribute
from windowtally.ingest_sync import ingest_sync_events
from windowtally.ingest_transcripts import ingest_transcripts
from windowtally.ledger import Ledger
from windowtally.sessions import SessionLine
from windowtally_gui import app_view, carry_model
from windowtally_gui.actions_model import Outcome
from windowtally_gui.app_view import App
from windowtally_gui.carry_model import JUST_USED, CarryRow, LinkQueue, carry_rows, ran_with, resume_link
from windowtally_gui.common_view import TickDelegate, draw_tick_box, size_to_content
from windowtally_gui.flow_model import Done, OpenSessions, SwitchFlow
from windowtally_gui.switch_model import APP as APP_CLIENT, CLI as CLI_CLIENT
from windowtally_gui.switch_view import BACKGROUND_NOTE, CARRY_NOTE, CarryDialog
from windowtally_gui.sync_model import Result
from windowtally_gui.theme_model import colours, contrast
from windowtally_gui.theme_view import Theme

NOW = 1_800_000_000.0


def line(session_id, last, *, title=None, stop=None, project="D:\\Work\\Project", unfinished=0, effort=None, mode=None):
    return SessionLine(session_id, title, project, last, stop, RESETS if stop else None, unfinished, effort, mode)


class RowsTest(unittest.TestCase):
    def test_the_stopped_come_first_then_the_working_then_the_rest_ticked_only_where_just_used(self):
        lines = [line("idle-new", NOW - 60, title="Newest idle"), line("working", NOW - 120, title="At work"),
                 line("stopped-old", NOW - 3600, title="Stopped long ago", stop="seven_day"),
                 line("stopped-new", NOW - 300, title="Stopped lately", stop="five_hour"),
                 line("idle-old", NOW - 7200, title="Oldest idle")]
        rows = carry_rows(lines, frozenset({"working"}), NOW)
        self.assertEqual([(r.session_id, r.state, r.ticked) for r in rows], [
            ("stopped-new", "Stopped by the 5-hour limit", True), ("stopped-old", "Stopped by the weekly limit", True),
            ("working", "Working", True), ("idle-new", "", True), ("idle-old", "", False)],
            "the idle a minute old within JUST_USED of the switch, the one two hours old outside it")
        self.assertEqual([r.last for r in rows], ["5m ago", "1h 00m ago", "now", "1m ago", "2h 00m ago"])

    def test_a_working_session_stopped_before_is_working_and_one_the_ledger_lacks_is_listed_as_at_work(self):
        rows = carry_rows([line("again", NOW - 30, title="Again", stop="five_hour")], frozenset({"again", "fresh"}),
                          NOW)
        self.assertEqual([(r.session_id, r.title, r.state) for r in rows],
                         [("fresh", "Untitled session", "Working"), ("again", "Again", "Working")],
                         "the one the ledger lacks is at work now, the latest activity of the two")

    def test_a_session_with_no_title_is_named_by_its_folder_and_a_stop_of_no_known_window_says_so(self):
        [row] = carry_rows([line("s1", NOW - 60, stop="", project="D:\\Work\\Parser")], frozenset(), NOW)
        self.assertEqual((row.title, row.state), ("Untitled session in Parser", "Stopped by a limit"))
        [row] = carry_rows([line("s2", NOW - 60, project=None)], frozenset(), NOW)
        self.assertEqual(row.title, "Untitled session")

    def test_the_link_names_the_session_by_its_id(self):
        self.assertEqual(resume_link("0b4c-11"), "claude://resume?session=0b4c-11")
        self.assertEqual(resume_link("a b&c"), "claude://resume?session=a%20b%26c")

    def test_an_idle_session_used_just_before_the_switch_is_ticked_and_an_older_one_is_not(self):
        self.assertEqual(JUST_USED, 900.0)
        lines = [line("minute", NOW - 60), line("edge", NOW - JUST_USED), line("past", NOW - JUST_USED - 1),
                 line("hours", NOW - 7200)]
        rows = carry_rows(lines, frozenset(), NOW)
        self.assertEqual([(r.session_id, r.state, r.ticked) for r in rows],
                         [("minute", "", True), ("edge", "", True), ("past", "", False), ("hours", "", False)])

    def test_what_was_just_used_is_counted_from_when_the_switch_was_asked_for(self):
        lines = [line("waited", NOW - JUST_USED - 30)]
        self.assertEqual([r.ticked for r in carry_rows(lines, frozenset(), NOW)], [False])
        [row] = carry_rows(lines, frozenset(), NOW, asked=NOW - 60)
        self.assertEqual((row.ticked, row.last), (True, "15m ago"), "ticked by the asking, its age by the clock")

    def test_a_session_with_background_work_unfinished_stands_after_the_working_and_is_ticked_however_old(self):
        lines = [line("idle-new", NOW - 60), line("at-work", NOW - 120, unfinished=1),
                 line("left", NOW - 3 * 3600, title="Long run", unfinished=2),
                 line("stopped", NOW - 4 * 3600, stop="five_hour", unfinished=1), line("idle-old", NOW - 5 * 3600)]
        rows = carry_rows(lines, frozenset({"at-work"}), NOW)
        self.assertEqual([(r.session_id, r.state, r.ticked) for r in rows], [
            ("stopped", "Stopped by the 5-hour limit", True), ("at-work", "Working", True),
            ("left", "Background work unfinished", True), ("idle-new", "", True), ("idle-old", "", False)])
        self.assertEqual(carry_model.UNFINISHED, "Background work unfinished")
        self.assertEqual([r.background for r in rows], [True, True, True, False, False],
                         "whatever its state says first")

    def test_each_row_says_what_its_session_ran_with_and_one_the_ledger_lacks_says_nothing(self):
        lines = [line("stopped", NOW - 300, stop="five_hour", effort="max", mode="auto"),
                 line("left", NOW - 3600, unfinished=1, mode="plan"), line("idle", NOW - 60, effort="xhigh"),
                 line("unknown", NOW - 7200)]
        rows = carry_rows(lines, frozenset({"fresh"}), NOW)
        self.assertEqual({r.session_id: r.ran_with for r in rows},
                         {"stopped": "max · Auto", "fresh": "", "left": "Plan", "idle": "xhigh", "unknown": ""})


class RanWithTest(unittest.TestCase):
    def test_the_effort_then_the_mode_in_the_apps_words_either_alone_or_nothing(self):
        self.assertEqual(ran_with("max", "auto"), "max · Auto")
        self.assertEqual(ran_with("xhigh", "acceptEdits"), "xhigh · Accept edits")
        self.assertEqual(ran_with("low", "bypassPermissions"), "low · Bypass permissions")
        self.assertEqual((ran_with(None, "default"), ran_with(None, "manual")), ("Manual", "Manual"))
        self.assertEqual((ran_with(None, "plan"), ran_with(None, "dontAsk")), ("Plan", "Don't ask"))
        self.assertEqual((ran_with("high", None), ran_with(None, None), ran_with("", "")), ("high", "", ""))

    def test_an_effort_or_a_mode_of_other_letters_is_shown_as_written_and_one_of_anything_else_not_at_all(self):
        self.assertEqual(ran_with("max", "someNewMode"), "max · someNewMode")
        self.assertEqual(ran_with("ultra", "auto"), "ultra · Auto")
        self.assertEqual(ran_with("max", "<b>auto</b>"), "max")
        self.assertEqual(ran_with("<b>max</b>", "auto"), "Auto")
        self.assertEqual(ran_with(None, "x" * 33), "")
        self.assertEqual(ran_with("x" * 33, None), "")


class LinkQueueTest(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.opened = []

    def queue(self, opener=None):
        return LinkQueue(opener or self.opened.append, clock=lambda: self.now, gap=2.0)

    def test_the_links_open_one_at_a_time_the_gap_apart_the_first_a_gap_after_they_are_added(self):
        links = self.queue()
        links.add((("s1", "One"), ("s2", "Two")))
        self.assertEqual((links.pending, links.progress_words()), (2, "Opening 2 sessions in the desktop app…"))
        self.assertEqual(links.tick(101.9), [])
        self.assertEqual(self.opened, [])
        links.tick(102.0)
        self.assertEqual(self.opened, ["claude://resume?session=s1"])
        links.tick(103.0)
        self.assertEqual(len(self.opened), 1, "not before the gap")
        links.tick(104.0)
        self.assertEqual(self.opened, ["claude://resume?session=s1", "claude://resume?session=s2"])
        self.assertEqual((links.pending, links.progress_words()), (0, None))

    def test_a_link_the_shell_cannot_open_is_answered_and_the_rest_go_on(self):
        def refuse(link):
            if link.endswith("s1"):
                raise OSError("no application is associated")
            self.opened.append(link)

        links = self.queue(refuse)
        links.add((("s1", "One"), ("s2", "Two")))
        self.assertEqual(links.tick(102.0), [carry_model.Failure("One", "no application is associated")])
        self.assertEqual(links.tick(104.0), [])
        self.assertEqual(self.opened, ["claude://resume?session=s2"])


class EndingRun:
    """A run of the sync script that ends with ``result`` at its first poll, and can be called off until then."""

    def __init__(self, result: Result):
        self.result, self.cancelled = result, False
        self.closing = self.starting = self.saving = False

    def poll(self):
        return self.result

    def cancel(self) -> bool:
        self.cancelled, self.result = True, Result(1, ())
        return True


class CarryFlowTest(unittest.TestCase):
    CARRY = (("s1", "One"), ("s2", "Two"))

    def setUp(self):
        self.machine = Machine()
        self.results: list[Result] = []

    def tearDown(self):
        self.machine.close()

    def flow(self) -> SwitchFlow:
        return SwitchFlow(self.machine.paths, sessions=lambda: 0,
                          start=lambda argv: EndingRun(self.results.pop(0) if self.results else Result(0, ())),
                          clock=lambda: 0.0)

    def test_a_switch_done_says_it_opens_the_sessions_and_hands_them_on(self):
        flow = self.flow()
        flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False, carry=self.CARRY)
        done, opened = flow.tick()
        self.assertEqual(done, Done(Outcome(True, "Switched the desktop app to beta. The CLI follows it as soon as no "
                                                  "CLI is running. Opening 2 sessions there: set the permission mode "
                                                  "and effort again in each."), True))
        self.assertEqual(opened, OpenSessions(self.CARRY, "beta"))

    def test_a_switch_that_leaves_the_app_signed_out_opens_none_and_says_so(self):
        self.results = [Result(5, ("Switched the desktop app to beta, but the app refused the login stored for it.",))]
        flow = self.flow()
        flow.switch_app(ACCOUNT_B, "beta", follows=False, wait=False, carry=self.CARRY[:1])
        [done] = flow.tick()
        self.assertEqual(done, Done(Outcome(False, "Switched the desktop app to beta, but the app refused the login "
                                                   "stored for it. The 1 session chosen was not opened."), True))

    def test_a_switch_not_made_or_called_off_hands_on_nothing(self):
        self.results = [Result(2, ("Refused: the desktop app refused to close. Nothing was changed.",))]
        flow = self.flow()
        flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False, carry=self.CARRY)
        self.assertEqual([type(event) for event in flow.tick()], [Done])
        flow = self.flow()
        flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False, carry=self.CARRY)
        self.assertTrue(flow.cancel())
        self.assertEqual([event.outcome.message for event in flow.tick()], ["Cancelled; nothing was changed."])


ROWS = (CarryRow("s1", "Stopped lately", "Stopped by the 5-hour limit", "5m ago", True),
        CarryRow("s2", "Idle one", "", "1h 00m ago", False))


class CarryDialogTest(unittest.TestCase):
    def dialog(self, at_work=0, rows=ROWS):
        window = CarryDialog(None, "alpha", "beta", rows, at_work)
        self.addCleanup(window.deleteLater)
        return window

    def test_it_names_the_account_switched_to_lists_the_sessions_and_says_what_the_link_leaves_behind(self):
        window = self.dialog()
        self.assertIn("beta", window.windowTitle())
        self.assertIn("from alpha to beta", window.lead.text())
        items = [window.list.topLevelItem(i) for i in range(window.list.topLevelItemCount())]
        self.assertEqual([[item.text(c) for c in range(3)] for item in items],
                         [["Stopped lately", "Stopped by the 5-hour limit", "5m ago"], ["Idle one", "", "1h 00m ago"]])
        self.assertEqual([item.checkState(0) for item in items], [Qt.CheckState.Checked, Qt.CheckState.Unchecked])
        self.assertEqual(window.note.text(), CARRY_NOTE)
        self.assertIn("permission mode and effort", CARRY_NOTE)
        self.assertIsNone(window.working)

    def test_with_nothing_working_it_offers_switch_and_cancel_and_switch_carries_the_ticked(self):
        window = self.dialog()
        self.assertEqual([b.text() for b in window.buttons.values()], ["Switch", "Cancel"])
        self.assertTrue(window.buttons["now"].isDefault())
        window.list.item_of("s2").setCheckState(0, Qt.CheckState.Checked)
        window.list.item_of("s1").setCheckState(0, Qt.CheckState.Unchecked)
        window.buttons["now"].click()
        self.assertEqual((window.answer, window.chosen), ("now", ("s2",)))

    def test_while_sessions_work_it_says_so_and_waiting_is_the_default(self):
        window = self.dialog(at_work=2)
        self.assertEqual([b.text() for b in window.buttons.values()], ["Wait and switch", "Switch", "Cancel"])
        self.assertTrue(window.buttons["wait"].isDefault())
        self.assertIn("2 Code sessions are working", window.working.text())
        window.buttons["wait"].click()
        self.assertEqual((window.answer, window.chosen), ("wait", ("s1",)))

    def test_cancel_escape_or_closing_carries_nothing(self):
        window = self.dialog()
        window.buttons["cancel"].click()
        self.assertEqual((window.answer, window.chosen), ("cancel", ()))
        window = self.dialog()
        window.show()
        APP.sendEvent(window, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertEqual((window.answer, window.chosen), ("cancel", ()))

    def test_where_a_sessions_background_work_is_unfinished_it_says_the_work_is_run_again(self):
        left = CarryRow("s3", "Long run", carry_model.UNFINISHED, "3h 00m ago", True, True)
        window = self.dialog(rows=ROWS + (left,))
        self.assertEqual(window.note.text(), CARRY_NOTE + " " + BACKGROUND_NOTE)
        self.assertIn("run again", BACKGROUND_NOTE)
        self.assertEqual(window.list.item_of("s3").text(1), "Background work unfinished")
        self.assertEqual(window.ticked(), ("s1", "s3"))
        stopped = CarryRow("s4", "Stopped mid-run", "Stopped by the weekly limit", "2h 00m ago", True, True)
        self.assertEqual(self.dialog(rows=(stopped,)).note.text(), CARRY_NOTE + " " + BACKGROUND_NOTE,
                         "said for a session a limit stopped too")

    def test_space_ticks_the_session_chosen(self):
        window = self.dialog()
        window.show()
        window.list.setFocus()
        window.list.setCurrentItem(window.list.item_of("s2"))
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            APP.sendEvent(window.list, QKeyEvent(kind, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " "))
        self.assertEqual(window.ticked(), ("s1", "s2"))

    def test_opened_as_the_window_opens_it_the_list_shows_whole_every_row_it_asks_for(self):
        for count, at_work in ((1, 1), (2, 1), (2, 0), (3, 0), (3, 1), (5, 1), (8, 1)):
            with self.subTest(count=count, at_work=at_work):
                rows = tuple(CarryRow(f"s{i}", f"Session {i}", "", "5m ago", i < 2, False, "max · Auto")
                             for i in range(count))
                window = self.dialog(at_work=at_work, rows=rows)
                size_to_content(window)
                window.show()
                APP.processEvents()
                listed = window.list
                view = listed.viewport().height()
                whole = sum(listed.visualItemRect(listed.topLevelItem(i)).bottom() < view for i in range(count))
                window.hide()
                self.assertEqual(whole, min(count, listed.rows_shown))

    def test_each_session_says_what_it_ran_with_and_the_note_points_there(self):
        rows = (CarryRow("s1", "Refactor the parser", "", "5m ago", True, False, "max · Auto"),
                CarryRow("s2", "Lexer tests", "", "1h 00m ago", False))
        window = self.dialog(rows=rows)
        self.assertEqual(window.list.headerItem().text(3), "Ran with")
        self.assertEqual([window.list.item_of(key).text(3) for key in ("s1", "s2")], ["max · Auto", ""])
        self.assertEqual(window.list.item_of("s1").toolTip(3), "max · Auto")
        self.assertIn("as Ran with shows", window.note.text())

    def test_the_search_keeps_the_sessions_whose_title_holds_every_word_and_a_hidden_tick_is_still_carried(self):
        rows = (CarryRow("s1", "Refactor the parser", "", "5m ago", True),
                CarryRow("s2", "Lexer tests", "", "10m ago", True),
                CarryRow("s3", "Parser tests", "", "1h 00m ago", False))
        window = self.dialog(rows=rows)
        self.assertEqual(window.count.text(), "3 sessions · 2 ticked")
        window.search.setText("PARSER")
        self.assertEqual(window.shown_keys(), ["s1", "s3"])
        self.assertEqual(window.count.text(), "2 of 3 sessions · 2 ticked")
        window.search.setText("parser  tests")
        self.assertEqual(window.shown_keys(), ["s3"])
        self.assertIs(window.list.currentItem(), window.list.item_of("s3"), "a session shown is chosen")
        window.list.item_of("s3").setCheckState(0, Qt.CheckState.Checked)
        self.assertEqual(window.count.text(), "1 of 3 sessions · 3 ticked")
        window.buttons["now"].click()
        self.assertEqual((window.answer, window.chosen), ("now", ("s1", "s2", "s3")), "the hidden ticks are carried")

    def test_a_search_that_keeps_none_chooses_none_so_space_ticks_nothing_out_of_sight(self):
        window = self.dialog()
        window.show()
        window.search.setText("nothing like it")
        self.assertEqual((window.shown_keys(), window.count.text()), ([], "0 of 2 sessions · 1 ticked"))
        self.assertIsNone(window.list.currentItem())
        window.list.setFocus()
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            APP.sendEvent(window.list, QKeyEvent(kind, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " "))
        self.assertEqual(window.ticked(), ("s1",))
        window.search.clear()
        self.assertEqual(window.shown_keys(), ["s1", "s2"])

    def test_return_in_the_search_goes_to_the_list_and_presses_no_button_and_ctrl_f_goes_back(self):
        window = self.dialog()
        window.show()
        window.search.setFocus()
        window.search.setText("idle")
        self.assertIs(window.list.currentItem(), window.list.item_of("s2"))
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            APP.sendEvent(window.search, QKeyEvent(kind, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
            APP.sendEvent(window.search, QKeyEvent(kind, Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier))
        self.assertEqual((window.answer, window.result(), window.isVisible()), ("cancel", 0, True),
                         "the default button was not pressed")
        self.assertIs(window.focusWidget(), window.list)
        self.assertIs(window.list.currentItem(), window.list.item_of("s2"))
        [find] = [s for s in window.findChildren(QShortcut) if s.key() == QKeySequence("Ctrl+F")]
        find.activated.emit()
        self.assertIs(window.focusWidget(), window.search)


class TickBoxTest(unittest.TestCase):
    """A list's tick box, which the window draws itself from the palette's roles, in both modes."""

    PAIRS = ((QPalette.ColorRole.Accent, "focus"), (QPalette.ColorRole.Base, "field"),
             (QPalette.ColorRole.PlaceholderText, "muted"))

    def setUp(self):
        self.theme = Theme(APP, "light")
        self.addCleanup(self.theme.apply, "light")

    def drawn(self, ticked: bool) -> list[str]:
        """The colours of a box drawn alone, one for each pixel of the square it is drawn in."""
        image = QImage(16, 16, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ff00ff"))
        painter = QPainter(image)
        draw_tick_box(painter, QRect(0, 0, 16, 16), APP.palette(), ticked)
        painter.end()
        return [image.pixelColor(x, y).name() for y in range(16) for x in range(16)]

    def test_a_ticked_box_is_filled_under_a_tick_and_an_unticked_one_is_an_empty_box_in_both_modes(self):
        for mode in ("light", "dark"):
            with self.subTest(mode=mode):
                self.theme.apply(mode)
                c = colours(mode)
                for role, name in self.PAIRS:
                    self.assertEqual(APP.palette().color(role).name(), c[name], (mode, name))
                ticked, empty = self.drawn(True), self.drawn(False)
                self.assertGreater(ticked.count(c["focus"]), 100, "filled with the accent")
                nearer_field = [p for p in ticked if p not in (c["focus"], "#ff00ff")
                                and contrast(p, c["focus"]) > contrast(p, c["field"])]
                self.assertGreaterEqual(len(nearer_field), 8, "a tick in the field's colour stands on the fill")
                self.assertEqual(empty.count(c["focus"]), 0)
                self.assertGreater(empty.count(c["field"]), 100, "empty inside")
                self.assertGreater(empty.count(c["muted"]), 30, "edged")

    def test_each_part_of_a_box_stands_out_at_three_to_one_on_every_ground_a_row_has(self):
        for mode in ("light", "dark"):
            c = colours(mode)
            self.assertGreaterEqual(contrast(c["field"], c["focus"]), 3.0, (mode, "the tick on its fill"))
            for ground in ("field", "hover", "selection"):
                self.assertGreaterEqual(contrast(c["focus"], c[ground]), 3.0, (mode, ground, "a ticked box"))
                self.assertGreaterEqual(contrast(c["muted"], c[ground]), 3.0, (mode, ground, "an unticked box's edge"))

    def test_the_switch_dialog_shows_which_sessions_are_ticked_in_both_modes(self):
        for mode in ("light", "dark"):
            with self.subTest(mode=mode):
                self.theme.apply(mode)
                accent = colours(mode)["focus"]
                window = CarryDialog(None, "alpha", "beta", ROWS + (CarryRow("s3", "Used lately", "", "2m ago", True),),
                                     0)
                self.addCleanup(window.deleteLater)
                self.assertIsInstance(window.list.itemDelegate(), TickDelegate)
                window.show()
                found = {}
                for key in ("s1", "s2", "s3"):
                    item = window.list.item_of(key)
                    window.list.scrollToItem(item)     # the offscreen platform's list shows one row at a time
                    APP.processEvents()
                    image = window.list.viewport().grab().toImage()
                    scale = image.devicePixelRatio()
                    row = window.list.visualItemRect(item).intersected(window.list.viewport().rect())
                    self.assertGreaterEqual(row.height(), 16, key)
                    found[key] = sum(image.pixelColor(int(x * scale), int(y * scale)).name() == accent
                                     for x in range(row.left(), row.right() + 1)
                                     for y in range(row.top(), row.bottom() + 1))
                window.hide()
                self.assertGreater(found["s1"], 30, "ticked and chosen")
                self.assertEqual(found["s2"], 0, "not ticked")
                self.assertGreater(found["s3"], 30, "ticked and not chosen")


def spin() -> None:
    APP.processEvents()


class CarryShellTest(unittest.TestCase):
    """Alpha's app, with a session a limit stopped and an idle one, switched to beta."""

    def setUp(self):
        self.machine = Machine()
        self.addCleanup(self.machine.close)
        self.paths = self.machine.paths
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.tray = StandInTray()
        StandInRun.runs, StandInRun.code, StandInRun.notes = [], 0, ()
        self.opened: list[str] = []
        self.shell = None
        now = time.time()
        self.machine.sync_events([(now - 7200, "desktop_account", ACCOUNT_A)])
        self.machine.transcript("stopped", [title_line("stopped", "Stopped lately")]
                                + assistant_lines("m1", now - 900, "stopped")
                                + [stop_line("stopped", now - 600, "u1", resets=now + 3600)])
        self.machine.transcript("idle", [title_line("idle", "Idle one")] + assistant_lines("m2", now - 1200, "idle"))
        ledger = Ledger.open(self.paths.ledger_db)
        try:
            ingest_transcripts(ledger, self.paths.projects_dir)
            ingest_sync_events(ledger, self.paths.sync_events)
            attribute(ledger)
        finally:
            ledger.close()
        accounts = [status_account(ACCOUNT_A, EMAIL_A, at=now),
                    status_account(ACCOUNT_B, EMAIL_B, at=now, desktop=False, cli=False,
                                   five_hour=status_window(resets=now + 3600, as_of=now - 60, percent=10.0))]
        accounts[1]["desktopArchived"] = True
        self.paths.status_file.write_text(json.dumps(status_document(
            accounts, at=now, syncFollows=True, oneClickDesktop=True, desktopRunning=True)), encoding="utf-8")

    def tearDown(self):
        if self.shell is not None:
            self.shell.stop()
            self.shell.main.hide()
            self.shell.main.deleteLater()
            self.shell.tray_menu.deleteLater()
            spin()

    def open(self, hidden=False):
        self.shell = App(APP, self.paths, start_hidden=hidden, make_tray=self.tray, start_sync=StandInRun,
                         open_links=self.opened.append)
        spin()
        return self.shell

    def status_changed(self, written: float) -> None:
        """A session whose status in Claude Code's session registry last changed at ``written``, its turn over."""
        register_session(self.paths.claude_home, "stopped", status="idle", changed=written)

    def open_all(self, shell) -> None:
        deadline = time.monotonic() + 60
        while shell.links.pending:
            shell.links.tick(time.monotonic() + 3600)
            self.assertLess(time.monotonic(), deadline)

    def test_the_sessions_offered_are_alphas_and_those_chosen_open_on_beta_once_the_switch_is_done(self):
        shell = self.open()
        with mock.patch.object(app_view, "ask_carry", return_value=("now", ("stopped",))) as asked:
            shell.switch_to(APP_CLIENT, ACCOUNT_B)
        left, to, rows, at_work = asked.call_args.args[1:]
        self.assertEqual((left, to, at_work), ("alpha", "beta", 0))
        self.assertEqual([(r.session_id, r.title, r.state, r.ticked) for r in rows],
                         [("stopped", "Stopped lately", "Stopped by the 5-hour limit", True),
                          ("idle", "Idle one", "", False)])
        self.assertIn("SwitchDesktop", StandInRun.runs[0])
        with mock.patch.object(shell, "refresh") as refresh:
            shell._quick()
        self.assertIn("Opening 1 session there", refresh.call_args.kwargs["after"].message)
        self.assertEqual(shell.links.pending, 1)
        self.assertEqual(shell.main.progress.text(), "Opening 1 session in the desktop app…")
        self.assertIn("A switch is already under way", self.refused_while(shell))
        self.open_all(shell)
        self.assertEqual(self.opened, ["claude://resume?session=stopped"])

    def refused_while(self, shell) -> str:
        shell.main.say("")
        shell.switch_to(APP_CLIENT, ACCOUNT_B)
        return shell.main.said.text()

    def test_cancel_in_the_dialog_starts_nothing(self):
        shell = self.open()
        with mock.patch.object(app_view, "ask_carry", return_value=("cancel", ())):
            shell.switch_to(APP_CLIENT, ACCOUNT_B)
        self.assertEqual(StandInRun.runs, [])

    def test_a_link_the_shell_cannot_open_is_said_on_the_status_line(self):
        shell = self.open()

        def refuse(_link):
            raise OSError("no application is associated")

        shell.links.open_link, shell.links.gap = refuse, 0.0
        with mock.patch.object(app_view, "ask_carry", return_value=("now", ("stopped",))):
            shell.switch_to(APP_CLIENT, ACCOUNT_B)
        with mock.patch.object(shell, "refresh"):
            shell._quick()
            shell._quick()
        self.assertEqual(shell.main.said.text(),
                         "Not opened in the desktop app: Stopped lately (no application is associated).")
        self.assertEqual(shell.links.pending, 0)

    def test_a_status_changed_since_the_last_pass_has_a_pass_run_first_and_cancel_calls_the_switch_off(self):
        self.status_changed(time.time() + 5)
        shell = self.open()
        started = []

        def start(name, _job, deliver, _failed):
            started.append((name, deliver))
            return True

        with mock.patch.object(shell.background, "start", side_effect=start), \
                mock.patch.object(app_view, "ask_carry") as asked:
            shell.switch_to(APP_CLIENT, ACCOUNT_B)
            self.assertEqual([name for name, _deliver in started], ["pass"])
            asked.assert_not_called()
            self.assertEqual(shell.main.progress.text(),
                             "Reading the sessions of alpha before switching the desktop app to beta…")
            self.assertIn("A switch is already under way", self.refused_while(shell))
            shell.cancel_switch()
            started[0][1](Outcome(True, "Read every source in 1.0 s."))
            asked.assert_not_called()
        self.assertEqual(StandInRun.runs, [])
        self.assertEqual(shell.main.said.text(), "Cancelled; nothing was changed.")

    def read_pending(self, shell):
        """Starts a switch whose pass before it is held, as though still running: what it delivers is returned."""
        started = []

        def start(name, _job, deliver, _failed):
            started.append(deliver)
            return True

        self.status_changed(time.time() + 5)
        with mock.patch.object(shell.background, "start", side_effect=start):
            shell.switch_to(APP_CLIENT, ACCOUNT_B)
        self.assertEqual(len(started), 1)
        return started[0]

    def test_the_rows_are_given_the_moment_the_switch_was_asked_for_not_the_end_of_the_pass_before_it(self):
        shell = self.open()
        before = time.time()
        delivered = self.read_pending(shell)
        after = time.time()
        with mock.patch.object(app_view, "carry_rows", wraps=carry_rows) as built, \
                mock.patch.object(app_view, "ask_carry", return_value=("cancel", ())):
            delivered(Outcome(True, "Read every source in 1.0 s."))
        asked = built.call_args.kwargs["asked"]
        self.assertTrue(before <= asked <= after, (before, asked, after))

    def test_while_the_sessions_are_read_no_other_job_of_the_sync_begins(self):
        shell = self.open()
        self.read_pending(shell)
        shell.main.say("")
        shell.start_desktop()
        self.assertIn("A switch is already under way", shell.main.said.text())
        shell.main.one_click.trigger()
        self.assertIn("A switch is under way", shell.main.said.text())
        self.assertTrue(shell.main.one_click.isChecked(), "the switch turned is put back")
        self.assertEqual(StandInRun.runs, [])

    def test_a_job_that_began_meanwhile_is_said_and_the_switch_is_not_made_without_a_word(self):
        shell = self.open()
        delivered = self.read_pending(shell)
        self.assertTrue(shell.flow.set_switch(follows=False), "a job the window did not guard against")
        with mock.patch.object(app_view, "ask_carry", return_value=("now", ("stopped",))):
            delivered(Outcome(True, "Read every source in 1.0 s."))
        self.assertEqual(len(StandInRun.runs), 1)
        self.assertNotIn("SwitchDesktop", StandInRun.runs[0])
        self.assertIn("Not switched: another of the account sync's jobs began meanwhile", shell.main.said.text())
        self.assertEqual(shell.links.pending, 0)

    def test_while_the_sessions_carried_are_opened_the_cli_may_switch_and_the_app_may_not(self):
        document = json.loads(self.paths.status_file.read_text(encoding="utf-8"))
        document["syncFollows"] = False
        self.paths.status_file.write_text(json.dumps(document), encoding="utf-8")
        shell = self.open()
        shell._adopt_switches()
        with mock.patch.object(app_view, "ask_carry", return_value=("now", ("stopped",))):
            shell.switch_to(APP_CLIENT, ACCOUNT_B)
        with mock.patch.object(shell, "refresh"):
            shell._quick()
        self.assertEqual(shell.links.pending, 1)
        self.assertIn("A switch is already under way", self.refused_while(shell))
        shell.switch_to(CLI_CLIENT, ACCOUNT_B)
        self.assertIn("SwitchCli", StandInRun.runs[-1])
        self.assertEqual(shell.links.pending, 1)

    def test_once_the_pass_before_the_switch_ends_the_sessions_are_offered(self):
        self.status_changed(time.time() + 5)
        shell = self.open()
        with mock.patch.object(app_view.actions_model, "read_sources",
                               return_value=Outcome(True, "Read every source in 1.0 s.")), \
                mock.patch.object(shell, "refresh"), \
                mock.patch.object(app_view, "ask_carry", return_value=("now", ())) as asked:
            shell.switch_to(APP_CLIENT, ACCOUNT_B)
            deadline = time.monotonic() + 30
            while not asked.called and time.monotonic() < deadline:
                shell._quick()
                time.sleep(0.02)
        asked.assert_called_once()
        self.assertIn("SwitchDesktop", StandInRun.runs[0])

    def test_a_switch_from_the_app_at_its_sign_in_page_offers_nothing(self):
        document = json.loads(self.paths.status_file.read_text(encoding="utf-8"))
        document.update(desktopAccount=None, desktopSignedIn=False)
        document["accounts"][0]["isDesktop"] = False
        self.paths.status_file.write_text(json.dumps(document), encoding="utf-8")
        shell = self.open()
        with mock.patch.object(app_view, "ask_carry") as asked:
            shell.switch_to(APP_CLIENT, ACCOUNT_B)
        asked.assert_not_called()
        self.assertIn("SwitchDesktop", StandInRun.runs[0])


if __name__ == "__main__":
    unittest.main()
