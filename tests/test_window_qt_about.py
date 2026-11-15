"""The About window and its window of text, headless: its words from ``about_model``, the logo's own pixels, the link,
which of the shipped texts it offers, and how the shell reaches it. The browser is a stand-in, so no test opens a page."""

import unittest
from unittest import mock

from qt_support import APP

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel

from test_window_qt_shell import ShellCase, spin
from windowtally_gui import about_model, app_view
from windowtally_gui.about_model import (FREE, LICENCE_TITLE, NAME, NOTICES_TITLE, OFFICIAL, OFFICIAL_COPIES, READS,
                                         WINDOW_TITLE, AboutContent)
from windowtally_gui.logo_model import logo_rows
from windowtally_gui.about_view import AboutWindow, Link, TextView, TextWindow, open_about, open_text
from windowtally_gui.common_view import digits, em
from windowtally_gui.theme_view import Theme, style_sheet
from windowtally_gui.theme_model import colours

CONTENT = AboutContent("Version 1.0.0, from source", "MIT License\n\nCopyright (c) 2026 The Invented\n", "Notices\n")


def press(widget, key=Qt.Key.Key_Return) -> None:
    APP.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def click(widget, button=Qt.MouseButton.LeftButton) -> None:
    at = QPointF(2, 2)
    APP.sendEvent(widget, QMouseEvent(QEvent.Type.MouseButtonPress, at, widget.mapToGlobal(at), button, button,
                                      Qt.KeyboardModifier.NoModifier))


class WindowCase(unittest.TestCase):
    def setUp(self):
        self.theme = Theme(APP, "light")
        self.opened: list[str] = []

    def open(self, content: AboutContent = CONTENT) -> AboutWindow:
        window = AboutWindow(None, self.theme, content, open_url=self.opened.append)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.hide)
        return window

    def words(self, window: AboutWindow) -> list[str]:
        return [label.text() for label in window.words]


