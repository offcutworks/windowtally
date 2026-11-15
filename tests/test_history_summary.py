"""The summary at the head of the History window and the history page: the figures most looked at over the span shown.

The expectations are worked from the maintainer's decisions (PROJECT.md, *Decisions*, 2026-10-23): the API-equivalent
cost in all and per day elapsed, today counted by the part of it gone; the plans' cost at list price on the bills' UTC
days that fall on the span's dates, with the API-equivalent cost as a multiple of it; each account's share of the
API-equivalent cost, the use with no known account a share of its own; the costliest model family with its share; the
hours with every account exhausted; the history page's thirty days counted on the cost charts' local days, so the
summary's total is what the tables add up to; and a first week the span begins inside saying from when it counts.
"""

import unittest
from datetime import date, timedelta
from fractions import Fraction
from html import escape

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bill,
                      bridge_line, epoch)
from windowtally import history
from windowtally.accounts import load_registry
from windowtally.billing import billing_report
from windowtally.bills import load_bills
from windowtally.ledger import Ledger
from windowtally.service import run_pass
from windowtally.timeutil import local_datetime
from windowtally_gui import history_model
from windowtally_gui.history_model import Heading, Tiles

NOW = epoch("2026-10-21T18:30:00Z")
DAY = 86400.0
ALPHA = history.Entity(ACCOUNT_A, "alpha", "series-1")
BETA = history.Entity(ACCOUNT_B, "beta", "series-2")


def costs_of(entries: dict[history.Entity, dict[str, float]]) -> history.Costs:
    """One day's costs, each entity's by family."""
    column = (history.Column(date(2026, 10, 21), date(2026, 10, 21)),)
    families = tuple(history.EntityCosts(entity, tuple(history.Stack(f, "series-5", (v,)) for f, v in by.items()))
                     for entity, by in entries.items())
    accounts = tuple(history.Stack(e.label, e.token, (sum(by.values()),)) for e, by in entries.items())
    return history.Costs(column, accounts, families)


class FiguresTest(unittest.TestCase):
    def test_shares_follow_the_accounts_and_unknown_use_is_a_share_of_its_own(self):
        costs = costs_of({BETA: {"Opus": 30.0, "Sonnet": 10.0}, history.UNATTRIBUTED: {"Sonnet": 60.0}})
        s = history.summary(None, {}, [ALPHA, BETA], costs, None, date(2026, 10, 21), NOW, weeks=())
        self.assertEqual(s.api, 100.0)
        self.assertEqual([(x.entity.label, x.cost) for x in s.shares],
                         [("alpha", 0.0), ("beta", 40.0), ("no known account", 60.0)])
        self.assertEqual(s.family, ("Sonnet", 70.0))
        tiles = {t.caption: t.figure for t in history.summary_tiles(s)}
        self.assertEqual((tiles["alpha's share"], tiles["beta's share"], tiles["no known account's share"]),
                         ("0%", "40%", "60%"))
        self.assertEqual(tiles["Top model family"], "Sonnet · 70%")

    def test_without_priced_use_or_bills_the_tiles_say_so(self):
        s = history.summary(None, {}, [ALPHA], costs_of({}), None, date(2026, 10, 21), NOW, weeks=())
        self.assertEqual([(t.caption, t.figure) for t in history.summary_tiles(s)],
                         [("API-equivalent cost", "$0.00"), ("API-equivalent per day", "$0.00"),
                          ("alpha's share", "—"), ("Top model family", "—"), ("Hours all exhausted", "no data")])

    def test_the_multiple_stands_only_where_the_plans_cost_something(self):
        base = dict(api=1234.5, days=10.0, shares=(), family=None, exhausted=2.25)
        words = [(t.caption, t.figure) for t in history.summary_tiles(history.Summary(plans=Fraction(600), **base))]
        self.assertEqual(words[:4], [("API-equivalent cost", "$1,234"), ("API-equivalent per day", "$123.45"),
                                     ("Plans at list price", "$600.00"), ("API-equivalent ÷ plans", "2.1×")])
        self.assertEqual(words[-1], ("Hours all exhausted", "2.2 h"))
        captions = [t.caption for t in history.summary_tiles(history.Summary(plans=Fraction(0), **base))]
        self.assertIn("Plans at list price", captions)
        self.assertNotIn("API-equivalent ÷ plans", captions)

    def test_the_days_elapsed_count_today_by_the_part_of_it_gone(self):
        today = local_datetime(NOW).date()
        midnight = history.local_midnight(today).timestamp()
        length = history.local_midnight(today + timedelta(days=1)).timestamp() - midnight
        self.assertAlmostEqual(history.days_elapsed(today - timedelta(days=29), NOW), 29 + (NOW - midnight) / length)
        self.assertEqual(history.days_elapsed(today - timedelta(days=6), midnight), 6.0)
        s = history.summary(None, {}, [ALPHA], costs_of({ALPHA: {"Opus": 87.0}}), None,
                            today - timedelta(days=29), NOW, weeks=())
        self.assertAlmostEqual(s.per_day, 87.0 / (29 + (NOW - midnight) / length))


