"""The history page: one self-contained HTML file — inline CSS, SVG and one short script, no external resource.

Sections: each account's standing now, the week's use by product where claude.ai reported it, its plan and how far it
is paid up, and the recommendation; the summary of
the figures most looked at over thirty days, tiles in columns of one width, wrapping onto further rows where the
width ends — a caption too long for its column wraps, and every figure of a row stands at its foot; weekly usage
over six weeks, each reset outside an account's schedule marked by its kind, and under it each weekly window's use by
product where claude.ai reported one and the weeks with such a reset; daily API-equivalent cost or daily tokens by
account over thirty days; daily cost by model family, one chart per account; tokens by kind per week over six weeks or
per month over the whole history; what the plans cost per month at their US list price, with each plan period's
API-equivalent use and the gaps between recorded periods; what a full 5-hour and weekly window held per plan over six
weeks or week by week, under the caveat that marks it a lower bound; hours when no account could be used, over six
weeks; per-account tables of sessions, models and effort over thirty days; and the same days' cost by the size of a
request's context, with the responses that wrote their context to the cache again after a pause. The summary, the
cost charts and the tables count the same thirty local days, so the summary's total is what the charts and the tables
add up to.

What a section's figures mean is no text on the page: it is the tooltip of a ? beside the section's heading
(``_h2``), and a box under the ? while Tab has it focused, as the window gives it in a hint. The capacity caveat
alone stands as text.

Where the text above says "or", the section shows one of its two views at a time (``history.SWITCH_VIEWS``), a
segmented switch in its heading choosing, as the window's does, with no script: a hidden radio button per view, which
Tab reaches and the arrow keys move, and the style sheet showing the view whose button is checked (``_switch``). The
export opens at the views the window shows.

This module is the page's markup alone: every figure and every word it shows of the history comes from the figures
layer (``history``), which the window's History view draws from too, so the two never disagree; the page chooses only
its ranges. The account cards and the recommendation are the page's own, from the standings a pass computed.

The same sections also render one span's history as the window shows it (``render_history``), the file the History
window exports: every section over that span, the cost per week where the window shows it so, and no cards or
recommendation.

Colour follows the entity, as ``history`` assigns it. The tokens are WindowTally's palette (``palette``), from which the
style sheet is written, so the window gives an account the colour this page does. Text never wears a series colour,
and every value a chart shows is also in its mark's tooltip or a table.

The page wears the window's look, a restrained dashboard's, tightened as the window's is, in a light and a dark mode it
takes from the browser (``prefers-color-scheme``) unless the document's root says one (``data-theme``): the page
ground, under a fine grid in the dark mode alone, as the window's ground lays it; cards, tiles, charts and tables as
panels with hairline edges, padded and spaced at the window's density — three quarters of a line at a panel's sides,
half a line above and below and between two panels, a line above a section's heading; figures in the words' face with
tabular digits. An account's card stands in the order of the window's card: its name and roles, its last response,
then its two windows as concentric rings from the window's geometry (``rings``) beside the two windows' names and
figures — the weekly window outside in the logo's blue, the 5-hour window inside in its green, each arc taking the
warning or the critical fill at the figures the plugin warns at (``limits.WARNING_THRESHOLDS``), its figure then
written in that level's text colour — then each window's line across the card behind its ring's dot, when it resets
and its pace, the weekly window's followed by the week's use by product, and the plan under a hairline. The page shows
no per-model window, which the window's card alone does. The card of an account a client uses is marked by a strip of
the account's colour inside its left edge; its edge stays the hairline. A card says a reading's age only once the
reading may be out of date and a plan's days left only while its renewal is near, by the window's bounds
(``limits.reading_dated``, ``limits.renewal_near``). An account's share tile draws the share as a bar in the account's
colour. Glow is on data alone and in the dark mode alone — a ring's arc, a chart's line (``charts``) — and the one
thing that moves is an arc at a warning or an error level, pulsing slowly as the window's does, and not at all where
the browser asks for reduced motion.

A table shows its headings and at most ``history.TABLE_ROWS`` rows, as the History window's tables do
(``windowtally_gui.table_view``): a longer one scrolls within its panel, its headings staying at the top and a total
row (``tr.total``) at the foot, so a long table does not lengthen the page; the style sheet does it. The page's one
script keeps a gesture of the wheel to what took its first turn, as the window does (``windowtally_gui.scroll_model``):
scrolling the page on, a table that the scroll brings under the still pointer does not take the turns that follow.
Without it the page reads the same and the wheel scrolls as the browser chooses.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import timedelta
from html import escape
from pathlib import Path
from typing import Callable, Mapping

from . import __version__, history, palette, rings
from .accounts import Account
from .billing import BillingReport, Subscription, usd_text
from .charts import (AREA, HALO_OPACITY, HALO_WIDTH, LINE_WIDTH, Axis, LineSeries, Marker, StackSeries, line_chart,
                     nice_ceiling, stacked_columns)
from .files import write_text_atomically
from .history import account_slots, when
from .ledger import Ledger
from .limits import (HISTORY_WEEKS, WEEK, AccountStanding, Recommendation, WindowStanding, reading_dated,
                     shared_reading, warning_level)
from .plan_use import plan_use
from .products import Report, shares_text
from .timeutil import local_datetime

DAILY_DAYS = 30
MAX_COLUMN_LABELS = 10   # a cost chart labels every n-th column, so no more than this many labels stand under it
UNATTRIBUTED = "var(--muted)"
RING_SIZE = 64           # a card's rings, square, in CSS pixels
GRID = 24                # CSS pixels between the page ground's lines, the window's ground's
# An arc at a warning or an error level fades to PULSE_LOW and back every PULSE_SECONDS, as the window's does
# (``windowtally_gui.motion_model``).
PULSE_SECONDS = 3.4
PULSE_LOW = 0.58
WORDS = '"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif'
# Named, never fetched: the first the reader's machine has. Figures share the words' family, each digit one width
# through ``font-variant-numeric:tabular-nums``, as the window's figures do.
FIGURES = WORDS


def _mode_tokens(colours: dict[str, str], dark: bool) -> str:
    """A mode's custom properties: the palette's tokens, then what the look lays in that mode — the opacity of the shade
    under a chart's line (``--area``) and of the glow along it (``--halo``), the glow on a ring's arc (``--glow``), and
    the page ground's grid (``--ground``), which the dark mode alone lays, as the window's ground does
    (``windowtally_gui.theme_view.GRIDDED_MODES``)."""
    look = (f"--area:{AREA[dark]}; --halo:{HALO_OPACITY}; --glow:drop-shadow(0 0 2.5px currentColor); "
            "--ground:linear-gradient(var(--page-grid) 1px,transparent 1px),"
            "linear-gradient(90deg,var(--page-grid) 1px,transparent 1px);" if dark
            else f"--area:{AREA[dark]}; --halo:0; --glow:none; --ground:none;")
    return f"{palette.css_tokens(colours)} {look}"


_CSS = (
    f"\n.windowtally {{ color-scheme: light; {_mode_tokens(palette.LIGHT, False)} }}\n"
    f'@media (prefers-color-scheme: dark) {{ :root:where(:not([data-theme="light"])) .windowtally {{ color-scheme: dark; '
    f"{_mode_tokens(palette.DARK, True)} }} }}\n"
    f':root[data-theme="dark"] .windowtally {{ color-scheme: dark; {_mode_tokens(palette.DARK, True)} }}\n'
    f".windowtally {{ font:14px/1.45 {WORDS}; background-size:{GRID}px {GRID}px; }}\n"
    f".windowtally .num, .windowtally .tile .fig, .windowtally td, .windowtally svg .tick {{ font-family:{FIGURES}; }}\n"
    f".windowtally svg .line {{ fill:none; stroke-width:{LINE_WIDTH}; stroke-linejoin:round; stroke-linecap:round; }}\n"
    f".windowtally svg .halo {{ fill:none; stroke-width:{LINE_WIDTH * HALO_WIDTH:g}; stroke-opacity:var(--halo); "
    "stroke-linejoin:round; stroke-linecap:round; }\n"
    f".windowtally svg .pulse {{ animation:windowtally-pulse {PULSE_SECONDS:g}s ease-in-out infinite; }}\n"
    f"@keyframes windowtally-pulse {{ 50% {{ opacity:{PULSE_LOW:g}; }} }}\n"
    "@media (prefers-reduced-motion: reduce) { .windowtally svg .pulse { animation:none; } }\n"
    + """html, body { margin:0; }
