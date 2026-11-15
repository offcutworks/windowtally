"""Where the History view's summary tiles stand at a width, in pixels, with no toolkit — ``history_view`` places
them, so the arrangement is tested without a display.

The tiles stand in columns of one width, every tile in one column, so a row's edges line up with the rows above and
below it and the tiles reach from one side of the column to the other, as the charts and tables under them do. A tile
gives the least width it can stand in — its figure, and its caption's longest word, since a caption wraps — and no
column is narrower than the widest of those, nor than the least width the caller sets, the history page's own, so the
window's tiles stand as the page's do. As many columns stand as fit at that width, never more than the tiles; of the
counts that hold the tiles in that many rows the fewest is taken, so the rows are as full as they can be. The tiles keep
their order, left to right and row by row. A row is as tall as its tallest tile, and every tile is stretched to its
column and its row. A width narrower than the widest tile gives one column, as wide as the width.

Every column's edges are rounded once, from where the column stands, so a column starts and ends at the same pixel in
every row.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

LEAST_WIDTH = 160   # a column's least width in pixels at 100 % display scale: the history page's tile columns' own


@dataclass(frozen=True)
class TilePlace:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class TileMarks:
    places: tuple[TilePlace, ...]                # one per tile, in the tiles' order
    height: int                                  # of every row, with the gaps between them
    columns: int


def layout_tiles(sizes: tuple[tuple[int, int], ...], width: int, gap: int, least: int = 0) -> TileMarks:
    """``sizes`` are each tile's least width and its height; ``width`` is the room the tiles share, ``gap`` the space
    between two tiles, side by side or one above the other, and ``least`` the width no column is narrower than."""
    if not sizes:
        return TileMarks((), 0, 0)
    need = max(least, max(w for w, _h in sizes))
    most = max((c for c in range(1, len(sizes) + 1) if (width + gap) / c - gap >= need - 1e-9), default=1)
    rows = math.ceil(len(sizes) / most)
    columns = min(c for c in range(1, most + 1) if math.ceil(len(sizes) / c) == rows)
    pitch = (width + gap) / columns              # a column and the gap after it

    places: list[TilePlace] = []
    y = 0
    for number in range(rows):
        row = range(number * columns, min(len(sizes), (number + 1) * columns))
        tall = max(sizes[index][1] for index in row)
        for at, _index in enumerate(row):
            x0, x1 = round(at * pitch), round((at + 1) * pitch - gap)
            places.append(TilePlace(x0, y, x1 - x0, tall))
        y += tall + (gap if number < rows - 1 else 0)
    return TileMarks(tuple(places), y, columns)
