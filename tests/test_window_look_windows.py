"""The restrained dashboard look of every window but the main one, headless: each account's share drawn as a bar in its
colour on the summary's tiles, the figures standing at one height; the shade under a chart's line and its glow in the
dark mode, under crisp gridlines; the tables as panels on the cards' surface; the page ground under a window given it,
the History and Conversations windows among them; and nothing left running while the History window stands at rest.
No Bills and sources window is made here: this module makes History windows first, and in one process a Bills and
sources test run after History windows have been made has been seen never to return."""

import unittest
from datetime import date

from qt_support import APP

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QFontMetricsF
from PySide6.QtWidgets import QWidget

from fixtures import ACCOUNT_A, ACCOUNT_B, epoch
from windowtally import history
from windowtally_gui import history_model
from windowtally_gui.cards_view import Meter
from windowtally_gui.common_view import Tip, digits, em
from windowtally_gui.history_model import Tiles
from windowtally_gui.history_view import SHARE_BAR, TilesView
from windowtally_gui.plot_model import Line, LinePlot, Series, area
from windowtally_gui.plot_view import AREA, HALO, ChartView
from windowtally_gui.table_view import PANEL, TableView
from windowtally_gui.theme_model import colours
from windowtally_gui.conversations_view import ConversationsWindow
from windowtally_gui.theme_view import GRID, Theme, _Grounded

import test_window_qt_history as history_tests

NOW = epoch("2026-10-21T18:30:00Z")
ALPHA = history.Entity(ACCOUNT_A, "alpha", "series-1")
BETA = history.Entity(ACCOUNT_B, "beta", "series-2")
MODES = ("light", "dark")


def spin() -> None:
    APP.processEvents()


def summary(costs: dict[history.Entity, float]) -> history.Summary:
    column = (history.Column(date(2026, 10, 21), date(2026, 10, 21)),)
    families = tuple(history.EntityCosts(entity, (history.Stack("Opus", "series-5", (cost,)),))
                     for entity, cost in costs.items())
    accounts = tuple(history.Stack(e.label, e.token, (cost,)) for e, cost in costs.items())
    return history.summary(None, {}, [ALPHA, BETA], history.Costs(column, accounts, families), None,
                           date(2026, 10, 21), NOW, weeks=())


class DigitsTest(unittest.TestCase):
    def test_a_width_in_digits_is_never_under_what_the_digits_take_and_under_a_pixel_over(self):
        # A digit's width is a fraction of a pixel on a scaled display: the count is taken of that width, not of a
        # whole number of pixels, or a list's column comes out narrower than the cells it was sized for.
        one = QFontMetricsF(APP.font()).horizontalAdvance("0")
        for count in (1, 4, 13, 26, 46.5):
            with self.subTest(count=count):
                self.assertGreaterEqual(digits(count), count * one)
                self.assertLess(digits(count) - count * one, 1)


class ShareFiguresTest(unittest.TestCase):
    def test_an_account_s_share_tile_carries_its_share_and_its_colour_and_no_other_tile_does(self):
        tiles = history.summary_tiles(summary({ALPHA: 30.0, BETA: 10.0, history.UNATTRIBUTED: 60.0}))
        shares = {t.caption: (t.share, t.token) for t in tiles if t.share is not None}
        self.assertEqual(shares, {"alpha's share": (0.3, "series-1"), "beta's share": (0.1, "series-2"),
                                  "no known account's share": (0.6, "muted")})
        self.assertEqual({t.figure for t in tiles if t.caption.endswith("'s share")}, {"30%", "10%", "60%"},
                         "the words are the figure's as before")

    def test_without_priced_use_a_share_has_no_bar(self):
        tiles = history.summary_tiles(summary({}))
        self.assertTrue(all(t.share is None for t in tiles))

    def test_the_window_s_tiles_take_a_bar_for_each_share_and_none_for_the_rest(self):
        block = history_model.summary_block(summary({ALPHA: 75.0, BETA: 25.0}))
        self.assertEqual(len(block.bars), len(block.items))
        self.assertEqual([(caption, bar) for (caption, _figure), bar in zip(block.items, block.bars) if bar],
                         [("alpha's share", (0.75, "series-1")), ("beta's share", (0.25, "series-2"))])

    def test_tiles_whose_bars_do_not_match_them_are_refused_rather_than_cut(self):
        theme = Theme(APP, "light")
        with self.assertRaises(ValueError):
            TilesView(theme, Tiles((("a", "1"), ("b", "2")), ((0.5, "series-1"),)))


class TilesBarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = Theme(APP, "light")

    def tiles(self) -> TilesView:
        view = TilesView(self.theme, Tiles((("Work's share", "60%"), ("Top model family", "Opus · 63%")),
                                           ((0.6, "series-2"), None)))
        view.resize(em(30), view.heightForWidth(em(30)))
        self.addCleanup(view.deleteLater)
        return view

    def test_a_share_is_drawn_as_far_as_it_goes_in_the_account_s_colour_in_each_mode(self):
        view = self.tiles()
        meter = view.bars[0]
        self.assertIsNone(view.bars[1])
        self.assertEqual(meter.height(), Meter.tall(SHARE_BAR))
        for mode in MODES:
            self.theme.apply(mode)
            image = meter.grab().toImage()
            middle = image.height() // 2
            ratio = meter.devicePixelRatio()
            self.assertEqual(image.pixelColor(round(meter.width() * 0.3 * ratio), middle).name(),
                             colours(mode)["series-2"])
            self.assertEqual(image.pixelColor(round(meter.width() * 0.9 * ratio), middle).name(), colours(mode)["grid"])
        self.theme.apply("light")

    def test_every_tile_keeps_the_bar_s_room_so_the_figures_stand_at_one_height(self):
        view = self.tiles()
        view.show()
        spin()
        self.addCleanup(view.hide)
        tops = {figure.mapTo(view, figure.rect().topLeft()).y() for figure in view.figures}
        self.assertEqual(len(tops), 1, tops)

    def test_a_meter_with_no_role_keeps_its_level_s_colour(self):
        meter = Meter(self.theme)
        meter.resize(100, 8)
        self.addCleanup(meter.deleteLater)
        meter.set(1.0, 1)
        image = meter.grab().toImage()
        self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2).name(), colours("light")["warning"])


class AreaTest(unittest.TestCase):
    def test_the_shape_under_a_line_runs_along_it_then_back_along_the_baseline(self):
        line = Line("series-1", (10.0, 50.0, 30.0, 50.0, 30.0, 20.0, 60.0, 20.0), "alpha")
        self.assertEqual(area(line, 90.0), line.points + (60.0, 90.0, 10.0, 90.0))


def flat_plot() -> LinePlot:
    """One level line at 60 % from the 10 to the 90 mark."""
    return LinePlot((Series("alpha", "series-1", ((10.0, 60.0), (90.0, 60.0))),), (), (0.0, 100.0), (0.0, 100.0),
                    ((50.0, "mid"),), ((0.0, "0%"), (20.0, "20%"), (100.0, "100%")), None)


class ChartGlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = Theme(APP, "light")

    def tearDown(self):
        self.theme.apply("light")

    def chart(self) -> ChartView:
        tip = Tip()
        self.addCleanup(tip.close)
        chart = ChartView(self.theme, flat_plot(), 12, (), tip)
        chart.resize(600, em(12))
        self.addCleanup(chart.deleteLater)
        return chart

    def colour(self, chart: ChartView, x: float, y: float) -> QColor:
        ratio = chart.devicePixelRatio()
        return chart.grab().toImage().pixelColor(round(x * ratio), round(y * ratio))

    def test_under_a_line_its_shade_fades_toward_the_baseline_and_a_gridline_crosses_it_crisp(self):
        chart = self.chart()
        marks = chart.marks()
        line = marks.lines[0]
        x, top = (line.points[0] + line.points[-2]) / 2, line.points[1]
        for mode in MODES:
            self.theme.apply(mode)
            c = colours(mode)
            page, tint = QColor(c["page"]), QColor(c["series-1"])
            near = self.colour(chart, x, top + 6)
            low = self.colour(chart, x, marks.baseline - 3)

            def towards(colour: QColor) -> float:
                return sum(abs(a - b) for a, b in zip(colour.getRgb()[:3], page.getRgb()[:3]))

            self.assertGreater(towards(near), towards(low), mode)
            self.assertLessEqual(towards(near), sum(abs(a - b) for a, b in zip(tint.getRgb()[:3], page.getRgb()[:3]))
                                 * AREA[mode == "dark"] + 3, "no stronger than its opacity")
            grid = next(y for y in marks.grid if top + 4 < y < marks.baseline - 2)
            self.assertEqual(self.colour(chart, x, grid).name(), c["grid"], "the gridline is drawn over the shade")

    def test_only_the_dark_mode_lays_a_glow_beside_the_line(self):
        chart = self.chart()
        marks = chart.marks()
        line = marks.lines[0]
        x, y = (line.points[0] + line.points[-2]) / 2, line.points[1] - marks.line_width * 1.3
        self.assertGreater(min(wider for wider, _opacity in HALO) * marks.line_width / 2, marks.line_width * 1.3 - 0.5)
        self.assertEqual(self.colour(chart, x, y).name(), colours("light")["page"], "above a line, light: the page")
        self.theme.apply("dark")
        self.assertNotEqual(self.colour(chart, x, y).name(), colours("dark")["page"], "dark: its glow")
        self.theme.apply("light")
        self.assertEqual(self.colour(chart, x, y).name(), colours("light")["page"], "and back: the glow goes")

    def test_the_lines_are_painted_once_for_a_size_and_a_mode_and_laid_down_at_each_repaint(self):
        chart = self.chart()
        chart.grab()
        layers = chart._layers
        chart.grab()
        self.assertIs(chart._layers, layers, "a repaint lays the same pictures down")
        self.theme.apply("dark")
        chart.grab()
        self.assertIsNot(chart._layers, layers, "a change of mode paints them again")
        layers = chart._layers
        chart.resize(700, chart.height())
        chart.grab()
        self.assertIsNot(chart._layers, layers, "and a new size")


