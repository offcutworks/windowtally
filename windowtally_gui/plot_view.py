"""A chart of the History window, and the legend above it, painted.

The marks are laid out by ``plot_model`` at the chart's width and drawn in the theme's colours, read while painting, so a
chart is never a read-back of what it drew and a change of mode needs no word to it. Qt draws in device-independent
pixels, so the layout's scale stays 1 at any display scale. Lines, the columns' rounded data ends and the round marks are
anti-aliased; gridlines are not, so a horizontal rule stays one crisp row of pixels. A ringed mark — a disc, a diamond
or a square — stands on a larger one of its shape in the page's colour, so a gridline under it is cut to that shape.

Glow is on data alone, painted as strokes and fills, never a graphics effect, which would render the chart offscreen at
every repaint: under each run of a line a shade of its colour fades from the run's height to nothing at its floor
(``plot_model.shade_floor``) — the baseline, unless the run is narrow — under the gridlines, so a rule stays crisp
across it; in the dark mode each line also carries a soft halo of its own colour, a
wider stroke laid under it. The columns, which are filled already, carry neither. A line can hold thousands of points,
and its round-joined halo costs several times the line itself, so the shades and the lines with their round marks are
painted once for a size, a mode and a pixel ratio, each on a picture of its own, and a repaint — a scroll's, above all —
lays the pictures down between the gridlines and the labels it draws afresh.

The plot starts after the widest of the value axis's labels — its own, and those of the charts it is lined up with
(``axis_labels``), so that every chart of the window has its axis at one place and its plot the same width.

The pointer resting on a mark for Windows' hover time shows what it is, in the one ``Tip`` the History window keeps; while
the view scrolls nothing shows, so marks passing under a still pointer stay silent (``scroll_model.words_due``). The
window asks each chart to look again as the view moves (``look``), a scroll bringing no mouse event. The wheel over a
chart scrolls the view: a chart carries no ``wheel_inside``.
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (QColor, QCursor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from .common_view import Tip, em, hover_ms, plain_label, rounded_path, scrolled_at
from .plot_model import (RING_WIDTH, Box, ColumnPlot, Dot, Label, Line, LinePlot, Margins, Marks, area, layout_columns,
                         layout_line, mark_at, shade_floor)
from .scroll_model import words_due
from .state_model import Area
from .theme_view import Theme

TIP_OFFSET = (14, 16)      # the pointer words' place from the pointer
LABEL_ROOM = 4096.0        # wider than any tick label: where a label is anchored, the box it is written in
# The shade under a line: its colour at this opacity where the run is highest, fading to nothing at its floor
# (``plot_model.shade_floor``); in the light mode, then the dark one.
AREA = (0.14, 0.20)
# The dark mode's glow along a line: each stroke this many times the line's width, at this opacity, under the line.
HALO = ((2.8, 0.14),)


def shape_polygon(shape: str, x: float, y: float, radius: float) -> QPolygonF | None:
    """A diamond — a square on its point — or a square around (``x``, ``y``) of the area of a disc of ``radius``, as the
    page's charts draw them (``windowtally.charts``); None for a disc, which is drawn as one."""
    if shape == "diamond":
        d = radius * math.sqrt(math.pi / 2)
        return QPolygonF([QPointF(x, y - d), QPointF(x + d, y), QPointF(x, y + d), QPointF(x - d, y)])
    if shape == "square":
        h = radius * math.sqrt(math.pi) / 2
        return QPolygonF([QPointF(x - h, y - h), QPointF(x + h, y - h), QPointF(x + h, y + h), QPointF(x - h, y + h)])
    return None


def _mark(painter: QPainter, dot: Dot, radius: float) -> None:
    """A round mark's shape at ``radius``, in the painter's brush."""
    polygon = shape_polygon(dot.shape, dot.x, dot.y, radius)
    if polygon is None:
        painter.drawEllipse(QPointF(dot.x, dot.y), radius, radius)
    else:
        painter.drawPolygon(polygon)


def data_end_path(box: Box, radius: float) -> QPainterPath:
    """A column segment with the rounded data end of the page's charts: the top corners, the baseline square."""
    width, height = box.x1 - box.x0, box.y1 - box.y0
    path = rounded_path(width, height, min(radius, width / 2, height), 0.0)
    path.translate(box.x0, box.y0)
    return path


