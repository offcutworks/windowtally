"""The logo and what carries it: two rings on a dark tile drawn at every size from its geometry, each filled clockwise
from the top; one ring for a single window; the greyed tile; the PNG and the icon file it is written as; the README's
picture, held to the drawing; and the About window's words — the release named from the build record a copy ships, the
copyright line read from the licence it ships, the notices offered only where it ships them, and the official copies'
address."""

import math
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import fixtures  # noqa: F401  (puts the tool folder on the import path)
from windowtally.release import BUILD_FILE_NAME, Release, write_release
from windowtally_gui.about_model import (LICENCE_FILE_NAME, MISSING_LICENCE, NO_COPYRIGHT, NOTICES_FILE_NAME,
                                         OFFICIAL_COPIES, about_content, copyright_line)
from windowtally_gui.logo_model import (FIVE_HOUR, GREY_TILE, ICON_SIZES, SAMPLES, SNAPPED_UP_TO, TILE, TRACK, WEEKLY,
                                        Ring, geometry, ico, icon_file, logo_rows, png, rgba, rings_rows)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
README_LOGO = fixtures.TOOL_ROOT / "images" / "logo.png"
README_LOGO_SIZE = 256
REWRITE_README_LOGO = ("in the tool folder, python -c \"from pathlib import Path; from windowtally_gui.logo_model import "
                       f"logo_rows, png; Path('images/logo.png').write_bytes(png(logo_rows({README_LOGO_SIZE})))\"")
EDGE_LEVELS = math.ceil(255 / SAMPLES ** 2)   # what one sub-sample changing sides moves a channel by, at most
EDGE_PIXELS = 64                              # pixels such a sample may move: far fewer than any redraw moves


def ring_pixel(rows, band: tuple[float, float], degrees: float) -> tuple:
    """The pixel in the middle of ``band`` at ``degrees`` clockwise from the top."""
    centre, radius = len(rows) / 2, sum(band) / 2
    turn = math.radians(degrees)
    return rows[int(centre - radius * math.cos(turn))][int(centre + radius * math.sin(turn))]


def png_chunks(data: bytes):
    """A PNG's chunks in order, each as (kind, body)."""
    at = len(PNG_SIGNATURE)
    while at < len(data):
        length = struct.unpack(">I", data[at:at + 4])[0]
        yield data[at + 4:at + 8], data[at + 8:at + 8 + length]
        at += 12 + length


def chunks(data: bytes) -> list[bytes]:
    return [kind for kind, _body in png_chunks(data)]


def decoded_rows(data: bytes) -> list[list[tuple]]:
    """An 8-bit RGBA PNG's pixels, row by row, as ``png`` stores them: each row unfiltered. Compared rather than the
    file's bytes, which another zlib may compress differently; ValueError for a row stored with a filter."""
    width = struct.unpack(">I", data[16:20])[0]
    raw = zlib.decompress(b"".join(body for kind, body in png_chunks(data) if kind == b"IDAT"))
    stride = 1 + 4 * width
    rows = []
    for at in range(0, len(raw), stride):
        if raw[at] != 0:
            raise ValueError(f"row {at // stride} is stored with filter {raw[at]}")
        rows.append([tuple(raw[pixel:pixel + 4]) for pixel in range(at + 1, at + stride, 4)])
    return rows


