"""How times, spans and figures read in the window: the desktop plugin's own forms (``plugin/hooks/text.ts``), so the
window and the band above a Code session's prompt say one thing the same way.

Names of days and months are written from WindowTally's tables (``windowtally.timeutil``), never by ``strftime``, whose
names follow whatever locale the process runs under: the window's words are English throughout.
"""

from __future__ import annotations

import math
from datetime import date

from windowtally.timeutil import DAYS, MONTHS, local_datetime


def span(seconds: float) -> str:
    """A span of time, its two coarsest units: ``<1m``, ``49m``, ``1h 05m``, ``4d 1h``."""
    minutes = int(max(0.0, seconds) // 60)
    if minutes < 1:
        return "<1m"
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h {minutes % 60:02d}m"
    return f"{hours // 24}d {hours % 24}h"


def ago(seconds: float) -> str:
    """How long ago: ``just now`` under a minute, else ``49m ago``."""
    return "just now" if seconds < 60 else f"{span(seconds)} ago"


def when(epoch: float, with_date: bool = False) -> str:
    """A moment in the machine's time zone: ``Mon 01:07``, or with ``with_date`` ``Mon 26 Oct 01:07``."""
    moment = local_datetime(epoch)
    clock = f"{moment.hour:02d}:{moment.minute:02d}"
    weekday = DAYS[moment.weekday()]
    return f"{weekday} {moment.day} {MONTHS[moment.month - 1]} {clock}" if with_date else f"{weekday} {clock}"


def day_text(text: str | None) -> str:
    """A day written YYYY-MM-DD, as ``Sat 7 Nov``; the text itself when it is not one."""
    try:
        day = date.fromisoformat(text or "")
    except ValueError:
        return text or ""
    return f"{DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"


def percent_text(value: float) -> str:
    """A percentage rounded half up, as the band rounds it: ``62.5`` reads ``63%``."""
    return f"{math.floor(value + 0.5)}%"


def plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")
