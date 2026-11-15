"""An account's card in the main window, and the line under the cards of an account whose plan has ended.

The card shows what ``live_model.Card`` says and nothing more, tightly, so that cards stand narrow and several abreast:
on a raised surface with rounded corners and a hairline edge, its colour (the page's colour for the account), its name, a
renewal tag and, at the row's right end, the buttons that switch the desktop app or the CLI to it; the roles it holds
as small chips of one neutral tint, the e-mail where the name is the user's own, the last response and, where both
windows rest on one reading and it is old enough to matter, its age. Then the gauges: the account's two windows as
concentric rings (``Rings``, ``windowtally.rings``: the weekly window outside, the 5-hour window inside, as the logo and
the tray icon draw them), centred beside the two windows' names and figures — a dot in each ring's colour, the name, the
figure, the figures starting at one place on every card, the weekly window first on an account with no 5-hour limit,
whose 5-hour window is its name and ``no limit`` alone; under them the account's per-model window where it has one
(Fable's), its name, its figure and a thin bar (``ScopedBar``) in place of a ring. Then each window's line across the
card's whole width, behind the key of its gauge — when it resets, the pace and the reading's age where it is said and
the windows' readings differ, the weekly window's ending with the week's use by product where claude.ai reported more
than one, then the per-model window's words; and, under a hairline, its plan on one line. Every word stays on the card:
a line too long for the card's width moves its later pieces whole onto a line of their own (``Flow``) rather than hiding
any. A figure at a warning level is written in the level's text colour beside a ring or a bar in the level's fill: the
words carry the state and the colour only reinforces it. The card is updated in place every second, so its widgets are
made once and only their words and colours change; a ring repaints only when its figures change.

What moves is the rings' alone (``motion_model``, through ``Theme.motion``): a ring whose figure changes sweeps to its new
value once, and a window at a warning or an error level pulses slowly; nothing moves while Windows' animation effects are
off. Glow is on data alone and in the dark mode alone: the rings' arcs carry a soft halo of their own colour, painted as a
few translucent strokes, never a graphics effect, which would render the card offscreen at every second's update. The
card of an account a client uses is marked by a strip of the account's colour inside its left edge; a card's edge stays
the hairline in every state, under the pointer included, since a card answers no click.

``Meter`` is the horizontal form of a fill — its track and its fill in the level's colour — that the History window's
tiles draw an account's share with, in the account's colour.

An account whose plan has ended and that no client uses has no card but a line (``EndedLine``), on the page itself
rather than a raised surface: its colour as a ring, its name and words in the page's quieter inks, and its switch
buttons at the line's end, as a card's.
"""

from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from windowtally.rings import Ring, fill, level_colour, rings

from .card_model import RING_INNER, bar_dashes, bar_fill, bar_known, flow_places
from .common_view import Hint, card_margins, em, plain_label
from .live_model import FIVE_HOUR_NAME, WEEKLY_NAME, Card, EndedRow, PlanRow, WindowRow
from .logo_model import FIVE_HOUR, WEEKLY
from .motion_model import moving, pulse_opacity, sweep_value
from .switch_model import APP, CLI, SwitchButton
from .theme_model import LEVEL_FILLS, LEVEL_TEXTS
from .theme_view import Theme

PLAN_TONES = {"normal": "ink", "warning": "warning-text", "muted": "ink-2"}
RING_SIZE = 3.2          # a card's rings, square, in lines of the default font: the two windows' names and figures
BAR_LINES = 0.3          # a per-model window's bar, tall, in lines of the default font
STRIP_LINES = 0.2        # the in-use card's strip of the account's colour, wide, in lines of the default font
# The halo the dark mode lays under a ring's arc: each stroke wider than the band by this share of the square's side, at
# this opacity; the widest stays inside the margin ``windowtally.rings`` keeps around the outer band, however thick the band.
HALO = ((0.065, 0.10), (0.033, 0.18))
CARD_RADIUS = 8          # the card's corner, as the style sheet rounds it

