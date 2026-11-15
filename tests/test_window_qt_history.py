"""The History window on an invented machine, headless: what it shows, its spans and their computation, its export,
its charts and tables and the wheel over them, and how the shell reaches it. The history is computed by the code the
page uses too; the save dialog and the browser are stand-ins, so no test shows a dialog or opens a page."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from qt_support import APP, StandInRun, StandInTray

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QWheelEvent
from PySide6.QtWidgets import QFileDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bill, bridge_line,
                      laid_out, status_account, status_document)
from windowtally import history
from windowtally.dashboard import render_history
from windowtally.history import TABLE_ROWS
from windowtally.service import run_pass
from windowtally_gui import history_model, common_view, history_view, plot_view, table_view
from windowtally_gui.background import Background
from windowtally_gui.history_model import Bullets, Chart, Heading, Note, Switch, Table, Tiles
from windowtally_gui.plot_model import ColumnPlot, ColumnStack, LinePlot, Marker, Series
from windowtally_gui.app_view import App
from windowtally_gui.common_view import ScrollFrame, Tip, em
from windowtally_gui.history_view import HINT_WIDTH, HistoryWindow, TilesView, ask_save_path
from windowtally_gui.plot_view import ChartView, LegendView
from windowtally_gui.table_view import TableView
from windowtally_gui.theme_view import Theme
from windowtally_gui.scroll_model import NOTCH
from windowtally_gui.theme_model import colours

NOW = time.time()
DAY = 86400.0


def spin() -> None:
    APP.processEvents()


def until(condition, patience: float = 5.0) -> bool:
    """Runs the event loop until ``condition()`` holds, for at most ``patience`` seconds; whether it held."""
    end = time.monotonic() + patience
    while not condition() and time.monotonic() < end:
        spin()
        time.sleep(0.002)
    return condition()


class Lane:
    """The history's lane with the computation held until a test lets it end, so nothing races a thread. It answers
    every call the window and the shell make of a lane, the shell's quick clock polling it too."""

    def __init__(self):
        self.jobs = []

    @property
    def running(self):
        return "history" if self.jobs else None

    def start(self, _name, job, deliver, failed):
        if self.jobs:
            return False
        self.jobs.append((job, deliver, failed))
        return True

    def poll(self):
        """Hands on nothing: a job here ends only when the test calls ``finish``."""

    def finish(self):
        job, deliver, failed = self.jobs.pop(0)
        try:
            result = job()
        except Exception as exc:
            failed(exc)
        else:
            deliver(result)


def seeded() -> Machine:
    machine = Machine()
    machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
    machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
    machine.app_history([(NOW - 20 * DAY + i * 3 * 3600, org, 30.0, (i % 50) * 1.8)
                         for i in range(150) for org in (ORG_A, ORG_B)])
    events = []
    for day in range(20):
        session = f"s{day}"
        owner = ACCOUNT_A if day % 2 else ACCOUNT_B
        answered = NOW - (20 - day) * DAY + 600
        events.append((answered - 60, "desktop_account", owner))
        machine.transcript(session, [bridge_line(session, owner, ORG_A)]
                           + assistant_lines(f"m{day}", answered, session))
    machine.sync_events(events)
    today = time.strftime("%Y-%m-%d", time.gmtime(NOW))
    machine.bills_file([bill(EMAIL_A, today, 90.0, plan="max5x", period=f"{today}..2099-01-01")])
    run_pass(machine.paths, now=NOW)
    return machine


class WindowCase(unittest.TestCase):
    """One machine for the class; a window for each test, on a lane the test ends by hand."""

    @classmethod
    def setUpClass(cls):
        cls.machine = seeded()
        cls.theme = Theme(APP, "light")
        cls.errors = ()

    @classmethod
    def tearDownClass(cls):
        cls.machine.close()

    def setUp(self):
        self.theme.apply("light")
        self.lane = Lane()
        self.chosen, self.opened = [], []
        self.answer = ""

    def window(self, paths=None) -> HistoryWindow:
        def choose(_parent, folder, name):
            self.chosen.append((folder, name))
            return self.answer

        window = HistoryWindow(self.theme, paths or self.machine.paths, lambda: self.errors, self.lane,
                               choose_file=choose, open_url=self.opened.append)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.hide)
        return window

    def shown(self, key: str = "30d") -> HistoryWindow:
        window = self.window()
        window.open()
        if key != "30d":
            window.span_buttons[key].click()
            self.lane.finish()
        self.lane.finish()
        spin()
        return window

    @staticmethod
    def texts(window: HistoryWindow) -> list[str]:
        layout = window.column
        found = []
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if isinstance(widget, QLabel):
                found.append(widget.text())
            elif widget is not None and type(widget) is QWidget:
                found += [label.text() for label in widget.findChildren(QLabel)]
        return found

    def blocks(self, window: HistoryWindow):
        return history_model.blocks(window.shown_history)


