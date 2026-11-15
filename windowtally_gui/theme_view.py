"""The window's one presentation mechanism.

Every colour a widget wears is a role (``theme_model``), applied at first paint and again at every change of mode through
``Theme.apply`` alone, which sets three things together: the colour scheme Qt asks Windows for, which is what turns the
title bar (measured with Qt 6.12.0 on the development machine, 2026-11-07: a dark scheme on a light Windows gives a dark
title bar on a window no toolkit call has touched); the palette the style draws from; and one style sheet written from
the roles, so nothing keeps a colour a change of mode would have to find. A widget names what it is by a dynamic
property (``surface``, ``ink``, ``primary``, ``chip``, ``segment``, ``help``, ``link``), never a colour; a widget that
paints itself reads ``Theme.c`` while it paints, so the repaint a change of palette and style sheet brings wears the new
mode.

``Theme.ink`` is the one door through which a role becomes a text colour, and it refuses a fill: the palette's
``warning`` and ``critical`` colour a meter and are unreadable as text, so the mistake cannot be written.

The style is Windows 11's own, which draws every control from the palette's roles in both modes; off Windows 11, where
its icon font may be missing, Fusion, which draws them too (``style_name``). The style sheet takes over the controls the
language draws its own way — the push buttons, the menu bar and the menus (the tray's included), the tips, the scroll
bars and the combo box's list — in every state the window puts them in; the check boxes and the combo box itself stay
the style's own, drawn from the roles. Every push button wears one quiet form, its face the control face under a
hairline edge, and the filled form (``primary``) is worn by the recommended account's first switch button alone, on the
main window's cards; a dialog's default answer is a quiet button too. A list's row the keyboard is on is marked by its
delegate, not by the style (``common_view.RowDelegate``). Words and figures are set in
Segoe UI Variable, the figures semibold with the font's tabular digits (OpenType ``tnum``), so every digit is one width
and a changing figure never shifts what follows it (``WORD_FAMILIES``; ``FIGURE_FAMILIES`` names the same families,
which the history page's figures follow; Qt takes the first family installed). Measured with Qt 6.12.0 on the
development machine, 2026-11-11: Segoe UI Variable Text's ten digits share one advance with ``tnum`` and take two
without it; Segoe UI, its fallback, keeps two advances either way.

What else the language lays on follows ``Theme.apply`` too:

- The page ground behind a window's content: the page colour, and in the dark mode alone a fine grid of lines one step
  off it, painted over only the region a repaint asks for, so the second's updates of the cards cost it nothing. The
  light mode lays no grid, its pale page reading as calm on its own. The main window's content
  stands in ``Ground``; the History, Bills and sources and Conversations windows, whose content stands in the window
  itself, take it through ``Theme.ground``. A dialog stands on the plain page colour: a grid behind a few lines and
  buttons would be ornament.
- The title bar, tinted to the page colour: on Windows 11 the caption colour is set through DWM on every top-level
  window as it shows and on every one shown at each change of mode, after the colour scheme, which sets the title
  bar's dark or light mode (measured with Qt 6.12.0 on the development machine, 2026-11-09: the caption keeps the
  colour set while the scheme changes, and is set again regardless). Off Windows 11 nothing is called.
- ``Motion``, the one clock everything that moves draws its frames from (``motion_model``): it runs only while
  something moves, and lets nothing move while Windows' animation effects are off.
"""

from __future__ import annotations

import sys
import time
from typing import Callable

import shiboken6
from PySide6.QtCore import QEvent, QObject, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget

from . import common_view
from .motion_model import FRAME, PULSE_FRAME
from .theme_model import caption_colour, colours

TEXT_ROLES = ("ink", "ink-2", "muted", "warning-text", "critical-text", "disabled-text", "on-primary")
FONT_GROWTH = {"bold": 0, "figure": 4, "title": 2}   # points above the default font; words bold, figures semibold
WORD_FAMILIES = ["Segoe UI Variable Text", "Segoe UI"]
FIGURE_FAMILIES = WORD_FAMILIES     # figures in the words' family, with tabular digits
GRIDDED_MODES = ("dark",)          # the modes whose page ground lays the fine grid
WINDOWS_11_BUILD = 22000
GRID = 24                  # device-independent pixels between the page grid's lines
DWMWA_CAPTION_COLOR = 35
# Windows that are no frame of their own: no title bar to tint.
UNFRAMED = (Qt.WindowType.Popup, Qt.WindowType.ToolTip, Qt.WindowType.SplashScreen, Qt.WindowType.Desktop)


