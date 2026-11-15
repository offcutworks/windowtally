"""billing: plan periods and changes of plan, gaps, the plans' cost per month at their US list price, days with a plan,
how far each account is paid up, the profile check and each period's API-equivalent use.

The history below is synthetic and chosen so that every expected figure can be worked out by hand. A bill's amount is
its own record, which no figure reads; the cost is the plan's list price (Pro $20, Max 5x $100, Ultra $200 a month)
spread over the period's printed days, and a period of neither a calendar month nor a year is priced by the day at
the monthly price, twelve months to 365 days ($1200/365 a day for Max 5x, $2400/365 for Ultra).

    alpha  Jan 01 Pro      €31  Jan 01..Feb 01  $20/31 a day    first order
           Jan 11 top-up    €6                                  no figure
           Feb 01 usage     €0  Jan 05..Jan 31                  no figure
           Feb 01 Pro      €28  Feb 01..Mar 01  $20/28          renewal, cut on Feb 15
           Feb 15 Max 5x   €70  Feb 15..Mar 15  $100/28         change of plan
           Mar 20 Max 5x   €90  Mar 20..Apr 19  $1200/365       new order after 5 days; 30 days, by the day
           Apr 19 Pro      €30  Apr 19..May 19  $20/30          renewal at a lower plan
    beta   Mar 16 Ultra   €300  Mar 16..Apr 15  $2400/365       first order, covering 4 of alpha's 5 gap days; by the day
           Apr 15 Pro      €30  Apr 15..May 15  $20/30          renewal, replaced the same day
           Apr 15 Max 5x   €60  Apr 15..May 15  $100/30         change of plan
"""

import unittest
from datetime import date
from decimal import Decimal
from fractions import Fraction

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bill,
                      bridge_line, epoch)
from windowtally.accounts import load_registry
from windowtally.attribution import attribute
from windowtally.billing import billing_report, cents, describe_start
from windowtally.bills import PLANS, load_bills
from windowtally.ingest_transcripts import ingest_transcripts
from windowtally.ledger import Ledger
from windowtally.pricing import response_cost

HISTORY = [
    bill(EMAIL_A, "2026-01-01", 31, plan="pro", period="2026-01-01..2026-02-01"),
    bill(EMAIL_A, "2026-01-11", 6, kind="topup", plan=None),
    bill(EMAIL_A, "2026-02-01", 0, kind="usage", plan=None, period="2026-01-05..2026-01-31"),
    bill(EMAIL_A, "2026-02-01", 28, plan="pro", period="2026-02-01..2026-03-01"),
    bill(EMAIL_A, "2026-02-15", 70, plan="max5x", period="2026-02-15..2026-03-15"),
    bill(EMAIL_A, "2026-03-20", 90, plan="max5x", period="2026-03-20..2026-04-19"),
    bill(EMAIL_A, "2026-04-19", 30, plan="pro", period="2026-04-19..2026-05-19"),
    bill(EMAIL_B, "2026-03-16", 300, plan="ultra", period="2026-03-16..2026-04-15"),
    bill(EMAIL_B, "2026-04-15", 30, plan="pro", period="2026-04-15..2026-05-15"),
    bill(EMAIL_B, "2026-04-15", 60, plan="max5x", period="2026-04-15..2026-05-15"),
]
NOW = epoch("2026-05-10T12:00:00Z")
WITHOUT_TOP_UPS = [b for b in HISTORY if b["kind"] == "subscription"]


def dollars(text: str) -> Decimal:
    return Decimal(text)


class BillingTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A, organization_type="claude_pro", tier=None)
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B, tier="default_claude_max_5x")
        self.machine.bills_file(HISTORY)
        self.ledger = Ledger.open(self.machine.paths.ledger_db)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def report(self, now: float = NOW, settings: dict | None = None):
        if settings is not None:
            self.machine.settings(settings)
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        return billing_report(load_bills(self.machine.paths), registry, registry, self.ledger, now)

    def subscription(self, report, email):
        return next(s for s in report.subscriptions if s.email == email)

    def costs(self, report=None) -> dict[str, dict[str, Fraction]]:
        return {row.month: dict(row.cost) for row in (report or self.report()).table.months}

    def test_a_bill_s_amount_and_currency_count_in_no_figure(self):
        before = self.costs()
        self.machine.bills_file([dict(b, amount=b["amount"] * 3 + 1, currency="CHF") for b in HISTORY])
        self.assertEqual(self.costs(), before)

    def test_the_cost_spreads_each_period_s_list_price_over_its_days_in_effect(self):
        costs = {month: {e: cents(v) for e, v in row.items()} for month, row in self.costs().items()}
        # alpha: Jan 31×$20/31; Feb 14×$20/28 + 14×$100/28; Mar 14×$100/28 + 12×$1200/365; Apr 18×$1200/365 + 12×$20/30;
        # May 18×$20/30. beta: Mar 16×$2400/365; Apr 14×$2400/365 + 16×$100/30 (the Pro it replaced holds no day);
        # May 14×$100/30.
        self.assertEqual(costs["2026-01"], {EMAIL_A: dollars("20.00")})
        self.assertEqual(costs["2026-02"], {EMAIL_A: dollars("60.00")})
        self.assertEqual(costs["2026-03"], {EMAIL_A: dollars("89.45"), EMAIL_B: dollars("105.21")})
        self.assertEqual(costs["2026-04"], {EMAIL_A: dollars("67.18"), EMAIL_B: dollars("145.39")})
        self.assertEqual(costs["2026-05"], {EMAIL_A: dollars("12.00"), EMAIL_B: dollars("46.67")})

    def test_top_ups_and_usage_settlements_count_in_no_figure(self):
        before = self.costs()
        self.machine.bills_file(WITHOUT_TOP_UPS)
        self.assertEqual(self.costs(), before)

    def test_days_with_a_plan_count_each_day_once(self):
        table = self.report().table
        days = {row.month: (row.service_days, row.any_service_days) for row in table.months}
        self.assertEqual(days["2026-01"], ({EMAIL_A: 31, EMAIL_B: 0}, 31))
        self.assertEqual(days["2026-03"], ({EMAIL_A: 26, EMAIL_B: 16}, 30))  # no plan on Mar 15
        self.assertEqual(days["2026-04"], ({EMAIL_A: 30, EMAIL_B: 30}, 30))
        self.assertEqual(days["2026-05"], ({EMAIL_A: 18, EMAIL_B: 14}, 18))

    def test_each_month_rounds_on_its_own_and_a_total_comes_from_the_exact_values(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-01-01", 20, plan="pro", period="2026-01-01..2026-02-04")])
        months = {month: row[EMAIL_A] for month, row in self.costs(self.report(now=epoch("2026-02-10T00:00:00Z"))).items()}
        # A 34-day Pro period, by the day at $240/365: January's 31 days are $20.383…, February's 3 days $1.972…; the
        # months show $20.38 and $1.97, while the total is $22.356…, shown $22.36.
        self.assertEqual((cents(months["2026-01"]), cents(months["2026-02"])), (dollars("20.38"), dollars("1.97")))
        self.assertEqual(cents(sum(months.values())), dollars("22.36"))

    def test_periods_say_how_they_began_and_how_long_their_plan_held(self):
        report = self.report()
        alpha = [(p.bill.plan, p.how, describe_start(p), p.until) for p in self.subscription(report, EMAIL_A).periods]
        self.assertEqual(alpha, [
            ("pro", "new", "first order", date(2026, 2, 1)),
            ("pro", "new", "renewal", date(2026, 2, 15)),
            ("max5x", "change", "change of plan from Pro", date(2026, 3, 15)),
            ("max5x", "new", "new order after 5 days without a plan", date(2026, 4, 19)),
            ("pro", "new", "renewal, lower than the Max 5x before", date(2026, 5, 19))])
        beta = [(p.bill.plan, p.how, p.bill.start, p.until) for p in self.subscription(report, EMAIL_B).periods]
        self.assertEqual(beta[1:], [("pro", "new", date(2026, 4, 15), date(2026, 4, 15)),
                                    ("max5x", "change", date(2026, 4, 15), date(2026, 5, 15))])
        # The two 30-day periods are neither a calendar month nor a year: priced by the day and named, as the status
        # file's source problems are, after their source.
        self.assertEqual(report.problems, (
            "bills: bills.json bill 6 is a Max 5x period of 30 days, not a month: it is counted at the monthly list "
            "price by the day",
            "bills: bills.json bill 8 is an Ultra period of 30 days, not a month: it is counted at the monthly list "
            "price by the day"))

    def test_a_gap_records_how_much_another_account_covered(self):
        report = self.report()
        (gap,) = self.subscription(report, EMAIL_A).gaps
        self.assertEqual((gap.start, gap.until, gap.days, gap.covered_days, gap.covered_by),
                         (date(2026, 3, 15), date(2026, 3, 20), 5, 4, ("beta",)))
        self.assertEqual(self.subscription(report, EMAIL_B).gaps, ())
        coverage = report.coverage
        self.assertEqual((coverage.start, coverage.until, coverage.days, coverage.covered),
                         (date(2026, 1, 1), date(2026, 5, 19), 138, 137))

    def test_today_each_account_is_paid_up_to_its_period_end(self):
        report = self.report(settings={"v": 1, "renewalReminderDays": 5})
        alpha, beta = self.subscription(report, EMAIL_A), self.subscription(report, EMAIL_B)
        self.assertEqual((alpha.state, alpha.plan, alpha.paid_until, alpha.days_left, alpha.renew_soon),
                         ("active", "pro", date(2026, 5, 19), 9, False))
        self.assertEqual((beta.state, beta.plan, beta.paid_until, beta.days_left, beta.renew_soon),
                         ("active", "max5x", date(2026, 5, 15), 5, True))
        # This month at list price, the whole of May: alpha 18×$20/30, beta 14×$100/30.
        self.assertEqual((cents(alpha.this_month), cents(beta.this_month)), (dollars("12.00"), dollars("46.67")))
        self.assertEqual(report.reminder_days, 5)

    def test_without_the_reminder_nothing_is_due_to_renew(self):
        report = self.report()
        self.assertFalse(any(s.renew_soon for s in report.subscriptions))
        self.assertIsNone(report.reminder_days)

    def test_after_the_last_period_the_account_has_no_recorded_plan(self):
        report = self.report(now=epoch("2026-05-20T00:00:00Z"))
        alpha = self.subscription(report, EMAIL_A)
        self.assertEqual((alpha.state, alpha.plan, alpha.paid_until, alpha.days_left), ("ended", None, date(2026, 5, 19), None))
        before = self.report(now=epoch("2025-12-20T00:00:00Z"))
        self.assertEqual((self.subscription(before, EMAIL_A).state, self.subscription(before, EMAIL_A).paid_until),
                         ("upcoming", date(2026, 1, 1)))

    def test_the_profile_is_set_against_the_plan_in_effect(self):
        third = "cccccccc-0000-4000-8000-000000000003"
        self.machine.add_account(third, "gamma@example.com", "0c0c0c0c-0000-4000-8000-00000000000c")
        report = self.report()
        checks = {s.label: (s.profile_plan, s.profile_check) for s in report.subscriptions}
        self.assertEqual(checks, {"alpha": ("pro", "matches"), "beta": ("max5x", "matches"),
                                  "gamma": ("ultra", "no-bill-today")})
        self.assertEqual(self.subscription(report, "gamma@example.com").state, "none")

    def test_a_profile_fetched_before_the_period_began_is_older_not_different(self):
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B, fetched=epoch("2026-04-10T00:00:00Z"))
        self.assertEqual(self.subscription(self.report(), EMAIL_B).profile_check, "profile-older")
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B, fetched=epoch("2026-05-01T00:00:00Z"))
        self.assertEqual(self.subscription(self.report(), EMAIL_B).profile_check, "differs")
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B, organization_type="claude_team", tier=None)
        self.assertEqual(self.subscription(self.report(), EMAIL_B).profile_check, "unknown-plan")

    def test_each_period_is_set_against_the_api_equivalent_use_while_it_held(self):
        self.machine.transcript("s1", [bridge_line("s1", ACCOUNT_A, ORG_A)]
                                + assistant_lines("m1", epoch("2026-03-25T10:00:00Z"), "s1")
                                + assistant_lines("m2", epoch("2026-05-02T10:00:00Z"), "s1"))
        ingest_transcripts(self.ledger, self.machine.paths.projects_dir)
        attribute(self.ledger)
        one = response_cost("claude-opus-5-5", input_tokens=2, output_tokens=120, cache_read_tokens=1000,
                            cache_write_5m_tokens=0, cache_write_1h_tokens=500)
        uses = {(u.period.bill.date.isoformat(), u.period.bill.plan): u
                for u in self.subscription(self.report(), EMAIL_A).uses}
        self.assertIsNone(uses[("2026-01-01", "pro")].api_usd)       # before the ledger's record of the account
        march = uses[("2026-03-20", "max5x")]
        self.assertAlmostEqual(march.api_usd, one)
        self.assertEqual(march.known_from, epoch("2026-03-25T10:00:00Z"))  # the record begins inside the period
        april = uses[("2026-04-19", "pro")]
        self.assertAlmostEqual(april.api_usd, one)
        self.assertIsNone(april.known_from)

    def test_a_period_inside_another_without_a_higher_plan_is_named(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-01-01", 90, plan="max5x", period="2026-01-01..2026-02-01"),
                                 bill(EMAIL_A, "2026-01-20", 18, plan="pro", period="2026-01-20..2026-02-20")])
        report = self.report(now=epoch("2026-01-25T00:00:00Z"))
        (problem,) = report.problems
        self.assertIn("bills.json bill 2 starts inside the period of bills.json bill 1 without raising the plan", problem)
        self.assertEqual(self.subscription(report, EMAIL_A).plan, "pro")

    def test_every_plan_is_named_after_the_article_it_takes(self):
        articles = {"pro": "a Pro", "max5x": "a Max 5x", "ultra": "an Ultra"}
        self.assertEqual(set(articles), set(PLANS))  # a new plan names its article here
        for plan, named in articles.items():
            with self.subTest(plan=plan):
                # A 30-day period, inside which a Pro period starts without raising the plan.
                self.machine.bills_file([bill(EMAIL_A, "2026-01-01", 1, plan=plan, period="2026-01-01..2026-01-31"),
                                         bill(EMAIL_A, "2026-01-20", 1, plan="pro", period="2026-01-20..2026-02-20")])
                report = self.report(now=epoch("2026-01-25T00:00:00Z"))
                self.assertIn(f"bills: bills.json bill 1 is {named} period of 30 days, not ", report.problems[0])
                inside = self.subscription(report, EMAIL_A).periods[1]
                self.assertEqual(describe_start(inside), f"starts inside {named} period without raising the plan")

    def test_bills_in_two_currencies_make_one_table_in_us_dollars(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-01-01", 200, plan="ultra", currency="USD",
                                      period="2026-01-01..2026-01-31"),
                                 bill(EMAIL_B, "2026-01-01", 180, plan="ultra", period="2026-01-01..2026-01-31")])
        report = self.report(now=epoch("2026-01-15T00:00:00Z"))
        self.assertEqual(report.table.emails, (EMAIL_A, EMAIL_B))
        # Each a 30-day Ultra period, by the day at $2400/365, whatever it was paid in.
        self.assertEqual({e: cents(v) for e, v in report.table.months[0].cost.items()},
                         {EMAIL_A: dollars("197.26"), EMAIL_B: dollars("197.26")})

    def test_every_account_sharing_an_e_mail_gets_its_subscription(self):
        from windowtally.accounts import Account
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        old = "00000000-0000-4000-8000-0000000000aa"  # an account the ledger remembers, its folder gone
        accounts = dict(registry, **{old: Account(uuid=old, email=EMAIL_A)})
        report = billing_report(load_bills(self.machine.paths), accounts, registry, self.ledger, NOW)
        alpha = report.for_account(ACCOUNT_A)
        self.assertIs(report.for_account(old), alpha)
        self.assertEqual((alpha.uuid, sorted(alpha.uuids)), (ACCOUNT_A, sorted([ACCOUNT_A, old])))
        self.assertEqual(alpha.profile_check, "matches")  # the profile on this machine stands for the e-mail

    def test_money_is_written_after_its_currency_s_code_rounded_half_up(self):
        from windowtally.billing import money_text
        self.assertEqual(money_text(Fraction(1, 40), "EUR"), "EUR 0.03")
        self.assertEqual(money_text(Decimal("1408.63"), "EUR"), "EUR 1,408.63")
        self.assertEqual(money_text(200, "USD"), "USD 200.00")
        self.assertEqual(money_text(18, "CHF"), "CHF 18.00")

    def test_the_bills_of_an_e_mail_no_account_has_are_counted_under_it(self):
        self.machine.bills_file([bill("delta@example.com", "2026-01-01", 18, plan="pro",
                                      period="2026-01-01..2026-02-01")])
        report = self.report(now=epoch("2026-01-15T00:00:00Z"))
        delta = self.subscription(report, "delta@example.com")
        self.assertEqual((delta.label, delta.uuid, delta.state, delta.profile_check), ("delta", None, "active", "no-profile"))


if __name__ == "__main__":
    unittest.main()
