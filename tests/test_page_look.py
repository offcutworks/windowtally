"""The restrained dashboard look of the history page and the History window's export, read from their markup: an
account card's two windows as rings from the window's geometry, in the logo's colours and the warning fills; a figure at
a level in the level's text colour; a reading's age and a plan's days left said only by the window's bounds, each
tested on both sides of its edge; each account's share as a bar in its colour; the shade and the glow under a chart's
line as the History window paints them; the mode's values in the style sheet; and one file with nothing fetched."""

import math
import re
import unittest
from datetime import date

from fixtures import ACCOUNT_A, ACCOUNT_B, EMAIL_A, epoch
from windowtally import charts, dashboard, history, palette, rings
from windowtally.accounts import Account
from windowtally.billing import Subscription
from windowtally.charts import Axis, LineSeries, line_chart
from windowtally.dashboard import PULSE_LOW, PULSE_SECONDS, RING_SIZE, AccountView, _cards, _summary
from windowtally.limits import (FIVE_HOURS, AccountStanding, WeeklyAnchor, WindowStanding, reading_dated, recommend,
                                renewal_near, shared_reading)
from windowtally_gui import motion_model, plot_view, theme_view

T0 = epoch("2026-10-20T10:00:00Z")
ALPHA = history.Entity(ACCOUNT_A, "alpha", "series-1")
BETA = history.Entity(ACCOUNT_B, "beta", "series-2")
VIEWS = {ACCOUNT_A: AccountView(ACCOUNT_A, "alpha", "var(--series-1)")}


def standing(five_hour: WindowStanding, weekly: WindowStanding, *, last_activity: float | None = T0 - 600,
             in_use: bool = False) -> AccountStanding:
    return AccountStanding(Account(uuid=ACCOUNT_A, email=EMAIL_A), five_hour, weekly,
                           WeeklyAnchor(T0 + 86400, exact=True), last_activity, in_use, in_use)


def five(percent: float | None, *, state: str = "running", as_of: float | None = T0 - 60) -> WindowStanding:
    return WindowStanding("five_hour", state, percent, T0 + 3600 if state == "running" else None, as_of, False)


def week(percent: float | None, *, as_of: float | None = T0 - 60) -> WindowStanding:
    return WindowStanding("seven_day", "current", percent, T0 + 86400, as_of, False)


def card(s: AccountStanding, subscription: Subscription | None = None) -> str:
    billing = None
    if subscription is not None:
        billing = type("Billing", (), {"configured": True, "for_account": staticmethod(lambda uuid: subscription)})()
    return _cards([s], VIEWS, recommend([s]), T0, billing)


def circles(html: str, kind: str) -> list[dict[str, str]]:
    """The attributes of each ``<circle>`` of class ``kind`` (``track`` or ``arc``, a pulsing arc among them)."""
    found = re.findall(rf'<circle class="{kind}( pulse)?" ([^>]*)/>', html)
    return [dict(re.findall(r'([a-z-]+)="([^"]*)"', attributes), pulse=pulse.strip()) for pulse, attributes in found]


def subscription(days_left: int) -> Subscription:
    return Subscription(email=EMAIL_A, label="alpha", uuid=ACCOUNT_A, uuids=(ACCOUNT_A,), bills=(), periods=(),
                        gaps=(), uses=(), state="active", plan="max5x", paid_until=date(2026, 11, 1),
                        days_left=days_left, renew_soon=False, profile_plan=None, profile_check="matches",
                        profile_fetched_at=None, this_month=None)


