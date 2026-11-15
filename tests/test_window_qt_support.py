"""What ``qt_support`` promises every test of the window: the objects a test lets go through ``deleteLater`` are deleted
as it ends, its cleanups having run, even where one of them failed, and so is what those deletions let go in turn, so
no window of one test stands through the next."""

import unittest

from qt_support import APP

import shiboken6
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


def window() -> QWidget:
    shown = QWidget()
    QVBoxLayout(shown).addWidget(QLabel("a line", shown))
    shown.show()
    APP.processEvents()
    return shown


class DeletionsTest(unittest.TestCase):
    def run_inner(self, test_body) -> unittest.TestResult:
        """Runs ``test_body`` as a test of its own, the way the suite runs one."""

        class Inner(unittest.TestCase):
            def test_it(self):
                test_body(self)

        result = unittest.TestResult()
        Inner("test_it").run(result)
        return result

    def test_a_window_a_test_lets_go_is_gone_once_the_test_has_ended(self):
        made = []

        def body(test):
            shown = window()
            made.append(shown)
            test.addCleanup(shown.deleteLater)
            test.addCleanup(shown.hide)

        result = self.run_inner(body)
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
        self.assertEqual(len(made), 1, "the inner test made its window")
        self.assertFalse(shiboken6.isValid(made[0]))

    def test_a_cleanup_that_fails_still_leaves_no_window_standing(self):
        made = []

        def body(test):
            shown = window()
            made.append(shown)
            test.addCleanup(shown.deleteLater)
            test.addCleanup(lambda: 1 / 0)

        result = self.run_inner(body)
        self.assertEqual(len(result.errors), 1, "the failing cleanup is the test's error")
        self.assertIn("ZeroDivisionError", result.errors[0][1])
        self.assertEqual(len(made), 1, "the inner test made its window")
        self.assertFalse(shiboken6.isValid(made[0]))

    def test_what_a_deletion_lets_go_in_turn_is_gone_too(self):
        made = []

        def body(test):
            shown, words = window(), QLabel("its words")
            words.show()
            made.extend((shown, words))
            shown.destroyed.connect(words.deleteLater)
            test.addCleanup(shown.deleteLater)

        result = self.run_inner(body)
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
        self.assertEqual(len(made), 2, "the inner test made both")
        self.assertFalse(shiboken6.isValid(made[0]))
        self.assertFalse(shiboken6.isValid(made[1]))

    def test_a_window_still_held_by_the_test_is_left_alone(self):
        made = []

        def body(test):
            made.append(window())
            test.addCleanup(made[0].hide)

        result = self.run_inner(body)
        self.addCleanup(lambda: made and shiboken6.isValid(made[0]) and made[0].deleteLater())
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
        self.assertTrue(shiboken6.isValid(made[0]))


if __name__ == "__main__":
    unittest.main()