class WordsTest(WindowCase):
    def test_it_says_what_about_model_says_in_its_order(self):
        window = self.open()
        self.assertEqual(window.windowTitle(), WINDOW_TITLE)
        self.assertEqual(self.words(window), ["Copyright (c) 2026 The Invented", FREE, OFFICIAL, READS])
        self.assertEqual(window.link.text(), OFFICIAL_COPIES)
        labels = [label.text() for label in window.findChildren(QLabel)]
        self.assertIn(NAME, labels)
        self.assertIn(CONTENT.version, labels)

    def test_a_copy_with_no_licence_says_so_and_offers_none(self):
        window = self.open(AboutContent("Version 1.0.0, from source", None))
        self.assertEqual(self.words(window)[0], about_model.MISSING_LICENCE)
        self.assertEqual(list(window.shipped), [])

    def test_it_offers_the_notices_only_where_the_copy_ships_them(self):
        self.assertEqual(list(self.open().shipped), ["Licence", "Third-party notices"])
        self.assertEqual(list(self.open(AboutContent("v", "licence\n")).shipped), ["Licence"])

    def test_the_name_wears_the_title_s_font(self):
        window = self.open()
        name = next(label for label in window.findChildren(QLabel) if label.text() == NAME)
        self.assertEqual(name.font().pointSizeF(), self.theme.fonts["title"].pointSizeF())

    def test_the_logo_is_the_drawing_s_own_pixels_at_three_lines(self):
        window = self.open()
        image = window.logo.pixmap().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        rows = logo_rows(em(3))
        self.assertEqual((image.width(), image.height()), (len(rows[0]), len(rows)))
        for y in (0, len(rows) // 4, len(rows) // 2, len(rows) - 1):
            for x in (0, len(rows[0]) // 3, len(rows[0]) - 1):
                colour = image.pixelColor(x, y)
                self.assertEqual((colour.red(), colour.green(), colour.blue(), colour.alpha()), tuple(rows[y][x]))

    def test_the_name_stands_beside_the_logo(self):
        window = self.open()
        window.show()
        spin()
        name = next(label for label in window.findChildren(QLabel) if label.text() == NAME)
        self.assertLess(name.x() - window.logo.geometry().right(), em(2))

    def test_the_window_keeps_to_its_content_and_close_has_the_focus(self):
        window = self.open()
        self.assertIs(window.focusWidget(), window.close_button)
        window.show()
        spin()
        self.assertEqual(window.minimumSize(), window.maximumSize())


class LinkTest(WindowCase):
    def test_the_mouse_opens_the_address_and_only_its_left_button(self):
        window = self.open()
        click(window.link, Qt.MouseButton.RightButton)
        self.assertEqual(self.opened, [])
        click(window.link)
        self.assertEqual(self.opened, [OFFICIAL_COPIES])

    def test_return_and_space_open_it_from_the_keyboard_and_other_keys_do_not(self):
        window = self.open()
        press(window.link, Qt.Key.Key_A)
        self.assertEqual(self.opened, [])
        window.show()
        press(window.link, Qt.Key.Key_Return)
        press(window.link, Qt.Key.Key_Space)
        self.assertEqual(self.opened, [OFFICIAL_COPIES, OFFICIAL_COPIES])
        self.assertTrue(window.isVisible())

    def test_tab_reaches_it_and_it_reads_as_a_link(self):
        window = self.open()
        self.assertEqual(window.link.focusPolicy(), Qt.FocusPolicy.TabFocus)
        self.assertEqual(window.link.cursor().shape(), Qt.CursorShape.PointingHandCursor)
        self.assertTrue(window.link.font().underline())
        self.assertEqual(window.link.textFormat(), Qt.TextFormat.PlainText)

    def test_its_focus_ring_comes_from_a_role_in_both_modes(self):
        for mode in ("light", "dark"):
            c = colours(mode)
            self.assertIn(f'QLabel[link="true"]:focus {{ border-color: {c["focus"]}; }}', style_sheet(c))


class ClosingTest(WindowCase):
    def test_close_and_escape_end_the_window(self):
        for leave in (lambda w: w.close_button.click(), lambda w: press(w, Qt.Key.Key_Escape)):
            window = AboutWindow(None, self.theme, CONTENT, open_url=self.opened.append)
            window.show()
            leave(window)
            self.assertFalse(window.isVisible())

    def test_a_window_closed_goes(self):
        window = AboutWindow(None, self.theme, CONTENT)
        window.show()
        heard = []
        window.destroyed.connect(lambda: heard.append(1))
        window.close_button.click()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        spin()
        self.assertEqual(heard, [1])


class TextTest(WindowCase):
    def open_text(self, words: str, parent=None) -> TextWindow:
        window = TextWindow(parent, "A title", words)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.hide)
        return window

    def test_the_licence_opens_over_the_window_modal_with_its_words(self):
        window = self.open()
        window.show()
        window.shipped["Licence"].click()
        shown = [w for w in window.findChildren(TextWindow)]
        self.assertEqual(len(shown), 1)
        self.addCleanup(shown[0].hide)
        self.assertEqual(shown[0].windowTitle(), LICENCE_TITLE)
        self.assertEqual(shown[0].view.toPlainText(), CONTENT.licence)
        self.assertTrue(shown[0].isModal())
        self.assertIs(QApplication.activeModalWidget(), shown[0])

    def test_the_notices_open_under_their_own_title(self):
        window = self.open()
        window.show()
        window.shipped["Third-party notices"].click()
        shown = window.findChildren(TextWindow)
        self.addCleanup(shown[0].hide)
        self.assertEqual((shown[0].windowTitle(), shown[0].view.toPlainText()), (NOTICES_TITLE, CONTENT.notices))

    def test_closing_the_words_gives_the_about_window_back(self):
        window = self.open()
        window.setModal(True)
        window.show()
        text = open_text(window, "A title", "words")
        self.assertIs(QApplication.activeModalWidget(), text)
        text.close_button.click()
        self.assertIs(QApplication.activeModalWidget(), window)

    def test_the_words_are_read_only_and_wrap(self):
        view = self.open_text("words").view
        self.assertTrue(view.isReadOnly())
        self.assertEqual(view.lineWrapMode(), TextView.LineWrapMode.WidgetWidth)

    def test_it_asks_for_room_for_its_words_up_to_eighty_by_twenty_eight(self):
        small = TextView("one\ntwo\n")
        self.addCleanup(small.deleteLater)
        self.assertEqual(small.asked.width(), digits(5))
        self.assertEqual(small.asked.height(), em(3))
        self.assertGreater(small.sizeHint().width(), small.asked.width())
        self.assertGreater(small.sizeHint().height(), small.asked.height())
        large = TextView("\n".join(["x" * 200] * 300))
        self.addCleanup(large.deleteLater)
        self.assertEqual(large.asked.width(), digits(80))
        self.assertEqual(large.asked.height(), em(28))
        empty = TextView("")
        self.addCleanup(empty.deleteLater)
        self.assertEqual(empty.asked.width(), digits(2))

    def test_close_and_escape_end_it_and_close_has_the_focus(self):
        window = self.open_text("words")
        self.assertIs(window.focusWidget(), window.close_button)
        window.show()
        press(window, Qt.Key.Key_Escape)
        self.assertFalse(window.isVisible())
        window = self.open_text("words")
        window.show()
        window.close_button.click()
        self.assertFalse(window.isVisible())

    def test_it_can_be_made_larger_where_the_about_window_cannot(self):
        window = self.open_text("words")
        window.show()
        spin()
        window.resize(window.width() + 50, window.height() + 50)
        spin()
        self.assertGreater(window.view.width(), window.view.sizeHint().width())


class ShellTest(ShellCase):
    def test_the_help_menu_s_entry_opens_it_modal_over_the_main_window(self):
        self.status()
        shell = self.open()
        with mock.patch.object(about_model, "read_release", return_value=None):
            shell.main.actions["about"]()
        (window,) = shell.main.findChildren(AboutWindow)
        self.addCleanup(window.hide)
        self.assertTrue(window.isModal())
        self.assertTrue(window.isVisible())
        self.assertEqual(self.words(window)[1], FREE)

    def test_it_reads_the_copy_it_runs_from(self):
        self.status()
        shell = self.open()
        window = open_about(shell.main, shell.theme)
        self.addCleanup(window.hide)
        self.assertEqual(self.words(window)[0], about_model.about_content().copyright)
        self.assertEqual("Licence" in window.shipped, about_model.about_content().licence is not None)

    def test_the_shell_imports_the_opener_it_uses(self):
        self.assertIs(app_view.open_about, open_about)

    def words(self, window: AboutWindow) -> list[str]:
        return [label.text() for label in window.words]