class RingsTest(unittest.TestCase):
    def test_a_card_draws_the_weekly_window_outside_and_the_5_hour_window_inside_from_the_window_s_geometry(self):
        html = card(standing(five(40.0), week(25.0)))
        outer, inner = rings.rings(RING_SIZE, (0.25, 0), (0.40, 0))
        tracks, arcs = circles(html, "track"), circles(html, "arc")
        self.assertEqual([(t["r"], t["stroke-width"]) for t in tracks],
                         [(f"{ring.radius:.2f}", f"{ring.width:.2f}") for ring in (outer, inner)])
        self.assertEqual([a["style"] for a in arcs], [f"color:{rings.WEEKLY}", f"color:{rings.FIVE_HOUR}"])
        for arc, ring in zip(arcs, (outer, inner)):
            around = 2 * math.pi * ring.radius
            self.assertEqual(arc["stroke-dasharray"], f"{around * ring.fraction:.2f} {around:.2f}")
            self.assertEqual(arc["transform"], f"rotate(-90 {RING_SIZE / 2:g} {RING_SIZE / 2:g})", "from the top")
            self.assertEqual(arc["pulse"], "", "nothing moves below a warning")
        self.assertNotIn('class="meter"', html, "no bar on a card")

    def test_an_arc_takes_its_own_window_s_warning_fill_and_pulses_and_its_figure_the_level_s_text_colour(self):
        # The 5-hour window warns from 80 % and errs from 95 %, the weekly window from 70 % and 90 %.
        html = card(standing(five(96.0), week(75.0)))
        weekly, five_hour = circles(html, "arc")
        self.assertEqual((weekly["style"], weekly["pulse"]), ("color:var(--warning)", "pulse"))
        self.assertEqual((five_hour["style"], five_hour["pulse"]), ("color:var(--critical)", "pulse"))
        self.assertIn('<b class="num l2">96%</b>', html)
        self.assertIn('<b class="num l1">75%</b>', html)
        self.assertIn('<i class="key" style="background:var(--critical)"></i>5-hour', html)
        calm = card(standing(five(79.0), week(69.0)))
        self.assertIn('<b class="num">79%</b>', calm)
        self.assertIn(f'<i class="key" style="background:{rings.FIVE_HOUR}"></i>5-hour', calm)
        self.assertNotIn("pulse", calm)

    def test_a_window_not_started_shows_its_track_alone_and_says_nothing_under_its_name(self):
        html = card(standing(five(0.0, state="not_started"), week(25.0)))
        self.assertEqual(len(circles(html, "track")), 2)
        self.assertEqual([a["style"] for a in circles(html, "arc")], [f"color:{rings.WEEKLY}"])
        self.assertIn("<b>not started</b></span></div>", html)
        self.assertNotIn("starts with the next message", html)

    def test_an_account_with_no_5_hour_limit_draws_its_one_ring_from_the_window_s_geometry(self):
        html = card(standing(five(None, state="no_limit"), week(50.0)))
        (single,) = rings.rings(RING_SIZE, (0.5, 0), None)
        self.assertEqual([(t["r"], t["stroke-width"]) for t in circles(html, "track")],
                         [(f"{single.radius:.2f}", f"{single.width:.2f}")])
        self.assertEqual(len(circles(html, "arc")), 1)

    def test_the_card_of_an_account_a_client_uses_carries_the_use_class(self):
        self.assertIn('<div class="card use" style="--account:var(--series-1)">',
                      card(standing(five(40.0), week(25.0), in_use=True)))
        self.assertIn('<div class="card" style="--account:var(--series-1)">', card(standing(five(40.0), week(25.0))))


