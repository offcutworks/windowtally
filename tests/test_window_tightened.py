"""The main window's tightened card and header, headless: the per-model window's bar and the logic it is drawn from, the
rings beside the two figures, a line whose first piece is wider than the card, the in-use strip, the card's edge under
the pointer, the one chip tint and the quiet buttons, the figures' family, the page ground's grid in the dark mode
alone, the actions at the header's line and the theme and Keep on top in the View menu alone."""

import json
import unittest
from pathlib import Path

from qt_support import APP

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QCheckBox, QComboBox, QMenu, QPushButton

from fixtures import ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, epoch, status_account, status_document, status_window
from windowtally.rings import BAND, GAP, MARGIN, rings
from windowtally_gui import main_view
from windowtally_gui.card_model import bar_dashes, bar_fill, bar_known, flow_places
from windowtally_gui.cards_view import CHIPS, AccountCard, ScopedBar
from windowtally_gui.common_view import em
from windowtally_gui.live_model import live_view
from windowtally_gui.logo_model import WEEKLY
from windowtally_gui.state_model import load_state
from windowtally_gui.status_model import snapshot_of
from windowtally_gui.theme_model import colours, contrast
from windowtally_gui.theme_view import FIGURE_FAMILIES, GRID, WORD_FAMILIES, Ground, Theme, style_sheet

import test_window_qt_shell as shell_tests

T0 = epoch("2026-10-20T10:00:00Z")
MODES = ("light", "dark")


def spin() -> None:
    APP.processEvents()


def scoped(state: str = "current", percent: float | None = 34.0) -> dict:
    return {"name": "Fable", "state": state, "percent": percent, "resetsAt": "2026-10-23T10:00:00Z",
            "asOf": "2026-10-20T07:00:00Z", "estimated": state == "current", "allowanceOfWeekly": 50}


def fullest(items=None) -> dict:
    """An account with a 5-hour window, the weekly window with its use by product, and the per-model windows given."""
    weekly = status_window("current", 23.0, T0 + 3 * 86400, as_of=T0 - 60, anchor_exact=True)
    weekly["byProduct"] = {"asOf": "2026-10-20T07:00:00Z",
                           "rows": [{"key": "claude_code", "name": "Claude Code", "percent": 89},
                                    {"key": "chat", "name": "Chats", "percent": 11}]}
    if items is not None:
        weekly["scoped"] = items
    return status_account(ACCOUNT_A, EMAIL_A, at=T0, weekly=weekly,
                          five_hour=status_window(percent=57.0, resets=T0 + 9000, as_of=T0 - 60))


def view(accounts, now: float = T0 + 30):
    doc = status_document(accounts, at=T0)
    return live_view(snapshot_of(Path("status.json"), json.dumps(doc)), now)


class BarLogicTest(unittest.TestCase):
    def test_a_used_window_fills_its_share_of_the_bar_and_never_less_than_the_bar_is_tall(self):
        self.assertEqual(bar_fill(200, 4, 0.34, True), 68)
        self.assertEqual(bar_fill(200, 4, 0.01, True), 4, "a sliver still reads as used")
        self.assertEqual(bar_fill(200, 4, 1.4, True), 200, "never beyond the bar's end")
        self.assertEqual(bar_fill(200, 4, 0.0, True), 0)

    def test_an_unknown_window_fills_nothing_and_its_track_is_dashes_never_whole(self):
        self.assertFalse(bar_known("unknown"))
        self.assertTrue(bar_known("≈34%"))
        self.assertEqual(bar_fill(200, 4, 0.5, False), 0)
        dashes = bar_dashes(100, 4)
        self.assertEqual(dashes[:2], ((0.0, 8), (12.0, 8)))
        self.assertLess(sum(length for _start, length in dashes), 100, "gaps between them")
        self.assertLessEqual(dashes[-1][0] + dashes[-1][1], 100, "the last cut at the bar's end")
        self.assertEqual(bar_dashes(0, 4), ())


