"""Inline SVG chart primitives for the history page: a step line chart and a stacked column chart.

Marks follow one fixed spec: 2px lines with round joins, columns at most 24px wide with a 4px rounded data end and a
2px surface-coloured gap between stacked segments, 8px markers — a disc, or a diamond or a square of the disc's area —
with a 2px surface ring, 1px recessive gridlines.
Colours are CSS custom properties (``var(--series-1)``), so the page's light and dark themes restyle every chart in
one place. Every mark carries a ``<title>``: the browser's own tooltip is the hover layer, with no script.

A line stands over a shade and, in the dark mode, a glow, at the History window's values
(``windowtally_gui.plot_view``): under each run of a line a vertical gradient of the line's colour, from the run's
highest point at opacity ``AREA`` (the light mode's, the dark mode's) to nothing at the run's floor (``shade_floor``),
drawn under the gridlines so a rule stays crisp across it; and under the line one stroke of its colour ``HALO_WIDTH``
times as wide at opacity ``HALO_OPACITY``. ``shade_floor`` is the one rule both media shade by: the History window's
charts take it from here (``windowtally_gui.plot_model``). Which mode's values apply is the page's style sheet's to say,
through ``--area`` and ``--halo``; the columns carry neither.
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from html import escape

AREA = (0.14, 0.20)
HALO_WIDTH = 2.8
HALO_OPACITY = 0.14
LINE_WIDTH = 2
AREA_REACH = 2.0         # how far a shade reaches below its run's lowest point, in widths of the run

WIDTH = 960
PLOT_LEFT = 52
PLOT_RIGHT = 16
PLOT_TOP = 14
PLOT_BOTTOM = 30
COLUMN_MAX = 24.0
SEGMENT_GAP = 2.0
DATA_END_RADIUS = 4.0


@dataclass
class LineSeries:
    label: str
    color: str                                   # a CSS colour expression, e.g. "var(--series-1)"
    points: list[tuple[float, float]]            # (x, y) sorted by x
    break_after: float | None = None             # a gap wider than this (in x units) breaks the line


@dataclass
class Marker:
    x: float
    y: float
    color: str
    title: str
    shape: str = "disc"                          # disc | diamond | square, each 8px across


MARKER_RADIUS = 4.0


def _marker(m: Marker, px: float, py: float) -> str:
    """A marker's mark at (``px``, ``py``): a disc, a diamond — a square on its point — or a square, the two squares of
    the disc's area, so no mark reads larger than another."""
    title = f"<title>{escape(m.title)}</title>"
    r = MARKER_RADIUS
    if m.shape == "diamond":
        d = r * math.sqrt(math.pi / 2)          # half the diagonal
        return (f'<path class="marker" d="M{px:.1f},{py - d:.1f}L{px + d:.1f},{py:.1f}L{px:.1f},{py + d:.1f}'
                f'L{px - d:.1f},{py:.1f}Z" fill="{m.color}">{title}</path>')
    if m.shape == "square":
        side = r * math.sqrt(math.pi)
        return (f'<rect class="marker" x="{px - side / 2:.1f}" y="{py - side / 2:.1f}" width="{side:.1f}" '
                f'height="{side:.1f}" fill="{m.color}">{title}</rect>')
    return f'<circle class="marker" cx="{px:.1f}" cy="{py:.1f}" r="{r:g}" fill="{m.color}">{title}</circle>'


@dataclass
class StackSeries:
    label: str
    color: str
    values: list[float]                          # one per column, aligned with the chart's columns


@dataclass
class Axis:
    ticks: list[tuple[float, str]] = field(default_factory=list)   # (value, label)


def shade_floor(xs: Sequence[float], ys: Sequence[float], baseline: float) -> float:
    """Where the shade under one run of a line has faded to nothing, its points ``xs``, ``ys`` on a plot whose y grows
    downward to ``baseline``: at the run's own lowest point, or further down by no more than ``AREA_REACH`` times the
    run's width, and never past ``baseline``. A run as wide as half its height, or one that drops to the baseline at a
    reset, fades at the baseline; a run a few pixels wide high on the chart casts a short shade under its own span, not
    a column to the baseline."""
    return min(baseline, max(max(ys), min(ys) + AREA_REACH * (xs[-1] - xs[0])))


