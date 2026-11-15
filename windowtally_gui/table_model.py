"""A History view's table laid out as text at places in pixels, with no toolkit — ``table_view`` paints it — so the
layout is tested without a display.

Every column is as wide as its widest text — its heading, or a cell measured in bold, so a total row fits — plus room
on both sides; words stand at a column's left, figures at its right. A table given a width to fill that is wider than
its columns need shares the difference among them in proportion to their widths, as a browser widens a table set to
the page's width, so every table of the view reaches the view's right edge as its charts do; one whose columns need
more is as wide as they need. The headings take a row of their own above the rows, every row is as tall as the
others, and the table is as tall as all its rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .history_model import FIGURES


@dataclass(frozen=True)
class Cell:
    x: float
    y: float                                     # the middle of its row
    text: str
    anchor: str                                  # w: starts at x (words); e: ends at x (figures)
    bold: bool = False


@dataclass(frozen=True)
class TableMarks:
    width: float
    height: float
    heading_height: float                        # the headings' row, from the top
    edges: tuple[float, ...]                     # every column's left edge, then the last one's right edge
    headings: tuple[Cell, ...]
    cells: tuple[Cell, ...]


def trailing_totals(totals: tuple[int, ...], count: int) -> int:
    """How many of ``count`` rows at the table's end are total rows."""
    found = 0
    while found < count and count - 1 - found in totals:
        found += 1
    return found


def layout_table(columns: tuple[tuple[str, str], ...], rows: tuple[tuple[str, ...], ...], totals: tuple[int, ...],
                 heading_width: Callable[[str], float], bold_width: Callable[[str], float], room: float,
                 heading_height: float, row_height: float, width: float = 0.0) -> TableMarks:
    """``columns`` are (heading, alignment); ``totals`` the rows set in bold; ``room`` the space a column adds to its
    widest text, half on each side; ``width`` the width to fill, 0 for none."""
    widths = []
    for index, (heading, _align) in enumerate(columns):
        widest = max([heading_width(heading)] + [bold_width(row[index]) for row in rows])
        widths.append(widest + room)
    needed = sum(widths)
    if width > needed > 0:
        widths = [w * width / needed for w in widths]
    edges = [0.0]
    for column in widths:
        edges.append(edges[-1] + column)

    def place(index: int, align: str) -> float:
        return edges[index + 1] - room / 2 if align == FIGURES else edges[index] + room / 2

    headings = tuple(Cell(place(index, align), heading_height / 2, heading, align)
                     for index, (heading, align) in enumerate(columns))
    cells = []
    for number, row in enumerate(rows):
        middle = heading_height + row_height * (number + 0.5)
        for index, (_heading, align) in enumerate(columns):
            cells.append(Cell(place(index, align), middle, row[index], align, number in totals))
    return TableMarks(edges[-1], heading_height + row_height * len(rows), heading_height, tuple(edges), headings,
                      tuple(cells))