class SaidWhenItMattersTest(unittest.TestCase):
    def test_a_fresh_reading_s_age_is_not_said_and_one_a_5_hour_window_old_is(self):
        fresh = T0 - FIVE_HOURS + 1
        self.assertNotIn("reading ", card(standing(five(40.0, as_of=fresh), week(25.0, as_of=fresh), last_activity=None)))
        old = T0 - FIVE_HOURS
        self.assertIn(" · reading ", card(standing(five(40.0, as_of=old), week(25.0, as_of=old), last_activity=None)))

    def test_a_response_since_the_reading_dates_it(self):
        at = T0 - 60
        self.assertNotIn("reading ", card(standing(five(40.0, as_of=at), week(25.0, as_of=at), last_activity=at)))
        self.assertIn(" · reading ", card(standing(five(40.0, as_of=at), week(25.0, as_of=at), last_activity=at + 1)))

    def test_one_reading_is_said_once_after_the_last_response_and_readings_that_differ_on_their_windows_lines(self):
        old = T0 - FIVE_HOURS
        shared = card(standing(five(40.0, as_of=old), week(25.0, as_of=old), last_activity=None))
        self.assertEqual(shared.count("reading "), 1)
        self.assertRegex(shared, r'<div class="note">last response [^<]* · reading [^<]*</div>')
        apart = card(standing(five(40.0, as_of=T0 - 60), week(25.0, as_of=old), last_activity=None))
        self.assertEqual(apart.count("reading "), 1, "the fresh one is not said")
        self.assertIn('<div class="note">last response —</div>', apart)
        self.assertRegex(apart, rf'<div class="line"><i class="key" style="background:{rings.WEEKLY}"></i>'
                                r'[^<]* · reading [^<]*</div>')

    def test_the_bounds_are_the_window_s(self):
        from windowtally_gui import live_model
        self.assertIs(live_model.renewal_near, renewal_near)
        window = type("Window", (), {"as_of": T0 - 60})()
        for last_activity in (None, T0 - 61, T0 - 59):
            self.assertEqual(live_model.reading_dated(window, last_activity, T0),
                             reading_dated(T0 - 60, last_activity, T0))
        for state, five_hour_as_of, weekly_as_of in (("running", T0, T0), ("running", T0, T0 - 1),
                                                     ("no_limit", None, T0), ("not_started", None, T0)):
            account = type("Account", (), {"five_hour": type("W", (), {"state": state, "as_of": five_hour_as_of})(),
                                           "weekly": type("W", (), {"as_of": weekly_as_of})()})()
            self.assertEqual(live_model.shared_reading(account), shared_reading(state, five_hour_as_of, weekly_as_of))
        self.assertTrue(shared_reading("no_limit", None, T0))
        self.assertFalse(shared_reading("running", T0, T0 - 1))

    def test_a_card_says_a_plan_s_days_left_within_a_week_of_its_renewal_and_the_table_always(self):
        self.assertIn("(7 days left)", card(standing(five(40.0), week(25.0)), subscription(7)))
        far = card(standing(five(40.0), week(25.0)), subscription(8))
        self.assertNotIn("days left", far)
        self.assertIn("paid until", far, "its date is always said")
        self.assertIn('<div class="row plan">', far)
        self.assertEqual(history.plan_words(subscription(8))[1][-14:], " (8 days left)")
        self.assertNotIn("left", history.plan_words(subscription(8), near_only=True)[1])


class TilesTest(unittest.TestCase):
    def test_an_account_s_share_is_a_bar_in_its_colour_and_every_tile_keeps_the_bar_s_room(self):
        column = (history.Column(date(2026, 10, 21), date(2026, 10, 21)),)
        costs = {ALPHA: 75.0, BETA: 25.0}
        families = tuple(history.EntityCosts(e, (history.Stack("Opus", "series-5", (c,)),)) for e, c in costs.items())
        accounts = tuple(history.Stack(e.label, e.token, (c,)) for e, c in costs.items())
        figures = history.summary(None, {}, [ALPHA, BETA], history.Costs(column, accounts, families), None,
                                  date(2026, 10, 21), T0, weeks=())
        html = _summary(figures)
        self.assertIn('<div class="cap">alpha&#x27;s share</div><div class="fig">75%</div>'
                      '<div class="bar"><i style="width:75%;background:var(--series-1)"></i></div>', html)
        self.assertIn('<div class="bar"><i style="width:25%;background:var(--series-2)"></i></div>', html)
        tiles = len(history.summary_tiles(figures))
        self.assertEqual(html.count('<div class="bar'), tiles)
        self.assertEqual(html.count('<div class="bar off"></div>'), tiles - 2)


