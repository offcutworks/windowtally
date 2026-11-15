"""The window's views, headless: the one presentation mechanism in both modes, the tray icon on a stand-in, the logo's
pixels, pieces of text on a line, the display's pixels a place is kept in, the wheel, hints and the dialogs."""

import ctypes
import struct
import sys
import time
import unittest
from unittest import mock

from qt_support import APP, StandInIcon

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPalette, QWheelEvent
from PySide6.QtWidgets import QLabel, QMenu, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget

from windowtally_gui import common_view
from windowtally_gui.live_model import TrayView
from windowtally_gui.logo_model import logo_rows
from windowtally_gui.cards_view import CHIPS, Chips, Flow, Meter
from windowtally_gui.common_view import (Hint, ScrollFrame, Tip, WheelRouter, em, image_of, logical_place,
                                         native_place, screen_at, set_on_top, size_to_content, tip_place)
from windowtally_gui import switch_view, tray_view
from windowtally_gui.switch_view import AskDialog, ask, fill_switch_menu, sessions_message
from windowtally_gui.theme_view import TEXT_ROLES, Theme, palette_of, scheme_of, style_name, style_sheet
from windowtally_gui.tray_view import Tray, TrayUnavailable, picture, windows_holds_icon
from windowtally_gui.scroll_model import PAGE
from windowtally_gui.state_model import Area, geometry_text, place_of
from windowtally_gui.switch_model import APP as APP_CLIENT, SwitchEntry
from windowtally_gui.theme_model import colours, contrast
from windowtally_gui.tray_model import icon_rows

MODES = ("light", "dark")


def spin() -> None:
    APP.processEvents()


class PresentationTest(unittest.TestCase):
    def setUp(self):
        self.theme = Theme(APP, "light")

    def test_windows_11_wears_its_own_style_and_anything_else_fusion(self):
        self.assertEqual(style_name(["windows11", "Fusion"], 22621), "windows11")
        self.assertEqual(style_name(["windows11", "Fusion"], 19045), "Fusion")
        self.assertEqual(style_name(["Fusion"], 22621), "Fusion")
        self.assertEqual(style_name(["windows11", "Fusion"], 0), "Fusion")

    def test_one_entry_point_sets_the_scheme_the_palette_and_the_sheet_from_roles(self):
        for mode in MODES:
            self.theme.apply(mode)
            c = colours(mode)
            self.assertEqual(self.theme.c, c)
            self.assertEqual(APP.palette().color(QPalette.ColorRole.Window).name(), c["page"])
            self.assertEqual(APP.styleSheet(), style_sheet(c))

    def test_each_mode_asks_for_its_own_scheme_never_windows_own(self):
        self.assertEqual(scheme_of("dark"), Qt.ColorScheme.Dark)
        self.assertEqual(scheme_of("light"), Qt.ColorScheme.Light)

    def test_going_to_dark_and_back_leaves_what_light_left(self):
        before = (APP.styleSheet(), palette_of(colours("light")).color(QPalette.ColorRole.Window).name())
        self.theme.apply("dark")
        self.assertNotEqual(APP.styleSheet(), before[0])
        self.theme.apply("light")
        self.assertEqual((APP.styleSheet(), APP.palette().color(QPalette.ColorRole.Window).name()), before)

    def test_a_fill_is_refused_as_a_text_colour(self):
        label = QLabel()
        for role in ("warning", "critical", "good", "focus", "primary"):
            with self.assertRaises(ValueError):
                self.theme.ink(label, role)
        self.theme.ink(label, "warning-text")
        self.assertEqual(label.property("ink"), "warning-text")

    def test_every_text_role_has_a_rule_in_both_modes(self):
        for mode in MODES:
            sheet = style_sheet(colours(mode))
            for role in TEXT_ROLES:
                self.assertIn(f'QLabel[ink="{role}"]', sheet)

    def test_the_primary_action_s_ink_reads_at_4_5_to_1_on_each_of_its_faces(self):
        for mode in MODES:
            c = colours(mode)
            for face in ("primary", "primary-hover", "primary-pressed"):
                self.assertGreaterEqual(contrast(c["on-primary"], c[face]), 4.5, (mode, face))

    def test_a_role_s_chip_reads_at_4_5_to_1_and_stands_apart_from_the_card(self):
        for mode in MODES:
            c = colours(mode)
            for tint in CHIPS.values():
                self.assertGreaterEqual(contrast(c["ink"], c[tint]), 4.5, (mode, tint))
                self.assertGreater(contrast(c[tint], c["surface-1"]), 1.05, (mode, tint))

    def test_a_widget_that_paints_itself_wears_the_mode_it_paints_in(self):
        meter = Meter(self.theme)
        meter.resize(100, 8)
        for mode in MODES:
            self.theme.apply(mode)
            image = meter.grab().toImage()
            self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2), QColor(colours(mode)["grid"]))
            meter.set(1.0, 2)
            image = meter.grab().toImage()
            self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2),
                             QColor(colours(mode)["critical"]))
            meter.set(0.0, 0)