class FirstPieceTest(unittest.TestCase):
    """A line's first piece wider than the whole width wraps on a line of its own rather than being cut."""

    @staticmethod
    def places(texts, width):
        return flow_places(texts, ("", " · ", " · "), width, lambda _index, text: 10 * len(text))

    def test_its_words_wrap_on_the_first_line_and_every_later_piece_has_a_line_of_its_own(self):
        self.assertEqual(self.places(("aaaaaaaaaaaa", "bb", "c"), 90),
                         (("aaaaaaaaaaaa", 0, True), ("bb", 1, True), ("c", 2, True)))

    def test_one_that_fits_stays_as_it_was(self):
        self.assertEqual(self.places(("aaaa", "bb"), 90), (("aaaa", 0, False), (" · bb", 0, False)))


class RingsTest(unittest.TestCase):
    def test_an_account_with_no_5_hour_limit_draws_its_weekly_ring_no_thicker_and_in_its_own_place(self):
        (single,) = rings(100, (0.4, 0), None)
        outer, _inner = rings(100, (0.4, 0), (0.1, 0))
        self.assertAlmostEqual(single.width, BAND * 100)
        self.assertEqual((single.radius, single.width), (outer.radius, outer.width))

    def test_a_band_is_under_a_twelfth_of_the_square_and_the_gap_and_margin_are_kept(self):
        # Thin rings: a band under a twelfth of the square, the glow's margin and the gap as they were.
        self.assertLess(BAND, 1 / 12)
        self.assertEqual((GAP, MARGIN), (0.035, 0.035))


class CardTest(unittest.TestCase):
    def setUp(self):
        self.theme = Theme(APP, "light", caption=lambda *_: True, animations=lambda: False)
        self.card = AccountCard(self.theme, lambda *_: None)
        self.addCleanup(self.card.deleteLater)

    def show(self, model, width_lines: float = main_view.CARD_WIDTH):
        self.card.update_from(model, "series-1")
        self.card.resize(em(width_lines), 10)
        self.card.show()
        self.card.resize(em(width_lines), self.card.sizeHint().height())
        spin()

    def test_the_fullest_case_shows_its_per_model_window_as_a_bar_with_its_name_figure_and_words(self):
        self.show(view([fullest([scoped()])]).cards[0])
        block = self.card.scoped
        self.assertTrue(block.row.isVisible())
        self.assertEqual((block.name.text(), block.figure.text()), ("Fable", "≈34%"))
        self.assertEqual(block.bar.shown, (0.34, 0, True))
        self.assertTrue(block.keyed.isVisible())
        self.assertEqual(block.keyed.key.key, (WEEKLY, 0), "its line keyed in its bar's colour")
        self.assertIn("50% of the weekly limit", block.line.labels[1].text())

    def test_an_account_without_one_shows_no_bar_and_no_line_for_it(self):
        self.show(view([fullest()]).cards[0])
        self.assertFalse(self.card.scoped.row.isVisible())
        self.assertFalse(self.card.scoped.keyed.isVisible())

    def test_an_unknown_one_does_not_read_as_nothing_used(self):
        self.show(view([fullest([scoped("unknown", None)])]).cards[0])
        block = self.card.scoped
        self.assertEqual(block.figure.text(), "unknown")
        self.assertEqual(block.bar.shown, (0.0, 0, False), "the bar knows it has nothing to fill")

    def test_the_rings_stand_beside_the_two_names_and_figures_alone(self):
        self.show(view([fullest([scoped()])]).cards[0])
        grid = self.card.layout()
        row, _column, rows, _columns = grid.getItemPosition(grid.indexOf(self.card.rings))
        names = {grid.getItemPosition(grid.indexOf(block.name))[0] for block in self.card.windows}
        self.assertEqual((row, rows), (min(names), 2))
        self.assertEqual(names, {row, row + 1})
        lines = [grid.getItemPosition(grid.indexOf(block.keyed))[0] for block in (*self.card.windows,
                                                                                     self.card.scoped)]
        self.assertGreater(min(lines), grid.getItemPosition(grid.indexOf(self.card.scoped.row))[0],
                           "the windows' lines under the gauges, across the card")

    def test_at_the_least_width_no_word_of_a_line_is_cut(self):
        # Offscreen, Qt finds no installed family and sets words about twice as wide as Segoe UI does, so this binds the
        # lines' wrapping; that the title row and the chips fit the least width is measured on the display
        # (``main_view.CARD_WIDTH``).
        accounts = [fullest([scoped("unknown", None)]),
                    status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False, cli=False,
                                   five_hour=status_window("no_limit", None, None, T0 - 60))]
        for model in view(accounts).cards:
            self.show(model)
            flows = [self.card.heading, self.card.plan, self.card.scoped.line]
            flows += [block.line for block in self.card.windows]
            for flow in flows:
                for label in flow.labels:
                    if label.isVisible() and label.text() and not label.wordWrap():
                        need = QFontMetrics(label.font()).horizontalAdvance(label.text())
                        self.assertGreaterEqual(label.width() + 1, need, (model.label, label.text()))

    def test_the_account_in_use_is_marked_by_a_strip_of_its_colour_and_another_by_none(self):
        in_use, other = view([status_account(ACCOUNT_A, EMAIL_A, at=T0),
                              status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False, cli=False)]).cards
        self.show(in_use)
        self.assertEqual(self.card.strip, "series-1")
        image = self.card.grab().toImage()
        ratio = self.card.devicePixelRatio()
        middle = round(self.card.height() / 2 * ratio)
        self.assertEqual(image.pixelColor(round(2 * ratio), middle), QColor(self.theme.c["series-1"]))
        self.card.update_from(other, "series-2")
        self.assertIsNone(self.card.strip)

    def test_a_card_s_edge_does_not_change_under_the_pointer(self):
        for mode in MODES:
            self.assertNotIn('QFrame[surface="card"]:hover', style_sheet(colours(mode)))
        self.assertFalse(self.card.testAttribute(Qt.WidgetAttribute.WA_Hover))