class ChartTest(unittest.TestCase):
    def chart(self) -> str:
        series = [LineSeries("alpha", "var(--series-1)", [(0, 10.0), (1, 40.0), (2, 30.0), (10, 5.0), (11, 20.0)],
                             break_after=5),
                  LineSeries("beta", "var(--series-2)", [(3, 50.0)])]
        return line_chart(series, x_range=(0, 12), y_range=(0.0, 100.0), x_axis=Axis([(0, "a")]),
                          y_axis=Axis([(0, "0%"), (100, "100%")]), title="Weekly use by account")

    def test_a_line_stands_over_a_shade_under_the_gridlines_and_a_glow_under_itself(self):
        svg = self.chart()
        self.assertEqual(svg.count('<path class="area"'), 2, "a shape under each run of the broken line")
        self.assertEqual(svg.count('<polyline class="halo"'), 2)
        self.assertEqual(svg.count('<polyline class="line"'), 2)
        self.assertEqual(svg.count('<circle class="dot"'), 1, "one reading alone is a dot, with no shade")
        self.assertLess(svg.rindex('class="area"'), svg.index('class="grid"'))
        self.assertLess(svg.index('class="grid"'), svg.index('class="halo"'))
        self.assertLess(svg.rindex('class="halo"'), svg.index('class="line"'))
        halo = re.search(r'<polyline class="halo" stroke="([^"]*)" points="([^"]*)"', svg).groups()
        line = re.search(r'<polyline class="line" stroke="([^"]*)" points="([^"]*)"', svg).groups()
        self.assertEqual(halo, line, "the glow is the line's own path and colour")

    def test_each_run_s_shade_runs_from_its_own_highest_point_to_nothing_at_its_floor(self):
        svg = self.chart()
        gradients = re.findall(
            r'<linearGradient id="([^"]*)" gradientUnits="userSpaceOnUse" x1="0" y1="([^"]*)" x2="0" y2="([^"]*)">'
            r'<stop offset="0" style="([^"]*)"/><stop offset="1" style="([^"]*)"/></linearGradient>', svg)
        self.assertEqual(len(gradients), 2, "a gradient of its own for each run of the broken line")
        bottom = 260 - charts.PLOT_BOTTOM
        # Each run is at least half as wide as its lowest point stands above the baseline, so it fades at the baseline.
        for (name, y1, y2, top, foot), highest in zip(gradients, (0.40, 0.20)):     # each run's own highest point
            self.assertEqual(svg.count(f'fill="url(#{name})"'), 1, name)
            self.assertEqual(float(y2), bottom, name)
            self.assertAlmostEqual(float(y1), bottom - highest * (bottom - charts.PLOT_TOP), places=1, msg=name)
            self.assertEqual(top, "stop-color:var(--series-1);stop-opacity:var(--area)")
            self.assertEqual(foot, "stop-color:var(--series-1);stop-opacity:0")
        areas = re.findall(r'<path class="area" fill="url\(#([^)]*)\)" d="([^"]*)"', svg)
        self.assertEqual([name for name, _d in areas], [name for name, *_ in gradients], "each run's shape its own fill")
        left, right = charts.PLOT_LEFT, charts.WIDTH - charts.PLOT_RIGHT
        for (_name, d), (first_x, last_x) in zip(areas, ((0, 2), (10, 11))):     # the x range is 0 to 12
            start, end = (left + x / 12 * (right - left) for x in (first_x, last_x))
            self.assertTrue(d.startswith(f"M{start:.1f},{bottom}L") and d.endswith(f"L{end:.1f},{bottom}Z"), d)

    def test_two_charts_of_one_document_name_their_gradients_apart(self):
        series = [LineSeries("alpha", "var(--series-1)", [(0, 10.0), (1, 40.0)])]
        ids = {re.search(r'<linearGradient id="([^"]*)"', line_chart(
            series, x_range=(0, 1), y_range=(0.0, 100.0), x_axis=Axis(), y_axis=Axis(), title=title)).group(1)
            for title in ("Weekly use by account", "Another chart")}
        self.assertEqual(len(ids), 2)
        other = [LineSeries("alpha", "var(--series-1)", [(0, 10.0), (1, 60.0)])]
        untitled = {re.search(r'<linearGradient id="([^"]*)"', line_chart(
            lines, x_range=(0, 1), y_range=(0.0, 100.0), x_axis=Axis(), y_axis=Axis())).group(1)
            for lines in (series, other)}
        self.assertEqual(len(untitled), 2, "charts with no title, or one title, still differ by what they draw")

    def test_the_treatment_is_the_history_window_s(self):
        self.assertEqual(charts.AREA, plot_view.AREA)
        self.assertEqual(((charts.HALO_WIDTH, charts.HALO_OPACITY),), plot_view.HALO)


