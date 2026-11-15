"""The window's colours by role, in the light and the dark mode, and which of the two Windows asks applications for.

The surfaces, the ink, the accounts' and model families' colours, the text colours of the two warning levels, the
recommendation's band (``advice``), the hairline a card's edge is drawn in (``edge``), a ring's empty track
(``ring-track``) and the fine grid on the page ground (``page-grid``) are the history page's own palette
(``windowtally.palette``), so the window and the page wear one colour for one thing. A page has no controls, so
the roles a control needs — a field, a hover and a pressed face, a selection, a focus ring, a disabled word — the one
filled primary action's faces and their ink (``primary``, ``on-primary``) and the one neutral tint every role's chip
stands on (``chip``) are the window's own and are kept here, each opaque. The palette's ``warning`` and ``critical`` are fills: they colour a
meter and are never a text colour; a figure at a level is written in the level's text peer instead
(``warning-text``, ``critical-text``), each measured at 4.5:1 or more on every surface it is written on (the suite
measures them).

The user chooses the theme (``THEME_CHOICES``): following Windows, the default, or light or dark whatever Windows asks.
Following Windows, the mode is Windows' "default app mode" (``AppsUseLightTheme`` in the user's personalisation key),
read again while the window runs, so the window turns dark or light with the system; where the key cannot be read the
window is light. The choice is the window's own, kept in ``window.json`` (``state_model``), and applies to every window
of WindowTally, since they share one theme.
"""

from __future__ import annotations

from windowtally import palette

LIGHT_ONLY = {
    "field": "#ffffff", "face": "#ffffff", "hover": "#e8eef6", "pressed": "#dde5f0", "selection": "#d6e4f5",
    "focus": "#2a78d6", "disabled-text": "#8a94a3",
    "primary": "#1f6fd0", "primary-hover": "#1a63bb", "primary-pressed": "#15559f",
    "on-primary": "#ffffff", "chip": "#e6ebf2",
}
DARK_ONLY = {
    "field": "#0b121c", "face": "#152132", "hover": "#1b293d", "pressed": "#22324a", "selection": "#1d3557",
    "focus": "#3987e5", "disabled-text": "#6c7a8f",
    "primary": "#2566b8", "primary-hover": "#2b71c8", "primary-pressed": "#1f589f",
    "on-primary": "#ffffff", "chip": "#1c2a3d",
}

ROLES = ("page", "surface-1", "ink", "ink-2", "muted", "grid", "baseline", "good", "warning", "critical",
         "series-1", "series-2", "series-3", "series-4", "series-5", "series-6", "series-7", "series-8",
         "warning-text", "critical-text", "advice", "edge", "ring-track", "page-grid") + tuple(LIGHT_ONLY)

LEVEL_FILLS = ("good", "warning", "critical")              # a painted bar at level 0, 1, 2
LEVEL_TEXTS = ("ink", "warning-text", "critical-text")      # a figure at level 0, 1, 2

THEME_CHOICES = ("system", "light", "dark")
THEME_LABELS = {"system": "Follow Windows", "light": "Light", "dark": "Dark"}


def colours(mode: str) -> dict[str, str]:
    """Every role's colour in ``mode`` (light | dark), as #rrggbb."""
    base, extra = (palette.DARK, DARK_ONLY) if mode == "dark" else (palette.LIGHT, LIGHT_ONLY)
    found = {role: base[role] for role in ROLES if role in base}
    found.update(extra)
    return found


def chosen_mode(choice: str, read_value=None) -> str:
    """The mode the window wears under the user's ``choice``: ``light`` or ``dark`` as chosen, else Windows' mode, the
    registry read only then. ``read_value`` is ``windows_mode``'s."""
    return choice if choice in ("light", "dark") else windows_mode(read_value)


def windows_mode(read_value=None) -> str:
    """``dark`` when Windows asks applications for the dark mode, else ``light``. ``read_value`` stands in for the
    registry read in tests: it returns the value of AppsUseLightTheme or raises OSError."""
    if read_value is None:
        read_value = _apps_use_light_theme
    try:
        return "light" if read_value() else "dark"
    except OSError:
        return "light"


def _apps_use_light_theme() -> int:
    try:
        import winreg
    except ImportError:  # not Windows: no such setting, so the light mode
        raise OSError("no Windows registry") from None
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
        value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
    return int(value)


def caption_colour(colour: str) -> int:
    """``colour`` (#rrggbb) as the COLORREF a title bar's colour is given to Windows in: 0x00bbggrr."""
    red, green, blue = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return red | green << 8 | blue << 16


def contrast(foreground: str, background: str) -> float:
    """The WCAG contrast ratio of two #rrggbb colours."""
    def luminance(colour: str) -> float:
        channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)
