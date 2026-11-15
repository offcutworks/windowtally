"""capacity: what a full window held per plan — the steps between readings, the rounding threshold, the plans the bills
give over time — and the section the history page and the window's History view show of it.

Expected values are derived by hand from the measure's rules (a full window holds 100 × dollars ÷ points over the
steps; a figure needs a rise of at least √chains ÷ 0.1 points), never read back from the code.
"""

import re
import unittest
from html import escape

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bill, epoch,
                      laid_out)
from windowtally import history
from windowtally.accounts import load_registry
from windowtally.billing import billing_report
from windowtally.bills import load_bills
from windowtally.capacity import Held, PlanSpan, differs, held, plan_spans, steps
from windowtally.ledger import Ledger
from windowtally.service import run_pass
from windowtally_gui import history_model
from windowtally_gui.history_model import Heading, Note, Switch, Table

MINUTE, HOUR, DAY = 60.0, 3600.0, 86400.0
T0 = epoch("2026-10-14T10:00:00Z")   # a Wednesday, so its local week begins on Monday 12 October in any zone near UTC
ULTRA = [PlanSpan(epoch("2026-10-01T00:00:00Z"), epoch("2026-11-01T00:00:00Z"), "ultra")]


class LedgerCase(unittest.TestCase):
    """A ledger written row by row: readings and responses of the accounts, nothing else."""

    def setUp(self):
        self.machine = Machine()
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        self.responses = 0

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def reading(self, t, percent, kind="five_hour", resets=None, source="plugin", account=ACCOUNT_A):
        self.ledger.db.execute(
            "INSERT INTO observations(source, ref, t, kind, percent, resets_at, account_uuid, account_source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'test')", (source, account, t, kind, float(percent), resets, account))

    def response(self, t, dollars, account=ACCOUNT_A):
        self.responses += 1
        self.ledger.db.execute(
            "INSERT INTO responses(message_id, t, session_id, input_tokens, output_tokens, thinking_tokens, "
            "cache_read_tokens, cache_write_5m_tokens, cache_write_1h_tokens, web_search_requests, web_fetch_requests, "
            "cost_usd, account_uuid) VALUES (?, ?, 's', 0, 0, 0, 0, 0, 0, 0, 0, ?, ?)",
            (f"m{self.responses}", t, dollars, account))

    def series(self, start, percents, *, kind="five_hour", resets=None, source="plugin", dollars=2.0,
               every=10 * MINUTE, account=ACCOUNT_A):
        """Readings every ``every`` from ``start``, each but the first a minute after a response of ``dollars``."""
        for index, percent in enumerate(percents):
            t = start + index * every
            if index:
                self.response(t - MINUTE, dollars, account)
            self.reading(t, percent, kind, resets, source, account)

    def steps(self, spans=None, since=T0 - DAY, until=T0 + DAY):
        return steps(self.ledger, spans or {ACCOUNT_A: ULTRA}, since, until)


