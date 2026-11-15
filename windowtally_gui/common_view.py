"""Window idioms every one of WindowTally's windows shares.

- Qt declares the process per-monitor DPI-aware itself and draws in device-independent pixels, so a size given here is a
  size at 100 % display scale and reads the same at 200 %. ``em`` sizes from the default font, for spacing beside text,
  as the maintainer's sizes in lines of the default font are given.
- ``window.json`` keeps a place in the display's own pixels, the top left of the frame and the size of what is inside it.
  ``native_place`` and ``logical_place`` turn such a place into Qt's terms and back, screen by screen: Qt keeps each
  screen's origin and scales what lies inside it. ``work_areas`` gives each monitor's working area in the same pixels.
- ``image_of`` makes a picture drawn as pixels (the logo, the tray's rings) a ``QImage``, drawing nothing itself.
- ``ScrollFrame`` scrolls as far as Windows' wheel setting says (``scroll_model``), notches arriving between two repaints
  scrolled in one step. ``WheelRouter``, one per application, sends each turn of the wheel where ``scroll_model`` says,
  from the widget under the pointer, so a gesture keeps to the view that took its first turn; Shift and the wheel go
  sideways over a widget that carries ``wheel_sideways``.
- ``Tip`` is the one small window of words a hint or a chart's mark shows, made once and moved, never a new window for
  each mark. It keeps to the screen's working area: where its words would pass the area's right or bottom edge they turn
  to the other side of the pointer or the control they belong to (``tip_place``). ``Hint`` shows a control's full
  text, or what it does, while the pointer rests on it and, given ``focus``, while the control has the keyboard focus:
  a hint that carries what something means is given it, so it is reached without a mouse.
- ``RowList`` is the form a list of records takes in a window of forms: rows under headings, one chosen at a time. A row
  that can be ticked draws its own tick box (``TickDelegate``), from the palette's roles, and the row the keyboard is
  on, while the list has the focus, wears a strip of the focus colour at its left (``RowDelegate``) where the style
  would frame it. A list given the height a window has left over stands in ``WholeRows``, at a whole number of its
  rows, so it never ends in a row cut through its words.
- ``card_margins`` is the padding every panel on the page wears — the main window's cards, the History window's tiles,
  the Bills and sources form — so the windows share one density.
"""

from __future__ import annotations

import math
import sys
import time
from typing import Callable, Iterable, Sequence

import shiboken6
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import (QFontMetrics, QFontMetricsF, QGuiApplication, QImage, QPainter, QPainterPath, QPalette, QPen,
                           QRegion, QScreen)
from PySide6.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QApplication, QComboBox, QFrame, QHeaderView, QLabel,
                               QPlainTextEdit, QScrollArea, QSizePolicy, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QTextEdit, QTreeWidget, QTreeWidgetItem, QWidget)

from windowtally.history import WHEEL_PAUSE

from .logo_model import Pixel
from .scroll_model import Gesture, inner_takes, scroll_bars, wheel_steps, wheel_turn, whole_rows_height
from .state_model import Area

APP_ID = "WindowTally.Window"
WHEEL_LINES = 3            # Windows' default lines a notch, where the setting cannot be read
HOVER_MS = 400             # Windows' default hover time, likewise
DRAG_PIXELS = 4            # Windows' default drag threshold, likewise
HINT_MS = 600              # how long the pointer rests on a control before its hint shows
CELL_MARGINS = 2           # digits of the default font a list's cell gives to its two margins
TICK_CORNER = 0.2          # a tick box's corner radius, in its side
TICK_STROKE = 0.12         # the tick's stroke, in the box's side
TICK_MARK = ((0.24, 0.53), (0.42, 0.70), (0.76, 0.32))   # the tick's three points, in the box's side
CURRENT_STRIP = 0.15       # the strip marking the row the keyboard is on, wide, in lines of the default font
CURRENT_INSET = 0.15       # how far the strip stands in from its row's top and bottom, in lines of the default font


def claim_identity(app_id: str = APP_ID) -> None:
    """An application identity of the process's own; where Windows refuses, the taskbar groups the window by its
    interpreter, as it would anyway — the identity decides nothing."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        pass


def em(n: float) -> int:
    """``n`` times the default font's line height, in device-independent pixels."""
    return int(n * QFontMetrics(QApplication.font()).lineSpacing())


