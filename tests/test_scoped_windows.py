"""Per-model weekly windows (Fable's): read from claude.ai through the browser extension, carried forward by the
service, written to status.json and shown by the window; and the responses of a model new to the price table, priced
where they stand.

Expected values are derived from the rules — a model's allowance is a share of the weekly window, its use raises both,
a reset of the allowance gives its share of the week back, past the allowance the model's use stops raising the week —
never read back from the code.
"""

import io
import json
import unittest

from fixtures import ACCOUNT_A, EMAIL_A, ORG_A, Machine, epoch, iso
from test_browser import frame, message, page_time
from windowtally.accounts import Account, by_org, load_registry
from windowtally.browser_host import ReadingError, checked_reading, reading_from, serve
from windowtally.ingest_browser import ingest_browser
from windowtally.ingest_transcripts import Repricing, reprice
from windowtally.ledger import Ledger, Observation
from windowtally.limits import (PROJECTION_LOOKBACK, WEEK, AccountStanding, Plateau, ScopedStanding,
                                WindowStanding, exhausts_at, family_rates, projection_plateaus, recommend,
                                scoped_standings)
from windowtally.service import run_pass, unpriced_problems
from windowtally.status_file import status_document
from windowtally_gui.live_model import scoped_row
from windowtally_gui.status_model import parse_status

T0 = epoch("2026-11-10T12:00:00Z")
HOUR = 3600.0
RESET = T0 + 3 * 86400


def scoped_message(**changes):
    """A reading carrying Fable's window, as the extension sends it."""
    row = {"name": "Fable", "percentUsed": 21, "resetsAt": page_time(RESET), "allowanceOfWeekly": 50}
    row.update(changes)
    return message(org=ORG_A, t=T0, weeklyScoped=[row])


def weekly(t, percent, source="plugin"):
    return Observation(source, "ref", t, "seven_day", float(percent), RESET, ACCOUNT_A)


class HostTest(unittest.TestCase):
    def test_a_per_model_window_is_kept_from_its_checked_fields_alone(self):
        sent = scoped_message(extra="dropped")
        self.assertEqual(reading_from(sent)["weeklyScoped"], [
            {"name": "Fable", "percentUsed": 21, "resetsAt": page_time(RESET), "allowanceOfWeekly": 50}])

    def test_an_allowance_claude_ai_did_not_give_is_kept_as_none(self):
        self.assertIsNone(reading_from(scoped_message(allowanceOfWeekly=None))["weeklyScoped"][0]["allowanceOfWeekly"])

    def test_one_not_in_its_shape_is_dropped_and_the_windows_kept(self):
        refused = {
            "no name": scoped_message(name=""),
            "a figure that is not a percentage": scoped_message(percentUsed=-1),
            "a reset that is not a time": scoped_message(resetsAt="soon"),
            "an allowance above the whole week": scoped_message(allowanceOfWeekly=150),
            "an allowance of nothing": scoped_message(allowanceOfWeekly=0),
            "not a list": dict(message(org=ORG_A, t=T0), weeklyScoped={"name": "Fable"}),
        }
        for case, sent in refused.items():
            with self.subTest(case):
                reading, dropped = checked_reading(sent)
                self.assertNotIn("weeklyScoped", reading)
                self.assertEqual(len(reading["windows"]), 2)
                self.assertIsNotNone(dropped)

    def test_a_reading_with_neither_addition_drops_nothing(self):
        self.assertEqual(checked_reading(message(org=ORG_A, t=T0))[1], None)

    def test_the_window_itself_still_refuses_what_is_not_a_reading(self):
        with self.assertRaises(ReadingError):
            reading_from(dict(scoped_message(), windows=[]))


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        self.orgs = by_org(registry)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def test_a_per_model_window_becomes_its_accounts_row(self):
        serve(io.BytesIO(frame(scoped_message())), io.BytesIO(), self.machine.paths.browser_dir)
        ingest_browser(self.ledger, self.machine.paths.browser_dir, self.orgs, T0)
        rows = self.ledger.scoped_observations(ACCOUNT_A)
        self.assertEqual([(r.t, r.name, r.percent, r.resets_at, r.allowance) for r in rows],
                         [(T0, "Fable", 21.0, RESET, 50.0)])