def _scale(value: float, low: float, high: float, start: float, end: float) -> float:
    if high == low:
        return (start + end) / 2
    return start + (value - low) / (high - low) * (end - start)


def _frame(height: int, x_axis: Axis, y_axis: Axis, x_range: tuple[float, float], y_range: tuple[float, float]) -> list[str]:
    left, right, top, bottom = PLOT_LEFT, WIDTH - PLOT_RIGHT, PLOT_TOP, height - PLOT_BOTTOM
    parts = []
    for value, label in y_axis.ticks:
        y = _scale(value, *y_range, bottom, top)
        parts.append(f'<line class="grid" x1="{left}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{escape(label)}</text>')
    for value, label in x_axis.ticks:
        x = _scale(value, *x_range, left, right)
        parts.append(f'<text class="tick" x="{x:.1f}" y="{bottom + 18}" text-anchor="middle">{escape(label)}</text>')
    parts.append(f'<line class="baseline" x1="{left}" x2="{right}" y1="{bottom}" y2="{bottom}"/>')
    return parts


def line_chart(series: list[LineSeries], *, x_range: tuple[float, float], y_range: tuple[float, float],
               x_axis: Axis, y_axis: Axis, markers: list[Marker] | None = None, height: int = 260,
               title: str = "") -> str:
    """Step lines: a value holds until the next point, which is what an observed percentage means. A chart's
    gradients are named from everything they are drawn from — the title, the height and each line's colour and
    points — so two charts of one document share a gradient's name only where they share the gradient."""
    left, right, top, bottom = PLOT_LEFT, WIDTH - PLOT_RIGHT, PLOT_TOP, height - PLOT_BOTTOM
    drawn = repr((title, height, x_range, y_range, [(s.color, s.points, s.break_after) for s in series]))
    key = f"{zlib.crc32(drawn.encode('utf-8')):08x}"
    defs, shades, halos, lines = [], [], [], []
    for number, s in enumerate(series):
        runs: list[list[tuple[float, float]]] = []
        for x, y in s.points:
            if runs and s.break_after is not None and x - runs[-1][-1][0] > s.break_after:
                runs.append([])
            if not runs:
                runs.append([])
            runs[-1].append((x, y))
        for run_number, run in enumerate(runs):
            coords: list[tuple[float, float]] = []
            for index, (x, y) in enumerate(run):
                px = _scale(x, *x_range, left, right)
                py = _scale(y, *y_range, bottom, top)
                if index:
                    coords.append((px, coords[-1][1]))
                coords.append((px, py))
            points = " ".join(f"{px:.1f},{py:.1f}" for px, py in coords)
            if len(coords) > 1:
                # Each run fades from its own highest point to its own floor, so it has a gradient of its own; the
                # shape still reaches the baseline, transparent below the floor.
                highest = min(py for _, py in coords)
                floor = shade_floor([px for px, _ in coords], [py for _, py in coords], bottom)
                # A run whose floor stands no lower than its top — a level run on the baseline, or a level one with no
                # width — has nothing to shade.
                if floor > highest:
                    gradient = f"area-{key}-{number}-{run_number}"
                    defs.append(f'<linearGradient id="{gradient}" gradientUnits="userSpaceOnUse" x1="0" '
                                f'y1="{highest:.1f}" x2="0" y2="{floor:.1f}"><stop offset="0" '
                                f'style="stop-color:{s.color};stop-opacity:var(--area)"/>'
                                f'<stop offset="1" style="stop-color:{s.color};stop-opacity:0"/></linearGradient>')
                    shades.append(f'<path class="area" fill="url(#{gradient})" d="M{coords[0][0]:.1f},{bottom}L'
                                  + "L".join(f"{px:.1f},{py:.1f}" for px, py in coords)
                                  + f'L{coords[-1][0]:.1f},{bottom}Z"/>')
                halos.append(f'<polyline class="halo" stroke="{s.color}" points="{points}"/>')
                lines.append(f'<polyline class="line" stroke="{s.color}" points="{points}">'
                             f'<title>{escape(s.label)}</title></polyline>')
            elif coords:
                lines.append(f'<circle class="dot" cx="{coords[0][0]:.1f}" cy="{coords[0][1]:.1f}" r="3" '
                             f'fill="{s.color}"><title>{escape(s.label)}</title></circle>')
    parts = ([f"<defs>{''.join(defs)}</defs>"] if defs else []) + shades
    parts += _frame(height, x_axis, y_axis, x_range, y_range) + halos + lines
    for m in markers or []:
        parts.append(_marker(m, _scale(m.x, *x_range, left, right), _scale(m.y, *y_range, bottom, top)))
    return (f'<svg class="chart" viewBox="0 0 {WIDTH} {height}" role="img" aria-label="{escape(title)}">'
            + "".join(parts) + "</svg>")


