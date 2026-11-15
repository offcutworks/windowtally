"""The window's History view, without a display: the computation, the spans asked for and shown, the blocks in the
history page's order, and the charts laid out as marks."""

import html
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bill,
                      bridge_line, epoch, page_headings)
from windowtally import files, history
from windowtally.dashboard import render_history
from windowtally.service import run_pass
from windowtally_gui import actions_model, history_model
from windowtally_gui.history_model import Bullets, Chart, Heading, Note, Requests, Switch, Table
from windowtally_gui.plot_model import (ColumnPlot, ColumnStack, Line, LinePlot, Margins, Marker, Marks, Series,
                                        layout_columns, layout_line, mark_at)
from windowtally_gui.table_model import layout_table, trailing_totals
from windowtally_gui.tiles_model import TilePlace, layout_tiles

NOW = epoch("2026-10-21T18:30:00Z")
DAY = 86400.0


def measure(text: str) -> float:
    return 7.0 * len(text)


def window_headings(blocks) -> list[tuple[Heading, tuple[str, ...]]]:
    """The window's headings in order, each with the words of the switch it heads: a switch gives each of its views'
    heading in the switch's order, a heading of no switch no words."""
    found = []
    for block in blocks:
        if isinstance(block, Heading):
            found.append((block, ()))
        elif isinstance(block, Switch):
            found += [(view.heading, tuple(v.choice for v in block.views)) for view in block.views]
    return found


class RequestsTest(unittest.TestCase):
    def test_the_last_span_chosen_wins(self):
        requests = Requests("30d")
        self.assertEqual(requests.want("6mo"), "6mo")
        self.assertIsNone(requests.want("7d"))                 # 6 months still runs
        self.assertEqual(requests.status(), ("Computing 7 days…", False))
        self.assertEqual(requests.done("6mo", result=object()), "7d")
        self.assertIsNone(requests.shown)                      # the result for a span no longer chosen is dropped
        shown = object()
        self.assertIsNone(requests.done("7d", result=shown))
        self.assertIs(requests.shown, shown)
        self.assertIsNone(requests.running)

    def test_a_recompute_while_the_same_span_runs_is_followed_by_one_more(self):
        requests = Requests("30d")
        self.assertEqual(requests.want("30d"), "30d")
        self.assertIsNone(requests.want("30d"))                # Recompute pressed while it runs
        self.assertIsNone(requests.want("30d"))                # and again: still one more, not two
        early = object()
        self.assertEqual(requests.done("30d", result=early), "30d")
        self.assertIs(requests.shown, early)                   # shown while the next one runs
        later = object()
        self.assertIsNone(requests.done("30d", result=later))
        self.assertIs(requests.shown, later)

    def test_a_failure_is_said_and_the_content_shown_stays(self):
        requests = Requests("30d")
        requests.want("30d")
        first = object()
        requests.done("30d", result=first)
        requests.want("all")
        requests.done("all", failure="no ledger at X")
        self.assertIs(requests.shown, first)
        self.assertEqual(requests.status(), ("Not computed: no ledger at X", True))
        requests.want("all")
        self.assertEqual(requests.status(), ("Computing the whole history…", False))