class StepTest(LedgerCase):
    def test_a_full_window_is_the_dollars_over_the_rise_times_a_hundred(self):
        self.series(T0, [10, 14, 18, 22], resets=T0 + 4 * HOUR)
        found = self.steps()
        self.assertEqual([(s.plan, s.kind, s.points, s.dollars) for s in found], [("ultra", "five_hour", 4.0, 2.0)] * 3)
        self.assertEqual(len({s.chain for s in found}), 1)
        self.assertEqual(Held(12.0, 6.0, 1).full, 50.0)

    def test_inside_one_5_hour_window_a_fall_adds_nothing_and_ends_no_chain(self):
        # Every reading names the window's one end, which alone resets it: 19 and 22 trail another session's reading.
        # Each step counts how far it took the chain's highest reading, so the chain rises 25 - 20.
        self.series(T0, [20, 19, 25, 22], resets=T0 + 4 * HOUR)
        found = self.steps()
        self.assertEqual([s.points for s in found], [0.0, 5.0, 0.0])
        self.assertEqual(len({s.chain for s in found}), 1)

    def test_a_5_hour_fall_of_a_reset_s_size_between_samples_naming_no_end_ends_the_chain(self):
        # The app's samples name no window end, so 24 to 21, a fall of three points, is taken for a reset: two chains,
        # rising 4 and 5.
        self.series(T0, [20, 24, 21, 26], source="app")
        found = self.steps()
        self.assertEqual([s.points for s in found], [4.0, 5.0])
        self.assertEqual(len({s.chain for s in found}), 2)

    def test_readings_more_than_three_hours_apart_make_no_step(self):
        self.series(T0, [10, 20], every=3 * HOUR + 1, resets=T0 + 4.5 * HOUR)
        self.series(T0 + 5 * HOUR, [10, 20], every=3 * HOUR, resets=T0 + 9 * HOUR)
        self.assertEqual([s.t for s in self.steps()], [T0 + 8 * HOUR])

    def test_a_reading_at_the_cap_makes_no_step(self):
        self.series(T0, [90, 99], resets=T0 + 4 * HOUR)
        self.series(T0 + HOUR, [95, 98], resets=T0 + 4 * HOUR)
        self.assertEqual([s.points for s in self.steps()], [3.0])

    def test_no_step_spans_the_end_of_a_5_hour_window(self):
        # The first reading's window ends half an hour on; the second's began ten minutes after the first reading.
        self.series(T0, [20, 25], resets=T0 + 30 * MINUTE, every=40 * MINUTE)
        self.reading(T0 + 2 * HOUR, 20, resets=None)
        self.response(T0 + 2 * HOUR + 10 * MINUTE, 2.0)
        self.reading(T0 + 2 * HOUR + 20 * MINUTE, 25, resets=T0 + 2 * HOUR + 10 * MINUTE + 5 * HOUR)
        self.assertEqual(self.steps(), [])

    def test_without_reset_times_the_5_hour_window_rule_decides(self):
        # A's window opened with the response at T0 - 4h50m and ended at T0 + 10m, before its second sample; B's
        # opened at T0 - 1h and runs past both.
        spans = {ACCOUNT_A: ULTRA, ACCOUNT_B: ULTRA}
        for account, opened in ((ACCOUNT_A, T0 - 4 * HOUR - 50 * MINUTE), (ACCOUNT_B, T0 - HOUR)):
            self.response(opened, 1.0, account)
            self.series(T0, [20, 26], source="app", every=30 * MINUTE, account=account)
        self.assertEqual([s.account for s in self.steps(spans)], [ACCOUNT_B])

    def test_without_reset_times_the_weekly_anchor_decides(self):
        # A's plugin reading two days on puts its weekly reset at T0 + 1h, between its two samples; B has no reading
        # to say where its week begins, and two samples are no fall to infer it from.
        spans = {ACCOUNT_A: ULTRA, ACCOUNT_B: ULTRA}
        for account in (ACCOUNT_A, ACCOUNT_B):
            self.series(T0, [2, 4], kind="seven_day", source="app", every=2 * HOUR, account=account)
        self.reading(T0 + 2 * DAY, 30, kind="seven_day", resets=T0 + HOUR + 7 * DAY)
        self.assertEqual([s.account for s in self.steps(spans)], [ACCOUNT_B])

    def test_a_step_needs_responses_between_its_readings_every_one_priced(self):
        self.reading(T0, 10, resets=T0 + 4 * HOUR)
        self.reading(T0 + 10 * MINUTE, 15, resets=T0 + 4 * HOUR)                     # no response between
        self.response(T0 + 15 * MINUTE, None)
        self.reading(T0 + 20 * MINUTE, 20, resets=T0 + 4 * HOUR)                     # an unpriced one
        self.response(T0 + 25 * MINUTE, 3.0)
        self.response(T0 + 26 * MINUTE, None)
        self.reading(T0 + 30 * MINUTE, 25, resets=T0 + 4 * HOUR)                     # a priced and an unpriced one
        self.response(T0 + 35 * MINUTE, 3.0)
        self.reading(T0 + 40 * MINUTE, 30, resets=T0 + 4 * HOUR)
        self.assertEqual([(s.points, s.dollars) for s in self.steps()], [(5.0, 3.0)])

    def test_the_app_s_samples_and_the_plugin_s_readings_are_never_paired(self):
        # Samples until the first plugin reading; from it the readings alone, a later sample left out.
        self.series(T0, [10, 12], source="app")
        self.response(T0 + 19 * MINUTE, 2.0)
        self.reading(T0 + 20 * MINUTE, 14, resets=T0 + 4 * HOUR)
        self.response(T0 + 29 * MINUTE, 2.0)
        self.reading(T0 + 30 * MINUTE, 16, resets=T0 + 4 * HOUR)
        self.response(T0 + 39 * MINUTE, 2.0)
        self.reading(T0 + 40 * MINUTE, 17, source="app")
        self.response(T0 + 49 * MINUTE, 2.0)
        self.reading(T0 + 50 * MINUTE, 20, resets=T0 + 4 * HOUR)
        found = self.steps()
        self.assertEqual([(s.chain[2], s.points, s.dollars) for s in found],
                         [("app", 2.0, 2.0), ("plugin", 2.0, 2.0), ("plugin", 4.0, 4.0)])
        self.assertEqual(len({s.chain for s in found}), 2)

    def test_a_step_needs_one_plan_at_both_readings(self):
        change = epoch("2026-10-14T00:00:00Z")
        spans = {ACCOUNT_A: [PlanSpan(epoch("2026-10-01T00:00:00Z"), change, "max5x"),
                             PlanSpan(change + DAY, epoch("2026-11-01T00:00:00Z"), "ultra")]}
        self.series(change - 30 * MINUTE, [10, 20], every=HOUR, resets=change + 3 * HOUR)
        self.series(change - 2 * HOUR, [10, 20], every=HOUR, resets=change + 2 * HOUR)
        self.series(change + 2 * DAY, [10, 20], every=HOUR, resets=change + 2 * DAY + 3 * HOUR)
        self.assertEqual([s.plan for s in self.steps(spans, since=change - DAY, until=change + 3 * DAY)],
                         ["max5x", "ultra"])

    def test_only_steps_ending_in_the_range_are_taken(self):
        self.series(T0, [10, 14, 18], resets=T0 + 4 * HOUR)
        self.assertEqual([s.t for s in self.steps(since=T0 + 15 * MINUTE)], [T0 + 20 * MINUTE])

    def test_a_reading_trailing_the_one_before_adds_nothing_and_the_chain_goes_on(self):
        # Another session's reading a point low: each step counts the rise of the chain's highest reading, so the
        # chain rises by its highest reading less its first, 25 - 20.
        self.series(T0, [20, 22, 21, 25], resets=T0 + 4 * HOUR)
        found = self.steps()
        self.assertEqual([s.points for s in found], [2.0, 0.0, 3.0])
        self.assertEqual(len({s.chain for s in found}), 1)
        self.assertEqual(held(found), Held(5.0, 6.0, 1))

    def test_a_5_hour_fall_between_readings_naming_one_window_end_does_not_end_the_chain(self):
        # 24 to 20 is a fall of four points, but both readings name the window's one end: a trailing reading.
        self.series(T0, [20, 24, 20, 26], resets=T0 + 4 * HOUR)
        found = self.steps()
        self.assertEqual([s.points for s in found], [4.0, 0.0, 2.0])
        self.assertEqual(len({s.chain for s in found}), 1)

    def test_a_weekly_fall_of_a_reset_s_size_ends_the_chain_though_its_reset_time_holds(self):
        # 24 to 21 is a fall of three points: a reset outside the schedule. Two chains, rising 4 and 5.
        self.series(T0, [20, 24, 21, 26], kind="seven_day", resets=T0 + 3 * DAY)
        found = self.steps()
        self.assertEqual([s.points for s in found], [4.0, 5.0])
        self.assertEqual(len({s.chain for s in found}), 2)

    def test_a_cut_through_a_chain_counts_no_trailing_reading_twice(self):
        # From T0 + 15 min only the steps to 21 and to 25 are taken: 0 and 1, the chain's highest going 24 to 25.
        self.series(T0, [20, 24, 21, 25], resets=T0 + 4 * HOUR)
        self.assertEqual([s.points for s in self.steps(since=T0 + 15 * MINUTE)], [0.0, 1.0])

    def test_a_pair_with_no_response_between_counts_no_dollars_and_an_unpriced_response_ends_the_chain(self):
        self.reading(T0, 10, resets=T0 + 4 * HOUR)
        self.reading(T0 + 10 * MINUTE, 12, resets=T0 + 4 * HOUR)                     # no response between
        self.response(T0 + 15 * MINUTE, 3.0)
        self.reading(T0 + 20 * MINUTE, 15, resets=T0 + 4 * HOUR)
        self.response(T0 + 25 * MINUTE, None)
        self.reading(T0 + 30 * MINUTE, 18, resets=T0 + 4 * HOUR)                     # an unpriced one between
        found = self.steps()
        self.assertEqual([(s.points, s.dollars) for s in found], [(2.0, 0.0), (3.0, 3.0)])
        self.assertEqual(len({s.chain for s in found}), 1)