def digits(n: float) -> int:
    """The width of ``n`` digits of the default font, in device-independent pixels, never under what they take: a
    digit's width is a fraction of a pixel on a scaled display, and rounded to a whole one before the count is taken
    it makes a column of 24 digits up to 12 pixels too narrow (measured on the development machine, 2026-11-10: 6.47
    pixels a digit at 150 % and 200 %, 6 as a whole number)."""
    return math.ceil(n * QFontMetricsF(QApplication.font()).horizontalAdvance("0"))


def card_margins() -> tuple[int, int, int, int]:
    """A panel's padding, left, top, right and bottom: three quarters of a line at its sides, half a line above and
    below, as the main window's cards stand."""
    pad = em(0.5)
    return int(pad * 1.5), pad, int(pad * 1.5), pad


def fixed_words(label: QLabel, width: int) -> QLabel:
    """``label``, its words wrapped, held at ``width`` and as tall as its words are at that width. A layout asks a
    wrapped label its height at the column's width, which in a column wider than the label gives one line for a
    paragraph, and a window fixed to its layout's height would then be too short for what it holds; the label's text
    is set before this is called and not changed after."""
    label.setWordWrap(True)
    label.setFixedWidth(width)
    label.ensurePolished()        # measured in the font the style gives it, not the one it was made with
    label.setMinimumHeight(label.heightForWidth(width))
    return label


