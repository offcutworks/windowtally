"""What a test of the window needs: Qt on its offscreen platform, one application for the whole run, the objects a test
lets go deleted as it ends, and stand-ins for the tray icon and for the sync script, so no test shows an icon, raises a
notification or starts a program.

A test module imports this first. A PySide6 that cannot be imported is an error under every interpreter, a release's own
included, which carries Qt: it means the environment is wrong, not that the tests have nothing to run. Qt's variables of
the account running the suite go first, since one naming another plugin folder would hide a plugin a release lacks.

The tests drive Qt through ``processEvents`` and run no event loop, and Qt carries out a ``deleteLater`` only when control
returns to one, so every window a test lets go would otherwise stay alive, hidden, for the rest of the run, reached
again by every later application-wide change — a theme applied, a style sheet set. Once a real file dialog has run, the
cost of those changes grows faster than the number of windows left, enough to keep a module of window tests from ending
(PySide6 6.12.0, measured on the development machine, 2026-11-11). Every test's own cleanups are therefore followed by
those deletions, here, so that no test module has to remember them; an object a class or a module lets go is not.
"""

import os
import sys
import unittest

for name in [name for name in os.environ if name.upper().startswith("QT_")]:
    del os.environ[name]
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QEvent, QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import fixtures  # noqa: E402,F401  (puts the tool folder on the import path)
from windowtally_gui.tray_view import Tray  # noqa: E402


def application() -> QApplication:
    """The run's one application; Qt allows no second."""
    return QApplication.instance() or QApplication(sys.argv[:1])


APP = application()
APP.setQuitOnLastWindowClosed(False)


def carry_out_deletions() -> None:
    """Deletes every object a ``deleteLater`` has marked, as Qt does when control returns to its event loop, then those
    the deletions mark in turn — a widget's end can let go of its hint's words — until a pass ends no widget. One pass
    is not enough: Qt leaves a deletion asked for while it deletes to its next pass."""
    while True:
        standing = len(QApplication.allWidgets())
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if len(QApplication.allWidgets()) >= standing:
            return


_test_cleanups = unittest.TestCase.doCleanups


def _cleanups_then_deletions(test: unittest.TestCase):
    """A test's cleanups, then the deletions they asked for; unittest reports a failing cleanup and goes on to the
    next, so the deletions follow whether or not each cleanup succeeded."""
    succeeded = _test_cleanups(test)
    carry_out_deletions()
    return succeeded


unittest.TestCase.doCleanups = _cleanups_then_deletions


class StandInIcon(QObject):
    """Qt's tray icon as far as ``Tray`` uses it, recording what it was told."""

    activated = Signal(object)

    def __init__(self):
        super().__init__()
        self.shown = False
        self.tooltip = ""
        self.picture = None
        self.menu = None
        self.messages = []
        self.shows = 0

    def setContextMenu(self, menu):
        self.menu = menu

    def setIcon(self, picture):
        self.picture = picture

    def setToolTip(self, text):
        self.tooltip = text

    def show(self):
        self.shown = True
        self.shows += 1

    def hide(self):
        self.shown = False

    def showMessage(self, title, message, _icon):
        self.messages.append((title, message))


class StandInTray:
    """Makes the ``Tray`` an ``App`` asks for, on a stand-in icon, with Windows' answer held in ``held``."""

    def __init__(self):
        self.icon = StandInIcon()
        self.held = True

    def __call__(self, theme, on_click, menu):
        return Tray(theme, on_click, menu, icon=self.icon, ask_windows=lambda: self.held)


class StandInRun:
    """One run of the sync script, ended as its ``code`` and ``notes`` say; ``runs`` keeps every command line asked for."""

    runs: list = []
    code = 0
    notes: tuple = ()

    def __init__(self, argv):
        type(self).runs.append(argv)
        self.cancelled = False
        self.closing = False
        self.starting = False
        self.saving = False

    def poll(self):
        from windowtally_gui.sync_model import Result
        return Result(type(self).code, tuple(type(self).notes))

    def cancel(self):
        self.cancelled = True
        return True