class RoundingTest(unittest.TestCase):
    def test_a_figure_needs_a_rise_of_ten_points_per_square_root_of_its_chains(self):
        self.assertIsNone(Held(9.0, 9.0, 1).full)
        self.assertEqual(Held(10.0, 9.0, 1).full, 90.0)
        self.assertIsNone(Held(14.0, 7.0, 2).full)            # 10 × √2 is 14.14
        self.assertEqual(Held(15.0, 7.5, 2).full, 50.0)
        self.assertIsNone(Held(0.0, 0.0, 0).full)

    def test_two_figures_differ_by_more_than_their_rounding(self):
        # 20 points in one chain: each figure may move by a twentieth of itself.
        fifty, thirty, forty_eight = Held(20.0, 10.0, 1), Held(20.0, 6.0, 1), Held(20.0, 9.6, 1)
        self.assertEqual((fifty.spread, thirty.spread), (2.5, 1.5))
        self.assertTrue(differs(fifty, thirty))
        self.assertFalse(differs(fifty, forty_eight))

    def test_a_week_is_marked_only_where_it_reads_differently_beyond_rounding(self):
        self.assertEqual(history._week_cell(Held(20.0, 6.0, 1), Held(20.0, 10.0, 1)), "$30 (lower)")
        self.assertEqual(history._week_cell(Held(20.0, 10.0, 1), Held(20.0, 6.0, 1)), "$50 (higher)")
        self.assertEqual(history._week_cell(Held(20.0, 9.6, 1), Held(20.0, 10.0, 1)), "$48")
        # $50.40 and $50.20 differ by more than their rounding (a twentieth of a dollar each) but both read $50.
        self.assertEqual(history._week_cell(Held(1000.0, 504.0, 1), Held(1000.0, 502.0, 1)), "$50")
        self.assertEqual(history._week_cell(Held(9.0, 9.0, 1), Held(20.0, 10.0, 1)), "—")
        self.assertEqual(history._week_cell(Held(20.0, 6.0, 1), None), "$30")

    def test_a_figure_below_ten_dollars_shows_its_cents(self):
        # $6.60 and $7.40 would both read $7 in whole dollars.
        self.assertEqual(history._week_cell(Held(40.0, 2.96, 1), Held(40.0, 2.64, 1)), "$7.40 (higher)")