def plain_label(parent: QWidget | None = None) -> QLabel:
    """A label that writes its text as it stands: Qt's default reads text that looks like HTML as markup, and a name, an
    e-mail or an error is the user's or the system's words."""
    label = QLabel(parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def image_of(rows: list[list[Pixel]]) -> QImage:
    """A picture drawn as pixels (``logo_model``'s rows) as a QImage of its own pixels."""
    height, width = len(rows), len(rows[0]) if rows else 0
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    for y, row in enumerate(rows):
        line = image.scanLine(y)
        line[0:width * 4] = b"".join(bytes(pixel) for pixel in row)
    return image


def rounded_path(width: float, height: float, top: float, bottom: float) -> QPainterPath:
    """A rectangle ``width`` by ``height`` at the origin, its top corners rounded by ``top`` and its bottom ones by
    ``bottom``, as the history page's charts round a column's data end."""
    path = QPainterPath(QPointF(0, top))
    path.quadTo(0, 0, top, 0)
    path.lineTo(width - top, 0)
    path.quadTo(width, 0, width, top)
    path.lineTo(width, height - bottom)
    path.quadTo(width, height, width - bottom, height)
    path.lineTo(bottom, height)
    path.quadTo(0, height, 0, height - bottom)
    path.closeSubpath()
    return path


def _system_value(action: int, default: int) -> int:
    """One of Windows' SystemParametersInfo numbers, or ``default`` where it cannot be read."""
    if sys.platform != "win32":
        return default
    import ctypes
    from ctypes import wintypes
    value = wintypes.UINT()
    try:
        if ctypes.windll.user32.SystemParametersInfoW(action, 0, ctypes.byref(value), 0):
            return value.value
    except (AttributeError, OSError):
        pass
    return default


def wheel_lines() -> int:
    """Windows' lines a wheel notch scrolls (SPI_GETWHEELSCROLLLINES), read at each turn so a change applies at once;
    ``scroll_model.PAGE`` for a screen at a time."""
    return _system_value(0x0068, WHEEL_LINES)


def hover_ms() -> int:
    """Windows' hover time (SPI_GETMOUSEHOVERTIME): how long the pointer rests before what it rests on responds."""
    return _system_value(0x0066, HOVER_MS)


def animations_on() -> bool:
    """Whether Windows' animation effects are on (SPI_GETCLIENTAREAANIMATION, the number Settings' Accessibility, Visual
    effects, Animation effects sets, by Microsoft's documentation), read at each call so a change applies at once; on
    where it cannot be read, as Windows' default is."""
    return bool(_system_value(0x1042, 1))


def drag_slop() -> tuple[int, int]:
    """Windows' drag threshold across and down (SM_CXDRAG, SM_CYDRAG): how far the pointer moves before it has moved."""
    if sys.platform != "win32":
        return DRAG_PIXELS, DRAG_PIXELS
    import ctypes
    try:
        metric = ctypes.windll.user32.GetSystemMetrics
        return metric(68) or DRAG_PIXELS, metric(69) or DRAG_PIXELS
    except (AttributeError, OSError):
        return DRAG_PIXELS, DRAG_PIXELS


def native_place(frame_x: int, frame_y: int, width: int, height: int, origin: tuple[int, int],
                 ratio: float) -> tuple[int, int, int, int]:
    """Width, height, x and y in the display's pixels of a window whose frame stands at (``frame_x``, ``frame_y``) in
    Qt's terms and whose inside is ``width`` by ``height``, on a screen with its origin at ``origin`` and ``ratio``
    pixels to Qt's one."""
    return (round(width * ratio), round(height * ratio), origin[0] + round((frame_x - origin[0]) * ratio),
            origin[1] + round((frame_y - origin[1]) * ratio))


def logical_place(width: int, height: int, x: int, y: int, origin: tuple[int, int],
                  ratio: float) -> tuple[int, int, int, int]:
    """``native_place`` undone: width, height, x and y in Qt's terms."""
    return (round(width / ratio), round(height / ratio), origin[0] + round((x - origin[0]) / ratio),
            origin[1] + round((y - origin[1]) / ratio))


def screen_at(x: int, y: int) -> QScreen:
    """The screen holding the display pixel (``x``, ``y``), else the primary one."""
    for screen in QGuiApplication.screens():
        area, ratio = screen.geometry(), screen.devicePixelRatio()
        if QRect(area.topLeft(), QSize(round(area.width() * ratio), round(area.height() * ratio))).contains(x, y):
            return screen
    return QGuiApplication.primaryScreen()


def place_of_window(window: QWidget) -> tuple[int, int, int, int]:
    """The window's width, height, x and y in the display's pixels."""
    screen, frame, inside = window.screen(), window.frameGeometry(), window.geometry()
    origin = screen.geometry().topLeft()
    return native_place(frame.x(), frame.y(), inside.width(), inside.height(), (origin.x(), origin.y()),
                        screen.devicePixelRatio())


def put_window(window: QWidget, width: int, height: int, x: int, y: int) -> None:
    """Gives the window a place in the display's pixels."""
    screen = screen_at(x, y)
    origin = screen.geometry().topLeft()
    w, h, left, top = logical_place(width, height, x, y, (origin.x(), origin.y()), screen.devicePixelRatio())
    window.resize(w, h)
    window.move(left, top)


def work_areas() -> tuple[Area, ...]:
    """Each monitor's working area — its screen less the taskbar — the main monitor's first, in the display's pixels.
    Where Windows cannot be asked, Qt's screens."""
    def from_qt() -> tuple[Area, ...]:
        found = []
        for screen in QGuiApplication.screens():
            area, ratio = screen.availableGeometry(), screen.devicePixelRatio()
            found.append(Area(area.left(), area.top(), area.left() + round(area.width() * ratio),
                              area.top() + round(area.height() * ratio)))
        return tuple(found) or (Area(0, 0, 1280, 720),)

    if sys.platform != "win32":
        return from_qt()
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    found = []

    def visit(monitor, _dc, _rect, _data):
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            work = info.rcWork
            found.append((not info.dwFlags & 1, Area(work.left, work.top, work.right, work.bottom)))
        return True

    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                  wintypes.LPARAM)(visit)
    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, callback, 0)
    except (AttributeError, OSError):
        return from_qt()
    areas = tuple(area for _secondary, area in sorted(found, key=lambda f: f[0]) if area.width > 0 and area.height > 0)
    return areas or from_qt()


def size_to_content(window: QWidget, parent: QWidget | None = None) -> None:
    """Opens ``window`` at what its content asks for, within 90 % of the screen, over ``parent`` where it shows; nothing
    opens with its buttons off-screen. ``adjustSize`` readies the layout, which holds the window to its least size, but
    stops at two thirds of the screen, which leaves a list's last columns behind its scroll bar on a display with room for
    them, so the content is asked again."""
    window.adjustSize()
    hint = window.sizeHint()
    screen = (parent.screen() if parent is not None and parent.isVisible() else QGuiApplication.primaryScreen())
    area = screen.availableGeometry()
    width = min(max(window.width(), hint.width()), int(area.width() * 0.9))
    layout = window.layout()
    asked = (layout.totalHeightForWidth(width) if layout is not None and layout.hasHeightForWidth()
             else max(window.height(), hint.height()))
    height = min(asked, int(area.height() * 0.9))
    window.resize(width, height)
    over = parent.frameGeometry() if parent is not None and parent.isVisible() else area
    x = over.left() + (over.width() - width) // 2
    y = over.top() + (over.height() - height) // 3
    window.move(max(area.left(), min(x, area.right() - width)), max(area.top(), min(y, area.bottom() - height)))


