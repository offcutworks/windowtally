"""A subscription's cost at its plan's US list price, in US dollars, wherever WindowTally shows one; status.json version 3,
with this month's totals across the accounts; and bills written alike whatever their currency.

The expectations are worked from the maintainer's decisions (PROJECT.md, *Decisions*, 2026-10-23): Pro $20 a month
or $200 a year, Max 5x $100 and Ultra $200 a month; a period's price spread over its printed days and counted on its
days in effect; the worked example of an upgrade from Max 5x to Ultra on the tenth day of a 30-day period, which
counts $100 × 10/30 + $200 = $233.33; a top-up or a settlement of extra usage counting in no figure; and the month's
totals counted on the bills' UTC month, every response and every bill once.
"""

import json
import unittest
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bill,
                      bridge_line, epoch, status_account, status_document, status_window)
from windowtally.__main__ import format_bills
from windowtally.accounts import load_registry
from windowtally.billing import billing_report, cents, list_price, money_text
from windowtally.bills import PLANS, load_bills, make_bill
from windowtally.history import subscriptions
from windowtally.ledger import Ledger
from windowtally.pricing import PLAN_PRICES, response_cost
from windowtally.service import run_pass
from windowtally_gui import bills_model, live_model, status_model

ACCOUNT_C = "cccccccc-0000-4000-8000-000000000003"     # a second account signed in with alpha's e-mail
ORG_C = "0c0c0c0c-0000-4000-8000-00000000000c"
STRANGER = "dddddddd-0000-4000-8000-000000000004"      # an account with no profile on the machine
EMAIL_GAMMA = "gamma@example.com"                      # an e-mail no account here has
NOW = epoch("2026-04-20T12:00:00Z")

# The worked example: Max 5x from 1 April (30 days to 1 May), raised to Ultra on the tenth day's end, 11 April,
# whose period runs to 11 May. Each bill is charged in a currency of its own, which no figure reads.
UPGRADE = [
    bill(EMAIL_A, "2026-04-01", 90, plan="max5x", period="2026-04-01..2026-05-01", currency="EUR", reference="A-1"),
    bill(EMAIL_A, "2026-04-11", 133.33, plan="ultra", period="2026-04-11..2026-05-11", currency="USD",
         reference="A-2"),
]


def made(plan: str, period: str):
    start, end = (date.fromisoformat(d) for d in period.split(".."))
    return make_bill(account=EMAIL_A, day=start, kind="subscription", plan=plan, amount=Decimal("1"), currency="EUR",
                     start=start, end=end, reference=None, origin="bill 1", position=1)