class PlanSpanTest(unittest.TestCase):
    def test_spans_join_a_plan_s_periods_and_leave_out_the_day_it_began_or_changed(self):
        m = Machine()
        try:
            m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
            m.bills_file([bill(EMAIL_A, "2026-09-07", 100.0, plan="max5x", period="2026-09-07..2026-10-07"),
                          bill(EMAIL_A, "2026-09-20", 140.0, plan="ultra", period="2026-09-20..2026-10-20"),
                          bill(EMAIL_A, "2026-10-20", 200.0, plan="ultra", period="2026-10-20..2026-11-20"),
                          bill(EMAIL_A, "2026-12-01", 100.0, plan="max5x", period="2026-12-01..2027-01-01")])
            registry, _ = load_registry(m.paths.accounts_dir)
            report = billing_report(load_bills(m.paths), registry, registry, None, epoch("2026-10-21T12:00:00Z"))
        finally:
            m.close()
        self.assertEqual(report.problems, ())
        self.assertEqual(plan_spans(report)[ACCOUNT_A], [
            PlanSpan(epoch("2026-09-08T00:00:00Z"), epoch("2026-09-20T00:00:00Z"), "max5x"),
            PlanSpan(epoch("2026-09-21T00:00:00Z"), epoch("2026-11-20T00:00:00Z"), "ultra"),
            PlanSpan(epoch("2026-12-02T00:00:00Z"), epoch("2027-01-01T00:00:00Z"), "max5x")])


