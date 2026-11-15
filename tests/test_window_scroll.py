"""How far the wheel scrolls a view of the window, and when a chart's pointer words may show, without a display."""

import unittest

import fixtures  # noqa: F401  (puts the tool folder on the import path, for a run of this module alone)
from windowtally.history import WHEEL_PAUSE
from windowtally_gui.scroll_model import (NOTCH, PAGE, Gesture, gesture_goes_on, inner_takes, wheel_steps, wheel_turn,
                                         words_due)


class WheelTest(unittest.TestCase):
    def test_a_notch_scrolls_windows_lines_down_or_up(self):
        self.assertEqual(wheel_steps(-NOTCH, 0, 3), (3, "units", 0))     # turned towards the user: down
        self.assertEqual(wheel_steps(NOTCH, 0, 3), (-3, "units", 0))
        self.assertEqual(wheel_steps(-NOTCH, 0, 5), (5, "units", 0))

    def test_notches_arriving_together_scroll_in_one_step(self):
        self.assertEqual(wheel_steps(-3 * NOTCH, 0, 3), (9, "units", 0))

    def test_a_fine_wheel_s_part_notches_add_up_and_none_is_lost(self):
        carried, lines = 0, 0
        for _ in range(4):
            count, what, carried = wheel_steps(-30, carried, 3)
            self.assertEqual(what, "units")
            lines += count
        self.assertEqual((lines, carried), (3, 0))
        self.assertEqual(wheel_steps(-30, 0, 3)[:2], (0, "units"))      # under a line: carried, not scrolled

    def test_a_setting_that_does_not_divide_a_notch_loses_nothing(self):
        carried, lines = 0, 0
        for _ in range(4):
            count, _what, carried = wheel_steps(-30, carried, 7)
            lines += count
        self.assertEqual((lines, carried), (7, 0))

    def test_turning_the_other_way_drops_what_was_carried(self):
        _count, _what, carried = wheel_steps(-30, 0, 3)
        self.assertEqual(wheel_steps(NOTCH, carried, 3), (-3, "units", 0))

    def test_a_screen_at_a_time_scrolls_pages(self):
        self.assertEqual(wheel_steps(-NOTCH, 0, PAGE), (1, "pages", 0))
        self.assertEqual(wheel_steps(-60, 0, PAGE), (0, "pages", 60))
        self.assertEqual(wheel_steps(-60, 60, PAGE), (1, "pages", 0))

    def test_no_lines_a_notch_scrolls_nothing(self):
        self.assertEqual(wheel_steps(-NOTCH, 40, 0), (0, "units", 0))


class InnerWheelTest(unittest.TestCase):
    """A table that scrolls within the History view takes the wheel until its edge, then passes it on."""

    def test_a_table_in_its_middle_takes_the_wheel_either_way(self):
        self.assertTrue(inner_takes(0.3, 0.7, -NOTCH))
        self.assertTrue(inner_takes(0.3, 0.7, NOTCH))

    def test_at_its_end_turning_down_or_at_its_top_turning_up_the_view_around_takes_it(self):
        self.assertFalse(inner_takes(0.6, 1.0, -NOTCH))
        self.assertFalse(inner_takes(0.0, 0.4, NOTCH))
        self.assertTrue(inner_takes(0.6, 1.0, NOTCH))     # at its end it still scrolls back up
        self.assertTrue(inner_takes(0.0, 0.4, -NOTCH))

    def test_a_table_showing_every_row_never_takes_it(self):
        self.assertFalse(inner_takes(0.0, 1.0, -NOTCH))
        self.assertFalse(inner_takes(0.0, 1.0, NOTCH))

    def test_tk_s_fractions_a_hair_from_the_edge_count_as_the_edge(self):
        self.assertFalse(inner_takes(0.6, 0.9999999, -NOTCH))
        self.assertFalse(inner_takes(0.0000001, 0.4, NOTCH))

    def test_no_turn_is_taken_by_nobody(self):
        self.assertFalse(inner_takes(0.3, 0.7, 0))