class ListPriceTest(unittest.TestCase):
    def test_every_plan_a_bill_may_name_has_its_list_price(self):
        self.assertEqual(set(PLAN_PRICES), set(PLANS))

    def test_a_period_is_priced_by_its_plan_and_its_printed_length(self):
        self.assertEqual(list_price(made("pro", "2026-01-31..2026-02-28")), (Fraction(20), None))
        self.assertEqual(list_price(made("pro", "2026-03-01..2027-03-01")), (Fraction(200), None))
        self.assertEqual(list_price(made("max5x", "2026-02-01..2026-03-01")), (Fraction(100), None))
        self.assertEqual(list_price(made("ultra", "2026-04-11..2026-05-11")), (Fraction(200), None))

    def test_a_month_renewing_on_the_31st_is_a_month_after_a_short_one_too(self):
        for period in ("2026-01-31..2026-02-28", "2026-02-28..2026-03-31", "2026-03-31..2026-04-30",
                       "2026-04-30..2026-05-31"):
            self.assertEqual(list_price(made("ultra", period)), (Fraction(200), None), period)

    def test_a_period_neither_a_month_nor_a_year_sold_is_priced_by_the_day_and_named(self):
        price, problem = list_price(made("max5x", "2026-04-01..2026-05-16"))
        self.assertEqual(price, Fraction(100) * 12 * 45 / 365)
        self.assertIn("45 days", problem)
        self.assertIn("bill 1", problem)
        price, problem = list_price(made("ultra", "2026-01-01..2027-01-01"))   # Ultra is sold by the month only
        self.assertEqual(price, Fraction(200) * 12)
        self.assertIsNotNone(problem)


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        self.ledger = Ledger.open(self.machine.paths.ledger_db)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def report(self, bills: list[dict]):
        self.machine.bills_file(bills)
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        return billing_report(load_bills(self.machine.paths), registry, registry, self.ledger, NOW)

    def test_the_worked_example_counts_233_33(self):
        report = self.report(UPGRADE)
        alpha = next(s for s in report.subscriptions if s.email == EMAIL_A)
        self.assertEqual([p.cost for p in alpha.periods], [Fraction(100) * 10 / 30, Fraction(200)])
        months = {row.month: row.cost[EMAIL_A] for row in report.table.months}
        self.assertEqual(sum(months.values(), Fraction(0)), Fraction(700, 3))
        self.assertEqual(cents(sum(months.values(), Fraction(0))), Decimal("233.33"))
        # April: ten days of Max 5x and twenty of the Ultra period's thirty; May: its last ten.
        self.assertEqual(months, {"2026-04": Fraction(100, 3) + Fraction(200) * 20 / 30,
                                  "2026-05": Fraction(200) * 10 / 30})
        self.assertEqual(alpha.this_month, months["2026-04"])
        self.assertEqual(report.problems, ())

    def test_top_ups_and_usage_settlements_count_in_no_figure(self):
        plain = self.report(UPGRADE)
        extra = self.report(UPGRADE + [
            bill(EMAIL_A, "2026-04-15", 25, kind="topup", plan=None, currency="USD"),
            bill(EMAIL_A, "2026-05-01", 40, kind="usage", plan=None, period="2026-04-01..2026-05-01")])
        self.assertEqual([r.cost for r in extra.table.months], [r.cost for r in plain.table.months])
        self.assertEqual(extra.this_month, plain.this_month)

    def test_a_bill_s_amount_and_currency_change_no_figure(self):
        report = self.report([
            bill(EMAIL_A, "2026-04-01", 1, plan="ultra", period="2026-04-01..2026-05-01", currency="JPY"),
            bill(EMAIL_B, "2026-04-01", 999, plan="ultra", period="2026-04-01..2026-05-01", currency="USD")])
        self.assertEqual([s.this_month for s in report.subscriptions], [Fraction(200), Fraction(200)])
        self.assertEqual(report.this_month, Fraction(400))

    def test_the_history_shows_list_prices_and_no_amount_charged(self):
        figures = subscriptions(self.report(UPGRADE), [], NOW)
        self.assertEqual(figures.summary[0].last_bill, "2026-04-11 · Ultra")
        self.assertEqual([p.list_price for p in figures.periods], ["$200.00", "$33.33"])
        self.assertEqual(figures.costs.all_cost, Fraction(700, 3))


class StatusVersion3Test(unittest.TestCase):
    """Alpha's e-mail is shared by two accounts; gamma's has none here; beta has no bill. Two responses fall in the
    UTC month, one of them an account's with no profile, and one in the month before."""

    def setUp(self):
        self.machine = m = Machine()
        m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        m.add_account(ACCOUNT_C, EMAIL_A, ORG_C)
        m.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        m.transcript("in-month", [bridge_line("in-month", ACCOUNT_A, ORG_A)]
                     + assistant_lines("r1", NOW - 3600, "in-month"))
        m.transcript("stranger", [bridge_line("stranger", STRANGER, ORG_C)]
                     + assistant_lines("r2", NOW - 7200, "stranger"))
        m.transcript("before", [bridge_line("before", ACCOUNT_A, ORG_A)]
                     + assistant_lines("r0", epoch("2026-03-31T23:00:00Z"), "before"))

    def tearDown(self):
        self.machine.close()

    def document(self) -> dict:
        run_pass(self.machine.paths, NOW, dashboard=False)
        return json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))

    def test_the_month_s_totals_count_every_response_and_every_bill_once(self):
        self.machine.bills_file(UPGRADE + [
            bill(EMAIL_GAMMA, "2026-04-05", 100, plan="max5x", period="2026-04-05..2026-05-05", currency="USD")])
        doc = self.document()
        self.assertEqual(doc["v"], 3)
        one = response_cost("claude-opus-5-5", input_tokens=2, output_tokens=120, cache_read_tokens=1000,
                            cache_write_5m_tokens=0, cache_write_1h_tokens=500)
        alpha_april = Fraction(100, 3) + Fraction(200) * 20 / 30
        gamma_april = Fraction(100) * 26 / 30
        self.assertEqual(doc["thisMonth"], {"apiEquivalent": float(cents(2 * one)),
                                            "plansAtListPrice": float(cents(alpha_april + gamma_april))})
        by_uuid = {a["uuid"]: a["subscription"]["thisMonthListPrice"] for a in doc["accounts"]}
        self.assertEqual(by_uuid, {ACCOUNT_A: float(cents(alpha_april)), ACCOUNT_C: float(cents(alpha_april)),
                                   ACCOUNT_B: 0.0})

    def test_without_a_bill_source_the_plans_cost_is_unknown(self):
        doc = self.document()
        self.assertIsNone(doc["thisMonth"]["plansAtListPrice"])
        self.assertIsInstance(doc["thisMonth"]["apiEquivalent"], float)
        self.assertTrue(all(a["subscription"] is None for a in doc["accounts"]))


