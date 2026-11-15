"""Whether the tray icon is really in the taskbar's notification area, and what the window does while it is not.

Qt says nothing of whether Windows holds its icon, and Windows can refuse one before the taskbar accepts icons — at
logon, when the window can start in the same second as Explorer. An icon refused at the start would never appear, and
the window, started hidden, would be out of reach. Qt adds its icon again when Explorer re-creates the taskbar (Qt
6.12.0, measured on the development machine, 2026-11-07); an icon Windows refused at its first add could not be made to
happen there, so nothing says Qt recovers from that. The window therefore asks Windows itself whether its icon is there
(``tray_view.Tray.present``), on a clock. One refusal is looked at again ``CHECK_MISSING_S`` seconds later before
anything is done, since Windows also refuses while Explorer is too busy to answer; refused twice running, the icon is
missing, and while it is:

- it makes the icon again every ``CHECK_MISSING_S`` seconds, taking it down and showing it, which has Qt add it anew;
- it shows the window once the icon has been missing for ``SHOW_AFTER_S`` seconds, saying why — the taskbar is then
  the only place the window can be found — rather than at once, since at logon the icon usually arrives at the next
  try;
- it says what a notification would have said on the status line, closing the window minimizes it instead of hiding
  it, and the icon's return is said where its absence was.

With the icon there, it is asked again every ``CHECK_PRESENT_S`` seconds, so an icon lost later is found too.
"""

from __future__ import annotations

from dataclasses import dataclass

CHECK_MISSING_S = 5
CHECK_PRESENT_S = 60
SHOW_AFTER_S = 120

MISSING_SHOWN_SAID = ("The tray icon is not in the taskbar's notification area, so the window shows itself: closing "
                      "it minimizes it, and notifications are said here, until the icon is back. It is made again "
                      f"every {CHECK_MISSING_S} s.")
MISSING_SAID = ("The tray icon is not in the taskbar's notification area: closing the window minimizes it, and "
                "notifications are said here, until the icon is back. It is made again every "
                f"{CHECK_MISSING_S} s.")
BACK_SAID = "The tray icon is back in the taskbar's notification area."


@dataclass(frozen=True)
class Step:
    """What one look at the icon leads to. ``say`` is for the status line, ``note`` for the log."""
    recreate: bool = False
    show: bool = False
    say: str | None = None
    ok: bool = True
    note: str | None = None
    next_check_s: float = CHECK_PRESENT_S


class TrayWatch:
    def __init__(self) -> None:
        self.missing_since: float | None = None
        self._refused_at: float | None = None   # a refusal not yet looked at again
        self._said = False

    @property
    def missing(self) -> bool:
        """Whether the icon was found missing: refused twice running, and not held since."""
        return self.missing_since is not None

    def on_check(self, present: bool | None, now: float, hidden: bool) -> Step:
        """One look: ``present`` is Windows' answer, None where it cannot be asked, which changes nothing; ``hidden``
        is whether the window is withdrawn."""
        if present is None:
            return Step()
        if present:
            self._refused_at = None
            if self.missing_since is None:
                return Step()
            missing_for = now - self.missing_since
            said, self.missing_since, self._said = self._said, None, False
            return Step(say=BACK_SAID if said else None,
                        note=f"The tray icon is in the notification area, {missing_for:.0f} s after it was found "
                             f"missing.")
        note = None
        if self.missing_since is None:
            if self._refused_at is None:
                self._refused_at = now
                return Step(next_check_s=CHECK_MISSING_S)
            self.missing_since, self._refused_at = self._refused_at, None
            note = f"The tray icon is not in the notification area; it is made again every {CHECK_MISSING_S} s."
        if self._said or now - self.missing_since < SHOW_AFTER_S:
            return Step(recreate=True, note=note, next_check_s=CHECK_MISSING_S)
        self._said = True
        return Step(recreate=True, show=hidden, say=MISSING_SHOWN_SAID if hidden else MISSING_SAID, ok=False,
                    note=f"The tray icon has been missing for {now - self.missing_since:.0f} s"
                         + ("; the window shows itself." if hidden else "."),
                    next_check_s=CHECK_MISSING_S)
