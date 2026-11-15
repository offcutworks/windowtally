"""The other windows in the tightened look, headless: a list given the height left over ends on a whole row, the row the
keyboard is on is marked by a strip of the focus colour rather than the style's frame, the shade under a short run of a
History chart reaches no further down than the run's width allows, the panels and the dialogs stand at the main
window's density, a dialog's words keep the lines they need, and the filled form is left to the main window's
recommended switch."""

import unittest

from qt_support import APP

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QWidget

from windowtally_gui import switch_view
from windowtally_gui.carry_model import CarryRow
from windowtally_gui.common_view import (CURRENT_STRIP, RowDelegate, RowList, Tip, WholeRows, card_margins, em,
                                         size_to_content)
from windowtally_gui.conversations_view import ConversationsWindow
from windowtally_gui.history_model import Tiles
from windowtally_gui.history_view import TilesView
from windowtally_gui.plot_model import AREA_REACH, Line, LinePlot, Series, shade_floor
from windowtally_gui.plot_view import ChartView
from windowtally_gui.scroll_model import scroll_bars, whole_rows_height
from windowtally_gui.theme_model import colours, contrast
from windowtally_gui.theme_view import Theme

import test_window_qt_arrange as arrange_tests
import test_window_qt_bills as bills_tests
import test_window_qt_history as history_tests

MODES = ("light", "dark")
COLUMNS = (("name", "Name", 20), ("what", "What", 12))


def spin(times: int = 3) -> None:
    for _ in range(times):
        APP.processEvents()


class WholeRowsModelTest(unittest.TestCase):
    def test_the_rows_part_holds_as_many_whole_rows_as_fit(self):
        self.assertEqual(whole_rows_height(300, 40, 26), 40 + 10 * 26)
        self.assertEqual(whole_rows_height(300, 40, 20), 300)

    def test_at_least_one_row_stands_however_little_is_left(self):
        self.assertEqual(whole_rows_height(50, 40, 26), 40 + 26)

    def test_a_row_of_no_height_leaves_the_height_as_given(self):
        self.assertEqual(whole_rows_height(300, 40, 0), 300)

    def test_a_bar_shows_only_where_what_it_scrolls_does_not_fit(self):
        self.assertEqual(scroll_bars(100, 100, 80, 80, 10, 10), (False, False))
        self.assertEqual(scroll_bars(100, 100, 80, 200, 10, 10), (True, False))
        self.assertEqual(scroll_bars(100, 100, 120, 80, 10, 10), (False, True))

    def test_each_bar_can_make_the_other_needed(self):
        self.assertEqual(scroll_bars(100, 100, 95, 95, 10, 10), (False, False))
        self.assertEqual(scroll_bars(100, 100, 95, 101, 10, 10), (True, True), "the side bar narrows the columns' room")
        self.assertEqual(scroll_bars(100, 100, 101, 95, 10, 10), (True, True), "the bar under them shortens the rows'")


class WholeRowsViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = Theme(APP, "light")

    def holder(self, rows: int) -> tuple[QWidget, RowList, WholeRows]:
        page = QWidget()
        self.addCleanup(page.deleteLater)
        listed = RowList(COLUMNS, 8, "name")
        listed.fill((str(n), (f"Row {n}", "words")) for n in range(rows))
        holder = WholeRows(listed, page)
        page.show()
        self.addCleanup(page.hide)
        return page, listed, holder

    def test_a_list_given_any_height_ends_on_a_whole_row(self):
        _page, listed, holder = self.holder(60)
        row = listed.row_height()
        self.assertGreater(row, 0)
        for height in range(em(10), em(10) + 2 * row + 1, 3):
            holder.setGeometry(0, 0, em(30), height)
            spin()
            self.assertEqual(listed.viewport().height() % row, 0, height)
            self.assertLessEqual(listed.height(), holder.height(), height)
            self.assertLess(holder.height() - listed.height(), row, height)

    def test_a_first_row_a_search_hides_leaves_the_rows_whole(self):
        _page, listed, holder = self.holder(60)
        listed.topLevelItem(0).setHidden(True)
        holder.setGeometry(0, 0, em(30), em(12) + 5)
        spin()
        row = listed.row_height()
        self.assertGreater(row, 0)
        self.assertEqual(listed.shown_count(), 59)
        self.assertEqual(listed.viewport().height() % row, 0)

    def test_a_list_too_narrow_for_its_columns_keeps_whole_rows_above_its_bar(self):
        _page, listed, holder = self.holder(60)
        holder.setGeometry(0, 0, em(8), em(12) + 5)
        spin()
        self.assertTrue(listed.horizontalScrollBar().isVisible())
        self.assertEqual(listed.viewport().height() % listed.row_height(), 0)

    def test_a_new_font_s_rows_still_end_whole_with_no_resize(self):
        _page, listed, holder = self.holder(60)
        holder.setGeometry(0, 0, em(30), em(12) + 5)
        spin()
        before = listed.row_height()
        font = listed.font()
        font.setPointSizeF(font.pointSizeF() * 1.7)
        listed.setFont(font)
        spin()
        self.assertNotEqual(listed.row_height(), before)
        self.assertEqual(listed.viewport().height() % listed.row_height(), 0)

    def test_rows_filled_after_the_height_was_given_still_end_whole(self):
        _page, listed, holder = self.holder(0)
        holder.setGeometry(0, 0, em(30), em(13) + 5)
        spin()
        listed.fill((str(n), (f"Row {n}", "words")) for n in range(40))
        spin()
        self.assertEqual(listed.viewport().height() % listed.row_height(), 0)