def style_name(keys: list[str], build: int) -> str:
    """The style the window wears: Windows 11's on Windows 11, else Fusion. ``keys`` are Qt's styles, ``build`` Windows'
    build number, 0 off Windows."""
    return "windows11" if build >= WINDOWS_11_BUILD and "windows11" in keys else "Fusion"


def scheme_of(mode: str) -> Qt.ColorScheme:
    """The colour scheme asked of Qt: the mode's own, never left to Windows, which the user's theme may overrule."""
    return Qt.ColorScheme.Dark if mode == "dark" else Qt.ColorScheme.Light


def palette_of(c: dict[str, str]) -> QPalette:
    palette = QPalette()
    for role, name in ((QPalette.ColorRole.Window, "page"), (QPalette.ColorRole.Base, "field"),
                       (QPalette.ColorRole.AlternateBase, "surface-1"), (QPalette.ColorRole.Button, "face"),
                       (QPalette.ColorRole.WindowText, "ink"), (QPalette.ColorRole.Text, "ink"),
                       (QPalette.ColorRole.ButtonText, "ink"), (QPalette.ColorRole.Highlight, "selection"),
                       (QPalette.ColorRole.HighlightedText, "ink"), (QPalette.ColorRole.Accent, "focus"),
                       (QPalette.ColorRole.PlaceholderText, "muted"), (QPalette.ColorRole.ToolTipBase, "face"),
                       (QPalette.ColorRole.ToolTipText, "ink")):
        palette.setColor(role, QColor(c[name]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["disabled-text"]))
    return palette


