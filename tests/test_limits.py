"""limits: window standings, the weekly anchor, extra resets, the recommendation and blocked time.

Expected values are derived from the window rules (a 5-hour window starts with the first message after the previous
one ended; the weekly window resets every seven days at one instant), never read back from the code.
"""

import unittest

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bridge_line,
                      epoch)
from windowtally.accounts import Account, by_org, load_registry
from windowtally.attribution import attribute
from windowtally.ingest_app_history import ingest_app_history
from windowtally.ingest_transcripts import ingest_transcripts
from windowtally.ledger import Ledger, Observation
from windowtally.limits import (FIVE_HOURS, WEEK, AccountStanding, WindowStanding, account_standing,
                                all_blocked_spans, blocked_spans_of, exhausts_at, five_hour_standing,
                                percent_per_dollar, recommend, weekly_anchor, weekly_standing)

T0 = epoch("2026-10-20T10:00:00Z")


def obs(t, percent, kind="five_hour", resets_at=None, source="plugin"):
    return Observation(source, "ref", t, kind, percent, resets_at, ACCOUNT_A)


class FiveHourTest(unittest.TestCase):
    def test_a_reading_inside_its_window(self):
        w = five_hour_standing([obs(T0, 26, resets_at=T0 + 3 * 3600)], [], T0 + 600)
        self.assertEqual((w.state, w.percent, w.resets_at, w.as_of, w.estimated), ("running", 26, T0 + 3 * 3600, T0, False))

    def test_past_its_end_with_no_message_it_has_not_started(self):
        w = five_hour_standing([obs(T0, 26, resets_at=T0 + 3600)], [T0 - 60], T0 + 7200)
        self.assertEqual((w.state, w.percent, w.resets_at), ("not_started", 0.0, None))

    def test_the_first_message_after_the_end_opens_a_window(self):
        end = T0 + 3600
        w = five_hour_standing([obs(T0, 26, resets_at=end)], [end + 100, end + 200], end + 300)
        self.assertEqual((w.state, w.resets_at, w.estimated), ("running", end + 100 + FIVE_HOURS, True))

    def test_windows_chain_through_continued_use(self):
        end = T0 + 3600
        second = end + 100 + FIVE_HOURS + 50
        w = five_hour_standing([obs(T0, 26, resets_at=end)], [end + 100, end + 4000, second], second + 10)
        self.assertEqual(w.resets_at, second + FIVE_HOURS)

    def test_without_a_reset_time_the_window_starts_at_the_first_message_of_its_run(self):
        samples = [obs(T0, 0, source="app"), obs(T0 + 900, 5, source="app"), obs(T0 + 1800, 12, source="app")]
        w = five_hour_standing(samples, [T0 - 4000, T0 + 300, T0 + 1000], T0 + 2000)
        self.assertEqual((w.state, w.percent, w.resets_at, w.estimated), ("running", 12, T0 + 300 + FIVE_HOURS, True))

    def test_no_observation_and_no_message(self):
        self.assertEqual(five_hour_standing([], [], T0).state, "unknown")

    def test_with_no_observation_windows_chain_from_the_first_message(self):
        # Messages at T0 and T0+1h open and continue one window; the first message after it ended opens the next.
        activity = [T0, T0 + 3600, T0 + FIVE_HOURS + 100, T0 + FIVE_HOURS + 200]
        w = five_hour_standing([], activity, T0 + FIVE_HOURS + 300)
        self.assertEqual((w.state, w.resets_at, w.estimated), ("running", T0 + 2 * FIVE_HOURS + 100, True))


class WeeklyTest(unittest.TestCase):
    def test_a_reading_before_its_reset(self):
        w = weekly_standing([obs(T0, 60, kind="seven_day", resets_at=T0 + 86400)], None, T0 + 3600)
        self.assertEqual((w.state, w.percent, w.resets_at, w.estimated), ("current", 60, T0 + 86400, False))

    def test_rolled_through_resets_since_the_reading(self):
        reset = T0 + 86400
        w = weekly_standing([obs(T0, 60, kind="seven_day", resets_at=reset)], None, reset + WEEK + 10)
        self.assertEqual((w.percent, w.resets_at, w.estimated), (0.0, reset + 2 * WEEK, False))

    def test_projection_at_the_recent_pace(self):
        now = T0
        samples = [obs(now - 1800, 50, kind="seven_day", resets_at=now + 86400),
                   obs(now - 600, 60, kind="seven_day", resets_at=now + 86400)]
        # 10 points in 1200 s; 40 points to go from now - 600.
        self.assertAlmostEqual(exhausts_at(samples, now), now - 600 + 4800)
        self.assertAlmostEqual(weekly_standing(samples, None, now).exhausts_at, now - 600 + 4800)


