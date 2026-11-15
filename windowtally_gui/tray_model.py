"""The tray icon's picture: the logo's rings (``logo_model``) showing the account in use's windows live. The outer ring
is its weekly window and the inner ring its 5-hour window, each filled clockwise from the top as far as the window is
used; for an account with no 5-hour limit, one ring as thick as the two together, its weekly window, so no empty ring
reads as a window at zero. Each ring takes its own window's level: below the window's first warning figure it wears
the logo's colour for that window, at a warning the palette's warning fill, at an error its critical fill. The tile's
rim wears the account in use's colour, so the tray tells which account is in use while staying the logo. Without a
fresh status for the account in use the tile is greyed and its rings empty: nothing on it is to be read as a figure.

Drawing the picture here, as pixels, keeps it testable without a display; ``common_view.image_of`` makes it an image.
"""

from __future__ import annotations

from .logo_model import FIVE_HOUR, WEEKLY, Pixel, Ring, rings_rows


def icon_rows(size: int, rim: str, warning: str, critical: str, *, five_hour: float | None = None,
              weekly: float | None = None, five_hour_level: int = 0, weekly_level: int = 0,
              weekly_only: bool = False, greyed: bool = False) -> list[list[Pixel]]:
    """The picture, ``size`` pixels square, row by row. ``rim`` is the account in use's colour; ``warning`` and
    ``critical`` are the fills of the two warning levels; a window's fill runs from 0 to 1, None without a figure, and
    its level is 0, 1 or 2. ``weekly_only`` draws the weekly window alone, the 5-hour window unread; ``greyed`` draws
    the greyed tile."""

    def ring(used: float | None, level: int, own: str) -> Ring:
        return Ring(used, (own, warning, critical)[max(0, min(level, 2))])

    weekly_ring = ring(weekly, weekly_level, WEEKLY)
    five_hour_ring = None if weekly_only else ring(five_hour, five_hour_level, FIVE_HOUR)
    return rings_rows(size, weekly_ring, five_hour_ring, rim=rim, greyed=greyed)
