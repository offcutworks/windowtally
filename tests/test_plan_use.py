"""plan_use: what the plans covered of the API-equivalent use — less the use at extra usage, and, without resets, less
the use beyond one window a week — and the weekly window's resets outside its schedule, by kind; and where the history,
the page, the window, status.json and the month's line show them.

Expected values are worked by hand from the maintainer's decisions of 2026-11-11: a response made while a window stood
exhausted, or a model's response while its own allowance stood full, was paid at extra usage and counts in no multiple;
the multiple without resets counts, per account and week, only the use up to the moment the week's use — every reading's
rise, a fall being a reset after which the count goes on from the next reading — reaches one full window, the dollars
across that moment split by points; a fall that gives back about the model's share of the week is a reset of its
allowance, one the model's share cannot explain is the week given back. They are never read back from the code.
"""

import re
import unittest
from fractions import Fraction
from html import escape

from fixtures import ACCOUNT_A, ACCOUNT_B, EMAIL_A, ORG_A, Machine, bill, epoch
from windowtally import history
from windowtally.accounts import Account, load_registry
from windowtally.billing import billing_report, month_totals_text
from windowtally.bills import load_bills
from windowtally.capacity import PlanSpan, steps
from windowtally.dashboard import _weekly_chart
from windowtally.ledger import Ledger
from windowtally.limits import WEEK, Recommendation
from windowtally.plan_use import Reset, Use, Week, plan_use
from windowtally.status_file import status_document
from windowtally_gui import history_model
from windowtally_gui.history_model import Chart, Legend

MINUTE, HOUR, DAY = 60.0, 3600.0, 86400.0
END = epoch("2026-11-07T12:00:00Z")      # the week's scheduled reset
START = END - WEEK
ALPHA = history.Entity(ACCOUNT_A, "alpha", "series-1")
FABLE, OPUS = "claude-fable-5-2", "claude-opus-5-5"


class LedgerCase(unittest.TestCase):
    """A ledger written row by row: one week of readings and responses of account A."""

    def setUp(self):
        self.machine = Machine()
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        self.responses = 0
        self.t = START + HOUR
        self.reading(self.t, 0)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def reading(self, t, percent, kind="seven_day", resets=END, account=ACCOUNT_A):
        self.ledger.db.execute(
            "INSERT INTO observations(source, ref, t, kind, percent, resets_at, account_uuid, account_source) "
            "VALUES ('plugin', ?, ?, ?, ?, ?, ?, 'test')", (account, t, kind, float(percent), resets, account))

    def response(self, t, dollars, model=OPUS, account=ACCOUNT_A):
        self.responses += 1
        self.ledger.db.execute(
            "INSERT INTO responses(message_id, t, session_id, model, input_tokens, output_tokens, thinking_tokens, "
            "cache_read_tokens, cache_write_5m_tokens, cache_write_1h_tokens, web_search_requests, web_fetch_requests, "
            "cost_usd, account_uuid) VALUES (?, ?, 's', ?, 0, 0, 0, 0, 0, 0, 0, 0, ?, ?)",
            (f"m{self.responses}", t, model, dollars, account))

    def allowance(self, t, percent, account=ACCOUNT_A, allowance=50.0):
        """claude.ai's reading of Fable's window: ``percent`` of an allowance of half the week."""
        self.ledger.db.execute(
            "INSERT INTO scoped_windows(source, ref, t, name, percent, resets_at, allowance, account_uuid, "
            "account_source) VALUES ('browser', ?, ?, 'Fable', ?, ?, ?, ?, 'org')",
            (ORG_A, t, float(percent), END, allowance, account))

    def use(self, *weekly, dollars=10.0, model=OPUS, every=10 * MINUTE):
        """A response of ``dollars`` then, a minute later, the weekly reading it brought, for each of ``weekly``."""
        for percent in weekly:
            self.t += every
            self.response(self.t, dollars, model)
            self.reading(self.t + MINUTE, percent)
        self.t += MINUTE

    def idle(self, *weekly, every=10 * MINUTE):
        """Weekly readings with no response before them: use elsewhere, or a reset."""
        for percent in weekly:
            self.t += every
            self.reading(self.t, percent)

    def week(self) -> tuple[Use, tuple]:
        found = plan_use(self.ledger, START, END)
        return found.between(START, END), found.weeks(ACCOUNT_A)


