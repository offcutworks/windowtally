"""How far the wheel scrolls a view, and when a chart's pointer words may show, with no toolkit.

The wheel. A notch is 120 of the wheel's units; a finer wheel or a touchpad sends less at a time. A view scrolls as far
as Windows' setting for the wheel says — so many lines of the default font a notch, three unless the user changed it,
or a page where the setting asks for a screen at a time — and every unit the wheel sent counts: what does not make a
whole line yet is carried to the next turn of the wheel, kept exactly whatever the setting, and dropped when the wheel
turns the other way, as Windows does. Notches arriving faster than the window repaints are added together and scrolled
in one step.

A view inside another — a table taller than it shows, within the History view — takes the wheel while it can still move
the way the wheel turns (``inner_takes``); at its top turning up, or at its end turning down, the turn goes on to the
view around it, so the wheel never stops at a table's edge.

The wheel's turns come in gestures, and a gesture keeps to the view that took its first turn (``gesture_goes_on``):
scrolling the History view on, a table that the scroll brings under the still pointer does not take the turns that
follow. A gesture ends when the wheel rests for ``history.WHEEL_PAUSE`` or the pointer has moved beyond Windows' drag
threshold from where the gesture began, the next turn choosing its view afresh (``Gesture``); a table that took a
gesture and reaches its edge passes the turn on to the view around it, which keeps the rest of the gesture, and a view
that can no longer move the wheel's way lets the turn choose afresh, so a table under the pointer is never held still
by a view that cannot move. So does a view that has gone, or one in another window than the pointer's.

Where each turn goes is decided here, whole (``wheel_turn``): the walk from the view under the pointer outwards to the
one that takes the turn, and the checks that let a held gesture choose afresh. The window's one wheel handler only
finds the widget under the pointer and answers this module's questions about its widgets (``WheelViews``), so the
decision runs in the tests with no toolkit and no display.

The pointer words. A chart's mark says what it is once the pointer has rested on it for Windows' hover time, and only
when the view has not scrolled for as long: while the content moves under a still pointer, marks pass beneath it and
none of them speaks.

A list's rows. A list given whatever height its window has left stands as tall as a whole number of its rows
(``whole_rows_height``), so its last row is never cut through its words; the list scrolls by rows, so each step still
ends on a whole one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

NOTCH = 120
PAGE = 0xFFFFFFFF       # Windows' wheel setting for "one screen at a time" (WHEEL_PAGESCROLL)
EDGE = 1e-6             # how near a view's fractions may come to 0 or 1 and still count as at its edge


def wheel_steps(delta: int, carried: int, lines: int) -> tuple[int, str, int]:
    """The scroll for ``delta`` wheel units under Windows' ``lines`` a notch, ``carried`` left short of a whole step
    before it: (how many, ``"units"`` or ``"pages"``, what is carried on). A positive count scrolls down, towards the
    content's end; the wheel's positive delta turns it away from the user, which scrolls up. What is carried is counted
    in wheel units times the steps a notch makes, so a setting that does not divide a notch loses nothing."""
    if lines == 0:
        return 0, "units", 0
    per, what = (1, "pages") if lines == PAGE else (lines, "units")
    amount = -delta * per
    if carried and (carried > 0) != (amount > 0):
        carried = 0
    total = carried + amount
    steps = int(total / NOTCH)
    return steps, what, total - steps * NOTCH


def inner_takes(first: float, last: float, delta: int) -> bool:
    """Whether a view scrolled inside another, now showing ``first`` to ``last`` of its content (0 to 1, from its
    scroll bar's value and page), takes a turn of ``delta`` wheel units rather than passing it on to the view around it."""
    if delta < 0:
        return last < 1.0 - EDGE
    if delta > 0:
        return first > EDGE
    return False


def gesture_goes_on(since: float, moved: tuple[int, int], slop: tuple[int, int], pause: float) -> bool:
    """Whether a turn of the wheel ``since`` seconds after its gesture's last turn, the pointer moved by ``moved``
    pixels (across, down) since the gesture's first turn, continues that gesture: it does unless the wheel rested
    longer than ``pause`` or the pointer moved further than ``slop`` (Windows' drag threshold, across and down) either
    way, as a hand turning the wheel does not."""
    return 0.0 <= since <= pause and abs(moved[0]) <= slop[0] and abs(moved[1]) <= slop[1]


@dataclass
class Gesture:
    """The wheel's gesture now: the view that took its last turn, when that turn came, where the pointer stood at the
    gesture's first turn, and the drag threshold read then — read once a gesture, not at every turn."""
    owner: object = None
    at: float = 0.0
    x: int = 0
    y: int = 0
    slop: tuple[int, int] = (0, 0)

    def held(self, now: float, x: int, y: int, pause: float) -> object:
        """The view a turn at (``x``, ``y``) goes to without choosing afresh; None once the gesture has ended."""
        if self.owner is None or not gesture_goes_on(now - self.at, (x - self.x, y - self.y), self.slop, pause):
            return None
        return self.owner

    def took(self, owner: object, now: float, x: int, y: int, slop: tuple[int, int] | None = None) -> None:
        """``owner`` took the turn at (``x``, ``y``); a ``slop`` begins a new gesture there. None ends the gesture."""
        if slop is not None:
            self.x, self.y, self.slop = x, y, slop
        self.owner, self.at = owner, now


class WheelViews(Protocol):
    """What the wheel's route asks of the window's views; the window answers for its widgets, a test for stand-ins."""

    def parent(self, view: object) -> object:
        """The view ``view`` sits in; None at the top of its window."""

    def takes_inside(self, view: object, delta: int) -> bool:
        """Whether ``view``, scrolling within the view around it, takes a turn of ``delta`` wheel units — having
        scrolled by it when it does; False for a view that does not scroll within another."""

    def is_frame(self, view: object) -> bool:
        """Whether ``view`` is a scrolling view of the window, which takes any turn that reaches it."""

    def scroll(self, view: object, delta: int) -> None:
        """Scrolls the frame ``view`` by a turn of ``delta`` wheel units."""

    def can_move(self, view: object, delta: int) -> bool:
        """Whether the frame ``view`` can still move the way a turn of ``delta`` wheel units goes."""

    def exists(self, view: object) -> bool:
        """Whether ``view`` is still there."""

    def window(self, view: object) -> object:
        """The window ``view`` is in, compared by equality."""


def wheel_taker(start: object, delta: int, views: WheelViews, *, frame_must_move: bool = False) -> object:
    """The view that takes a turn of ``delta`` wheel units, from ``start`` outwards, having scrolled it: the first that
    scrolls within the view around it and can still move the wheel's way, else the frame around it; None where none
    does. With ``frame_must_move`` a frame that cannot move the wheel's way does not take it either, and nothing
    scrolls."""
    view = start
    while view is not None:
        if views.takes_inside(view, delta):
            return view
        if views.is_frame(view):
            if frame_must_move and not views.can_move(view, delta):
                return None
            views.scroll(view, delta)
            return view
        view = views.parent(view)
    return None


def wheel_turn(gesture: Gesture, under: object, delta: int, now: float, x: int, y: int, pause: float,
               views: WheelViews, slop: Callable[[], tuple[int, int]]) -> object:
    """Where a turn of ``delta`` wheel units at (``x``, ``y``) on the screen goes, ``under`` being the view under the
    pointer; the turn taken (``wheel_taker``) and ``gesture`` kept. A held gesture's turn goes out from its view to the
    first that can move the wheel's way, unless that view has gone or stands in another window than ``under``. Where
    it cannot go so — the held frame, or the frame a held table at its edge passes the turn to, unable to move — as
    when no gesture is held, the turn chooses afresh from ``under`` and begins a gesture, reading Windows' drag
    threshold through ``slop``: once a gesture, never at every turn. None where nothing takes it."""
    owner = gesture.held(now, x, y, pause)
    if owner is not None and views.exists(owner) and views.window(owner) == views.window(under):
        taker = wheel_taker(owner, delta, views, frame_must_move=True)
        if taker is not None:
            gesture.took(taker, now, x, y)
            return taker
    taker = wheel_taker(under, delta, views)
    gesture.took(taker, now, x, y, slop())
    return taker


def words_due(now: float, rested_since: float, scrolled_at: float, rest: float) -> float:
    """Seconds still to wait before a mark under the pointer since ``rested_since`` may say what it is, the view last
    scrolled at ``scrolled_at``; 0 when it may now."""
    return max(0.0, rested_since + rest - now, scrolled_at + rest - now)


def scroll_bars(width: int, height: int, columns: int, rows: int, across: int, down: int) -> tuple[bool, bool]:
    """Which scroll bars a list ``width`` by ``height`` inside its frame and headings shows, as Qt shows them while
    needed: (the one down its side, the one under its rows). ``columns`` is the least width its columns take, ``rows``
    the height of every row it shows; the bar down the side takes ``across`` of the width and the one under the rows
    ``down`` of the height, and each can make the other needed."""
    side = under = False
    for _ in range(2):
        under = columns > width - (across if side else 0)
        side = rows > height - (down if under else 0)
    return side, columns > width - (across if side else 0)


def whole_rows_height(height: int, fixed: int, row: int) -> int:
    """The height of a list given ``height`` whose headings, frame and scroll bar take ``fixed`` and whose rows stand
    ``row`` tall each: as many whole rows as the rest holds, and at least one, though one row may need more than
    ``height`` gives. A row of no height, which no laid-out list has, leaves ``height`` as given."""
    if row <= 0:
        return height
    return fixed + max(1, (height - fixed) // row) * row
