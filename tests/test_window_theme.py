"""The window's colours and its pictures: every role in both modes, text roles legible on every surface they are
written on, the mode Windows asks for and the theme the user chose, the icon's pixels and PNG, and the placement of a card's
lines' pieces."""

import json
import math
import struct
import tempfile
import unittest
import zlib
from dataclasses import replace
from pathlib import Path

import fixtures  # noqa: F401  (puts the tool folder on the import path, for a run of this module alone)
from windowtally import palette
from windowtally_gui.card_model import flow_places
from windowtally_gui.state_model import WindowState, load_state, save_state
from windowtally_gui.theme_model import (LEVEL_TEXTS, ROLES, THEME_CHOICES, THEME_LABELS, chosen_mode, colours,
                                         contrast, windows_mode)
from windowtally_gui.logo_model import FIVE_HOUR, GREY_RIM, TRACK, WEEKLY, geometry, png, rgba
from windowtally_gui.tray_model import icon_rows

TEXT_SURFACES = ("page", "surface-1", "field", "face", "hover", "selection")


class ColoursTest(unittest.TestCase):
    def test_every_role_has_a_colour_in_both_modes(self):
        for mode in ("light", "dark"):
            found = colours(mode)
            self.assertEqual(set(found), set(ROLES), mode)
            self.assertTrue(all(len(v) == 7 and v.startswith("#") for v in found.values()), mode)

    def test_the_surfaces_ink_and_accounts_are_the_history_page_s(self):
        for mode, page in (("light", palette.LIGHT), ("dark", palette.DARK)):
            found = colours(mode)
            for role in ("page", "surface-1", "ink", "ink-2", "series-1", "series-2", "series-3", "warning",
                         "critical"):
                self.assertEqual(found[role], page[role], (mode, role))

    def test_every_text_role_reads_at_4_5_to_1_on_every_surface(self):
        for mode in ("light", "dark"):
            found = colours(mode)
            for text in ("ink", "ink-2") + LEVEL_TEXTS[1:]:
                for surface in TEXT_SURFACES:
                    with self.subTest(mode=mode, text=text, surface=surface):
                        self.assertGreaterEqual(contrast(found[text], found[surface]), 4.5)

    def test_the_recommendation_s_band_reads_at_4_5_to_1(self):
        for mode in ("light", "dark"):
            found = colours(mode)
            for text in ("ink", "critical-text"):    # critical-text once every account is at its limit
                with self.subTest(mode=mode, text=text):
                    self.assertGreaterEqual(contrast(found[text], found["advice"]), 4.5)

    def test_the_accent_button_s_ink_reads_at_4_5_to_1_on_each_of_its_faces_and_its_ring_stands_out_from_the_card(self):
        for mode in ("light", "dark"):
            found = colours(mode)
            for face in ("selection", "advice", "pressed"):     # at rest, under the pointer, pressed
                with self.subTest(mode=mode, face=face):
                    self.assertGreaterEqual(contrast(found["ink"], found[face]), 4.5)
            with self.subTest(mode=mode, what="ring on the card"):   # a control's edge: 3:1 against what it stands on
                self.assertGreaterEqual(contrast(found["focus"], found["surface-1"]), 3.0)

    def test_cards_stand_apart_from_the_page_and_the_page_s_notes_are_legible(self):
        for mode, page in (("light", palette.LIGHT), ("dark", palette.DARK)):
            with self.subTest(mode=mode):
                self.assertGreaterEqual(contrast(page["surface-1"], page["page"]), 1.1)
                for surface in ("page", "surface-1"):
                    self.assertGreaterEqual(contrast(page["muted"], page[surface]), 4.5)

    def test_the_mode_follows_windows_and_is_light_where_it_cannot_be_read(self):
        self.assertEqual(windows_mode(lambda: 0), "dark")
        self.assertEqual(windows_mode(lambda: 1), "light")

        def unreadable():
            raise OSError("no such key")

        self.assertEqual(windows_mode(unreadable), "light")


def ring_pixel(rows, band: tuple[float, float], degrees: float) -> tuple:
    """The pixel in the middle of ``band`` at ``degrees`` clockwise from the top."""
    centre, radius = len(rows) / 2, sum(band) / 2
    turn = math.radians(degrees)
    return rows[int(centre - radius * math.cos(turn))][int(centre + radius * math.sin(turn))]


