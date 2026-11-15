"""A table of the History window, painted from ``table_model``.

The table stands as a panel on the cards' surface, edged by their hairline and rounded as they are: the headings in the
quieter ink above a hairline, the rows parted by the faint gridline, a total row in bold. It reads as a list of headings
does, but it paints its text itself rather than being a Qt item view, for two reasons: an
item view scrolls itself, which the window's one wheel handler leaves alone, so the wheel's gesture rule would stop at
it; and nothing in a table is chosen, so nothing an item view gives is lost. Only the rows the repaint reaches are
written.

A table shows at most ``history.TABLE_ROWS`` rows, as the history page's tables do. A longer one scrolls within itself by
its bar or by the wheel, so a long table does not lengthen the view: its headings stand in a part of their own above the
rows', and the total rows at its end in one below them, so neither scrolls away. The wheel over such a table's rows or
their bar moves the rows while they can move the way the wheel turns, and at their top or end moves the view around it
(``scroll_model.inner_takes``, through ``common_view``'s one wheel handler); the wheel over a table that shows every
row, or over its headings or totals, moves the view around it. The rows take a gesture of the wheel only when its first
turn finds them under the pointer (``scroll_model.gesture_goes_on``).

The table fills the view's width, laid out again whenever that changes, so its right edge stands where the charts' do; a
table whose columns need more than the view's width keeps that width and scrolls sideways by its bar or by Shift and the
wheel, headings, rows and totals together. Colours are read while painting, so a change of mode needs no word to it.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QScrollBar, QSizePolicy, QWidget

from windowtally.history import TABLE_ROWS

from .common_view import em, rounded_path, wheel_lines
from .history_model import FIGURES, Table
from .scroll_model import inner_takes, wheel_steps
from .table_model import Cell, TableMarks, layout_table, trailing_totals
from .theme_view import Theme

BORDER = 1                 # the frame
RADIUS = 8                 # the frame's corners, as a card's
PANEL = "surface-1"        # what the headings and the rows stand on


class _Part(QWidget):
    """One of a table's three parts, which paints what ``paint`` writes."""

    def __init__(self, parent: QWidget, height: int, paint: Callable[[QPainter, QRectF], None]):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.painted = paint

    def paintEvent(self, event) -> None:
        self.painted(QPainter(self), QRectF(event.rect()))