class ExhaustedTest(LedgerCase):
    def test_use_while_the_week_stood_exhausted_is_outside_the_plans_and_a_week_without_a_fall_has_none_beyond(self):
        self.use(*range(10, 101, 10))                     # $100 takes the week to 100 %
        self.response(self.t + 5 * MINUTE, 10.0)          # two responses more: only extra usage answers them
        self.response(self.t + 6 * MINUTE, 10.0)
        use, weeks = self.week()
        self.assertEqual((use.api, use.outside, use.beyond), (120.0, 20.0, 0.0))
        self.assertEqual((use.in_plans, use.one_window), (100.0, 100.0))
        self.assertEqual([(w.used, w.resets) for w in weeks], [(100.0, ())])

    def test_use_while_the_five_hour_window_stood_exhausted_is_outside_the_plans(self):
        self.reading(self.t + MINUTE, 100, kind="five_hour", resets=self.t + 3 * HOUR)
        self.response(self.t + 2 * MINUTE, 7.0)
        self.response(self.t + 3 * HOUR + MINUTE, 5.0)    # the 5-hour window has reset: the plan's again
        use, _weeks = self.week()
        self.assertEqual((use.api, use.outside), (12.0, 7.0))


class BeyondTest(LedgerCase):
    def test_use_after_a_reset_past_one_full_window_is_beyond_it_split_by_points_across_the_moment(self):
        self.use(10, 20, 30, 40, 50, 60)                  # $60, 60 points
        self.idle(0)                                      # a reset outside the schedule: the week given back
        self.use(15, 30, 45, dollars=15.0)                # 75, 90, then 105 points: a third of the last $15 beyond
        use, weeks = self.week()
        self.assertEqual(use.api, 105.0)
        self.assertAlmostEqual(use.beyond, 5.0)
        self.assertAlmostEqual(use.one_window, 100.0)
        (week,) = weeks
        self.assertEqual(week.used, 105.0)
        self.assertEqual([(r.kind, r.model, r.given) for r in week.resets], [("extra", None, 60.0)])
        self.assertAlmostEqual(week.beyond, 5.0)

    def test_the_use_between_a_reset_and_the_first_reading_after_it_is_not_counted(self):
        self.use(10, 20, 30, 40, 50, 60, 70, 80)          # 80 points
        self.response(self.t + MINUTE, 10.0)              # after a reset no reading saw, 25 points from nothing
        self.t += 2 * MINUTE
        self.idle(25)                                     # the first reading after it: the week fell from 80
        self.use(30, dollars=10.0)                        # counted from 25: 85 points in all, none beyond
        use, weeks = self.week()
        self.assertEqual(weeks[0].used, 85.0)
        self.assertEqual(use.beyond, 0.0)

    def test_a_reading_of_a_window_already_over_is_left_out(self):
        self.use(10, 20)
        self.t = END + HOUR
        self.reading(self.t, 2, resets=END + WEEK)        # the next week
        self.reading(self.t + MINUTE, 20, resets=END)     # a session hands on last week's figure late
        self.reading(self.t + 2 * MINUTE, 3, resets=END + WEEK)
        weeks = plan_use(self.ledger, START, END + DAY).weeks(ACCOUNT_A)
        self.assertEqual([(w.end, w.resets) for w in weeks], [(END, ()), (END + WEEK, ())])


