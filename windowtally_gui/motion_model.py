"""Whether, and how, anything in the window moves: the restraint's one rule, with no toolkit.

Nothing moves at rest. A figure that changes sweeps its ring from the value shown to the new one, once (``SWEEP``
seconds, easing out), and a window at a warning or an error level pulses slowly and lightly (``PULSE``) for as long as
it stays there. Nothing else moves: no ambient motion, no motion when a window first shows its values. With Windows'
animation effects off (Settings, Accessibility, Visual effects) nothing moves at all — a change shows at once and a
level holds still, at full strength.

The views ask what to draw at a moment (``sweep_value``, ``pulse_opacity``); a clock runs only while ``moving`` says
something moves, so a window at rest runs no timer it did not run before.
"""

from __future__ import annotations

import math

SWEEP = 0.6         # seconds a ring takes to move to a new value
PULSE = 3.4         # seconds of one pulse, from full strength to its lowest and back
PULSE_LOW = 0.58    # the opacity a pulsing ring falls to at the middle of a pulse
FRAME = 0.04        # seconds between frames while a ring sweeps
PULSE_FRAME = 0.1   # seconds between frames while rings only pulse: a pulse this slow needs no more, and costs less


def eased(t: float) -> float:
    """A cubic ease-out over ``t`` from 0 to 1, held to that range: fast at first, settling into place."""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def sweep_value(start: float, end: float, elapsed: float, animate: bool) -> tuple[float, bool]:
    """The value a ring shows ``elapsed`` seconds into a move from ``start`` to ``end``, and whether it is still moving.
    Without ``animate`` (Windows' animation effects off) the ring stands at ``end`` at once."""
    if not animate or start == end or elapsed >= SWEEP:
        return end, False
    return start + (end - start) * eased(elapsed / SWEEP), True


def pulse_opacity(level: int, elapsed: float, animate: bool) -> float:
    """The opacity of a window's arc ``elapsed`` seconds into its pulse: full below a warning, and full throughout where
    nothing may move; at a warning or an error a cosine between full and ``PULSE_LOW``, full at the pulse's start."""
    if level < 1 or not animate:
        return 1.0
    phase = (elapsed % PULSE) / PULSE
    return PULSE_LOW + (1.0 - PULSE_LOW) * (1.0 + math.cos(2 * math.pi * phase)) / 2


def pulses(level: int, animate: bool) -> bool:
    """Whether a window at ``level`` pulses."""
    return animate and level >= 1


def moving(sweeping: bool, level: int, animate: bool) -> bool:
    """Whether a ring needs frames: while it sweeps, or while it pulses."""
    return animate and (sweeping or level >= 1)