class ShowsTest(WindowCase):
    def test_on_opening_the_content_s_place_says_it_is_computing_and_the_line_names_the_span(self):
        window = self.window()
        window.open()
        self.assertEqual(self.texts(window), ["Computing…"])
        self.assertEqual(window.status.text(), "Computing 30 days…")
        self.assertTrue(window.span_buttons["30d"].isChecked())
        self.assertEqual(window.windowTitle(), "WindowTally — history")

    def test_every_heading_note_and_bullet_stands_in_the_history_page_s_order(self):
        window = self.shown()
        expected = []
        for block in self.blocks(window):
            if isinstance(block, Heading):
                expected.append(block.text)
                if block.hint:
                    expected.append("?")
            elif isinstance(block, Note):
                expected.append(block.text)
            elif isinstance(block, Bullets):
                expected += [f"• {item}" for item in block.items]
        self.assertEqual(self.texts(window), expected)

    def test_each_span_shows_the_blocks_its_history_gives(self):
        for key in ("7d", "6mo", "all"):
            window = self.shown(key)
            self.assertEqual(window.shown_history.span.key, key)
            blocks = self.blocks(window)
            switches = [b for b in blocks if isinstance(b, Switch)]
            self.assertEqual(len(window.charts), sum(isinstance(b, Chart) for b in blocks))
            self.assertEqual([len(s.charts) for s in window.switches],
                             [sum(isinstance(b, Chart) for b in s.views[s.shown].blocks) for s in switches],
                             "a switch's charts are its shown view's")
            # Every view of a switch is laid out once, the views not shown hidden, so each has its tables.
            tables = window.scroll.body.findChildren(TableView)
            self.assertEqual([t.table for t in tables], [b for b in laid_out(blocks) if isinstance(b, Table)])

    def test_the_tiles_are_the_summary_s_figures_in_its_order(self):
        window = self.shown()
        tiles = window.scroll.body.findChild(TilesView)
        block = next(b for b in self.blocks(window) if isinstance(b, Tiles))
        self.assertEqual([(c.text(), f.text()) for c, f in zip(tiles.captions, tiles.figures)], list(block.items))

    def test_the_tiles_share_the_column_s_edges_and_their_rows_line_up(self):
        window = self.shown()
        window.resize(em(60), em(44))
        spin()
        tiles = window.scroll.body.findChild(TilesView)
        spin()
        first, last = tiles.boxes[0].geometry(), tiles.boxes[-1].geometry()
        self.assertEqual(first.left(), 0)
        widest = max(box.geometry().right() for box in tiles.boxes)
        self.assertEqual(widest + 1, tiles.width())
        self.assertGreaterEqual(tiles.height(), last.bottom())

    def test_a_narrower_window_stacks_the_tiles_and_lengthens_the_view_rather_than_cutting_it(self):
        window = self.shown()
        tiles = window.scroll.body.findChild(TilesView)
        wide = tiles.heightForWidth(em(60))
        self.assertGreater(tiles.heightForWidth(em(20)), wide)

    def test_a_legend_names_each_series_and_a_shape_only_where_the_chart_marks_a_reset(self):
        disc = history.RESET_MARKS["extra"]
        legend = LegendView(self.theme, (("alpha", "series-1", ""), (history.EXTRA_RESET_NOTE, "ink-2", disc)))
        self.addCleanup(legend.deleteLater)
        self.assertEqual([e.findChild(QLabel).text() for e in legend.entries], ["alpha", history.EXTRA_RESET_NOTE])
        self.assertEqual([e.findChild(plot_view.LegendMark).mark for e in legend.entries], ["", disc])

    def test_a_narrow_legend_wraps_rather_than_cuts_a_name_off(self):
        legend = LegendView(self.theme, tuple((f"account {i}", "series-1", "") for i in range(6)))
        self.addCleanup(legend.deleteLater)
        self.assertGreater(legend.heightForWidth(em(8)), legend.heightForWidth(em(80)))

    def test_a_heading_s_hint_stands_behind_a_question_mark_that_tab_reaches(self):
        window = self.shown()
        # A heading stands at the top level, or heads a switch with the words of the view it shows.
        shown = [b if isinstance(b, Heading) else b.views[b.shown].heading
                 for b in self.blocks(window) if isinstance(b, (Heading, Switch))]
        with_hint = next(h for h in shown if h.hint)
        marks = [label for label in window.scroll.body.findChildren(QLabel) if label.text() == "?"]
        self.assertEqual(len(marks), sum(bool(h.hint) for h in shown))
        self.assertEqual(marks[0].focusPolicy(), Qt.FocusPolicy.TabFocus)
        hints = [child for child in marks[0].children() if isinstance(child, common_view.Hint)]
        self.assertEqual([(h.text, h.focus, h.tip.width) for h in hints], [(with_hint.hint, True, HINT_WIDTH)])

    def test_the_summary_opens_the_view_after_each_change_of_span(self):
        window = self.shown()
        window.show()
        window.resize(em(60), em(30))
        spin()
        bar = window.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        window.recompute()
        self.lane.finish()
        spin()
        self.assertEqual(bar.value(), 0)