def style_sheet(c: dict[str, str]) -> str:
    """The rules that say what the style does not: the surfaces, the inks, the controls the language draws its own way,
    the one primary action, the roles' chips. A card's edge is the hairline in every state: a card answers no click, so
    nothing on it changes under the pointer."""
    inks = "\n".join(f'QLabel[ink="{role}"] {{ color: {c[role]}; }}' for role in TEXT_ROLES)
    return f"""
QFrame[surface="card"] {{
    background: {c["surface-1"]}; border: 1px solid {c["edge"]}; border-radius: 8px;
}}
QFrame[surface="tile"] {{
    background: {c["surface-1"]}; border: 1px solid {c["edge"]}; border-radius: 8px;
}}
QFrame[surface="rule"] {{ background: {c["baseline"]}; border: none; }}
QFrame[surface="hairline"] {{ background: {c["edge"]}; border: none; }}
QFrame[surface="band"] {{ background: {c["advice"]}; border-radius: 4px; }}
QFrame[surface="accent"] {{ background: {c["focus"]}; border-radius: 1px; }}
QFrame[surface="accent-critical"] {{ background: {c["critical"]}; border-radius: 1px; }}
QLabel[surface="tip"] {{
    background: {c["face"]}; color: {c["ink"]}; border: 1px solid {c["edge"]}; border-radius: 4px; padding: 4px 6px;
}}
QToolTip {{ background: {c["face"]}; color: {c["ink"]}; border: 1px solid {c["edge"]}; padding: 4px 6px; }}
{inks}
QPushButton {{
    background: {c["face"]}; color: {c["ink"]}; border: 1px solid {c["edge"]}; border-radius: 5px; padding: 2px 10px;
}}
QPushButton:hover {{ background: {c["hover"]}; border-color: {c["baseline"]}; }}
QPushButton:pressed {{ background: {c["pressed"]}; border-color: {c["baseline"]}; }}
QPushButton:focus {{ border-color: {c["focus"]}; }}
QPushButton:disabled {{ background: {c["face"]}; color: {c["disabled-text"]}; border-color: {c["edge"]}; }}
QMenuBar {{ background: {c["page"]}; color: {c["ink"]}; padding: 1px 4px; }}
QMenuBar::item {{ background: transparent; color: {c["ink"]}; padding: 4px 9px; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {c["hover"]}; }}
QMenuBar::item:pressed {{ background: {c["pressed"]}; }}
QMenu {{ background: {c["surface-1"]}; color: {c["ink"]}; border: 1px solid {c["edge"]}; padding: 4px; }}
QMenu::item {{ background: transparent; color: {c["ink"]}; padding: 4px 18px 4px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c["selection"]}; color: {c["ink"]}; }}
QMenu::item:disabled {{ color: {c["disabled-text"]}; }}
QMenu::separator {{ height: 1px; background: {c["edge"]}; margin: 4px 8px; }}
QComboBox QAbstractItemView {{
    background: {c["surface-1"]}; color: {c["ink"]}; border: 1px solid {c["edge"]}; outline: none;
    selection-background-color: {c["selection"]}; selection-color: {c["ink"]};
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0px; }}
QScrollBar::handle:vertical {{ background: {c["baseline"]}; border-radius: 3px; min-height: 28px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c["baseline"]}; border-radius: 3px; min-width: 28px; margin: 2px; }}
QScrollBar::handle:hover, QScrollBar::handle:pressed {{ background: {c["muted"]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QPushButton[primary="true"] {{
    background: {c["primary"]}; color: {c["on-primary"]}; border: 1px solid {c["primary"]}; border-radius: 5px;
    padding: 2px 10px;
}}
QPushButton[primary="true"]:hover {{ background: {c["primary-hover"]}; border-color: {c["primary-hover"]}; }}
QPushButton[primary="true"]:pressed {{ background: {c["primary-pressed"]}; border-color: {c["primary-pressed"]}; }}
QPushButton[primary="true"]:focus {{ border-color: {c["focus"]}; }}
QPushButton[primary="true"]:disabled {{
    background: {c["face"]}; color: {c["disabled-text"]}; border-color: {c["baseline"]};
}}
QLabel[chip] {{ color: {c["ink"]}; background: {c["chip"]}; border-radius: 4px; padding: 0px 5px; }}
QPushButton[segment] {{
    background: {c["face"]}; color: {c["ink"]}; border: 1px solid {c["edge"]}; border-radius: 0px; padding: 2px 10px;
}}
QPushButton[segment="first"] {{ border-top-left-radius: 5px; border-bottom-left-radius: 5px; }}
QPushButton[segment="middle"] {{ border-left: none; }}
QPushButton[segment="last"] {{ border-left: none; border-top-right-radius: 5px; border-bottom-right-radius: 5px; }}
QPushButton[segment]:checked {{ background: {c["selection"]}; }}
QPushButton[segment]:hover {{ background: {c["hover"]}; }}
QPushButton[segment]:pressed {{ background: {c["pressed"]}; }}
QPushButton[segment]:focus {{ border-color: {c["focus"]}; }}
QPushButton[segment]:disabled {{ background: {c["face"]}; color: {c["disabled-text"]}; }}
QLabel[help="true"] {{ border: 1px solid transparent; border-radius: 3px; padding: 0px 4px; }}
QLabel[help="true"]:focus {{ border-color: {c["focus"]}; }}
QLabel[link="true"] {{ border: 1px solid transparent; border-radius: 3px; }}
QLabel[link="true"]:hover {{ border-color: {c["baseline"]}; }}
QLabel[link="true"]:focus {{ border-color: {c["focus"]}; }}
QTreeWidget {{ background: {c["field"]}; border: 1px solid {c["baseline"]}; border-radius: 6px; }}
QTreeWidget:focus {{ border-color: {c["focus"]}; }}
QTreeWidget::item:hover {{ background: {c["hover"]}; }}
QTreeWidget::item:selected {{ background: {c["selection"]}; color: {c["ink"]}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: transparent; color: {c["ink-2"]}; border: none; border-bottom: 1px solid {c["baseline"]};
    padding: 3px;
}}
"""


def set_caption(window: int, colour: int) -> bool:
    """Sets the caption colour of the native window ``window`` through DWM; whether DWM took it."""
    import ctypes
    from ctypes import wintypes
    value = wintypes.DWORD(colour)
    try:
        return ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(window), DWMWA_CAPTION_COLOR,
                                                          ctypes.byref(value), ctypes.sizeof(value)) == 0
    except (AttributeError, OSError):
        return False


