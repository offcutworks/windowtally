"""Tokens over time: the token chart on the cost chart's columns, the tables by week and by calendar month with every
kind and the same responses' API-equivalent cost, the summary's token tile, on the history page, the History window
and its export; and the summary tiles standing one to a column.

The expectations are worked from the maintainer's decision of 2026-10-31 — tokens by week, by month and in total, the
unit a user thinks in — and from the choices made in building it: every kind shown, thinking inside output and counted
once, split by account, the page's months over the whole history.
"""

import unittest
from datetime import date, timedelta
from html import escape

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bridge_line,
                      epoch, laid_out, page_headings)
from windowtally import history
from windowtally.accounts import by_org, load_registry
from windowtally.attribution import attribute
from windowtally.dashboard import render_dashboard, render_history
from windowtally.ingest_app_history import ingest_app_history
from windowtally.ingest_sync import ingest_sync_events
from windowtally.ingest_transcripts import ingest_transcripts
from windowtally.ledger import Ledger
from windowtally.limits import recommend, standings
from windowtally.timeutil import local_datetime
from windowtally_gui import history_model
from windowtally_gui.history_model import Chart, Heading, Note, Switch, Table
from windowtally_gui.tiles_model import TilePlace, layout_tiles

NOW = epoch("2026-10-21T18:30:00Z")
DAY = 86400.0
STRANGER = "dddddddd-0000-4000-8000-000000000004"
# (days before NOW, owner, input, output, thinking, cache read, cache write): one response each, at noon UTC
RESPONSES = ((1, ACCOUNT_A, 3, 200, 50, 4000, 700), (2, ACCOUNT_B, 5, 100, 0, 2000, 300),
             (9, ACCOUNT_A, 7, 300, 90, 6000, 900), (3, STRANGER, 11, 40, 10, 500, 100),
             (95, ACCOUNT_B, 13, 60, 20, 800, 200))


def total(row) -> int:
    _days, _owner, i, o, _th, cr, cw = row
    return i + o + cr + cw


class TokensTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        m = self.machine
        m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        m.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        events = []
        for n, (days, owner, i, o, th, cr, cw) in enumerate(RESPONSES):
            answered = local_datetime(NOW - days * DAY).replace(hour=12, minute=0, second=0).timestamp()
            events.append((answered - 60, "desktop_account", owner))
            m.transcript(f"s{n}", [bridge_line(f"s{n}", owner, ORG_A)]
                         + assistant_lines(f"m{n}", answered, f"s{n}", outputs=(o,), input_tokens=i, thinking=th,
                                           cache_read=cr, cache_write_1h=cw))
        m.sync_events(events)
        self.ledger = Ledger.open(m.paths.ledger_db)
        registry, _ = load_registry(m.paths.accounts_dir)
        ingest_sync_events(self.ledger, m.paths.sync_events)
        ingest_app_history(self.ledger, m.paths.plan_usage_history, by_org(registry))
        ingest_transcripts(self.ledger, m.paths.projects_dir)
        attribute(self.ledger)
        self.ledger.upsert_accounts(registry)
        self.accounts = self.ledger.known_accounts()
        self.today = local_datetime(NOW).date()

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def of(self, key: str) -> history.History:
        return history.history(self.ledger, self.accounts, history.SPAN_OF[key], NOW, billing=None, errors=[])

    def test_the_span_s_tokens_are_every_kind_once_per_account_with_unknown_use_last(self):
        use = self.of("30d").tokens
        in_all = use.months.rows[-1]
        recent = [r for r in RESPONSES if r[0] < 30]
        self.assertEqual(in_all.period, "In all")
        # beta was seen first, its response 95 days back, so it leads, as it does in the cost chart.
        self.assertEqual(use.months.labels, ("beta", "alpha", "no known account"))
        self.assertEqual(in_all.accounts, (total(RESPONSES[1]), total(RESPONSES[0]) + total(RESPONSES[2]),
                                           total(RESPONSES[3])))
        t = in_all.tokens
        self.assertEqual((t.input, t.output, t.thinking, t.cache_read, t.cache_write),
                         tuple(sum(r[k] for r in recent) for k in (2, 3, 4, 5, 6)))
        self.assertEqual(t.total, sum(total(r) for r in recent), "thinking is counted inside output, once")
        self.assertEqual(use.total, t.total)
        self.assertEqual([(s.label, s.token) for s in use.accounts],
                         [("beta", "series-1"), ("alpha", "series-2"), ("no known account", "muted")])

    def test_the_tokens_agree_with_the_models_table_and_the_cost_chart(self):
        h = self.of("30d")
        models = h.usage.models
        in_all = h.tokens.weeks.rows[-1]
        self.assertEqual(in_all.tokens.output, sum(r.output for r in models))
        self.assertEqual(in_all.tokens.cache_read, sum(r.cache_read for r in models))
        self.assertAlmostEqual(in_all.cost, sum(sum(s.values) for s in h.costs.accounts))
        self.assertEqual(h.tokens.columns, h.costs.columns)

    def test_weeks_run_from_monday_and_months_by_the_calendar(self):
        use = self.of("30d").tokens
        weeks = [r.period for r in use.weeks.rows[:-1]]
        first = self.of("30d").first
        self.assertEqual(weeks[0], f"week of {(first - timedelta(days=first.weekday())).isoformat()}")
        self.assertTrue(all(date.fromisoformat(w[8:]).weekday() == 0 for w in weeks))
        self.assertEqual(weeks, sorted(weeks))
        self.assertEqual([r.period for r in use.months.rows], ["2026-09", "2026-10", "In all"])
        self.assertEqual(sum(sum(r.accounts) for r in use.weeks.rows[:-1]), sum(use.weeks.rows[-1].accounts))

    def test_long_spans_chart_tokens_per_week_and_all_reaches_the_first_response(self):
        h = self.of("all")
        self.assertTrue(h.by_week)
        self.assertEqual(h.tokens.columns, h.costs.columns)
        self.assertEqual(h.tokens.months.rows[-1].tokens.total, sum(total(r) for r in RESPONSES))
        self.assertEqual(h.summary.tokens, sum(total(r) for r in RESPONSES))

    def test_a_span_without_responses_says_so(self):
        empty = history.token_use(self.ledger, list(self.of("7d").accounts), (self.today, self.today),
                                  (self.today, self.today), (self.today, self.today), False)
        self.assertEqual((empty.accounts, empty.total, empty.weeks.rows, empty.months.rows), ((), 0, (), ()))

    def test_the_summary_shows_the_span_s_tokens(self):
        h = self.of("30d")
        tiles = [(t.caption, t.figure) for t in history.summary_tiles(h.summary)]
        self.assertIn(("Tokens", history.count(sum(total(r) for r in RESPONSES if r[0] < 30))), tiles)

    def test_the_window_shows_the_tokens_after_the_cost_and_marks_each_table_s_total(self):
        h = self.of("30d")
        blocks = history_model.blocks(h)
        at = {b.key: i for i, b in enumerate(blocks) if isinstance(b, Switch)}
        columns, tables = blocks[at[history.COLUMNS_SWITCH]], blocks[at[history.TOKEN_TABLES_SWITCH]]
        _cost, tokens = columns.views
        self.assertEqual([(v.choice, v.heading.text) for v in columns.views],
                         list(zip(history.SWITCH_VIEWS[history.COLUMNS_SWITCH],
                                  ["API-equivalent cost per day", "Tokens per day"])), "the tokens after the cost")
        self.assertEqual(tokens.heading, Heading("Tokens per day", history.TOKENS_NOTE))
        self.assertEqual([(v.choice, v.heading.text) for v in tables.views],
                         [(word, history.TOKENS_BY) for word in history.SWITCH_VIEWS[history.TOKEN_TABLES_SWITCH]])
        self.assertLess(at[history.COLUMNS_SWITCH], at[history.TOKEN_TABLES_SWITCH])
        after = next(b for b in blocks[at[history.TOKEN_TABLES_SWITCH] + 1:] if isinstance(b, Heading))
        self.assertEqual(after.text, "Subscriptions")
        _week, month = tables.views
        table = month.blocks[0]
        self.assertIsInstance(table, Table)
        self.assertEqual([c[0] for c in table.columns],
                         ["Month", "beta", "alpha", "no known account"] + list(history.TOKEN_COLUMNS))
        self.assertEqual(table.totals, (len(table.rows) - 1,))
        self.assertEqual(table.rows[-1][0], "In all")
        chart = tokens.blocks[1]                  # after its legend
        self.assertIsInstance(chart, Chart)
        self.assertEqual(chart.plot.y_ticks[-1][1], history.count(chart.plot.y_ticks[-1][0]))
        self.assertNotIn(history.TOKENS_NOTE, [b.text for b in laid_out(blocks) if isinstance(b, Note)],
                         "what each kind of token counts is the heading's hint, never text at rest")

    def test_the_export_carries_the_tokens_as_the_window_shows_them(self):
        h = self.of("6mo")
        page = render_history(h)
        hint = escape(history.TOKENS_NOTE)
        cost, tokens = (escape(word) for word in history.SWITCH_VIEWS[history.COLUMNS_SWITCH])
        self.assertIn(f'<h2>Tokens per week <span class="seg"><label for="switch-columns-0">{cost}</label>'
                      f'<label for="switch-columns-1" class="on">{tokens}</label></span> <span class="help" '
                      f'tabindex="0" title="{hint}" aria-label="{hint}">?</span></h2>', page)
        for row in h.tokens.months.rows:
            self.assertIn(escape(row.period), page)
            for cell in history.token_cells(row):
                self.assertIn(escape(cell), page)

    def test_the_page_tables_six_weeks_and_every_month_since_the_first_response(self):
        current = standings(self.ledger, self.accounts.values(), NOW)
        page = render_dashboard(self.ledger, self.accounts, current, recommend(current), NOW, [], None)
        found = [(before, words, after) for before, words, after, _hint in page_headings(page)]
        self.assertEqual(len(found), page.count("<h2>"), "every heading read, a switch and a hint beside it or none")
        columns = history.SWITCH_VIEWS[history.COLUMNS_SWITCH]
        tables = history.SWITCH_VIEWS[history.TOKEN_TABLES_SWITCH]
        at = found.index(("Tokens per day", columns, ""))
        self.assertEqual(found[at - 1], ("API-equivalent cost per day", columns, ""), "a pane per view, the cost first")
        switched = [(before, after) for before, words, after in found if words == tables]
        self.assertEqual(switched, [(history.TOKENS_BY, ", last six weeks"), (history.TOKENS_BY, ", whole history")])
        self.assertLess(at, found.index((history.TOKENS_BY, tables, ", last six weeks")))
        months = page[page.index("</span>, whole history"):]
        months = months[:months.index("</table>")]
        first = local_datetime(NOW - 95 * DAY).date()
        self.assertIn(f"{first.year:04d}-{first.month:02d}", months)
        self.assertIn(f"<b>{history.count(sum(total(r) for r in RESPONSES))}</b>", months)
        self.assertIn('<div class="cap">Tokens</div>', page)