class TablePanelTest(history_tests.TableCase):
    def test_the_headings_and_the_rows_stand_on_the_cards_surface_edged_by_their_hairline(self):
        _frame, view, _filler = self.view(history_tests.table(3))
        for mode in MODES:
            self.theme.apply(mode)
            c = colours(mode)
            head, rows = view.head.grab().toImage(), view.rows.grab().toImage()
            ratio = view.head.devicePixelRatio()
            self.assertEqual(head.pixelColor(head.width() // 2, round(4 * ratio)).name(), c[PANEL])
            self.assertEqual(rows.pixelColor(rows.width() // 2, round(2 * ratio)).name(), c[PANEL])
            self.assertEqual(head.pixelColor(head.width() // 2, head.height() - 1).name(), c["edge"],
                             "a hairline under the headings")
            self.assertEqual(rows.pixelColor(0, rows.height() // 2).name(), c["edge"], "the panel's edge")
            line = round((view.sizes[2] - 1) * ratio)
            self.assertEqual(rows.pixelColor(rows.width() // 2, line).name(), c["grid"], "rows parted by the gridline")
        self.theme.apply("light")


class GroundTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = Theme(APP, "light")

    def test_a_window_given_the_ground_wears_the_page_under_its_grid_in_the_dark_mode_alone(self):
        window = QWidget()
        window.resize(GRID * 4, GRID * 4)
        self.addCleanup(window.deleteLater)
        self.theme.ground(window)
        for mode, line in (("light", "page"), ("dark", "page-grid")):
            self.theme.apply(mode)
            image = window.grab().toImage()
            ratio = window.devicePixelRatio()
            c = colours(mode)
            self.assertEqual(image.pixelColor(round(GRID * ratio), round(GRID / 2 * ratio)).name(), c[line], mode)
            self.assertEqual(image.pixelColor(round(GRID / 2 * ratio), round(GRID / 2 * ratio)).name(), c["page"],
                             mode)
        self.theme.apply("light")


class HistoryAtRestTest(history_tests.WindowCase):
    def test_the_window_opens_on_the_summary_with_its_bars(self):
        h = history_model.compute(self.machine.paths, "30d", now=history_tests.NOW)
        block = history_model.blocks(h)[1]
        self.assertEqual(block, history_model.summary_block(h.summary))
        self.assertTrue(any(block.bars), "the invented machine's accounts have priced use, so shares have bars")

    def test_the_history_and_conversations_windows_stand_on_the_ground(self):
        conversations = ConversationsWindow(self.theme, self.machine.paths, self.lane, lambda: None, lambda: False,
                                            frozenset, lambda _link: None)
        self.addCleanup(conversations.deleteLater)
        for window in (self.window(), conversations):
            self.assertIsNotNone(window.findChild(_Grounded), type(window).__name__)

    def test_nothing_runs_on_a_clock_while_the_history_window_stands_at_rest(self):
        window = self.shown()
        spin()
        self.assertTrue(window.findChildren(TableView) and window.findChildren(ChartView))
        running = [timer for timer in window.findChildren(QTimer) if timer.isActive()]
        self.assertEqual(running, [])


if __name__ == "__main__":
    unittest.main()