class PlansCostTest(unittest.TestCase):
    """Max 5x for alpha from 7 September, renewed on 7 October; a top-up of beta's that counts in no figure."""

    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        self.ledger = Ledger.open(self.machine.paths.ledger_db)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def report(self):
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        self.ledger.upsert_accounts(registry)
        return billing_report(load_bills(self.machine.paths), self.ledger.known_accounts(), registry, self.ledger, NOW)

    def test_the_plans_cost_follows_the_span_s_dates(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-09-07", 90.0, plan="max5x", period="2026-09-07..2026-10-07"),
                                 bill(EMAIL_A, "2026-10-07", 90.0, plan="max5x", period="2026-10-07..2026-11-07"),
                                 bill(EMAIL_B, "2026-10-10", 15.0, kind="topup", plan=None)])
        billing = self.report()
        # 22 September to 21 October: 15 of September's 30 days at $100, and 15 of October's 31.
        self.assertEqual(history.plans_cost(billing, date(2026, 9, 22), date(2026, 10, 21)),
                         Fraction(100, 30) * 15 + Fraction(100, 31) * 15)
        self.assertEqual(history.plans_cost(billing, date(2026, 8, 1), date(2026, 9, 6)), 0)

    def test_a_period_cut_short_counts_only_its_days_in_effect(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-04-01", 90, plan="max5x", period="2026-04-01..2026-05-01"),
                                 bill(EMAIL_A, "2026-04-11", 133.33, plan="ultra", period="2026-04-11..2026-05-11")])
        billing = self.report()
        self.assertEqual(history.plans_cost(billing, date(2026, 4, 1), date(2026, 5, 10)),
                         Fraction(100) * 10 / 30 + 200)
        self.assertEqual(history.plans_cost(billing, date(2026, 4, 11), date(2026, 4, 20)), Fraction(200) * 10 / 30)

    def test_without_a_bill_source_there_is_no_plans_cost(self):
        self.assertIsNone(history.plans_cost(self.report(), date(2026, 9, 22), date(2026, 10, 21)))
        self.assertIsNone(history.plans_cost(None, date(2026, 9, 22), date(2026, 10, 21)))


