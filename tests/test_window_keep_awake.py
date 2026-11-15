"""The keep-awake's switch in the window: in the View menu and the tray menu beside Silence notifications, on by
default, written to the settings when turned and taken up when the settings change by another hand.

Expected values follow ``windowtally_gui/app_view.py``'s statement of the switch and ``windowtally/settings.py``'s of
the key.
"""

import json
import unittest

from qt_support import StandInRun  # noqa: F401  (sets Qt's offscreen platform before PySide6 is imported)

from test_window_qt_shell import ShellCase
from windowtally.settings import load_settings

LABEL = "Keep the computer awake while Claude Code works"


def labels(menu) -> list[str]:
    return [action.text() for action in menu.actions()]


class KeepAwakeSwitchTest(ShellCase):
    def view_menu(self, shell):
        return next(a.menu() for a in shell.main.menuBar().actions() if a.text() == "View")

    def test_the_switch_stands_beside_silence_in_the_view_menu_and_the_tray_menu_and_is_on_by_default(self):
        shell = self.open()
        self.assertTrue(shell.main.keep_awake.isCheckable())
        self.assertTrue(shell.main.keep_awake.isChecked())
        for menu in (self.view_menu(shell), shell.tray_menu):
            with self.subTest(menu=menu):
                shown = labels(menu)
                self.assertIn(LABEL, shown)
                self.assertEqual(shown.index(LABEL), shown.index("Silence notifications") + 1)

    def test_turning_it_writes_the_settings_and_says_so(self):
        shell = self.open()
        shell.main.keep_awake.trigger()
        self.assertFalse(shell.main.keep_awake.isChecked())
        self.assertIs(load_settings(self.paths.settings_file).keep_awake_off, True)
        self.assertEqual(shell.main.said.text(), "The computer may sleep while Claude Code sessions work.")
        shell.main.keep_awake.trigger()
        self.assertIs(load_settings(self.paths.settings_file).keep_awake_off, False)
        self.assertNotIn("keepAwakeOff", json.loads(self.paths.settings_file.read_text(encoding="utf-8")))

    def test_settings_that_cannot_be_written_leave_the_switch_as_it_was(self):
        self.machine.settings({"v": 2})
        shell = self.open()
        self.assertTrue(shell.main.keep_awake.isChecked(), "settings that cannot be read leave it on")
        shell.main.keep_awake.trigger()
        self.assertTrue(shell.main.keep_awake.isChecked())
        self.assertTrue(shell.main.said.text().startswith("Not changed: "), shell.main.said.text())

    def test_a_change_of_the_setting_by_hand_is_followed(self):
        self.machine.settings({"v": 1, "keepAwakeOff": True})
        shell = self.open()
        self.assertFalse(shell.main.keep_awake.isChecked())
        self.machine.settings({"v": 1})
        shell._follow_settings()
        self.assertTrue(shell.main.keep_awake.isChecked())


if __name__ == "__main__":
    unittest.main()