def _column_path(x: float, width: float, y_top: float, y_bottom: float, rounded: bool) -> str:
    """A column segment; the top segment of a stack gets the rounded data end, the baseline stays square."""
    radius = min(DATA_END_RADIUS, width / 2, max(0.0, y_bottom - y_top)) if rounded else 0.0
    if radius <= 0:
        return f"M{x:.1f},{y_bottom:.1f}V{y_top:.1f}H{x + width:.1f}V{y_bottom:.1f}Z"
    return (f"M{x:.1f},{y_bottom:.1f}V{y_top + radius:.1f}Q{x:.1f},{y_top:.1f} {x + radius:.1f},{y_top:.1f}"
            f"H{x + width - radius:.1f}Q{x + width:.1f},{y_top:.1f} {x + width:.1f},{y_top + radius:.1f}"
            f"V{y_bottom:.1f}Z")


def stacked_columns(columns: list[str], stacks: list[StackSeries], *, y_axis: Axis, y_max: float,
                    column_titles: list[str], value_format, height: int = 240, title: str = "",
                    label_every: int = 1) -> str:
    """One column per entry of ``columns`` (its x label), segments stacked in ``stacks`` order from the baseline."""
    left, right, top, bottom = PLOT_LEFT, WIDTH - PLOT_RIGHT, PLOT_TOP, height - PLOT_BOTTOM
    count = max(1, len(columns))
    slot = (right - left) / count
    width = min(COLUMN_MAX, slot * 0.7)
    x_axis = Axis([(index, label) for index, label in enumerate(columns) if index % label_every == 0])
    parts = _frame(height, Axis(), y_axis, (0, 1), (0.0, y_max))
    for index, label in [(i, l) for i, l in x_axis.ticks]:
        cx = left + slot * (index + 0.5)
        parts.append(f'<text class="tick" x="{cx:.1f}" y="{bottom + 18}" text-anchor="middle">{escape(label)}</text>')
    for index in range(len(columns)):
        x = left + slot * (index + 0.5) - width / 2
        base = 0.0
        segments = [(s, s.values[index]) for s in stacks if s.values[index] > 0]
        for position, (s, value) in enumerate(segments):
            y_bottom = _scale(base, 0.0, y_max, bottom, top)
            y_top = _scale(base + value, 0.0, y_max, bottom, top)
            if position:
                y_bottom -= SEGMENT_GAP / 2
            if position < len(segments) - 1:
                y_top += SEGMENT_GAP / 2
            if y_bottom - y_top >= 0.5:
                path = _column_path(x, width, y_top, y_bottom, rounded=position == len(segments) - 1)
                parts.append(f'<path class="segment" d="{path}" fill="{s.color}">'
                             f'<title>{escape(column_titles[index])} · {escape(s.label)}: {escape(value_format(value))}'
                             f'</title></path>')
            base += value
    return (f'<svg class="chart" viewBox="0 0 {WIDTH} {height}" role="img" aria-label="{escape(title)}">'
            + "".join(parts) + "</svg>")


def nice_ceiling(value: float) -> float:
    """A round axis maximum at or above ``value``: 1, 2, 2.5, 5 or 10 times a power of ten."""
    if value <= 0:
        return 1.0
    base = 10 ** math.floor(math.log10(value))
    for factor in (1, 2, 2.5, 5, 10):
        if base * factor >= value * (1 - 1e-12):
            return base * factor
    return base * 10