class HighestReadingTest(unittest.TestCase):
    """Use only raises a window's figure, so the figure is the highest any observation of the window read."""

    def test_a_5_hour_reading_trailing_another_session_s_does_not_lower_the_figure(self):
        end = T0 + 3 * 3600
        w = five_hour_standing([obs(T0, 30, resets_at=end), obs(T0 + 5, 25, resets_at=end)], [], T0 + 60)
        self.assertEqual((w.percent, w.as_of), (30, T0 + 5))

    def test_an_app_sample_a_point_above_claude_code_s_reading_raises_the_figure(self):
        end = T0 + 3 * 3600
        w = five_hour_standing([obs(T0 - 600, 36, source="app"), obs(T0, 35, resets_at=end)], [], T0 + 60)
        self.assertEqual(w.percent, 36)

    def test_a_reading_of_the_window_before_does_not_count_for_this_one(self):
        # A session handing on its reading of the window that ended an hour ago, after this window's first reading.
        end = T0 + 3 * 3600
        w = five_hour_standing([obs(T0, 20, resets_at=end), obs(T0 + 60, 90, resets_at=end - FIVE_HOURS - 3600),
                                obs(T0 + 120, 21, resets_at=end)], [], T0 + 180)
        self.assertEqual(w.percent, 21)

    def test_an_observation_from_before_the_5_hour_window_began_does_not_count(self):
        end = T0 + 3 * 3600
        w = five_hour_standing([obs(end - FIVE_HOURS - 600, 80, source="app"), obs(T0, 10, resets_at=end)], [], T0 + 60)
        self.assertEqual(w.percent, 10)

    def test_a_weekly_reading_trailing_by_a_point_does_not_lower_the_figure(self):
        reset = T0 + 86400
        w = weekly_standing([obs(T0, 61, kind="seven_day", resets_at=reset),
                             obs(T0 + 5, 60, kind="seven_day", resets_at=reset)], None, T0 + 60)
        self.assertEqual(w.percent, 61)

    def test_a_weekly_fall_of_a_reset_s_size_starts_the_window_again(self):
        # An unscheduled reset: the figure falls from 70 to 4 with the reset time unchanged.
        reset = T0 + 86400
        w = weekly_standing([obs(T0, 70, kind="seven_day", resets_at=reset),
                             obs(T0 + 3600, 4, kind="seven_day", resets_at=reset),
                             obs(T0 + 3605, 3, kind="seven_day", resets_at=reset)], None, T0 + 3700)
        self.assertEqual(w.percent, 4)

    def test_last_week_s_readings_do_not_count_for_this_week(self):
        reset = T0 + 86400
        w = weekly_standing([obs(reset - WEEK - 600, 95, kind="seven_day", resets_at=reset - WEEK),
                             obs(T0, 2, kind="seven_day", resets_at=reset)], None, T0 + 60)
        self.assertEqual(w.percent, 2)

    def test_the_estimate_adds_only_what_was_spent_after_the_latest_observation(self):
        # The latest reading already counts the use before it, whatever figure it reads, so the estimate's rise starts
        # there: 36 + 0.5 points per dollar × $2.
        class Spending:
            starts: list = []

            def cost_between(self, account, start, now):
                self.starts.append(start)
                return 2.0

        end, spending = T0 + 3 * 3600, Spending()
        w = five_hour_standing([obs(T0 - 600, 36, source="app"), obs(T0, 35, resets_at=end)], [], T0 + 60,
                               rate=0.5, ledger=spending, account=ACCOUNT_A)
        self.assertEqual((w.percent, w.estimated, spending.starts), (37.0, True, [T0]))

    def test_with_no_reset_time_known_the_latest_weekly_sample_stands_alone(self):
        # No reading names the week's reset and no fall shows one, so last week's 40 may be what came before it.
        w = weekly_standing([obs(T0 - 2 * 86400, 40, kind="seven_day", source="app"),
                             obs(T0, 38, kind="seven_day", source="app")], None, T0 + 60)
        self.assertEqual(w.percent, 38)

    def test_a_trailing_reading_leaves_the_projection_at_the_pace_of_the_highest(self):
        end = T0 + 3 * 3600
        samples = [obs(T0 - 1800, 50, resets_at=end), obs(T0 - 600, 60, resets_at=end),
                   obs(T0 - 590, 56, resets_at=end)]
        # 10 points in 1210 s counted at the highest figure, 40 points to go from the latest observation.
        self.assertAlmostEqual(exhausts_at(samples, T0), T0 - 590 + 40 * 1210 / 10)