# What a switch button does, said beside it while the pointer rests on it: both end the client's own session, so the
# words say how much.
HINTS = {APP: "Close the desktop app and start it again signed in to {label}",
         CLI: "Sign the CLI in to {label}; no CLI may be running"}

# The widest figure or state a window shows, each in its font: every card's figure column holds them, so the figures
# end at one place on every card whatever they say.
FIGURES = (("≈100%", "figure"), ("not started", "bold"), ("running", "bold"), ("unknown", "bold"), ("no limit", "bold"))

# The chip a role wears, by the role's words in ``live_model.card``: one neutral tint for every role, holding the ink at
# 4.5:1 or more (the suite measures it).
CHIPS = {"desktop app": "chip", "CLI": "chip", "use next": "chip"}


class Meter(QWidget):
    """A horizontal meter: its rounded track, and its fill as far as the window is used, in the level's colour — or in
    ``role``'s where one is given, as an account's share is drawn in the account's colour. ``lines`` is its height in
    lines of the default font."""

    def __init__(self, theme: Theme, parent: QWidget | None = None, lines: float = 0.4):
        super().__init__(parent)
        self.theme = theme
        self.setFixedHeight(self.tall(lines))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.fraction, self.level, self.role = 0.0, 0, None

    @staticmethod
    def tall(lines: float) -> int:
        """How tall a meter of ``lines`` stands, in pixels: never less than 15 pixels a line, so a small default font
        leaves the default meter its 6 and a share's bar its 4."""
        return max(math.ceil(15 * lines), em(lines))

    def set(self, fraction: float, level: int = 0, role: str | None = None) -> None:
        if (fraction, level, role) != (self.fraction, self.level, self.role):
            self.fraction, self.level, self.role = fraction, level, role
            self.update()

    def paintEvent(self, _event) -> None:
        c = self.theme.c
        width, height = self.width(), self.height()
        radius = height / 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c["grid"]))
        painter.drawRoundedRect(QRectF(0, 0, width, height), radius, radius)
        if self.fraction > 0:
            painter.setBrush(QColor(c[self.role or LEVEL_FILLS[self.level]]))
            painter.drawRoundedRect(QRectF(0, 0, max(height, round(width * self.fraction)), height), radius, radius)


class Swatch(QWidget):
    """The account's colour, as a dot, or a ring where ``ring``, smoothed by the painter on whatever stands behind it."""

    def __init__(self, theme: Theme, ring: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.theme, self.ring = theme, ring
        self.setFixedSize(max(8, em(0.6)), max(8, em(0.6)))
        self.role = "muted"

    def set(self, role: str) -> None:
        if role != self.role:
            self.role = role
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.theme.c[self.role]))
        whole = QRectF(self.rect())
        if not self.ring:
            painter.drawEllipse(whole)
            return
        inner = whole.width() * (1 - RING_INNER) / 2
        path = QPainterPath()
        path.addEllipse(whole)
        path.addEllipse(whole.adjusted(inner, inner, -inner, -inner))
        painter.drawPath(path)


class Dot(QWidget):
    """The key from a window's name or line to its gauge: a small dot in the colour the ring's arc is drawn in, or,
    ``pill``, a short bar in the colour a per-model window's bar is filled in."""

    def __init__(self, theme: Theme, parent: QWidget | None = None, pill: bool = False):
        super().__init__(parent)
        self.theme = theme
        side = max(5, round(em(0.33)))
        self.setFixedSize(side * 2 if pill else side, side)
        self.pill = pill
        self.key: tuple[str, int] | None = None     # the gauge's colour at rest and its window's level

    def set(self, key: tuple[str, int] | None) -> None:
        """Shows the dot of the ring whose colour at rest and level ``key`` gives; none where the window has no ring."""
        if key != self.key:
            self.key = key
            self.update()
        self.setVisible(key is not None)

    def paintEvent(self, _event) -> None:
        if self.key is None:
            return
        c = self.theme.c
        rest, level = self.key
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(level_colour(rest, level, c["warning"], c["critical"])))
        if self.pill:
            radius = self.height() / 2
            painter.drawRoundedRect(QRectF(self.rect()), radius, radius)
        else:
            painter.drawEllipse(QRectF(self.rect()))