def framed(widget: QWidget) -> bool:
    """Whether ``widget`` is a top-level window with a title bar of its own: no menu, tip or splash."""
    return widget.isWindow() and widget.windowType() not in UNFRAMED


class _Shown(QObject):
    """One per application: tints each framed window's title bar as it shows, through the theme in use."""

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.theme: "Theme | None" = None
        app.installEventFilter(self)

    @staticmethod
    def of(app: QApplication) -> "_Shown":
        found = app.findChild(_Shown)
        return found if found is not None else _Shown(app)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Show and self.theme is not None and isinstance(watched, QWidget):
            self.theme.tint(watched)
        return False


def paint_ground(widget: QWidget, area: QRect, c: dict[str, str], mode: str) -> None:
    """The page ground over ``area`` of ``widget``: the page colour, under a fine grid in ``page-grid``, ``GRID``
    pixels apart from the widget's corner, in a mode of ``GRIDDED_MODES``."""
    painter = QPainter(widget)
    painter.fillRect(area, QColor(c["page"]))
    if mode not in GRIDDED_MODES:
        painter.end()
        return
    pen = QPen(QColor(c["page-grid"]))
    pen.setCosmetic(True)
    pen.setWidth(1)
    painter.setPen(pen)
    for x in range(area.left() - area.left() % GRID, area.right() + 1, GRID):
        painter.drawLine(x, area.top(), x, area.bottom())
    for y in range(area.top() - area.top() % GRID, area.bottom() + 1, GRID):
        painter.drawLine(area.left(), y, area.right(), y)
    painter.end()


class Ground(QWidget):
    """The page ground behind a window's content, as a widget its content stands in (the main window's), read from the
    theme while it paints, over only the region the repaint asks for."""

    def __init__(self, theme: "Theme", parent: QWidget | None = None):
        super().__init__(parent)
        self.theme = theme
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def paintEvent(self, event) -> None:
        paint_ground(self, event.rect(), self.theme.c, self.theme.mode)


class _Grounded(QObject):
    """The page ground under a window whose content stands in the window itself: painted as the window's own paint
    event begins, over only the region it asks for, so its children, which fill no background of their own, stand on
    it as the main window's content stands on ``Ground``."""

    def __init__(self, theme: "Theme", window: QWidget):
        super().__init__(window)
        self.theme = theme
        window.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Paint:
            paint_ground(watched, event.rect(), self.theme.c, self.theme.mode)
        return False


class Motion(QObject):
    """The one clock everything that moves draws its frames from. A widget that moves asks for frames (``want``),
    ``fast`` while it sweeps, and gives them up once it stands still (``done``); the clock runs only while some widget
    wants them, at ``FRAME`` while one sweeps and at ``PULSE_FRAME`` while they only pulse, and repaints only those a
    person can see: a hidden widget is let go, and while every one left stands in a minimized window the clock only
    looks once a second for the window's return. ``animations`` says whether Windows' animation effects are on, read
    at every frame and at every start, so switching them off stops what moves at once."""

    ASLEEP = 1.0    # seconds between looks while everything that moves stands in a minimized window

    def __init__(self, animations: Callable[[], bool] | None = None, clock: Callable[[], float] = time.monotonic):
        super().__init__()
        self.animations = animations if animations is not None else common_view.animations_on
        self.clock = clock
        self.movers: dict[QWidget, bool] = {}     # each widget that moves, and whether it sweeps
        self.watched: set[int] = set()            # the widgets whose end is watched, so each is watched once
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._frame)

    def allowed(self) -> bool:
        return self.animations()

    def now(self) -> float:
        return self.clock()

    def want(self, widget: QWidget, fast: bool = False) -> None:
        if id(widget) not in self.watched:
            self.watched.add(id(widget))
            widget.destroyed.connect(lambda _gone=None, w=widget, key=id(widget): self._gone(w, key))
        self.movers[widget] = fast
        self._pace()

    def done(self, widget: QWidget) -> None:
        self.movers.pop(widget, None)
        self._pace()

    def _gone(self, widget: QWidget, key: int) -> None:
        self.watched.discard(key)
        self.done(widget)

    def _pace(self, asleep: bool = False) -> None:
        # As the interpreter exits, a widget can be destroyed, or let go, after Qt has deleted the clock's timer; there
        # is then no clock left to pace, and touching its timer would raise.
        if not shiboken6.isValid(self.timer):
            return
        if not self.movers:
            self.timer.stop()
            return
        seconds = self.ASLEEP if asleep else FRAME if any(self.movers.values()) else PULSE_FRAME
        interval = round(seconds * 1000)
        if self.timer.interval() != interval or not self.timer.isActive():
            self.timer.start(interval)

    def _frame(self) -> None:
        asleep = True
        for widget in list(self.movers):
            if not widget.isVisible():
                self.done(widget)      # a hidden widget asks again as it shows
            elif not widget.window().isMinimized():
                asleep = False
                widget.update()
        self._pace(asleep)


