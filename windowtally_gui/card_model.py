"""An account card's own layout logic, with no toolkit: its colour ring's proportion, where a line's pieces of text go
at a width, and how far a per-model window's bar is filled.

The dot. A disc in the account's colour; an account whose plan has ended wears its colour as a ring of the same size
instead, ``RING_INNER`` of the radius hollow: still its colour, as in the History window's charts, but hollow, as set
aside. ``cards_view`` paints either with a smoothed edge.

A line's pieces. A card line is pieces of text, each in a colour of its own — when a window resets, then its pace and
reading — written one after another, joined by a separator, while they fit the card's width. From the first piece that
does not fit, it and every piece after it go whole onto a line of their own, without the separator, so no word is ever
hidden and the line's start stays where the eye looks for it. A first piece wider than the whole width has a line of its
own from the start, where its words wrap, rather than being cut at the card's edge.

The per-model bar. A per-model window (Fable's) has no ring: it is a thin bar under the rings, filled from the left as far
as the window is used (``WindowRow.fraction``), a used window never thinner than the bar is tall so it reads as used.
A window with no figure (``unknown``) has nothing to fill and must not read as a window at zero: its track is drawn as
dashes, never whole (``bar_dashes``), beside the word that says it is unknown.
"""

from __future__ import annotations

from typing import Callable

Place = tuple[str, int, bool]   # the text shown, its line (0 the first), whether it has a line of its own

RING_INNER = 0.55   # a ring's inner radius as a share of its outer one
UNKNOWN = "unknown"  # the figure of a window with no reading to fill a bar from


def flow_places(texts: tuple[str, ...], joins: tuple[str, ...], width: int,
                measure: Callable[[int, str], int]) -> tuple[Place | None, ...]:
    """Where each piece of ``texts`` goes at ``width`` pixels: None for an empty piece, else its place. ``joins[i]``
    stands before piece ``i`` when it follows another on the first line; ``measure(i, text)`` is the width of ``text``
    in piece ``i``'s font. A width of 0 (not laid out yet) puts every piece on the first line."""
    places: list[Place | None] = []
    line, used, alone = 0, 0, False
    for index, text in enumerate(texts):
        if not text:
            places.append(None)
            continue
        first = not any(places)
        shown = text if first or alone else joins[index] + text
        if first and width and measure(index, shown) > width:
            alone = True                     # on line 0, its words wrapping; every later piece on a line of its own
            places.append((shown, line, alone))
            continue
        if not first and not alone and width and used + measure(index, shown) > width:
            alone = True
        if alone:
            line, shown = line + 1, text
        used += measure(index, shown)
        places.append((shown, line, alone))
    return tuple(places)


def bar_known(figure: str) -> bool:
    """Whether a per-model window's ``figure`` gives a bar to fill: every figure but ``unknown``."""
    return figure != UNKNOWN


def bar_fill(width: float, height: float, fraction: float, known: bool) -> float:
    """How many pixels of a bar ``width`` long and ``height`` tall are filled: none for an unknown window or one at
    nothing used, else its fraction of the width, never less than its height, never more than the width."""
    if not known or fraction <= 0 or width <= 0:
        return 0.0
    return min(width, max(height, width * min(fraction, 1.0)))


def bar_dashes(width: float, height: float) -> tuple[tuple[float, float], ...]:
    """The dashes an unknown window's track is drawn as, each its start and its length: dashes twice the bar's height
    long with a gap of its height, the last cut at the bar's end."""
    if width <= 0 or height <= 0:
        return ()
    dash, step = 2 * height, 3 * height
    dashes, start = [], 0.0
    while start < width:
        dashes.append((start, min(dash, width - start)))
        start += step
    return tuple(dashes)