class HistoryViewTest(unittest.TestCase):
    """A machine whose ledger a pass has written; the window then computes from it."""

    @classmethod
    def setUpClass(cls):
        cls.machine = m = Machine()
        m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        m.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        m.app_history([(NOW - 20 * DAY + i * 3 * 3600, org, 30.0, (i % 50) * 1.8)
                       for i in range(150) for org in (ORG_A, ORG_B)])
        events = []
        for day in range(20):
            session = f"s{day}"
            owner = ACCOUNT_A if day % 2 else ACCOUNT_B
            answered = NOW - (20 - day) * DAY + 600
            # The app is on the session's owner when it answers: its account of that moment takes the response.
            events.append((answered - 60, "desktop_account", owner))
            m.transcript(session, [bridge_line(session, owner, ORG_A)]
                         + assistant_lines(f"m{day}", answered, session))
        m.sync_events(events)
        m.bills_file([bill(EMAIL_A, "2026-09-07", 90.0, plan="max5x", period="2026-09-07..2026-10-07"),
                      bill(EMAIL_A, "2026-10-07", 90.0, plan="max5x", period="2026-10-07..2026-11-07"),
                      bill(EMAIL_B, "2026-10-10", 15.0, kind="topup", plan=None)])
        run_pass(m.paths, now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.machine.close()

    def test_the_history_is_computed_without_writing_the_ledger_or_reading_a_profile(self):
        paths = self.machine.paths
        before = paths.ledger_db.read_bytes()
        profiles = paths.accounts_dir.with_name("accounts-away")
        shutil.move(str(paths.accounts_dir), str(profiles))   # the sync's store out of reach
        try:
            h = history_model.compute(paths, "30d", ("bills: a problem",), now=NOW)
        finally:
            shutil.move(str(profiles), str(paths.accounts_dir))
        self.assertEqual(paths.ledger_db.read_bytes(), before)
        self.assertEqual([(e.label, e.token) for e in h.accounts], [("alpha", "series-1"), ("beta", "series-2")])
        self.assertTrue(h.subscriptions.configured)
        self.assertIn("Source problem: bills: a problem", h.coverage)

    def test_no_ledger_is_a_failure_said_in_words(self):
        empty = Machine()
        try:
            with self.assertRaises(FileNotFoundError):
                history_model.compute(empty.paths, "7d", now=NOW)
        finally:
            empty.close()

    def headings(self, key: str) -> list[str]:
        """Every heading the window can show, in order: a switch's every view's, in the switch's order."""
        return [heading.text for heading, _words in window_headings(
            history_model.blocks(history_model.compute(self.machine.paths, key, now=NOW)))]

    def test_the_blocks_follow_the_page_s_order_without_the_cards(self):
        headings = self.headings("30d")
        order = ["Summary", "Weekly use", "API-equivalent cost per day", "Subscriptions",
                 "Plans at list price, by month", "Plan periods", "Gaps between periods", "All accounts exhausted",
                 "Sessions", "Models", "Effort", "Coverage"]
        self.assertEqual([h for h in headings if h in order], order)
        self.assertIn("alpha cost by model family", headings)
        self.assertNotIn("Next:", " ".join(headings))

    def test_long_spans_say_week_where_short_ones_say_day(self):
        self.assertIn("API-equivalent cost per week", self.headings("6mo"))
        self.assertIn("Tokens per week", self.headings("6mo"))
        self.assertIn("beta cost by model family", self.headings("all"))
        self.assertIn("API-equivalent cost per day", self.headings("7d"))
        self.assertIn("Tokens per day", self.headings("7d"))

    def test_the_subscription_summary_shows_no_profile_check(self):
        blocks = history_model.blocks(history_model.compute(self.machine.paths, "30d", now=NOW))
        summary = next(b for b in blocks if isinstance(b, Table) and b.columns[1][0] == "Plan today")
        self.assertEqual([c[0] for c in summary.columns], ["Account", "Plan today", "Bills", "Last bill"])

    def test_the_month_tables_mark_their_totals_and_carry_the_page_s_note_as_their_hint(self):
        blocks = history_model.blocks(history_model.compute(self.machine.paths, "30d", now=NOW))
        index = blocks.index(Heading("Plans at list price, by month", history.COST_NOTE))
        cost = next(b for b in blocks[index:] if isinstance(b, Table))
        self.assertEqual(cost.totals, (len(cost.rows) - 1,))
        self.assertEqual(cost.rows[-1][0], "In all")
        self.assertFalse(any("Top-ups" in row[0] for row in cost.rows), "a top-up counts in no figure")
        notes = [b.text for b in blocks if isinstance(b, Note)]
        self.assertNotIn(history.COST_NOTE, notes, "the heading's hint, never text at rest")
        self.assertTrue(isinstance(blocks[-1], Bullets))

    def test_every_chart_colour_is_a_role_the_window_has(self):
        from windowtally_gui.theme_model import ROLES
        for key in ("7d", "all"):
            for block in history_model.blocks(history_model.compute(self.machine.paths, key, now=NOW)):
                if isinstance(block, Chart):
                    tokens = ([s.token for s in block.plot.series] + [m.token for m in block.plot.markers]
                              if isinstance(block.plot, LinePlot) else [s.token for s in block.plot.stacks])
                    self.assertTrue(set(tokens) <= set(ROLES), tokens)

    def test_the_export_is_the_span_shown_in_the_window_s_order_without_the_cards(self):
        h = history_model.compute(self.machine.paths, "30d", now=NOW)
        page = render_history(h)
        found = page_headings(page)
        window = [(b.text, words, "", b.hint) for b, words in window_headings(history_model.blocks(h))]
        self.assertEqual(found, window, "every heading and its hint, pair for pair, a switch's a pane per view")
        self.assertEqual(page.count("<h2>"), len(window))
        self.assertIn(f"30 days from {history.day_text(h.first)}", page)
        self.assertNotIn('class="card"', page)
        self.assertNotIn("Next:", page)
        for tile in history.summary_tiles(h.summary):
            self.assertIn(html.escape(tile.figure), page)

    def test_a_long_span_exports_its_cost_per_week(self):
        h = history_model.compute(self.machine.paths, "6mo", now=NOW)
        page = render_history(h)
        hint = html.escape(history.BY_WEEK_NOTE)
        cost, tokens = (html.escape(word) for word in history.SWITCH_VIEWS[history.COLUMNS_SWITCH])
        self.assertIn(f'<h2>API-equivalent cost per week <span class="seg"><label for="switch-columns-0" class="on">'
                      f'{cost}</label><label for="switch-columns-1">{tokens}</label></span> <span class="help" '
                      f'tabindex="0" title="{hint}" aria-label="{hint}">?</span></h2>', page)
        self.assertIn(html.escape(history.column_title(h.costs.columns[-1])), page)

    def test_the_export_is_written_where_asked_then_opened(self):
        h = history_model.compute(self.machine.paths, "7d", now=NOW)
        self.assertEqual(history_model.export_name(h), "windowtally-history-7d-2026-10-21.html")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "out" / history_model.export_name(h)
            opened = []
            outcome = actions_model.export_history(h, path, opened.append)
            self.assertTrue(outcome.ok, outcome.message)
            self.assertEqual(path.read_text(encoding="utf-8"), render_history(h))
            self.assertEqual(opened, [path.resolve().as_uri()])

            def refuse(_url):
                raise OSError("no browser")
            outcome = actions_model.export_history(h, path, refuse)
            self.assertFalse(outcome.ok)
            self.assertIn("it was not opened: no browser", outcome.message)
            self.assertTrue(path.exists(), "the file stays written when only opening it failed")

            # Whether a refused write was waited for is read from the writer's retry pause, not from a clock: rendering
            # and writing the page take what the machine's load gives them.
            with mock.patch.object(files, "time", wraps=files.time) as clock:
                outcome = actions_model.export_history(h, Path(folder), opened.append)   # a folder, not a file
            clock.sleep.assert_not_called()   # a refused write is not waited for on the window's thread
            self.assertFalse(outcome.ok)
            self.assertTrue(outcome.message.startswith("Not exported: "), outcome.message)

            with mock.patch.object(actions_model, "render_history", side_effect=ValueError("no columns")):
                outcome = actions_model.export_history(h, path, opened.append)
            self.assertEqual((outcome.ok, outcome.message), (False, "Not exported: no columns"))

    def test_the_export_says_what_the_window_says_of_the_subscriptions(self):
        page = render_history(history_model.compute(self.machine.paths, "30d", now=NOW))
        self.assertIn("<th>Bills</th>", page)
        self.assertNotIn("<th class=\"l\">Profile</th>", page, "the window reads no profile")
        empty = Machine()
        try:
            empty.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
            run_pass(empty.paths, now=NOW, dashboard=False)
            page = render_history(history_model.compute(empty.paths, "7d", now=NOW))
        finally:
            empty.close()
        self.assertIn(html.escape(history.NO_BILLS_NOTE), page)
        self.assertNotIn("python -m windowtally", page)


class SharedEmailTest(unittest.TestCase):
    """Two of WindowTally's accounts share one e-mail, and only the second's profile is still on this machine."""

    def test_the_window_names_the_subscription_as_the_page_does(self):
        first, second = "a0a0a0a0-0000-4000-8000-000000000011", "a1a1a1a1-0000-4000-8000-000000000012"
        machine = Machine()
        try:
            machine.add_account(first, "shared@example.com", "0c0c0c0c-0000-4000-8000-0000000000c1")
            machine.add_account(second, "shared@example.com", "0c0c0c0c-0000-4000-8000-0000000000c2")
            machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
            machine.bills_file([bill("shared@example.com", "2026-10-07", 90.0, plan="max5x",
                                     period="2026-10-07..2026-11-07")])
            run_pass(machine.paths, now=NOW, dashboard=False)
            shutil.rmtree(machine.paths.accounts_dir / first)        # the ledger keeps the account; its profile is gone
            page = run_pass(machine.paths, now=NOW, dashboard=False).billing
            window = history_model.compute(machine.paths, "30d", now=NOW).subscriptions.summary
            page_uuid = next(s.uuid for s in page.subscriptions if s.email == "shared@example.com")
            window_uuid = next(r.subscription.uuid for r in window if r.subscription.email == "shared@example.com")
            self.assertEqual((page_uuid, window_uuid), (second, second))
        finally:
            machine.close()


class SharedTicksTest(unittest.TestCase):
    def test_the_figures_layer_s_ticks_are_days_then_mondays_then_months(self):
        start = history.local_midnight(date(2026, 10, 15)).timestamp()
        self.assertEqual([label for _t, label in history.time_ticks(start, start + 6.5 * DAY)],
                         ["Thu 15", "Fri 16", "Sat 17", "Sun 18", "Mon 19", "Tue 20", "Wed 21"])
        self.assertEqual([label for _t, label in history.time_ticks(start, start + 30 * DAY)],
                         ["Oct 19", "Oct 26", "Nov 02", "Nov 09"])
        months = history.time_ticks(history.local_midnight(date(2026, 4, 21)).timestamp(), NOW)
        self.assertEqual([label for _t, label in months], ["May 26", "Jun 26", "Jul 26", "Aug 26", "Sep 26", "Oct 26"])


class PlotLayoutTest(unittest.TestCase):
    margins = Margins(left=40, right=10, top=10, bottom=30)

    def test_a_line_steps_and_breaks_where_the_readings_stop(self):
        plot = LinePlot((Series("alpha", "series-1", ((0.0, 0.0), (10.0, 50.0), (100.0, 20.0))),), (),
                        (0.0, 100.0), (0.0, 100.0), (), ((0.0, "0%"), (100.0, "100%")), 30.0)
        marks = layout_line(plot, 150, 140, self.margins, measure)
        # The plot spans x 40..140 and y 110..10: the first run steps right, then up; the last point stands alone.
        self.assertEqual(marks.lines[0].points, (40.0, 110.0, 50.0, 110.0, 50.0, 60.0))
        self.assertEqual([(d.x, d.y, d.ringed) for d in marks.dots], [(140.0, 90.0, False)])
        self.assertEqual(marks.grid, (110.0, 10.0))

    def test_a_marker_is_ringed_and_says_what_it_marks(self):
        plot = LinePlot((), (Marker(50.0, 50.0, "series-2", "alpha: extra reset"),), (0.0, 100.0), (0.0, 100.0), (),
                        (), None)
        dot = layout_line(plot, 150, 140, self.margins, measure).dots[0]
        self.assertEqual((dot.x, dot.y, dot.ringed, dot.hover), (90.0, 60.0, True, "alpha: extra reset"))

    def test_columns_stack_from_the_baseline_with_a_gap_and_skip_empty_segments(self):
        plot = ColumnPlot(("a", "b"), (ColumnStack("x", "series-1", (10.0, 0.0), ("a·x", "b·x")),
                                       ColumnStack("y", "series-2", (10.0, 20.0), ("a·y", "b·y"))),
                          20.0, ((0.0, "$0"), (20.0, "$20")))
        marks = layout_columns(plot, 240, 130, self.margins, measure)
        first, second, only = marks.boxes
        self.assertEqual((first.hover, second.hover, only.hover), ("a·x", "a·y", "b·y"))
        self.assertEqual((first.y1, first.y0), (100.0, 56.0))        # the lower segment's top gives 1 px
        self.assertEqual((second.y1, second.y0), (54.0, 10.0))       # the upper's bottom gives 1 px
        self.assertEqual((only.y0, only.y1), (10.0, 100.0))          # alone in its column, nothing given
        self.assertLessEqual(first.x1 - first.x0, 24.0)

    def test_tick_labels_that_would_overlap_are_left_out(self):
        plot = ColumnPlot(tuple(f"10-{d:02d}" for d in range(1, 31)),
                          (ColumnStack("x", "series-1", tuple(1.0 for _ in range(30)), tuple("" for _ in range(30))),),
                          1.0, ())
        marks = layout_columns(plot, 400, 130, self.margins, measure)
        shown = [label.x for label in marks.labels]
        self.assertLess(len(shown), 30)
        self.assertTrue(all(b - a >= 35 + 8 for a, b in zip(shown, shown[1:])))


    def test_only_a_stack_s_top_segment_is_its_data_end(self):
        plot = ColumnPlot(("a", "b"), (ColumnStack("x", "series-1", (10.0, 0.0), ("a·x", "b·x")),
                                       ColumnStack("y", "series-2", (10.0, 20.0), ("a·y", "b·y"))),
                          20.0, ((0.0, "$0"), (20.0, "$20")))
        first, second, only = layout_columns(plot, 240, 130, self.margins, measure).boxes
        self.assertEqual((first.end, second.end, only.end), (False, True, True))

    def test_a_top_segment_too_thin_to_draw_leaves_the_data_end_to_the_one_under_it(self):
        plot = ColumnPlot(("a",), (ColumnStack("x", "series-1", (200.0,), ("a·x",)),
                                   ColumnStack("y", "series-2", (0.01,), ("a·y",))), 200.0, ())
        boxes = layout_columns(plot, 240, 130, self.margins, measure).boxes
        self.assertEqual([(box.hover, box.end) for box in boxes], [("a·x", True)])


class MarkAtTest(unittest.TestCase):
    """Which mark stands at a place, for a view that draws the marks itself."""
    margins = Margins(left=40, right=10, top=10, bottom=30)

    def line_marks(self):
        # The plot spans x 40..140 and y 110..10: alpha runs along y 60 from x 50 to x 140, then rises there to y 30;
        # beta lies on it from x 100 to x 120, and the marker at (70, 60).
        plot = LinePlot((Series("alpha", "series-1", ((10.0, 50.0), (100.0, 80.0))),
                         Series("beta", "series-2", ((60.0, 50.0), (80.0, 50.0)))),
                        (Marker(30.0, 50.0, "series-3", "extra reset"),), (0.0, 100.0), (0.0, 100.0), (), (), None)
        return layout_line(plot, 150, 140, self.margins, measure)

    def test_a_line_is_found_along_its_step_and_up_its_rise_and_nowhere_else(self):
        marks = self.line_marks()
        alpha = marks.lines[0]
        self.assertIs(mark_at(marks, 55.0, 60.0), alpha)
        self.assertIs(mark_at(marks, 55.0, 61.5), alpha, "half the stroke and the reach count")
        self.assertIsNone(mark_at(marks, 55.0, 63.0))
        self.assertIs(mark_at(marks, 140.0, 40.0), alpha, "the rise at the line's last point")
        self.assertIsNone(mark_at(marks, 45.0, 60.0), "the line starts at its first reading")

    def test_the_mark_drawn_last_answers_where_marks_overlap(self):
        marks = self.line_marks()
        self.assertIs(mark_at(marks, 110.0, 60.0), marks.lines[1], "the later series")
        dot = marks.dots[0]
        self.assertIs(mark_at(marks, dot.x, dot.y), dot, "a round mark before any line under it")

    def test_a_ringed_mark_answers_across_its_ring(self):
        marks = self.line_marks()
        dot = marks.dots[0]
        self.assertIs(mark_at(marks, dot.x, dot.y - dot.radius - marks.ring), dot)
        self.assertIsNone(mark_at(marks, dot.x, dot.y - dot.radius - marks.ring - marks.reach - 1))

    def test_a_column_answers_inside_it_only(self):
        plot = ColumnPlot(("a",), (ColumnStack("x", "series-1", (10.0,), ("a·x",)),), 10.0, ())
        marks = layout_columns(plot, 240, 130, self.margins, measure)
        box = marks.boxes[0]
        self.assertIs(mark_at(marks, (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2), box)
        self.assertIsNone(mark_at(marks, box.x0 - 1, box.y1 - 1))

    def test_a_line_of_thousands_of_points_is_searched_from_where_the_pointer_stands(self):
        class Counted(tuple):
            reads = 0

            def __getitem__(self, index):
                type(self).reads += 1
                return super().__getitem__(index)

        points = [0.0, 50.0]
        for x in range(1, 20000):
            points += [float(x), points[-1], float(x), float(x % 7)]
        marks = Marks((), 100.0, 0.0, 20000.0, (), lines=(Line("series-1", Counted(points), "alpha"),))
        self.assertIsNone(mark_at(marks, 1000.5, 90.0))
        self.assertIs(mark_at(marks, 1000.5, 6.0), marks.lines[0])
        self.assertLess(Counted.reads, 200, "a pointer's move reads a few segments, not the line")


class PlotScaleTest(unittest.TestCase):
    """At 200 % every stroke, radius, gap and offset is twice its size at 100 %; where the data stands is not."""
    margins = Margins(left=40, right=10, top=10, bottom=30)

    def test_a_line_chart_s_marks_grow_with_the_display_scale(self):
        plot = LinePlot((Series("alpha", "series-1", ((0.0, 0.0), (10.0, 50.0), (100.0, 20.0))),),
                        (Marker(50.0, 50.0, "series-2", "alpha: extra reset"),), (0.0, 100.0), (0.0, 100.0),
                        ((50.0, "mid"),), ((0.0, "0%"), (100.0, "100%")), 30.0)
        single = layout_line(plot, 150, 140, self.margins, measure)
        double = layout_line(plot, 150, 140, self.margins, measure, scale=2.0)
        self.assertEqual(double.lines, single.lines)
        self.assertEqual([(d.x, d.y) for d in double.dots], [(d.x, d.y) for d in single.dots])
        self.assertEqual([d.radius for d in single.dots], [3.0, 4.0])
        self.assertEqual([d.radius for d in double.dots], [6.0, 8.0])
        self.assertEqual((double.line_width, double.hairline, double.ring), (4.0, 2.0, 4.0))
        self.assertEqual((single.line_width, single.hairline, single.ring), (2.0, 1.0, 2.0))
        value, position = double.labels[0], double.labels[-1]
        self.assertEqual((value.x, value.anchor), (40 - 12, "e"))
        self.assertEqual((position.y, position.anchor), (110 + 8, "n"))

    def test_a_column_chart_s_gap_and_tick_spacing_grow_with_the_display_scale(self):
        plot = ColumnPlot(("a", "b"), (ColumnStack("x", "series-1", (10.0, 0.0), ("a·x", "b·x")),
                                       ColumnStack("y", "series-2", (10.0, 20.0), ("a·y", "b·y"))),
                          20.0, ((0.0, "$0"), (20.0, "$20")))
        first, second, _only = layout_columns(plot, 240, 130, self.margins, measure, scale=2.0).boxes
        self.assertEqual((first.y1, first.y0), (100.0, 57.0))        # the lower segment's top gives 2 px
        self.assertEqual((second.y1, second.y0), (53.0, 10.0))       # the upper's bottom gives 2 px
        many = ColumnPlot(tuple(f"10-{d:02d}" for d in range(1, 31)),
                          (ColumnStack("x", "series-1", tuple(1.0 for _ in range(30)), tuple("" for _ in range(30))),),
                          1.0, ())
        shown = [label.x for label in layout_columns(many, 400, 130, self.margins, measure, scale=2.0).labels]
        self.assertTrue(all(b - a >= 35 + 16 for a, b in zip(shown, shown[1:])))


class TableLayoutTest(unittest.TestCase):
    def test_columns_fit_their_widest_text_and_figures_stand_at_the_right(self):
        marks = layout_table((("Account", "w"), ("Cost", "e")), (("alpha", "$1.00"), ("Total", "$1.00")), (1,),
                             lambda text: 7.0 * len(text), lambda text: 8.0 * len(text), 30.0, 20.0, 25.0)
        self.assertEqual(marks.edges, (0.0, 79.0, 149.0))              # widest + room: 49 + 30, 40 + 30
        self.assertEqual((marks.width, marks.height, marks.heading_height), (149.0, 70.0, 20.0))
        self.assertEqual([(c.x, c.y, c.text, c.anchor) for c in marks.headings],
                         [(15.0, 10.0, "Account", "w"), (134.0, 10.0, "Cost", "e")])
        self.assertEqual([(c.x, c.y, c.text, c.anchor, c.bold) for c in marks.cells],
                         [(15.0, 32.5, "alpha", "w", False), (134.0, 32.5, "$1.00", "e", False),
                          (15.0, 57.5, "Total", "w", True), (134.0, 57.5, "$1.00", "e", True)])

    def test_a_wider_width_is_shared_among_the_columns_in_proportion_to_their_widths(self):
        marks = layout_table((("Account", "w"), ("Cost", "e")), (("alpha", "$1.00"), ("Total", "$1.00")), (1,),
                             lambda text: 7.0 * len(text), lambda text: 8.0 * len(text), 30.0, 20.0, 25.0, width=298.0)
        self.assertEqual(marks.edges, (0.0, 158.0, 298.0))             # 79 and 70 doubled, as 149 is
        self.assertEqual(marks.width, 298.0)
        self.assertEqual([(c.x, c.anchor) for c in marks.headings], [(15.0, "w"), (283.0, "e")])
        self.assertEqual([(c.x, c.text) for c in marks.cells[:2]], [(15.0, "alpha"), (283.0, "$1.00")])

    def test_a_narrower_width_leaves_the_columns_as_wide_as_they_need(self):
        marks = layout_table((("Account", "w"), ("Cost", "e")), (("alpha", "$1.00"),), (),
                             lambda text: 7.0 * len(text), lambda text: 8.0 * len(text), 30.0, 20.0, 25.0, width=100.0)
        self.assertEqual((marks.edges, marks.width), ((0.0, 79.0, 149.0), 149.0))


    def test_the_table_view_keeps_the_model_s_rule_for_the_totals_kept_below_the_rows(self):
        from windowtally_gui import table_view
        self.assertIs(table_view.trailing_totals, trailing_totals)


class TileLayoutTest(unittest.TestCase):
    def test_the_widest_tile_sets_the_columns_of_one_width_and_every_tile_takes_one(self):
        # The widest tile's least width, 230, leaves room for two columns of 240 with a gap of 10 in 490, at 0 and
        # 250; the six tiles take three rows in their order, the first as tall as its taller second tile.
        marks = layout_tiles(((100, 50), (100, 60), (100, 50), (100, 50), (100, 50), (230, 50)), 490, 10)
        self.assertEqual(marks.columns, 2)
        self.assertEqual(marks.places, (TilePlace(0, 0, 240, 60), TilePlace(250, 0, 240, 60),
                                        TilePlace(0, 70, 240, 50), TilePlace(250, 70, 240, 50),
                                        TilePlace(0, 130, 240, 50), TilePlace(250, 130, 240, 50)))
        self.assertEqual(marks.height, 180)

    def test_a_width_narrower_than_the_tiles_gives_one_column_as_wide_as_it(self):
        marks = layout_tiles(((100, 30), (120, 30)), 80, 10)
        self.assertEqual(marks.places, (TilePlace(0, 0, 80, 30), TilePlace(0, 40, 80, 30)))

    def test_no_tiles_take_no_room(self):
        self.assertEqual((layout_tiles((), 400, 10).places, layout_tiles((), 400, 10).height), ((), 0))


if __name__ == "__main__":
    unittest.main()