class Rings(QWidget):
    """A card's two windows as concentric rings (``windowtally.rings``). An arc whose figure changes sweeps to it once, and an
    arc at a warning or an error level pulses (``motion_model``), both drawn from the theme's one clock; the first
    figures shown, and every figure while Windows' animation effects are off, stand where they are at once. It paints its
    own square in the card's colour, so a frame of a pulse repaints the rings alone, never the card beneath them."""

    def __init__(self, theme: Theme, parent: QWidget | None = None):
        super().__init__(parent)
        self.theme = theme
        side = em(RING_SIZE)
        self.setFixedSize(side, side)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.windows: tuple[tuple[float, int], tuple[float, int] | None] | None = None
        self.start: tuple[float, ...] = ()       # each arc's fraction when its sweep began
        self.swept_at: float | None = None       # when the sweep under way began
        self.pulsed_at = 0.0                     # when the windows' pulse began

    def set(self, weekly: tuple[float, int], five_hour: tuple[float, int] | None) -> None:
        """The weekly window's fraction used and level, and the 5-hour window's, None for an account with no 5-hour
        limit; the rings repaint only where these change."""
        windows = (weekly, five_hour)
        if windows == self.windows:
            return
        motion = self.theme.motion
        now = motion.now()
        before = self.windows
        if before is not None and (before[1] is None) == (five_hour is None) and motion.allowed():
            self.start = self._shown(now)[0]
            self.swept_at = now
        else:
            self.swept_at = None
        if self._level(windows) >= 1 and (before is None or self._level(before) < 1):
            self.pulsed_at = now
        self.windows = windows
        self.update()
        self._ask(self._shown(now)[1])

    @staticmethod
    def _level(windows) -> int:
        return max(window[1] for window in windows if window is not None)

    def _targets(self) -> tuple[float, ...]:
        return tuple(window[0] for window in self.windows if window is not None)

    def _shown(self, now: float) -> tuple[tuple[float, ...], bool]:
        """Each arc's fraction at ``now``, and whether a sweep is still under way."""
        targets = self._targets()
        if self.swept_at is None or len(self.start) != len(targets):
            return targets, False
        animate = self.theme.motion.allowed()
        shown, sweeping = [], False
        for start, end in zip(self.start, targets):
            value, going = sweep_value(start, end, now - self.swept_at, animate)
            shown.append(value)
            sweeping = sweeping or going
        if not sweeping:
            self.swept_at = None
        return tuple(shown), sweeping

    def _ask(self, sweeping: bool) -> None:
        motion = self.theme.motion
        if self.windows is not None and moving(sweeping, self._level(self.windows), motion.allowed()):
            motion.want(self, fast=sweeping)
        else:
            motion.done(self)

    def marks(self, now: float, shown: tuple[float, ...] | None = None) -> tuple[Ring, ...]:
        """The rings as they stand at ``now``; ``shown``, each arc's fraction then, where already worked out."""
        shown = self._shown(now)[0] if shown is None else shown
        weekly, five_hour = self.windows
        return rings(self.width(), (shown[0], weekly[1]),
                     None if five_hour is None else (shown[1], five_hour[1]))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.windows is not None:
            self._ask(self._shown(self.theme.motion.now())[1])

    def paintEvent(self, _event) -> None:
        c, motion = self.theme.c, self.theme.motion
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(c["surface-1"]))
        if self.windows is None:
            return
        now, animate = motion.now(), motion.allowed()
        shown, sweeping = self._shown(now)
        marks = self.marks(now, shown)
        centre = self.width() / 2
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        def stroke(colour: QColor, width: float) -> None:
            pen = QPen(colour, width)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)

        for ring in marks:
            stroke(QColor(c["ring-track"]), ring.width)
            painter.drawEllipse(QRectF(centre - ring.radius, centre - ring.radius, 2 * ring.radius, 2 * ring.radius))
        for ring in marks:
            if ring.fraction <= 0:
                continue
            box = QRectF(centre - ring.radius, centre - ring.radius, 2 * ring.radius, 2 * ring.radius)
            span = -max(1, round(ring.fraction * 360 * 16))     # clockwise from the top, in sixteenths of a degree
            opacity = pulse_opacity(ring.level, now - self.pulsed_at, animate)
            colour = QColor(fill(ring, c["warning"], c["critical"]))
            if self.theme.mode == "dark":
                for grow, alpha in HALO:
                    halo = QColor(colour)
                    halo.setAlphaF(alpha * opacity)
                    stroke(halo, ring.width + grow * self.width())
                    painter.drawArc(box, 90 * 16, span)
            colour.setAlphaF(opacity)
            stroke(colour, ring.width)
            painter.drawArc(box, 90 * 16, span)
        painter.end()
        self._ask(sweeping)