class QuarterHourDayTest(unittest.TestCase):
    def test_a_quarter_hour_lies_in_one_local_day_across_the_clock_changes(self):
        # Every minute of the two days around each change of the clock the European and US rules make in 2026 and 2027,
        # in whatever zone the suite runs: a moment's quarter hour starts on the moment's own local day.
        for day in ("2026-03-08", "2026-03-29", "2026-10-25", "2026-11-01", "2027-03-14", "2027-03-28",
                    "2027-10-31", "2027-11-07"):
            start = epoch(f"{day}T00:00:00Z") - DAY / 2
            for step in range(int(2 * DAY / 60)):
                moment = start + step * 60 + 0.25
                quarter = int(moment // history.QUARTER_HOUR) * history.QUARTER_HOUR
                self.assertEqual(history._day(quarter), local_datetime(moment).date().isoformat(), moment)


class OneColumnTileTest(unittest.TestCase):
    def test_a_tile_wider_than_the_others_stands_in_one_column_like_them(self):
        # The widest tile's least width, 140, sets the columns: three of 156 with gaps of 10 fill 488 and hold the six
        # tiles in two rows; four would be 114 wide, too narrow for it.
        marks = layout_tiles(((100, 50), (100, 60), (100, 50), (100, 50), (100, 50), (140, 50)), 488, 10)
        self.assertEqual(marks.columns, 3)
        self.assertEqual({p.width for p in marks.places}, {156})
        self.assertEqual(marks.places[5], TilePlace(332, 70, 156, 50))
        self.assertEqual(marks.height, 120)

    def test_no_column_is_narrower_than_the_least_width_asked(self):
        marks = layout_tiles(tuple((60, 40) for _ in range(6)), 500, 10, least=160)
        self.assertEqual(marks.columns, 3)
        self.assertTrue(all(p.width >= 160 for p in marks.places))

    def test_of_the_counts_holding_the_fewest_rows_the_fewest_columns_are_taken(self):
        # Five columns fit and hold seven tiles in two rows; four hold them in two rows too, and fill them the more.
        marks = layout_tiles(tuple((50, 40) for _ in range(7)), 333, 10)
        self.assertEqual(marks.columns, 4)
        self.assertEqual(marks.places[3].x + marks.places[3].width, 333)
        self.assertEqual([(p.x, p.width) for p in marks.places[4:]], [(p.x, p.width) for p in marks.places[:3]])

    def test_a_width_narrower_than_the_widest_tile_gives_one_column_as_wide_as_it(self):
        marks = layout_tiles(((100, 30), (120, 30)), 80, 10, least=160)
        self.assertEqual(marks.places, (TilePlace(0, 0, 80, 30), TilePlace(0, 40, 80, 30)))


if __name__ == "__main__":
    unittest.main()