class GestureTest(unittest.TestCase):
    """A gesture of the wheel keeps to the view that took its first turn until the wheel rests or the pointer moves."""
    SLOP = (4, 4)

    def test_the_pause_is_the_user_s_one_and_a_half_seconds(self):
        self.assertEqual(WHEEL_PAUSE, 1.5)

    def test_turns_coming_while_the_pointer_stands_still_are_one_gesture(self):
        self.assertTrue(gesture_goes_on(0.02, (0, 0), self.SLOP, WHEEL_PAUSE))
        self.assertTrue(gesture_goes_on(1.5, (0, 0), self.SLOP, WHEEL_PAUSE))

    def test_a_rest_longer_than_the_pause_ends_it(self):
        self.assertFalse(gesture_goes_on(1.51, (0, 0), self.SLOP, WHEEL_PAUSE))

    def test_the_hand_s_tremor_within_the_drag_threshold_keeps_it(self):
        self.assertTrue(gesture_goes_on(0.1, (4, -4), self.SLOP, WHEEL_PAUSE))

    def test_moving_the_pointer_beyond_the_drag_threshold_either_way_ends_it(self):
        for moved in ((5, 0), (-5, 0), (0, 5), (0, -5)):
            self.assertFalse(gesture_goes_on(0.1, moved, self.SLOP, WHEEL_PAUSE), moved)

    def test_a_clock_that_went_back_ends_it(self):
        self.assertFalse(gesture_goes_on(-0.1, (0, 0), self.SLOP, WHEEL_PAUSE))

    def test_the_view_that_took_the_first_turn_takes_the_next_while_the_pointer_stands_still(self):
        gesture, view = Gesture(), object()
        self.assertIsNone(gesture.held(10.0, 100, 200, WHEEL_PAUSE))          # no gesture yet: choose afresh
        gesture.took(view, 10.0, 100, 200, self.SLOP)
        self.assertIs(gesture.held(10.1, 100, 200, WHEEL_PAUSE), view)
        gesture.took(view, 10.1, 100, 200)
        self.assertIs(gesture.held(11.5, 101, 199, WHEEL_PAUSE), view)        # 1.4 s after the last turn, not the first
        self.assertIsNone(gesture.held(13.1, 100, 200, WHEEL_PAUSE))

    def test_a_pointer_drifting_a_little_at_each_turn_ends_it_once_it_has_left_where_the_gesture_began(self):
        gesture, view = Gesture(), object()
        gesture.took(view, 10.0, 100, 200, self.SLOP)
        now, y = 10.0, 200
        for _ in range(2):
            now, y = now + 0.05, y + 2
            self.assertIs(gesture.held(now, 100, y, WHEEL_PAUSE), view)
            gesture.took(view, now, 100, y)
        self.assertIsNone(gesture.held(now + 0.05, 100, y + 2, WHEEL_PAUSE))   # 6 px from where it began

    def test_the_view_a_table_passes_the_turn_to_keeps_the_gesture(self):
        gesture, table, view = Gesture(), object(), object()
        gesture.took(table, 10.0, 100, 200, self.SLOP)
        gesture.took(view, 10.1, 100, 200)
        self.assertIs(gesture.held(10.2, 100, 200, WHEEL_PAUSE), view)

    def test_a_turn_nothing_took_ends_it(self):
        gesture, view = Gesture(), object()
        gesture.took(view, 10.0, 100, 200, self.SLOP)
        gesture.took(None, 10.1, 100, 200)
        self.assertIsNone(gesture.held(10.2, 100, 200, WHEEL_PAUSE))

    def test_the_threshold_is_the_one_read_when_the_gesture_began(self):
        gesture, view = Gesture(), object()
        gesture.took(view, 10.0, 100, 200, (8, 8))
        self.assertIs(gesture.held(10.1, 107, 200, WHEEL_PAUSE), view)


class View:
    """A stand-in for a widget of the window: a frame (a ScrollFrame), a table scrolling within one, or neither."""

    def __init__(self, name, parent=None, *, frame=False, table=False, room=True, window="main"):
        self.name, self.parent, self.frame, self.table, self.room, self.window = name, parent, frame, table, room, window
        self.alive = True

    def __repr__(self):
        return self.name


class Views:
    """The stand-ins as ``scroll_model.WheelViews``, recording what scrolled and how often the threshold was read."""

    def __init__(self):
        self.scrolled, self.slop_reads = [], 0

    def parent(self, view):
        return view.parent

    def takes_inside(self, view, delta):
        if view.table and view.room:
            self.scrolled.append(view.name)
            return True
        return False

    def is_frame(self, view):
        return view.frame

    def scroll(self, view, delta):
        self.scrolled.append(view.name)

    def can_move(self, view, delta):
        return view.room

    def exists(self, view):
        return view.alive

    def window(self, view):
        return view.window

    def slop(self):
        self.slop_reads += 1
        return (4, 4)