class LogoTest(unittest.TestCase):
    def test_every_size_is_square_with_clear_corners_and_the_tile_in_the_middle(self):
        for size in (16, 20, 24, 32, 48, 64):
            rows = logo_rows(size)
            self.assertEqual((len(rows), {len(row) for row in rows}), (size, {size}), size)
            for x, y in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
                self.assertEqual(rows[y][x][3], 0, (size, x, y))
            if size > 16:
                self.assertEqual(rows[size // 2][size // 2], rgba(TILE), size)

    def test_each_ring_fills_clockwise_from_the_top(self):
        rows = logo_rows(64)
        shape = geometry(64)
        self.assertEqual(ring_pixel(rows, shape.outer, 10), rgba(WEEKLY), "the weekly ring starts at the top")
        self.assertEqual(ring_pixel(rows, shape.outer, 180), rgba(WEEKLY))
        self.assertEqual(ring_pixel(rows, shape.outer, 300), rgba(TRACK), "and stops short of it")
        self.assertEqual(ring_pixel(rows, shape.inner, 90), rgba(FIVE_HOUR))
        self.assertEqual(ring_pixel(rows, shape.inner, 200), rgba(TRACK))
        self.assertEqual(ring_pixel(rows, shape.inner, 350), rgba(TRACK))

    def test_the_small_sizes_draw_each_ring_and_the_gap_a_whole_number_of_pixels_wide(self):
        for size in (16, 20, 24, 32, 40, 48):
            shape = geometry(size)
            widths = (shape.outer[1] - shape.outer[0], shape.inner[1] - shape.inner[0], shape.outer[0] - shape.inner[1])
            self.assertTrue(all(width >= 1 and width == int(width) for width in widths), (size, widths))
            self.assertLess(shape.inner[0], shape.inner[1], size)
        self.assertGreater(256, SNAPPED_UP_TO)
        large = geometry(256)
        self.assertAlmostEqual((large.outer[1] - large.outer[0]) / (large.inner[1] - large.inner[0]), 1.0)

    def test_one_ring_covers_both_bands_and_the_gap(self):
        rows = rings_rows(48, Ring(1.0, WEEKLY), None)
        shape = geometry(48)
        for band in (shape.outer, shape.inner, (shape.inner[1], shape.outer[0])):
            self.assertEqual(ring_pixel(rows, band, 180), rgba(WEEKLY), band)

    def test_a_ring_without_a_figure_draws_its_track_alone(self):
        rows = rings_rows(48, Ring(None, WEEKLY), Ring(0.5, FIVE_HOUR))
        shape = geometry(48)
        self.assertEqual(ring_pixel(rows, shape.outer, 90), rgba(TRACK))
        self.assertNotIn(rgba(WEEKLY), {pixel for row in rows for pixel in row})

    def test_the_greyed_tile_fills_no_ring(self):
        rows = rings_rows(32, Ring(1.0, WEEKLY), Ring(1.0, FIVE_HOUR), greyed=True)
        used = {pixel for row in rows for pixel in row}
        self.assertNotIn(rgba(WEEKLY), used)
        self.assertNotIn(rgba(FIVE_HOUR), used)
        self.assertIn(rgba(GREY_TILE), used)


class EncodingTest(unittest.TestCase):
    def test_the_png_carries_the_image_alone(self):
        data = png(logo_rows(24))
        self.assertTrue(data.startswith(PNG_SIGNATURE))
        self.assertEqual(chunks(data), [b"IHDR", b"IDAT", b"IEND"])
        self.assertEqual(struct.unpack(">IIBB", data[16:26]), (24, 24, 8, 6), "24 x 24, 8-bit RGBA")

    def test_the_icon_file_holds_each_size_as_a_png_in_ascending_order(self):
        sizes = (32, 16, 24)
        data = ico({size: logo_rows(size) for size in sizes})
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind, count), (0, 1, 3))
        seen = []
        for index in range(count):
            width, height, _colours, _zero, planes, bits, length, offset = struct.unpack(
                "<BBBBHHII", data[6 + 16 * index:22 + 16 * index])
            image = data[offset:offset + length]
            self.assertTrue(image.startswith(PNG_SIGNATURE))
            self.assertEqual(struct.unpack(">II", image[16:24]), (width, height))
            self.assertEqual((planes, bits), (1, 32))
            seen.append(width)
        self.assertEqual(seen, [16, 24, 32])
        self.assertEqual(offset + length, len(data), "the last image ends the file")

    def test_256_pixels_is_written_as_0_in_the_directory(self):
        clear = [[(0, 0, 0, 0)] * 256 for _ in range(256)]
        data = ico({256: clear})
        self.assertEqual(data[6:8], b"\x00\x00")
        offset = struct.unpack("<I", data[18:22])[0]
        self.assertEqual(struct.unpack(">II", data[offset + 16:offset + 24]), (256, 256))

    def test_the_start_menu_icon_holds_every_size_up_to_256(self):
        self.assertEqual(ICON_SIZES[-1], 256)
        self.assertTrue({16, 20, 24, 32, 48} <= set(ICON_SIZES))
        data = icon_file()
        self.assertEqual(struct.unpack("<H", data[4:6])[0], len(ICON_SIZES))