def dialog_owner(parent: QWidget | None) -> QWidget | None:
    """The window a dialog opens over: ``parent`` while it shows, else None, a minimized window included, since Windows
    does not show what it owns; the dialog is then a window of its own, at the front."""
    return parent if parent is not None and parent.isVisible() and not parent.isMinimized() else None


def set_on_top(window: QWidget, on: bool) -> None:
    """Keeps ``window`` above others or lets it go, through its native window where it has one: the widget's own flag
    would hide the window to change it. The hints are masked as numbers: PySide6's ``~hint`` holds only the lower bits, so
    ``flags & ~hint`` also clears the close button's hint and Windows greys the button (measured on the development
    machine with PySide6 6.12.0, 2026-11-08)."""
    hint = Qt.WindowType.WindowStaysOnTopHint
    handle = window.windowHandle()
    if handle is not None:
        handle.setFlag(hint, on)
    flags = window.windowFlags()
    window.overrideWindowFlags(flags | hint if on else Qt.WindowType(flags.value & ~hint.value))


_SELF_SCROLLING = (QAbstractItemView, QTextEdit, QPlainTextEdit, QComboBox, QAbstractSpinBox)


class _QtViews:
    """The window's widgets as ``scroll_model.WheelViews``. A widget scrolling within a view carries ``wheel_inside``, a
    function of the wheel's delta that scrolls it and says whether it took the turn; a ScrollFrame is a frame."""

    @staticmethod
    def parent(view):
        return view.parentWidget()

    @staticmethod
    def takes_inside(view, delta: int) -> bool:
        inside = getattr(view, "wheel_inside", None)
        return inside is not None and bool(inside(delta))

    @staticmethod
    def is_frame(view) -> bool:
        return isinstance(view, ScrollFrame)

    @staticmethod
    def scroll(view, delta: int) -> None:
        view.scroll(delta)

    @staticmethod
    def can_move(view, delta: int) -> bool:
        return view.can_move(delta)

    @staticmethod
    def exists(view) -> bool:
        return shiboken6.isValid(view)

    @staticmethod
    def window(view):
        return view.window()


class WheelRouter(QObject):
    """The one application-wide wheel handler, unless the pointer is over a widget that scrolls itself or a popup is up:
    where the turn goes is ``scroll_model.wheel_turn``'s to decide, from the widget under the pointer."""

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.gesture = Gesture()
        self.scrolled_at = 0.0      # when a view last scrolled, on ``time.monotonic``'s clock; 0 if none has
        app.installEventFilter(self)

    @classmethod
    def of(cls, app: QApplication) -> "WheelRouter":
        found = app.findChild(cls)
        return found if found is not None else cls(app)

    def eventFilter(self, _watched, event) -> bool:
        if event.type() != QEvent.Type.Wheel:
            return False
        delta, at = event.angleDelta().y(), event.globalPosition().toPoint()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and self.sideways(delta, at):
            return True
        return self.turn(delta, at)

    def sideways(self, delta: int, at: QPoint) -> bool:
        """Whether a turn with Shift held went sideways: to the widget under the pointer carrying ``wheel_sideways``, a
        function of the wheel's delta, the view around it staying where it is. Over anything else the turn scrolls as a
        turn without Shift does."""
        widget = QApplication.widgetAt(at)
        moved = getattr(widget, "wheel_sideways", None)
        if moved is None or not delta or QApplication.activePopupWidget() is not None:
            return False
        moved(delta)
        return True

    def turn(self, delta: int, at: QPoint) -> bool:
        """Whether a turn of ``delta`` wheel units at ``at`` on the screen was taken."""
        if not delta or QApplication.activePopupWidget() is not None:
            return False
        widget = QApplication.widgetAt(at)
        if widget is None or isinstance(widget, _SELF_SCROLLING):
            return False
        owner = wheel_turn(self.gesture, widget, delta, time.monotonic(), at.x(), at.y(), WHEEL_PAUSE, _QtViews,
                           drag_slop)
        return owner is not None