class ModelTest(LedgerCase):
    def fable_then_reset(self):
        """Fable takes the week to 50 % and its own allowance to full; two Fable responses then run at usage credits;
        the user resets Fable's allowance, the next response's reading showing the week fallen to 10 %; Opus then takes
        the week to 40 %."""
        self.use(10, 20, 30, 40, 50, dollars=20.0, model=FABLE)
        self.allowance(self.t + MINUTE, 100)
        self.t += MINUTE
        self.use(50, 50, dollars=20.0, model=FABLE)
        self.use(10, dollars=20.0, model=FABLE)
        self.use(20, 30, 40, dollars=50.0)

    def test_a_model_s_use_past_its_allowance_is_outside_the_plans_and_a_fall_giving_its_share_back_resets_it(self):
        self.fable_then_reset()
        use, weeks = self.week()
        self.assertEqual((use.api, use.outside), (310.0, 40.0), "the two responses at usage credits")
        (week,) = weeks
        self.assertEqual([(r.kind, r.model, r.given) for r in week.resets], [("model", "Fable", 40.0)])
        self.assertEqual((week.used, use.beyond), (80.0, 0.0), "50 points, then 30 counted from the 10 % reading")

    def test_a_model_s_rate_is_read_off_claude_ai_s_readings_of_its_window_where_they_measure_it(self):
        # Opus's $50 raised the week 2 points, 0.04 a dollar. claude.ai read Fable's window at nothing; Fable's $20 then
        # came with 10 points more, of which claude.ai read 10 % of its window, 5 weekly points: 0.25 a dollar, the
        # rest of that rise use elsewhere. Its next $60 takes 15 weekly points at that, its window to 40 %, so the
        # response after them is the plans'. What the weekly rises would leave Fable, 0.75 a dollar, fills its
        # allowance on those $60 and puts that response outside them.
        self.use(2, dollars=50.0)
        self.t += 4 * HOUR
        self.idle(2)
        self.allowance(self.t + MINUTE, 0)
        self.t += 2 * MINUTE
        self.use(12, dollars=20.0, model=FABLE)
        self.allowance(self.t + MINUTE, 10)
        self.t += 2 * MINUTE
        self.response(self.t, 60.0, FABLE)
        self.response(self.t + MINUTE, 250.0)
        self.reading(self.t + 2 * MINUTE, 72)
        self.t += 2 * MINUTE
        self.use(73, dollars=1.0, model=FABLE)
        use, _weeks = self.week()
        self.assertEqual((use.api, use.outside), (381.0, 0.0))

    def test_what_a_full_window_holds_leaves_the_use_at_usage_credits_out(self):
        self.fable_then_reset()
        span = {ACCOUNT_A: [PlanSpan(START - DAY, END + DAY, "ultra")]}
        weekly = [s for s in steps(self.ledger, span, START, END) if s.kind == "seven_day"]
        # Fable's $100 and Opus's $150 raised the week; the $40 at usage credits raised nothing, and the response whose
        # reading shows the reset ends a run.
        self.assertEqual(sum(s.dollars for s in weekly), 250.0)
        self.assertEqual(sum(s.points for s in weekly), 80.0)

    def test_a_fall_giving_back_more_than_the_model_held_is_an_extra_reset(self):
        self.allowance(self.t + MINUTE, 0)
        self.t += MINUTE
        self.use(10, 20, dollars=20.0, model=FABLE)       # Fable holds 20 points of the week
        self.use(30, 40, 50, 60, 70, dollars=50.0)
        self.idle(0)                                      # 70 points given back: more than Fable's 20
        _use, weeks = self.week()
        self.assertEqual([(r.kind, r.given) for r in weeks[0].resets], [("extra", 70.0)])

    def test_a_fall_while_the_model_was_used_and_its_allowance_not_read_for_the_account_is_of_a_kind_not_known(self):
        self.allowance(self.t, 10, account=ACCOUNT_B)    # claude.ai reads Fable's window on another account
        self.use(10, 20, dollars=20.0, model=FABLE)
        self.idle(0)
        _use, weeks = self.week()
        self.assertEqual([r.kind for r in weeks[0].resets], ["unknown"])

    def test_before_claude_ai_first_read_a_model_s_window_its_use_is_the_plans_and_no_fall_is_its_reset(self):
        # The week before: Fable alone takes the week to 80 %, past its half, and the week falls by 50 points — what a
        # reset of a half-week allowance would give back. claude.ai first reads Fable's window only the week after.
        t = START - WEEK + HOUR
        self.reading(t, 0, resets=START)
        for level in (20, 40, 60, 80):
            t += 10 * MINUTE
            self.response(t, 20.0, FABLE)
            self.reading(t + MINUTE, level, resets=START)
        self.reading(t + 20 * MINUTE, 30, resets=START)
        self.allowance(self.t + MINUTE, 0)
        use = plan_use(self.ledger, START - WEEK, END)
        before = use.between(START - WEEK, START)
        self.assertEqual((before.api, before.outside), (80.0, 0.0))
        self.assertEqual([(r.kind, r.given) for r in use.weeks(ACCOUNT_A)[0].resets], [("extra", 50.0)])

    def test_after_claude_ai_first_read_a_model_s_window_every_week_counts_its_allowance_read_or_not(self):
        self.allowance(self.t + MINUTE, 0)                # read once, in this week
        t = END + HOUR
        self.reading(t, 0, resets=END + WEEK)
        for level in (20, 40, 60, 80):                    # the next week, which claude.ai never reads
            t += 10 * MINUTE
            self.response(t, 20.0, FABLE)
            self.reading(t + MINUTE, level, resets=END + WEEK)
        # Fable's level is twice the week's rise, its allowance being half the week: 120 % before the last response.
        use = plan_use(self.ledger, START, END + WEEK).between(END, END + WEEK)
        self.assertEqual((use.api, use.outside), (80.0, 20.0))

    def test_a_week_re_anchored_into_the_one_before_judges_its_fall_from_the_model_s_first_reading(self):
        later = END + 4 * DAY                             # the schedule moved: the next week starts 3 days before END
        self.allowance(START + HOUR, 0, account=ACCOUNT_B)   # Fable's window read once, on another account
        self.response(START + 3 * HOUR, 10.0, FABLE)
        self.reading(START + 3 * HOUR + MINUTE, 20)
        self.response(END - 2.8 * DAY, 10.0, FABLE)       # Fable used inside what becomes the next week too
        self.reading(END - 2.8 * DAY + MINUTE, 30)
        self.reading(END - 2.6 * DAY, 5)                  # a fall in the first week
        self.reading(END - 2.4 * DAY, 10, resets=later)
        self.reading(END - 2.0 * DAY, 0, resets=later)    # a fall in the next week
        self.response(END - 1.0 * DAY, 10.0, FABLE)       # inside both weeks' spans
        self.reading(END - 1.0 * DAY + MINUTE, 10, resets=later)
        weeks = plan_use(self.ledger, START, later).weeks(ACCOUNT_A)
        # Fable was used in each week before its fall, and account A's allowance was never read: neither fall can be
        # told from the model's reset.
        self.assertEqual([[r.kind for r in w.resets] for w in weeks], [["unknown"], ["unknown"]])

    def test_a_fall_in_a_week_without_the_model_s_use_is_extra(self):
        self.allowance(self.t, 0, account=ACCOUNT_B)
        self.use(10, 20, 30)
        self.idle(0)
        _use, weeks = self.week()
        self.assertEqual([r.kind for r in weeks[0].resets], ["extra"])


