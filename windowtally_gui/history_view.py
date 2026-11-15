"""The History window: the history page's content over a span the user chooses, in a window of its own beside the main
one.

At its head, fixed while the rest scrolls: the spans — 7 days, 30 days, 6 months, All — as one segmented control, the
chosen one filled; Recompute (F5); Export HTML… (Ctrl+S), which saves the history shown as one HTML file where the user
chooses and opens it in the browser; and the line saying what is shown and as of when, or which span is being computed,
or why it could not be, or how the last export went. Below, one scrolling column in the page's order
(``history_model.blocks``): the summary's tiles first, a caption over a figure on the cards' surface, in the columns of
one width ``tiles_model`` gives, the figures at their foot; charts at the window's width (``plot_view``), every one
with its value axis at the place the widest of their labels sets; tables at the window's width, a long one showing twelve
rows and scrolling within itself under headings that stay (``table_view``); the notes beside them, which say only a
section's state. What a section's figures mean is the hint of a ? beside its heading, never text in the column. A
section holding two views of one kind — the cost or the token chart, the token tables by week or by month, a full
window by plan or by week — shows one, a segmented control beside its heading choosing (``SwitchView``); a choice stays
while the window stands, through every change of span and Recompute, and the export shows the view shown. So the
tiles, the charts and the tables share the column's two edges. The content shown stays while the next span is computed,
and is replaced in place when it is ready.

Closing the window hides it; it is computed afresh each time it is shown, as on each choice and on Recompute.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QCursor, QFontMetricsF, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from windowtally.history import SPANS, History
from windowtally.paths import MachinePaths

from . import actions_model, history_model
from .background import Background
from .cards_view import Meter
from .common_view import Hint, ScrollFrame, Tip, card_margins, em, plain_label
from .history_model import Bullets, Chart, Heading, Legend, Note, Requests, Switch, Table, Tiles
from .plot_view import ChartView, LegendView
from .table_view import TableView
from .theme_view import Theme
from .tiles_model import LEAST_WIDTH, TileMarks, layout_tiles

SIZE = (60, 44)        # lines of the default font, wide and tall, within 90 % of the monitor
LEAST_SIZE = (24, 16)  # lines of the default font the window can be made down to
HINT_WIDTH = 40        # lines of the default font a section's hint wraps at: some run to a paragraph
SHARE_BAR = 0.25       # lines of the default font an account's share bar stands tall


def ask_save_path(parent: QWidget, folder: Path | None, name: str) -> str:
    """The file the user chooses to export to, or "" if they did not. The dialog is Windows' own (measured with Qt 6.12.0
    on the development machine, 2026-11-07), so it follows Windows, not the window's palette. It is deleted once it has
    answered: left standing it would keep its file-system model under the window for as long as the window stands."""
    dialog = QFileDialog(parent, "Export the history as HTML", str(folder) if folder else "",
                         "HTML file (*.html);;All files (*.*)")
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setDefaultSuffix("html")
    dialog.selectFile(name)
    chosen = dialog.selectedFiles()[0] if dialog.exec() else ""
    dialog.deleteLater()
    return chosen


class TilesView(QWidget):
    """A tile per figure, each in one of the columns of one width across the view (``tiles_model``), its caption wrapped
    to the column. A tile's height depends on its column's width, which depends only on the tiles' least widths, so the
    columns are found first and the heights at their width. An account's share has a bar under its figure, as far as the
    share goes, in the account's colour, and every tile keeps that bar's room, so the figures stand at one height."""

    def __init__(self, theme: Theme, tiles: Tiles, parent: QWidget | None = None):
        super().__init__(parent)
        self.gap = em(0.5)                   # as the main window's cards stand apart
        self.boxes: list[QFrame] = []
        self.captions: list[QLabel] = []
        self.figures: list[QLabel] = []
        self.bars: list[Meter | None] = []
        margins = card_margins()
        bars = tiles.bars or (None,) * len(tiles.items)
        # Where any tile has a bar, every tile keeps its room under the figure, so the figures stand at one height.
        self.under = em(0.3) + Meter.tall(SHARE_BAR) if any(bars) else 0
        for (caption, figure), bar in zip(tiles.items, bars, strict=True):
            box = QFrame(self)
            theme.mark(box, "surface", "tile")
            stack = QVBoxLayout(box)
            stack.setContentsMargins(*margins)
            stack.setSpacing(0)
            words = plain_label(box)
            words.setText(caption)
            words.setWordWrap(True)
            words.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            theme.ink(words, "ink-2")
            stack.addWidget(words)
            stack.addStretch(1)
            value = plain_label(box)
            value.setText(figure)
            value.setFont(theme.fonts["figure"])
            theme.ink(value, "ink")
            stack.addWidget(value)
            meter = None
            if bar is not None:
                meter = Meter(theme, box, SHARE_BAR)
                meter.set(bar[0], role=bar[1])
                stack.addSpacing(self.under - meter.height())
                stack.addWidget(meter)
            elif self.under:
                stack.addSpacing(self.under)
            self.boxes.append(box)
            self.captions.append(words)
            self.figures.append(value)
            self.bars.append(meter)
        self.sides = margins[0] + margins[2] + 2      # a tile's padding and rim, on its two sides
        self.tops = margins[1] + margins[3] + 2
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _least(self, index: int) -> int:
        """The narrowest a tile stands in: its figure, or its caption's longest word, since the caption wraps."""
        metrics = QFontMetricsF(self.captions[index].font())
        word = max((metrics.horizontalAdvance(w) for w in self.captions[index].text().split()), default=0.0)
        return self.sides + max(int(word) + 1, self.figures[index].sizeHint().width())

    def _arranged(self, width: int) -> TileMarks:
        least = [self._least(index) for index in range(len(self.boxes))]
        columns = layout_tiles(tuple((wide, 0) for wide in least), width, self.gap, LEAST_WIDTH)
        sizes = []
        for index, (wide, place) in enumerate(zip(least, columns.places)):
            caption = self.captions[index].heightForWidth(max(1, place.width - self.sides))
            sizes.append((wide, self.tops + caption + self.figures[index].sizeHint().height() + self.under))
        return layout_tiles(tuple(sizes), width, self.gap, LEAST_WIDTH)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arranged(width).height

    def sizeHint(self) -> QSize:
        return QSize(em(SIZE[0]), self.heightForWidth(em(SIZE[0])))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for box, place in zip(self.boxes, self._arranged(self.width()).places):
            box.setGeometry(place.x, place.y, place.width, place.height)