def scrolled_at() -> float:
    """When a view of the application last scrolled, on ``time.monotonic``'s clock; 0 if none has."""
    return WheelRouter.of(QApplication.instance()).scrolled_at


class ScrollFrame(QScrollArea):
    """A vertically scrolling frame; put content in ``.body``. It scrolls by the wheel wherever the pointer is over it,
    its children included, and shows its scroll bar only while the content is taller than the frame."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.router = WheelRouter.of(QApplication.instance())
        self.body = QWidget()
        self.setWidget(self.body)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.verticalScrollBar().valueChanged.connect(self._moved)
        self.viewport().setAutoFillBackground(False)
        self.body.setAutoFillBackground(False)
        self._wheel = 0             # wheel units arrived since the last step
        self._carried = 0           # wheel units short of a whole line, kept for the next turn
        self._stepping = False

    def _moved(self, _value: int) -> None:
        """The view moved, by the wheel, its bar or the keyboard: nothing under the pointer is at rest."""
        self.router.scrolled_at = time.monotonic()

    def can_move(self, delta: int) -> bool:
        """Whether the view can still move the way a turn of ``delta`` wheel units goes."""
        bar = self.verticalScrollBar()
        whole = bar.maximum() + bar.pageStep()
        if whole <= 0:
            return False
        return inner_takes(bar.value() / whole, (bar.value() + bar.pageStep()) / whole, delta)

    def scroll(self, delta: int) -> None:
        """Takes a turn of the wheel; the view moves once the window is idle, by every turn taken until then."""
        self.router.scrolled_at = time.monotonic()
        self._wheel += delta
        if not self._stepping:
            self._stepping = True
            QTimer.singleShot(0, self, self._step)

    def _step(self) -> None:
        self._stepping = False
        delta, self._wheel = self._wheel, 0
        count, what, self._carried = wheel_steps(delta, self._carried, wheel_lines())
        bar = self.verticalScrollBar()
        if count:
            bar.setValue(bar.value() + count * (bar.pageStep() if what == "pages" else em(1)))


def draw_tick_box(painter: QPainter, box: QRect, palette: QPalette, ticked: bool) -> None:
    """Draws a tick box in ``box``: ticked, filled with the palette's accent under a tick in the field's colour; not
    ticked, the field's colour edged in the placeholder ink. Each pair is 3:1 or more on a list's field, hover and
    selection in both modes (the suite measures them)."""
    side = min(box.width(), box.height())
    square = QRectF(box.x() + (box.width() - side) / 2 + 0.5, box.y() + (box.height() - side) / 2 + 0.5,
                    side - 1, side - 1)
    accent, field = palette.color(QPalette.ColorRole.Accent), palette.color(QPalette.ColorRole.Base)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(accent if ticked else palette.color(QPalette.ColorRole.PlaceholderText), 1))
    painter.setBrush(accent if ticked else field)
    painter.drawRoundedRect(square, side * TICK_CORNER, side * TICK_CORNER)
    if ticked:
        stroke = QPen(field, max(1.5, side * TICK_STROKE))
        stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(stroke)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline([QPointF(square.x() + x * square.width(), square.y() + y * square.height())
                              for x, y in TICK_MARK])


class TickDelegate(QStyledItemDelegate):
    """Draws the tick box of a row that can be ticked, in place of the style's. Inside a list the style sheet gives a
    frame, Windows 11's style draws a ticked box blank and an unticked one as a box, so each reads as the other (measured
    with Qt 6.12.0 on the development machine, 2026-11-10: the tick returns once the sheet has no rule for the list). The
    cell is drawn as the style draws it but for the box, which the window draws where the style puts it, so a click
    still lands on it, over the row's ground and its chosen or hover panel, in the palette's roles, which a change of
    mode repaints. A box half ticked, which no list here has, is drawn as one not ticked; a cell with no tick box is
    the style's alone."""

    def paint(self, painter, option, index) -> None:
        if index.data(Qt.ItemDataRole.CheckStateRole) is None:
            super().paint(painter, option, index)
            return
        shown = QStyleOptionViewItem(option)
        self.initStyleOption(shown, index)
        style = shown.widget.style() if shown.widget is not None else QApplication.style()
        box = style.subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, shown, shown.widget)
        painter.save()
        painter.setClipRegion(QRegion(shown.rect).subtracted(QRegion(box)), Qt.ClipOperation.IntersectClip)
        super().paint(painter, option, index)
        painter.restore()
        painter.save()
        painter.setClipRect(box, Qt.ClipOperation.IntersectClip)
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, shown, painter, shown.widget)
        draw_tick_box(painter, box, shown.palette, shown.checkState == Qt.CheckState.Checked)
        painter.restore()


