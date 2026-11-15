"""The History view's charts as marks laid out at a size in pixels: a step line chart and a stacked column chart. No
toolkit — ``plot_view`` paints the marks — so the layout is tested without a display.

The marks follow the history page's chart spec (``windowtally.charts``) at the window's scale: step lines, because an
observed percentage holds until the next reading, broken where the readings stop for longer than the history's line
break; columns no wider than the view allows, stacked from the baseline with a gap between segments; markers — a disc,
or a diamond or a square of the disc's area — ringed in the surface colour; one recessive gridline per value tick.
Colours are palette roles, resolved by the view. A tick label that would overlap the one before it is left out, so the
axis stays legible at any width; every mark carries the words its pointer shows, which say what a tooltip says on the
page. ``mark_at`` answers which mark stands at a place, so a view that draws the marks itself has no items to ask;
``area`` is the shape under a line, which the view shades, and ``shade_floor`` how far down that shade reaches: a run
of readings that stops soon after it starts is a few pixels wide, and a shade from its height to the baseline would
stand under it as a thin column of its own.

Every stroke, radius, gap and offset below is given in pixels at 100 % display scale and multiplied by the ``scale`` the
view passes — 2 at 200 % — so a chart reads at a high display scale as it does at 100 %, not at half the size.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass, replace
from typing import Callable

from windowtally.charts import AREA_REACH as AREA_REACH   # the shade's reach, named with the rule that uses it
from windowtally.charts import DATA_END_RADIUS
from windowtally.charts import shade_floor as run_shade_floor

COLUMN_MAX = 24.0
SEGMENT_GAP = 2.0
LABEL_GAP = 8.0          # least space between two tick labels
VALUE_OFFSET = 6.0       # from a value tick's label to the plot
POSITION_OFFSET = 4.0    # from the baseline to a position tick's label
LINE_WIDTH = 2.0
HAIRLINE = 1.0           # a gridline and the baseline
READING_RADIUS = 3.0     # a lone reading
MARKER_RADIUS = 4.0      # a reset outside the schedule's mark, of every kind and shape, inside its ring
RING_WIDTH = 2.0         # the marker's ring in the surface colour
REACH = 1.0              # how far beyond a thin mark the pointer still counts as on it


@dataclass(frozen=True)
class Series:
    label: str
    token: str
    points: tuple[tuple[float, float], ...]      # (x, y) by x


@dataclass(frozen=True)
class Marker:
    x: float
    y: float
    token: str
    hover: str
    shape: str = "disc"                          # disc | diamond | square (``windowtally.history.RESET_MARKS``)


@dataclass(frozen=True)
class LinePlot:
    series: tuple[Series, ...]
    markers: tuple[Marker, ...]
    x_range: tuple[float, float]
    y_range: tuple[float, float]
    x_ticks: tuple[tuple[float, str], ...]
    y_ticks: tuple[tuple[float, str], ...]
    break_after: float | None                    # a gap wider than this, in x units, breaks a line


@dataclass(frozen=True)
class ColumnStack:
    label: str
    token: str
    values: tuple[float, ...]                    # one per column
    hovers: tuple[str, ...]                      # one per column: what its segment says


@dataclass(frozen=True)
class ColumnPlot:
    labels: tuple[str, ...]                      # one per column
    stacks: tuple[ColumnStack, ...]              # stacked in this order from the baseline
    y_max: float
    y_ticks: tuple[tuple[float, str], ...]


@dataclass(frozen=True)
class Line:
    token: str
    points: tuple[float, ...]                    # x0, y0, x1, y1, ...
    hover: str


@dataclass(frozen=True)
class Dot:
    token: str
    x: float
    y: float
    radius: float
    ringed: bool
    hover: str
    shape: str = "disc"                          # disc, or a diamond or a square of the disc's area


@dataclass(frozen=True)
class Box:
    token: str
    x0: float
    y0: float
    x1: float
    y1: float
    hover: str
    end: bool = False                            # the top segment of its stack: the column's data end


@dataclass(frozen=True)
class Label:
    x: float
    y: float
    text: str
    anchor: str                                  # e: right edge at x (a value tick); n: top's middle (a position tick)


@dataclass(frozen=True)
class Marks:
    grid: tuple[float, ...]                      # y of each gridline
    baseline: float
    left: float
    right: float
    labels: tuple[Label, ...]
    lines: tuple[Line, ...] = ()
    dots: tuple[Dot, ...] = ()
    boxes: tuple[Box, ...] = ()
    line_width: float = LINE_WIDTH
    hairline: float = HAIRLINE
    ring: float = RING_WIDTH                     # the width of a ringed dot's ring, outside its radius
    data_end: float = DATA_END_RADIUS            # the rounding of a column's data end, as the page's
    reach: float = REACH


@dataclass(frozen=True)
class Margins:
    left: float
    right: float
    top: float
    bottom: float


def _scale(value: float, low: float, high: float, start: float, end: float) -> float:
    if high == low:
        return (start + end) / 2
    return start + (value - low) / (high - low) * (end - start)


def _spaced(candidates: list[Label], measure: Callable[[str], float], scale: float) -> tuple[Label, ...]:
    """The position ticks, left to right, leaving out each one that would overlap the last one kept."""
    kept: list[Label] = []
    end = float("-inf")
    for label in candidates:
        half = measure(label.text) / 2
        if label.x - half >= end + LABEL_GAP * scale:
            kept.append(label)
            end = label.x + half
    return tuple(kept)


def _frame(y_ticks, y_range, width: float, height: float, margins: Margins,
           scale: float) -> tuple[float, float, float, float, list[float], list[Label]]:
    left, right = margins.left, width - margins.right
    top, bottom = margins.top, height - margins.bottom
    grid, labels = [], []
    for value, text in y_ticks:
        y = _scale(value, *y_range, bottom, top)
        grid.append(y)
        labels.append(Label(left - VALUE_OFFSET * scale, y, text, "e"))
    return left, right, top, bottom, grid, labels


def _strokes(scale: float) -> dict[str, float]:
    return {"line_width": LINE_WIDTH * scale, "hairline": HAIRLINE * scale, "ring": RING_WIDTH * scale,
            "data_end": DATA_END_RADIUS * scale, "reach": REACH * scale}


def layout_line(plot: LinePlot, width: float, height: float, margins: Margins,
                measure: Callable[[str], float], scale: float = 1.0) -> Marks:
    left, right, top, bottom, grid, labels = _frame(plot.y_ticks, plot.y_range, width, height, margins, scale)
    ticks = [Label(_scale(value, *plot.x_range, left, right), bottom + POSITION_OFFSET * scale, text, "n")
             for value, text in plot.x_ticks]
    lines, dots = [], []
    for s in plot.series:
        runs: list[list[tuple[float, float]]] = []
        for x, y in s.points:
            if not runs or (plot.break_after is not None and x - runs[-1][-1][0] > plot.break_after):
                runs.append([])
            runs[-1].append((x, y))
        for run in runs:
            coords: list[float] = []
            for x, y in run:
                px = _scale(x, *plot.x_range, left, right)
                py = _scale(y, *plot.y_range, bottom, top)
                if coords:
                    coords += [px, coords[-1]]
                coords += [px, py]
            if len(coords) > 2:
                lines.append(Line(s.token, tuple(coords), s.label))
            else:
                dots.append(Dot(s.token, coords[0], coords[1], READING_RADIUS * scale, False, s.label))
    for m in plot.markers:
        dots.append(Dot(m.token, _scale(m.x, *plot.x_range, left, right), _scale(m.y, *plot.y_range, bottom, top),
                        MARKER_RADIUS * scale, True, m.hover, m.shape))
    return Marks(tuple(grid), bottom, left, right, tuple(labels) + _spaced(ticks, measure, scale), tuple(lines),
                 tuple(dots), **_strokes(scale))


def layout_columns(plot: ColumnPlot, width: float, height: float, margins: Margins,
                   measure: Callable[[str], float], column_max: float = COLUMN_MAX, scale: float = 1.0) -> Marks:
    left, right, top, bottom, grid, labels = _frame(plot.y_ticks, (0.0, plot.y_max), width, height, margins, scale)
    gap = SEGMENT_GAP * scale
    count = max(1, len(plot.labels))
    slot = (right - left) / count
    column = min(column_max, slot * 0.7)
    ticks = [Label(left + slot * (index + 0.5), bottom + POSITION_OFFSET * scale, text, "n")
             for index, text in enumerate(plot.labels)]
    boxes = []
    for index in range(len(plot.labels)):
        x = left + slot * (index + 0.5) - column / 2
        base = 0.0
        segments = [(s, s.values[index]) for s in plot.stacks if s.values[index] > 0]
        kept = []
        for position, (s, value) in enumerate(segments):
            y_bottom = _scale(base, 0.0, plot.y_max, bottom, top)
            y_top = _scale(base + value, 0.0, plot.y_max, bottom, top)
            if position:
                y_bottom -= gap / 2
            if position < len(segments) - 1:
                y_top += gap / 2
            if y_bottom - y_top >= 0.5:
                kept.append(Box(s.token, x, y_top, x + column, y_bottom, s.hovers[index]))
            base += value
        if kept:                                 # the top one kept: a segment too thin to draw is no data end
            kept[-1] = replace(kept[-1], end=True)
        boxes += kept
    return Marks(tuple(grid), bottom, left, right, tuple(labels) + _spaced(ticks, measure, scale), boxes=tuple(boxes),
                 **_strokes(scale))


def area(line: Line, baseline: float) -> tuple[float, ...]:
    """The shape under ``line`` down to ``baseline``, as a polygon's points: the line's own, then the baseline under its
    last point and under its first. A line broken where its readings stop has a shape under each run, none under the
    gap."""
    return line.points + (line.points[-2], baseline, line.points[0], baseline)


def shade_floor(line: Line, baseline: float) -> float:
    """Where the shade under ``line``, one run of readings, has faded to nothing, by the rule the history page's charts
    shade by (``windowtally.charts.shade_floor``, ``AREA_REACH``)."""
    return run_shade_floor(line.points[0::2], line.points[1::2], baseline)


def _on_line(line: Line, x: float, y: float, reach: float) -> bool:
    """Whether (``x``, ``y``) lies within ``reach`` of a step line, whose points run left to right, each segment square
    to the axes: a line can hold thousands of points, so the search starts where ``x`` stands."""
    points = line.points
    count = len(points) // 2
    start = max(0, bisect_left(range(count), x - reach, key=lambda index: points[2 * index]) - 1)
    for index in range(start, count - 1):
        x0, y0, x1, y1 = points[2 * index:2 * index + 4]
        if x0 > x + reach:
            return False
        if x0 - reach <= x <= x1 + reach and min(y0, y1) - reach <= y <= max(y0, y1) + reach:
            return True
    return False


def mark_at(marks: Marks, x: float, y: float) -> Dot | Line | Box | None:
    """The mark standing at (``x``, ``y``), the one drawn last where marks overlap: a round mark, then a line, then a
    column; None where there is none."""
    for dot in reversed(marks.dots):
        if math.hypot(x - dot.x, y - dot.y) <= dot.radius + (marks.ring if dot.ringed else 0.0) + marks.reach:
            return dot
    for line in reversed(marks.lines):
        if _on_line(line, x, y, marks.line_width / 2 + marks.reach):
            return line
    for box in reversed(marks.boxes):
        if box.x0 <= x <= box.x1 and box.y0 <= y <= box.y1:
            return box
    return None
