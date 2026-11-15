"""The history page in the tightened look, read from its markup and style sheet: an account card in the order of the
window's card, every word of it kept; the account in use marked by a strip of its colour inside the card's left edge,
its edge the hairline; the page ground's grid in the dark mode alone; the window's density; and each run of a chart's
line shaded down to its own floor, by the one rule the History window shades by."""

import re
import unittest
from datetime import date

from fixtures import ACCOUNT_A, EMAIL_A
from test_page_look import T0, card, five, standing, week
from windowtally import charts, dashboard, history
from windowtally.billing import Subscription
from windowtally.charts import Axis, LineSeries, line_chart
from windowtally.limits import recommend
from windowtally.products import Report, Share
from windowtally_gui import plot_model, theme_view


def text(html: str) -> str:
    """The words a reader sees, the markup taken out."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", html)).strip()


class CardOrderTest(unittest.TestCase):
    def test_a_card_stands_in_the_window_s_card_s_order(self):
        plan = Subscription(email=EMAIL_A, label="alpha", uuid=ACCOUNT_A, uuids=(ACCOUNT_A,), bills=(), periods=(),
                            gaps=(), uses=(), state="active", plan="max5x", paid_until=date(2026, 11, 1),
                            days_left=12, renew_soon=False, profile_plan=None, profile_check="matches",
                            profile_fetched_at=None, this_month=None)
        html = card(standing(five(40.0), week(25.0)), plan)
        places = [html.index(mark) for mark in ("<h3>", '<div class="note">last response', '<div class="gauges">',
                                                 '<svg class="rings"', "5-hour</span>", "Weekly</span>",
                                                 '<div class="line">', '<div class="row plan">')]
        self.assertEqual(places, sorted(places))
        lines = re.findall(r'<div class="line">(.*?)</div>', html)
        self.assertEqual(len(lines), 2, "each ringed window's line under the gauges")
        self.assertTrue(lines[0].endswith("(in 1h 0m)") and "resets" in lines[0], lines[0])
        self.assertIn("resets Wed 11:00", lines[1])
        figures = html[html.index('<div class="figs">'):html.index('<div class="line">')]
        self.assertNotIn("resets", figures, "the figures stand beside the rings, the resets on the lines under them")

    def test_each_line_stands_behind_its_ring_s_dot_and_the_figure_s_row_carries_the_same_dot(self):
        html = card(standing(five(96.0), week(75.0)))
        dots = re.findall(r'<i class="key" style="background:([^"]*)"></i>', html)
        self.assertEqual(dots, ["var(--critical)", "var(--warning)", "var(--critical)", "var(--warning)"],
                         "the two rows beside the rings, then the two lines, in the card's order")

    def test_an_account_with_no_5_hour_limit_puts_its_weekly_window_first_and_its_limit_s_words_on_a_line(self):
        html = card(standing(five(None, state="no_limit"), week(50.0)))
        self.assertLess(html.index("Weekly</span>"), html.index("5-hour</span>"))
        self.assertIn('<span class="k"><i class="key off"></i>5-hour</span><span><b>no limit</b></span>', html)
        lines = re.findall(r'<div class="line">(.*?)</div>', html)
        self.assertEqual(lines[-1], '<i class="key off"></i>this account has no 5-hour limit')
        self.assertIn("resets Wed 11:00", lines[0])

    def test_the_week_s_use_by_product_follows_the_weekly_window_s_line(self):
        shares = (Share("claude_code", "Claude Code", 99.0), Share("chat", "Chats", 1.0), Share("other", "Other", 0.0))
        report = Report(ACCOUNT_A, "org", T0 - 300, T0 - 300, T0 - 86400, shares, 25.0)
        s = standing(five(40.0), week(25.0))
        html = dashboard._cards([s], {ACCOUNT_A: dashboard.AccountView(ACCOUNT_A, "alpha", "var(--series-1)")},
                                recommend([s]), T0, None, {ACCOUNT_A: report})
        lines = re.findall(r'<div class="line">(.*?)</div>', html)
        self.assertEqual(lines[-1], f'<i class="key off"></i>by product {history.when(T0 - 300, T0)}: Claude Code 99%, '
                                    "Chats 1%", "the shares above nothing, in the page's order")
        self.assertIn("resets Wed 11:00", lines[-2])

    def test_every_word_the_card_said_it_still_says(self):
        # The words of a card before the tightened order, as the page wrote them: the title and roles, each window's
        # name, figure and line, the last response.
        html = card(standing(five(40.0, as_of=T0 - 60), week(25.0, as_of=T0 - 60), in_use=True))
        said = text(html)
        for words in ("alpha", "desktop app", "CLI", "5-hour", "40%", "Weekly", "25%", "resets", "last response"):
            self.assertIn(words, said)
        before = ("alpha desktop app CLI use next 5-hour 40% resets ≈Tue 12:00 (in 1h 0m) Weekly 25% resets Wed 11:00 "
                  "(in 1d 0h) last response Tue 10:50 (0h 10m ago)")
        # The card's words, the recommendation under the cards left out, compared as a set of words in any order.
        self.assertEqual(sorted(said.split("Next:")[0].split()), sorted(before.split()))


class InUseTest(unittest.TestCase):
    def test_the_account_in_use_is_marked_by_a_strip_of_its_colour_inside_the_card_s_left_edge(self):
        css = dashboard._CSS
        self.assertIn('.windowtally .card.use::before { content:""; position:absolute; left:0; top:0; bottom:0; '
                      "width:4px; background:var(--account); }", css)
        self.assertIn(".windowtally .card { position:relative; overflow:hidden; }", css,
                      "the strip is clipped to the card's rounded corner")

    def test_the_in_use_card_s_edge_stays_the_hairline_and_wears_no_shadow(self):
        css = dashboard._CSS
        self.assertEqual(re.findall(r"\.card\.use \{", css), [])
        self.assertNotIn("use-shadow", css)
        self.assertNotIn("box-shadow:var(", css)


class GroundTest(unittest.TestCase):
    def test_the_page_ground_lays_its_grid_in_the_dark_mode_alone_as_the_window_s_ground_does(self):
        self.assertEqual(theme_view.GRIDDED_MODES, ("dark",))
        css = dashboard._CSS
        light = re.search(r"\n\.windowtally \{ color-scheme: light; ([^}]*)\}", css).group(1)
        media = re.search(r"@media \(prefers-color-scheme: dark\) \{ [^{]*\{ color-scheme: dark; ([^}]*)\}", css).group(1)
        chosen = re.search(r':root\[data-theme="dark"\] \.windowtally \{ color-scheme: dark; ([^}]*)\}', css).group(1)
        self.assertIn("--ground:none;", light)
        grid = ("--ground:linear-gradient(var(--page-grid) 1px,transparent 1px),"
                "linear-gradient(90deg,var(--page-grid) 1px,transparent 1px);")
        self.assertIn(grid, media)
        self.assertIn(grid, chosen)
        self.assertIn("background-image:var(--ground);", css)
        self.assertEqual(css.count("linear-gradient(var(--page-grid)"), 2, "the grid in the dark blocks alone")


class DensityTest(unittest.TestCase):
    def test_panels_tiles_and_sections_stand_at_the_window_s_density(self):
        css = dashboard._CSS
        # The page's line is its 14 px text at 1.45: half a line is 10 px, three quarters 15 px, a line 20 px.
        self.assertIn("border-radius:8px; padding:10px 15px; }", css, "a card's and a panel's padding")
        self.assertIn("padding:10px 15px;\n  display:flex;", css, "a tile's")
        self.assertIn("minmax(280px,1fr)); gap:10px; }", css, "cards half a line apart")
        self.assertIn("minmax(160px,1fr)); gap:10px; }", css, "tiles half a line apart")
        self.assertIn(".windowtally h2 { font-size:16px; font-weight:600; margin:20px 0 8px; }", css)
        self.assertIn("padding:10px 15px 40px;", css, "the page half a line under its top")


class ShadeTest(unittest.TestCase):
    def gradients(self, svg: str) -> list[tuple[float, float]]:
        return [(float(y1), float(y2)) for y1, y2 in re.findall(
            r'<linearGradient id="[^"]*" gradientUnits="userSpaceOnUse" x1="0" y1="([^"]*)" x2="0" y2="([^"]*)">', svg)]

    def test_each_run_fades_from_its_own_highest_point_to_its_own_floor(self):
        # One run five units wide reaching 40 %, and a narrow, level run high on the chart after a break.
        series = [LineSeries("alpha", "var(--series-1)", [(0, 10.0), (4, 40.0), (5, 35.0), (30, 90.0), (30.2, 90.0)],
                             break_after=5)]
        svg = line_chart(series, x_range=(0, 40), y_range=(0.0, 100.0), x_axis=Axis(), y_axis=Axis(),
                         title="Weekly use by account")
        bottom, top = 260 - charts.PLOT_BOTTOM, charts.PLOT_TOP
        left, right = charts.PLOT_LEFT, charts.WIDTH - charts.PLOT_RIGHT

        def px(x): return left + x / 40 * (right - left)
        def py(y): return bottom - y / 100 * (bottom - top)

        (wide_top, wide_floor), (narrow_top, narrow_floor) = self.gradients(svg)
        self.assertAlmostEqual(wide_top, py(40.0), places=1)
        self.assertEqual(wide_floor, bottom, "a run as wide as half its height fades at the baseline")
        self.assertAlmostEqual(narrow_top, py(90.0), places=1)
        self.assertAlmostEqual(narrow_floor, py(90.0) + charts.AREA_REACH * (px(30.2) - px(30)), places=0)
        self.assertLess(narrow_floor, bottom, "a narrow run casts a short shade, not a column to the baseline")
        self.assertEqual(len(set(re.findall(r'fill="url\(#([^)]*)\)"', svg))), 2, "a gradient of each run's own")

    def test_the_page_and_the_history_window_shade_by_one_rule(self):
        self.assertIs(plot_model.AREA_REACH, charts.AREA_REACH)
        line = plot_model.Line("series-1", (10.0, 40.0, 14.0, 40.0, 14.0, 60.0), "alpha")
        self.assertEqual(plot_model.shade_floor(line, 300.0), charts.shade_floor((10.0, 14.0, 14.0), (40.0, 40.0, 60.0),
                                                                               300.0))
        self.assertEqual(charts.shade_floor((0.0, 4.0), (40.0, 40.0), 300.0), 40.0 + charts.AREA_REACH * 4.0)
        self.assertEqual(charts.shade_floor((0.0, 200.0), (40.0, 40.0), 300.0), 300.0, "never past the baseline")


if __name__ == "__main__":
    unittest.main()