.windowtally { background-color:var(--page); background-image:var(--ground); color:var(--ink);
  padding:10px 15px 40px; min-height:100vh; box-sizing:border-box; }
.windowtally main { max-width:1000px; margin:0 auto; }
.windowtally h1 { font-size:22px; font-weight:600; margin:0 0 4px; }
.windowtally h2 { font-size:16px; font-weight:600; margin:20px 0 8px; }
.windowtally .sub { color:var(--ink-2); margin:0 0 10px; font-variant-numeric:tabular-nums; }
.windowtally .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:10px; }
.windowtally .card, .windowtally .panel { background:var(--surface-1); border:1px solid var(--edge); border-radius:8px; padding:10px 15px; }
.windowtally .card { position:relative; overflow:hidden; }
.windowtally .card.use::before { content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--account); }
.windowtally .card h3 { margin:0 0 2px; font-size:15px; font-weight:600; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.windowtally .swatch { width:10px; height:10px; border-radius:50%; display:inline-block; flex:none; }
.windowtally .badge { font-size:11px; font-weight:400; color:var(--ink); border:1px solid var(--edge); border-radius:4px; padding:0 6px; }
.windowtally .gauges { display:flex; gap:10px; align-items:center; margin:6px 0 4px; }
.windowtally .gauges svg { flex:none; }
.windowtally .gauges .figs { flex:1; min-width:0; }
.windowtally .row { display:grid; grid-template-columns:72px 1fr; gap:8px; align-items:baseline; margin:2px 0; }
.windowtally .row .k { color:var(--ink-2); }
.windowtally .key { display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:6px; vertical-align:1px; }
.windowtally .key.off { visibility:hidden; }
.windowtally .card .line { color:var(--ink-2); font-size:12px; margin:2px 0; padding-left:12px; text-indent:-12px; }
.windowtally .row.plan { border-top:1px solid var(--edge); margin-top:8px; padding-top:6px; }
.windowtally .num { font-size:16px; font-weight:600; font-variant-numeric:tabular-nums; }
.windowtally .num.l1 { color:var(--warning-text); } .windowtally .num.l2 { color:var(--critical-text); }
.windowtally svg .track { fill:none; stroke:var(--ring-track); }
.windowtally svg .arc { fill:none; stroke:currentColor; filter:var(--glow); }
.windowtally .note { color:var(--muted); font-size:12px; }
.windowtally .help { position:relative; display:inline-block; width:15px; height:15px; margin-left:6px;
  border:1px solid var(--baseline); border-radius:50%; color:var(--ink-2); font-size:11px; font-weight:600;
  line-height:15px; text-align:center; vertical-align:2px; cursor:help; }
.windowtally .help:focus-visible::after { content:attr(aria-label); position:absolute; z-index:2; left:0; top:20px;
  width:min(440px, 80vw); padding:6px 10px; background:var(--surface-1); border:1px solid var(--edge);
  border-radius:6px; color:var(--ink); font-size:12px; font-weight:400; line-height:1.45; text-align:left;
  white-space:normal; }
.windowtally .tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:10px; }
.windowtally .tile { background:var(--surface-1); border:1px solid var(--edge); border-radius:8px; padding:10px 15px;
  display:flex; flex-direction:column; overflow-wrap:anywhere; }
.windowtally .tile .cap { color:var(--ink-2); font-size:12px; margin-bottom:auto; }
.windowtally .tile .bar.off { visibility:hidden; }
.windowtally .tile .fig { font-size:20px; font-weight:600; font-variant-numeric:tabular-nums; }
.windowtally .tile .bar { height:3px; border-radius:2px; background:var(--ring-track); overflow:hidden; margin:4px 0 2px; }
.windowtally .tile .bar i { display:block; height:100%; border-radius:2px; }
.windowtally .rec { margin:10px 0 0; padding:8px 12px; border-left:3px solid var(--series-1); background:var(--advice); }
.windowtally .legend { display:flex; gap:16px; flex-wrap:wrap; color:var(--ink-2); font-size:12px; margin:0 0 6px; }
.windowtally .legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:-1px; }
.windowtally .legend b.ring, .windowtally .legend b.square, .windowtally .legend b.diamond { display:inline-block; width:8px; height:8px; border:2px solid var(--ink-2); margin-right:6px; vertical-align:-1px; }
.windowtally .legend b.ring { border-radius:50%; }
.windowtally .legend b.diamond { width:7px; height:7px; transform:rotate(45deg); margin:0 7px 0 1px; }
.windowtally svg.chart { width:100%; height:auto; display:block; box-sizing:border-box; background:var(--surface-1);
  border:1px solid var(--edge); border-radius:8px; }