class SectionTest(LedgerCase):
    """The section's rows from a ledger and the bills: per plan over the range, and week by week."""

    def billing(self, bills):
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        if bills is not None:
            self.machine.bills_file(bills)
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        self.ledger.upsert_accounts(registry)
        self.accounts = self.ledger.known_accounts()
        return billing_report(load_bills(self.machine.paths), self.accounts, registry, self.ledger, T0 + 9 * DAY)

    def capacity(self, billing):
        shown = history.entities(self.ledger, self.accounts)
        return history.plan_capacity(self.ledger, shown, billing, epoch("2026-10-12T12:00:00Z"), T0 + 9 * DAY)

    def test_every_plan_has_its_row_and_a_week_lower_than_the_one_before_says_so(self):
        billing = self.billing([bill(EMAIL_A, "2026-10-01", 200.0, plan="ultra", period="2026-10-01..2026-11-01")])
        self.series(T0, [10, 30], dollars=10.0, resets=T0 + 4 * HOUR)
        self.series(T0 + 7 * DAY, [10, 30], dollars=6.0, resets=T0 + 7 * DAY + 4 * HOUR)
        self.series(T0 + 7 * DAY + 20 * MINUTE, [40, 45], kind="seven_day", resets=T0 + 9 * DAY)
        c = self.capacity(billing)
        self.assertTrue(c.known)
        # Over the range: 40 points for $16 in two chains, each 20 points; the weekly window rose 5, too little.
        self.assertEqual([(p.plan, p.five_hour, p.weekly, p.held_by) for p in c.plans],
                         [("Pro", "—", "—", "none here"), ("Max 5x", "—", "—", "none here"),
                          ("Ultra", "$40", "—", "alpha")])
        self.assertEqual([(w.monday.isoformat(), w.plan, w.five_hour, w.weekly) for w in c.weeks],
                         [("2026-10-12", "Ultra", "$50", "—"), ("2026-10-19", "Ultra", "$30 (lower)", "—")])

    def test_an_account_holds_its_plan_from_the_day_its_period_began(self):
        # The plan began on the range's last day, which no step counts, but it holds the plan all the same.
        billing = self.billing([bill(EMAIL_A, "2026-10-23", 100.0, plan="max5x", period="2026-10-23..2026-11-23")])
        self.assertEqual([(p.plan, p.held_by) for p in self.capacity(billing).plans],
                         [("Pro", "none here"), ("Max 5x", "alpha"), ("Ultra", "none here")])

    def test_how_many_5_hour_windows_a_week_held_is_the_weekly_figure_over_the_5_hour_one(self):
        # A full 5-hour window held 100 × 10 ÷ 20 = $50, give or take 50 × 1 ÷ 20 = $2.50, a twentieth of it; a full
        # weekly window 100 × 20 ÷ 10 = $200, give or take 200 × 1 ÷ 10 = $20, a tenth. So 4.0 full 5-hour windows,
        # give or take 4.0 × (1/10 + 1/20) = 0.6.
        five_hour, weekly = Held(20.0, 10.0, 1), Held(10.0, 20.0, 1)
        self.assertEqual(history._windows_text(five_hour, weekly), "4.0 (3.4–4.6)")
        self.assertEqual(history._windows_text(Held(5.0, 10.0, 1), weekly), "—")
        self.assertEqual(history._windows_text(five_hour, Held(5.0, 20.0, 1)), "—")
        # A rise with no dollars recorded between its readings — all the use elsewhere — has no quotient.
        self.assertEqual(history._windows_text(Held(20.0, 0.0, 1), weekly), "—")

    def test_without_bills_no_plan_is_known(self):
        billing = self.billing(None)
        self.series(T0, [10, 30], dollars=10.0, resets=T0 + 4 * HOUR)
        self.assertEqual(self.capacity(billing), history.Capacity(False))
        self.assertEqual(self.capacity(None), history.Capacity(False))
        blocks = history_model._capacity_blocks(history.Capacity(False))
        self.assertEqual(blocks, [Heading(history.CAPACITY_HEADING), Note(history.CAPACITY_NO_BILLS)])