class StandingTest(unittest.TestCase):
    """One account's Fable window over readings, weekly observations and responses written row by row."""

    def setUp(self):
        self.machine = Machine()
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        self.responses = 0

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def reading(self, t, percent, resets_at=RESET, allowance=50.0, name="Fable"):
        self.ledger.db.execute(
            "INSERT INTO scoped_windows(source, ref, t, name, percent, resets_at, allowance, account_uuid, "
            "account_source) VALUES ('browser', ?, ?, ?, ?, ?, ?, ?, 'org')",
            (ORG_A, t, name, float(percent), resets_at, allowance, ACCOUNT_A))

    def response(self, t, dollars, model="claude-fable-5-2"):
        self.responses += 1
        self.ledger.db.execute(
            "INSERT INTO responses(message_id, t, session_id, model, input_tokens, output_tokens, thinking_tokens, "
            "cache_read_tokens, cache_write_5m_tokens, cache_write_1h_tokens, web_search_requests, web_fetch_requests, "
            "cost_usd, account_uuid) VALUES (?, ?, 's', ?, 0, 0, 0, 0, 0, 0, 0, 0, ?, ?)",
            (f"m{self.responses}", t, model, dollars, ACCOUNT_A))

    def fable(self, now, observations=(), rate=None) -> ScopedStanding:
        found = scoped_standings(self.ledger, ACCOUNT_A, list(observations), rate, now)
        self.assertEqual([s.name for s in found], ["Fable"])
        return found[0]

    def test_the_reading_stands_where_nothing_was_spent_since(self):
        self.reading(T0, 21)
        s = self.fable(T0 + 600, rate=0.5)
        self.assertEqual((s.state, s.percent, s.resets_at, s.as_of, s.estimated, s.allowance),
                         ("current", 21.0, RESET, T0, False, 50.0))

    def test_the_models_spend_since_the_reading_is_added_over_its_allowance(self):
        # $10 of Fable at half a weekly point a dollar is 5 weekly points, 10 points of an allowance half the week.
        self.reading(T0, 20)
        self.response(T0 + 600, 10.0)
        self.response(T0 + 900, 30.0, model="claude-opus-5-5")   # another model's use is not the allowance's
        s = self.fable(T0 + 1800, rate=0.5)
        self.assertAlmostEqual(s.percent, 30.0)
        self.assertTrue(s.estimated)

    def test_without_the_rate_or_the_allowance_nothing_is_added(self):
        self.reading(T0, 20, allowance=None)
        self.response(T0 + 600, 10.0)
        self.assertEqual((self.fable(T0 + 1800, rate=0.5).percent, self.fable(T0 + 1800, rate=0.5).estimated),
                         (20.0, False))

    def test_a_scheduled_reset_since_the_reading_empties_it(self):
        self.reading(T0, 80, resets_at=T0 + HOUR)
        self.response(T0 + 2 * HOUR, 4.0)
        s = self.fable(T0 + 3 * HOUR, rate=0.5)
        # $4 at 0.5 is 2 weekly points, 4 points of the allowance, all since the reset.
        self.assertEqual(s.resets_at, T0 + HOUR + WEEK)
        self.assertAlmostEqual(s.percent, 4.0)

    def test_a_fall_of_the_week_by_the_models_share_is_a_reset_of_its_allowance(self):
        # 80 % of a half-week allowance is 40 weekly points: the week falling 62 -> 21 gave them back.
        self.reading(T0, 80)
        week = [weekly(T0, 60), weekly(T0 + 600, 62), weekly(T0 + 1200, 21), weekly(T0 + 1800, 22)]
        s = self.fable(T0 + 1800, week)
        self.assertEqual((s.state, s.percent, s.estimated), ("current", 0.0, True))

    def test_the_rise_after_a_reset_of_the_allowance_counts_from_the_reset(self):
        self.reading(T0, 80)
        self.response(T0 + 300, 20.0)                        # before the reset: given back with the rest
        week = [weekly(T0, 60), weekly(T0 + 600, 67), weekly(T0 + 1200, 21)]
        self.response(T0 + 1500, 6.0)                        # after it: 3 weekly points, 6 of the allowance
        s = self.fable(T0 + 1800, week, rate=0.5)
        self.assertAlmostEqual(s.percent, 6.0)

    def test_a_fall_that_is_not_the_models_share_leaves_it_unknown(self):
        self.reading(T0, 80)
        week = [weekly(T0, 60), weekly(T0 + 600, 62), weekly(T0 + 1200, 47)]   # 15 points, not 40
        s = self.fable(T0 + 1800, week)
        self.assertEqual((s.state, s.percent), ("unknown", None))

    def test_a_fall_the_model_held_too_little_of_the_week_for_leaves_it_as_it_was(self):
        # 4 % of a half-week allowance is 2 weekly points: a fall of 30 is not its reset, nor touched it.
        self.reading(T0, 4)
        week = [weekly(T0, 60), weekly(T0 + 600, 62), weekly(T0 + 1200, 32)]
        self.assertEqual(self.fable(T0 + 1800, week).percent, 4.0)

    def test_a_fall_before_the_reading_is_the_readings_own_past(self):
        self.reading(T0 + 1800, 21)
        week = [weekly(T0, 60), weekly(T0 + 600, 21), weekly(T0 + 2400, 22)]
        self.assertEqual(self.fable(T0 + 3000, week).state, "current")

    def test_an_account_that_never_used_the_model_has_no_window(self):
        self.reading(T0, 0)
        self.reading(T0 + HOUR, 0)
        self.assertEqual(scoped_standings(self.ledger, ACCOUNT_A, [], None, T0 + 2 * HOUR), ())

    def test_one_that_used_it_keeps_the_window_at_nothing_after_a_reset(self):
        self.reading(T0, 30, resets_at=T0 + HOUR)
        self.reading(T0 + 2 * HOUR, 0, resets_at=T0 + HOUR + WEEK)
        self.assertEqual(self.fable(T0 + 3 * HOUR).percent, 0.0)

    def test_the_projection_stops_the_models_share_of_the_pace_at_its_allowance(self):
        # Fable at 60 % of a half-week allowance has 20 weekly points left; all the cost of the last hours was Fable's.
        self.reading(T0, 60)
        self.response(T0 + HOUR - 60, 5.0)
        scoped = self.fable(T0 + HOUR)
        week = [weekly(T0, 30), weekly(T0 + HOUR, 40)]
        plateaus = projection_plateaus(self.ledger, ACCOUNT_A, week, [scoped], None, T0 + HOUR)
        self.assertEqual(plateaus, [Plateau(1.0, 20.0)])
        self.assertIsNone(exhausts_at(week, T0 + HOUR, plateaus), "the week stops at 60 % as Fable's allowance fills")

    def test_a_reading_older_than_the_projections_span_counts_its_cost_over_that_span_alone(self):
        self.reading(T0, 60)
        self.response(T0 + HOUR - 60, 5.0)
        self.response(T0 + HOUR - PROJECTION_LOOKBACK - 60, 50.0, model="claude-opus-5-5")
        week = [weekly(T0, 30), weekly(T0 + HOUR, 40)]
        self.assertEqual(projection_plateaus(self.ledger, ACCOUNT_A, week, [self.fable(T0 + HOUR)], None, T0 + HOUR),
                         [Plateau(1.0, 20.0)])

    def test_the_headroom_is_the_allowances_room_at_the_latest_weekly_observation(self):
        # At half a weekly point a dollar: $5 of Fable before the last weekly observation put it at 65 % (17.5 weekly
        # points left), $8 after it at 73 % by now; the projection starts at the observation, so its room is 17.5.
        self.reading(T0, 60)
        self.response(T0 + HOUR - 60, 5.0)
        self.response(T0 + HOUR + 600, 8.0)
        now = T0 + HOUR + 900
        scoped = self.fable(now, rate=0.5)
        self.assertAlmostEqual(scoped.percent, 60 + 0.5 * 13 * 2)
        week = [weekly(T0, 30), weekly(T0 + HOUR, 40)]
        (plateau,) = projection_plateaus(self.ledger, ACCOUNT_A, week, [scoped], 0.5, now)
        self.assertAlmostEqual(plateau.headroom, (100 - (60 + 0.5 * 5 * 2)) * 0.5)

    def test_a_name_with_more_than_the_familys_word_still_counts_the_familys_use(self):
        self.reading(T0, 20, name="Fable 5.2")
        self.response(T0 + 600, 10.0)
        found = scoped_standings(self.ledger, ACCOUNT_A, [], 0.5, T0 + 1800)
        self.assertEqual([(s.name, s.percent) for s in found], [("Fable 5.2", 30.0)])

    def test_a_name_that_names_no_family_adds_nothing(self):
        self.reading(T0, 20, name="Cowork")
        self.response(T0 + 600, 10.0)
        found = scoped_standings(self.ledger, ACCOUNT_A, [], 0.5, T0 + 1800)
        self.assertEqual([(s.name, s.percent, s.estimated) for s in found], [("Cowork", 20.0, False)])

    def test_a_reading_without_a_reset_time_resets_with_the_week(self):
        # The weekly observations name the week's reset; once it passed, the window starts again from nothing.
        self.reading(T0, 80, resets_at=None)
        week = [weekly(T0, 60), weekly(T0 + 600, 62)]
        s = self.fable(RESET + HOUR, week)
        self.assertEqual((s.state, s.percent, s.resets_at), ("current", 0.0, RESET + WEEK))


