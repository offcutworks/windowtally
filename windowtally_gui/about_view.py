"""The About window, reached from the Help menu, and the window of text it opens for the licence and the third-party
notices.

The logo stands beside the name and the version; the official address is a link that opens in the browser, from the mouse
or, focused, from the keyboard. *Licence* opens the copy's licence and *Third-party notices* the notices a release ships;
a copy without either file offers no button for it (``about_model``). Neither window blocks the clocks: each is shown
modal and goes when it closes.
"""

from __future__ import annotations

import webbrowser
from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QLayout, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from .about_model import (FREE, LICENCE_TITLE, NAME, NOTICES_TITLE, OFFICIAL, OFFICIAL_COPIES, READS, WINDOW_TITLE,
                          AboutContent, about_content)
from .common_view import digits, em, image_of, plain_label, size_to_content
from .logo_model import logo_rows
from .theme_view import Theme

WRAP = 22                 # lines of the default font the window's words run to before they wrap
LOGO = 3                  # the logo's side, in lines of the default font
TEXT_SIZE = (80, 28)      # the most the window of text asks for: digits across, lines down


class Link(QLabel):
    """Words that open an address, from the mouse or, reached by Tab, from Return or Space."""

    def __init__(self, text: str, opened: Callable[[], object], parent: QWidget | None = None):
        super().__init__(text, parent)
        self.opened = opened
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setIndent(0)      # a label with a frame would otherwise stand in from the words above and below it
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        font = self.font()
        font.setUnderline(True)
        self.setFont(font)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.opened()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.opened()
        else:
            super().keyPressEvent(event)


class AboutWindow(QDialog):
    def __init__(self, parent: QWidget | None, theme: Theme, content: AboutContent,
                 open_url: Callable[[str], object] = webbrowser.open):
        """``open_url`` stands in for the browser in a test."""
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        pad = em(0.5)
        grid = QGridLayout(self)
        grid.setContentsMargins(pad * 2, pad * 2, pad * 2, pad * 2)
        grid.setHorizontalSpacing(pad * 2)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(1, 1)
        grid.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        logo = QLabel(self)
        ratio = self.devicePixelRatioF()
        picture = QPixmap.fromImage(image_of(logo_rows(round(em(LOGO) * ratio))))
        picture.setDevicePixelRatio(ratio)
        logo.setPixmap(picture)
        self.logo = logo
        grid.addWidget(logo, 0, 0, 2, 1, Qt.AlignmentFlag.AlignLeft)
        name = plain_label(self)
        name.setText(NAME)
        name.setFont(theme.fonts["title"])
        theme.ink(name, "ink")
        grid.addWidget(name, 0, 1, Qt.AlignmentFlag.AlignBottom)
        version = plain_label(self)
        version.setText(content.version)
        theme.ink(version, "ink-2")
        grid.addWidget(version, 1, 1, Qt.AlignmentFlag.AlignTop)

        self.words: list[QLabel] = []
        for row, (text, top) in enumerate(((content.copyright, pad * 2), (FREE, pad), (OFFICIAL, pad)), start=2):
            self._line(grid, row, text, top)
        self.link = Link(OFFICIAL_COPIES, lambda: open_url(OFFICIAL_COPIES), self)
        theme.ink(self.link, "ink")
        theme.mark(self.link, "link", "true")
        grid.addWidget(self.link, 5, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        self._line(grid, 6, READS, pad * 2)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, pad * 2, 0, 0)
        buttons.setSpacing(pad)
        buttons.addStretch(1)
        self.shipped: dict[str, QPushButton] = {}
        for label, title, words in (("Licence", LICENCE_TITLE, content.licence),
                                    ("Third-party notices", NOTICES_TITLE, content.notices)):
            if words is not None:
                button = QPushButton(label, self)
                button.clicked.connect(lambda _checked=False, t=title, w=words: open_text(self, t, w))
                buttons.addWidget(button)
                self.shipped[label] = button
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        grid.addLayout(buttons, 7, 0, 1, 2)
        self.close_button.setFocus()

    def _line(self, grid: QGridLayout, row: int, text: str, top: int) -> None:
        label = plain_label(self)
        label.setText(text)
        label.setWordWrap(True)
        label.setFixedWidth(em(WRAP))
        label.setContentsMargins(0, top, 0, 0)
        self.theme.ink(label, "ink")
        grid.addWidget(label, row, 0, 1, 2)
        self.words.append(label)


class TextView(QPlainTextEdit):
    """Words to read, wrapped and scrolled, asking for room for their longest line and their lines, up to ``TEXT_SIZE``."""

    def __init__(self, words: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setPlainText(words)
        self.setReadOnly(True)
        lines = words.splitlines() or [""]
        self.asked = QSize(digits(min(TEXT_SIZE[0], max(len(line) for line in lines) + 2)),
                           em(min(TEXT_SIZE[1], len(lines) + 1)))

    def sizeHint(self) -> QSize:
        margin = 2 * (self.frameWidth() + round(self.document().documentMargin()))
        return QSize(self.asked.width() + margin + self.verticalScrollBar().sizeHint().width(),
                     self.asked.height() + margin)


class TextWindow(QDialog):
    """A window showing ``words``, read-only and scrolled, modal over ``parent``."""

    def __init__(self, parent: QWidget | None, title: str, words: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        pad = em(0.5)
        body = QVBoxLayout(self)
        body.setContentsMargins(pad * 2, pad * 2, pad * 2, pad * 2)
        body.setSpacing(pad)
        self.view = TextView(words, self)
        body.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.reject)
        row.addWidget(self.close_button)
        body.addLayout(row)
        self.close_button.setFocus()


def _shown(window: QDialog, parent: QWidget | None) -> None:
    size_to_content(window, parent)
    window.setModal(True)
    window.show()
    window.raise_()
    window.activateWindow()


def open_text(parent: QWidget | None, title: str, words: str) -> TextWindow:
    window = TextWindow(parent, title, words)
    _shown(window, parent)
    return window


def open_about(parent: QWidget | None, theme: Theme) -> AboutWindow:
    window = AboutWindow(parent, theme, about_content())
    _shown(window, parent)
    return window