class HistoryWindow(QWidget):
    def __init__(self, theme: Theme, paths: MachinePaths, source_errors: Callable[[], tuple[str, ...]],
                 work: Background, *, choose_file: Callable[[QWidget, Path | None, str], str] = ask_save_path,
                 open_url: Callable[[str], object] = webbrowser.open):
        """``source_errors()`` gives the problems status.json lists; ``work`` is the lane the history is computed on,
        polled by the main window's clock. ``choose_file`` and ``open_url`` stand in for the save dialog and the
        browser in a test."""
        super().__init__()
        self.theme, self.paths = theme, paths
        self.source_errors, self.work = source_errors, work
        self.choose_file, self.open_url = choose_file, open_url
        self.requests = Requests()
        self.shown_history: History | None = None
        self.choices: dict[str, str] = {}         # each switch's view the user chose, kept while the window stands
        self.switches: list[SwitchView] = []
        self._export_folder: Path | None = None   # where the last export was saved, offered for the next
        self._sized = False
        self.tip = Tip()
        self.destroyed.connect(self.tip.close)
        self.charts: list[ChartView] = []
        self.axis: tuple[str, ...] = ()           # every chart's value labels, which set where each axis stands
        self.setWindowTitle("WindowTally — history")
        theme.ground(self)
        pad = em(0.5)
        self.pad = pad

        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)
        head = QVBoxLayout()
        head.setContentsMargins(pad * 2, pad, pad * 2, pad)
        head.setSpacing(pad)
        row = QHBoxLayout()
        row.setSpacing(pad)
        self.spans = QButtonGroup(self)
        self.span_buttons: dict[str, QPushButton] = {}
        segments = QHBoxLayout()
        segments.setSpacing(0)
        for index, span in enumerate(SPANS):
            button = QPushButton(span.label, self)
            button.setCheckable(True)
            place = "first" if index == 0 else "last" if index == len(SPANS) - 1 else "middle"
            theme.mark(button, "segment", place)
            button.clicked.connect(lambda _checked=False, key=span.key: self._chosen(key))
            self.spans.addButton(button)
            segments.addWidget(button)
            self.span_buttons[span.key] = button
        self.span_buttons[self.requests.chosen].setChecked(True)
        row.addLayout(segments)
        row.addSpacing(pad)
        self.recompute_button = QPushButton("Recompute", self)
        self.recompute_button.clicked.connect(lambda _checked=False: self.recompute())
        Hint(self.recompute_button, "Read the ledger again (F5)")
        row.addWidget(self.recompute_button)
        self.export_button = QPushButton("Export HTML…", self)
        self.export_button.clicked.connect(lambda _checked=False: self.export())
        Hint(self.export_button, "Save as HTML and open it (Ctrl+S)")
        row.addWidget(self.export_button)
        row.addStretch(1)
        head.addLayout(row)
        self.status = plain_label(self)
        self.status.setWordWrap(True)
        theme.ink(self.status, "ink-2")
        head.addWidget(self.status)
        page.addLayout(head)
        rule = QFrame(self)
        rule.setFixedHeight(1)
        theme.mark(rule, "surface", "rule")
        page.addWidget(rule)

        self.scroll = ScrollFrame(self)
        self.scroll.verticalScrollBar().valueChanged.connect(lambda _value: self._scrolled())
        self.column = QVBoxLayout(self.scroll.body)
        self.column.setContentsMargins(0, 0, pad, 0)
        self.column.setSpacing(0)
        self.column.setAlignment(Qt.AlignmentFlag.AlignTop)
        wrapper = QVBoxLayout()
        wrapper.setContentsMargins(pad * 2, 0, pad, pad)
        wrapper.addWidget(self.scroll)
        page.addLayout(wrapper, 1)

        QShortcut(QKeySequence(Qt.Key.Key_F5), self, activated=self.recompute)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.export)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)
        self._placeholder("Computing…")

    # --- showing --------------------------------------------------------------------------------------------------

    def open(self) -> None:
        if not self._sized:
            self._sized = True
            self._size()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()
        self.span_buttons[self.requests.chosen].setFocus()
        self.recompute()

    def _size(self) -> None:
        area = QGuiApplication.primaryScreen().availableGeometry()
        width = min(em(SIZE[0]), int(area.width() * 0.9))
        height = min(em(SIZE[1]), int(area.height() * 0.9))
        self.resize(width, height)
        self.move(area.left() + (area.width() - width) // 2, area.top() + (area.height() - height) // 3)
        self.setMinimumSize(min(width, em(LEAST_SIZE[0])), min(height, em(LEAST_SIZE[1])))

    # --- computing ------------------------------------------------------------------------------------------------

    def _chosen(self, key: str) -> None:
        self._start(self.requests.want(key))

    def recompute(self) -> None:
        self._start(self.requests.want(self.requests.chosen))

    def _start(self, key: str | None) -> None:
        if key is not None:
            errors = self.source_errors()
            started = self.work.start(
                "history", lambda: history_model.compute(self.paths, key, errors),
                lambda result, key=key: self._finished(key, result=result),
                lambda error, key=key: self._finished(key, failure=str(error) or type(error).__name__))
            if not started:   # cannot happen while this window owns the lane; said rather than lost
                self.requests.done(key, failure="another computation is running")
        self._say()

    def _finished(self, key: str, result: History | None = None, failure: str | None = None) -> None:
        following = self.requests.done(key, result, failure)
        if self.requests.shown is not None and self.requests.shown is not self.shown_history:
            self.shown_history = self.requests.shown
            self._render(history_model.blocks(self.shown_history, self.choices))
        self._start(following)

    def _say(self) -> None:
        self._tell(*self.requests.status())
        self.span_buttons[self.requests.chosen].setChecked(True)
        if self.shown_history is None:   # nothing computed yet: the content's place says what the line says
            self._placeholder("Computing…" if self.requests.running else "Not computed.")

    # --- exporting ------------------------------------------------------------------------------------------------

    def export(self) -> None:
        """The history shown, saved where the user chooses as one HTML file and opened in the browser; said on the
        line above the content until the next computation's word replaces it."""
        if self.shown_history is None:
            self._tell("Nothing to export yet: still computing." if self.requests.running else
                       "Nothing to export: not computed.", failed=True)
            return
        shown = self.shown_history
        folder = self._export_folder or next((p for p in (Path.home() / "Downloads", Path.home()) if p.is_dir()), None)
        name = self.choose_file(self, folder, history_model.export_name(shown))
        if not name:
            return
        path = Path(name)
        self._export_folder = path.parent
        outcome = actions_model.export_history(shown, path, self.open_url, self.choices)
        self._tell(outcome.message, failed=not outcome.ok)

    def _tell(self, text: str, failed: bool = False) -> None:
        self.status.setText(text)
        self.theme.ink(self.status, "critical-text" if failed else "ink-2")

    # --- the content ----------------------------------------------------------------------------------------------

    def _scrolled(self) -> None:
        """The marks moved under a pointer that may not have: no mouse event says so. Only the chart really under the
        pointer looks, the part of one that is scrolled away or covered being no place for its words."""
        at = QCursor.pos()
        under = QApplication.widgetAt(at)
        for chart in self.charts + [c for switch in self.switches for c in switch.charts]:
            chart.look(at if chart is under else None)

    def _clear(self) -> None:
        self.tip.hide()
        self.charts = []
        self.switches = []
        while self.column.count():
            item = self.column.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()

    def _add(self, widget: QWidget, above: int = 0, below: int = 0, column: QVBoxLayout | None = None) -> None:
        """``widget`` into ``column``, the scrolling column where none is named."""
        column = self.column if column is None else column
        if above:
            column.addSpacing(above)
        column.addWidget(widget)
        if below:
            column.addSpacing(below)

    def _placeholder(self, text: str) -> None:
        self._clear()
        self._add(self._note(text), above=self.pad)

    def _render(self, blocks) -> None:
        body = self.scroll.body
        body.setUpdatesEnabled(False)
        try:
            self._fill(blocks)
        finally:
            body.setUpdatesEnabled(True)

    def _fill(self, blocks) -> None:
        self._clear()
        # Every chart's value labels, a switched section's every view's among them, so a chart's axis stands where the
        # others' do whichever view is shown.
        charts = [b for block in blocks for b in ((block,) if not isinstance(block, Switch)
                                                   else (b for view in block.views for b in view.blocks))
                  if isinstance(b, Chart)]
        self.axis = tuple(text for chart in charts for _value, text in chart.plot.y_ticks)
        self.lay(blocks, self.column, self.charts)
        self.column.addStretch(1)
        self.scroll.verticalScrollBar().setValue(0)

    def lay(self, blocks, column: QVBoxLayout, charts: list[ChartView]) -> None:
        """``blocks`` into ``column``, each chart made also into ``charts``."""
        body, pad = self.scroll.body, self.pad
        for index, block in enumerate(blocks):
            if isinstance(block, Heading):
                self._add(self._heading(block), above=pad * 2 if index else pad, below=pad // 2, column=column)
            elif isinstance(block, Switch):
                switch = SwitchView(self, block, body)
                self.switches.append(switch)
                self._add(switch, above=pad * 2 if index else pad, column=column)
            elif isinstance(block, Note):
                self._add(self._note(block.text), above=pad // 2, column=column)
            elif isinstance(block, Legend):
                self._add(self._legend(block), below=pad // 2, column=column)
            elif isinstance(block, Chart):
                chart = ChartView(self.theme, block.plot, block.height, self.axis, self.tip, body)
                charts.append(chart)
                self._add(chart, column=column)
            elif isinstance(block, Table):
                self._add(TableView(self.theme, block, body), column=column)
            elif isinstance(block, Tiles):
                self._add(TilesView(self.theme, block, body), column=column)
            elif isinstance(block, Bullets):
                for item in block.items:
                    self._add(self._note(f"• {item}", "ink"), column=column)

    def _heading(self, heading: Heading) -> QWidget:
        row = HeadingRow(self.theme, self.pad, self.scroll.body)
        row.say(heading)
        return row.frame

    def _note(self, text: str, role: str = "ink-2") -> QLabel:
        label = plain_label(self.scroll.body)
        label.setText(text)
        label.setWordWrap(True)
        self.theme.ink(label, role)
        return label

    def _legend(self, legend: Legend) -> LegendView:
        """A swatch per series and, for each kind of reset the chart marks, its marker's outline."""
        items = (tuple((label, token, "") for label, token in legend.items)
                 + tuple((words, "ink-2", shape) for words, shape in legend.marks))
        return LegendView(self.theme, items, self.scroll.body)


class HeadingRow:
    """A section's heading, in ``frame``: its words and, while it has a hint, a ? beside them that shows the hint while
    the pointer rests on it or on the words, and while the ?, which Tab reaches, has the focus — the surface itself
    carrying no explanation. A switched section's control stands between the words and the ? (``place``), and ``say``
    changes the words and the hint in place."""

    def __init__(self, theme: Theme, pad: int, parent: QWidget):
        self.theme = theme
        self.frame = QWidget(parent)
        self.row = QHBoxLayout(self.frame)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(pad // 2)
        self.title = plain_label(self.frame)
        self.title.setMinimumWidth(1)  # a long account's name gives way to a narrow window, not the column to the name
        self.title.setFont(theme.fonts["title"])
        theme.ink(self.title, "ink")
        self.row.addWidget(self.title)
        self.row.addStretch(1)
        self.mark: QLabel | None = None             # made with the first hint
        self.hints: tuple[Hint, Hint] | None = None   # the words' and the ?'s

    def place(self, control: QHBoxLayout) -> None:
        """``control`` after the words, before the ?."""
        self.row.insertLayout(1, control)

    def say(self, heading: Heading) -> None:
        self.title.setText(heading.text)
        if heading.hint and self.mark is None:
            self.mark = mark = plain_label(self.frame)
            mark.setText("?")
            mark.setFont(self.theme.fonts["bold"])
            mark.setCursor(Qt.CursorShape.WhatsThisCursor)
            self.theme.ink(mark, "ink-2")
            self.theme.mark(mark, "help", "true")
            self.row.insertWidget(self.row.count() - 1, mark)
            self.hints = (Hint(self.title, width=HINT_WIDTH), Hint(mark, width=HINT_WIDTH, focus=True))
        if self.mark is not None:
            for hint in self.hints:
                hint.text = heading.hint
                hint.tip.hide()
            self.mark.setVisible(bool(heading.hint))
            self.mark.setFocusPolicy(Qt.FocusPolicy.TabFocus if heading.hint else Qt.FocusPolicy.NoFocus)


class SwitchView(QWidget):
    """A section shown in one of its views at a time: its heading row — the shown view's words, the switch as a
    segmented control like the spans', the shown view's ? — over the shown view's blocks. Every view is laid out once
    and the others hidden, so a view chosen again comes back as it was left, a table scrolled where it stood. A choice
    is kept in the window's ``choices``, so the next computation and the export show the same view."""

    def __init__(self, window: HistoryWindow, switch: Switch, parent: QWidget):
        super().__init__(parent)
        self.owner, self.switch = window, switch      # not ``window``, which would hide QWidget.window()
        theme, pad = window.theme, window.pad
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.head = HeadingRow(theme, pad, self)
        segments = QHBoxLayout()
        segments.setSpacing(0)
        self.group = QButtonGroup(self)
        self.buttons: list[QPushButton] = []
        last = len(switch.views) - 1
        for index, view in enumerate(switch.views):
            button = QPushButton(view.choice, self.head.frame)
            button.setCheckable(True)
            theme.mark(button, "segment", "first" if index == 0 else "last" if index == last else "middle")
            button.clicked.connect(lambda _checked=False, index=index: self.choose(index))
            self.group.addButton(button)
            segments.addWidget(button)
            self.buttons.append(button)
        self.head.place(segments)
        outer.addWidget(self.head.frame)
        outer.addSpacing(pad // 2)
        self.bodies: list[QWidget] = []
        self.view_charts: list[list[ChartView]] = []
        for view in switch.views:
            body = QWidget(self)
            column = QVBoxLayout(body)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(0)
            charts: list[ChartView] = []
            window.lay(view.blocks, column, charts)
            body.setVisible(False)
            outer.addWidget(body)
            self.bodies.append(body)
            self.view_charts.append(charts)
        self.shown = -1
        self._show(switch.shown)

    @property
    def charts(self) -> list[ChartView]:
        """The shown view's charts."""
        return self.view_charts[self.shown]

    def choose(self, index: int) -> None:
        """The user's choice of a view: shown, and kept for the window."""
        self.owner.choices[self.switch.key] = self.switch.views[index].choice
        self._show(index)

    def _show(self, index: int) -> None:
        self.buttons[index].setChecked(True)
        if index == self.shown:
            return
        self.owner.tip.hide()
        self.head.say(self.switch.views[index].heading)
        for at, body in enumerate(self.bodies):
            body.setVisible(at == index)
        self.shown = index