class MeasuredRiseTest(unittest.TestCase):
    """The weekly window's rise since the model's reading, read from the weekly readings and shared between the model
    and every other model by what each spent at its own points per dollar."""

    # StandingTest's ledger and rows, without running its tests a second time.
    setUp, tearDown = StandingTest.setUp, StandingTest.tearDown
    reading, response, fable = StandingTest.reading, StandingTest.response, StandingTest.fable

    def observed(self, t, percent):
        """A weekly reading of the plugin's, stored in the ledger, where the points per dollar are measured from."""
        self.ledger.db.execute(
            "INSERT INTO observations(source, ref, t, kind, percent, resets_at, account_uuid, account_source) "
            "VALUES ('plugin', 'ref', ?, 'seven_day', ?, ?, ?, 'test')", (t, float(percent), RESET, ACCOUNT_A))

    def other_models_run(self):
        """Hours before the reading: $50 of Opus raised the week 2 points, 0.04 a dollar."""
        self.observed(T0 - 8 * HOUR, 10)
        self.response(T0 - 8 * HOUR + 300, 50.0, model="claude-opus-5-5")
        self.observed(T0 - 8 * HOUR + 600, 12)

    def mixed_run(self):
        """Later, more than three hours on: $40 of Fable and $50 of Opus raised the week 10 points, 2 of them Opus's at
        0.04 a dollar, so 8 for Fable's $40, 0.2 a dollar."""
        self.observed(T0 - 4 * HOUR, 20)
        self.response(T0 - 4 * HOUR + 200, 40.0)
        self.response(T0 - 4 * HOUR + 400, 50.0, model="claude-opus-5-5")
        self.observed(T0 - 4 * HOUR + 600, 30)

    def test_the_familys_rate_is_what_its_runs_rose_beyond_the_other_models_rate(self):
        self.other_models_run()
        self.mixed_run()
        model, rest = family_rates(self.ledger, ACCOUNT_A, "Fable", T0)
        self.assertAlmostEqual(rest, 0.04)
        self.assertAlmostEqual(model, 0.2)

    def test_without_a_run_free_of_the_family_neither_rate_is_known(self):
        self.mixed_run()
        self.assertEqual(family_rates(self.ledger, ACCOUNT_A, "Fable", T0), (None, None))

    def test_without_a_run_of_the_family_its_rate_alone_is_unknown(self):
        self.other_models_run()
        model, rest = family_rates(self.ledger, ACCOUNT_A, "Fable", T0)
        self.assertIsNone(model)
        self.assertAlmostEqual(rest, 0.04)

    def test_the_rise_since_the_reading_is_the_models_where_only_its_use_came(self):
        # The week rose 10 points on $5 of Fable alone: all 10 are Fable's, 20 points of its half-week allowance. The
        # account's single rate would have said 0.5 * 5 = 2.5 weekly points.
        self.reading(T0, 20)
        self.response(T0 + 600, 5.0)
        s = self.fable(T0 + HOUR, [weekly(T0, 40), weekly(T0 + HOUR, 50)], rate=0.5)
        self.assertAlmostEqual(s.percent, 40.0)
        self.assertTrue(s.estimated)

    def test_a_rise_that_none_of_the_models_use_came_in_is_not_its(self):
        self.reading(T0, 20)
        self.response(T0 + 600, 20.0, model="claude-opus-5-5")
        s = self.fable(T0 + HOUR, [weekly(T0, 40), weekly(T0 + HOUR, 60)], rate=0.5)
        self.assertEqual((s.percent, s.estimated), (20.0, False))

    def test_without_rates_the_rise_is_shared_by_dollars(self):
        # $30 of Fable and $10 of Opus: Fable's part of the 20 points is 15, 30 of its allowance.
        self.reading(T0, 40)
        self.response(T0 + 600, 30.0)
        self.response(T0 + 1200, 10.0, model="claude-opus-5-5")
        s = self.fable(T0 + HOUR, [weekly(T0, 50), weekly(T0 + HOUR, 70)])
        self.assertAlmostEqual(s.percent, 70.0)

    def test_with_the_families_rates_the_rise_is_shared_by_what_each_dollar_costs(self):
        # $50 of Fable at 0.2 a dollar against $50 of Opus at 0.04: Fable's part of the 20 points is 10/12 of them.
        self.other_models_run()
        self.mixed_run()
        self.reading(T0, 40)
        self.response(T0 + 600, 50.0)
        self.response(T0 + 1200, 50.0, model="claude-opus-5-5")
        s = self.fable(T0 + HOUR, [weekly(T0, 50), weekly(T0 + HOUR, 70)])
        self.assertAlmostEqual(s.percent, 40 + 20 * 10 / 12 * 2)
        self.assertAlmostEqual(s.rate, 0.2)
        self.assertAlmostEqual(s.rest_rate, 0.04)

    def test_the_models_part_stops_at_its_allowance(self):
        # 30 points of Fable's use against the 5 its allowance had left: the window is full, the rest is not its.
        self.reading(T0, 90)
        self.response(T0 + 600, 100.0)
        self.assertEqual(self.fable(T0 + HOUR, [weekly(T0, 50), weekly(T0 + HOUR, 80)]).percent, 100.0)

    def test_the_spend_after_the_latest_weekly_reading_is_added_at_the_models_rate(self):
        # The measured 10 points take it to 40; $4 since, at half a weekly point a dollar, 2 points more: 44.
        self.reading(T0, 20)
        self.response(T0 + 600, 5.0)
        self.response(T0 + HOUR + 600, 4.0)
        s = self.fable(T0 + HOUR + 900, [weekly(T0, 40), weekly(T0 + HOUR, 50)], rate=0.5)
        self.assertAlmostEqual(s.percent, 44.0)

    def test_a_reset_is_read_from_the_measured_part_where_the_single_rate_fell_short(self):
        # Fable alone took the week 50 -> 75: its 25 points fill its allowance, and the fall 75 -> 27 gave back those
        # 25 and the 25 it held at the reading. At the single rate it would have held 50 + 0.5 * 10 * 2 = 60 %, 30
        # points, too few for a fall of 48 to be its reset.
        self.reading(T0, 50)
        self.response(T0 + 600, 10.0)
        s = self.fable(T0 + 2 * HOUR, [weekly(T0, 50), weekly(T0 + HOUR, 75), weekly(T0 + 2 * HOUR, 27)], rate=0.5)
        self.assertEqual((s.state, s.percent, s.estimated), ("current", 0.0, True))

    def test_a_weekly_reading_before_the_models_reading_lends_it_none_of_its_rise(self):
        # The week rose 40 -> 50 across the reading, $40 of Fable before it, which the reading already counts, and 10
        # cents after it. No weekly reading after the model's brackets a rise, so with no rate nothing is added.
        self.response(T0 - HOUR, 40.0)
        self.reading(T0, 20)
        self.response(T0 + 600, 0.10)
        s = self.fable(T0 + HOUR, [weekly(T0 - 2 * HOUR, 40), weekly(T0 + HOUR, 50)])
        self.assertEqual(s.percent, 20.0)

    def test_spend_after_the_last_reading_before_a_fall_is_not_weighed_against_the_rise_before_it(self):
        # The week's 20-point rise between the two readings came with $50 of Opus and none of Fable; Fable's $50 came
        # after the last of them, and with no rate it adds nothing. Fable held its 25 points, which the fall of 25
        # gave back: a reset of its allowance.
        self.reading(T0, 50)
        self.response(T0 + 600, 50.0, model="claude-opus-5-5")
        self.response(T0 + HOUR + 600, 50.0)
        s = self.fable(T0 + 2 * HOUR, [weekly(T0, 50), weekly(T0 + HOUR, 70), weekly(T0 + 2 * HOUR, 45)])
        self.assertEqual((s.state, s.percent, s.estimated), ("current", 0.0, True))

    def test_the_projection_shares_the_pace_by_what_each_dollar_costs(self):
        # $10 of Fable at 0.2 and $10 of Opus at 0.04 over the span: Fable's part of the pace is 2 / 2.4.
        fable = ScopedStanding("Fable", "current", 60.0, RESET, T0, True, 50.0, 0.2, 0.04)
        self.response(T0 + HOUR - 120, 10.0)
        self.response(T0 + HOUR - 60, 10.0, model="claude-opus-5-5")
        (plateau,) = projection_plateaus(self.ledger, ACCOUNT_A, [weekly(T0, 30), weekly(T0 + HOUR, 40)], [fable],
                                         None, T0 + HOUR)
        self.assertAlmostEqual(plateau.share, 2 / 2.4)
        self.assertAlmostEqual(plateau.headroom, 20.0)