class ConversationsListTest(history_tests.WindowCase):
    def test_the_conversations_list_stands_in_whole_rows(self):
        window = ConversationsWindow(self.theme, self.machine.paths, self.lane, lambda: None, lambda: False, frozenset,
                                     lambda _link: None)
        self.addCleanup(window.deleteLater)
        self.assertIsInstance(window.list.parentWidget(), WholeRows)


class BillsListTest(bills_tests.WindowCase):
    def test_the_bills_list_stands_in_whole_rows_and_record_is_a_quiet_button(self):
        window = self.open()
        self.assertIsInstance(window.bills.parentWidget(), WholeRows)
        self.assertIsNone(window.submit_button.property("primary"))
        margins = window.submit_button.parentWidget().layout().contentsMargins()
        self.assertEqual((margins.left(), margins.top(), margins.right(), margins.bottom()), card_margins())


class ArrangeButtonsTest(arrange_tests.WindowCase):
    def test_ok_is_a_quiet_button_and_still_the_default(self):
        window = self.open()
        self.assertIsNone(window.ok.property("primary"))
        self.assertTrue(window.ok.isDefault())


class CurrentRowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = Theme(APP, "light")

    def tearDown(self):
        self.theme.apply("light")

    def test_the_strip_reads_on_every_ground_a_row_takes(self):
        for mode in MODES:
            c = colours(mode)
            for ground in ("field", "selection", "hover"):
                self.assertGreaterEqual(contrast(c["focus"], c[ground]), 3.0, (mode, ground))

    def test_the_row_the_keyboard_is_on_wears_the_strip_at_its_left_and_no_frame(self):
        listed = RowList(COLUMNS, 4, "name")
        self.addCleanup(listed.deleteLater)
        self.assertIsInstance(listed.itemDelegate(), RowDelegate)
        listed.fill((str(n), (f"Row {n}", "words")) for n in range(3))
        listed.resize(em(30), listed.sizeHint().height())
        listed.show()
        self.addCleanup(listed.hide)
        listed.activateWindow()
        listed.setFocus()
        spin()
        index = listed.indexFromItem(listed.topLevelItem(1))
        listed.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        spin()
        if not listed.hasFocus():
            self.skipTest("no keyboard focus on this platform")
        rect = listed.visualRect(index)
        last = listed.visualRect(listed.model().index(1, len(COLUMNS) - 1))
        for mode in MODES:
            self.theme.apply(mode)
            spin()
            c = colours(mode)
            image = listed.viewport().grab().toImage()
            ratio = listed.devicePixelRatio()
            middle = round((rect.top() + rect.height() / 2) * ratio)
            self.assertEqual(image.pixelColor(round((rect.left() + 1) * ratio), middle).name(), c["focus"], mode)
            right = round((last.right() - 1) * ratio)
            self.assertEqual(image.pixelColor(right, round((rect.top() + 1) * ratio)).name(), c["field"],
                             (mode, "no frame along the row's top"))
            other = listed.visualRect(listed.indexFromItem(listed.topLevelItem(2)))
            self.assertEqual(image.pixelColor(round((other.left() + 1) * ratio),
                                              round((other.top() + other.height() / 2) * ratio)).name(), c["field"],
                             (mode, "no strip on another row"))

    def test_the_strip_is_narrow_beside_the_words(self):
        self.assertLessEqual(CURRENT_STRIP, 0.2)