class RowDelegate(TickDelegate):
    """A list's cells, and the mark of the row the keyboard is on while the list has the focus: a rounded strip of the
    palette's accent, ``CURRENT_STRIP`` lines wide, inside the left of the row's first cell, whichever of its cells is
    current. Windows 11's style frames the current row in the text colour, which in the dark mode reads as a harsh
    white box; a cell is therefore drawn without its focus state, so the style draws no frame, and the strip stands for
    it, 3:1 or more on the field, the hover and the selection in both modes (the suite measures it). The list leaves
    the frame to its cells (``RowList``), since a view showing focus across all its columns draws it round the row
    itself."""

    def paint(self, painter, option, index) -> None:
        cell = QStyleOptionViewItem(option)
        cell.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, cell, index)
        view = option.widget
        if (index.column() != 0 or view is None or not view.hasFocus()
                or view.currentIndex().row() != index.row() or view.currentIndex().parent() != index.parent()):
            return
        side = max(2.0, em(CURRENT_STRIP))
        inset = em(CURRENT_INSET)
        cell = QRectF(option.rect)
        strip = QRectF(cell.left(), cell.top() + inset, side, max(side, cell.height() - 2 * inset))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(option.palette.color(QPalette.ColorRole.Accent))
        painter.drawRoundedRect(strip, side / 2, side / 2)
        painter.restore()


class RowList(QTreeWidget):
    """Rows under headings, one chosen at a time, each known by its key, whatever place it stands in. ``columns`` are each
    column's key, title and width in digits of the default font, so the list scales with the display; ``rows`` is how many
    it asks to show; the column ``stretch`` takes what the window gives beyond that, and the others can be dragged wider.
    It scrolls itself, so the wheel over it stays the list's own (``WheelRouter``). A cell's margins come on top of the
    digits, so a column holds as many as it says. Its cells are drawn by ``RowDelegate``: a row made checkable shows its
    tick box, and the row the keyboard is on its strip."""

    def __init__(self, columns: Sequence[tuple[str, str, int]], rows: int, stretch: str, parent: QWidget | None = None,
                 least: int = 4):
        super().__init__(parent)
        self.columns = [key for key, _title, _width in columns]
        self.stretch_column = self.columns.index(stretch)
        self.widths = [digits(width + CELL_MARGINS) for _key, _title, width in columns]
        self.rows_shown = rows
        self.setColumnCount(len(columns))
        self.setHeaderLabels([title for _key, title, _width in columns])
        self.setRootIsDecorated(False)
        self.setItemsExpandable(False)
        self.setUniformRowHeights(True)
        self.setAllColumnsShowFocus(False)     # the current row's mark is its delegate's strip (``RowDelegate``)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setItemDelegate(RowDelegate(self))
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        header.setSectionsClickable(False)
        header.setMinimumSectionSize(digits(least))
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for index, key in enumerate(self.columns):
            self.setColumnWidth(index, self.widths[index])
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch if key == stretch
                                        else QHeaderView.ResizeMode.Interactive)

    def sizeHint(self) -> QSize:
        frame = 2 * self.frameWidth()
        row = max(self.sizeHintForRow(0), em(1) + 6)
        return QSize(sum(self.widths) + frame + self.verticalScrollBar().sizeHint().width(),
                     self.header().sizeHint().height() + row * self.rows_shown + frame)

    # The view repaints only the current cell when the current row or the focus changes; the strip that marks the
    # row stands in its first cell, so the rows are repainted whole.
    def currentChanged(self, current, previous) -> None:
        super().currentChanged(current, previous)
        self.viewport().update()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.viewport().update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.viewport().update()

    def row_height(self) -> int:
        """The height every row stands at, as the view lays its rows out, read off the first row shown — a row a
        search hides stands at no height; while none is shown, what a row would ask."""
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if not item.isHidden():
                return self.rowHeight(self.indexFromItem(item))
        return max(self.sizeHintForRow(0), em(1) + 6)

    def shown_count(self) -> int:
        """How many rows stand in the list, those a search hides left out."""
        return sum(not self.topLevelItem(index).isHidden() for index in range(self.topLevelItemCount()))

    def fill(self, rows: Iterable[tuple[str, Sequence[str]]], chosen: str | None = None) -> None:
        """Replaces the rows with ``rows``, each its key and its cells, ``chosen`` the one selected. No selection is
        signalled: the caller knows what it filled."""
        with QSignalBlocker(self):
            self.clear()
            for key, cells in rows:
                item = QTreeWidgetItem(list(cells))
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                self.addTopLevelItem(item)
                if key == chosen:
                    self.setCurrentItem(item)

    def key_chosen(self) -> str | None:
        chosen = self.selectedItems()
        return chosen[0].data(0, Qt.ItemDataRole.UserRole) if chosen else None

    def item_of(self, key: str) -> QTreeWidgetItem | None:
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item.data(0, Qt.ItemDataRole.UserRole) == key:
                return item
        return None

    def set_cell(self, key: str, column: str, text: str) -> None:
        self.item_of(key).setText(self.columns.index(column), text)