class SurfacesTest(LedgerCase):
    def test_the_summary_shows_the_use_outside_the_plans_and_the_multiple_without_resets_after_the_one_with_them(self):
        s = history.Summary(api=1000.0, days=10.0, plans=Fraction(200), shares=(), family=None, exhausted=None,
                            outside=100.0, beyond=180.0)
        self.assertEqual([(t.caption, t.figure) for t in history.summary_tiles(s)][:6],
                         [("API-equivalent cost", "$1,000"), ("API-equivalent per day", "$100.00"),
                          ("Outside the plans", "$100.00"), ("Plans at list price", "$200.00"),
                          ("API-equivalent ÷ plans", "4.5×"), ("Without resets ÷ plans", "3.6×")])

    def test_the_multiple_without_resets_stands_only_where_it_reads_differently(self):
        base = dict(api=1000.0, days=10.0, plans=Fraction(200), shares=(), family=None, exhausted=None, outside=0.0)
        captions = [t.caption for t in history.summary_tiles(history.Summary(beyond=0.1, **base))]
        self.assertIn("API-equivalent ÷ plans", captions)
        self.assertNotIn("Without resets ÷ plans", captions, "5.0× either way")
        self.assertNotIn("Outside the plans", captions, "none was paid outside the plans")

    def test_the_reset_table_s_columns_are_those_of_the_resets_it_counts(self):
        class Uses:
            def weeks(self, uuid):
                return (Week(START, END, 80.0, (Reset(START + HOUR, START + 2 * HOUR, 40.0, 10.0, "unknown"),
                                                Reset(START + 3 * DAY, START + 3 * DAY + HOUR, 60.0, 0.0, "extra")),
                             0.0),) if uuid == ACCOUNT_A else ()

        table = history.reset_table([ALPHA], Uses(), START + DAY, END)   # the first reset lies before the range
        self.assertEqual(table.columns, ("Account", "Week from", "Extra", "Points given back", "Beyond one window"))
        self.assertEqual(table.rows, (("alpha", history.moment_text(START), "1", "60 points", "—"),))

    def test_the_month_s_line_says_the_use_outside_the_plans_and_both_multiples(self):
        self.assertEqual(month_totals_text(1284.0, 300.0, in_plans=1200.0, one_window=1080.0),
                         "This month: $1,284 API-equivalent, $84 outside the plans · $300 plans at list price · 4.0× "
                         "· 3.6× without resets")
        self.assertEqual(month_totals_text(1284.0, 300.0), "This month: $1,284 API-equivalent · "
                                                           "$300 plans at list price · 4.3×")

    def test_status_json_writes_each_split_only_where_it_is_less(self):
        def month(**given):
            return status_document([], Recommendation(None, "", None), now=END, desktop_account=None,
                                   cli_account=None, cli_condition=None, api_this_month=100.0, **given)["thisMonth"]

        self.assertEqual(month(in_plans_this_month=80.0, one_window_this_month=70.0),
                         {"apiEquivalent": 100.0, "plansAtListPrice": None, "inPlans": 80.0, "withinOneWindow": 70.0})
        self.assertEqual(month(in_plans_this_month=100.0, one_window_this_month=90.0),
                         {"apiEquivalent": 100.0, "plansAtListPrice": None, "withinOneWindow": 90.0})
        self.assertEqual(month(in_plans_this_month=100.0, one_window_this_month=100.0),
                         {"apiEquivalent": 100.0, "plansAtListPrice": None})

    def test_the_chart_marks_each_kind_of_reset_with_its_own_shape_and_names_each_in_its_legend(self):
        line = history.UsageLine(ALPHA, ((START + HOUR, 10.0), (START + 2 * HOUR, 60.0), (START + 3 * HOUR, 5.0)))
        resets = (history.Reset(ALPHA, START + HOUR, START + 2 * HOUR, 5.0, "extra", None, 30.0),
                  history.Reset(ALPHA, START + 2 * HOUR, START + 3 * HOUR, 5.0, "model", "Fable", 55.0),
                  history.Reset(ALPHA, START + 3 * HOUR, START + 4 * HOUR, 5.0, "unknown", None, 9.0))
        usage = history.WeeklyUsage(START, END, (line,), resets)
        page = _weekly_chart(usage)
        self.assertEqual((page.count('<circle class="marker"'), page.count('<path class="marker"'),
                          page.count('<rect class="marker"')), (1, 1, 1))
        self.assertIn(escape("alpha: Fable's allowance reset between "), page)
        self.assertIn("55 points given back", page)
        self.assertEqual(re.findall(r'<b class="(\w+)"></b>([^<]*)<', page),
                         [("ring", escape(history.EXTRA_RESET_NOTE)), ("diamond", escape("Fable's allowance reset")),
                          ("square", "reset of a kind not known")])
        self.assertEqual(history.reset_legend(usage)[1:], (("Fable's allowance reset", "diamond"),
                                                           ("reset of a kind not known", "square")))

    def test_the_history_tables_the_weeks_with_a_reset_and_the_window_draws_the_same(self):
        self.use(10, 20, 30, 40, 50, 60)
        self.idle(0)
        self.use(15, 30, 45, dollars=15.0)
        accounts = {ACCOUNT_A: _account()}
        h = history.history(self.ledger, accounts, history.SPAN_OF["30d"], END - HOUR, billing=None, errors=[])
        self.assertEqual(h.resets.columns, ("Account", "Week from", "Extra", "Points given back", "Beyond one window"))
        self.assertEqual(h.resets.rows, ((h.accounts[0].label, history.moment_text(START), "1", "60 points", "$5.00"),))
        blocks = history_model.blocks(h)
        heading = blocks.index(history_model.Heading(history.RESETS_HEADING, history.RESETS_NOTE))
        self.assertEqual(blocks[heading + 1].rows, h.resets.rows)
        chart = next(b for b in blocks if isinstance(b, Chart) and isinstance(b.plot, history_model.LinePlot))
        self.assertEqual([(m.shape, m.token) for m in chart.plot.markers], [("disc", h.accounts[0].token)])
        legend = next(b for b in blocks if isinstance(b, Legend) and b.marks)
        self.assertEqual(legend.marks, ((history.EXTRA_RESET_NOTE, "disc"),))
        self.assertAlmostEqual(h.summary.beyond, 5.0)

    def test_a_plan_period_says_its_use_outside_the_plans_and_its_multiple_without_resets(self):
        self.use(*range(10, 61, 10))
        self.idle(0)
        self.use(*range(10, 61, 10))                      # 120 points: the last $20 beyond one window
        self.response(self.t + 5 * MINUTE, 10.0)
        self.reading(self.t + 6 * MINUTE, 100)            # then a reading at the limit, and $30 at extra usage after it
        for minutes in (7, 8, 9):
            self.response(self.t + minutes * MINUTE, 10.0)
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.machine.bills_file([bill(EMAIL_A, "2026-10-25", 200.0, plan="ultra", period="2026-10-25..2026-11-25")])
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        self.ledger.upsert_accounts(registry)
        accounts = self.ledger.known_accounts()
        now = END - HOUR
        billing = billing_report(load_bills(self.machine.paths), accounts, registry, self.ledger, now)
        uses = plan_use(self.ledger, history.uses_start(billing, START), now)
        (row,) = history.subscriptions(billing, history.entities(self.ledger, accounts), now, uses).periods
        cost = float(billing.subscriptions[0].periods[0].cost)
        # $160 in all, $30 of it at extra usage: $130 the plans covered; beyond one window the two responses past 100
        # points and the one after them, $30, so $100 within it.
        self.assertTrue(row.api.startswith("$160 (from "), row.api)   # the ledger's record begins inside the period
        self.assertTrue(row.api.endswith(f", $30 of it outside the plans · {130 / cost:,.0f}× its list price, "
                                         f"{100 / cost:,.0f}× without resets"), row.api)


def _account() -> Account:
    return Account(ACCOUNT_A, EMAIL_A, ORG_A)


if __name__ == "__main__":
    unittest.main()
