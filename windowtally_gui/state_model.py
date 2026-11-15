"""window.json — the window's own record in WindowTally's data folder: its place and size, whether it stays on top, the
theme the user chose (``theme_model.THEME_CHOICES``), and the notices it already gave (``notices_model``). Only the
window reads or writes it and nothing else depends on it, so a file that cannot be read gives way to the defaults,
which the window says in its status line, and is written afresh at the next change. A theme absent or unknown follows
Windows.

    {"v": 1, "geometry": "760x560+120+80", "keepOnTop": false, "theme": "system",
     "renewalsNotified": ["<account uuid> 2026-11-07"], "problemsNotified": ["bills: ..."]}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from windowtally.files import write_text_atomically

from .theme_model import THEME_CHOICES

STATE_VERSION = 1
_GEOMETRY = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")


@dataclass(frozen=True)
class WindowState:
    geometry: str | None = None                 # "WIDTHxHEIGHT+X+Y", the display's pixels (common_view)
    keep_on_top: bool = False
    theme: str = "system"                       # system | light | dark
    renewals_notified: tuple[str, ...] = ()     # "<account uuid> <paid until>"
    problems_notified: tuple[str, ...] = ()


def place_of(geometry: str | None) -> tuple[int, int, int, int] | None:
    """The width, height, x and y a geometry string holds; None for anything else."""
    found = _GEOMETRY.match(geometry or "")
    return tuple(int(g) for g in found.groups()) if found else None


def geometry_text(width: int, height: int, x: int, y: int) -> str:
    """The string ``window.json`` keeps a place in."""
    return f"{width}x{height}+{x}+{y}"


def _strings(value: object) -> tuple[str, ...]:
    return tuple(v for v in value if isinstance(v, str)) if isinstance(value, list) else ()


def load_state(path: Path) -> tuple[WindowState, str | None]:
    """The record, and why it could not be read where it could not (the defaults then stand)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return WindowState(), None
    except (OSError, ValueError) as exc:
        return WindowState(), f"the window's record {path} could not be read ({exc}); it starts afresh"
    if not isinstance(data, dict) or data.get("v") != STATE_VERSION:
        return WindowState(), f"the window's record {path} is not version {STATE_VERSION}; it starts afresh"
    geometry = data.get("geometry")
    return WindowState(geometry=geometry if isinstance(geometry, str) and _GEOMETRY.match(geometry) else None,
                       keep_on_top=data.get("keepOnTop") is True,
                       theme=data.get("theme") if data.get("theme") in THEME_CHOICES else "system",
                       renewals_notified=_strings(data.get("renewalsNotified")),
                       problems_notified=_strings(data.get("problemsNotified"))), None


def save_state(path: Path, state: WindowState) -> None:
    data = {"v": STATE_VERSION, "geometry": state.geometry, "keepOnTop": state.keep_on_top, "theme": state.theme,
            "renewalsNotified": list(state.renewals_notified), "problemsNotified": list(state.problems_notified)}
    write_text_atomically(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


@dataclass(frozen=True)
class Area:
    """A rectangle in pixels, its right and bottom edges just outside it: a monitor's working area — its screen less the
    taskbar — or, for the words beside them, a control or the pointer, a point (``common_view.tip_place``)."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def fitted_geometry(geometry: str | None, areas: tuple[Area, ...], default: tuple[int, int]) -> str:
    """Where the window opens: its remembered place while the middle of its title bar lies on a monitor attached now,
    cut to fit that monitor's working area; else ``default`` (width, height) centred on the first area. ``areas``
    holds at least one."""
    place = place_of(geometry)
    if place:
        width, height, x, y = place
        grip = (x + width // 2, y + 10)
        area = next((a for a in areas if a.left <= grip[0] < a.right and a.top <= grip[1] < a.bottom), None)
        if area is not None:
            width, height = min(width, area.width), min(height, area.height)
            x = max(area.left, min(x, area.right - width))
            y = max(area.top, min(y, area.bottom - height))
            return geometry_text(width, height, x, y)
    main = areas[0]
    width, height = min(default[0], main.width), min(default[1], main.height)
    return geometry_text(width, height, main.left + (main.width - width) // 2, main.top + (main.height - height) // 3)
