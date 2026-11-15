"""WindowTally's logo, drawn as pixels from its geometry with the standard library: the logo is reviewed as code, and
the program keeps no image of it. The one copy of it in the tree is the README's logo, ``images/logo.png``: this
drawing at 256 pixels as ``png`` writes it, which a test holds to the drawing, so a change here fails that test until
the file is written again.

The mark is two rings on a dark rounded tile with a grey rim: the weekly window the outer ring, in blue, the 5-hour
window the inner ring, in green, each filled clockwise from the top over a dim track. The logo at rest is the two rings
at fixed fills (``logo_rows``); the tray draws the same rings live, each ring filled as far as its window is used
(``tray_model``). One ring as thick as the two together stands for a single window. A greyed tile, its rings empty,
says that nothing on it is to be read as a figure.

Every size is drawn on its own pixel grid, never scaled from another. Up to ``SNAPPED_UP_TO`` pixels each ring and the
gap between them are a whole number of pixels wide, so the small sizes the tray and the title bar show stay as legible
as the large; above it the geometry is kept as drawn. Edges are smoothed by sampling each pixel on a sub-grid, so the
cost grows with the area: the tray's sizes take a few milliseconds, 256 pixels about a second, which is why that size
is drawn only for the Start menu entry's icon file.

The dark tile shows on a light taskbar and, by its grey rim, on a dark one. ``png`` encodes rows as a PNG holding only
the image itself (IHDR, IDAT, IEND); ``ico`` writes a Windows icon file of several sizes, each stored as such a PNG,
which Windows Vista and later read in an icon file at every size.
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass

from windowtally.rings import FIVE_HOUR, WEEKLY   # the rings' colours, which a card's rings and the page's wear too

Pixel = tuple[int, int, int, int]

TILE = "#1f1f1d"
RIM = "#7a7873"
TRACK = "#3b3b38"
GREY_TILE = "#2a2a28"
GREY_RIM = "#66645f"
GREY_TRACK = "#3d3d3a"
AT_REST = (0.70, 0.45)          # the logo's weekly and 5-hour fills

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
"""The sizes the Start menu entry's icon file holds: the small icon at 100-250 % scale, the large ones, and the
largest Windows shows."""
SNAPPED_UP_TO = 48
SAMPLES = 4                     # each pixel is sampled on a SAMPLES x SAMPLES sub-grid


def rgba(colour: str, alpha: int = 255) -> Pixel:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16), alpha


@dataclass(frozen=True)
class Ring:
    used: float | None          # 0 to 1, filled clockwise from the top; None draws the track alone
    colour: str


@dataclass(frozen=True)
class Geometry:
    corner: float               # the tile's corner radius
    rim: int                    # the rim's width
    outer: tuple[float, float]  # the weekly ring's inner and outer radius
    inner: tuple[float, float]  # the 5-hour ring's
    single: tuple[float, float]  # one ring over both bands and the gap between them


def geometry(size: int) -> Geometry:
    """The tile and the rings at ``size`` pixels, in pixels from the tile's centre."""
    rim = max(1, round(size / 24))
    reach = size / 2 - rim - max(1, round(size * 0.06))
    if size <= SNAPPED_UP_TO:
        width, gap = max(1, round(0.28 * reach)), max(1, round(0.10 * reach))
    else:
        width, gap = 0.28 * reach, 0.10 * reach
    inner = (reach - 2 * width - gap, reach - width - gap)
    return Geometry(size * 0.2, rim, (reach - width, reach), inner, (inner[0], reach))


def _inside_rounded(x: float, y: float, low: float, high: float, radius: float) -> bool:
    """Whether the point lies inside the square from ``low`` to ``high`` on both axes, its corners of ``radius``."""
    if not (low <= x < high and low <= y < high):
        return False
    nearest_x = min(max(x, low + radius), high - radius)
    nearest_y = min(max(y, low + radius), high - radius)
    return (x - nearest_x) ** 2 + (y - nearest_y) ** 2 <= radius * radius


def rings_rows(size: int, weekly: Ring, five_hour: Ring | None, rim: str = RIM,
               greyed: bool = False) -> list[list[Pixel]]:
    """The tile and its rings, ``size`` pixels square, row by row. ``five_hour`` None draws the weekly window as one
    ring over both bands; ``rim`` colours the tile's rim; ``greyed`` draws the greyed tile, every ring empty."""
    shape = geometry(size)
    if greyed:
        tile, edge, track = rgba(GREY_TILE), rgba(GREY_RIM), rgba(GREY_TRACK)
    else:
        tile, edge, track = rgba(TILE), rgba(rim), rgba(TRACK)
    if five_hour is None:
        bands = [(shape.single, weekly)]
    else:
        bands = [(shape.outer, weekly), (shape.inner, five_hour)]
    painted = [(low, high, None if greyed or ring.used is None else ring.used * 2 * math.pi, rgba(ring.colour))
               for (low, high), ring in bands]
    centre, inset, full = size / 2, shape.rim, SAMPLES * SAMPLES
    inner_corner = max(0.5, shape.corner - shape.rim)
    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            red = green = blue = covered = 0
            for j in range(SAMPLES):
                y = py + (j + 0.5) / SAMPLES
                for i in range(SAMPLES):
                    x = px + (i + 0.5) / SAMPLES
                    if not _inside_rounded(x, y, 0, size, shape.corner):
                        continue
                    colour = tile
                    if not _inside_rounded(x, y, inset, size - inset, inner_corner):
                        colour = edge
                    else:
                        dx, dy = x - centre, y - centre
                        distance = math.hypot(dx, dy)
                        for low, high, sweep, fill in painted:
                            if low <= distance < high:
                                clockwise = math.atan2(dx, -dy) % (2 * math.pi)
                                colour = fill if sweep is not None and clockwise < sweep else track
                    red, green, blue, covered = red + colour[0], green + colour[1], blue + colour[2], covered + 1
            if covered:
                row.append((round(red / covered), round(green / covered), round(blue / covered),
                            round(255 * covered / full)))
            else:
                row.append((0, 0, 0, 0))
        rows.append(row)
    return rows


def logo_rows(size: int) -> list[list[Pixel]]:
    """The logo at rest, ``size`` pixels square."""
    weekly, five_hour = AT_REST
    return rings_rows(size, Ring(weekly, WEEKLY), Ring(five_hour, FIVE_HOUR))


def png(rows: list[list[Pixel]]) -> bytes:
    """The rows as a PNG image, 8-bit RGBA."""
    height, width = len(rows), len(rows[0])
    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def ico(images: dict[int, list[list[Pixel]]]) -> bytes:
    """A Windows icon file holding each size's rows as a PNG, the sizes in ascending order."""
    entries = [(size, png(images[size])) for size in sorted(images)]
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = len(header) + 16 * len(entries)
    directory, data = b"", b""
    for size, image in entries:
        side = 0 if size >= 256 else size      # 0 stands for 256 in an icon directory
        directory += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(image), offset + len(data))
        data += image
    return header + directory + data


def icon_file(sizes: tuple[int, ...] = ICON_SIZES) -> bytes:
    """The logo as a Windows icon file."""
    return ico({size: logo_rows(size) for size in sizes})