class RouteTest(unittest.TestCase):
    """Where a turn of the wheel goes: out from the view under the pointer to the one that takes it, and a held
    gesture's turn to its view unless that view has gone, stands in another window or is a frame that cannot move."""

    def setUp(self):
        self.views, self.gesture = Views(), Gesture()
        self.page = View("page", frame=True)
        self.panel = View("panel", self.page)
        self.table = View("table", self.panel, table=True)
        self.cell = View("cell", self.table)
        self.now = 10.0

    def turn(self, under, delta=-NOTCH, x=100, y=200):
        self.now += 0.05
        return wheel_turn(self.gesture, under, delta, self.now, x, y, WHEEL_PAUSE, self.views, self.views.slop)

    def test_a_first_turn_goes_to_the_table_under_the_pointer_while_it_can_move(self):
        self.assertIs(self.turn(self.cell), self.table)
        self.assertEqual(self.views.scrolled, ["table"])

    def test_a_table_at_its_edge_passes_the_turn_out_to_the_frame_around_it(self):
        self.table.room = False
        self.assertIs(self.turn(self.cell), self.page)
        self.assertEqual(self.views.scrolled, ["page"])

    def test_a_turn_with_nothing_around_that_scrolls_goes_nowhere_and_ends_the_gesture(self):
        loose = View("loose", View("bare"))
        self.assertIsNone(self.turn(loose))
        self.assertEqual(self.views.scrolled, [])
        self.assertIsNone(self.gesture.owner)

    def test_a_held_gesture_keeps_to_its_frame_though_a_table_that_could_move_comes_under_the_pointer(self):
        self.assertIs(self.turn(self.page), self.page)
        self.assertIs(self.turn(self.cell), self.page)
        self.assertEqual(self.views.scrolled, ["page", "page"])

    def test_a_held_gesture_keeps_to_its_table_while_the_pointer_is_over_another_view(self):
        self.assertIs(self.turn(self.cell), self.table)
        self.assertIs(self.turn(self.page), self.table)
        self.assertEqual(self.views.scrolled, ["table", "table"])

    def test_a_held_table_at_its_edge_passes_the_turn_to_the_frame_which_then_keeps_the_gesture(self):
        self.assertIs(self.turn(self.cell), self.table)
        self.table.room = False
        self.assertIs(self.turn(self.cell), self.page)
        self.table.room = True
        self.assertIs(self.turn(self.cell), self.page)
        self.assertEqual(self.views.scrolled, ["table", "page", "page"])

    def test_a_held_table_at_its_edge_in_a_frame_that_cannot_move_lets_the_turn_choose_afresh(self):
        other = View("other table", self.panel, table=True)
        self.assertIs(self.turn(self.cell), self.table)
        self.table.room = self.page.room = False
        self.assertIs(self.turn(other), other)          # never lost to a frame that cannot move
        self.assertEqual(self.views.scrolled, ["table", "other table"])

    def test_a_held_view_that_has_gone_lets_the_turn_choose_afresh(self):
        self.assertIs(self.turn(self.page), self.page)
        self.page.alive = False
        self.assertIs(self.turn(self.cell), self.table)

    def test_a_held_view_in_another_window_lets_the_turn_choose_afresh(self):
        other = View("other", frame=True, window="dialog")
        self.assertIs(self.turn(other), other)
        self.assertIs(self.turn(self.cell), self.table)
        self.assertEqual(self.views.scrolled, ["other", "table"])

    def test_a_held_frame_that_cannot_move_the_wheel_s_way_lets_the_turn_choose_afresh(self):
        self.assertIs(self.turn(self.page), self.page)
        self.page.room = False
        self.assertIs(self.turn(self.cell), self.table)
        self.assertIs(self.gesture.owner, self.table)

    def test_the_drag_threshold_is_read_when_a_gesture_begins_and_not_at_its_later_turns(self):
        self.turn(self.cell)
        self.turn(self.cell)
        self.assertEqual(self.views.slop_reads, 1)
        self.now += WHEEL_PAUSE + 0.1               # the wheel rested: the next turn begins a gesture
        self.turn(self.cell)
        self.assertEqual(self.views.slop_reads, 2)

    def test_a_gesture_ended_by_a_rest_chooses_afresh_from_under_the_pointer(self):
        self.assertIs(self.turn(self.page), self.page)
        self.now += WHEEL_PAUSE + 0.1
        self.assertIs(self.turn(self.cell), self.table)


class TableFootTest(unittest.TestCase):
    """The total rows at a scrolling table's end stay below its rows; any others scroll with them."""

    def test_the_total_rows_at_the_end_are_counted_and_no_others(self):
        from windowtally_gui.table_view import trailing_totals
        self.assertEqual(trailing_totals((29,), 30), 1)
        self.assertEqual(trailing_totals((28, 29), 30), 2)
        self.assertEqual(trailing_totals((3,), 30), 0)          # a total among the rows scrolls with them
        self.assertEqual(trailing_totals((), 30), 0)
        self.assertEqual(trailing_totals((0,), 1), 1)


class PointerWordsTest(unittest.TestCase):
    REST = 0.4

    def test_the_words_show_once_the_pointer_has_rested(self):
        self.assertEqual(words_due(10.0, 9.0, 0.0, self.REST), 0.0)
        self.assertAlmostEqual(words_due(10.0, 9.9, 0.0, self.REST), 0.3)

    def test_no_words_while_the_view_scrolls(self):
        self.assertAlmostEqual(words_due(10.0, 9.0, 9.9, self.REST), 0.3)
        self.assertEqual(words_due(10.0, 9.0, 9.5, self.REST), 0.0)


if __name__ == "__main__":
    unittest.main()
