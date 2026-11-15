"""A card's rings, with no toolkit and no markup: an account's two windows as concentric rings, as the logo and the tray
icon draw them. The window's cards paint them (``windowtally_gui.cards_view``) and the history page's cards write them
as SVG (``dashboard``), so both draw one geometry in one set of colours.

The outer ring is the weekly window and the inner one the 5-hour window, each a track and an arc filled clockwise from
the top as far as the window is used. Each arc takes its own window's level as the tray's rings do: below the window's
first warning figure the logo's colour for that window (``WEEKLY``, ``FIVE_HOUR``, which the logo's drawing takes from
here), the same in both modes; at a warning the palette's warning fill; at an error its critical fill. An account with
no 5-hour limit draws its weekly window alone, one band in the weekly ring's place and no thicker, so no empty ring
reads as a window at zero; a window not started, or one with no figure, shows its track alone. The tray icon draws its
own rings (``windowtally_gui.tray_model``) and keeps its single ring as thick as the two bands.

The geometry is in pixels for a square of ``size``, with a margin kept free around the outer ring for the glow the
dark mode lays on its arcs.
"""

from __future__ import annotations

from dataclasses import dataclass

WEEKLY = "#3987e5"      # the weekly window's ring at rest: the logo's blue
FIVE_HOUR = "#1baf7a"   # the 5-hour window's ring at rest: the logo's green

BAND = 0.08        # a ring's band, as a share of the square's side
GAP = 0.035         # the space between the two bands, likewise
MARGIN = 0.035      # the space kept around the outer band for its glow, likewise


@dataclass(frozen=True)
class Ring:
    radius: float       # the band's middle, in pixels from the square's centre
    width: float        # the band's width in pixels
    fraction: float     # how far the arc runs, 0 to 1
    level: int          # the window's warning level, 0 to 2
    rest: str           # the arc's colour below a warning: the logo's colour for the window


def rings(size: float, weekly: tuple[float, int], five_hour: tuple[float, int] | None) -> tuple[Ring, ...]:
    """The rings for a square of ``size`` pixels: the weekly window's ring, outermost, then the 5-hour window's; for an
    account with no 5-hour limit (``five_hour`` None) the weekly window's alone, in its own place and of its own band.
    Each window is its fraction used and its level."""
    band, gap = size * BAND, size * GAP
    outer = size / 2 - size * MARGIN - band / 2
    inner = outer - band - gap
    if five_hour is None:
        return (Ring(outer, band, _held(weekly[0]), weekly[1], WEEKLY),)
    return (Ring(outer, band, _held(weekly[0]), weekly[1], WEEKLY),
            Ring(inner, band, _held(five_hour[0]), five_hour[1], FIVE_HOUR))


def fill(ring: Ring, warning: str, critical: str) -> str:
    """The colour ``ring``'s arc is drawn in: its window's at rest, the warning or the critical fill at those levels."""
    return level_colour(ring.rest, ring.level, warning, critical)


def level_colour(rest: str, level: int, warning: str, critical: str) -> str:
    """``rest`` below a warning, else the warning or the critical fill: an arc's colour, and that of the dot that
    keys a window's name to its ring."""
    return (rest, warning, critical)[max(0, min(level, 2))]


def rest_colour(kind: str) -> str:
    """The colour a window's ring wears at rest: the weekly window's (``seven_day``) or the 5-hour window's."""
    return WEEKLY if kind == "seven_day" else FIVE_HOUR


def _held(fraction: float) -> float:
    return max(0.0, min(1.0, fraction))