class TableView(QWidget):
    def __init__(self, theme: Theme, table: Table, parent: QWidget | None = None):
        super().__init__(parent)
        self.theme, self.table = theme, table
        self.bold = theme.fonts["bold"]
        self.plain = QFontMetricsF(self.font())
        self.heavy = QFontMetricsF(self.bold)
        line = self.plain.lineSpacing()
        # The space a column adds to its text, the headings' row and a row, from the font.
        self.sizes = (self.plain.horizontalAdvance("0") * 3, int(line + 2 * int(line * 0.15)), int(line * 1.35))
        self.marks = self._layout(0.0)
        count = len(table.rows)
        # A table that scrolls keeps its totals below the rows; one that shows every row keeps them among the rows.
        self.foot_rows = trailing_totals(table.totals, count) if count > TABLE_ROWS else 0
        self.shown = min(count, TABLE_ROWS) - self.foot_rows
        self.kept = count - self.foot_rows
        row_height = self.sizes[2]
        self.head = _Part(self, BORDER + self.sizes[1], self._paint_head)
        self.rows = _Part(self, self.shown * row_height + (0 if self.foot_rows else BORDER), self._paint_rows)
        self.foot = _Part(self, self.foot_rows * row_height + BORDER, self._paint_foot) if self.foot_rows else None
        self.bar = QScrollBar(Qt.Orientation.Horizontal, self)
        self.rows_bar = QScrollBar(Qt.Orientation.Vertical, self)
        self.rows_bar.setRange(0, self.kept - self.shown)
        self.rows_bar.setPageStep(max(1, self.shown))
        self.rows_bar.setSingleStep(1)
        self.rows_bar.setVisible(self.kept > self.shown)
        self.bar.setSingleStep(em(1))
        self.bar.hide()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.addWidget(self.head, 0, 0)
        grid.addWidget(self.rows, 1, 0)
        if self.foot is not None:
            grid.addWidget(self.foot, 2, 0)
        grid.addWidget(self.bar, 3, 0)
        grid.addWidget(self.rows_bar, 1, 1)
        grid.setColumnStretch(0, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for part in self._parts():
            part.wheel_sideways = self._sideways
        self.rows.wheel_inside = self.rows_bar.wheel_inside = self._wheel_inside
        self.rows_bar.valueChanged.connect(lambda _value: self.rows.update())
        self.bar.valueChanged.connect(lambda _value: self._repaint())
        self._carried = 0           # Shift and the wheel's units short of a whole step
        self._rows_carried = 0      # the wheel's units short of a whole row
        self._width = 0

    def _parts(self) -> tuple[_Part, ...]:
        return (self.head, self.rows) + (() if self.foot is None else (self.foot,))

    def _repaint(self) -> None:
        for part in self._parts():
            part.update()

    def _layout(self, width: float) -> TableMarks:
        """The table at ``width`` pixels, its frame included, or as wide as its columns need where that is more."""
        table, (room, heading_height, row_height) = self.table, self.sizes
        return layout_table(table.columns, table.rows, table.totals, self.plain.horizontalAdvance,
                            self.heavy.horizontalAdvance, room, heading_height, row_height,
                            width=max(0.0, width - 2 * BORDER))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self.rows.width()
        if width != self._width:
            self._width = width
            self.marks = self._layout(width)
            whole = int(self.marks.width) + 2 * BORDER
            self.bar.setRange(0, max(0, whole - width))
            self.bar.setPageStep(max(1, width))
            self.bar.setVisible(whole > width)
            self._repaint()

    # --- the wheel ------------------------------------------------------------------------------------------------

    def _sideways(self, delta: int) -> None:
        count, what, self._carried = wheel_steps(delta, self._carried, wheel_lines())
        if count:
            self.bar.setValue(self.bar.value() + count * (self.bar.pageStep() if what == "pages" else em(1)))

    def _wheel_inside(self, delta: int) -> bool:
        """Takes a turn of the wheel while the rows can move its way; False passes it on to the view around."""
        bar = self.rows_bar
        whole = bar.maximum() + bar.pageStep()
        if not inner_takes(bar.value() / whole, (bar.value() + bar.pageStep()) / whole, delta):
            self._rows_carried = 0
            return False
        count, what, self._rows_carried = wheel_steps(delta, self._rows_carried, wheel_lines())
        if count:
            bar.setValue(bar.value() + count * (bar.pageStep() if what == "pages" else 1))
        return True

    # --- painting -------------------------------------------------------------------------------------------------

    def _surface(self, painter: QPainter, part: _Part, top: bool, bottom: bool, fill: str) -> None:
        """``part``'s rim in the frame's colour, its top corners rounded where ``top`` and its bottom ones where
        ``bottom``, its inside in ``fill``; what is written after this stays inside it."""
        c, width, height = self.theme.c, part.width(), part.height()
        over, under = min(RADIUS, height) if top else 0, min(RADIUS, height) if bottom else 0
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(rounded_path(width, height, over, under), QColor(c["edge"]))
        inside = rounded_path(width - 2 * BORDER, height - (BORDER if top else 0) - (BORDER if bottom else 0),
                              max(0, over - BORDER), max(0, under - BORDER))
        inside.translate(BORDER, BORDER if top else 0)
        painter.fillPath(inside, QColor(c[fill]))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setClipRect(inside.boundingRect())

    def _write(self, painter: QPainter, cell: Cell, x: float, y: float) -> None:
        """``cell``'s text, its place across moved by ``x`` and the middle of its height at ``y``."""
        metrics = self.heavy if cell.bold else self.plain
        left = x + cell.x - (metrics.horizontalAdvance(cell.text) if cell.anchor == FIGURES else 0)
        painter.drawText(QPointF(left, y + (metrics.ascent() - metrics.descent()) / 2), cell.text)

    def _write_rows(self, painter: QPainter, rows: range, x: float, y: float) -> None:
        """``rows`` of the table's cells, a row whose middle ``marks`` puts at ``m`` written at ``y + m``."""
        cells, columns = self.marks.cells, len(self.table.columns)
        painter.setPen(QColor(self.theme.c["ink"]))
        for row in rows:
            painter.setFont(self.bold if row in self.table.totals else self.font())
            for cell in cells[row * columns:(row + 1) * columns]:
                self._write(painter, cell, x, y + cell.y)

    def _part_rows(self, painter: QPainter, part: _Part, count: int, top: float) -> None:
        """The faint gridline under each of ``count`` rows from ``top`` down, on each row's last line of pixels, but where
        the part's own frame or end stands."""
        row_height = self.sizes[2]
        painter.setPen(QPen(QColor(self.theme.c["grid"]), BORDER))
        for index in range(count):
            y = top + (index + 1) * row_height - 1
            if y < part.height() - BORDER - 1:
                painter.drawLine(QPointF(BORDER, y), QPointF(part.width() - BORDER, y))

    def _paint_head(self, painter: QPainter, _shown: QRectF) -> None:
        c, marks, x = self.theme.c, self.marks, BORDER - self.bar.value()
        self._surface(painter, self.head, True, False, PANEL)
        painter.setPen(QPen(QColor(c["edge"]), BORDER))
        painter.drawLine(QPointF(BORDER, self.head.height() - 0.5), QPointF(self.head.width() - BORDER,
                                                                           self.head.height() - 0.5))
        painter.setPen(QColor(c["ink-2"]))
        for cell in marks.headings:
            self._write(painter, cell, x, BORDER + cell.y)

    def _paint_rows(self, painter: QPainter, shown: QRectF) -> None:
        row_height = self.sizes[2]
        self._surface(painter, self.rows, False, self.foot is None, PANEL)
        top = -self.rows_bar.value() * row_height
        first = max(0, int((shown.top() - top) // row_height))
        last = min(self.kept, int((shown.bottom() - top) // row_height) + 1)
        self._part_rows(painter, self.rows, last - first, top + first * row_height)
        self._write_rows(painter, range(first, last), BORDER - self.bar.value(), top - self.marks.heading_height)

    def _paint_foot(self, painter: QPainter, _shown: QRectF) -> None:
        self._surface(painter, self.foot, False, True, PANEL)
        painter.setPen(QPen(QColor(self.theme.c["edge"]), BORDER))
        painter.drawLine(QPointF(BORDER, 0.5), QPointF(self.foot.width() - BORDER, 0.5))
        self._write_rows(painter, range(self.kept, len(self.table.rows)), BORDER - self.bar.value(),
                         -self.marks.heading_height - self.kept * self.sizes[2])