class TrayPictureTest(unittest.TestCase):
    ORANGE, AMBER, RED = "#eb6834", "#fab219", "#d03b3b"

    def test_each_ring_takes_its_own_window_s_level_the_rim_the_account_s_colour_and_the_corners_are_clear(self):
        rows = icon_rows(32, self.ORANGE, self.AMBER, self.RED, five_hour=0.5, weekly=1.0, five_hour_level=1,
                         weekly_level=0)
        shape = geometry(32)
        self.assertEqual((len(rows), len(rows[0])), (32, 32))
        self.assertEqual(rows[0][0][3], 0, "a rounded corner is transparent")
        self.assertEqual(rows[0][16], rgba(self.ORANGE), "the rim wears the account in use's colour")
        self.assertEqual(ring_pixel(rows, shape.outer, 90), rgba(WEEKLY), "the weekly ring below a warning, all used")
        self.assertEqual(ring_pixel(rows, shape.outer, 270), rgba(WEEKLY))
        self.assertEqual(ring_pixel(rows, shape.inner, 90), rgba(self.AMBER), "the 5-hour ring at its warning")
        self.assertEqual(ring_pixel(rows, shape.inner, 270), rgba(TRACK), "half the 5-hour window used")
        colours_used = {pixel for row in rows for pixel in row}
        self.assertNotIn(rgba(self.RED), colours_used)
        self.assertNotIn(rgba(FIVE_HOUR), colours_used, "the 5-hour ring wears the warning fill, not its own")
        errors = icon_rows(32, self.ORANGE, self.AMBER, self.RED, five_hour=0.5, weekly=1.0, weekly_level=2)
        self.assertEqual(ring_pixel(errors, shape.outer, 90), rgba(self.RED))
        self.assertEqual(ring_pixel(errors, shape.inner, 90), rgba(FIVE_HOUR))

    def test_without_a_fresh_status_the_tile_is_greyed_and_nothing_is_filled(self):
        rows = icon_rows(16, "#2a78d6", self.AMBER, self.RED, five_hour=0.9, weekly=0.9, greyed=True)
        colours_used = {pixel[:3] for row in rows for pixel in row if pixel[3]}
        for colour in ("#2a78d6", WEEKLY, FIVE_HOUR, self.AMBER, self.RED):
            self.assertNotIn(rgba(colour)[:3], colours_used, colour)
        self.assertEqual(rows[0][8], rgba(GREY_RIM), "the greyed tile has a grey rim, not the account's")

    def test_the_png_holds_the_pixels_and_nothing_else(self):
        rows = icon_rows(20, "#2a78d6", self.AMBER, self.RED, five_hour=0.3, weekly=0.6)
        data = png(rows)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        kinds, at = [], 8
        while at < len(data):
            length = struct.unpack(">I", data[at:at + 4])[0]
            kinds.append(data[at + 4:at + 8])
            at += 12 + length
        self.assertEqual(kinds, [b"IHDR", b"IDAT", b"IEND"])
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), (20, 20))
        start = data.index(b"IDAT") + 4
        length = struct.unpack(">I", data[start - 8:start - 4])[0]
        raw = zlib.decompress(data[start:start + length])
        self.assertEqual(len(raw), 20 * (1 + 20 * 4))
        self.assertEqual(tuple(raw[1 + 4 * 0:1 + 4 * 1]), rows[0][0])
        middle = 10 * (1 + 20 * 4) + 1 + 4 * 10
        self.assertEqual(tuple(raw[middle:middle + 4]), rows[10][10])


class ThemeChoiceTest(unittest.TestCase):
    def test_light_and_dark_are_kept_without_asking_windows(self):
        def not_asked():
            raise AssertionError("Windows' mode was read")

        self.assertEqual(chosen_mode("light", not_asked), "light")
        self.assertEqual(chosen_mode("dark", not_asked), "dark")

    def test_following_windows_takes_its_mode_and_an_unknown_choice_follows_too(self):
        self.assertEqual(chosen_mode("system", lambda: 0), "dark")
        self.assertEqual(chosen_mode("system", lambda: 1), "light")
        self.assertEqual(chosen_mode("sepia", lambda: 0), "dark")

    def test_every_choice_has_its_words(self):
        self.assertEqual(set(THEME_LABELS), set(THEME_CHOICES))
        self.assertEqual(THEME_CHOICES[0], "system", "following Windows is the default")

    def test_the_window_s_record_keeps_the_choice_and_an_absent_or_unknown_one_follows_windows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "window.json"
            state = replace(WindowState(), theme="dark", keep_on_top=True)
            save_state(path, state)
            self.assertEqual(load_state(path), (state, None))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["theme"], "dark")
            for written in ({"v": 1}, {"v": 1, "theme": "sepia"}, {"v": 1, "theme": 1}):
                path.write_text(json.dumps(written), encoding="utf-8")
                self.assertEqual(load_state(path)[0].theme, "system", written)


class FlowTest(unittest.TestCase):
    """A card line's pieces at a width, measured here as ten pixels a character."""

    JOINS = ("", " · ", " · ")

    @staticmethod
    def measure(_index, text):
        return 10 * len(text)

    def places(self, texts, width):
        return flow_places(texts, self.JOINS, width, self.measure)

    def test_pieces_that_fit_share_the_first_line_joined(self):
        # 40 + 50 + 40 pixels: exactly the width.
        self.assertEqual(self.places(("aaaa", "bb", "c"), 130),
                         (("aaaa", 0, False), (" · bb", 0, False), (" · c", 0, False)))

    def test_from_the_first_piece_that_does_not_fit_each_piece_has_a_line_of_its_own_without_its_join(self):
        # "aaaa" + " · bb" = 90 fits 90; " · c" would make 130.
        self.assertEqual(self.places(("aaaa", "bb", "c"), 90),
                         (("aaaa", 0, False), (" · bb", 0, False), ("c", 1, True)))
        self.assertEqual(self.places(("aaaa", "bbbbbb", "c"), 90),
                         (("aaaa", 0, False), ("bbbbbb", 1, True), ("c", 2, True)), "c follows onto a line of its own")

    def test_an_empty_piece_takes_no_place_and_no_join(self):
        self.assertEqual(self.places(("", "bb", ""), 100), (None, ("bb", 0, False), None))
        self.assertEqual(self.places(("aa", "", "c"), 100), (("aa", 0, False), None, (" · c", 0, False)))

    def test_before_the_line_has_a_width_every_piece_is_on_the_first_line(self):
        self.assertEqual(self.places(("aaaa", "bbbbbbbbbbbb", "c"), 0),
                         (("aaaa", 0, False), (" · bbbbbbbbbbbb", 0, False), (" · c", 0, False)))


if __name__ == "__main__":
    unittest.main()
