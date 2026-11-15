"""history: the figures the history page and the window's History view both draw, over a range or a span."""

import unittest
from datetime import date, timedelta
from html import escape

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bill,
                      bridge_line, epoch)
from windowtally import history
from windowtally.accounts import by_org, load_registry
from windowtally.attribution import attribute
from windowtally.billing import billing_report
from windowtally.bills import load_bills
from windowtally.dashboard import render_dashboard
from windowtally.ingest_app_history import ingest_app_history
from windowtally.ingest_sync import ingest_sync_events
from windowtally.ingest_transcripts import ingest_transcripts
from windowtally.ledger import Ledger
from windowtally.limits import recommend, standings
from windowtally.timeutil import local_datetime

NOW = epoch("2026-10-21T18:30:00Z")
DAY = 86400.0
STRANGER = "dddddddd-0000-4000-8000-000000000004"


class SpanTest(unittest.TestCase):
    def test_seven_and_thirty_days_count_today(self):
        today = date(2026, 10, 21)
        self.assertEqual(history.first_day("7d", None, today), date(2026, 10, 15))
        self.assertEqual(history.first_day("30d", None, today), date(2026, 9, 22))

    def test_six_months_start_on_the_same_day_or_the_month_s_last(self):
        for today, first in ((date(2026, 10, 21), date(2026, 4, 21)), (date(2026, 8, 31), date(2026, 2, 28)),
                             (date(2026, 3, 31), date(2025, 9, 30)), (date(2026, 6, 15), date(2025, 12, 15)),
                             (date(2026, 12, 31), date(2026, 6, 30)), (date(2026, 1, 1), date(2025, 7, 1))):
            self.assertEqual(history.first_day("6mo", None, today), first, today)

    def test_all_starts_with_the_ledger_s_first_record(self):
        machine = Machine()
        ledger = Ledger.open(machine.paths.ledger_db)
        try:
            today = date(2026, 10, 21)
            self.assertEqual(history.first_day("all", ledger, today), today)
            machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
            machine.transcript("s1", [bridge_line("s1", ACCOUNT_A, ORG_A)]
                               + assistant_lines("m1", NOW - 40 * DAY, "s1"))
            ingest_transcripts(ledger, machine.paths.projects_dir)
            self.assertEqual(history.first_day("all", ledger, today), local_datetime(NOW - 40 * DAY).date())
        finally:
            ledger.close()
            machine.close()

    def test_an_unknown_span_is_refused(self):
        with self.assertRaises(ValueError):
            history.first_day("1y", None, date(2026, 10, 21))


class WordsTest(unittest.TestCase):
    def test_days_and_months_are_written_in_english(self):
        self.assertEqual(history.day_text(date(2026, 11, 7)), "Sat 07 Nov 2026")
        self.assertEqual(history.month_label("2026-01"), "Jan 26")
        self.assertEqual(history.day_month(date(2026, 9, 5)), "05 Sep")
        self.assertEqual(history.month_day(date(2026, 9, 5)), "Sep 05")

    def test_a_moment_reads_with_its_distance_within_six_days(self):
        self.assertTrue(history.when(NOW + 30, NOW).endswith("(just now)"))
        self.assertTrue(history.when(NOW + 2 * 3600 + 300, NOW).endswith("(in 2h 5m)"))
        self.assertTrue(history.when(NOW - 3 * DAY, NOW).endswith("(3d 0h ago)"))
        moment = local_datetime(NOW - 20 * DAY)
        self.assertEqual(history.when(NOW - 20 * DAY, NOW),
                         f"{history.MONTHS[moment.month - 1]} {moment.day:02d} {moment.hour:02d}:{moment.minute:02d}")
        self.assertEqual(history.when(None, NOW), "—")


class ByWeekTest(unittest.TestCase):
    def test_days_are_summed_into_weeks_from_monday(self):
        first = date(2026, 10, 7)                       # a Wednesday
        columns = tuple(history.Column(first + timedelta(days=i), first + timedelta(days=i)) for i in range(14))
        values = tuple(float(i + 1) for i in range(14))
        entity = history.Entity("a", "alpha", "series-1")
        costs = history.Costs(columns, (history.Stack("alpha", "series-1", values),),
                              (history.EntityCosts(entity, (history.Stack("Opus", "series-5", values),)),))
        weekly = history.by_week(costs)
        self.assertEqual([(c.first, c.last) for c in weekly.columns],
                         [(date(2026, 10, 7), date(2026, 10, 11)), (date(2026, 10, 12), date(2026, 10, 18)),
                          (date(2026, 10, 19), date(2026, 10, 20))])
        self.assertEqual(weekly.accounts[0].values, (15.0, 63.0, 27.0))
        self.assertEqual(weekly.families[0].families[0].values, (15.0, 63.0, 27.0))
        self.assertEqual(sum(weekly.accounts[0].values), sum(values))