class TrayTest(unittest.TestCase):
    def setUp(self):
        self.theme = Theme(APP, "light")
        self.icon = StandInIcon()
        self.menu = QMenu()
        self.addCleanup(self.menu.deleteLater)
        self.clicks = []
        self.answers = [True]
        self.tray = Tray(self.theme, lambda: self.clicks.append(1), self.menu, icon=self.icon,
                         ask_windows=lambda: self.answers[0])

    def test_the_icon_shows_at_once_with_the_menu_and_a_tooltip(self):
        self.assertTrue(self.icon.shown)
        self.assertIs(self.icon.menu, self.menu)
        self.assertEqual(self.icon.tooltip, "WindowTally")

    def test_a_click_or_a_double_click_shows_the_window_and_the_context_click_does_not(self):
        reason = QSystemTrayIcon.ActivationReason
        for each in (reason.Trigger, reason.DoubleClick, reason.Context, reason.MiddleClick):
            self.icon.activated.emit(each)
        self.assertEqual(len(self.clicks), 2)

    def test_the_picture_is_the_rings_drawn_by_the_tray_s_model_pixel_for_pixel(self):
        view = TrayView("tip", 1, 0.4, 0.7, "a", weekly_level=1)
        rows = icon_rows(32, "#2a78d6", self.theme.c["warning"], self.theme.c["critical"], five_hour=0.4, weekly=0.7,
                         five_hour_level=0, weekly_level=1, weekly_only=False, greyed=False)
        drawn = picture(32, view, "#2a78d6", self.theme).pixmap(32, 32).toImage()
        for y, row in enumerate(rows):
            for x, pixel in enumerate(row):
                if pixel[3] == 255:
                    colour = drawn.pixelColor(x, y)
                    self.assertEqual((colour.red(), colour.green(), colour.blue(), colour.alpha()), pixel)

    def test_a_tooltip_and_picture_unchanged_are_not_set_again(self):
        view = TrayView("tip", 0, 0.4, 0.7, "a")
        self.tray.show(view, "#123456")
        set_to = self.icon.picture
        self.tray.show(view, "#123456")
        self.assertIs(self.icon.picture, set_to)
        self.tray.show(TrayView("tip 2", 0, 0.4, 0.7, "a"), "#123456")
        self.assertIsNot(self.icon.picture, set_to)
        self.assertEqual(self.icon.tooltip, "tip 2")

    def test_windows_answer_passes_through_and_an_unaskable_one_is_logged_once(self):
        self.assertTrue(self.tray.present())
        self.answers[0] = None
        with self.assertLogs("windowtally_gui.tray_view", "WARNING") as logs:
            self.assertIsNone(self.tray.present())
            self.assertIsNone(self.tray.present())
        self.assertEqual(len(logs.records), 1)

    def test_making_the_icon_again_takes_it_down_and_shows_it(self):
        self.tray.recreate()
        self.assertTrue(self.icon.shown)
        self.assertEqual(self.icon.shows, 2)

    def test_where_there_is_no_notification_area_the_tray_says_so(self):
        with mock.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False):
            with self.assertRaises(TrayUnavailable):
                Tray(self.theme, lambda: None, self.menu)

    def test_with_no_window_of_qt_s_for_the_icon_windows_cannot_be_asked(self):
        self.assertIsNone(windows_holds_icon())