class SurfacesTest(unittest.TestCase):
    """A machine a pass has written, with use on both accounts, times when both were at their limit, and bills."""

    @classmethod
    def setUpClass(cls):
        cls.machine = m = Machine()
        m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        m.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        m.app_history([(NOW - 20 * DAY + i * 3 * 3600, org, 100.0 if i % 40 == 39 else 0.0, 30.0)
                       for i in range(160) for org in (ORG_A, ORG_B)])
        for day in range(40):
            session = f"s{day}"
            owner = ACCOUNT_A if day % 2 else ACCOUNT_B
            m.transcript(session, [bridge_line(session, owner, ORG_A)]
                         + assistant_lines(f"m{day}", NOW - (40 - day) * DAY + 3600, session,
                                           model="claude-sonnet-5-5" if day % 3 else "claude-opus-5-5"))
        m.bills_file([bill(EMAIL_A, "2026-09-07", 90.0, plan="max5x", period="2026-09-07..2026-10-07"),
                      bill(EMAIL_A, "2026-10-07", 90.0, plan="max5x", period="2026-10-07..2026-11-07")])
        run_pass(m.paths, now=NOW, dashboard=True)
        cls.h = history_model.compute(m.paths, "30d", now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.machine.close()

    def test_the_total_is_what_the_cost_charts_and_the_usage_tables_add_up_to(self):
        s = self.h.summary
        self.assertGreater(s.api, 0)
        self.assertAlmostEqual(s.api, sum(sum(stack.values) for stack in self.h.costs.accounts))
        self.assertAlmostEqual(s.api, sum(r.cost or 0.0 for r in self.h.usage.models))
        self.assertAlmostEqual(s.api, sum(r.cost or 0.0 for r in self.h.usage.efforts))
        self.assertAlmostEqual(sum(x.cost for x in s.shares), s.api)
        self.assertEqual([x.entity for x in s.shares][:len(self.h.accounts)], list(self.h.accounts))

    def test_the_plans_cost_and_the_multiple_are_over_the_same_dates(self):
        s, first = self.h.summary, self.h.first
        self.assertEqual(s.plans, history.plans_cost(
            billing_report(load_bills(self.machine.paths), {}, {}, None, NOW), first, local_datetime(NOW).date()))
        self.assertAlmostEqual(s.multiple, s.api / float(s.plans))

    def test_the_hours_exhausted_are_the_table_s_over_the_span(self):
        s = self.h.summary
        self.assertGreater(s.exhausted, 0)
        self.assertAlmostEqual(s.exhausted, sum(week.hours for week in self.h.exhausted if week.known))

    def test_a_first_week_the_span_begins_inside_says_from_when_it_counts(self):
        ledger = Ledger.open_readonly(self.machine.paths.ledger_db)
        try:
            accounts = ledger.known_accounts().values()
            wednesday = history.local_midnight(date(2026, 10, 14)).timestamp()
            weeks = history.exhausted_weeks(ledger, accounts, wednesday, NOW)
            self.assertEqual(weeks[0].covered_from, wednesday)
            self.assertTrue(history.exhausted_text(weeks[0]).endswith("(from Wed 00:00)"))
            self.assertIsNone(weeks[1].covered_from)
            monday = history.local_midnight(date(2026, 10, 12)).timestamp()
            self.assertIsNone(history.exhausted_weeks(ledger, accounts, monday, NOW)[0].covered_from)
        finally:
            ledger.close()

    def test_the_window_opens_on_the_summary(self):
        blocks = history_model.blocks(self.h)
        self.assertEqual(blocks[0], Heading("Summary"))
        s, tiles = self.h.summary, blocks[1]
        self.assertIsInstance(tiles, Tiles)
        self.assertEqual(tiles.items, tuple((t.caption, t.figure) for t in history.summary_tiles(s)))
        self.assertEqual(len(tiles.bars), len(tiles.items), "a bar or none for every tile")
        self.assertTrue(s.shares and s.api > 0)
        barred = [(caption, bar) for (caption, _figure), bar in zip(tiles.items, tiles.bars) if bar is not None]
        self.assertEqual([caption for caption, _bar in barred], [f"{item.entity.label}'s share" for item in s.shares],
                         "no tile but an account's share has a bar")
        for (_caption, (share, token)), item in zip(barred, s.shares):
            self.assertAlmostEqual(share, item.cost / s.api)
            self.assertEqual(token, item.entity.token, "an account's share is drawn in the account's colour")
        self.assertAlmostEqual(sum(share for _caption, (share, _token) in barred), 1.0)
        self.assertEqual(blocks[2], Heading("Weekly use"), "no use by product here, so no hint")

    def test_the_page_shows_the_window_s_thirty_days_after_the_recommendation(self):
        page = self.machine.paths.dashboard_file.read_text(encoding="utf-8")
        head = page.index("<h2>Summary, last 30 days</h2>")
        self.assertLess(page.index('<p class="rec">'), head)
        self.assertLess(head, page.index("<h2>Weekly use, last six weeks"))
        tiles = page[head:page.index("<h2>Weekly use")]
        position = 0
        for tile in history.summary_tiles(self.h.summary):
            found = tiles.index(f'<div class="cap">{escape(tile.caption)}</div><div class="fig">{escape(tile.figure)}',
                                position)
            self.assertGreater(found, position)
            position = found


if __name__ == "__main__":
    unittest.main()