class ReadRateTest(unittest.TestCase):
    """The model's points per dollar read off claude.ai's readings of its own window: what the window rose between two
    readings, over its allowance, is the model's part of the week, and what the model spent between them its dollars.
    Fable's allowance is half the week, so a point of its window is half a weekly point."""

    setUp, tearDown = StandingTest.setUp, StandingTest.tearDown
    reading, response, fable = StandingTest.reading, StandingTest.response, StandingTest.fable
    observed, other_models_run, mixed_run = (MeasuredRiseTest.observed, MeasuredRiseTest.other_models_run,
                                             MeasuredRiseTest.mixed_run)

    def rates(self, week=()):
        return family_rates(self.ledger, ACCOUNT_A, "Fable", T0, self.ledger.scoped_observations(ACCOUNT_A), list(week))

    def two_readings(self, first=20, second=40, dollars=50.0, **reading):
        """Two readings two hours apart inside the week, the model's ``dollars`` between them."""
        self.reading(T0 - 3 * HOUR, first, **reading)
        self.response(T0 - 2 * HOUR, dollars)
        self.reading(T0 - HOUR, second, **reading)

    def test_the_rise_between_two_readings_over_the_models_spend_is_its_rate(self):
        # 20 -> 40 is 20 points of the allowance, 10 of the week, on $50 of Fable: 0.2 a dollar. Another model's use
        # between them is none of the window's.
        self.two_readings()
        self.response(T0 - 2 * HOUR + 60, 500.0, model="claude-opus-5-5")
        self.assertEqual(self.rates()[1], None)
        self.assertAlmostEqual(self.rates()[0], 0.2)

    def week_before(self, read=True):
        """The window read in the week before, at 90 %, and the weekly window observed then, which is returned: the
        account was watched from this week's start on."""
        if read:
            self.reading(RESET - WEEK - 86400, 90, resets_at=RESET - WEEK)
        return [Observation("plugin", "ref", RESET - WEEK - 86400, "seven_day", 50.0, RESET - WEEK, ACCOUNT_A)]

    def test_a_weeks_first_reading_is_measured_from_the_weeks_start_where_the_window_stood_empty(self):
        # The reading before it belongs to the week before, at 90 %: no fall of 60, but a week begun at nothing. 30 %
        # is 15 weekly points on the $60 spent since the week began: 0.25 a dollar.
        watched = self.week_before()
        self.response(RESET - WEEK - 3600, 1000.0)           # the week before's use is not this week's
        self.response(T0 - 2 * 86400, 60.0)
        self.reading(T0 - HOUR, 30)
        self.assertAlmostEqual(self.rates(watched)[0], 0.25)

    def test_a_weeks_first_reading_of_a_week_not_watched_from_its_start_only_sets_the_level(self):
        # Without a reading of the window in a week before, or without a weekly observation by the week's start, the
        # spend recorded since the start may not be the whole of it: the first reading measures nothing. The next is
        # measured from it: 30 -> 40 is 5 weekly points on $10.
        for case, read in {"the window never read before": False, "the week not observed by its start": True}.items():
            with self.subTest(case):
                self.ledger.db.execute("DELETE FROM scoped_windows")
                self.ledger.db.execute("DELETE FROM responses")
                observed = self.week_before(read)
                week = [] if read else observed
                self.response(T0 - 2 * 86400, 60.0)
                self.reading(T0 - 3 * HOUR, 30)
                self.assertEqual(self.rates(week), (None, None))
                self.response(T0 - 2 * HOUR, 10.0)
                self.reading(T0 - HOUR, 40)
                self.assertAlmostEqual(self.rates(week)[0], 0.5)

    def test_a_reading_in_the_first_minute_of_its_week_is_passed_over(self):
        # Half a minute into the week it still shows the week before's 90 %: neither a week begun at 90 % on the $6
        # spent in that half minute, nor a fall when the next reads 30 %, 15 weekly points on $60.
        watched = self.week_before()
        self.response(RESET - WEEK + 10, 6.0)
        self.reading(RESET - WEEK + 30, 90)
        self.response(T0 - 2 * 86400, 54.0)
        self.reading(T0 - HOUR, 30)
        self.assertAlmostEqual(self.rates(watched)[0], 0.25)

    def test_the_read_rate_stands_before_what_the_weekly_rises_leave(self):
        # The weekly rises leave Fable 0.2 a dollar (MeasuredRiseTest); claude.ai read its window at 8 %, 4 weekly
        # points, on the same $40: 0.1 a dollar. The other models' rate is the rises' either way.
        watched = self.week_before()
        self.other_models_run()
        self.mixed_run()
        self.reading(T0 - HOUR, 8)
        model, rest = self.rates(watched)
        self.assertAlmostEqual(model, 0.1)
        self.assertAlmostEqual(rest, 0.04)

    def test_the_standing_carries_the_read_rate(self):
        self.two_readings()
        s = self.fable(T0)
        self.assertAlmostEqual(s.rate, 0.2)
        self.assertEqual(s.percent, 40.0)

    def test_the_spend_since_the_reading_is_added_at_the_read_rate(self):
        # $5 more at the read 0.2 a dollar is 1 weekly point, 2 of the allowance; the single rate given would add 5.
        self.two_readings()
        self.response(T0 + 600, 5.0)
        self.assertAlmostEqual(self.fable(T0 + 1800, rate=0.5).percent, 42.0)

    def test_a_fall_of_the_window_measures_nothing_and_the_next_reading_counts_from_it(self):
        # 80 -> 10 is a reset of the allowance, whatever was spent across it; 10 -> 20 is 5 weekly points on $10.
        self.reading(T0 - 5 * HOUR, 80)
        self.response(T0 - 4 * HOUR, 100.0)
        self.reading(T0 - 3 * HOUR, 10)
        self.response(T0 - 2 * HOUR, 10.0)
        self.reading(T0 - HOUR, 20)
        self.assertAlmostEqual(self.rates()[0], 0.5)

    def test_a_lower_reading_short_of_a_fall_adds_nothing_and_the_next_counts_from_the_higher(self):
        # 30, then 29 on $10, then 34 on $10 more: 4 points of the allowance above the highest read, 2 weekly points,
        # on the $20 spent across both.
        self.reading(T0 - 5 * HOUR, 30)
        self.response(T0 - 4 * HOUR, 10.0)
        self.reading(T0 - 3 * HOUR, 29)
        self.response(T0 - 2 * HOUR, 10.0)
        self.reading(T0 - HOUR, 34)
        self.assertAlmostEqual(self.rates()[0], 0.1)

    def test_a_lower_reading_with_nothing_spent_does_not_lower_what_the_next_counts_from(self):
        # 30, then 29 read again while idle, then 34 on $10: 4 points of the allowance above the highest read, 2 weekly
        # points, 0.2 a dollar, not the 5 from 29.
        self.reading(T0 - 5 * HOUR, 30)
        self.reading(T0 - 3 * HOUR, 29)
        self.response(T0 - 2 * HOUR, 10.0)
        self.reading(T0 - HOUR, 34)
        self.assertAlmostEqual(self.rates()[0], 0.2)

    def test_a_fall_of_the_weekly_window_while_two_readings_ran_measures_nothing(self):
        # The week fell 62 -> 21: a reset that may have emptied the window, which then rose again. It counts whether
        # the weekly observation showing it came before the later reading or after it, the reset having come between
        # that observation and the one before.
        self.two_readings()
        shown = {"before the later reading": [weekly(T0 - 3 * HOUR + 60, 60), weekly(T0 - 2 * HOUR, 62),
                                              weekly(T0 - 90 * 60, 21)],
                 "after the later reading": [weekly(T0 - 150 * 60, 62), weekly(T0 - 30 * 60, 21)]}
        for case, week in shown.items():
            with self.subTest(case):
                self.assertEqual(self.rates(week), (None, None))
        # One wholly before the pair is the earlier reading's own past.
        self.assertAlmostEqual(self.rates([weekly(T0 - 5 * HOUR, 62), weekly(T0 - 4 * HOUR, 21)])[0], 0.2)

    def test_a_rise_with_none_of_the_models_spend_here_measures_nothing(self):
        # The window rose 10 points and nothing was spent here: the model's use elsewhere. The pair after it is 0.2.
        self.reading(T0 - 5 * HOUR, 10)
        self.two_readings()
        self.assertAlmostEqual(self.rates()[0], 0.2)

    def test_what_does_not_measure_the_rate_leaves_it_unknown(self):
        cases = {
            "a full allowance, where the window stops rising": dict(first=90, second=100),
            "under the dollars a rate is trusted from": dict(first=20, second=22, dollars=4.0),
            "a response of the model's without a list price": dict(dollars=None),
            "readings that name no reset time": dict(resets_at=None),
            "an allowance claude.ai did not say": dict(allowance=None),
            "no rise": dict(first=20, second=20),
        }
        for case, readings in cases.items():
            with self.subTest(case):
                self.ledger.db.execute("DELETE FROM scoped_windows")
                self.ledger.db.execute("DELETE FROM responses")
                self.two_readings(**readings)
                self.assertEqual(self.rates(), (None, None))