class AnchorTest(unittest.TestCase):
    """Three weeks of app samples around a Saturday 02:00 UTC reset, with an extra reset on one Wednesday."""

    def samples(self):
        saturday = epoch("2026-10-03T02:00:00Z")
        gaps = [(-3 * 3600, 4 * 3600), (-1 * 3600, 7 * 3600), (-6 * 3600, 1 * 3600)]
        result = []
        for week, (before, after) in enumerate(gaps):
            reset = saturday + week * WEEK
            result += [obs(reset - 3 * 86400 + h * 900, 60 + h * 0.5, kind="seven_day", source="app") for h in range(8)]
            result.append(obs(reset + before, 95, kind="seven_day", source="app"))
            result.append(obs(reset + after, 2, kind="seven_day", source="app"))
        wednesday = saturday + 4 * 86400 + 10 * 3600
        result += [obs(wednesday - 900, 80, kind="seven_day", source="app"),
                   obs(wednesday + 900, 5, kind="seven_day", source="app")]
        return sorted(result, key=lambda o: o.t), saturday, wednesday

    def test_inferred_within_the_window_every_fall_allows(self):
        samples, saturday, _ = self.samples()
        anchor = weekly_anchor(samples)
        self.assertFalse(anchor.exact)
        # Every scheduled fall lies in (Sat 01:00, Sat 03:00]; the middle of that run is Sat 02:00.
        offset = (anchor.at - saturday) % WEEK
        offset = min(offset, WEEK - offset)
        self.assertLessEqual(offset, 1800)

    def test_the_unscheduled_fall_is_one_the_inferred_schedule_does_not_explain(self):
        # No scheduled reset lies between the readings either side of Wednesday's fall: a reset outside the schedule.
        samples, _, wednesday = self.samples()
        self.assertGreater(weekly_anchor(samples).next_after(wednesday - 900), wednesday + 900)

    def test_a_reading_gives_the_exact_anchor(self):
        anchor = weekly_anchor([obs(T0, 50, kind="seven_day", resets_at=T0 + 1000)])
        self.assertEqual((anchor.at, anchor.exact), (T0 + 1000, True))
        self.assertEqual(anchor.next_after(T0 + 1000), T0 + 1000 + WEEK)


def standing(label, weekly_percent, weekly_reset, five_state="not_started", five_percent=0.0, five_reset=None):
    account = Account(uuid=label, email=f"{label}@example.com")
    return AccountStanding(account, WindowStanding("five_hour", five_state, five_percent, five_reset, None, False),
                           WindowStanding("seven_day", "current", weekly_percent, weekly_reset, None, False),
                           None, None, False, False)


class RecommendTest(unittest.TestCase):
    def test_the_usable_account_whose_weekly_allowance_expires_first(self):
        rec = recommend([standing("a", 50, T0 + 3 * 86400), standing("b", 20, T0 + 5 * 86400),
                         standing("c", 97, T0 + 86400)])
        self.assertEqual(rec.account_uuid, "a")

    def test_an_account_whose_five_hour_window_is_nearly_full_waits(self):
        rec = recommend([standing("a", 50, T0 + 3 * 86400, "running", 92, T0 + 3600),
                         standing("b", 20, T0 + 5 * 86400)])
        self.assertEqual(rec.account_uuid, "b")

    def test_with_none_under_the_ceilings_the_most_of_a_week_left_and_the_earliest_relief(self):
        rec = recommend([standing("a", 96, T0 + 2 * 86400), standing("b", 50, T0 + 5 * 86400, "running", 95, T0 + 3600)])
        self.assertEqual(rec.account_uuid, "b")
        self.assertEqual(rec.relief_at, T0 + 3600)