class ReadmeLogoTest(unittest.TestCase):
    def test_the_readme_s_picture_is_the_logo_as_drawn(self):
        # The tree's one copy of the logo: a copy of the drawing, so a change to the drawing fails here until rewritten.
        # Another maths library may put a sample on a ring's end on the other side of it, moving that pixel by at most
        # one sample's share; a redrawn ring, fill or colour moves far more pixels, or by far more.
        data = README_LOGO.read_bytes()
        self.assertEqual(chunks(data), [b"IHDR", b"IDAT", b"IEND"], "the image alone, nothing else a PNG can carry")
        self.assertEqual(struct.unpack(">IIBB", data[16:26]), (README_LOGO_SIZE, README_LOGO_SIZE, 8, 6))
        stored, drawn = decoded_rows(data), logo_rows(README_LOGO_SIZE)
        self.assertEqual(len(stored), README_LOGO_SIZE)
        moved = [step for row, wanted in zip(stored, drawn) for pixel, expected in zip(row, wanted)
                 if (step := max(abs(got - want) for got, want in zip(pixel, expected)))]
        message = f"the README's picture differs from the logo as drawn; rewrite it: {REWRITE_README_LOGO}"
        self.assertLessEqual(max(moved, default=0), EDGE_LEVELS, message)
        self.assertLessEqual(len(moved), EDGE_PIXELS, message)


class AboutTest(unittest.TestCase):
    def test_the_licence_this_folder_ships_names_offcutworks_and_no_notices_are_offered(self):
        content = about_content(fixtures.TOOL_ROOT)
        self.assertRegex(content.copyright, r"^Copyright \(c\) \d{4} offcutworks$")
        self.assertTrue(content.licence.startswith("MIT License"))
        self.assertIsNone(content.notices, "a copy from source ships no third-party notices")
        self.assertTrue(content.version.startswith("Version "))

    def test_a_copy_without_its_licence_says_so_and_a_release_offers_its_notices(self):
        with tempfile.TemporaryDirectory() as folder:
            content = about_content(Path(folder))
            self.assertIsNone(content.licence)
            self.assertEqual(content.copyright, MISSING_LICENCE)
            Path(folder, LICENCE_FILE_NAME).write_text("MIT License\n\nCopyright (c) 2027 someone\n", encoding="utf-8")
            Path(folder, NOTICES_FILE_NAME).write_text("Python: PSF License\n", encoding="utf-8")
            content = about_content(Path(folder))
            self.assertEqual(content.copyright, "Copyright (c) 2027 someone")
            self.assertEqual(content.notices, "Python: PSF License\n")

    def test_the_copyright_line_is_the_licence_s_own_and_none_without_one(self):
        self.assertEqual(copyright_line("MIT License\n\n  Copyright (c) 2026 offcutworks  \nPermission"),
                         "Copyright (c) 2026 offcutworks")
        self.assertIsNone(copyright_line("No notice here"))
        self.assertIsNone(copyright_line(None))
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, LICENCE_FILE_NAME).write_text("A licence with no notice\n", encoding="utf-8")
            self.assertEqual(about_content(Path(folder)).copyright, NO_COPYRIGHT, "never a blank line")

    def test_the_version_line_names_a_release_by_its_build_record_and_a_copy_from_source_as_such(self):
        self.assertEqual(about_content(fixtures.TOOL_ROOT).version, "Version 1.0.0, from source")
        with tempfile.TemporaryDirectory() as folder:
            write_release(Path(folder), Release("2027.5.2", "3.14.8"))
            self.assertEqual(about_content(Path(folder)).version, "Version 1.0.0, release 2027.5.2")
            Path(folder, BUILD_FILE_NAME).write_text("not a record", encoding="utf-8")
            self.assertEqual(about_content(Path(folder)).version, "Version 1.0.0, release unknown")

    def test_official_copies_come_from_the_publisher_s_repository(self):
        self.assertEqual(OFFICIAL_COPIES, "https://github.com/offcutworks/windowtally")


if __name__ == "__main__":
    unittest.main()
