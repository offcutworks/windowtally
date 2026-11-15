"""WindowTally's colours, light and dark: the one palette the history page's style sheet is written from and the window
paints with, so an account wears one colour wherever it is drawn.

A token is a CSS custom property's name without its two dashes. The series slots are the dataviz reference palette,
unchanged (validated by its authors as an ordered set for stacks, bars and lines in both modes; the first three slots
also validate all-pairs): accounts take slots 1-3 in the order they were first seen, model families slots 4-8. The
status colours ``good``, ``warning`` and ``critical`` are fills, the same in both modes, and never a text colour,
because amber on a light surface is unreadable: a figure at a warning level is written in the level's text peer
(``warning-text``, ``critical-text``) beside the ring its status colours.
``surface-1`` stands apart from ``page`` in both modes, so a card or panel reads as a region of its own, and ``muted``,
the page's note and tick text, reads at 4.5:1 or more on both.

The surfaces and inks are a restrained dashboard's: a cool, blue-black page under the dark mode, its showcase, and a
cool, pale one under the light mode, its counterpart in the same language; cards one step off the page, inks tinted
toward the blue of the logo's weekly ring. What that language lays on them is here too, each opaque, as it would
stand over the surface under it: the hairline a card's or a panel's edge is drawn in (``edge``), a ring's empty track
(``ring-track``), the fine grid on the page ground (``page-grid``) and the accent-tinted band the recommendation stands
on (``advice``).
"""

from __future__ import annotations

LIGHT: dict[str, str] = {
    "surface-1": "#ffffff", "page": "#edf1f6", "ink": "#0c1320", "ink-2": "#3b4759", "muted": "#5a677a",
    "grid": "#e1e7ef", "baseline": "#c5cfdc",
    "series-1": "#2a78d6", "series-2": "#eb6834", "series-3": "#1baf7a", "series-4": "#eda100",
    "series-5": "#e87ba4", "series-6": "#008300", "series-7": "#6250d6", "series-8": "#e34948",
    "good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b",
    "warning-text": "#8a5300", "critical-text": "#b3261e", "advice": "#e3edf9",
    "edge": "#d5dde8", "ring-track": "#e3e9f1", "page-grid": "#e4eaf3",
}

DARK: dict[str, str] = {
    "surface-1": "#101a28", "page": "#070b12", "ink": "#e6edf7", "ink-2": "#a7b4c7", "muted": "#8391a6",
    "grid": "#172233", "baseline": "#26354a",
    "series-1": "#3987e5", "series-2": "#d95926", "series-3": "#199e70", "series-4": "#c98500",
    "series-5": "#d55181", "series-6": "#008300", "series-7": "#9085e9", "series-8": "#e66767",
    "good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b",
    "warning-text": "#fab219", "critical-text": "#ff8a80", "advice": "#11243b",
    "edge": "#273344", "ring-track": "#1a2433", "page-grid": "#0b1422",
}

ACCOUNT_SLOTS = ("series-1", "series-2", "series-3")
FAMILY_SLOTS = ("series-4", "series-5", "series-6", "series-7", "series-8")


def css_tokens(palette: dict[str, str]) -> str:
    """The palette as CSS custom-property declarations."""
    return " ".join(f"--{name}:{value};" for name, value in palette.items())
