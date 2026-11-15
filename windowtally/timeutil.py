"""Timestamp parsing and formatting shared by the ingesters. The ledger stores every time as epoch seconds (UTC).

Names of days and months are written from ``DAYS`` and ``MONTHS``, never by ``strftime``, whose names follow whatever
locale the process runs under: WindowTally's words are English in every process, the window's included.
"""

from __future__ import annotations

from datetime import datetime, timezone

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def parse_iso(text: str | None) -> float | None:
    """Epoch seconds for an ISO 8601 timestamp ("2026-10-20T20:10:00.086Z", "...-05:00"); None when unparseable.

    A timestamp without an offset is read as UTC: every producer WindowTally reads writes UTC or an explicit offset.
    """
    if not text or not isinstance(text, str):
        return None
    candidate = text.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def to_iso(epoch: float | None) -> str | None:
    """UTC ISO 8601 with milliseconds and a Z suffix, or None."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def local_datetime(epoch: float) -> datetime:
    """The moment in the machine's local time zone, for display."""
    return datetime.fromtimestamp(epoch).astimezone()