class ChartView(QWidget):
    def __init__(self, theme: Theme, plot: LinePlot | ColumnPlot, height_lines: float, axis_labels: tuple[str, ...],
                 tip: Tip, parent: QWidget | None = None):
        """``axis_labels`` are the value-axis labels of the charts this one is lined up with; its own count whether or
        not they are among them. ``tip`` is the window's one window of words."""
        super().__init__(parent)
        self.theme, self.plot, self.tip = theme, plot, tip
        self.axis_labels = tuple(dict.fromkeys(tuple(text for _value, text in plot.y_ticks) + axis_labels))
        self.setFixedHeight(em(height_lines))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self._marks: Marks | None = None
        self._size = QSize()                                 # the size the marks are laid out at
        self._polygons: list[tuple[str, QPolygonF]] = []     # each line, built once a layout: it can hold thousands
        self._areas: list[tuple[str, QPolygonF, float, float]] = []  # each line's shape, its top and its shade's floor
        self._layers: tuple[QPixmap, QPixmap] | None = None   # the shades, and the lines and round marks, painted
        self._layers_key: tuple | None = None                 # the size, mode and pixel ratio they were painted at
        self._under: Dot | Line | Box | None = None          # the mark under the pointer
        self._rested_since = 0.0
        self._rest = 0.0                                     # Windows' hover time, read as the pointer arrives
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._due)

    # --- the layout -------------------------------------------------------------------------------------------------

    def marks(self) -> Marks | None:
        """The marks at the chart's size, laid out once for it; None for a chart too small to hold any."""
        if self._size != self.size() or self._marks is None:
            self._size = self.size()
            self._layers_key = None
            self._marks = self._laid() if self.width() >= 40 and self.height() >= 40 else None
            if self._marks is None:
                return None
            self._polygons = [(line.token, QPolygonF([QPointF(line.points[i], line.points[i + 1])
                                                      for i in range(0, len(line.points), 2)]))
                              for line in self._marks.lines]
            self._areas = []
            for line, (_token, polygon) in zip(self._marks.lines, self._polygons, strict=True):
                shape = QPolygonF(polygon)        # the line's own points, then the baseline's two that close it
                closing = area(line, self._marks.baseline)[len(line.points):]
                shape.append(QPointF(closing[0], closing[1]))
                shape.append(QPointF(closing[2], closing[3]))
                self._areas.append((line.token, shape, min(line.points[1::2]), shade_floor(line, self._marks.baseline)))
        return self._marks

    def _margins(self, metrics: QFontMetricsF) -> Margins:
        line = metrics.lineSpacing()
        widest = max((metrics.horizontalAdvance(text) for text in self.axis_labels), default=0.0)
        return Margins(left=widest + 12, right=em(0.8), top=line * 0.6, bottom=line * 1.6)

    def _laid(self) -> Marks:
        metrics = QFontMetricsF(self.font())
        margins = self._margins(metrics)
        if isinstance(self.plot, LinePlot):
            return layout_line(self.plot, self.width(), self.height(), margins, metrics.horizontalAdvance)
        return layout_columns(self.plot, self.width(), self.height(), margins, metrics.horizontalAdvance,
                              column_max=em(1.4))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._left()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._marks, self._layers_key = None, None
            self.update()

    # --- painting -------------------------------------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        marks = self.marks()
        if marks is None:
            return
        c = self.theme.c
        ratio = self.devicePixelRatioF()
        drawn = bool(self._polygons or marks.dots)          # a column chart has neither, and no picture
        if drawn and self._layers_key != (self._size, self.theme.mode, ratio):
            self._layers = (self._layer(self._paint_shades, marks, ratio), self._layer(self._paint_lines, marks, ratio))
            self._layers_key = (self._size, self.theme.mode, ratio)
        painter = QPainter(self)
        if drawn:
            painter.drawPixmap(0, 0, self._layers[0])
        rule = QPen(QColor(c["grid"]), marks.hairline)
        painter.setPen(rule)
        for y in marks.grid:
            painter.drawLine(QPointF(marks.left, y), QPointF(marks.right, y))
        rule.setColor(QColor(c["baseline"]))
        painter.setPen(rule)
        painter.drawLine(QPointF(marks.left, marks.baseline), QPointF(marks.right, marks.baseline))
        painter.setPen(QColor(c["ink-2"]))
        for label in marks.labels:
            self._label(painter, label)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for box in marks.boxes:
            painter.setBrush(QColor(c[box.token]))
            if box.end:
                painter.drawPath(data_end_path(box, marks.data_end))
            else:
                painter.drawRect(QRectF(box.x0, box.y0, box.x1 - box.x0, box.y1 - box.y0))
        if drawn:
            painter.drawPixmap(0, 0, self._layers[1])

    def _layer(self, paint, marks: Marks, ratio: float) -> QPixmap:
        """What ``paint`` draws, on a transparent picture of the chart's size in the display's pixels."""
        picture = QPixmap(round(self.width() * ratio), round(self.height() * ratio))
        picture.setDevicePixelRatio(ratio)
        picture.fill(Qt.GlobalColor.transparent)
        painter = QPainter(picture)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint(painter, marks)
        painter.end()
        return picture

    def _paint_shades(self, painter: QPainter, marks: Marks) -> None:
        c, dark = self.theme.c, self.theme.mode == "dark"
        painter.setPen(Qt.PenStyle.NoPen)
        for token, shape, top, floor in self._areas:
            # A run whose floor stands no lower than its top — a level run on the baseline, or a level one with no
            # width — has nothing to shade.
            if floor <= top:
                continue
            shade = QLinearGradient(0.0, top, 0.0, floor)
            colour = QColor(c[token])
            colour.setAlphaF(AREA[dark])
            shade.setColorAt(0.0, colour)
            colour.setAlphaF(0.0)
            shade.setColorAt(1.0, colour)
            painter.setBrush(shade)
            painter.drawPolygon(shape)

    def _paint_lines(self, painter: QPainter, marks: Marks) -> None:
        c, dark = self.theme.c, self.theme.mode == "dark"
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for token, polygon in self._polygons:
            if dark:
                for wider, opacity in HALO:
                    colour = QColor(c[token])
                    colour.setAlphaF(opacity)
                    painter.setPen(QPen(colour, marks.line_width * wider, Qt.PenStyle.SolidLine,
                                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                    painter.drawPolyline(polygon)
            painter.setPen(QPen(QColor(c[token]), marks.line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            painter.drawPolyline(polygon)
        painter.setPen(Qt.PenStyle.NoPen)
        for dot in marks.dots:
            if dot.ringed:
                painter.setBrush(QColor(c["page"]))
                _mark(painter, dot, dot.radius + marks.ring)
            painter.setBrush(QColor(c[dot.token]))
            _mark(painter, dot, dot.radius)

    @staticmethod
    def _label(painter: QPainter, label: Label) -> None:
        """A tick label at its anchor: ``e`` its right edge at the middle of its height, ``n`` the middle of its top."""
        if label.anchor == "e":
            box = QRectF(label.x - LABEL_ROOM, label.y - LABEL_ROOM / 2, LABEL_ROOM, LABEL_ROOM)
            flags = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        else:
            box = QRectF(label.x - LABEL_ROOM / 2, label.y, LABEL_ROOM, LABEL_ROOM)
            flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        painter.drawText(box, flags, label.text)

    # --- what the pointer shows -------------------------------------------------------------------------------------

    def look(self, at: QPoint | None) -> None:
        """What stands at ``at`` on the screen now, None where the pointer is not over this chart: the pointer moved over
        it, or the marks moved under it as the view scrolled. The words follow the pointer, and go while the view
        scrolls."""
        point = self.mapFromGlobal(at) if at is not None else None
        marks = self.marks() if point is not None and self.isVisible() and self.rect().contains(point) else None
        mark = mark_at(marks, point.x(), point.y()) if marks is not None else None
        if mark is None:
            self._left()
        elif mark is not self._under:
            self._left()
            self._under = mark
            self._rested_since = time.monotonic()
            self._rest = hover_ms() / 1000
            self._wait()
        else:
            if self.tip.shown and time.monotonic() - scrolled_at() < self._rest:
                self.tip.hide()
                self._wait()
            self.tip.move(*self._place(at))

    def mouseMoveEvent(self, event) -> None:
        self.look(event.globalPosition().toPoint())

    def leaveEvent(self, _event) -> None:
        self._left()

    def hideEvent(self, _event) -> None:
        self._left()

    def _wait(self) -> None:
        if not self._timer.isActive():
            self._timer.start(max(1, round(self._rest * 1000)))

    def _due(self) -> None:
        if self._under is None:
            return
        left = words_due(time.monotonic(), self._rested_since, scrolled_at(), self._rest)
        if left > 0:
            self._timer.start(max(1, round(left * 1000)))
            return
        if self._under.hover:
            self.tip.show(self._under.hover, *self._place(QCursor.pos()))

    @staticmethod
    def _place(at: QPoint) -> tuple[int, int, Area]:
        """Where the words go for the pointer at ``at``, and the pointer they keep clear of (``Tip``)."""
        return at.x() + TIP_OFFSET[0], at.y() + TIP_OFFSET[1], Area(at.x(), at.y(), at.x(), at.y())

    def _left(self) -> None:
        if self._under is not None:
            self._under = None
            self._timer.stop()
            self.tip.hide()


class LegendMark(QWidget):
    """A series' colour as a small square, or, where ``mark`` names a reset marker's shape — a disc, a diamond, a
    square — that shape's outline in the quieter ink."""

    def __init__(self, theme: Theme, role: str, mark: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.theme, self.role, self.mark = theme, role, mark
        self.setFixedSize(max(8, em(0.6)), max(8, em(0.6)))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = QColor(self.theme.c[self.role])
        whole = QRectF(self.rect())
        if self.mark:
            painter.setPen(QPen(colour, RING_WIDTH))
            inner = whole.adjusted(RING_WIDTH / 2, RING_WIDTH / 2, -RING_WIDTH / 2, -RING_WIDTH / 2)
            if self.mark == "diamond":
                c, d = inner.center(), inner.width() / 2
                painter.drawPolygon(QPolygonF([QPointF(c.x(), c.y() - d), QPointF(c.x() + d, c.y()),
                                               QPointF(c.x(), c.y() + d), QPointF(c.x() - d, c.y())]))
            elif self.mark == "square":
                painter.drawRect(inner)
            else:
                painter.drawEllipse(inner)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            painter.drawRoundedRect(whole, 2, 2)


class LegendView(QWidget):
    """A mark and a name per series, left to right, wrapping where the width ends, so a narrow window loses no name."""

    def __init__(self, theme: Theme, items: tuple[tuple[str, str, str], ...], parent: QWidget | None = None):
        """``items`` are each (name, role, the reset marker's shape its mark outlines, or "" for a series' colour)."""
        super().__init__(parent)
        self.gap = em(1)
        self.entries: list[QWidget] = []
        for label, role, mark in items:
            entry = QWidget(self)
            row = QHBoxLayout(entry)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(em(0.25))
            row.addWidget(LegendMark(theme, role, mark, entry))
            words: QLabel = plain_label(entry)
            words.setText(label)
            theme.ink(words, "ink-2")
            row.addWidget(words)
            self.entries.append(entry)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _places(self, width: int) -> tuple[list[tuple[int, int]], int]:
        """Each entry's place at ``width``, and the height they take."""
        places, x, y, tall = [], 0, 0, 0
        for entry in self.entries:
            wide, high = entry.sizeHint().width(), entry.sizeHint().height()
            if x and x + wide > width:
                x, y = 0, y + tall + self.gap // 3
                tall = 0
            places.append((x, y))
            x += wide + self.gap
            tall = max(tall, high)
        return places, y + tall

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._places(width)[1]

    def sizeHint(self) -> QSize:
        return QSize(sum(e.sizeHint().width() + self.gap for e in self.entries), self.heightForWidth(10 ** 6))

    def minimumSizeHint(self) -> QSize:
        return QSize(max((e.sizeHint().width() for e in self.entries), default=0), self.heightForWidth(10 ** 6))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        places, _height = self._places(self.width())
        for entry, (x, y) in zip(self.entries, places):
            entry.setGeometry(x, y, entry.sizeHint().width(), entry.sizeHint().height())