class ScrollingWordsTest(WindowCase):
    def test_the_charts_share_the_window_s_one_window_of_words(self):
        window = self.shown()
        self.assertEqual({chart.tip for chart in window.charts}, {window.tip})

    def test_a_scroll_under_a_still_pointer_takes_the_words_away(self):
        window = self.shown()
        window.show()
        spin()
        chart = next(c for c in window.charts if c.marks().boxes)
        window.scroll.ensureWidgetVisible(chart)
        spin()
        box = chart.marks().boxes[0]
        at = chart.mapToGlobal(QPoint(round((box.x0 + box.x1) / 2), round(box.y1 - 1)))
        with (mock.patch.object(plot_view, "hover_ms", return_value=10),
              mock.patch.object(history_view, "QCursor", mock.Mock(pos=lambda: at))):
            chart.look(at)
            self.assertTrue(until(lambda: window.tip.shown))
            window.scroll.verticalScrollBar().setValue(window.scroll.verticalScrollBar().value() + em(4))
            self.assertFalse(window.tip.shown)

    def test_a_scroll_with_the_pointer_elsewhere_finds_no_mark_it_is_not_over(self):
        window = self.shown()
        window.show()
        spin()
        chart = next(c for c in window.charts if c.marks().boxes)
        window.scroll.ensureWidgetVisible(chart)
        spin()
        box = chart.marks().boxes[0]
        at = chart.mapToGlobal(QPoint(round((box.x0 + box.x1) / 2), round(box.y1 - 1)))
        with (mock.patch.object(plot_view, "hover_ms", return_value=1),
              mock.patch.object(history_view, "QCursor", mock.Mock(pos=lambda: at)),
              mock.patch.object(history_view.QApplication, "widgetAt", return_value=window.recompute_button)):
            window.scroll.verticalScrollBar().setValue(window.scroll.verticalScrollBar().value() + 1)
            self.assertFalse(until(lambda: window.tip.shown, 0.05))

    def test_a_scroll_by_the_bar_or_the_keyboard_counts_as_the_wheel_s_does(self):
        window = self.shown()
        window.show()
        spin()
        router = window.scroll.router
        router.scrolled_at = 0.0
        window.scroll.verticalScrollBar().setValue(em(4))
        self.assertGreater(router.scrolled_at, 0.0)

    def test_a_block_that_cannot_be_drawn_leaves_the_column_painting(self):
        window = self.shown()
        with mock.patch.object(history_view, "TableView", side_effect=IndexError("a short row")):
            with self.assertRaises(IndexError):
                window._render(self.blocks(window))
        self.assertTrue(window.scroll.body.updatesEnabled())


class SpansTest(WindowCase):
    def test_a_change_of_span_keeps_the_content_shown_and_says_which_span_is_computed(self):
        window = self.shown()
        before = window.shown_history
        tiles = window.scroll.body.findChild(TilesView)
        window.span_buttons["7d"].click()
        self.assertEqual(window.status.text(), "Computing 7 days…")
        self.assertIs(window.shown_history, before)
        self.assertIs(window.scroll.body.findChild(TilesView), tiles)
        self.lane.finish()
        self.assertEqual(window.shown_history.span.key, "7d")
        self.assertIn("as of", window.status.text())

    def test_the_last_span_chosen_wins_and_the_buttons_stay_usable_meanwhile(self):
        window = self.window()
        window.open()
        for key in ("6mo", "7d"):
            self.assertTrue(window.span_buttons[key].isEnabled())
            window.span_buttons[key].click()
        self.lane.finish()                                     # 30 days, chosen no longer: dropped
        self.assertIsNone(window.shown_history)
        self.lane.finish()
        self.assertEqual(window.shown_history.span.key, "7d")
        self.assertTrue(window.span_buttons["7d"].isChecked())
        self.assertEqual(self.lane.jobs, [])

    def test_a_click_on_the_chosen_span_computes_it_again(self):
        window = self.shown()
        window.span_buttons["30d"].click()
        self.assertEqual(len(self.lane.jobs), 1)

    def test_recompute_reads_the_ledger_again_by_button_and_by_f5(self):
        window = self.shown()
        window.recompute_button.click()
        self.assertEqual(len(self.lane.jobs), 1)
        self.lane.finish()
        self.shortcut(window, Qt.Key.Key_F5).activated.emit()
        self.assertEqual(len(self.lane.jobs), 1)

    @staticmethod
    def shortcut(window, key):
        return next(s for s in window.findChildren(QShortcut) if s.key() == QKeySequence(key))

    def test_a_failure_is_said_in_the_critical_ink_and_the_content_stays(self):
        window = self.shown()
        tiles = window.scroll.body.findChild(TilesView)
        with mock.patch.object(history_model, "compute", side_effect=OSError("no ledger at X")):
            window.recompute()
            self.lane.finish()
        self.assertEqual(window.status.text(), "Not computed: no ledger at X")
        self.assertEqual(window.status.property("ink"), "critical-text")
        self.assertIs(window.scroll.body.findChild(TilesView), tiles)
        window.recompute()
        self.lane.finish()
        self.assertEqual(window.status.property("ink"), "ink-2")

    def test_with_no_ledger_the_content_s_place_says_it_was_not_computed(self):
        empty = Machine()
        self.addCleanup(empty.close)
        window = self.window(empty.paths)
        window.open()
        self.lane.finish()
        self.assertEqual(self.texts(window), ["Not computed."])
        self.assertTrue(window.status.text().startswith("Not computed: "))

    def test_the_source_problems_status_lists_reach_coverage(self):
        type(self).errors = ("bills: a problem",)
        self.addCleanup(setattr, type(self), "errors", ())
        window = self.shown()
        self.assertIn("• Source problem: bills: a problem", self.texts(window))

    def test_a_lane_that_refuses_is_said_rather_than_lost(self):
        window = self.window()
        self.lane.start("other", lambda: None, lambda _r: None, lambda _e: None)
        window.open()
        self.assertEqual(window.status.text(), "Not computed: another computation is running")

    def test_closing_hides_the_window_and_showing_it_computes_afresh(self):
        window = self.shown()
        window.show()
        self.assertTrue(window.close())
        self.assertTrue(window.isHidden())
        self.assertEqual(self.lane.jobs, [])
        window.open()
        self.assertEqual(len(self.lane.jobs), 1)

    def test_escape_hides_the_window(self):
        window = self.shown()
        self.assertFalse(window.isHidden())
        self.shortcut(window, Qt.Key.Key_Escape).activated.emit()
        self.assertTrue(window.isHidden())

    def test_the_window_opens_inside_the_monitor_at_its_size_and_can_be_made_smaller(self):
        window = self.shown()
        area = window.screen().availableGeometry()
        self.assertEqual((window.width(), window.height()),
                         (min(em(60), int(area.width() * 0.9)), min(em(44), int(area.height() * 0.9))))
        self.assertTrue(area.contains(window.geometry()))
        self.assertLess(window.minimumWidth(), window.width())