def windows_build() -> int:
    return sys.getwindowsversion().build if sys.platform == "win32" else 0


def caption_setter(app: QApplication) -> Callable[[int, int], bool] | None:
    """What sets a title bar's colour here: DWM on Windows 11's own windows, nothing anywhere else."""
    if app.platformName() == "windows" and windows_build() >= WINDOWS_11_BUILD:
        return set_caption
    return None


class Theme:
    def __init__(self, app: QApplication, mode: str, *, caption: Callable[[int, int], bool] | None = None,
                 animations: Callable[[], bool] | None = None):
        """``caption`` sets a native window's caption colour, DWM's where not given (``caption_setter``);
        ``animations`` says whether Windows' animation effects are on, Windows' own setting where not given."""
        self.app = app
        self.mode = mode
        self.c = colours(mode)
        self.caption = caption if caption is not None else caption_setter(app)
        self.motion = Motion(animations)      # the theme's own, ending with it
        app.setStyle(style_name(QStyleFactory.keys(), windows_build()))
        base = QFont(app.font())
        base.setFamilies(WORD_FAMILIES)
        app.setFont(base)
        size = base.pointSizeF() if base.pointSizeF() > 0 else 9.0
        self.fonts: dict[str, QFont] = {}
        for name, grow in FONT_GROWTH.items():
            font = QFont(base)
            font.setPointSizeF(size + grow)
            if name == "figure":
                font.setFamilies(FIGURE_FAMILIES)
                font.setWeight(QFont.Weight.DemiBold)
                font.setFeature(QFont.Tag("tnum"), 1)
            else:
                font.setBold(True)
            self.fonts[name] = font
        _Shown.of(app).theme = self
        self.apply(mode)

    def apply(self, mode: str) -> None:
        """The one entry point: first paint and every change of mode. The title bars follow the colour scheme, which
        sets their own light or dark mode."""
        self.mode = mode
        self.c = colours(mode)
        self.app.styleHints().setColorScheme(scheme_of(mode))
        self.app.setPalette(palette_of(self.c))
        self.app.setStyleSheet(style_sheet(self.c))
        for widget in self.app.topLevelWidgets():
            if widget.isVisible():
                self.tint(widget)

    def ground(self, window: QWidget) -> None:
        """Lays the page ground under ``window``, a window whose content stands in it rather than in a ``Ground``."""
        _Grounded(self, window)

    def tint(self, widget: QWidget) -> None:
        """Tints the title bar of ``widget``, a framed window, to the page colour; anything else is left alone."""
        if self.caption is not None and framed(widget):
            self.caption(int(widget.winId()), caption_colour(self.c["page"]))

    def ink(self, label: QWidget, role: str) -> None:
        """Writes ``label`` in the text role ``role``; a role that is no text colour is refused."""
        if role not in TEXT_ROLES:
            raise ValueError(f"{role} is no text role")
        self.mark(label, "ink", role)

    @staticmethod
    def mark(widget: QWidget, name: str, value: object) -> None:
        """Sets the dynamic property the style sheet reads, the widget restyled only where it changed."""
        if widget.property(name) != value:
            widget.setProperty(name, value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