@unittest.skipUnless(sys.platform == "win32", "the structure is Windows' own")
class NotifyIconDataTest(unittest.TestCase):
    """The structure the tray's check hands Windows: NOTIFYICONDATAW whole, as Windows Vista and later read it, its size
    in its own cbSize. The 32-bit offsets are shellapi.h's NOTIFYICONDATAW_V2_SIZE and NOTIFYICONDATAW_V3_SIZE, which end
    before guidItem and hBalloonIcon; a 64-bit build aligns each handle to 8 bytes."""

    LAYOUTS = {32: (956, 936, 952), 64: (976, 952, 968)}   # its size, guidItem's offset, hBalloonIcon's offset

    def test_it_has_the_size_and_the_layout_windows_reads(self):
        data = tray_view._notify_icon_data()
        self.assertEqual((ctypes.sizeof(data), data.guidItem.offset, data.hBalloonIcon.offset),
                         self.LAYOUTS[struct.calcsize("P") * 8])

    def test_the_check_hands_windows_that_size_in_a_modification_that_changes_nothing(self):
        handed = []

        def notify(message, data):
            sent = data._obj
            handed.append((message, sent.cbSize, sent.hWnd, sent.uID, sent.uFlags))
            return 1

        with mock.patch.object(tray_view, "_shell_notify_icon", return_value=notify):
            self.assertTrue(tray_view.holds_icon(0x1234, 7))
        self.assertEqual(handed, [(tray_view.NIM_MODIFY, ctypes.sizeof(tray_view._notify_icon_data()), 0x1234, 7, 0)])


class PicturesTest(unittest.TestCase):
    def test_a_picture_becomes_an_image_of_its_own_pixels(self):
        rows = logo_rows(32)
        image = image_of(rows)
        self.assertEqual((image.width(), image.height()), (32, 32))
        for x, y in ((0, 0), (16, 4), (31, 31), (10, 22)):
            colour = image.pixelColor(x, y)
            self.assertEqual((colour.red(), colour.green(), colour.blue(), colour.alpha()), rows[y][x])


class PlaceTest(unittest.TestCase):
    def test_a_place_turns_into_the_display_s_pixels_and_back_on_any_screen(self):
        for origin, ratio in (((0, 0), 1.0), ((0, 0), 2.0), ((-1920, 200), 1.5), ((3840, 0), 2.0)):
            native = native_place(origin[0] + 100, origin[1] + 40, 800, 600, origin, ratio)
            self.assertEqual(logical_place(*native, origin, ratio), (800, 600, origin[0] + 100, origin[1] + 40))
        self.assertEqual(native_place(100, 40, 800, 600, (0, 0), 2.0), (1600, 1200, 200, 80))

    def test_the_record_s_string_holds_a_place_and_nothing_else_reads_as_one(self):
        self.assertEqual(place_of(geometry_text(760, 560, -120, 80)), (760, 560, -120, 80))
        for bad in (None, "", "760x560", "a+b"):
            self.assertIsNone(place_of(bad))

    def test_a_pixel_on_no_screen_falls_to_the_primary_one(self):
        self.assertIs(screen_at(10 ** 6, 10 ** 6), APP.primaryScreen())


class WindowSizeTest(unittest.TestCase):
    class Asks(QWidget):
        def __init__(self, width: int):
            super().__init__()
            self.width_asked = width

        def sizeHint(self) -> QSize:
            return QSize(self.width_asked, 100)

    def opened_for(self, fraction: float) -> tuple[int, int]:
        screen = APP.primaryScreen().availableGeometry().width()
        window = QWidget()
        self.addCleanup(window.deleteLater)
        QVBoxLayout(window).addWidget(self.Asks(int(screen * fraction)))
        size_to_content(window)
        return window.width(), screen

    def test_a_window_opens_as_wide_as_its_content_asks_past_two_thirds_of_the_screen(self):
        width, screen = self.opened_for(0.8)
        self.assertGreaterEqual(width, int(screen * 0.8))

    def test_nothing_opens_wider_than_nine_tenths_of_the_screen(self):
        width, screen = self.opened_for(1.5)
        self.assertLessEqual(width, int(screen * 0.9))

    def test_a_window_holds_to_its_least_size_past_nine_tenths_of_the_screen(self):
        screen = APP.primaryScreen().availableGeometry().width()
        window = QWidget()
        self.addCleanup(window.deleteLater)
        least = QWidget()
        least.setMinimumWidth(int(screen * 1.2))
        QVBoxLayout(window).addWidget(least)
        size_to_content(window)
        self.assertGreaterEqual(window.width(), int(screen * 1.2))

    def test_words_that_wrap_have_the_height_they_take_at_the_width_the_window_opens_at(self):
        class Wraps(self.Asks):
            def __init__(self, width: int):
                super().__init__(width)
                policy = self.sizePolicy()
                policy.setHeightForWidth(True)
                self.setSizePolicy(policy)

            def hasHeightForWidth(self) -> bool:
                return True

            def heightForWidth(self, width: int) -> int:
                return self.width_asked * 100 // max(1, width)

        area = APP.primaryScreen().availableGeometry()
        words = Wraps(int(area.width() * 1.5))
        window = QWidget()
        self.addCleanup(window.deleteLater)
        QVBoxLayout(window).addWidget(words)
        size_to_content(window)
        self.assertLessEqual(window.width(), int(area.width() * 0.9))
        self.assertGreaterEqual(window.height(), words.heightForWidth(window.width()))