class ProjectionTest(unittest.TestCase):
    """exhausts_at over a week rising 10 points an hour from 30 to 40."""

    WEEK_RISING = [weekly(T0, 30), weekly(T0 + HOUR, 40)]

    def test_without_a_plateau_the_pace_runs_on_to_the_top(self):
        self.assertAlmostEqual(exhausts_at(self.WEEK_RISING, T0 + HOUR), T0 + HOUR + 6 * HOUR)

    def test_a_plateau_takes_its_share_of_the_pace_away_once_its_headroom_is_used(self):
        # Half the pace is Fable's, 20 points left: 4 hours at 10 an hour to 80, then 5 an hour for the last 20.
        self.assertAlmostEqual(exhausts_at(self.WEEK_RISING, T0 + HOUR, [Plateau(0.5, 20.0)]), T0 + HOUR + 8 * HOUR)

    def test_a_full_allowance_takes_its_share_away_at_once(self):
        self.assertAlmostEqual(exhausts_at(self.WEEK_RISING, T0 + HOUR, [Plateau(0.5, 0.0)]), T0 + HOUR + 12 * HOUR)

    def test_a_pace_that_is_all_the_models_stops_where_its_allowance_does(self):
        self.assertIsNone(exhausts_at(self.WEEK_RISING, T0 + HOUR, [Plateau(1.0, 30.0)]))
        self.assertAlmostEqual(exhausts_at(self.WEEK_RISING, T0 + HOUR, [Plateau(1.0, 60.0)]), T0 + HOUR + 6 * HOUR)

    def test_plateaus_given_once_through_are_read_whole(self):
        once = (p for p in [Plateau(0.5, 20.0)])
        self.assertAlmostEqual(exhausts_at(self.WEEK_RISING, T0 + HOUR, once), T0 + HOUR + 8 * HOUR)


class RepriceTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.ledger = Ledger.open(self.machine.paths.ledger_db)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def stored(self, message_id, model, output_tokens):
        self.ledger.db.execute(
            "INSERT INTO responses(message_id, t, session_id, model, input_tokens, output_tokens, thinking_tokens, "
            "cache_read_tokens, cache_write_5m_tokens, cache_write_1h_tokens, web_search_requests, web_fetch_requests, "
            "cost_usd, account_uuid) VALUES (?, ?, 's', ?, 0, ?, 0, 0, 0, 0, 0, 0, NULL, ?)",
            (message_id, T0, model, output_tokens, ACCOUNT_A))

    def cost(self, message_id):
        return self.ledger.db.execute("SELECT cost_usd FROM responses WHERE message_id=?", (message_id,)).fetchone()[0]

    def test_a_response_read_before_its_model_had_a_price_is_priced_where_it_stands(self):
        # Fable 5.2's output is $40 a million tokens: a million is $40.
        self.stored("m1", "claude-fable-5-2", 1_000_000)
        self.stored("m2", "claude-unpublished-9", 1_000)
        self.stored("m3", "claude-unpublished-9", 1_000)
        self.assertEqual(reprice(self.ledger), Repricing(1, (("claude-unpublished-9", 2),)))
        self.assertAlmostEqual(self.cost("m1"), 40.0)
        self.assertIsNone(self.cost("m2"))
        self.assertEqual(reprice(self.ledger).priced, 0, "a priced response is not priced again")

    def test_each_model_still_without_a_price_is_a_source_problem(self):
        self.assertEqual(unpriced_problems(Repricing(0, (("claude-unpublished-9", 2), ("claude-x", 1)))), [
            "prices: claude-unpublished-9 has no list price, so the cost of its 2 responses counts as nothing",
            "prices: claude-x has no list price, so the cost of its 1 response counts as nothing"])

    def test_a_pass_names_the_unpriced_model_among_the_source_problems(self):
        self.stored("m2", "claude-unpublished-9", 1_000)
        self.ledger.db.commit()
        report = run_pass(self.machine.paths, T0, dashboard=False)
        self.assertIn("prices: claude-unpublished-9 has no list price, so the cost of its 1 response counts as nothing",
                      report.errors)