class BarPaintTest(unittest.TestCase):
    def setUp(self):
        self.theme = Theme(APP, "dark", caption=lambda *_: True, animations=lambda: False)

    def test_the_bar_fills_in_the_weekly_ring_s_colour_and_an_unknown_one_shows_gaps(self):
        bar = ScopedBar(self.theme)
        self.addCleanup(bar.deleteLater)
        bar.resize(200, bar.height())
        bar.set(0.5, 0, True)
        image = bar.grab().toImage()
        ratio = bar.devicePixelRatio()
        y = round(bar.height() / 2 * ratio)
        self.assertEqual(image.pixelColor(round(40 * ratio), y), QColor(WEEKLY))
        self.assertEqual(image.pixelColor(round(160 * ratio), y), QColor(self.theme.c["ring-track"]))
        bar.set(0.0, 0, False)
        image = bar.grab().toImage()
        seen = {image.pixelColor(x, y).name() for x in range(image.width())}
        self.assertNotIn(WEEKLY.lower(), seen)
        self.assertGreater(len(seen), 1, "dashes and the gaps between them")


class SharedValuesTest(unittest.TestCase):
    def test_every_chip_wears_one_neutral_tint_readable_and_apart_from_the_card(self):
        self.assertEqual(set(CHIPS.values()), {"chip"})
        for mode in MODES:
            c = colours(mode)
            self.assertGreaterEqual(contrast(c["ink"], c["chip"]), 4.5, mode)
            self.assertGreater(contrast(c["chip"], c["surface-1"]), 1.05, mode)

    def test_the_quiet_button_s_words_read_in_every_state_on_every_surface_it_stands_on(self):
        for mode in MODES:
            c = colours(mode)
            for face in ("face", "hover", "pressed"):
                self.assertGreaterEqual(contrast(c["ink"], c[face]), 4.5, (mode, face))
            self.assertGreaterEqual(contrast(c["disabled-text"], c["face"]), 3.0, mode)
            sheet = style_sheet(c)
            self.assertIn(f'border: 1px solid {c["edge"]}; border-radius: 5px; padding: 2px 10px;', sheet)
            self.assertIn(f'QPushButton[segment] {{\n    background: {c["face"]}; color: {c["ink"]}; '
                          f'border: 1px solid {c["edge"]};', sheet, "the segments wear the one form")

    def test_figures_are_set_in_the_words_family_with_tabular_digits(self):
        theme = Theme(APP, "light", caption=lambda *_: True, animations=lambda: False)
        self.assertEqual(FIGURE_FAMILIES, WORD_FAMILIES)
        figure = theme.fonts["figure"]
        self.assertEqual(figure.families(), WORD_FAMILIES)
        self.assertEqual(figure.featureValue(QFont.Tag("tnum")), 1)

    def test_the_page_ground_lays_its_grid_in_the_dark_mode_alone(self):
        theme = Theme(APP, "light", caption=lambda *_: True, animations=lambda: False)
        ground = Ground(theme)
        self.addCleanup(ground.deleteLater)
        ground.resize(GRID * 3, GRID * 3)
        for mode, grid_colour in (("light", "page"), ("dark", "page-grid")):
            theme.apply(mode)
            image = ground.grab().toImage()
            c = colours(mode)
            self.assertEqual(image.pixelColor(GRID // 2, GRID // 2), QColor(c["page"]), mode)
            self.assertEqual(image.pixelColor(GRID, GRID // 2), QColor(c[grid_colour]), mode)
        theme.apply("light")


class HeaderTest(shell_tests.ShellCase):
    def test_the_five_actions_stand_at_the_right_end_of_the_header_s_line_and_each_runs(self):
        self.status()
        shell = self.open()
        main = shell.main
        main.resize(em(100), em(30))
        main.show()
        spin()
        buttons = [main.action_buttons[key] for key in ("refresh", "conversations", "history_view", "bills", "folder")]
        self.assertEqual([b.text() for b in buttons], ["Refresh now", "Conversations", "History", "Bills",
                                                       "Data folder"])
        central = main.centralWidget()
        line = main.status_line.geometry()
        for button in buttons:
            place = QRect(button.mapTo(central, QPoint(0, 0)), button.size())
            self.assertGreater(place.left(), line.right() - 1, button.text())
            self.assertLess(abs(place.top() - line.top()), em(1), button.text())
        last = QRect(buttons[-1].mapTo(central, QPoint(0, 0)), buttons[-1].size())
        self.assertGreater(last.right(), central.width() - em(2), "the line's end")
        ran = []
        for key in main.action_buttons:
            main.actions[key] = lambda k=key: ran.append(k)
        for button in buttons:
            button.click()
        self.assertEqual(ran, ["refresh", "conversations", "history_view", "bills", "folder"])
        main.hide()

    def test_where_the_window_is_narrow_the_actions_stand_under_the_words_still_at_the_right_end(self):
        self.status()
        main = self.open().main
        main.show()
        for lines in (100, 20):
            main.resize(em(lines), em(30))
            spin()
            spin()
            line, bar = main.status_line.geometry(), main.actions_bar.geometry()
            self.assertGreaterEqual(line.width(), main.status_line.widest(), (lines, "no piece wraps within itself"))
            self.assertGreater(bar.right(), main.centralWidget().width() - em(2), (lines, "the line's right end"))
            under = bar.top() >= line.bottom()
            self.assertEqual(under, main._actions_under, lines)
        self.assertTrue(main._actions_under, "at the window's least width they stand under the words")
        main.resize(em(100), em(30))
        spin()
        self.assertFalse(main._actions_under, "with room again they come back beside the words")
        main.hide()

    def test_no_theme_drop_down_and_no_keep_on_top_box_stand_in_the_window(self):
        self.status()
        main = self.open().main
        self.assertEqual(main.centralWidget().findChildren(QComboBox), [])
        self.assertEqual(main.centralWidget().findChildren(QCheckBox), [])
        self.assertEqual({b.text() for b in main.centralWidget().findChildren(QPushButton)}
                         & {"Theme", "Keep on top"}, set())

    def test_the_theme_and_keep_on_top_are_set_in_the_view_menu_and_kept_across_starts(self):
        self.status()
        shell = self.open()
        shell.main.theme_actions["dark"].trigger()
        self.assertEqual(shell.theme.mode, "dark")
        shell.main.keep_on_top.trigger()
        self.assertTrue(shell.main.keep_on_top.isChecked())
        shell._save_now()
        state = load_state(self.paths.window_state)[0]
        self.assertEqual((state.theme, state.keep_on_top), ("dark", True))
        (view_menu,) = [m for m in shell.main.menuBar().findChildren(QMenu) if m.title() == "View"]
        self.assertIn(shell.main.keep_on_top, view_menu.actions())
        self.assertTrue(all(action in view_menu.actions() for action in shell.main.theme_actions.values()))


if __name__ == "__main__":
    unittest.main()