class ExportTest(WindowCase):
    def test_the_history_shown_is_written_where_asked_then_opened(self):
        window = self.shown()
        with tempfile.TemporaryDirectory() as folder:
            self.answer = str(Path(folder) / "out.html")
            window.export_button.click()
            self.assertEqual(self.chosen[-1][1], history_model.export_name(window.shown_history))
            self.assertEqual(Path(self.answer).read_text(encoding="utf-8"), render_history(window.shown_history))
            self.assertEqual(self.opened, [Path(self.answer).resolve().as_uri()])
            self.assertEqual(window.status.text(), f"Exported to {Path(self.answer)}.")

    def test_the_next_export_is_offered_the_folder_of_the_last(self):
        window = self.shown()
        with tempfile.TemporaryDirectory() as folder:
            self.answer = str(Path(folder) / "out.html")
            window.export()
            window.export()
            self.assertEqual(self.chosen[1][0], Path(folder))

    def test_a_dialog_called_off_writes_nothing_and_says_nothing(self):
        window = self.shown()
        said = window.status.text()
        window.export()
        self.assertEqual(self.chosen[0][1], history_model.export_name(window.shown_history))
        self.assertEqual((window.status.text(), self.opened), (said, []))

    def test_before_anything_is_computed_it_says_so_and_asks_nothing(self):
        window = self.window()
        window.open()
        window.export()
        self.assertEqual(window.status.text(), "Nothing to export yet: still computing.")
        self.assertEqual(window.status.property("ink"), "critical-text")
        with mock.patch.object(history_model, "compute", side_effect=OSError("no ledger")):
            self.lane.finish()
        window.export()
        self.assertEqual(window.status.text(), "Nothing to export: not computed.")
        self.assertEqual(self.chosen, [])

    def test_a_refused_write_is_said_in_the_critical_ink(self):
        window = self.shown()
        with tempfile.TemporaryDirectory() as folder:
            self.answer = folder            # a folder, not a file
            window.export()
        self.assertTrue(window.status.text().startswith("Not exported: "))
        self.assertEqual(window.status.property("ink"), "critical-text")

    def test_the_save_dialog_offers_the_name_in_the_folder_and_answers_with_the_file(self):
        seen = []

        def accept():
            dialog = APP.activeModalWidget()
            seen.append((dialog.windowTitle(), dialog.acceptMode(), dialog.defaultSuffix(), dialog.directory().path()))
            dialog.accept()

        with tempfile.TemporaryDirectory() as folder:
            QTimer.singleShot(0, accept)
            answer = ask_save_path(None, Path(folder), "windowtally-history-7d.html")
            self.assertEqual(Path(answer), Path(folder).resolve() / "windowtally-history-7d.html")
            self.assertEqual(seen, [("Export the history as HTML", QFileDialog.AcceptMode.AcceptSave, "html",
                                     Path(folder).resolve().as_posix())])

    def test_the_save_dialog_called_off_answers_with_nothing(self):
        QTimer.singleShot(0, lambda: APP.activeModalWidget().reject())
        self.assertEqual(ask_save_path(None, None, "windowtally-history-7d.html"), "")

    def test_the_save_dialog_goes_once_it_has_answered(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        with mock.patch.object(QFileDialog, "exec", lambda _dialog: 0):
            ask_save_path(parent, None, "windowtally-history-7d.html")
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(parent.findChildren(QFileDialog), [])

    def test_ctrl_s_exports(self):
        window = self.shown()
        shortcut = next(s for s in window.findChildren(QShortcut) if s.key() == QKeySequence("Ctrl+S"))
        shortcut.activated.emit()
        self.assertEqual(len(self.chosen), 1)


def column_plot() -> ColumnPlot:
    return ColumnPlot(("a", "b"), (ColumnStack("x", "series-1", (10.0, 0.0), ("a·x", "b·x")),
                                   ColumnStack("y", "series-2", (10.0, 20.0), ("a·y", "b·y"))),
                      20.0, ((0.0, "$0"), (20.0, "$20")))


def line_plot() -> LinePlot:
    """A line above the 20 % gridline, and a marker on that gridline."""
    return LinePlot((Series("alpha", "series-1", ((10.0, 60.0), (50.0, 80.0), (100.0, 80.0))),),
                    (Marker(30.0, 20.0, "series-2", "alpha: extra reset"),), (0.0, 100.0), (0.0, 100.0),
                    ((50.0, "mid"),), ((0.0, "0%"), (20.0, "20%"), (100.0, "100%")), None)


class ChartCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = Theme(APP, "light")

    def setUp(self):
        self.theme.apply("light")
        self.tip = Tip()
        self.addCleanup(self.tip.close)

    def chart(self, plot, axis=(), width=600) -> ChartView:
        chart = ChartView(self.theme, plot, 12, axis, self.tip)
        chart.resize(width, em(12))
        self.addCleanup(chart.deleteLater)
        return chart

    def colour_at(self, chart, x, y) -> QColor:
        ratio = chart.devicePixelRatio()
        return chart.grab().toImage().pixelColor(round(x * ratio), round(y * ratio))


class ChartPaintTest(ChartCase):
    def test_the_charts_of_a_window_share_their_axis_and_their_plot_s_width(self):
        wide = ("$1,234,567.00",)
        marks = [self.chart(plot, wide).marks() for plot in (column_plot(), line_plot())]
        self.assertEqual({m.left for m in marks}, {marks[0].left})
        self.assertEqual({m.right for m in marks}, {marks[0].right})

    def test_a_chart_too_small_for_marks_paints_nothing_and_says_so(self):
        chart = self.chart(line_plot(), width=20)
        self.assertIsNone(chart.marks())
        chart.grab()

    def test_a_chart_is_laid_out_again_at_a_new_width(self):
        chart = self.chart(line_plot())
        before = chart.marks().right
        chart.resize(800, chart.height())
        self.assertEqual(chart.marks().right - before, 200)

    def test_the_marks_are_laid_out_in_the_window_s_pixels_at_any_display_scale(self):
        marks = self.chart(line_plot()).marks()
        self.assertEqual((marks.line_width, marks.hairline, marks.ring), (2.0, 1.0, 2.0))

    def test_a_column_s_data_end_is_rounded_and_the_segment_under_it_is_square(self):
        chart = self.chart(column_plot())
        top, under = None, None
        for box in chart.marks().boxes:
            if box.end and top is None:
                top = box
            elif not box.end:
                under = box
        fill = QColor(colours("light")["series-2"])
        self.assertNotEqual(self.colour_at(chart, top.x0 + 0.5, top.y0 + 0.5).name(), fill.name(), "the corner is cut")
        self.assertEqual(self.colour_at(chart, (top.x0 + top.x1) / 2, top.y0 + 2).name(), fill.name())
        self.assertEqual(self.colour_at(chart, under.x0 + 1, under.y0 + 1).name(),
                         QColor(colours("light")["series-1"]).name())

    def test_a_line_is_anti_aliased_and_its_ringed_mark_cuts_the_gridline_to_a_circle(self):
        chart = self.chart(line_plot())
        marks = chart.marks()
        image = chart.grab().toImage()
        ratio = chart.devicePixelRatio()
        c = colours("light")
        seen = {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())}
        self.assertIn(c["series-1"], seen)
        self.assertGreater(len(seen), 8, "edges blend into the page")
        dot = next(d for d in marks.dots if d.ringed)
        self.assertEqual(self.colour_at(chart, dot.x, dot.y).name(), c["series-2"])
        grid = image.pixelColor(round((dot.x + 3 * dot.radius) * ratio), round(dot.y * ratio))
        self.assertEqual(grid.name(), c["grid"], "the gridline runs up to the mark")
        ring = image.pixelColor(int((dot.x + dot.radius + marks.ring / 2) * ratio), round(dot.y * ratio))
        page = QColor(c["page"])
        apart = sum(abs(a - b) for a, b in zip(ring.getRgb()[:3], page.getRgb()[:3]))
        self.assertLess(apart, 12, "and is cut where the ring stands")

    def test_a_change_of_mode_paints_the_new_colours(self):
        chart = self.chart(column_plot())
        box = chart.marks().boxes[0]
        at = ((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
        self.assertEqual(self.colour_at(chart, *at).name(), colours("light")["series-1"])
        self.theme.apply("dark")
        self.assertEqual(self.colour_at(chart, *at).name(), colours("dark")["series-1"])
        self.theme.apply("light")
        self.assertEqual(self.colour_at(chart, *at).name(), colours("light")["series-1"])


class PointerWordsTest(ChartCase):
    def over(self, chart, x, y) -> QPoint:
        return chart.mapToGlobal(QPoint(round(x), round(y)))

    def shown_chart(self):
        chart = self.chart(column_plot())
        chart.show()
        spin()
        self.addCleanup(chart.hide)
        box = chart.marks().boxes[0]
        return chart, box, self.over(chart, (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)

    def test_a_mark_says_what_it_is_after_windows_hover_time_not_before(self):
        chart, box, at = self.shown_chart()
        with mock.patch.object(plot_view, "hover_ms", return_value=10):
            chart.look(at)
            self.assertFalse(self.tip.shown)
            self.assertTrue(until(lambda: self.tip.shown))
        self.assertEqual(self.tip._label.text(), box.hover)

    def test_nothing_is_said_while_the_view_scrolls(self):
        chart, _box, at = self.shown_chart()
        with mock.patch.object(plot_view, "hover_ms", return_value=10), \
                mock.patch.object(plot_view, "scrolled_at", side_effect=lambda: time.monotonic()):
            chart.look(at)
            until(lambda: self.tip.shown, 0.05)
        self.assertFalse(self.tip.shown)

    def test_a_scroll_takes_the_words_away_and_they_come_back_once_it_has_rested(self):
        chart, box, at = self.shown_chart()
        with mock.patch.object(plot_view, "hover_ms", return_value=10):
            chart.look(at)
            self.assertTrue(until(lambda: self.tip.shown))
            with mock.patch.object(plot_view, "scrolled_at", return_value=time.monotonic()):
                chart.look(at)
                self.assertFalse(self.tip.shown)
            self.assertTrue(until(lambda: self.tip.shown))

    def test_one_window_of_words_is_moved_as_the_pointer_moves_and_reworded_from_mark_to_mark(self):
        chart, first, at = self.shown_chart()
        with mock.patch.object(plot_view, "hover_ms", return_value=10):
            chart.look(at)
            self.assertTrue(until(lambda: self.tip.shown))
            window = self.tip._label
            chart.look(at + QPoint(1, 2))
            self.assertEqual((window.x(), window.y()), (at.x() + 15, at.y() + 18))
            other = chart.marks().boxes[-1]
            chart.look(self.over(chart, (other.x0 + other.x1) / 2, (other.y0 + other.y1) / 2))
            self.assertTrue(until(lambda: self.tip.shown))
        self.assertIs(self.tip._label, window)
        self.assertEqual(window.text(), other.hover)

    def test_leaving_the_mark_or_the_chart_or_hiding_it_takes_the_words_away(self):
        chart, _box, at = self.shown_chart()
        for leave in (lambda: chart.look(chart.mapToGlobal(QPoint(1, 1))),
                      lambda: chart.leaveEvent(QEvent(QEvent.Type.Leave)),
                      chart.hide):
            with mock.patch.object(plot_view, "hover_ms", return_value=10):
                chart.show()
                chart.look(at)
                self.assertTrue(until(lambda: self.tip.shown))
                leave()
                self.assertFalse(self.tip.shown)


def rows(count: int, wide: bool = False) -> tuple:
    return tuple((f"row {i}", f"{i:,}") + (("a long text " * 30,) if wide else ()) for i in range(count))


def table(count: int, totals=(), wide: bool = False) -> Table:
    return Table((("Name", "w"), ("Figure", "e")) + ((("Words", "w"),) if wide else ()), rows(count, wide), totals)


class TableCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = Theme(APP, "light")

    def setUp(self):
        self.theme.apply("light")
        patcher = mock.patch.object(table_view, "wheel_lines", return_value=3)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(common_view, "wheel_lines", return_value=3)
        patcher.start()
        self.addCleanup(patcher.stop)

    def view(self, block: Table) -> tuple[ScrollFrame, TableView, QWidget]:
        """The table in a scrolling frame, a tall filler under it so the frame can move."""
        frame = ScrollFrame()
        self.addCleanup(frame.deleteLater)
        self.addCleanup(frame.hide)
        column = QVBoxLayout(frame.body)
        column.setContentsMargins(0, 0, 0, 0)
        table_view = TableView(self.theme, block, frame.body)
        column.addWidget(table_view)
        filler = QWidget(frame.body)
        filler.setFixedHeight(em(60))
        column.addWidget(filler)
        frame.resize(em(30), em(20))
        frame.show()
        spin()
        frame.router.gesture.owner = None
        return frame, table_view, filler

    def turn(self, frame, widget, delta=-NOTCH, shift=False) -> None:
        """A turn of the wheel over a point of ``widget`` near its top left, where it stands in view."""
        inside = QPoint(min(em(1), widget.width() // 2), min(em(0.5), widget.height() // 2))
        at = widget.mapToGlobal(inside)
        event = QWheelEvent(QPointF(inside), QPointF(at), QPoint(0, 0), QPoint(0, delta),
                            Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        APP.sendEvent(widget, event)
        spin()


class TableShapeTest(TableCase):
    def test_a_table_that_fits_shows_every_row_with_its_totals_among_them_and_no_bar(self):
        _frame, view, _filler = self.view(table(TABLE_ROWS, (TABLE_ROWS - 1,)))
        self.assertIsNone(view.foot)
        self.assertEqual(view.shown, TABLE_ROWS)
        self.assertTrue(view.rows_bar.isHidden())

    def test_a_long_table_shows_the_page_s_rows_its_totals_kept_below_them(self):
        _frame, view, _filler = self.view(table(30, (29,)))
        self.assertEqual(view.shown + view.foot_rows, TABLE_ROWS)
        self.assertEqual(view.foot_rows, 1)
        self.assertIsNotNone(view.foot)
        self.assertEqual(view.rows.height(), view.shown * view.sizes[2])
        self.assertFalse(view.rows_bar.isHidden())
        self.assertEqual(view.rows_bar.maximum(), 29 - view.shown)

    def test_a_total_among_the_rows_scrolls_with_them(self):
        _frame, view, _filler = self.view(table(30, (3,)))
        self.assertEqual(view.foot_rows, 0)
        self.assertIsNone(view.foot)

    def test_a_table_with_no_rows_shows_its_headings(self):
        _frame, view, _filler = self.view(table(0))
        self.assertEqual(view.shown, 0)
        view.grab()

    def test_the_table_fills_the_view_and_a_wide_one_keeps_it_scrolling_sideways(self):
        _frame, view, _filler = self.view(table(3))
        self.assertEqual(view.marks.width + 2, view.rows.width())
        self.assertTrue(view.bar.isHidden())
        _frame, wide, _filler = self.view(table(3, wide=True))
        self.assertGreater(wide.marks.width + 2, wide.rows.width())
        self.assertFalse(wide.bar.isHidden())
        self.assertEqual(wide.bar.maximum(), int(wide.marks.width) + 2 - wide.rows.width())

    def test_the_parts_wear_their_roles_in_each_mode_and_back(self):
        _frame, view, _filler = self.view(table(3))

        def fills():
            head = view.head.grab().toImage()
            row = view.rows.grab().toImage()
            return head.pixelColor(head.width() // 2, 4).name(), row.pixelColor(row.width() // 2, 2).name()

        def panel(mode: str):   # the headings and the rows both stand on the cards' surface
            return colours(mode)["surface-1"], colours(mode)["surface-1"]

        self.assertEqual(fills(), panel("light"))
        self.theme.apply("dark")
        self.assertEqual(fills(), panel("dark"))
        self.theme.apply("light")
        self.assertEqual(fills(), panel("light"))

    def test_a_total_row_is_set_in_bold(self):
        _frame, view, _filler = self.view(table(3, (2,)))
        cells = view.marks.cells
        self.assertEqual([cell.bold for cell in cells[-2:]], [True, True])
        self.assertEqual([cell.bold for cell in cells[:2]], [False, False])


class TableWheelTest(TableCase):
    def test_the_wheel_over_the_rows_moves_them_as_many_rows_as_windows_gives_lines_then_the_view(self):
        frame, view, _filler = self.view(table(30))
        bar = frame.verticalScrollBar()
        self.turn(frame, view.rows)
        self.assertEqual((view.rows_bar.value(), bar.value()), (3, 0))
        self.assertIs(frame.router.gesture.owner, view.rows)
        view.rows_bar.setValue(view.rows_bar.maximum())
        self.turn(frame, view.rows)
        self.assertEqual(view.rows_bar.value(), view.rows_bar.maximum())
        self.assertEqual(bar.value(), 3 * em(1), "at their end the view around takes the turn")
        self.assertIs(frame.router.gesture.owner, frame)

    def test_the_rows_bar_takes_the_wheel_as_the_rows_do(self):
        frame, view, _filler = self.view(table(30))
        self.turn(frame, view.rows_bar)
        self.assertEqual(view.rows_bar.value(), 3)
        self.assertEqual(frame.verticalScrollBar().value(), 0)

    def test_the_wheel_over_the_headings_or_totals_or_a_table_showing_every_row_moves_the_view(self):
        frame, view, _filler = self.view(table(30, (29,)))
        bar = frame.verticalScrollBar()
        self.turn(frame, view.head)
        self.assertEqual((view.rows_bar.value(), bar.value()), (0, 3 * em(1)))
        frame.router.gesture.owner = None
        self.turn(frame, view.foot)
        self.assertEqual((view.rows_bar.value(), bar.value()), (0, 6 * em(1)))
        frame, short, _filler = self.view(table(5))
        self.turn(frame, short.rows)
        self.assertEqual(frame.verticalScrollBar().value(), 3 * em(1))

    def test_a_gesture_that_began_on_the_view_goes_on_moving_the_view_over_a_table(self):
        frame, view, filler = self.view(table(30))
        at = view.rows.mapToGlobal(QPoint(em(1), 2))
        frame.router.gesture.took(frame, time.monotonic(), at.x(), at.y(), (10 ** 6, 10 ** 6))
        self.turn(frame, view.rows)
        self.assertEqual(view.rows_bar.value(), 0)
        self.assertEqual(frame.verticalScrollBar().value(), 3 * em(1))

    def test_a_finer_wheel_s_part_notches_add_up_to_a_row(self):
        frame, view, _filler = self.view(table(30))
        for _ in range(4):
            self.turn(frame, view.rows, delta=-10)
        self.assertEqual(view.rows_bar.value(), 1)

    def test_a_screen_at_a_time_moves_the_rows_a_page(self):
        from windowtally_gui.scroll_model import PAGE
        frame, view, _filler = self.view(table(30))
        with mock.patch.object(table_view, "wheel_lines", return_value=PAGE):
            self.turn(frame, view.rows)
        self.assertEqual(view.rows_bar.value(), view.shown)

    def test_shift_and_the_wheel_move_a_wide_table_sideways_headings_rows_and_totals_together_the_view_staying(self):
        frame, view, _filler = self.view(table(30, (29,), wide=True))
        for part in (view.head, view.rows, view.foot):
            before = view.bar.value()
            self.turn(frame, part, shift=True)
            self.assertEqual(view.bar.value() - before, 3 * em(1))
        self.assertEqual((frame.verticalScrollBar().value(), view.rows_bar.value()), (0, 0))
        painted = view.head.grab().toImage()
        self.assertEqual(painted.pixelColor(painted.width() // 2, 4).name(), colours("light")["surface-1"])

    def test_shift_and_the_wheel_elsewhere_scroll_as_the_wheel_does(self):
        frame, _view, filler = self.view(table(3))
        self.turn(frame, filler, shift=True)
        self.assertEqual(frame.verticalScrollBar().value(), 3 * em(1))

    def test_the_wheel_over_a_table_s_sideways_bar_moves_the_view(self):
        frame, view, _filler = self.view(table(3, wide=True))
        self.turn(frame, view.bar)
        self.assertEqual(frame.verticalScrollBar().value(), 3 * em(1))


class ShellCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.tray = StandInTray()
        self.machine.paths.window_state.unlink(missing_ok=True)
        self.shell = App(APP, self.machine.paths, start_hidden=True, make_tray=self.tray, start_sync=StandInRun)
        self.shell.history_work = self.lane
        self.addCleanup(self.close_shell)
        spin()

    def close_shell(self):
        self.shell.stop()
        if self.shell.history_window is not None:
            self.shell.history_window.hide()
            self.shell.history_window.deleteLater()
        self.shell.main.hide()
        self.shell.main.deleteLater()
        self.shell.tray_menu.deleteLater()
        spin()

    def status(self, **changes):
        document = status_document([status_account(ACCOUNT_A, EMAIL_A, at=NOW)], at=NOW, **changes)
        self.machine.paths.status_file.write_text(json.dumps(document), encoding="utf-8")
        self.addCleanup(self.machine.paths.status_file.unlink)
        self.shell._look()


class ReachedTest(ShellCase):
    def test_it_is_reached_from_the_button_the_file_menu_and_the_tray_s_menu_and_is_one_window(self):
        button = next(b for b in self.shell.main.findChildren(QPushButton) if b.text() == "History")
        button.click()
        window = self.shell.history_window
        self.assertFalse(window.isHidden())
        window.hide()
        file_menu = self.shell.main.menuBar().actions()[0].menu()
        next(a for a in file_menu.actions() if a.text() == "Show the history").trigger()
        self.assertIs(self.shell.history_window, window)
        self.assertFalse(window.isHidden())
        window.hide()
        next(a for a in self.shell.tray_menu.actions() if a.text() == "History").trigger()
        self.assertIs(self.shell.history_window, window)
        self.assertFalse(window.isHidden())

    def test_it_is_kept_on_top_with_the_main_window_opened_after_the_choice_or_before_it(self):
        self.assertFalse(self.shell.main.keep_on_top.isChecked())
        self.shell.main.keep_on_top.trigger()
        self.shell.open_history()
        flag = Qt.WindowType.WindowStaysOnTopHint
        window = self.shell.history_window
        self.assertTrue(window.windowFlags() & flag)
        self.shell.main.keep_on_top.trigger()
        self.assertFalse(window.windowFlags() & flag)
        self.assertFalse(window.isHidden(), "the change hides nothing")

    def test_the_source_problems_of_the_status_shown_reach_the_computation(self):
        self.status(sourceErrors=["ledger: locked"])
        self.assertEqual(self.shell._source_errors(), ("ledger: locked",))
        self.shell.open_history()
        self.lane.finish()
        self.assertIn("• Source problem: ledger: locked", self.texts(self.shell.history_window))

    def test_with_no_status_there_are_no_problems_to_pass_on(self):
        self.assertEqual(self.shell._source_errors(), ())

    def test_a_change_of_mode_reaches_the_window_through_the_one_theme(self):
        self.shell.open_history()
        self.lane.finish()
        self.shell.main.choose_theme("dark")
        self.addCleanup(self.shell.theme.apply, "light")
        self.assertEqual(self.shell.theme.mode, "dark")
        spin()
        image = self.shell.history_window.scroll.grab().toImage()
        self.assertEqual(image.pixelColor(image.width() - 2, image.height() - 2).name(), colours("dark")["page"])

    def test_the_computation_reaches_the_window_from_a_thread_through_the_quick_clock(self):
        self.shell.history_work = Background()
        self.shell.open_history()
        window = self.shell.history_window
        end = time.monotonic() + 30
        while window.requests.running is not None and time.monotonic() < end:
            self.shell._quick()
            time.sleep(0.01)
        self.assertIsNotNone(window.shown_history)
        self.assertIn("as of", window.status.text())


class QuitTest(ShellCase):
    def test_a_quit_with_the_window_open_ends_the_event_loop(self):
        self.shell.open_history()
        self.lane.finish()
        ended = []
        QTimer.singleShot(0, self.shell.quit)
        # The guard is stopped as the test ends: left to fire in a later test, its exit would end at once every event
        # loop started after it, a dialog's among them, until the application next runs its own.
        guard = QTimer()
        guard.setSingleShot(True)
        guard.timeout.connect(lambda: ended.append("timed out") or APP.exit(1))
        guard.start(5000)
        self.addCleanup(guard.stop)
        self.assertEqual(APP.exec(), 0)
        self.assertEqual(ended, [])


if __name__ == "__main__":
    unittest.main()
