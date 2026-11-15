"""The window's restrained dashboard look, headless: the motion rule and the rings as logic, the bounds that decide
when a card says a reading's age and a plan's days left, the header's in-use words, the title bar's tint through a
stand-in for DWM, the page ground, the one clock what moves draws from, the rings as painted and the source problems'
line standing only while there are problems."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from qt_support import APP

import shiboken6
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QDialog, QMenu, QWidget

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, epoch, status_account, status_document,
                      status_subscription, status_window)
from windowtally.limits import FIVE_HOURS
from windowtally_gui import motion_model
from windowtally_gui.cards_view import HALO, AccountCard, Rings
from windowtally_gui.live_model import live_view, reading_dated, renewal_near
from windowtally_gui.logo_model import FIVE_HOUR, WEEKLY
from windowtally_gui.motion_model import PULSE, PULSE_LOW, SWEEP, eased, moving, pulse_opacity, sweep_value
from windowtally.rings import BAND, GAP, MARGIN, fill, rings
from windowtally_gui.status_model import Window, snapshot_of
from windowtally_gui.theme_model import caption_colour, colours, contrast
from windowtally_gui.theme_view import GRID, Ground, Motion, Theme, framed, style_sheet

import test_window_qt_shell as shell_tests

T0 = epoch("2026-10-20T10:00:00Z")
MODES = ("light", "dark")


def spin() -> None:
    APP.processEvents()


def window(as_of: float | None) -> Window:
    return Window(kind="five_hour", state="running", percent=40.0, resets_at=T0 + 3600, as_of=as_of, estimated=False,
                  exhausts_at=None, anchor_exact=True)


def view(accounts=None, now: float = T0 + 30, **changes):
    doc = status_document(accounts or [status_account(ACCOUNT_A, EMAIL_A, at=T0)], at=T0, **changes)
    return live_view(snapshot_of(Path("status.json"), json.dumps(doc)), now)


class MotionRuleTest(unittest.TestCase):
    def test_the_ease_runs_from_nothing_to_whole_and_is_held_to_that_range(self):
        self.assertEqual((eased(0.0), eased(1.0), eased(-1.0), eased(2.0)), (0.0, 1.0, 0.0, 1.0))
        self.assertGreater(eased(0.5), 0.5, "fast at first, settling into place")

    def test_a_change_sweeps_once_from_the_old_value_to_the_new_and_stops(self):
        self.assertEqual(sweep_value(0.2, 0.6, 0.0, True), (0.2, True))
        middle, going = sweep_value(0.2, 0.6, SWEEP / 2, True)
        self.assertTrue(0.2 < middle < 0.6 and going)
        self.assertEqual(sweep_value(0.2, 0.6, SWEEP, True), (0.6, False))
        self.assertEqual(sweep_value(0.6, 0.6, 0.1, True), (0.6, False), "no change, no motion")

    def test_with_windows_animation_effects_off_a_change_shows_at_once(self):
        self.assertEqual(sweep_value(0.2, 0.6, 0.0, False), (0.6, False))

    def test_only_a_window_at_a_warning_or_an_error_pulses_and_then_slowly_and_lightly(self):
        self.assertEqual(pulse_opacity(0, PULSE / 2, True), 1.0)
        for level in (1, 2):
            self.assertEqual(pulse_opacity(level, 0.0, True), 1.0, "the pulse starts at full strength")
            self.assertAlmostEqual(pulse_opacity(level, PULSE / 2, True), PULSE_LOW)
            self.assertAlmostEqual(pulse_opacity(level, PULSE, True), 1.0)
        self.assertGreaterEqual(PULSE, 3.0, "slow")
        self.assertGreaterEqual(PULSE_LOW, 0.5, "light")

    def test_with_windows_animation_effects_off_a_level_holds_still_at_full_strength(self):
        self.assertEqual(pulse_opacity(2, PULSE / 2, False), 1.0)

    def test_frames_are_wanted_only_while_something_moves(self):
        self.assertFalse(moving(False, 0, True), "at rest nothing runs")
        self.assertTrue(moving(True, 0, True))
        self.assertTrue(moving(False, 1, True))
        self.assertFalse(moving(True, 2, False))


class RingsLogicTest(unittest.TestCase):
    def test_the_weekly_window_is_the_outer_ring_and_the_5_hour_the_inner_in_the_logo_s_colours(self):
        weekly, five_hour = rings(100, (0.4, 0), (0.7, 0))
        self.assertGreater(weekly.radius, five_hour.radius)
        self.assertEqual((weekly.rest, five_hour.rest), (WEEKLY, FIVE_HOUR))
        self.assertAlmostEqual(weekly.radius - five_hour.radius, (BAND + GAP) * 100)
        self.assertAlmostEqual(weekly.radius + weekly.width / 2, 50 - MARGIN * 100, msg="room kept for the glow")

    def test_an_account_with_no_5_hour_limit_draws_its_weekly_ring_alone_leaving_the_5_hour_s_place_empty(self):
        (weekly,) = rings(100, (0.4, 0), None)
        self.assertAlmostEqual(weekly.width, BAND * 100)
        two = rings(100, (0.4, 0), (0.1, 0))
        self.assertAlmostEqual(weekly.radius + weekly.width / 2, two[0].radius + two[0].width / 2)
        self.assertAlmostEqual(weekly.radius - weekly.width / 2, two[0].radius - two[0].width / 2)
        self.assertGreater(weekly.radius - weekly.width / 2, two[1].radius + two[1].width / 2,
                           "nothing drawn where the 5-hour ring would stand")

    def test_an_arc_takes_its_window_s_level_as_the_tray_s_rings_do(self):
        weekly, five_hour = rings(100, (0.9, 2), (0.85, 1))
        self.assertEqual(fill(five_hour, "#warn00", "#crit00"), "#warn00")
        self.assertEqual(fill(weekly, "#warn00", "#crit00"), "#crit00")
        self.assertEqual(fill(rings(100, (0.1, 0), None)[0], "#warn00", "#crit00"), WEEKLY)

    def test_a_fraction_is_held_to_the_ring(self):
        self.assertEqual([r.fraction for r in rings(100, (1.4, 2), (-0.2, 0))], [1.0, 0.0])


class ShownWhenItMattersTest(unittest.TestCase):
    def test_a_reading_is_dated_once_a_5_hour_window_old(self):
        now = T0
        self.assertFalse(reading_dated(window(now - FIVE_HOURS + 1), None, now))
        self.assertTrue(reading_dated(window(now - FIVE_HOURS), None, now))

    def test_a_reading_is_dated_once_a_response_came_after_it(self):
        now = T0
        self.assertFalse(reading_dated(window(now - 60), now - 61, now), "the response before the reading")
        self.assertFalse(reading_dated(window(now - 60), now - 60, now))
        self.assertTrue(reading_dated(window(now - 60), now - 59, now), "use the reading does not hold")

    def test_no_reading_is_always_said(self):
        self.assertTrue(reading_dated(window(None), None, T0))

    def test_a_plan_s_days_left_are_said_within_one_week(self):
        self.assertTrue(renewal_near(0))
        self.assertTrue(renewal_near(7))
        self.assertFalse(renewal_near(8))

    def test_a_card_says_a_fresh_reading_s_age_nowhere_and_an_old_one_s_once(self):
        fresh = view()
        self.assertEqual(fresh.cards[0].heading, "last response 10m ago")
        self.assertEqual((fresh.cards[0].five_hour.note, fresh.cards[0].weekly.note), ("", ""))
        old = view(now=T0 + FIVE_HOURS)
        self.assertTrue(old.cards[0].heading.endswith(" · read 5h 01m ago"), old.cards[0].heading)

    def test_a_card_says_each_window_s_reading_where_they_differ_and_matter(self):
        account = status_account(ACCOUNT_A, EMAIL_A, at=T0,
                                 weekly=status_window("current", 30.0, T0 + 86400, as_of=T0 - 3600, anchor_exact=True))
        card = view([account]).cards[0]
        self.assertEqual(card.five_hour.note, "", "read after the last response, a minute ago")
        self.assertEqual(card.weekly.note, "read 1h 00m ago", "a response came after it")

    def test_a_plan_shows_its_days_left_only_when_its_renewal_is_near(self):
        for days, shown in ((7, True), (8, False)):
            account = status_account(ACCOUNT_A, EMAIL_A, at=T0, plan=status_subscription(daysLeft=days))
            text = view([account]).cards[0].plan.text
            self.assertEqual(text.endswith(f"({days} days left)"), shown, text)
            self.assertIn("paid until Sat 7 Nov", text, "its date always")

    def test_a_window_not_started_says_nothing_under_its_name(self):
        account = status_account(ACCOUNT_A, EMAIL_A, at=T0, five_hour=status_window("not_started", None, None, T0 - 60))
        card = view([account]).cards[0]
        self.assertEqual((card.five_hour.figure, card.five_hour.detail, card.five_hour.note), ("not started", "", ""))

    def test_the_header_leaves_which_account_each_client_uses_to_the_chips(self):
        header = view(syncFollows=True, desktopRunning=True).header
        self.assertEqual(header.in_use_line, "the CLI follows the app")
        other = [status_account(ACCOUNT_A, EMAIL_A, at=T0, cli=False),
                 status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False)]
        apart = view(other, cliAccount=ACCOUNT_B, syncFollows=False, desktopRunning=True).header
        self.assertNotIn("Desktop app", apart.in_use_line, "each card's chip names its client")

    def test_the_header_names_the_clients_where_no_chip_can(self):
        closed = view(desktopRunning=False).header
        self.assertTrue(closed.in_use_line.startswith("Desktop app: alpha (not running) · CLI: alpha · "))
        signed_out = view(desktopAccount=None, desktopSignedIn=False).header
        self.assertTrue(signed_out.in_use_line.startswith("Desktop app: at its sign-in page · CLI: alpha · "))
        unknown = view(cliAccount=None).header
        self.assertTrue(unknown.in_use_line.startswith("Desktop app: alpha · CLI: unknown · "), unknown.in_use_line)

    def test_a_start_the_window_made_leaves_the_clients_to_the_chips_and_the_progress_row(self):
        doc = status_document([status_account(ACCOUNT_A, EMAIL_A, at=T0)], at=T0, desktopRunning=False)
        header = live_view(snapshot_of(Path("status.json"), json.dumps(doc)), T0 + 30, starting=True).header
        self.assertNotIn("Desktop app", header.in_use_line)

    def test_the_hidden_accounts_and_the_sync_s_mode_are_always_said(self):
        accounts = [status_account(ACCOUNT_A, EMAIL_A, at=T0), status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False,
                                                                              cli=False)]
        accounts[1]["hidden"] = True
        self.assertEqual(view(accounts, syncFollows=True).header.in_use_line,
                         "the CLI follows the app · 1 account hidden")

    def test_a_card_knows_whether_a_client_uses_its_account(self):
        accounts = [status_account(ACCOUNT_A, EMAIL_A, at=T0),
                    status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False, cli=False)]
        self.assertEqual([card.in_use for card in view(accounts).cards], [True, False])


class LookTest(unittest.TestCase):
    def setUp(self):
        self.captions = []
        self.animate = [False]
        self.theme = Theme(APP, "light", caption=lambda hwnd, colour: self.captions.append((hwnd, colour)) or True,
                           animations=lambda: self.animate[0])
        self.now = [100.0]
        self.theme.motion.clock = lambda: self.now[0]

    def tearDown(self):
        self.theme.motion.timer.stop()
        self.theme.motion.movers.clear()

    def test_a_title_bar_s_colour_is_given_to_windows_as_a_colorref(self):
        self.assertEqual(caption_colour("#070b12"), 0x120b07)
        self.assertEqual(caption_colour("#edf1f6"), 0xf6f1ed)

    def test_a_framed_window_is_tinted_as_it_shows_and_again_at_every_change_of_mode(self):
        window = QWidget()
        self.addCleanup(window.deleteLater)
        window.show()
        spin()
        hwnd = int(window.winId())
        self.assertIn((hwnd, caption_colour(colours("light")["page"])), self.captions)
        before = len(self.captions)
        self.theme.apply("dark")
        self.assertIn((hwnd, caption_colour(colours("dark")["page"])), self.captions[before:])
        dialog = QDialog(window)
        before = len(self.captions)
        dialog.show()
        spin()
        self.assertIn((int(dialog.winId()), caption_colour(colours("dark")["page"])), self.captions[before:])
        dialog.close()
        window.close()

    def test_a_menu_or_a_tip_has_no_title_bar_to_tint(self):
        menu = QMenu()
        self.addCleanup(menu.deleteLater)
        self.assertFalse(framed(menu))
        before = len(self.captions)
        menu.popup(QPoint(0, 0))
        spin()
        menu.close()
        self.assertEqual(len(self.captions), before)

    def test_off_windows_11_nothing_is_called(self):
        theme = Theme(APP, "light")      # offscreen: no caption setter
        self.assertIsNone(theme.caption)
        window = QWidget()
        self.addCleanup(window.deleteLater)
        window.show()
        spin()
        window.close()

    def test_the_page_ground_is_the_page_colour_under_a_fine_grid_in_the_dark_mode_alone(self):
        ground = Ground(self.theme)
        ground.resize(GRID * 3, GRID * 3)
        for mode, line in (("light", "page"), ("dark", "page-grid")):
            self.theme.apply(mode)
            image = ground.grab().toImage()
            c = colours(mode)
            self.assertEqual(image.pixelColor(GRID // 2, GRID // 2), QColor(c["page"]), mode)
            self.assertEqual(image.pixelColor(GRID, GRID // 2), QColor(c[line]), mode)
            self.assertEqual(image.pixelColor(GRID // 2, GRID), QColor(c[line]), mode)
        ground.deleteLater()

    def test_the_grid_and_the_ring_track_stand_one_step_off_what_they_lie_on(self):
        for mode in MODES:
            c = colours(mode)
            self.assertLess(contrast(c["page-grid"], c["page"]), 1.2, (mode, "a fine grid, not a pattern"))
            self.assertGreater(contrast(c["page-grid"], c["page"]), 1.03, mode)
            self.assertGreater(contrast(c["ring-track"], c["surface-1"]), 1.03, mode)
            self.assertGreater(contrast(c["edge"], c["surface-1"]), 1.1, mode)

    def test_disabled_words_stand_at_3_to_1_on_a_button_and_on_a_menu(self):
        for mode in MODES:
            c = colours(mode)
            for surface in ("face", "surface-1"):
                self.assertGreaterEqual(contrast(c["disabled-text"], c[surface]), 3.0, (mode, surface))

    def test_the_in_use_card_is_marked_by_a_strip_of_its_account_s_colour_and_no_rule_edges_it(self):
        for mode in MODES:
            self.assertNotIn('QFrame[surface="card"][use=', style_sheet(colours(mode)), mode)
        card = AccountCard(self.theme, lambda *_: None)
        self.addCleanup(card.deleteLater)
        accounts = [status_account(ACCOUNT_A, EMAIL_A, at=T0),
                    status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False, cli=False)]
        in_use, other = view(accounts).cards
        card.update_from(in_use, "series-1")
        self.assertEqual((card.strip, card.property("use")), ("series-1", None))
        card.update_from(other, "series-2")
        self.assertEqual((card.strip, card.property("use")), (None, None))

    def test_a_card_draws_its_windows_as_rings_with_a_dot_of_each_ring_s_colour(self):
        card = AccountCard(self.theme, lambda *_: None)
        self.addCleanup(card.deleteLater)
        model = view().cards[0]
        card.update_from(model, "series-1")
        self.assertEqual(card.rings.windows, ((0.69, 0), (0.82, 1)))
        five_hour, weekly = card.windows
        self.assertEqual((five_hour.dot.key, weekly.dot.key), ((FIVE_HOUR, 1), (WEEKLY, 0)))
        no_limit = status_account(ACCOUNT_A, EMAIL_A, at=T0, five_hour=status_window("no_limit", None, None, T0 - 60))
        card.update_from(view([no_limit]).cards[0], "series-1")
        self.assertEqual(card.rings.windows, ((0.69, 0), None))
        self.assertEqual(card.windows[0].dot.key, (WEEKLY, 0), "the weekly window leads")
        self.assertIsNone(card.windows[1].dot.key, "no ring, no dot")

    def test_the_dark_mode_s_halo_stays_inside_the_ring_s_square_whatever_its_shape(self):
        for marks in (rings(100, (1.0, 0), (1.0, 0)), rings(100, (1.0, 0), None)):
            widest = max(ring.radius + (ring.width + HALO[0][0] * 100) / 2 for ring in marks)
            self.assertLessEqual(widest, 50, marks)

    def test_while_every_moving_ring_stands_in_a_minimized_window_the_clock_only_looks_for_its_return(self):
        ring = Rings(self.theme)
        self.addCleanup(ring.deleteLater)
        ring.show()
        spin()
        self.animate[0] = True
        ring.set((0.3, 0), (0.85, 1))
        self.assertEqual(self.theme.motion.timer.interval(), round(motion_model.PULSE_FRAME * 1000))
        ring.showMinimized()
        spin()
        self.theme.motion._frame()
        if ring.isMinimized():      # offscreen windows take the minimized state on this platform
            self.assertEqual(self.theme.motion.timer.interval(), round(self.theme.motion.ASLEEP * 1000))
            ring.showNormal()
            spin()
            self.theme.motion._frame()
        self.assertEqual(self.theme.motion.timer.interval(), round(motion_model.PULSE_FRAME * 1000))
        ring.hide()

    def test_each_widget_s_end_is_watched_once_however_often_it_asks_for_frames(self):
        widget = QWidget()
        self.addCleanup(widget.deleteLater)
        self.theme.motion.want(widget)
        self.theme.motion.done(widget)
        once = widget.receivers("2destroyed(QObject*)")     # PySide adds a receiver of its own with the first
        for _ in range(3):
            self.theme.motion.want(widget)
            self.theme.motion.done(widget)
        self.assertEqual(widget.receivers("2destroyed(QObject*)"), once)

    def test_a_ring_wears_the_mode_it_paints_in(self):
        ring = Rings(self.theme)
        self.addCleanup(ring.deleteLater)
        # A pixel on the outer band just clockwise of the top, where every arc begins.
        top = (ring.width() // 2 + 3, round(ring.width() / 2 - rings(ring.width(), (0, 0), (0, 0))[0].radius))
        for mode in MODES:
            self.theme.apply(mode)
            ring.set((0.0, 0), (0.0, 0))
            self.assertEqual(ring.grab().toImage().pixelColor(*top), QColor(colours(mode)["ring-track"]))
            ring.set((1.0, 2), (0.0, 0))
            self.assertEqual(ring.grab().toImage().pixelColor(*top), QColor(colours(mode)["critical"]))
            ring.set((0.3, 0), (0.0, 0))
            self.assertEqual(ring.grab().toImage().pixelColor(*top), QColor(WEEKLY))
            ring.windows = None

    def test_a_ring_s_first_figures_and_every_figure_without_animation_effects_stand_at_once(self):
        ring = Rings(self.theme)
        self.addCleanup(ring.deleteLater)
        self.animate[0] = True
        ring.set((0.2, 0), (0.1, 0))
        self.assertEqual(ring.marks(self.now[0])[0].fraction, 0.2, "nothing sweeps in from nothing")
        self.assertNotIn(ring, self.theme.motion.movers)
        self.animate[0] = False
        ring.set((0.6, 0), (0.1, 0))
        self.assertEqual(ring.marks(self.now[0])[0].fraction, 0.6)
        self.assertNotIn(ring, self.theme.motion.movers)
        self.assertFalse(self.theme.motion.timer.isActive(), "no clock runs at rest")

    def test_a_ring_whose_figure_changes_sweeps_to_it_once_and_stops(self):
        ring = Rings(self.theme)
        self.addCleanup(ring.deleteLater)
        ring.show()
        self.animate[0] = True
        ring.set((0.2, 0), (0.1, 0))
        ring.set((0.6, 0), (0.1, 0))
        self.assertIn(ring, self.theme.motion.movers)
        self.assertTrue(self.theme.motion.timer.isActive())
        self.assertEqual(self.theme.motion.timer.interval(), round(motion_model.FRAME * 1000), "a sweep runs smooth")
        self.now[0] += SWEEP / 2
        self.assertTrue(0.2 < ring.marks(self.now[0])[0].fraction < 0.6)
        self.now[0] += SWEEP
        ring.grab()     # paints it, as a frame would
        self.assertEqual(ring.marks(self.now[0])[0].fraction, 0.6)
        self.assertNotIn(ring, self.theme.motion.movers)
        self.assertFalse(self.theme.motion.timer.isActive())
        ring.hide()

    def test_a_ring_at_a_warning_pulses_while_it_stays_there_and_not_once_animation_effects_are_off(self):
        ring = Rings(self.theme)
        self.addCleanup(ring.deleteLater)
        ring.show()
        self.animate[0] = True
        ring.set((0.3, 0), (0.85, 1))
        self.assertIn(ring, self.theme.motion.movers)
        self.assertEqual(self.theme.motion.timer.interval(), round(motion_model.PULSE_FRAME * 1000),
                         "a pulse this slow takes fewer frames")
        self.animate[0] = False
        ring.grab()     # paints it, as a frame would
        self.assertNotIn(ring, self.theme.motion.movers, "switched off: it stands still")
        self.animate[0] = True
        ring.set((0.3, 0), (0.5, 0))
        self.assertIn(ring, self.theme.motion.movers, "the change itself sweeps")
        self.now[0] += SWEEP + 0.01
        ring.grab()     # paints it, as a frame would
        self.assertNotIn(ring, self.theme.motion.movers, "back below the warning, the sweep done: nothing moves")
        ring.hide()

    def test_a_widget_that_ends_after_the_clock_s_timer_raises_nothing(self):
        # As the interpreter exits, Qt can delete the clock's timer before a widget the clock moves.
        motion = Motion(animations=lambda: True)
        widget = QWidget()
        motion.want(widget)
        shiboken6.delete(motion.timer)
        with mock.patch.object(sys, "excepthook") as hook:
            shiboken6.delete(widget)
        hook.assert_not_called()
        self.assertEqual(motion.movers, {})

    def test_the_clock_lets_go_of_a_widget_no_one_can_see(self):
        widget = QWidget()
        self.addCleanup(widget.deleteLater)
        self.theme.motion.want(widget)
        self.assertTrue(self.theme.motion.timer.isActive())
        self.theme.motion._frame()
        self.assertNotIn(widget, self.theme.motion.movers)
        self.assertFalse(self.theme.motion.timer.isActive())

    def test_figures_take_the_words_families_with_tabular_digits(self):
        self.assertEqual(APP.font().families()[0], "Segoe UI Variable Text")
        figure = self.theme.fonts["figure"]
        self.assertEqual(figure.families()[:2], ["Segoe UI Variable Text", "Segoe UI"])
        self.assertFalse({"Cascadia Mono", "Consolas"} & set(figure.families()))
        self.assertEqual(figure.featureValue(QFont.Tag("tnum")), 1)


class ProblemsLineTest(shell_tests.ShellCase):
    def test_the_source_problems_line_stands_only_while_there_are_problems(self):
        self.status()
        main = self.open().main
        self.assertTrue(main.problem_count.isHidden())
        self.assertTrue(main.problem_toggle.isHidden())
        self.status(sourceErrors=["bills: unreadable"])
        self.shell.main.show_view(view(sourceErrors=["bills: unreadable"]), {})
        self.assertFalse(main.problem_count.isHidden())
        self.assertFalse(main.problem_toggle.isHidden())
        self.assertEqual(main.problem_count.text(), "1 source problem")
        main.problem_toggle.click()
        main.show_view(view(), {})
        self.assertTrue(main.problem_count.isHidden())
        self.assertTrue(main.problem_frame.isHidden(), "an open list closes with its problems")


if __name__ == "__main__":
    unittest.main()