class ScopedBar(QWidget):
    """A per-model window's gauge: a thin rounded track in the rings' track colour, filled from the left as far as the
    window is used in the weekly ring's colour at rest, the warning or the critical fill at those levels — the window
    lies inside the week; an unknown window's track drawn as dashes, so it never reads as nothing used
    (``card_model.bar_fill``, ``bar_dashes``). It never moves: it repaints only when its figure changes."""

    def __init__(self, theme: Theme, parent: QWidget | None = None):
        super().__init__(parent)
        self.theme = theme
        self.setFixedHeight(max(3, em(BAR_LINES)))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.shown: tuple[float, int, bool] = (0.0, 0, True)    # its fraction used, its level, whether it is known

    def set(self, fraction: float, level: int, known: bool) -> None:
        if (fraction, level, known) != self.shown:
            self.shown = (fraction, level, known)
            self.update()

    def paintEvent(self, _event) -> None:
        c = self.theme.c
        fraction, level, known = self.shown
        width, height = self.width(), self.height()
        radius = height / 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c["ring-track"]))
        if not known:
            for start, length in bar_dashes(width, height):
                painter.drawRoundedRect(QRectF(start, 0, length, height), radius, radius)
            return
        painter.drawRoundedRect(QRectF(0, 0, width, height), radius, radius)
        filled = bar_fill(width, height, fraction, known)
        if filled:
            painter.setBrush(QColor(level_colour(WEEKLY, level, c["warning"], c["critical"])))
            painter.drawRoundedRect(QRectF(0, 0, filled, height), radius, radius)


class Chips(QWidget):
    """The roles an account holds, each a small chip of the one neutral tint; a chip is made once and shown while the
    role is held."""

    def __init__(self, theme: Theme, parent: QWidget | None = None):
        super().__init__(parent)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(em(0.25))
        self.chips: dict[str, QLabel] = {}
        for words, tint in CHIPS.items():
            chip = QLabel(words, self)
            theme.mark(chip, "chip", tint)
            chip.hide()
            self.row.addWidget(chip)
            self.chips[words] = chip

    def set(self, tags: tuple[str, ...]) -> None:
        for words, chip in self.chips.items():
            chip.setVisible(words in tags)

    def needs(self) -> int:
        """The width the chips shown take, whether or not they are laid out yet."""
        shown = [chip for chip in self.chips.values() if not chip.isHidden()]
        return sum(chip.sizeHint().width() for chip in shown) + self.row.spacing() * max(0, len(shown) - 1)


class SwitchButtons:
    """The buttons that switch the desktop app or the CLI to an account, at the end of the row they are put in: each
    client's made once and shown or hidden, redrawn only when what they offer changes."""

    def __init__(self, row: QHBoxLayout, parent: QWidget, theme: Theme, on_switch: Callable[[str, str], None],
                 uuid: Callable[[], str]):
        self.row, self.theme = row, theme
        self.buttons = {client: QPushButton("Switch here", parent) for client in (APP, CLI)}
        self.hints = {client: Hint(button) for client, button in self.buttons.items()}
        for client, button in self.buttons.items():
            button.clicked.connect(lambda _checked=False, c=client: on_switch(c, uuid()))
            button.hide()
        self._offered: tuple[SwitchButton, ...] | None = None

    def height(self) -> int:
        return max(button.sizeHint().height() for button in self.buttons.values())

    def show(self, switches: tuple[SwitchButton, ...], label: str) -> None:
        """Shows the buttons ``switches`` offers, the first at the left."""
        if switches == self._offered:
            return
        self._offered = switches
        for button in self.buttons.values():
            self.row.removeWidget(button)
            button.hide()
        for offer in switches:
            button = self.buttons[offer.client]
            button.setText(offer.text)
            self.theme.mark(button, "primary", offer.accent)
            self.hints[offer.client].text = HINTS[offer.client].format(label=label)
            self.row.addWidget(button)
            button.show()