class AtOrNearTheLimitTest(unittest.TestCase):
    """Past the recommendation's ceilings an account can still be used; only ``CAPPED`` blocks it."""

    def test_the_account_with_the_most_of_its_week_left_is_recommended(self):
        rec = recommend([standing("a", 99, T0 + 34500), standing("b", 98, T0 + 41700), standing("c", 95, T0 + 192900)])
        self.assertEqual(rec.account_uuid, "c")
        self.assertEqual(rec.relief_at, T0 + 34500)
        self.assertIn("Every account is at or near its limit. c has the most left. Room returns ≈", rec.reason)

    def test_equal_weeks_fall_to_the_one_that_resets_first(self):
        rec = recommend([standing("a", 97, T0 + 3 * 86400), standing("b", 97, T0 + 2 * 86400)])
        self.assertEqual(rec.account_uuid, "b")

    def test_a_five_hour_window_near_its_limit_does_not_block_an_account(self):
        rec = recommend([standing("a", 50, T0 + 5 * 86400, "running", 92, T0 + 3600), standing("b", 97, T0 + 86400)])
        self.assertEqual((rec.account_uuid, rec.relief_at), ("a", T0 + 3600))

    def test_a_blocked_account_is_never_the_one_recommended(self):
        rec = recommend([standing("a", 40, T0 + 86400, "running", 99, T0 + 3600), standing("b", 96, T0 + 2 * 86400)])
        self.assertEqual(rec.account_uuid, "b")

    def test_an_account_with_no_weekly_figure_comes_after_every_account_with_one(self):
        rec = recommend([standing("a", None, None, "running", 95, T0 + 3600), standing("b", 96, T0 + 86400)])
        self.assertEqual(rec.account_uuid, "b")

    def test_room_returns_with_the_first_account_under_the_ceilings_not_at_a_reset_that_leaves_none(self):
        rec = recommend([standing("a", 96, T0 + 2 * 86400, "running", 99, T0 + 3600),
                         standing("b", 97, T0 + 3 * 86400)])
        self.assertEqual((rec.account_uuid, rec.relief_at), ("b", T0 + 2 * 86400))

    def test_with_no_reset_known_the_reason_names_none(self):
        rec = recommend([standing("a", 97, None)])
        self.assertEqual((rec.account_uuid, rec.relief_at, rec.relief_exact), ("a", None, False))
        self.assertEqual(rec.reason, "Every account is at or near its limit. a has the most left.")


class EveryAccountBlockedTest(unittest.TestCase):
    def test_at_the_cap_none_is_recommended_and_the_first_opens_at_the_earliest_reset(self):
        rec = recommend([standing("a", 99, T0 + 86400), standing("b", 100, T0 + 2 * 86400)])
        self.assertEqual((rec.account_uuid, rec.relief_at), (None, T0 + 86400))
        self.assertTrue(rec.reason.startswith("Every account is at its limit. The first opens ≈"))

    def test_a_capped_five_hour_window_opens_at_its_own_reset_though_the_week_is_past_the_ceiling(self):
        rec = recommend([standing("a", 96, T0 + 2 * 86400, "running", 99, T0 + 3600)])
        self.assertEqual((rec.account_uuid, rec.relief_at), (None, T0 + 3600))

    def test_a_capped_week_opens_at_its_reset_whatever_the_five_hour_window_says(self):
        rec = recommend([standing("a", 99, T0 + 2 * 86400, "running", 99, T0 + 3600)])
        self.assertEqual(rec.relief_at, T0 + 2 * 86400)

    def test_with_no_reset_known_there_is_no_opening_to_name(self):
        rec = recommend([standing("a", 99, None)])
        self.assertEqual((rec.account_uuid, rec.reason, rec.relief_at), (None, "Every account is at its limit.", None))


class BlockedTest(unittest.TestCase):
    def test_spans_end_at_the_reset_or_the_next_reading_below_the_cap(self):
        weekly = [obs(T0, 99.5, kind="seven_day", resets_at=T0 + 5000), obs(T0 + 1000, 99.7, kind="seven_day", resets_at=T0 + 5000)]
        self.assertEqual(blocked_spans_of(weekly, "seven_day", None, T0 + 10 ** 6), [(T0, T0 + 5000)])
        five_hour = [obs(T0, 100, source="app"), obs(T0 + 3600, 40, source="app")]
        self.assertEqual(blocked_spans_of(five_hour, "five_hour", None, T0 + 10 ** 6), [(T0, T0 + 3600)])

    def test_a_capped_five_hour_sample_blocks_only_until_its_window_could_have_ended(self):
        # The window was already running at T0, so it ended by T0 + 5 h, however long nothing was seen after.
        five_hour = [obs(T0, 50, source="app"), obs(T0 + 3600, 100, source="app")]
        self.assertEqual(blocked_spans_of(five_hour, "five_hour", None, T0 + 10 ** 6), [(T0 + 3600, T0 + FIVE_HOURS)])

    def test_every_account_blocked_and_an_account_not_yet_seen_counts_as_blocked(self):
        machine = Machine()
        try:
            machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
            machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
            machine.app_history([(T0, ORG_A, 100, 50), (T0 + 7200, ORG_A, 0, 50),
                                 (T0 + 3600, ORG_B, 100, 50), (T0 + 9000, ORG_B, 0, 50)])
            ledger = Ledger.open(machine.paths.ledger_db)
            registry, _ = load_registry(machine.paths.accounts_dir)
            ingest_app_history(ledger, machine.paths.plan_usage_history, by_org(registry))
            # A: blocked (T0, T0+7200). B: not seen before T0+3600, then blocked (T0+3600, T0+9000).
            self.assertEqual(all_blocked_spans(ledger, registry.values(), T0, T0 + 20000), [(T0, T0 + 7200)])
            ledger.close()
        finally:
            machine.close()