class HistoryTest(unittest.TestCase):
    """The figures over a span, on a machine with two accounts, an account WindowTally does not know, and bills."""

    def setUp(self):
        self.machine = Machine()
        m = self.machine
        m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        m.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        samples = []
        for step in range(0, 60 * 8):                   # sixty days of samples, every three hours
            t = NOW - 60 * DAY + step * 3 * 3600
            samples.append((t, ORG_A, 10.0, (step % 56) * 1.5))
            samples.append((t + 60, ORG_B, 20.0, (step % 56) * 1.2))
        m.app_history(samples)
        events = []
        for day in range(50):
            owner = (ACCOUNT_A, ACCOUNT_B, STRANGER)[day % 3]
            session = f"s{day}"
            answered = NOW - (50 - day) * DAY + 3600
            # The app is on the session's owner when it answers — STRANGER included, an account with no profile here —
            # so its account of that moment takes the response.
            events.append((answered - 60, "desktop_account", owner))
            m.transcript(session, [bridge_line(session, owner, ORG_A)]
                         + assistant_lines(f"m{day}", answered, session,
                                           model="claude-sonnet-5-5" if day % 2 else "claude-opus-5-5"))
        m.sync_events(events)
        m.bills_file([bill(EMAIL_A, "2026-05-07", 90.0, plan="max5x", period="2026-05-07..2026-06-07"),
                      bill(EMAIL_A, "2026-10-07", 180.0, plan="ultra", period="2026-10-07..2026-11-07")])
        self.ledger = Ledger.open(m.paths.ledger_db)
        self.registry, _ = load_registry(m.paths.accounts_dir)
        ingest_sync_events(self.ledger, m.paths.sync_events)
        ingest_app_history(self.ledger, m.paths.plan_usage_history, by_org(self.registry))
        ingest_transcripts(self.ledger, m.paths.projects_dir)
        attribute(self.ledger)
        self.ledger.upsert_accounts(self.registry)
        self.accounts = self.ledger.known_accounts()
        self.billing = billing_report(load_bills(m.paths), self.accounts, self.registry, self.ledger, NOW)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def of(self, key: str) -> history.History:
        return history.history(self.ledger, self.accounts, history.SPAN_OF[key], NOW, billing=self.billing,
                               errors=["transcripts: denied"])

    def test_a_span_ranges_every_section_but_the_subscriptions(self):
        today = local_datetime(NOW).date()
        week, month = self.of("7d"), self.of("30d")
        self.assertEqual(len(week.costs.columns), 7)
        self.assertEqual(len(month.costs.columns), 30)
        self.assertEqual(month.costs.columns[-1].last, today)
        self.assertGreaterEqual(week.weekly.start, history.local_midnight(week.first).timestamp())
        self.assertLess(month.weekly.start, week.weekly.start)
        self.assertEqual(week.exhausted[0].monday, week.first - timedelta(days=week.first.weekday()))
        self.assertLess(sum(r.responses for r in week.usage.models), sum(r.responses for r in month.usage.models))
        self.assertEqual(week.subscriptions, month.subscriptions)
        self.assertEqual(week.subscriptions.costs.months, ("2026-05", "2026-06", "2026-07", "2026-08", "2026-09",
                                                           "2026-10", "2026-11"))

    def test_long_spans_count_cost_per_week(self):
        for key, weekly in (("7d", False), ("30d", False), ("6mo", True), ("all", True)):
            h = self.of(key)
            self.assertEqual(h.by_week, weekly, key)
            if weekly:
                self.assertTrue(all(c.first.weekday() == 0 for c in h.costs.columns[1:]), key)
        days = history.daily_costs(self.ledger, list(self.of("all").accounts), self.of("all").first,
                                   local_datetime(NOW).date())
        self.assertAlmostEqual(sum(sum(s.values) for s in self.of("all").costs.accounts),
                               sum(sum(s.values) for s in days.accounts))

    def test_accounts_wear_the_page_s_colours_and_unknown_use_is_grey(self):
        h = self.of("30d")
        self.assertEqual([(e.label, e.token) for e in h.accounts], [("alpha", "series-1"), ("beta", "series-2")])
        self.assertEqual([(s.label, s.token) for s in h.costs.accounts],
                         [("alpha", "series-1"), ("beta", "series-2"), ("no known account", "muted")])

    def test_use_by_an_account_windowtally_does_not_know_is_counted_as_having_none(self):
        items = self.of("30d").coverage
        stranger = self.ledger.db.execute("SELECT COUNT(*) FROM responses WHERE account_uuid=?",
                                          (STRANGER,)).fetchone()[0]
        self.assertGreater(stranger, 0)
        self.assertIn(f"{stranger:,} responses have no known account.", items)
        self.assertIn("Source problem: transcripts: denied", items)

    def test_the_page_says_what_the_figures_say(self):
        current = standings(self.ledger, self.accounts.values(), NOW)
        page = render_dashboard(self.ledger, self.accounts, current, recommend(current), NOW, ["transcripts: denied"],
                                self.billing)
        figures = self.of("30d")
        for item in figures.coverage:
            self.assertIn(escape(item), page)
        for row in figures.subscriptions.periods:
            self.assertIn(escape(row.began), page)
            self.assertIn(escape(row.in_effect), page)
        for heading, note in ((history.PLAN_COST_HEADING, history.COST_NOTE),
                              (history.EXHAUSTED_HEADING, history.EXHAUSTED_NOTE)):
            hint = escape(note)
            self.assertIn(f'<h2>{escape(heading)} <span class="help" tabindex="0" title="{hint}" aria-label="{hint}">'
                          f'?</span></h2>', page, "what the figures mean: the ? beside the heading")


class LocalDayTest(unittest.TestCase):
    def test_a_response_s_day_is_its_local_day_across_the_clock_changes(self):
        # Every minute of the two days around each change of the clock the European and US rules make in 2026 and 2027, in
        # whatever zone the suite runs: wherever the zone changes its clock then, the day is checked across it. The
        # two sides are two paths, the naive local time and the zone-aware one the rest of WindowTally displays.
        for day in ("2026-03-08", "2026-03-29", "2026-10-25", "2026-11-01", "2027-03-14", "2027-03-28",
                    "2027-10-31", "2027-11-07"):
            start = epoch(f"{day}T00:00:00Z") - DAY / 2
            for step in range(int(2 * DAY / 60)):
                moment = start + step * 60 + 0.25
                self.assertEqual(history._day(moment), local_datetime(moment).date().isoformat(), moment)


if __name__ == "__main__":
    unittest.main()