.windowtally svg .grid { stroke:var(--grid); stroke-width:1; }
.windowtally svg .baseline { stroke:var(--baseline); stroke-width:1; }
.windowtally svg .tick { fill:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; }
.windowtally svg .marker { stroke:var(--surface-1); stroke-width:2; }
.windowtally .table-wrap { overflow:auto; }
.windowtally .panel.table-wrap { padding:0; }
.windowtally table { border-collapse:collapse; width:100%; font-size:13px; }
.windowtally th, .windowtally td { text-align:right; padding:5px 8px; border-bottom:1px solid var(--grid); white-space:nowrap; font-variant-numeric:tabular-nums; }
.windowtally th:first-child, .windowtally td:first-child, .windowtally th.l, .windowtally td.l { text-align:left; }
.windowtally td:first-child, .windowtally td.l { font-family:inherit; }
.windowtally th:first-child, .windowtally td:first-child { padding-left:15px; }
.windowtally th:last-child, .windowtally td:last-child { padding-right:15px; }
.windowtally tbody tr:last-child td { border-bottom:0; }
.windowtally th { color:var(--ink-2); font-weight:600; }
.windowtally .table-wrap thead th { position:sticky; top:0; z-index:1; background:var(--surface-1); border-bottom:0; box-shadow:inset 0 -1px var(--edge); }
.windowtally .table-wrap tr.total td { position:sticky; bottom:0; z-index:1; background:var(--surface-1); box-shadow:inset 0 1px var(--edge); }
.windowtally .switch { position:relative; }
.windowtally .switch > input { position:absolute; top:0; left:0; width:1px; height:1px; margin:0; opacity:0; }
.windowtally .switch > .view { display:none; }
.windowtally .seg { display:inline-flex; margin:0 2px 0 4px; vertical-align:1px; }
.windowtally .seg label { padding:0 10px; font-size:12px; font-weight:400; line-height:20px; color:var(--ink);
  background:var(--surface-1); border:1px solid var(--edge); cursor:pointer; }