def v3_document(api: float | None, plans: float | None, list_price: float = 161.94) -> dict:
    at = NOW
    subscription = {"state": "active", "plan": "ultra", "planName": "Ultra", "paidUntil": "2026-05-07",
                    "daysLeft": 16, "renewSoon": False, "thisMonthListPrice": list_price, "profilePlan": "ultra",
                    "profileCheck": "matches"}
    accounts = [status_account(ACCOUNT_A, EMAIL_A, at=at, plan=subscription),
                status_account(ACCOUNT_B, EMAIL_B, at=at, desktop=False, cli=False,
                               weekly=status_window("current", 40.0, at + 86400, as_of=at - 60, anchor_exact=True))]
    return status_document(accounts, at=at, v=3, thisMonth={"apiEquivalent": api, "plansAtListPrice": plans})


class WindowTest(unittest.TestCase):
    def snapshot(self, doc: dict):
        return status_model.snapshot_of(Path("status.json"), json.dumps(doc))

    def test_the_main_window_gives_the_month_s_totals_under_the_accounts_in_use(self):
        view = live_model.live_view(self.snapshot(v3_document(1283.56, 300.0)), NOW)
        self.assertEqual(view.header.totals_line,
                         "This month: $1,284 API-equivalent · $300 plans at list price · 4.3×")
        view = live_model.live_view(self.snapshot(v3_document(1283.56, None)), NOW)
        self.assertEqual(view.header.totals_line, "This month: $1,284 API-equivalent")

    def test_a_card_leaves_this_month_s_cost_to_the_header(self):
        cards = live_model.live_view(self.snapshot(v3_document(10.0, 600.0, 193.55)), NOW).cards
        self.assertEqual(cards[0].plan.note, "")
        self.assertNotIn("$", cards[0].plan.text)

    def test_the_window_reads_version_3_only(self):
        old = v3_document(1.0, 1.0)
        old["v"] = 2
        self.assertEqual(self.snapshot(old).kind, "unknown-version")
        broken = v3_document(1.0, 1.0)
        del broken["thisMonth"]
        self.assertEqual(self.snapshot(broken).kind, "unreadable")


class BillsWrittenAlikeTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)

    def tearDown(self):
        self.machine.close()

    def test_every_currency_is_written_by_its_code(self):
        self.assertEqual(money_text(Decimal("1408.625"), "EUR"), "EUR 1,408.63")
        self.assertEqual(money_text(Decimal("200"), "USD"), "USD 200.00")
        self.assertEqual(money_text(Decimal("18"), "CHF"), "CHF 18.00")

    def test_the_bill_form_suggests_only_the_currencies_already_recorded(self):
        self.assertEqual(bills_model.read_list(self.machine.paths).currencies, ())
        self.machine.bills_file(UPGRADE)
        self.assertEqual(bills_model.read_list(self.machine.paths).currencies, ("EUR", "USD"))

    def test_the_bills_command_lists_amounts_by_code_and_costs_at_list_price(self):
        self.machine.bills_file(UPGRADE)
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        text = format_bills(billing_report(load_bills(self.machine.paths), registry, registry, None, NOW),
                            listing=True)
        self.assertIn("this month $166.67 at list price", text)
        self.assertIn("EUR 90.00", text)
        self.assertIn("USD 133.33", text)


if __name__ == "__main__":
    unittest.main()
