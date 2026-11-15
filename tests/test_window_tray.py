"""The tray icon's check: Windows asked whether it holds the icon, a refusal looked at again, the icon made again while
it is missing, and a window started hidden shown once the icon has been missing for long enough, with what it says."""

import unittest

import fixtures  # noqa: F401  (puts the tool folder on the import path)
from windowtally_gui.tray_check_model import (BACK_SAID, CHECK_MISSING_S, CHECK_PRESENT_S, MISSING_SAID,
                                              MISSING_SHOWN_SAID, SHOW_AFTER_S, TrayWatch)

T0 = 1_000_000.0


class TrayWatchTest(unittest.TestCase):
    def setUp(self):
        self.watch = TrayWatch()

    def missing_from(self, at: float, hidden: bool = True):
        """Two refusals running, the second ``CHECK_MISSING_S`` after the first: the icon is missing from ``at``."""
        self.watch.on_check(False, at, hidden=hidden)
        return self.watch.on_check(False, at + CHECK_MISSING_S, hidden=hidden)

    def test_an_icon_held_is_asked_about_again_a_minute_later_and_nothing_else_happens(self):
        step = self.watch.on_check(True, T0, hidden=True)
        self.assertEqual((step.recreate, step.show, step.say, step.note), (False, False, None, None))
        self.assertEqual(step.next_check_s, CHECK_PRESENT_S)
        self.assertFalse(self.watch.missing)

    def test_an_answer_that_cannot_be_had_changes_nothing(self):
        step = self.watch.on_check(None, T0, hidden=True)
        self.assertEqual((step.recreate, step.show, step.say), (False, False, None))
        self.assertEqual(step.next_check_s, CHECK_PRESENT_S)
        self.assertFalse(self.watch.missing)

    def test_one_refusal_is_looked_at_again_soon_before_anything_is_done(self):
        # Windows also refuses while Explorer is too busy to answer: an icon on show is not torn down for that.
        step = self.watch.on_check(False, T0, hidden=True)
        self.assertEqual((step.recreate, step.show, step.say, step.note), (False, False, None, None))
        self.assertEqual(step.next_check_s, CHECK_MISSING_S)
        self.assertFalse(self.watch.missing)
        held = self.watch.on_check(True, T0 + CHECK_MISSING_S, hidden=True)
        self.assertEqual((held.recreate, held.say, held.note), (False, None, None))
        self.assertFalse(self.watch.missing)

    def test_a_refusal_that_did_not_follow_another_starts_the_count_afresh(self):
        self.watch.on_check(False, T0, hidden=True)
        self.watch.on_check(True, T0 + CHECK_MISSING_S, hidden=True)
        again = self.watch.on_check(False, T0 + 100, hidden=True)
        self.assertFalse(again.recreate)
        self.assertFalse(self.watch.missing)

    def test_a_missing_icon_is_made_again_every_few_seconds_and_logged_once(self):
        first = self.missing_from(T0)
        self.assertTrue(first.recreate)
        self.assertEqual(first.next_check_s, CHECK_MISSING_S)
        self.assertIsNotNone(first.note)
        self.assertIsNone(first.say)
        self.assertTrue(self.watch.missing)
        next_ = self.watch.on_check(False, T0 + 2 * CHECK_MISSING_S, hidden=True)
        self.assertTrue(next_.recreate)
        self.assertIsNone(next_.note)
        self.assertFalse(next_.show)

    def test_an_icon_back_at_logon_before_the_bound_shows_nothing_and_says_nothing(self):
        # The logon case: refused at the start, held after the next try; the window stays in the tray.
        self.missing_from(T0)
        step = self.watch.on_check(True, T0 + 2 * CHECK_MISSING_S, hidden=True)
        self.assertEqual((step.recreate, step.show, step.say), (False, False, None))
        self.assertIn("10 s", step.note)
        self.assertFalse(self.watch.missing)
        self.assertEqual(step.next_check_s, CHECK_PRESENT_S)

    def test_a_hidden_window_shows_itself_once_the_icon_has_been_missing_for_the_bound(self):
        # The bound counts from the first refusal.
        self.missing_from(T0)
        before = self.watch.on_check(False, T0 + SHOW_AFTER_S - 1, hidden=True)
        self.assertFalse(before.show)
        self.assertIsNone(before.say)
        at = self.watch.on_check(False, T0 + SHOW_AFTER_S, hidden=True)
        self.assertTrue(at.show)
        self.assertTrue(at.recreate)
        self.assertEqual(at.say, MISSING_SHOWN_SAID)
        self.assertFalse(at.ok)
        self.assertIn("shows itself", at.note)
        # Said once: the next looks go on making the icon again without showing or saying it again.
        later = self.watch.on_check(False, T0 + SHOW_AFTER_S + CHECK_MISSING_S, hidden=True)
        self.assertEqual((later.recreate, later.show, later.say), (True, False, None))

    def test_a_window_not_hidden_is_told_without_being_said_to_show_itself(self):
        self.missing_from(T0, hidden=False)
        step = self.watch.on_check(False, T0 + SHOW_AFTER_S, hidden=False)
        self.assertFalse(step.show)
        self.assertEqual(step.say, MISSING_SAID)
        self.assertNotIn("shows itself", step.say)

    def test_the_icons_return_is_said_where_its_absence_was(self):
        self.missing_from(T0)
        self.watch.on_check(False, T0 + SHOW_AFTER_S, hidden=True)
        step = self.watch.on_check(True, T0 + SHOW_AFTER_S + CHECK_MISSING_S, hidden=False)
        self.assertEqual(step.say, BACK_SAID)
        self.assertTrue(step.ok)
        self.assertFalse(self.watch.missing)

    def test_an_icon_lost_again_later_starts_a_fresh_count(self):
        self.missing_from(T0)
        self.watch.on_check(False, T0 + SHOW_AFTER_S, hidden=True)
        self.watch.on_check(True, T0 + SHOW_AFTER_S + 5, hidden=False)
        later = T0 + 10_000
        lost = self.missing_from(later)
        self.assertIsNotNone(lost.note)
        self.assertFalse(lost.show)
        self.assertEqual(self.watch.on_check(False, later + SHOW_AFTER_S, hidden=True).say, MISSING_SHOWN_SAID)


if __name__ == "__main__":
    unittest.main()