class WholeRows(QWidget):
    """Holds ``rows``, a list given the height a window has left over, at the height of a whole number of its rows
    (``scroll_model.whole_rows_height``), at least one, the rest of the height standing empty under it, so the list ends
    on a whole row rather than one cut through its words. The headings, the frame and, where the columns are wider than
    the list, the scroll bar under them are the fixed part; which bars show is worked out as Qt shows them
    (``scroll_model.scroll_bars``). Placed again whenever its own size changes, a column is dragged wider, rows come
    into a list that held none, since a row's height is known only then, or the list's style, font or display scale
    changes, any of which can change a row's height; a search that hides rows moves nothing but whether a scroll bar
    shows, which the next placing takes up."""

    def __init__(self, rows: RowList, parent: QWidget | None = None):
        super().__init__(parent)
        self.rows = rows
        rows.setParent(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._row = rows.row_height()
        self._due = False
        rows.header().sectionResized.connect(lambda *_: self._place())
        rows.model().rowsInserted.connect(self._rows_came)
        rows.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.rows and event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange,
                                                     QEvent.Type.DevicePixelRatioChange) and not self._due:
            self._due = True           # placed once the change has settled, however many arrive together
            QTimer.singleShot(0, self, self._settled)
        return False

    def _settled(self) -> None:
        self._due = False
        self._place()

    def sizeHint(self) -> QSize:
        return self.rows.sizeHint()

    def minimumSizeHint(self) -> QSize:
        return self.rows.minimumSizeHint()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place()

    def _rows_came(self, _parent, first: int, _last: int) -> None:
        """Rows came in: only the first row into an empty list can change a row's height, so only then is the list
        placed again; a fill of many rows asks once."""
        if first == 0 and self.rows.row_height() != self._row:
            self._place()

    def _place(self) -> None:
        rows, width, height = self.rows, self.width(), self.height()
        frame = 2 * rows.frameWidth()
        header = rows.header()
        head = 0 if rows.isHeaderHidden() else max(header.minimumHeight(), header.sizeHint().height())
        self._row = rows.row_height()
        # The stretching column fills whatever the others leave, so the columns overflow only where the others and
        # the stretching one's least width do.
        need = header.minimumSectionSize() + sum(header.sectionSize(index) for index in range(header.count())
                                                  if index != rows.stretch_column)
        bar_down = rows.horizontalScrollBar().sizeHint().height()
        _side, under = scroll_bars(width - frame, height - frame - head, need, rows.shown_count() * self._row,
                                   rows.verticalScrollBar().sizeHint().width(), bar_down)
        fixed = frame + head + (bar_down if under else 0)
        rows.setGeometry(0, 0, width, min(height, whole_rows_height(height, fixed, self._row)))