class StyleSheetTest(unittest.TestCase):
    def blocks(self) -> tuple[str, str, str]:
        css = dashboard._CSS
        light = re.search(r"\n\.windowtally \{ color-scheme: light; ([^}]*)\}", css).group(1)
        media = re.search(r"@media \(prefers-color-scheme: dark\) \{ [^{]*\{ color-scheme: dark; ([^}]*)\}", css).group(1)
        chosen = re.search(r':root\[data-theme="dark"\] \.windowtally \{ color-scheme: dark; ([^}]*)\}', css).group(1)
        return light, media, chosen

    def test_each_mode_says_how_much_shade_and_glow_data_wears_and_the_light_mode_wears_no_glow(self):
        light, media, chosen = self.blocks()
        self.assertEqual(media, chosen, "the dark mode is one, however it is chosen")
        self.assertIn(f"--area:{charts.AREA[0]};", light)
        self.assertIn("--halo:0;", light)
        self.assertIn("--glow:none;", light)
        self.assertIn(f"--area:{charts.AREA[1]};", chosen)
        self.assertIn(f"--halo:{charts.HALO_OPACITY};", chosen)
        self.assertIn("--glow:drop-shadow(", chosen)
        for colours, block in ((palette.LIGHT, light), (palette.DARK, chosen)):
            for token in ("warning-text", "critical-text", "advice", "edge", "ring-track", "page-grid"):
                self.assertIn(f"--{token}:{colours[token]};", block)

    def test_glow_is_on_data_marks_alone(self):
        css = dashboard._CSS
        self.assertEqual(re.findall(r"([^{}\n]*)\{[^}]*var\(--glow\)", css), [".windowtally svg .arc "])
        self.assertEqual(re.findall(r"([^{}\n]*)\{[^}]*var\(--halo\)", css), [".windowtally svg .halo "])

    def test_the_one_thing_that_moves_is_a_pulsing_arc_at_the_window_s_pace_and_not_under_reduced_motion(self):
        css = dashboard._CSS
        self.assertEqual((PULSE_SECONDS, PULSE_LOW), (motion_model.PULSE, motion_model.PULSE_LOW))
        self.assertEqual(re.findall(r"animation:([^;}]*)", css),
                         [f"windowtally-pulse {PULSE_SECONDS:g}s ease-in-out infinite", "none"])
        self.assertIn(f"@keyframes windowtally-pulse {{ 50% {{ opacity:{PULSE_LOW:g}; }} }}", css)
        self.assertIn("@media (prefers-reduced-motion: reduce) { .windowtally svg .pulse { animation:none; } }", css)
        self.assertNotIn("transition", css)

    def test_the_page_ground_is_the_window_s_grid_and_the_fonts_are_named_never_fetched(self):
        css = dashboard._CSS
        self.assertEqual(dashboard.GRID, theme_view.GRID)
        self.assertIn(f"background-size:{dashboard.GRID}px {dashboard.GRID}px;", css)
        self.assertIn("var(--page-grid) 1px", css)
        for family in theme_view.WORD_FAMILIES:
            self.assertIn(f'"{family}"', dashboard.WORDS)
        for family in theme_view.FIGURE_FAMILIES:
            self.assertIn(family, dashboard.FIGURES)
        self.assertNotIn("@font-face", css)
        self.assertNotIn("@import", css)
        self.assertNotIn("url(", css)


if __name__ == "__main__":
    unittest.main()