class Flow(QWidget):
    """Pieces of text written one after another, each in its own ink, placed by ``card_model.flow_places``: on one line
    while they fit the width, and from the first that does not, each piece whole on a line of its own, so no word is ever
    hidden. ``joins[i]`` stands between piece ``i - 1`` and piece ``i`` on one line. ``first``, where given, is a widget
    standing as the first piece, in place of its text. Its width is whatever its place gives it, never what the pieces
    ask, or a line of one piece could not narrow to be cut into two."""

    def __init__(self, theme: Theme, inks: tuple[str, ...], joins: tuple[str, ...], first: "Chips | None" = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.theme = theme
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(0)
        self.first = first
        self.labels: list[QLabel] = []
        for role in inks:
            label = plain_label(self)
            theme.ink(label, role)
            self.labels.append(label)
        if first is not None:
            first.setParent(self)
        self.joins = joins
        self.texts = ("",) * len(inks)
        self._placed: tuple | None = None
        # A last, empty column takes what a piece on a line of its own needs beyond the first line's pieces.
        self.grid.setColumnStretch(len(inks), 1)

    def colour(self, index: int, role: str) -> None:
        self.theme.ink(self.labels[index], role)

    def set(self, *texts: str) -> None:
        self.texts = texts
        self._layout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout()

    def _measure(self, index: int, text: str) -> int:
        if index == 0 and self.first is not None:
            return self.first.needs()
        return QFontMetrics(self.labels[index].font()).horizontalAdvance(text)

    def widest(self) -> int:
        """The width of the widest piece shown: what the line needs for no piece to wrap within itself."""
        return max((self._measure(index, text) for index, text in enumerate(self.texts) if text), default=0)

    def _layout(self) -> None:
        # The card is updated every second, mostly with the words it already shows: nothing is measured then.
        key = (tuple(self.texts), self.width(), self.first.needs() if self.first is not None else 0)
        if key == self._placed:
            return
        self._placed = key
        places = flow_places(tuple(self.texts), self.joins, self.width(), self._measure)
        for index, (label, spot) in enumerate(zip(self.labels, places)):
            piece = self.first if index == 0 and self.first is not None else label
            self.grid.removeWidget(piece)
            if piece is not label:
                label.hide()
            if spot is None:
                piece.hide()
                continue
            shown, row, alone = spot
            if piece is label:
                label.setWordWrap(alone)
                label.setText(shown)
            if alone:
                self.grid.addWidget(piece, row, 0, 1, len(self.labels) + 1)
            else:
                self.grid.addWidget(piece, 0, index)
            piece.show()


class KeyedLine(QWidget):
    """A window's words across the card's width, behind the key of its gauge (``Dot``): when it resets, the pace and the
    reading where it is said, and on the weekly window the week's use by product where there is one."""

    def __init__(self, theme: Theme, parent: QWidget, pill: bool = False):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(em(0.35))
        # The key centred on the first row of words, wherever the line's later pieces wrap.
        slot = QWidget(self)
        self.key = Dot(theme, slot, pill=pill)
        slot.setFixedSize(self.key.width(), QFontMetrics(self.font()).height())
        held = QVBoxLayout(slot)
        held.setContentsMargins(0, 0, 0, 0)
        held.addWidget(self.key, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(slot, 0, Qt.AlignmentFlag.AlignTop)
        self.flow = Flow(theme, ("ink", "ink-2", "ink-2"), ("", " · ", " · "), parent=self)
        row.addWidget(self.flow, 1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set(self, key: tuple[str, int] | None, *texts: str) -> None:
        """Shows ``texts`` behind ``key``, its gauge's colour at rest and level, or no key, its place kept, where the
        window has no gauge; the whole line goes where the texts are all empty."""
        self.key.set(key)
        self.flow.set(*texts)
        self.setVisible(any(texts))


def show_figure(theme: Theme, label: QLabel, model: WindowRow) -> None:
    """A window's figure on ``label`` in its level's text colour: a figure written large, a state (not started,
    unknown) at the text's own size."""
    font = "figure" if model.figure.endswith("%") else "bold"
    if label.font() != theme.fonts[font]:
        label.setFont(theme.fonts[font])
    label.setText(model.figure)
    theme.ink(label, LEVEL_TEXTS[model.level])


class WindowBlock:
    """A ringed window on a card: beside the rings, the dot of its ring's colour, its name and its figure on one row;
    under the gauges, its line (``KeyedLine``) behind that dot."""

    NAMES = (FIVE_HOUR_NAME, WEEKLY_NAME)

    def __init__(self, parent: QWidget, grid: QGridLayout, theme: Theme, row: int, line: "KeyedLine"):
        self.theme = theme
        pad = em(0.25)
        self.dot = Dot(theme, parent)
        self.name = plain_label(parent)
        theme.ink(self.name, "ink-2")
        self.figure = plain_label(parent)
        self.figure.setFont(theme.fonts["figure"])
        self.keyed = line
        self.line = line.flow
        # The name and the figure on one baseline, the dot centred on their line.
        grid.addWidget(self.dot, row, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self.name, row, 2, Qt.AlignmentFlag.AlignBaseline | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self.figure, row, 3, Qt.AlignmentFlag.AlignBaseline | Qt.AlignmentFlag.AlignLeft)
        self.pad = pad

    def figure_width(self) -> int:
        """What the figure column needs for the widest figure or state."""
        return max(QFontMetrics(self.theme.fonts[font]).horizontalAdvance(text) for text, font in FIGURES) + self.pad * 2

    def name_width(self) -> int:
        """What the name column needs for the wider window name, so the figures start at one place on every card."""
        return max(QFontMetrics(self.name.font()).horizontalAdvance(name) for name in self.NAMES) + self.pad

    def update(self, model: WindowRow, ring: tuple[str, int] | None = None) -> None:
        """Shows ``model``, its dot in the colour of its ring, which ``ring`` gives as the ring's colour at rest and its
        level; none where the window has no ring."""
        self.dot.set(ring)
        self.name.setText(model.name)
        show_figure(self.theme, self.figure, model)
        # A window with nothing to say beyond its figure (no 5-hour limit, not started) takes no line.
        self.keyed.set(ring, model.detail, model.note, model.products)


class ScopedBlock:
    """A card's per-model window (Fable's) under the rings: its name, its figure and its bar (``ScopedBar``) on one
    row across the card, and its line (``KeyedLine``) behind the bar's key, after the ringed windows' lines."""

    def __init__(self, parent: QWidget, theme: Theme, line: KeyedLine):
        self.theme = theme
        self.row = QWidget(parent)
        row = QHBoxLayout(self.row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(em(0.35))
        self.name = plain_label(self.row)
        theme.ink(self.name, "ink-2")
        self.figure = plain_label(self.row)
        self.figure.setFont(theme.fonts["bold"])
        self.bar = ScopedBar(theme, self.row)
        row.addWidget(self.name, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.figure, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.bar, 1, Qt.AlignmentFlag.AlignVCenter)
        self.keyed = line
        self.line = line.flow

    def update(self, model: WindowRow) -> None:
        """Shows ``model``: its figure in its level's text colour, its bar from its fraction and level."""
        known = bar_known(model.figure)
        self.name.setText(model.name)
        show_figure(self.theme, self.figure, model)
        self.bar.set(model.fraction, model.level, known)
        self.keyed.set((WEEKLY, model.level), model.detail, model.note, model.products)

    def set_visible(self, shown: bool) -> None:
        """Shows or hides the row and the line: a card's per-model block where the account has no such window."""
        self.row.setVisible(shown)
        if not shown:
            self.keyed.setVisible(False)


class AccountCard(QFrame):
    def __init__(self, theme: Theme, on_switch: Callable[[str, str], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.theme = theme
        self.uuid = ""
        self.strip: str | None = None     # the account's colour role while a client uses it
        pad = em(0.5)
        self.setProperty("surface", "card")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        grid = QGridLayout(self)
        grid.setContentsMargins(*card_margins())
        grid.setHorizontalSpacing(em(0.35))
        grid.setVerticalSpacing(em(0.15))
        last = 4                          # the columns: the rings, the dots, the names, the figures, the rest
        span = last + 1
        title = QHBoxLayout()
        title.setContentsMargins(0, 0, 0, 0)
        title.setSpacing(pad)
        self.swatch = Swatch(theme, parent=self)
        title.addWidget(self.swatch, 0, Qt.AlignmentFlag.AlignVCenter)
        self.label = plain_label(self)
        self.label.setFont(theme.fonts["title"])
        self.label.setMinimumWidth(1)     # a narrow row clips its words and never a button
        title.addWidget(self.label)
        self.renew = plain_label(self)
        self.renew.setFont(theme.fonts["bold"])
        self.renew.setMinimumWidth(1)
        theme.ink(self.renew, "warning-text")
        title.addWidget(self.renew)
        title.addStretch(1)
        # The switch buttons stand at the title row's right end.
        self.switches = SwitchButtons(title, self, theme, on_switch, lambda: self.uuid)
        grid.addLayout(title, 0, 0, 1, span)
        # The title row is as tall as a button on every card, so cards abreast keep their lines level whether or not one
        # of them offers a button.
        grid.setRowMinimumHeight(0, self.switches.height())
        # The roles the account holds, its e-mail, its last response and its reading's age, together: they wrap whole onto
        # lines of their own where the card is too narrow for one.
        self.chips = Chips(theme)
        self.heading = Flow(theme, ("ink-2", "ink-2"), ("", "  "), first=self.chips, parent=self)
        grid.addWidget(self.heading, 1, 0, 1, span)
        # The gauges: the rings centred beside the two windows' names and figures, whatever lines follow.
        self.rings = Rings(theme, self)
        grid.addWidget(self.rings, 2, 0, 2, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        # The windows' lines across the card under the gauges, each behind its gauge's key: the two ringed windows', then
        # the per-model window's.
        lines = (KeyedLine(theme, self), KeyedLine(theme, self), KeyedLine(theme, self, pill=True))
        # The two windows in the card's order (``Card.windows``): the 5-hour window first, the weekly window first on an
        # account with no 5-hour limit.
        self.windows = (WindowBlock(self, grid, theme, 2, lines[0]), WindowBlock(self, grid, theme, 3, lines[1]))
        # Under them the account's per-model window (``Card.scoped``, Fable's), hidden where it has none: one block, the
        # one such window claude.ai lists.
        self.scoped = ScopedBlock(self, theme, lines[2])
        grid.addWidget(self.scoped.row, 4, 0, 1, span)
        for index, line in enumerate(lines):
            grid.addWidget(line, 5 + index, 0, 1, span)
        below = 5 + len(lines)
        # The plan under a hairline, then the profile's word on it where the profile says otherwise.
        self.rule = QWidget(self)
        ruled = QHBoxLayout(self.rule)
        ruled.setContentsMargins(0, em(0.3), 0, em(0.15))
        line = QFrame(self.rule)
        line.setFixedHeight(1)
        theme.mark(line, "surface", "hairline")
        ruled.addWidget(line)
        grid.addWidget(self.rule, below, 0, 1, span)
        self.plan = Flow(theme, ("ink-2", "ink", "ink-2"), ("", "  ", " · "), parent=self)
        grid.addWidget(self.plan, below + 1, 0, 1, span)
        # Cards abreast are one height; a card needing less keeps its lines at the top, the space under them.
        grid.setRowStretch(below + 2, 1)
        grid.setColumnMinimumWidth(2, self.windows[0].name_width())
        grid.setColumnMinimumWidth(3, self.windows[0].figure_width())
        grid.setColumnStretch(last, 1)

    def update_from(self, card: Card, colour_role: str) -> None:
        self.uuid = card.uuid
        self.swatch.set(colour_role)
        self.label.setText(card.label)
        self.renew.setText(card.renew_tag or "")
        self.chips.set(card.tags)
        self.heading.set("chips" if card.tags else "", card.heading)
        metered = card.five_hour.metered
        self.rings.set((card.weekly.fraction, card.weekly.level),
                       (card.five_hour.fraction, card.five_hour.level) if metered else None)
        keys = {id(card.weekly): (WEEKLY, card.weekly.level),
                id(card.five_hour): (FIVE_HOUR, card.five_hour.level) if metered else None}
        for block, window in zip(self.windows, card.windows):
            block.update(window, keys[id(window)])
        self.scoped.set_visible(bool(card.scoped))
        if card.scoped:
            self.scoped.update(card.scoped[0])
        self._plan(card.plan)
        self.switches.show(card.switches, card.label)
        self._strip(colour_role if card.in_use else None)

    def _plan(self, plan: PlanRow | None) -> None:
        self.rule.setVisible(plan is not None)
        if plan is None:
            self.plan.hide()
            return
        self.plan.show()
        self.plan.colour(1, PLAN_TONES.get(plan.tone, "ink"))
        self.plan.set("Plan", plan.text, plan.note)

    def _strip(self, role: str | None) -> None:
        """The card of an account a client uses: a strip of the account's colour inside its left edge."""
        if role != self.strip:
            self.strip = role
            self.update(self._strip_area())

    def _strip_area(self) -> QRect:
        return QRect(0, 0, max(3, em(STRIP_LINES)) + 2, self.height())

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        # A repaint clear of the strip (a line's words changing each second) leaves it as it was.
        if self.strip is None or not event.rect().intersects(self._strip_area()):
            return
        inside = QRectF(self.rect()).adjusted(1, 1, -1, -1)     # within the hairline edge
        card = QPainterPath()
        card.addRoundedRect(inside, CARD_RADIUS - 1, CARD_RADIUS - 1)
        band = QPainterPath()
        band.addRect(QRectF(inside.left(), inside.top(), max(3, em(STRIP_LINES)), inside.height()))
        # The strip filled as a path, antialiased, so its rounded ends follow the card's corner smoothly: a clip path
        # is not antialiased and would step it.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(card.intersected(band), QColor(self.theme.c[self.strip]))


class EndedLine(QWidget):
    """An account whose plan has ended and that no client uses, on a line under the cards: its colour as a ring, its
    name, when its plan ended and when its week resets, the e-mail where the name is the user's own, and the buttons that
    switch to it at the line's end."""

    def __init__(self, theme: Theme, on_switch: Callable[[str, str], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.uuid = ""
        pad = em(0.5)
        row = QHBoxLayout(self)
        row.setContentsMargins(pad * 2, pad // 2, pad * 2, pad // 2)
        row.setSpacing(pad)
        self.swatch = Swatch(theme, ring=True, parent=self)
        row.addWidget(self.swatch, 0, Qt.AlignmentFlag.AlignVCenter)
        # The name and its words: one line while they fit, each piece whole on a line of its own where they do not.
        self.words = Flow(theme, ("ink-2", "muted", "muted"), ("", "  ", " · "), parent=self)
        self.words.labels[0].setFont(theme.fonts["bold"])
        row.addWidget(self.words, 1)
        self.switches = SwitchButtons(row, self, theme, on_switch, lambda: self.uuid)

    def update_from(self, row: EndedRow, colour_role: str) -> None:
        self.uuid = row.uuid
        self.swatch.set(colour_role)
        self.words.set(row.label, row.text, row.email)
        self.switches.show(row.switches, row.label)