class KeepOnTopTest(unittest.TestCase):
    def setUp(self):
        self.window = QWidget()
        self.addCleanup(self.window.deleteLater)

    def held(self, hint) -> bool:
        return bool(self.window.windowFlags() & hint)

    def test_a_window_not_kept_on_top_keeps_its_close_button(self):
        set_on_top(self.window, False)
        self.assertTrue(self.held(Qt.WindowType.WindowCloseButtonHint))
        self.assertFalse(self.held(Qt.WindowType.WindowStaysOnTopHint))

    def test_a_window_let_go_keeps_its_close_button_and_every_hint_it_had(self):
        before = self.window.windowFlags()
        set_on_top(self.window, True)
        self.assertTrue(self.held(Qt.WindowType.WindowStaysOnTopHint))
        self.assertTrue(self.held(Qt.WindowType.WindowCloseButtonHint))
        set_on_top(self.window, False)
        self.assertEqual(self.window.windowFlags(), before)

    def test_an_open_window_changes_without_hiding_and_its_native_window_keeps_the_close_button(self):
        self.window.show()
        spin()
        for on in (False, True, False):
            set_on_top(self.window, on)
            spin()
            self.assertTrue(self.window.isVisible())
            self.assertTrue(self.window.windowHandle().flags() & Qt.WindowType.WindowCloseButtonHint)
            self.assertEqual(bool(self.window.windowHandle().flags() & Qt.WindowType.WindowStaysOnTopHint), on)
            self.assertTrue(self.held(Qt.WindowType.WindowCloseButtonHint))


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.theme = Theme(APP, "light")
        self.flow = Flow(self.theme, ("ink", "ink-2", "ink-2"), ("", " · ", " · "))
        self.addCleanup(self.flow.deleteLater)

    def spots(self):
        return [self.flow.grid.getItemPosition(self.flow.grid.indexOf(label)) if not label.isHidden() else None
                for label in self.flow.labels]

    def test_pieces_that_fit_share_the_first_line_joined(self):
        self.flow.resize(4000, 40)
        self.flow.set("one", "two", "three")
        self.assertEqual([label.text() for label in self.flow.labels], ["one", " · two", " · three"])
        self.assertEqual([spot[0] for spot in self.spots()], [0, 0, 0])

    def test_a_narrow_width_puts_each_piece_whole_on_a_line_of_its_own_without_its_join(self):
        self.flow.resize(60, 40)
        self.flow.set("one", "two is longer than the width", "three is too")
        self.assertEqual(self.flow.labels[1].text(), "two is longer than the width")
        self.assertEqual([spot[0] for spot in self.spots()], [0, 1, 2])

    def test_an_empty_piece_takes_no_place(self):
        self.flow.resize(4000, 40)
        self.flow.set("one", "", "three")
        self.assertIsNone(self.spots()[1])

    def test_a_change_of_the_chips_places_the_line_again_though_its_words_stand(self):
        chips = Chips(self.theme)
        flow = Flow(self.theme, ("ink-2", "ink-2"), ("", "  "), first=chips)
        chips.set(("CLI",))
        wide = chips.needs()
        flow.resize(wide + QFontMetrics(flow.labels[1].font()).horizontalAdvance("  words") + 2, 40)
        flow.set("chips", "words")
        self.assertEqual(flow.grid.getItemPosition(flow.grid.indexOf(flow.labels[1]))[0], 0)
        chips.set(("desktop app", "CLI", "use next"))
        flow.set("chips", "words")
        self.assertEqual(flow.grid.getItemPosition(flow.grid.indexOf(flow.labels[1]))[0], 1)

    def test_chips_stand_as_the_first_piece_and_show_only_the_roles_held(self):
        chips = Chips(self.theme)
        flow = Flow(self.theme, ("ink-2", "ink-2"), ("", "  "), first=chips)
        chips.set(("CLI",))
        flow.resize(4000, 40)
        flow.set("chips", "words")
        self.assertFalse(chips.chips["CLI"].isHidden())
        self.assertTrue(chips.chips["desktop app"].isHidden())
        self.assertGreater(chips.needs(), 0)
        self.assertEqual(flow.grid.getItemPosition(flow.grid.indexOf(chips))[:2], (0, 0))
        flow.set("", "words")
        self.assertTrue(chips.isHidden())