class EstimateTest(unittest.TestCase):
    def test_the_rise_since_the_last_reading_is_estimated_from_recent_cost(self):
        machine = Machine()
        try:
            machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
            machine.app_history([(T0, ORG_A, 10, 40), (T0 + 3600, ORG_A, 12, 42)])
            # claude-opus-5-5 output at $20 per million: 500k tokens cost $10, 250k tokens $5.
            lines = [bridge_line("s1", ACCOUNT_A, ORG_A)]
            lines += assistant_lines("m1", T0 + 1800, "s1", outputs=(500_000,), input_tokens=0, cache_read=0, cache_write_1h=0)
            lines += assistant_lines("m2", T0 + 5000, "s1", outputs=(250_000,), input_tokens=0, cache_read=0, cache_write_1h=0)
            machine.transcript("s1", lines)
            ledger = Ledger.open(machine.paths.ledger_db)
            registry, _ = load_registry(machine.paths.accounts_dir)
            ingest_app_history(ledger, machine.paths.plan_usage_history, by_org(registry))
            ingest_transcripts(ledger, machine.paths.projects_dir)
            attribute(ledger)
            weekly = account_standing(ledger, registry[ACCOUNT_A], T0 + 6000).weekly
            # 2 points for $10 between the samples: 0.2 points per dollar; $5 since the last one adds 1 point.
            self.assertAlmostEqual(weekly.percent, 43.0)
            self.assertTrue(weekly.estimated)
            ledger.close()
        finally:
            machine.close()


class RateTest(unittest.TestCase):
    """The estimates' points per dollar over readings and responses written row by row."""

    def setUp(self):
        self.machine = Machine()
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        self.responses = 0

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def reading(self, t, percent, source="plugin", resets_at=T0 + 4 * 3600):
        self.ledger.db.execute(
            "INSERT INTO observations(source, ref, t, kind, percent, resets_at, account_uuid, account_source) "
            "VALUES (?, 'ref', ?, 'five_hour', ?, ?, ?, 'test')",
            (source, t, float(percent), resets_at if source == "plugin" else None, ACCOUNT_A))

    def response(self, t, dollars):
        self.responses += 1
        self.ledger.db.execute(
            "INSERT INTO responses(message_id, t, session_id, input_tokens, output_tokens, thinking_tokens, "
            "cache_read_tokens, cache_write_5m_tokens, cache_write_1h_tokens, web_search_requests, web_fetch_requests, "
            "cost_usd, account_uuid) VALUES (?, ?, 's', 0, 0, 0, 0, 0, 0, 0, 0, ?, ?)",
            (f"m{self.responses}", t, dollars, ACCOUNT_A))

    def test_a_reading_trailing_another_session_s_neither_adds_to_the_rise_nor_takes_from_it(self):
        # 20, 25, 24, 30 with $2 before each later reading: the run rises 30 - 20 = 10 points for $6.
        for index, percent in enumerate((20, 25, 24, 30)):
            if index:
                self.response(T0 + index * 600 - 60, 2.0)
            self.reading(T0 + index * 600, percent)
        self.assertAlmostEqual(percent_per_dollar(self.ledger, ACCOUNT_A, "five_hour", T0 + 3600), 10 / 6)

    def test_an_app_sample_among_the_plugin_s_readings_is_left_out(self):
        # The sample reads a point above the plugin's next reading: paired with them it would count 11 points.
        self.reading(T0, 20)
        self.response(T0 + 240, 3.0)
        self.reading(T0 + 300, 31, source="app")
        self.response(T0 + 540, 3.0)
        self.reading(T0 + 600, 30)
        self.assertAlmostEqual(percent_per_dollar(self.ledger, ACCOUNT_A, "five_hour", T0 + 3600), 10 / 6)


if __name__ == "__main__":
    unittest.main()
