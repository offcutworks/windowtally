"""The window's tray icon and its notifications, through ``QSystemTrayIcon``.

A left click, or a double one, shows the window and brings it to the front — never hides it — and a right click opens
the menu. The tooltip is ``live_model.TrayView``'s and the picture ``tray_model``'s, redrawn only when either changes. On
Windows a notification goes through the tray icon, so a window whose icon could not be made raises none.

Qt reports nothing when Windows does not hold its icon, and its ``geometry`` stays empty whether or not it does, so
``present`` asks Windows itself: an icon modification that changes nothing, sent to the window Qt keeps for its icon under
the id Qt registers it by, which Windows accepts only for an icon it holds (``tray_check_model`` says what the window does
with the answer). Hiding the icon destroys that window and showing it makes another, so the window is looked for at each
question. Measured with Qt 6.12.0 on the development machine (2026-11-07), on the process's own icon: Windows refuses the
modification once the icon is removed, and Qt adds the icon again when the window receives Windows' taskbar-created
message, or on hiding and showing it.
"""

from __future__ import annotations

import functools
import logging
import os
import sys
from typing import Callable

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .common_view import image_of
from .live_model import TrayView
from .theme_view import Theme
from .tray_model import icon_rows

log = logging.getLogger(__name__)

# The window class Qt registers for the window that owns its tray icon: its name carries Qt's version before this tail.
QT_TRAY_CLASS_TAIL = "TrayIconMessageWindowClass"
QT_ICON_ID = 0
NIM_MODIFY = 1


def _system_metric(index: int, fallback: int) -> int:
    if sys.platform == "win32":
        import ctypes
        try:
            size = ctypes.windll.user32.GetSystemMetrics(index)
            if size > 0:
                return size
        except (AttributeError, OSError):
            pass
    return fallback


def icon_size() -> int:
    """The small-icon size Windows draws the tray at, in pixels (16 at 100 % scale)."""
    return _system_metric(49, 16)  # SM_CXSMICON


def icon_sizes() -> tuple[int, ...]:
    """The sizes Windows draws a window's icons at on this display, the large first: the large icon (the taskbar,
    Alt+Tab; SM_CXICON, 32 at 100 % scale) and the small one (the title bar; 16 at 100 %)."""
    return tuple(sorted({_system_metric(11, 32), icon_size()}, reverse=True))  # SM_CXICON


def picture(size: int, view: TrayView, colour: str, theme: Theme) -> QIcon:
    """The tray's picture of ``view``, its rim in ``colour``, the account in use's."""
    rows = icon_rows(size, colour, theme.c["warning"], theme.c["critical"], five_hour=view.five_hour,
                     weekly=view.weekly, five_hour_level=view.five_hour_level, weekly_level=view.weekly_level,
                     weekly_only=view.weekly_only, greyed=view.level < 0)
    return QIcon(QPixmap.fromImage(image_of(rows)))


@functools.cache
def _notify_icon_data():
    """NOTIFYICONDATAW whole, as Windows Vista and later read it."""
    import ctypes
    import ctypes.wintypes as wt

    class Guid(ctypes.Structure):
        _fields_ = [("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16), ("data3", ctypes.c_uint16),
                    ("data4", ctypes.c_ubyte * 8)]

    class NotifyIconData(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                    ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128),
                    ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                    ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                    ("guidItem", Guid), ("hBalloonIcon", wt.HICON)]

    return NotifyIconData


@functools.cache
def _shell_notify_icon():
    import ctypes
    import ctypes.wintypes as wt
    function = ctypes.WinDLL("shell32").Shell_NotifyIconW
    function.argtypes = [wt.DWORD, ctypes.POINTER(_notify_icon_data())]
    function.restype = wt.BOOL
    return function


def tray_window() -> int | None:
    """This process's window that owns Qt's tray icon, or None where there is none."""
    import ctypes
    import ctypes.wintypes as wt
    user32 = ctypes.WinDLL("user32")
    enum_proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wt.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    pid, found = os.getpid(), []

    def each(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            name = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, name, 128)
            if name.value.endswith(QT_TRAY_CLASS_TAIL):
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(enum_proc(each), 0)
    return found[0] if found else None


def holds_icon(hwnd: int, uid: int) -> bool:
    """Whether the notification area holds the icon ``uid`` of the window ``hwnd``: a modification that changes nothing,
    which Windows refuses for an icon it does not hold."""
    import ctypes
    data_type = _notify_icon_data()
    data = data_type(cbSize=ctypes.sizeof(data_type), hWnd=hwnd, uID=uid, uFlags=0)
    return bool(_shell_notify_icon()(NIM_MODIFY, ctypes.byref(data)))


def windows_holds_icon() -> bool | None:
    """Whether Windows holds Qt's icon now; None where that cannot be asked — off Windows, or with no window of Qt's for
    the icon."""
    if sys.platform != "win32":
        return None
    hwnd = tray_window()
    return None if hwnd is None else holds_icon(hwnd, QT_ICON_ID)


class TrayUnavailable(Exception):
    """The platform has no notification area to put an icon in."""


class Tray:
    """``icon`` and ``ask_windows`` stand in for Qt's icon and Windows' answer in a test."""

    def __init__(self, theme: Theme, on_click: Callable[[], None], menu: QMenu, *,
                 icon: QSystemTrayIcon | None = None, ask_windows: Callable[[], bool | None] = windows_holds_icon):
        if icon is None and not QSystemTrayIcon.isSystemTrayAvailable():
            raise TrayUnavailable("no notification area")
        self.theme, self.menu = theme, menu
        self.size = icon_size()
        self._shown: tuple | None = None
        self._ask_windows = ask_windows
        self._unaskable_said = False
        self.icon = icon if icon is not None else QSystemTrayIcon(QApplication.instance())
        self.icon.activated.connect(lambda reason: self._activated(reason, on_click))
        self.icon.setContextMenu(menu)
        blank = TrayView("WindowTally", -1, None, None, None)
        self.icon.setIcon(picture(self.size, blank, theme.c["ink-2"], theme))
        self.icon.setToolTip(blank.tooltip)
        self.icon.show()

    @staticmethod
    def _activated(reason, on_click: Callable[[], None]) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            on_click()

    def recreate(self) -> None:
        """Takes the icon down and makes it again, with the picture and tooltip last shown."""
        self.icon.hide()
        self.icon.show()

    def present(self) -> bool | None:
        """Whether Windows holds the icon now; None where that cannot be asked, which is logged once."""
        answer = self._ask_windows()
        if answer is None and not self._unaskable_said:
            self._unaskable_said = True
            log.warning("Whether the tray icon is in the notification area cannot be asked: no window of class *%s in "
                        "this process", QT_TRAY_CLASS_TAIL)
        return answer

    def show(self, view: TrayView, colour: str) -> None:
        key = (view.tooltip, view.level, view.five_hour, view.weekly, view.weekly_only, view.five_hour_level,
               view.weekly_level, colour, self.theme.mode)
        if key == self._shown:
            return
        self._shown = key
        self.icon.setIcon(picture(self.size, view, colour, self.theme))
        self.icon.setToolTip(view.tooltip)

    def notify(self, title: str, message: str) -> None:
        self.icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information)

    def destroy(self) -> None:
        self.icon.hide()