class LivePathTest(unittest.TestCase):
    """Transcripts, plugin readings and the account sync's records on a synthetic machine, through a pass, to the history
    page the pass writes and the window's History view."""

    NOW = epoch("2026-10-21T18:00:00Z")
    # alpha's full week held $100 over a full 5-hour window's 100 × 10 ÷ 15 = $66.67 (shown $67): 1.5 windows, give or
    # take 1.5 × (1/10 + 1/15) = 0.25, a tenth and a fifteenth being the two figures' shares of themselves. Both ends,
    # 1.25 and 1.75, lie exactly halfway between two tenths, so which tenth each shows is the floating-point
    # arithmetic's last bit, not the rule's.
    WINDOWS_ULTRA = r"1\.5 \(1\.[23]–1\.[78]\)"

    @classmethod
    def setUpClass(cls):
        cls.machine = m = Machine()
        m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        m.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        m.bills_file([bill(EMAIL_A, "2026-10-07", 200.0, plan="ultra", period="2026-10-07..2026-11-07"),
                      bill(EMAIL_B, "2026-10-07", 100.0, plan="max5x", period="2026-10-07..2026-11-07")])
        # Each account answers six sessions ten minutes apart while the desktop app is on it, each response costing
        # $2.00 at list price (100,000 output tokens of claude-opus-5-5), each session's reading a minute after it.
        # alpha's 5-hour figure rises 3 points a step and its week 2; beta's 5 and 1.
        weekly_resets = {ACCOUNT_A: epoch("2026-10-24T22:00:00Z"), ACCOUNT_B: epoch("2026-10-26T06:00:00Z")}
        events = []
        for account, start, five_hour, weekly in ((ACCOUNT_A, epoch("2026-10-21T10:00:00Z"), (10, 3), (40, 2)),
                                                  (ACCOUNT_B, epoch("2026-10-21T14:00:00Z"), (20, 5), (10, 1))):
            events.append((start - HOUR, "desktop_account", account))
            for k in range(6):
                session, t = f"{account[0]}{k}", start + k * 10 * MINUTE
                m.transcript(session, assistant_lines(f"m{account[0]}{k}", t - MINUTE, session, outputs=(8, 100000),
                                                      input_tokens=0, cache_read=0, cache_write_1h=0))
                m.reading(session, t, (five_hour[0] + k * five_hour[1], start + 4 * HOUR),
                          (weekly[0] + k * weekly[1], weekly_resets[account]))
        m.sync_events(events)
        run_pass(m.paths, now=cls.NOW, dashboard=True)
        cls.page = m.paths.dashboard_file.read_text(encoding="utf-8")
        cls.blocks = history_model.blocks(history_model.compute(m.paths, "30d", now=cls.NOW))

    @classmethod
    def tearDownClass(cls):
        cls.machine.close()

    def capacity(self) -> tuple[int, Switch]:
        """Where the window's full-window switch stands among its blocks, and the switch."""
        found = [(i, b) for i, b in enumerate(self.blocks)
                 if isinstance(b, Switch) and b.key == history.CAPACITY_SWITCH]
        self.assertEqual(len(found), 1, "the bills name a plan, so the full window stands as a switch")
        return found[0]

    def tables(self) -> tuple[Table, Table]:
        """The full window by plan and by week: each view's table, after its caveat."""
        by_plan, by_week = self.capacity()[1].views
        for view in (by_plan, by_week):
            self.assertIsInstance(view.blocks[1], Table, view.choice)
        return by_plan.blocks[1], by_week.blocks[1]

    def section(self) -> str:
        """The page's full-window switch, every view's pane, up to the next section."""
        head = self.page.index(f'<input type="radio" name="switch-{history.CAPACITY_SWITCH}"')
        return self.page[head:self.page.index("<h2>All accounts exhausted", head)]

    def test_the_window_shows_the_caveat_before_the_figures_after_the_subscriptions(self):
        at, switch = self.capacity()
        before = [b.text for b in self.blocks[:at] if isinstance(b, Heading)]
        after = [b.text for b in self.blocks[at + 1:] if isinstance(b, Heading)]
        self.assertEqual(before[-1], "Gaps between periods")
        self.assertEqual(after[0], "All accounts exhausted")
        self.assertEqual([v.choice for v in switch.views], list(history.SWITCH_VIEWS[history.CAPACITY_SWITCH]))
        for view in switch.views:
            self.assertEqual(view.heading, Heading(history.CAPACITY_BY, history.CAPACITY_NOTE))
            self.assertEqual(view.blocks[0], Note(history.CAPACITY_CAVEAT), view.choice)
        plans, weeks = self.tables()
        # alpha: 15 points of its 5-hour window and 10 of its week for $10; beta: 25 and 5 points for $10, beta's week
        # too small a rise for a figure, so its plan has no windows in a week.
        windows = plans.rows[2][3]
        self.assertRegex(windows, f"^{self.WINDOWS_ULTRA}$")
        self.assertEqual(plans.rows, (("Pro", "—", "—", "—", "none here"), ("Max 5x", "$40", "—", "—", "beta"),
                                      ("Ultra", "$67", "$100", windows, "alpha")))
        self.assertEqual(weeks.rows, (("week of 2026-10-19", "Max 5x", "$40", "—", "—"),
                                      ("week of 2026-10-19", "Ultra", "$67", "$100", windows)))
        self.assertNotIn(Note(history.CAPACITY_NOTE), laid_out(self.blocks),
                         "how it is counted is the heading's hint alone")

    def test_the_page_says_the_same_with_the_caveat_first(self):
        section = self.section()
        hint = escape(history.CAPACITY_NOTE)
        self.assertLess(self.page.index("<h2>Gaps between periods</h2>"), self.page.index(section))
        panes = section.split('<div class="view v')[1:]
        self.assertEqual(len(panes), len(history.SWITCH_VIEWS[history.CAPACITY_SWITCH]))
        for pane in panes:
            heading = pane[pane.index("<h2>"):pane.index("</h2>")]
            self.assertTrue(heading.startswith(f'<h2>{escape(history.CAPACITY_BY)} <span class="seg">'), heading)
            self.assertIn("</span>, last six weeks ", heading)
            self.assertIn(f'title="{hint}" aria-label="{hint}">?</span>', heading)
            self.assertLess(pane.index(escape(history.CAPACITY_CAVEAT)), pane.index("<table>"))
            self.assertEqual(pane.count(hint), 2, "the hint's title and aria-label, and no note on the page")
        by_plan = panes[0]
        none = re.escape("—")                   # the windows cell is a pattern, the other cells literals
        for plan, five_hour, weekly, windows, held_by in (("Max 5x", "$40", "—", none, "beta"),
                                                          ("Ultra", "$67", "$100", self.WINDOWS_ULTRA, "alpha"),
                                                          ("Pro", "—", "—", none, "none here")):
            self.assertRegex(by_plan, re.escape(f'<td class="l">{plan}</td><td>{five_hour}</td><td>{weekly}</td><td>')
                             + windows + re.escape(f'</td><td class="l">{held_by}</td>'))

    def test_the_window_and_the_page_say_how_many_5_hour_windows_a_week_held(self):
        # alpha's Ultra: a full week $100 over a full 5-hour window $67, 1.5; beta's Max 5x has no weekly figure.
        plans, weeks = self.tables()
        for table in (plans, weeks):
            self.assertIn(history.CAPACITY_WINDOWS, [title for title, _ in table.columns])
        self.assertEqual([row[3] for row in plans.rows[:2]], ["—", "—"])
        self.assertTrue(plans.rows[2][3].startswith("1.5 ("), plans.rows[2])
        self.assertTrue(weeks.rows[1][4].startswith("1.5 ("), weeks.rows[1])
        section = self.section()
        self.assertEqual(section.count(f"<th>{escape(history.CAPACITY_WINDOWS)}</th>"), 2, "a column in each view")
        self.assertIn('<td>$67</td><td>$100</td><td>1.5 (', section)


if __name__ == "__main__":
    unittest.main()