.windowtally .seg label + label { border-left:0; }
.windowtally .seg label:first-child { border-radius:5px 0 0 5px; }
.windowtally .seg label:last-child { border-radius:0 5px 5px 0; }
.windowtally .seg label:hover { background:var(--grid); }
.windowtally .seg label.on { background:var(--advice); border-color:var(--baseline); }
"""
    # The headings and ``TABLE_ROWS`` rows of 13 px text, each row 5 px of padding above and below and a 1 px rule, and
    # room for the sideways bar a wide table adds.
    + f".windowtally .table-wrap {{ max-height:calc({history.TABLE_ROWS + 1} * (13px * 1.45 + 11px) + 17px); }}\n"
    # A switched section shows the view whose radio button is checked, the focus ring on its filled label.
    + "".join(f".windowtally .switch > input.v{i}:checked ~ .view.v{i} {{ display:block; }}\n"
              f".windowtally .switch > input.v{i}:focus-visible ~ .view.v{i} .seg label.on {{ outline:2px solid "
              "var(--series-1); outline-offset:1px; }\n"
              for i in range(max(len(views) for views in history.SWITCH_VIEWS.values()))))

# A gesture of the wheel keeps to what took its first turn, the page or a table's panel: it ends when the wheel rests
# for ``history.WHEEL_PAUSE`` or the pointer moves beyond Windows' default drag threshold from where the gesture began,
# a page being unable to read the setting. While the page holds a gesture, a turn over a panel that would scroll is
# taken from the panel and scrolls the page smoothly, the turns arriving while that scroll runs adding to where it goes;
# a panel holding one passes it to the page at its edge, and whichever holds it chooses afresh where it cannot move the
# wheel's way. Shift, Ctrl and a sideways turn stay the browser's.
_SCRIPT = ("""(() => {
const PAUSE = %d, SLOP = 4, GLIDE = 400, page = document.scrollingElement;
let owner = null, at = 0, x = 0, y = 0, aim = null, aimed = 0;
const room = (el, dy) => dy < 0 ? el.scrollTop > 0 : el.scrollTop + el.clientHeight < el.scrollHeight - 1;
addEventListener("wheel", (e) => {
  if (e.ctrlKey || e.shiftKey || !e.deltaY || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
  const panel = e.target instanceof Element ? e.target.closest(".table-wrap") : null;
  const ended = !owner || !owner.isConnected || e.timeStamp - at > PAUSE
    || Math.abs(e.clientX - x) > SLOP || Math.abs(e.clientY - y) > SLOP;
  if (ended) { x = e.clientX; y = e.clientY; }
  if (ended || !room(owner, e.deltaY)) owner = panel && room(panel, e.deltaY) ? panel : page;
  at = e.timeStamp;
  if (owner !== page || !panel || panel.scrollHeight <= panel.clientHeight) { aim = null; return; }
  e.preventDefault();
  const unit = e.deltaMode === 1 ? parseFloat(getComputedStyle(document.body).lineHeight) || 16
    : e.deltaMode === 2 ? page.clientHeight : 1;
  const from = aim !== null && e.timeStamp - aimed < GLIDE ? aim : page.scrollTop;
  aim = Math.max(0, Math.min(page.scrollHeight - page.clientHeight, from + e.deltaY * unit));
  aimed = e.timeStamp;
  page.scrollTo({top: aim, behavior: "smooth"});
}, {passive: false});
})();""" % round(history.WHEEL_PAUSE * 1000))


@dataclass(frozen=True)
class AccountView:
    uuid: str | None        # None: use with no known account
    label: str
    color: str


def _css(token: str) -> str:
    return f"var(--{token})"


def account_views(ledger: Ledger, accounts: dict[str, Account]) -> list[AccountView]:
    """Accounts in the order they were first seen, each with its colour slot."""
    return [AccountView(a.uuid, a.label, _css(token)) for a, token in account_slots(ledger, accounts)]


def _ring_window(w: WindowStanding) -> tuple[float, int]:
    """A window as its ring takes it: how full it is, 0 to 1, and its warning level; nothing filled without a figure."""
    return (0.0 if w.percent is None else w.percent / 100.0), warning_level(w.kind, w.percent)


def _ring_fill(ring: rings.Ring) -> str:
    return rings.fill(ring, "var(--warning)", "var(--critical)")


def _rings(s: AccountStanding) -> str:
    """The account's two windows as concentric rings (``rings``), as SVG: each ring a track and, where its window is
    used at all, an arc from the top, clockwise; an arc at a warning or an error level pulses. The figures stand in
    words beside it, so the picture is hidden from a screen reader."""
    five_hour = None if s.five_hour.state == "no_limit" else _ring_window(s.five_hour)
    centre = RING_SIZE / 2
    parts = []
    for ring in rings.rings(RING_SIZE, _ring_window(s.weekly), five_hour):
        circle = f'cx="{centre:g}" cy="{centre:g}" r="{ring.radius:.2f}" stroke-width="{ring.width:.2f}"'
        parts.append(f'<circle class="track" {circle}/>')
        if ring.fraction > 0:
            around = 2 * math.pi * ring.radius
            parts.append(f'<circle class="arc{" pulse" if ring.level else ""}" {circle} '
                         f'stroke-dasharray="{around * ring.fraction:.2f} {around:.2f}" '
                         f'transform="rotate(-90 {centre:g} {centre:g})" style="color:{_ring_fill(ring)}"/>')
    return (f'<svg class="rings" viewBox="0 0 {RING_SIZE} {RING_SIZE}" width="{RING_SIZE}" height="{RING_SIZE}" '
            f'aria-hidden="true">{"".join(parts)}</svg>')


def _window(name: str, w: WindowStanding, now: float, reset_estimated: bool | None = None,
            say_reading: bool = False) -> tuple[str, str]:
    """A window as the card shows it: its row beside the rings — a dot in its ring's colour, its name, its figure — and
    its line across the card, behind the same dot — when it resets and its pace — or no line where there is nothing to
    say. ``reset_estimated`` overrides ``w.estimated`` for the reset time alone: a reset time is approximate only when
    it was inferred (a weekly one, when its schedule was), whatever the figure's estimate. ``say_reading`` adds the
    moment of the reading the figure rests on, which the card decides (``_cards``)."""
    approx = "≈" if w.estimated else ""
    reset_approx = approx if reset_estimated is None else ("≈" if reset_estimated else "")
    if w.state == "no_limit":
        # No figure and no ring: the window says the account has no such limit, and nothing more, the place of its
        # ring's dot kept empty.
        return (f'<div class="row"><span class="k"><i class="key off"></i>{escape(name)}</span><span><b>no limit</b>'
                '</span></div>', _line("", "this account has no 5-hour limit"))
    level = warning_level(w.kind, w.percent)
    if w.state == "not_started":
        figure, detail = "<b>not started</b>", ""
    elif w.state == "unknown" or w.percent is None:
        figure = "<b>unknown</b>" if w.state == "unknown" else "<b>running</b>"
        detail = f"resets {reset_approx}{when(w.resets_at, now)}" if w.resets_at else "no reading yet"
    else:
        figure = f'<b class="num{f" l{level}" if level else ""}">{escape(approx)}{w.percent:.0f}%</b>'
        detail = f"resets {reset_approx}{when(w.resets_at, now)}" if w.resets_at else "reset time unknown"
        if w.exhausts_at:
            detail += f" · full at this pace {when(w.exhausts_at, now)}"
    if say_reading:
        detail += (" · " if detail else "") + f"reading {when(w.as_of, now)}"
    colour = rings.level_colour(rings.rest_colour(w.kind), level, "var(--warning)", "var(--critical)")
    key = f'<i class="key" style="background:{colour}"></i>'
    return (f'<div class="row"><span class="k">{key}{escape(name)}</span><span>{figure}</span></div>',
            _line(colour, detail) if detail else "")


def _line(colour: str, words: str) -> str:
    """One of the card's lines under the gauges, behind its gauge's dot in ``colour``, or the dot's place kept empty
    where ``colour`` is empty, so every line's words start at one place."""
    key = f'<i class="key" style="background:{colour}"></i>' if colour else '<i class="key off"></i>'
    return f'<div class="line">{key}{escape(words)}</div>'


def _plan_row(subscription: Subscription | None, now: float) -> str:
    """The card's plan line, under a hairline; its days left only while the renewal is near, and the profile only
    where it says something else."""
    if subscription is None:
        return ""
    # An account not wholly read says so in its plan's words; its profile was not compared.
    note = "" if subscription.profile_check in ("matches", "unread") else history.profile_text(subscription, now)
    return (f'<div class="row plan"><span class="k">Plan</span><span>{_plan_text(subscription, near_only=True)}'
            + (f'<div class="note">{escape(note)}</div>' if note else "") + "</span></div>")


def _products_line(report: Report | None, now: float) -> str:
    """The week's use by product, after the weekly window's line, as the window's card says it; nothing where there is
    none."""
    if report is None or not report.used:
        return ""
    return _line("", f"by product {when(report.as_of, now)}: {shares_text(report.used)}")


def _cards(standings: list[AccountStanding], views: dict[str | None, AccountView], recommendation: Recommendation,
           now: float, billing: BillingReport | None = None, by_product: dict[str, Report] | None = None) -> str:
    cards = []
    for s in standings:
        view = views.get(s.account.uuid)
        subscription = billing.for_account(s.account.uuid) if billing and billing.configured else None
        badges = []
        if s.is_desktop:
            badges.append("desktop app")
        if s.is_cli:
            badges.append("CLI")
        if recommendation.account_uuid == s.account.uuid:
            badges.append("use next")
        if subscription and subscription.renew_soon:
            badges.append("renew soon")
        badge_html = "".join(f'<span class="badge">{escape(b)}</span>' for b in badges)

        def dated(w: WindowStanding) -> bool:
            # A window never read has no moment to say: its line says ``no reading yet`` where it has no reset either.
            return w.as_of is not None and reading_dated(w.as_of, s.last_activity, now)

        # One reading is said once, after the last response; readings that differ each on their window's line.
        shared = shared_reading(s.five_hour.state, s.five_hour.as_of, s.weekly.as_of)
        five_hour = _window("5-hour", s.five_hour, now, reset_estimated=not s.five_hour.reset_exact,
                            say_reading=not shared and dated(s.five_hour))
        weekly = _window("Weekly", s.weekly, now, reset_estimated=not (s.anchor and s.anchor.exact),
                         say_reading=not shared and dated(s.weekly))
        weekly = (weekly[0], weekly[1] + _products_line((by_product or {}).get(s.account.uuid), now))
        # The weekly window first on an account with no 5-hour limit: the one limit it has.
        windows = [weekly, five_hour] if s.five_hour.state == "no_limit" else [five_hour, weekly]
        colour = view.color if view else UNATTRIBUTED
        reading = f" · reading {when(s.weekly.as_of, now)}" if shared and dated(s.weekly) else ""
        # The window's card's order: the title, the heading's words, the rings beside the two windows' figures, each
        # window's line across the card, the plan under a hairline.
        cards.append(
            f'<div class="card{" use" if s.is_desktop or s.is_cli else ""}" style="--account:{colour}">'
            f'<h3><span class="swatch" style="background:{colour}"></span>'
            f'{escape(s.account.label)}{badge_html}</h3>'
            f'<div class="note">last response {escape(when(s.last_activity, now))}{escape(reading)}</div>'
            f'<div class="gauges">{_rings(s)}<div class="figs">{"".join(row for row, _ in windows)}</div></div>'
            + "".join(line for _, line in windows)
            + _plan_row(subscription, now) + "</div>")
    rec = f'<p class="rec"><b>Next:</b> {escape(recommendation.reason)}</p>'
    return f'<div class="cards">{"".join(cards)}</div>{rec}'


def _help(hint: str) -> str:
    """The ? beside a heading whose tooltip is ``hint``; nothing for no hint."""
    words = escape(hint)
    return f' <span class="help" tabindex="0" title="{words}" aria-label="{words}">?</span>' if hint else ""


def _h2(text: str, hint: str = "") -> str:
    """A section's heading; ``hint``, what its figures mean, is the tooltip of a ? beside it, never text on the page."""
    return f"<h2>{escape(text)}{_help(hint)}</h2>"


@dataclass(frozen=True)
class _View:
    """One of a switched section's views: its word on the switch (``history.SWITCH_VIEWS``), its heading's words before
    and after the switch and its hint, and its markup."""
    choice: str
    before: str
    body: str
    hint: str = ""
    after: str = ""


def _switch(key: str, views: list[_View], shown: str) -> str:
    """A section shown in one of its views at a time, with no script: a radio button per view, unseen but reached by Tab
    and moved by the arrow keys, and in each view's heading the switch as labels of those buttons, its own filled; the
    style sheet shows the view whose button is checked, ``shown`` at first."""
    name = f"switch-{key}"
    inputs = "".join(f'<input type="radio" name="{name}" id="{name}-{i}" class="v{i}" aria-label="{escape(view.choice)}"'
                     + (" checked" if view.choice == shown else "") + ">" for i, view in enumerate(views))
    panes = []
    for i, view in enumerate(views):
        labels = "".join(f'<label for="{name}-{j}"' + (' class="on"' if j == i else "") + f">{escape(other.choice)}</label>"
                         for j, other in enumerate(views))
        panes.append(f'<div class="view v{i}"><h2>{escape(view.before)} <span class="seg">{labels}</span>'
                     f"{escape(view.after)}{_help(view.hint)}</h2>{view.body}</div>")
    return f'<div class="switch">{inputs}{"".join(panes)}</div>'


def _legend(items: list[tuple[str, str]]) -> str:
    return '<div class="legend">' + "".join(
        f'<span><i style="background:{color}"></i>{escape(label)}</span>' for label, color in items) + "</div>"


LEGEND_MARKS = {"disc": "ring", "diamond": "diamond", "square": "square"}   # a marker's shape: its legend mark's class


def _weekly_chart(usage: history.WeeklyUsage, empty: str = "No weekly readings yet.") -> str:
    series = [LineSeries(line.entity.label, _css(line.entity.token), list(line.points), break_after=history.LINE_BREAK)
              for line in usage.lines]
    markers = [Marker(r.after, r.value, _css(r.entity.token), history.reset_words(r), history.RESET_MARKS[r.kind])
               for r in usage.resets]
    if not series:
        return f'<p class="note">{escape(empty)}</p>'
    chart = line_chart(series, x_range=(usage.start, usage.end), y_range=(0.0, 100.0),
                       x_axis=Axis(list(history.time_ticks(usage.start, usage.end))),
                       y_axis=Axis([(0, "0%"), (25, "25%"), (50, "50%"), (75, "75%"), (100, "100%")]),
                       markers=markers, title="Weekly use by account")
    legend = _legend([(s.label, s.color) for s in series])
    marks = "".join(f'<span><b class="{LEGEND_MARKS[mark]}"></b>{escape(words)}</span>'
                    for words, mark in history.reset_legend(usage))
    if marks:
        legend = legend.replace("</div>", f"{marks}</div>", 1)
    return legend + chart


def _resets(table: history.ResetTable) -> str:
    """The weeks with a reset outside the schedule, under their heading, which explains them in its hint."""
    head = _h2(history.RESETS_HEADING, history.RESETS_NOTE)
    if not table.rows:
        return head + f'<p class="note">{escape(history.RESETS_NONE)}</p>'
    heads = "".join(f'<th class="l">{escape(c)}</th>' if i < 2 else f"<th>{escape(c)}</th>"
                    for i, c in enumerate(table.columns))
    rows = "".join("<tr>" + "".join(f'<td class="l">{escape(c)}</td>' if i < 2 else f"<td>{escape(c)}</td>"
                                    for i, c in enumerate(row)) + "</tr>" for row in table.rows)
    return (head + f'<div class="panel table-wrap"><table><thead><tr>{heads}</tr></thead><tbody>{rows}</tbody>'
            "</table></div>")


def _stack_series(stacks: tuple[history.Stack, ...]) -> list[StackSeries]:
    return [StackSeries(s.label, _css(s.token), list(s.values)) for s in stacks]


def _summary(figures: history.Summary, heading: str = f"{history.SUMMARY_HEADING}, last {DAILY_DAYS} days") -> str:
    def bar(t: history.Tile) -> str:
        """An account's share as a bar in its colour, under the figure that says it; every tile keeps the bar's room,
        so the figures of a row stand on one line."""
        if t.share is None:
            return '<div class="bar off"></div>'
        return f'<div class="bar"><i style="width:{max(0.0, min(1.0, t.share)) * 100:.0f}%;background:{_css(t.token)}"></i></div>'

    tiles = "".join(f'<div class="tile"><div class="cap">{escape(t.caption)}</div><div class="fig">{escape(t.figure)}'
                    f"</div>{bar(t)}</div>" for t in history.summary_tiles(figures))
    return f'<h2>{escape(heading)}</h2><div class="tiles">{tiles}</div>'


def _stacked(columns: tuple[history.Column, ...], stacks: list[StackSeries], figure: Callable[[float], str], title: str,
             ticks: tuple[float, ...] = (0, 0.25, 0.5, 0.75, 1.0), height: int = 240) -> str:
    """The stacks' legend and their stacked columns, ``figure`` writing a value at each of ``ticks``, the value axis's
    fractions; about ten columns labelled, whatever their number."""
    labels = [history.column_label(column) for column in columns]
    y_max = nice_ceiling(max(sum(s.values[i] for s in stacks) for i in range(len(labels))))
    return (_legend([(s.label, s.color) for s in stacks])
            + stacked_columns(labels, stacks, y_axis=Axis([(y_max * f, figure(y_max * f)) for f in ticks]), y_max=y_max,
                              column_titles=[history.column_title(column) for column in columns], value_format=figure,
                              height=height, title=title, label_every=-(-len(labels) // MAX_COLUMN_LABELS)))


def _columns(costs: history.Costs, use: history.TokenUse, by_week: bool = False,
             chosen: Mapping[str, str] | None = None, no_cost: str = f"No priced responses in the last {DAILY_DAYS} days.",
             no_tokens: str = f"No responses in the last {DAILY_DAYS} days.") -> str:
    """The cost chart or the token chart, a column per day, or per week from Monday where ``by_week``, a switch
    choosing; then each account's cost by model family, under whichever is shown."""
    unit = "week" if by_week else "day"
    cost, tokens = history.SWITCH_VIEWS[history.COLUMNS_SWITCH]
    stacks, token_stacks = _stack_series(costs.accounts), _stack_series(use.accounts)
    views = [_View(cost, history.cost_heading(unit),
                   _stacked(costs.columns, stacks, history.usd, f"API-equivalent cost per {unit} by account")
                   if stacks else f'<p class="note">{escape(no_cost)}</p>',
                   history.BY_WEEK_NOTE if by_week and stacks else ""),
             _View(tokens, history.tokens_heading(unit),
                   _stacked(use.columns, token_stacks, history.count, f"Tokens per {unit} by account")
                   if token_stacks else f'<p class="note">{escape(no_tokens)}</p>', history.TOKENS_NOTE)]
    parts = [_switch(history.COLUMNS_SWITCH, views, history.shown_view(history.COLUMNS_SWITCH, chosen or {}))]
    for entry in costs.families:
        parts += [_h2(history.family_heading(entry.entity.label)),
                  _stacked(costs.columns, _stack_series(entry.families), history.usd,
                           f"{entry.entity.label} cost per {unit} by model family", (0, 0.5, 1.0), 180)]
    return "".join(parts)


def _product_table(table: history.ProductTable) -> str:
    """The weekly windows' use by product, under the weekly chart; nothing where claude.ai reported none."""
    if not table.rows:
        return ""
    heads = history.product_columns(table)

    def words(index: int) -> bool:   # the account, the window's start and the moment reported; the rest are figures
        return index < 2 or index == len(heads) - 1

    head = "".join(f'<th class="l">{escape(h)}</th>' if words(i) else f"<th>{escape(h)}</th>" for i, h in enumerate(heads))
    rows = ["<tr>" + "".join(f'<td class="l">{escape(c)}</td>' if words(i) else f"<td>{escape(c)}</td>"
                             for i, c in enumerate(history.product_cells(table, row))) + "</tr>" for row in table.rows]
    return (f'<div class="panel table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody>'
            "</table></div>")


def _weekly(heading: str, usage: history.WeeklyUsage, products: history.ProductTable, resets: history.ResetTable,
            empty: str) -> str:
    """The weekly chart under ``heading``, then the use by product, which the heading's hint explains where it
    stands, then the resets outside the schedule."""
    return (_h2(heading, history.PRODUCTS_NOTE if products.rows else "") + _weekly_chart(usage, empty)
            + _product_table(products) + _resets(resets))


def _token_table(table: history.TokenTable, first: str) -> str:
    """``first`` heads the period column; the last row, the range in all, is set in bold."""
    if not table.rows:
        return f'<p class="note">{escape(history.NO_TOKENS_NOTE)}</p>'
    head = "".join(f"<th>{escape(label)}</th>" for label in table.labels + history.TOKEN_COLUMNS)
    rows = []
    for index, row in enumerate(table.rows):
        texts = (row.period,) + history.token_cells(row)
        total = index == len(table.rows) - 1
        texts = tuple(f"<b>{escape(text)}</b>" if total else escape(text) for text in texts)
        rows.append(("<tr class=\"total\">" if total else "<tr>") + f'<td class="l">{texts[0]}</td>'
                    + "".join(f"<td>{text}</td>" for text in texts[1:]) + "</tr>")
    return (f'<div class="panel table-wrap"><table><thead><tr><th class="l">{escape(first)}</th>{head}</tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def _token_tables(use: history.TokenUse, by_week: bool = False, chosen: Mapping[str, str] | None = None,
                  weeks: str = "", months: str = "") -> str:
    """The tokens by week or by month, a switch choosing, ``weeks`` and ``months`` following the switch in each view's
    heading."""
    week, month = history.SWITCH_VIEWS[history.TOKEN_TABLES_SWITCH]
    return _switch(history.TOKEN_TABLES_SWITCH,
                   [_View(week, history.TOKENS_BY, _token_table(use.weeks, "Week"), after=weeks),
                    _View(month, history.TOKENS_BY, _token_table(use.months, "Month"), after=months)],
                   history.shown_view(history.TOKEN_TABLES_SWITCH, chosen or {}, by_week))


def _plan_text(s: Subscription, near_only: bool = False) -> str:
    """The plan in effect today and how far it is paid up, as HTML; ``near_only`` as ``history.plan_words`` takes it."""
    plan, rest = history.plan_words(s, near_only)
    return f"<b>{escape(plan)}</b>{escape(rest)}"


_REMINDER_OFF = "off; <code>python -m windowtally bills remind --days 3</code> turns it on"
_NO_BILLS = ("No bills recorded; <code>python -m windowtally bills add</code> records one, <code>python -m windowtally "
             "bills source --manifest PATH</code> reads an archive's manifest.")


def _summary_table(subscriptions: history.Subscriptions, profile: bool = True, reminder_off: str = _REMINDER_OFF) -> str:
    """The plans today; ``profile`` adds each account's profile check, which only a pass's standings carry.
    ``reminder_off`` is markup, the page's naming the command line."""
    rows = []
    for row in subscriptions.summary:
        s = row.subscription
        rows.append(
            f'<tr><td class="l"><span class="swatch" style="background:{_css(row.token)}"></span> '
            f'{escape(s.label)}</td><td class="l">{_plan_text(s)}{" · renew soon" if s.renew_soon else ""}</td>'
            + (f'<td class="l">{escape(row.profile)}</td>' if profile else "")
            + f'<td>{row.bills:,}</td><td class="l">{escape(row.last_bill)}</td></tr>')
    days = subscriptions.reminder_days
    reminder = escape(history.reminder_text(days)) if days else history.reminder_text(None, reminder_off)
    return ('<div class="panel table-wrap"><table><thead><tr><th class="l">Account</th><th class="l">Plan today</th>'
            + ('<th class="l">Profile</th>' if profile else "")
            + '<th>Bills</th><th class="l">Last bill</th></tr></thead><tbody>'
            + "".join(rows) + f'</tbody></table></div><p class="note">{reminder}</p>')


def _cost_tables(figures: history.CostFigures) -> str:
    """The month-by-month chart and table of the plans' cost at list price."""
    maybe = history.money_cell
    months = list(figures.months)
    stacks = _stack_series(figures.stacks)
    parts = [_h2(history.PLAN_COST_HEADING, history.COST_NOTE)]
    if stacks:
        totals = [sum(s.values[i] for s in stacks) for i in range(len(months))]
        y_max = nice_ceiling(max(totals))
        ticks = Axis([(y_max * f, history.money_tick(y_max * f)) for f in (0, 0.25, 0.5, 0.75, 1.0)])
        every = 3 if len(months) > 18 else 2 if len(months) > 9 else 1
        parts += [_legend([(s.label, s.color) for s in stacks]),
                  stacked_columns([history.month_label(m) for m in months], stacks, y_axis=ticks, y_max=y_max,
                                  column_titles=months, value_format=usd_text, label_every=every,
                                  title="Plans' cost per month by account at list price")]
    head = "".join(f"<th>{escape(label)}</th><th>{escape(label)} per day</th>" for label in figures.labels)
    rows = []
    for row in figures.cost_months:
        cells = "".join(f"<td>{maybe(cell.cost)}</td><td>{maybe(cell.per_day)}</td>" for cell in row.cells)
        rows.append(f"<tr><td>{row.month}</td>{cells}<td>{maybe(row.total)}</td>"
                    f"<td>{row.days}</td><td>{maybe(row.per_day)}</td></tr>")
    total_cells = "".join(f"<td><b>{usd_text(cell.cost)}</b></td><td>{maybe(cell.per_day)}</td>"
                          for cell in figures.totals)
    parts.append(
        '<div class="panel table-wrap"><table><thead><tr><th class="l">Month</th>' + head
        + "<th>All accounts</th><th>Days with a plan</th><th>Per day</th></tr></thead><tbody>" + "".join(rows)
        + f'<tr class="total"><td class="l"><b>In all</b></td>{total_cells}<td><b>{usd_text(figures.all_cost)}</b></td>'
          f"<td>{figures.all_days}</td><td>{maybe(figures.all_per_day)}</td></tr>"
          "</tbody></table></div>")
    return "".join(parts)


def _periods_table(periods: tuple[history.PeriodRow, ...]) -> str:
    if not periods:
        return ""
    rows = [f'<tr><td class="l">{escape(p.label)}</td><td class="l">{escape(p.bill)}</td>'
            f'<td class="l">{escape(p.plan)}</td><td class="l">{escape(p.began)}</td>'
            f'<td class="l">{escape(p.in_effect)}</td><td>{escape(p.list_price)}</td><td>{escape(p.api)}</td></tr>'
            for p in periods]
    return (_h2("Plan periods", history.PERIODS_NOTE)
            + '<div class="panel table-wrap"><table><thead><tr><th class="l">Account</th><th class="l">Bill</th>'
            '<th class="l">Plan</th><th class="l">How it began</th><th class="l">In effect</th><th>At list price</th>'
            "<th>API-equivalent in effect</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def _gaps_table(subscriptions: history.Subscriptions) -> str:
    rows = [f'<tr><td class="l">{escape(g.label)}</td><td>{g.start.isoformat()}</td>'
            f'<td>{g.until.isoformat()}</td><td>{g.days}</td><td class="l">{escape(g.covered)}</td></tr>'
            for g in subscriptions.gaps]
    summary = "" if subscriptions.coverage is None else f'<p class="note">{escape(subscriptions.coverage)}</p>'
    if not rows:
        return f'{_h2(history.GAPS_HEADING)}<p class="note">{history.GAPS_NONE[subscriptions.unread]}</p>' + summary
    return (_h2(history.GAPS_HEADING)
            + '<div class="panel table-wrap"><table><thead><tr><th class="l">Account</th><th>From</th><th>Until</th>'
            '<th>Days</th><th class="l">Covered by another</th></tr></thead><tbody>' + "".join(rows)
            + "</tbody></table></div>" + summary)


def _subscriptions(subscriptions: history.Subscriptions | None, window: bool = False) -> str:
    """``window``: in the History window's words, which name its buttons, and without the profile check it does not
    read; otherwise in the page's, which name the command line."""
    if subscriptions is None:
        return ""
    if not subscriptions.configured:
        return f'<h2>Subscriptions</h2><p class="note">{escape(history.NO_BILLS_NOTE) if window else _NO_BILLS}</p>'
    table = (_summary_table(subscriptions, profile=False, reminder_off="off") if window
             else _summary_table(subscriptions))
    unread = f'<p class="note">{escape(history.UNREAD_NOTE)}</p>' if subscriptions.unread else ""
    return ("<h2>Subscriptions</h2>" + table + unread
            + ("" if subscriptions.costs is None else _cost_tables(subscriptions.costs))
            + _periods_table(subscriptions.periods) + _gaps_table(subscriptions))


def _capacity(capacity: history.Capacity, period: str = ", last six weeks",
              no_weeks: str = "No readings in the last six weeks measure a window.",
              chosen: Mapping[str, str] | None = None) -> str:
    """What a full window held, by plan or by week, a switch choosing; in either view the caveat first, in the ink of
    the page's lead lines rather than a note's grey, so it is read before the figures it qualifies; how it is counted
    is the heading's hint."""
    if not capacity.known:
        return _h2(history.CAPACITY_HEADING + period) + f'<p class="note">{escape(history.CAPACITY_NO_BILLS)}</p>'
    windows = escape(history.CAPACITY_WINDOWS)
    five, weekly = (escape(c) for c in history.CAPACITY_COLUMNS)
    caveat = f'<p class="sub">{escape(history.CAPACITY_CAVEAT)}</p>'
    plans = "".join(f'<tr><td class="l">{escape(p.plan)}</td><td>{escape(p.five_hour)}</td><td>{escape(p.weekly)}</td>'
                    f'<td>{escape(p.windows)}</td><td class="l">{escape(p.held_by)}</td></tr>' for p in capacity.plans)
    plans = (f'<div class="panel table-wrap"><table><thead><tr><th class="l">Plan</th><th>{five}</th>'
             f'<th>{weekly}</th><th>{windows}</th><th class="l">Held by</th></tr></thead><tbody>' + plans
             + "</tbody></table></div>")
    if capacity.weeks:
        weeks = "".join(f'<tr><td class="l">week of {w.monday.isoformat()}</td><td class="l">{escape(w.plan)}</td>'
                        f"<td>{escape(w.five_hour)}</td><td>{escape(w.weekly)}</td><td>{escape(w.windows)}</td></tr>"
                        for w in capacity.weeks)
        weeks = ('<div class="panel table-wrap"><table><thead><tr><th class="l">Week</th><th class="l">Plan</th>'
                 f"<th>{five}</th><th>{weekly}</th><th>{windows}</th></tr></thead><tbody>"
                 + weeks + "</tbody></table></div>")
    else:
        weeks = f'<p class="note">{escape(no_weeks)}</p>'
    by_plan, by_week = history.SWITCH_VIEWS[history.CAPACITY_SWITCH]
    return _switch(history.CAPACITY_SWITCH,
                   [_View(by_plan, history.CAPACITY_BY, caveat + plans, history.CAPACITY_NOTE, period),
                    _View(by_week, history.CAPACITY_BY, caveat + weeks, history.CAPACITY_NOTE, period)],
                   history.shown_view(history.CAPACITY_SWITCH, chosen or {}))


def _blocked_table(weeks: tuple[history.ExhaustedWeek, ...]) -> str:
    """The hours with every account exhausted, under their heading, which explains them in its hint."""
    rows = [f"<tr><td>week of {escape(week.monday.isoformat())}</td><td>{escape(history.exhausted_text(week))}</td></tr>"
            for week in weeks]
    return (_h2(history.EXHAUSTED_HEADING, history.EXHAUSTED_NOTE)
            + '<div class="panel table-wrap"><table><thead><tr><th>Week</th>'
            f'<th>{escape(history.EXHAUSTED_COLUMN)}</th></tr></thead><tbody>' + "".join(rows)
            + "</tbody></table></div>")


def _usage_tables(tables: history.UsageTables, period: str = f" (last {DAILY_DAYS} days)") -> str:
    count, usd = history.count, history.usd
    model_rows = "".join(
        f'<tr><td class="l">{escape(r.label)}</td><td class="l">{escape(r.model)}</td>'
        f"<td>{r.responses:,}</td><td>{r.sessions:,}</td><td>{count(r.input)}</td><td>{count(r.output)}</td>"
        f"<td>{count(r.thinking)}</td><td>{count(r.cache_read)}</td><td>{count(r.cache_write)}</td>"
        f"<td>{usd(r.cost or 0.0)}{'' if r.cost is not None else ' (unpriced)'}</td></tr>" for r in tables.models)
    effort_rows = "".join(
        f'<tr><td class="l">{escape(r.label)}</td><td class="l">{escape(r.effort)}</td>'
        f"<td>{r.responses:,}</td><td>{count(r.output)}</td><td>{usd(r.cost or 0.0)}</td></tr>" for r in tables.efforts)
    session_rows = "".join(
        f'<tr><td class="l">{escape(r.label)}</td><td>{r.sessions:,}</td><td>{r.cli:,}</td>'
        f"<td>{r.prompts:,}</td><td>{r.agents:,}</td><td>{r.agent_share:.0f}%</td></tr>" for r in tables.sessions)
    context_rows = ""
    for index, row in enumerate(tables.context):                 # the last row, "In all", is set in bold
        total = index == len(tables.context) - 1
        texts = tuple(f"<b>{escape(t)}</b>" if total else escape(t) for t in history.context_cells(row))
        context_rows += (('<tr class="total">' if total else "<tr>") + f'<td class="l">{texts[0]}</td>'
                         + "".join(f"<td>{t}</td>" for t in texts[1:]) + "</tr>")
    context_head = "".join(f'<th class="l">{escape(c)}</th>' if j == 0 else f"<th>{escape(c)}</th>"
                           for j, c in enumerate(history.CONTEXT_COLUMNS))
    return (
        f"<h2>Sessions{escape(period)}</h2>"
        '<div class="panel table-wrap"><table><thead><tr><th>Account</th><th>Sessions</th><th>of them CLI</th>'
        "<th>Prompts</th><th>Subagents</th><th>Subagent cost share</th></tr></thead><tbody>"
        + session_rows + "</tbody></table></div>"
        f"<h2>Models{escape(period)}</h2>"
        '<div class="panel table-wrap"><table><thead><tr><th>Account</th><th class="l">Model</th><th>Responses</th>'
        "<th>Sessions</th><th>Input</th><th>Output</th><th>of it thinking</th><th>Cache read</th><th>Cache write</th>"
        "<th>API-equivalent</th></tr></thead><tbody>" + model_rows + "</tbody></table></div>"
        f"<h2>Effort{escape(period)}</h2>"
        '<div class="panel table-wrap"><table><thead><tr><th>Account</th><th class="l">Effort</th><th>Responses</th>'
        "<th>Output</th><th>API-equivalent</th></tr></thead><tbody>" + effort_rows + "</tbody></table></div>"
        + _h2(history.CONTEXT_HEADING + period, history.CONTEXT_NOTE)
        + f'<div class="panel table-wrap"><table><thead><tr>{context_head}</tr></thead><tbody>' + context_rows
        + "</tbody></table></div>"
        + f'<p class="note">{escape(history.rewrite_text(tables.rewrites))}</p>')


def _coverage(items: tuple[str, ...]) -> str:
    return _h2("Coverage", history.COVERAGE_NOTE) + "<ul>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>"


def render_dashboard(ledger: Ledger, accounts: dict[str, Account], standings: list[AccountStanding],
                     recommendation: Recommendation, now: float | None = None, errors: list[str] | None = None,
                     billing: BillingReport | None = None, by_product: dict[str, Report] | None = None) -> str:
    """``by_product`` is each account's current report of the week's use by product (``products.current_reports``),
    which the cards show as status.json gives it to the window's."""
    now = time.time() if now is None else now
    entities = history.entities(ledger, accounts)
    by_uuid: dict[str | None, AccountView] = {e.uuid: AccountView(e.uuid, e.label, _css(e.token)) for e in entities}
    today = local_datetime(now).date()
    first = today - timedelta(days=DAILY_DAYS - 1)
    costs = history.daily_costs(ledger, entities, first, today)
    tokens = history.token_use(ledger, entities, (first, today),
                               (local_datetime(now - HISTORY_WEEKS * WEEK).date(), today),
                               (history.first_day("all", ledger, today), today), False)
    six_weeks = now - HISTORY_WEEKS * WEEK
    since = history.local_midnight(first).timestamp()
    uses = plan_use(ledger, history.uses_start(billing, min(since, six_weeks)), now)
    figures = history.summary(ledger, accounts, entities, costs, billing, first, now, tokens=tokens.total,
                              use=uses.between(since, now))
    body = (
        f'<h1>WindowTally</h1><p class="sub">Generated {escape(history.stamp(now))} '
        f"· WindowTally {escape(__version__)}</p>"
        + _cards(standings, by_uuid, recommendation, now, billing, by_product)
        + _summary(figures)
        + _weekly(f"{history.WEEKLY_HEADING}, last six weeks",
                  history.weekly_usage(ledger, entities, six_weeks, now, uses),
                  history.product_table(ledger, entities, six_weeks, now),
                  history.reset_table(entities, uses, six_weeks, now), "No weekly readings yet.")
        + _columns(costs, tokens)
        + _token_tables(tokens, weeks=", last six weeks", months=", whole history")
        + _subscriptions(history.subscriptions(billing, entities, now, uses))
        + _capacity(history.plan_capacity(ledger, entities, billing, six_weeks, now, uses))
        + _blocked_table(history.exhausted_weeks(ledger, accounts.values(), now - HISTORY_WEEKS * WEEK, now))
        + _usage_tables(history.usage_tables(ledger, entities, history.local_midnight(first).timestamp()))
        + _coverage(history.coverage(ledger, accounts, now, errors or [], billing)))
    return _document("WindowTally", body)


def render_history(h: history.History, chosen: Mapping[str, str] | None = None) -> str:
    """The history over the span the window shows, as the window shows it: the same sections in the same order, every
    one over the span but the subscriptions, each switch at the view ``chosen`` names as the window's does, and no
    account cards or recommendation, which are the live window's."""
    body = (
        f"<h1>WindowTally — history</h1><p class=\"sub\">{escape(h.span.label)} from "
        f"{escape(history.day_text(h.first))} · as of {escape(history.stamp(h.now))} "
        f"· WindowTally {escape(__version__)}</p>"
        + _summary(h.summary, history.SUMMARY_HEADING)
        + _weekly(history.WEEKLY_HEADING, h.weekly, h.products, h.resets, history.SPAN_NO_WEEKLY)
        + _columns(h.costs, h.tokens, h.by_week, chosen, history.SPAN_NO_COST, history.SPAN_NO_TOKENS)
        + _token_tables(h.tokens, h.by_week, chosen)
        + _subscriptions(h.subscriptions, window=True)
        + _capacity(h.capacity, "", history.SPAN_NO_CAPACITY_WEEKS, chosen)
        + _blocked_table(h.exhausted)
        + _usage_tables(h.usage, "")
        + _coverage(h.coverage))
    return _document(f"WindowTally — history, {h.span.label}", body)


def _document(title: str, body: str) -> str:
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{escape(title)}</title><style>{_CSS}</style><script>{_SCRIPT}</script></head>"
            f'<body class="windowtally"><main>{body}</main></body></html>')


def write_dashboard(path: Path, html: str) -> None:
    write_text_atomically(path, html)