def tip_place(width: int, height: int, x: int, y: int, beside: Area, area: Area) -> tuple[int, int]:
    """Where words ``width`` by ``height`` stand, asked for at (``x``, ``y``) beside ``beside`` — the pointer, as a
    point, or the control they belong to — within ``area``, a screen's working area. On each axis where they would pass
    the area's far edge they are mirrored across ``beside``: words below and right of the pointer go above or left of
    it, and a control's hint goes above it, or ends as far in from its right as it would have begun in from its left.
    Then they are held inside the area. Asked for below or beside what they belong to, they stay clear of it unless
    they fit on neither side of it either way; words over the pointer would take it off what they speak of, which
    hides them. One frame of pixels throughout."""
    if x + width > area.right:
        x = beside.left + beside.right - x - width
    if y + height > area.bottom:
        y = beside.top + beside.bottom - y - height
    return max(area.left, min(x, area.right - width)), max(area.top, min(y, area.bottom - height))


class Tip:
    """The small window of words beside the pointer or a control, made on first use and then moved and reworded — a
    pointer crossing many marks shows one window, never a window for each."""

    def __init__(self, width: float = 26):
        """``width``: lines of the default font the words wrap at."""
        self.width = width
        self._label: QLabel | None = None
        self.shown = False

    def show(self, text: str, x: int, y: int, beside: Area | None = None) -> None:
        """Shows ``text`` at (``x``, ``y``) on the screen, kept on the screen's working area (``tip_place``); ``beside``
        is what the words belong to, the point (``x``, ``y``) itself where none is given."""
        if self._label is None:
            self._label = plain_label()
            self._label.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
            self._label.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self._label.setProperty("surface", "tip")
            self._label.setWordWrap(True)
            self._label.setMaximumWidth(em(self.width))
        self._label.setText(text)
        self._label.ensurePolished()   # the style sheet's padding counts in the size the words are placed by
        self._label.adjustSize()
        self._put(x, y, beside)
        if not self.shown:
            self._label.show()
            self.shown = True

    def move(self, x: int, y: int, beside: Area | None = None) -> None:
        if self.shown:
            self._put(x, y, beside)

    def _put(self, x: int, y: int, beside: Area | None) -> None:
        beside = beside if beside is not None else Area(x, y, x, y)
        # The screen the words are asked for on; where that place is on none, the one what they belong to is on.
        screen = (QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.screenAt(QPoint(beside.left, beside.top))
                  or QGuiApplication.primaryScreen())
        work = screen.availableGeometry()
        area = Area(work.left(), work.top(), work.left() + work.width(), work.top() + work.height())
        size = self._label.size()
        self._label.move(*tip_place(size.width(), size.height(), x, y, beside, area))

    def hide(self) -> None:
        if self.shown:
            self._label.hide()
            self.shown = False

    def close(self) -> None:
        if self._label is not None:
            self._label.deleteLater()
            self._label, self.shown = None, False


class Hint(QObject):
    """Text shown beside a widget while the pointer rests on it and, with ``focus``, while the widget has the keyboard
    focus, so a hint that carries what a surface means is reachable without a mouse."""

    def __init__(self, widget: QWidget, text: str = "", width: float = 26, focus: bool = False):
        """``width``: lines of the default font the words wrap at."""
        super().__init__(widget)
        self.widget, self.text, self.focus = widget, text, focus
        self.tip = Tip(width)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(HINT_MS)
        self._timer.timeout.connect(self._show)
        widget.destroyed.connect(self.tip.close)
        widget.installEventFilter(self)

    def eventFilter(self, _watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Enter or (self.focus and kind == QEvent.Type.FocusIn):
            if self.text:
                self._timer.start()
        elif kind in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Hide) or (
                self.focus and kind == QEvent.Type.FocusOut):
            self._timer.stop()
            self.tip.hide()
        return False

    def _show(self) -> None:
        """The words under the control, a line's height in from its left; above it where the screen ends below."""
        corner = self.widget.mapToGlobal(QPoint(0, 0))
        control = Area(corner.x(), corner.y(), corner.x() + self.widget.width(), corner.y() + self.widget.height())
        self.tip.show(self.text, control.left + em(1), control.bottom + 2, control)


def clock(owner: QObject, ms: int, call: Callable[[], None]) -> QTimer:
    """A clock of ``ms`` milliseconds owned by ``owner``, started: whatever a look does, the next one comes."""
    timer = QTimer(owner)
    timer.timeout.connect(call)
    timer.start(ms)
    return timer