class ShadeTest(unittest.TestCase):
    def test_a_short_run_high_on_the_chart_shades_no_column_to_the_baseline(self):
        line = Line("series-1", (100.0, 40.0, 104.0, 40.0), "short")
        self.assertEqual(shade_floor(line, 300.0), 40.0 + AREA_REACH * 4.0)

    def test_the_shade_reaches_at_least_the_run_s_own_lowest_point(self):
        line = Line("series-1", (100.0, 200.0, 104.0, 200.0, 104.0, 40.0), "rising")
        self.assertEqual(shade_floor(line, 300.0), 200.0)

    def test_a_run_that_drops_to_the_baseline_or_is_wide_fades_at_the_baseline(self):
        dropped = Line("series-1", (100.0, 60.0, 104.0, 60.0, 104.0, 300.0), "reset")
        wide = Line("series-1", (100.0, 60.0, 400.0, 60.0), "wide")
        self.assertEqual(shade_floor(dropped, 300.0), 300.0)
        self.assertEqual(shade_floor(wide, 300.0), 300.0)


class ShortRunChartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = Theme(APP, "light")

    def tearDown(self):
        self.theme.apply("light")

    def test_under_a_short_run_the_page_shows_near_the_baseline_in_each_mode(self):
        plot = LinePlot((Series("alpha", "series-1", ((50.0, 80.0), (51.0, 85.0))),), (), (0.0, 100.0), (0.0, 100.0),
                        ((50.0, "mid"),), ((0.0, "0%"), (100.0, "100%")), None)
        tip = Tip()
        self.addCleanup(tip.close)
        chart = ChartView(self.theme, plot, 12, (), tip)
        chart.resize(600, em(12))
        self.addCleanup(chart.deleteLater)
        marks = chart.marks()
        line = marks.lines[0]
        x = (line.points[0] + line.points[-2]) / 2
        for mode in MODES:
            self.theme.apply(mode)
            ratio = chart.devicePixelRatio()
            image = chart.grab().toImage()
            low = image.pixelColor(round(x * ratio), round((marks.baseline - 6) * ratio))
            self.assertEqual(low.name(), colours(mode)["page"], mode)


class DensityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = Theme(APP, "light")

    def test_a_tile_wears_a_card_s_padding_and_the_cards_gap(self):
        view = TilesView(self.theme, Tiles((("a", "1"), ("b", "2"))))
        self.addCleanup(view.deleteLater)
        margins = view.boxes[0].layout().contentsMargins()
        self.assertEqual((margins.left(), margins.top(), margins.right(), margins.bottom()), card_margins())
        self.assertEqual(view.gap, em(0.5))


class DialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = Theme(APP, "dark")

    def carry(self) -> switch_view.CarryDialog:
        rows = (CarryRow("a", "Sort the notes by site", "working", "now", True),
                CarryRow("b", "Add a map of the sightings", "", "4 min ago", True),
                CarryRow("c", "Tidy the species list", "background work unfinished", "2 h ago", True, True),
                CarryRow("d", "Export the season as CSV", "", "3 days ago", False))
        window = switch_view.CarryDialog(None, "Work", "Studio", rows, 1)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.hide)
        size_to_content(window, None)
        window.show()
        spin()
        return window

    def test_the_switch_s_words_keep_their_lines_and_nothing_stands_on_the_list(self):
        window = self.carry()
        for label in (window.lead, window.working, window.note):
            self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()), label.text()[:30])
        self.assertLess(window.working.geometry().bottom(), window.search.geometry().top())
        self.assertLess(window.list.geometry().bottom(), window.note.geometry().top())
        self.assertGreaterEqual(window.list.height(), window.list.sizeHint().height())

    def test_a_dialog_stands_a_line_in_from_its_edges(self):
        window = self.carry()
        margins = window.layout().contentsMargins()
        self.assertEqual({margins.left(), margins.top(), margins.right(), margins.bottom()}, {em(0.5) * 2})
        asked = switch_view.AskDialog(None, "Code sessions are working", "A question.",
                                      (("now", "Switch anyway"), ("cancel", "Cancel")), default="cancel", cancel="cancel")
        self.addCleanup(asked.deleteLater)
        self.assertEqual(asked.layout().contentsMargins().left(), em(0.5) * 2)


if __name__ == "__main__":
    unittest.main()