class WheelTest(unittest.TestCase):
    def setUp(self):
        self.frame = ScrollFrame()
        self.frame.resize(300, 200)
        layout = QVBoxLayout(self.frame.body)
        self.rows = [QLabel(f"row {n}") for n in range(100)]
        for row in self.rows:
            layout.addWidget(row)
        self.frame.show()
        spin()
        self.addCleanup(self.frame.deleteLater)
        self.bar = self.frame.verticalScrollBar()

    def lines(self, setting):
        return mock.patch.object(common_view, "wheel_lines", return_value=setting)

    def test_a_notch_scrolls_as_many_lines_as_windows_setting_says(self):
        with self.lines(3):
            self.frame.scroll(-120)
            spin()
        self.assertEqual(self.bar.value(), 3 * em(1))

    def test_notches_arriving_between_two_repaints_scroll_in_one_step_and_what_makes_no_line_is_carried(self):
        with self.lines(3):
            self.frame.scroll(-120)
            self.frame.scroll(-120)
            spin()
            self.assertEqual(self.bar.value(), 6 * em(1))
            self.frame.scroll(-20)
            spin()
            self.assertEqual(self.bar.value(), 6 * em(1))
            self.frame.scroll(-20)
            spin()
        self.assertEqual(self.bar.value(), 7 * em(1))

    def test_a_setting_of_a_screen_at_a_time_scrolls_a_page(self):
        with self.lines(PAGE):
            self.frame.scroll(-120)
            spin()
        self.assertEqual(self.bar.value(), self.bar.pageStep())

    def test_the_view_says_whether_it_can_still_move_the_wheel_s_way(self):
        self.assertTrue(self.frame.can_move(-120))
        self.assertFalse(self.frame.can_move(120))
        self.bar.setValue(self.bar.maximum())
        self.assertFalse(self.frame.can_move(-120))
        self.assertTrue(self.frame.can_move(120))

    def test_a_turn_over_a_child_reaches_the_view_through_the_router_and_is_taken(self):
        router = self.frame.router
        router.gesture.owner = None
        at = self.rows[1].mapToGlobal(QPoint(5, 5))
        with self.lines(3):
            self.assertTrue(router.turn(-120, at))
            spin()
        self.assertEqual(self.bar.value(), 3 * em(1))
        self.assertIs(router.gesture.owner, self.frame)
        self.assertGreater(router.scrolled_at, 0)

    def test_a_gesture_held_by_a_view_in_another_window_chooses_afresh(self):
        outer, inner = self.frame, ScrollFrame()
        self.addCleanup(inner.deleteLater)
        router = outer.router
        router.gesture.owner, router.gesture.at = inner, time.monotonic()
        router.gesture.x, router.gesture.y = 0, 0
        router.gesture.slop = (10 ** 6, 10 ** 6)
        with self.lines(3):
            router.turn(-120, self.rows[1].mapToGlobal(QPoint(5, 5)))
        self.assertIs(router.gesture.owner, outer)

    def test_a_widget_scrolling_within_the_view_takes_the_turn_while_it_can_move(self):
        router = self.frame.router
        router.gesture.owner = None
        turns = []

        def inside(delta):
            turns.append(delta)
            return len(turns) == 1

        self.rows[1].wheel_inside = inside
        at = self.rows[1].mapToGlobal(QPoint(5, 5))
        with self.lines(3):
            router.turn(-120, at)
            spin()
            self.assertEqual(self.bar.value(), 0)
            self.assertIs(router.gesture.owner, self.rows[1])
            router.turn(-120, at)
            spin()
        self.assertEqual(self.bar.value(), 3 * em(1))
        self.assertIs(router.gesture.owner, self.frame)

    def test_a_widget_that_scrolls_itself_keeps_its_turn(self):
        from PySide6.QtWidgets import QComboBox
        box = QComboBox(self.frame.body)
        box.addItems(["one", "two"])
        box.move(0, 0)
        box.show()
        box.raise_()
        spin()
        self.assertFalse(self.frame.router.turn(-120, box.mapToGlobal(QPoint(5, 5))))

    def test_the_application_s_wheel_events_come_to_the_router(self):
        event = QWheelEvent(QPointF(5, 5), QPointF(self.rows[1].mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, -120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        with self.lines(3):
            APP.sendEvent(self.rows[1], event)
            spin()
        self.assertEqual(self.bar.value(), 3 * em(1))


class TipTest(unittest.TestCase):
    def test_one_window_of_words_is_moved_and_reworded_never_made_again(self):
        tip = Tip()
        self.addCleanup(tip.close)
        tip.show("one", 10, 20)
        window = tip._label
        tip.show("two", 30, 40)
        self.assertIs(tip._label, window)
        self.assertEqual(window.text(), "two")
        self.assertEqual((window.x(), window.y()), (30, 40))
        tip.hide()
        self.assertFalse(tip.shown)

    def test_a_hint_shows_after_a_rest_and_goes_with_the_pointer(self):
        button = QPushButton("B")
        self.addCleanup(button.deleteLater)
        hint = Hint(button, "what it does")
        hint.eventFilter(button, _event("Enter"))
        self.assertTrue(hint._timer.isActive())
        hint._show()
        self.assertTrue(hint.tip.shown)
        hint.eventFilter(button, _event("Leave"))
        self.assertFalse(hint.tip.shown)
        self.assertFalse(hint._timer.isActive())

    def test_a_hint_with_no_words_shows_nothing(self):
        button = QPushButton("B")
        self.addCleanup(button.deleteLater)
        hint = Hint(button)
        hint.eventFilter(button, _event("Enter"))
        self.assertFalse(hint._timer.isActive())

    def test_a_hint_reached_by_the_keyboard_only_where_it_says_so(self):
        button = QPushButton("B")
        self.addCleanup(button.deleteLater)
        plain, keyed = Hint(button, "x"), Hint(button, "x", focus=True)
        plain.eventFilter(button, _event("FocusIn"))
        keyed.eventFilter(button, _event("FocusIn"))
        self.assertFalse(plain._timer.isActive())
        self.assertTrue(keyed._timer.isActive())
        keyed._timer.stop()

    def test_words_that_would_pass_the_area_s_edge_go_to_the_other_side_of_what_they_belong_to(self):
        area = Area(0, 0, 1000, 800)
        self.assertEqual(tip_place(200, 50, 514, 416, Area(500, 400, 500, 400), area), (514, 416))
        # Past the right edge, the words end 14 pixels left of the pointer; past the bottom, 16 above it.
        self.assertEqual(tip_place(200, 50, 914, 416, Area(900, 400, 900, 400), area), (686, 416))
        self.assertEqual(tip_place(200, 50, 514, 796, Area(500, 780, 500, 780), area), (514, 714))
        # A control's hint, asked for 20 in from its left and 2 below it, ends 20 in from its right, 2 above it.
        self.assertEqual(tip_place(200, 50, 870, 762, Area(850, 700, 990, 760), area), (770, 648))
        # Words fitting on neither side of the pointer are held at the area's edge, still below it, clear of it.
        self.assertEqual(tip_place(600, 50, 514, 416, Area(500, 400, 500, 400), area), (0, 416))
        # Words wider than the area start at its left edge.
        self.assertEqual(tip_place(1200, 50, 10, 10, Area(10, 10, 10, 10), area), (0, 10))

    def test_words_asked_for_past_the_screen_s_corner_stand_on_it_clear_of_the_pointer(self):
        tip = Tip()
        self.addCleanup(tip.close)
        self.addCleanup(tip.hide)
        work = APP.primaryScreen().availableGeometry()
        pointer = QPoint(work.right() - 2, work.bottom() - 2)
        tip.show("words long enough to wrap onto a line of their own", pointer.x() + 14, pointer.y() + 16,
                 Area(pointer.x(), pointer.y(), pointer.x(), pointer.y()))
        frame = tip._label.geometry()
        self.assertTrue(work.contains(frame), (work, frame))
        self.assertLess(frame.right(), pointer.x())
        self.assertLess(frame.bottom(), pointer.y())
        tip.move(work.left() + 20, work.top() + 30)
        self.assertEqual(tip._label.pos(), QPoint(work.left() + 20, work.top() + 30))

    def test_a_hint_at_the_screen_s_foot_stands_above_its_control(self):
        work = APP.primaryScreen().availableGeometry()
        holder = QWidget()
        self.addCleanup(holder.deleteLater)
        self.addCleanup(holder.hide)
        holder.setGeometry(work.left() + 40, work.bottom() - 31, 200, 32)
        button = QPushButton("B", holder)
        button.setGeometry(0, 0, 120, 30)
        holder.show()
        spin()
        hint = Hint(button, "what it does")
        hint._show()
        self.addCleanup(hint.tip.close)
        self.addCleanup(hint.tip.hide)
        frame, control = hint.tip._label.geometry(), QRect(button.mapToGlobal(QPoint(0, 0)), button.size())
        self.assertTrue(work.contains(frame), (work, frame))
        self.assertLess(frame.bottom(), control.top())


def _event(name):
    from PySide6.QtCore import QEvent
    return QEvent(getattr(QEvent.Type, name))


class SwitchViewTest(unittest.TestCase):
    def test_a_menu_is_written_afresh_and_says_why_it_is_empty(self):
        menu = QMenu()
        chosen = []
        fill_switch_menu(menu, (SwitchEntry(APP_CLIENT, "u1", "alpha"), SwitchEntry(APP_CLIENT, "u2", "beta  (use next)")),
                         "", lambda client, uuid: chosen.append((client, uuid)))
        self.assertEqual([a.text() for a in menu.actions()], ["alpha", "beta  (use next)"])
        menu.actions()[1].trigger()
        self.assertEqual(chosen, [(APP_CLIENT, "u2")])
        fill_switch_menu(menu, (), "No other account", lambda *_: None)
        self.assertEqual([a.text() for a in menu.actions()], ["No other account"])
        self.assertFalse(menu.actions()[0].isEnabled())

    def test_a_name_with_an_ampersand_is_written_as_it_stands_in_a_menu(self):
        menu = QMenu()
        fill_switch_menu(menu, (SwitchEntry(APP_CLIENT, "u1", "R&D"),), "", lambda *_: None)
        self.assertEqual(menu.actions()[0].text(), "R&&D")

    def test_a_question_stands_on_its_own_while_the_main_window_is_minimized(self):
        owner = QWidget()
        self.addCleanup(owner.deleteLater)
        owner.show()
        owner.showMinimized()
        spin()
        with mock.patch.object(AskDialog, "exec"), mock.patch.object(switch_view, "AskDialog",
                                                                    wraps=AskDialog) as made:
            ask(owner, "T", "M", (("a", "A"),), default="a", cancel="a")
        self.assertIsNone(made.call_args.args[0])

    def dialog(self):
        window = AskDialog(None, "T", "M", (("now", "Now"), ("wait", "Wait"), ("cancel", "Cancel")), default="wait",
                           cancel="cancel")
        self.addCleanup(window.deleteLater)
        return window

    def test_a_dialog_answers_by_the_button_pressed(self):
        window = self.dialog()
        window.buttons["now"].click()
        self.assertEqual(window.answer, "now")

    def test_closing_a_dialog_or_escape_answers_as_cancel_and_its_default_is_the_cautious_one(self):
        window = self.dialog()
        window.reject()
        self.assertEqual(window.answer, "cancel")
        self.assertTrue(window.buttons["wait"].isDefault())

    def test_the_question_counts_the_sessions_and_says_what_ends(self):
        self.assertEqual(sessions_message(1, "switching the desktop app to alpha"),
                         "1 Code session is working. Switching the desktop app to alpha closes the desktop app and ends "
                         "it, without the app's own question.")
        self.assertIn("2 Code sessions are working", sessions_message(2, "opening"))
        self.assertIn("ends them", sessions_message(2, "opening"))


if __name__ == "__main__":
    unittest.main()