def standing(scoped=()) -> AccountStanding:
    account = Account(uuid=ACCOUNT_A, email=EMAIL_A, org_uuid=ORG_A, org_name=None, rate_limit_tier=None)
    return AccountStanding(
        account=account,
        five_hour=WindowStanding("five_hour", "no_limit", None, None, T0, False),
        weekly=WindowStanding("seven_day", "current", 22.0, RESET, T0, False, None, reset_exact=True),
        anchor=None, last_activity=T0, is_desktop=True, is_cli=True, scoped=tuple(scoped))


FABLE = ScopedStanding("Fable", "current", 24.06, RESET, T0 - HOUR, True, 50.0)


class StatusTest(unittest.TestCase):
    def document(self, scoped=()):
        current = [standing(scoped)]
        return status_document(current, recommend(current), now=T0, desktop_account=ACCOUNT_A,
                               cli_account=ACCOUNT_A, cli_condition=None)

    def test_the_weekly_window_carries_the_accounts_per_model_windows(self):
        weekly = self.document([FABLE])["accounts"][0]["weekly"]
        self.assertEqual(weekly["scoped"], [{"name": "Fable", "state": "current", "percent": 24.1,
                                             "resetsAt": iso(RESET), "asOf": iso(T0 - HOUR), "estimated": True,
                                             "allowanceOfWeekly": 50.0}])

    def test_an_account_with_none_has_no_key(self):
        self.assertNotIn("scoped", self.document()["accounts"][0]["weekly"])

    def test_the_window_reads_it_back(self):
        status = parse_status(json.loads(json.dumps(self.document([FABLE]))))
        (scoped,) = status.accounts[0].weekly.scoped
        self.assertEqual((scoped.name, scoped.state, scoped.percent, scoped.resets_at, scoped.as_of, scoped.estimated,
                          scoped.allowance), ("Fable", "current", 24.1, RESET, T0 - HOUR, True, 50.0))

    def test_one_not_in_its_shape_reads_as_none_and_the_document_stands(self):
        document = self.document([FABLE])
        document["accounts"][0]["weekly"]["scoped"] = [{"state": "current"}]
        self.assertEqual(parse_status(document).accounts[0].weekly.scoped, ())


class CardTest(unittest.TestCase):
    def rows(self, scoped):
        document = StatusTest().document([scoped])
        account = parse_status(json.loads(json.dumps(document))).accounts[0]
        return scoped_row(account.weekly.scoped[0], account.weekly, T0)

    def test_its_figure_its_level_and_what_it_rests_on(self):
        row = self.rows(ScopedStanding("Fable", "current", 85.0, RESET, T0 - HOUR, True, 50.0))
        self.assertEqual((row.name, row.figure, row.level, row.metered), ("Fable", "≈85%", 1, False))
        self.assertEqual(row.detail, "", "its reset is the week's, said on the weekly window")
        self.assertEqual(row.note, "50% of the weekly limit · read on claude.ai 1h 00m ago")

    def test_unknown_says_why(self):
        row = self.rows(ScopedStanding("Fable", "unknown", None, RESET, T0 - HOUR, False, 50.0))
        self.assertEqual(row.figure, "unknown")
        self.assertIn("a reset came since claude.ai was read", row.note)


if __name__ == "__main__":
    unittest.main()
