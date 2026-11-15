"""Refunds: a cancellation's prorated refund, read from a bill archive's manifest (its credit note and the refund's own
document) and from WindowTally's own bills file (an entry of kind refund naming the bill it credits), matched to that
bill, ending its plan on the refund's date, and listed beside it, its sum in its own currency and in no figure.

The history is synthetic and every figure is worked out by hand. Alpha's Pro, 28 Sep to 28 Oct (30 days, $20/30 a day),
is refunded on 4 Oct: its plan was held 28, 29 and 30 Sep and 1, 2 and 3 Oct, six days, $20 × 6/30 = $4.00 in all,
of which three days, $2.00, fall in October.
"""

import contextlib
import io
import json
import unittest
from datetime import date
from decimal import Decimal
from fractions import Fraction

from fixtures import ACCOUNT_A, EMAIL_A, EMAIL_B, ORG_A, Machine, bill, epoch, manifest_rows
from windowtally.__main__ import format_bills, main
from windowtally.accounts import Account, load_registry
from windowtally.billing import billing_report, day_start
from windowtally.limits import AccountStanding, Recommendation, WeeklyAnchor, WindowStanding
from windowtally.bills import BillsError, add_bill, load_bills, make_bill, read_bills_file
from windowtally.bills_manifest import read_manifest_source
from windowtally.capacity import plan_spans
from windowtally.history import subscriptions as history_subscriptions
from windowtally.status_file import status_document
from windowtally_gui import actions_model
from windowtally_gui.bills_model import BillForm, read_list, takes_period, takes_plan

NOW = epoch("2026-10-10T12:00:00Z")
PRO = bill(EMAIL_A, "2026-09-28", 24, plan="pro", period="2026-09-28..2026-10-28", reference="A-1")
REFUND = bill(EMAIL_A, "2026-10-04", 19.20, kind="refund", reference="A-1")


def standing(uuid: str, email: str) -> AccountStanding:
    """An idle account's standing, its windows unknown: what the status writes of its bills is all that is read."""
    return AccountStanding(Account(uuid=uuid, email=email),
                           WindowStanding("five_hour", "not_started", None, None, None, False, None),
                           WindowStanding("seven_day", "unknown", None, None, None, False, None),
                           WeeklyAnchor(NOW + 86400, exact=False), None, False, False)


def refund_rows(account: str, entry_id: str, day: str, amount: str, line_item: str, period: str, *,
                invoice: str) -> list[dict]:
    """The two rows a bill archive files a refund as: its credit note and the refund's own document, each under the
    credited bill's invoice number, the sum returned unsigned."""
    base = {"vendor": "Anthropic Claude", "subject": "Personal", "account": account, "entry_id": entry_id, "date": day,
            "status": "paid", "currency": "EUR", "amount": amount, "eur_equiv": f"-{amount}", "eur_basis": "native",
            "invoice_no": invoice, "line_item": line_item, "service_period": period}
    return [dict(base, doc_type="CreditNote", receipt_no="", filename=f"{day}_{entry_id}_CreditNote.pdf"),
            dict(base, doc_type="Refund", receipt_no=f"F-{invoice}", filename=f"{day}_{entry_id}_Refund.pdf")]


class RefundReadingTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()

    def tearDown(self):
        self.machine.close()

    def test_a_manifest_refund_is_read_from_its_credit_note_and_matched_to_its_bill(self):
        rows = (manifest_rows(EMAIL_A, "A01", "2026-09-28", "24.00", "Claude Pro", "2026-09-28..2026-10-28",
                              invoice="A-1")
                + refund_rows(EMAIL_A, "A01", "2026-10-04", "19.20", "Claude Pro", "2026-09-28..2026-10-28",
                              invoice="A-1"))
        manifest = self.machine.manifest(rows)
        read = read_manifest_source(manifest)
        self.assertEqual(read.left_out, ())
        self.assertEqual([(b.kind, b.date, b.amount, b.reference, b.start) for b in read.bills],
                         [("subscription", date(2026, 9, 28), Decimal("24.00"), "A-1", date(2026, 9, 28)),
                          ("refund", date(2026, 10, 4), Decimal("19.20"), "A-1", None)])
        self.assertEqual(read.bills[1].origin, "_manifest.csv row 4", "the credit note's row, not the refund's")
        self.machine.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(manifest)}]})
        bill_set = load_bills(self.machine.paths)
        pro = next(b for b in bill_set.bills if b.kind == "subscription")
        self.assertEqual(bill_set.refund_of(pro).amount, Decimal("19.20"))
        self.assertEqual((bill_set.errors, bool(bill_set.unread)), ((), False))

    def test_the_bills_file_holds_a_refund_pointing_at_the_bill_it_credits(self):
        self.machine.bills_file([PRO, REFUND])
        pro, refund = read_bills_file(self.machine.paths.bills_file)
        self.assertEqual((refund.kind, refund.plan, refund.start, refund.reference), ("refund", None, None, "A-1"))
        bill_set = load_bills(self.machine.paths)
        self.assertIs(bill_set.refund_of(pro), next(b for b in bill_set.bills if b.kind == "refund"))
        self.assertEqual(bill_set.duplicates, (), "a refund shares its bill's reference without being a copy of it")

    def test_a_refund_names_its_bill_and_has_no_plan_or_period(self):
        with self.assertRaises(ValueError) as caught:
            make_bill(account=EMAIL_A, day=date(2026, 10, 4), kind="refund", plan=None, amount=Decimal("19.20"),
                      currency="EUR", start=date(2026, 9, 28), end=date(2026, 11, 30), reference=None,
                      origin="test", position=0)
        self.assertIn("a refund has no service period", str(caught.exception))
        self.assertIn("a refund names the bill it credits by that bill's reference", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            make_bill(account=EMAIL_A, day=date(2026, 10, 4), kind="refund", plan="pro", amount=Decimal("19.20"),
                      currency="EUR", start=None, end=None, reference="A-1", origin="test", position=0)
        self.assertIn("a refund has no plan", str(caught.exception))

    def test_one_refund_of_a_bill_is_recorded_and_a_second_refused(self):
        path = self.machine.bills_file([PRO])
        refund = make_bill(account=EMAIL_A, day=date(2026, 10, 4), kind="refund", plan=None, amount=Decimal("19.20"),
                           currency="EUR", start=None, end=None, reference="A-1", origin="test", position=0)
        add_bill(path, refund)
        with self.assertRaises(BillsError) as caught:
            add_bill(path, refund)
        self.assertIn("already holds a refund of the bill A-1", str(caught.exception))
        self.assertEqual([b.kind for b in read_bills_file(path)], ["subscription", "refund"])

    def test_a_refund_that_cannot_be_its_bills_is_left_out_with_the_bill(self):
        cases = {
            "another currency": (dict(REFUND, currency="USD"), "returns USD"),
            "more than charged": (dict(REFUND, amount=25), "returns more than"),
            "before the bill": (dict(REFUND, date="2026-09-27"), "is dated before"),
            "after its period": (dict(REFUND, date="2026-10-28"), "on or after the end"),
        }
        for case, (refund, words) in cases.items():
            with self.subTest(case):
                self.machine.bills_file([PRO, refund, bill(EMAIL_B, "2026-10-01", 200, period="2026-10-01..2026-11-01")])
                bill_set = load_bills(self.machine.paths)
                self.assertEqual([b.account for b in bill_set.bills], [EMAIL_B])
                self.assertTrue(any(words in e and "the bill is left out with its refund" in e
                                    for e in bill_set.errors), bill_set.errors)
                self.assertEqual(bill_set.unread.emails, {EMAIL_A})

    def test_a_refund_of_no_bill_counted_is_left_out_and_two_that_differ_are_copies_that_differ(self):
        self.machine.bills_file([dict(REFUND, reference="A-9"), PRO])
        bill_set = load_bills(self.machine.paths)
        self.assertEqual([b.kind for b in bill_set.bills], ["subscription"])
        self.assertIn("credits the bill A-9 of alpha@example.com, which is not among the bills counted; it is left out",
                      bill_set.errors[0])
        self.assertEqual(bill_set.unread.emails, {EMAIL_A})
        manifest = self.machine.manifest(
            manifest_rows(EMAIL_A, "A01", "2026-09-28", "24.00", "Claude Pro", "2026-09-28..2026-10-28", invoice="A-1")
            + refund_rows(EMAIL_A, "A01", "2026-10-05", "10.00", "Claude Pro", "2026-09-28..2026-10-28",
                          invoice="A-1"))
        self.machine.bills_file([PRO, REFUND])
        self.machine.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(manifest)}]})
        bill_set = load_bills(self.machine.paths)
        self.assertEqual([b.kind for b in bill_set.bills], ["subscription"], "the bill counts once, no refund kept")
        self.assertEqual([(d.reference, d.counted) for d in bill_set.duplicates], [("A-1", True), ("A-1", False)])
        self.assertEqual(bill_set.unread.emails, {EMAIL_A}, "a refund left out leaves its account not wholly read")


class RefundEndsThePlanTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A, organization_type="claude_pro", tier=None)

    def tearDown(self):
        self.machine.close()

    def report(self, bills: list[dict], now: float = NOW, remind: int | None = None):
        self.machine.bills_file(bills)
        if remind is not None:
            self.machine.settings({"v": 1, "renewalReminderDays": remind})
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        return billing_report(load_bills(self.machine.paths), registry, registry, None, now)

    def test_the_plan_ends_on_the_refunds_date_and_counts_only_the_days_held(self):
        report = self.report([PRO, REFUND], remind=30)
        (alpha,) = report.subscriptions
        (period,) = alpha.periods
        self.assertEqual((period.until, period.held, period.refund.amount), (date(2026, 10, 4), date(2026, 10, 4),
                                                                             Decimal("19.20")))
        self.assertEqual((alpha.state, alpha.plan, alpha.paid_until, alpha.days_left, alpha.renew_soon),
                         ("ended", None, date(2026, 10, 4), None, False))
        self.assertEqual((alpha.profile_plan, alpha.profile_check), ("pro", "no-bill-today"))
        self.assertEqual(period.cost, Fraction(20 * 6, 30))
        self.assertEqual(alpha.this_month, Fraction(20 * 3, 30))
        september, october = report.table.months
        self.assertEqual((september.service_days[EMAIL_A], october.service_days[EMAIL_A]), (3, 3))
        self.assertEqual(report.coverage.until, date(2026, 10, 4))

    def test_before_its_date_the_refunded_plan_runs_only_to_it(self):
        (alpha,) = self.report([PRO, REFUND], now=epoch("2026-10-02T12:00:00Z")).subscriptions
        self.assertEqual((alpha.state, alpha.paid_until, alpha.days_left), ("active", date(2026, 10, 4), 2))

    def test_a_refunded_change_of_plan_does_not_bring_back_the_plan_it_replaced(self):
        bills = [bill(EMAIL_A, "2026-10-01", 20, plan="pro", period="2026-10-01..2026-11-01", reference="A-1"),
                 bill(EMAIL_A, "2026-10-10", 80, plan="max5x", period="2026-10-10..2026-11-10", reference="A-2"),
                 bill(EMAIL_A, "2026-10-15", 60, kind="refund", reference="A-2")]
        (alpha,) = self.report(bills, now=epoch("2026-10-20T12:00:00Z")).subscriptions
        pro, max5x = alpha.periods
        self.assertEqual((pro.until, max5x.how, max5x.until), (date(2026, 10, 10), "change", date(2026, 10, 15)))
        self.assertEqual((alpha.state, alpha.paid_until), ("ended", date(2026, 10, 15)))

    def test_an_order_after_a_refund_inside_the_printed_period_is_a_new_order(self):
        bills = [bill(EMAIL_A, "2026-10-01", 20, plan="pro", period="2026-10-01..2026-11-01", reference="A-1"),
                 bill(EMAIL_A, "2026-10-05", 15, kind="refund", reference="A-1"),
                 bill(EMAIL_A, "2026-10-20", 20, plan="pro", period="2026-10-20..2026-11-20", reference="A-2")]
        report = self.report(bills, now=epoch("2026-10-25T12:00:00Z"))
        (alpha,) = report.subscriptions
        first, second = alpha.periods
        self.assertEqual((second.how, second.gap_before), ("new", 15))
        self.assertEqual([(g.start, g.until) for g in alpha.gaps], [(date(2026, 10, 5), date(2026, 10, 20))])
        self.assertEqual((alpha.state, alpha.paid_until), ("active", date(2026, 11, 20)))
        self.assertEqual(report.problems, (), "a period starting inside a refunded one is no overlap")

    def test_a_period_refunded_on_its_first_day_holds_no_day_and_is_not_upcoming(self):
        bills = [bill(EMAIL_A, "2026-11-08", 20, plan="pro", period="2026-11-12..2026-12-12", reference="A-1"),
                 bill(EMAIL_A, "2026-11-09", 20, kind="refund", reference="A-1")]
        (alpha,) = self.report(bills, now=epoch("2026-11-10T12:00:00Z")).subscriptions
        (period,) = alpha.periods
        self.assertEqual((period.until, period.cost), (date(2026, 11, 12), Fraction(0)))
        self.assertEqual((alpha.state, alpha.paid_until), ("ended", date(2026, 11, 9)),
                         "ended on the refund's day, never on the future day the period would have begun")
        self.assertEqual(alpha.this_month, Fraction(0))

    def test_a_refunded_plan_span_ends_on_the_refunds_date(self):
        report = self.report([PRO, REFUND])
        (span,) = plan_spans(report)[ACCOUNT_A]
        self.assertEqual((span.plan, span.end), ("pro", day_start(date(2026, 10, 4))))

    def test_the_status_says_the_account_ended_on_the_refunds_date(self):
        report = self.report([PRO, REFUND])
        doc = status_document([standing(ACCOUNT_A, EMAIL_A)], Recommendation(None, "", None), now=NOW,
                              desktop_account=None, cli_account=None, cli_condition=None, billing=report)
        subscription = doc["accounts"][0]["subscription"]
        self.assertEqual((subscription["state"], subscription["paidUntil"], subscription["thisMonthListPrice"]),
                         ("ended", "2026-10-04", 2.0))
        self.assertNotIn("billsUnread", doc)


class RefundListedBesideItsBillTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()

    def tearDown(self):
        self.machine.close()

    def test_the_bills_command_lists_the_refund_under_its_bill(self):
        self.machine.bills_file([PRO, bill(EMAIL_A, "2026-11-01", 6, kind="topup", plan=None), REFUND])
        text = format_bills(billing_report(load_bills(self.machine.paths), {}, {}, None, NOW), listing=True)
        lines = text.splitlines()
        pro = next(i for i, line in enumerate(lines) if "Pro" in line and "[A-1]" in line)
        self.assertIn("refund", lines[pro + 1])
        self.assertIn("2026-10-04", lines[pro + 1])
        self.assertIn("EUR 19.20 returned on the bill [A-1]", lines[pro + 1])
        self.assertIn("no recorded plan today; the last period ended 2026-10-04", text)

    def test_the_history_shows_the_period_held_and_its_refund_beside_the_bill(self):
        self.machine.bills_file([PRO, REFUND])
        report = billing_report(load_bills(self.machine.paths), {}, {}, None, NOW)
        subs = history_subscriptions(report, [], NOW)
        (row,) = subs.periods
        self.assertEqual(row.in_effect, "2026-09-28 → 2026-10-04")
        self.assertIn("refunded EUR 19.20 on 2026-10-04", row.bill)
        self.assertEqual(row.list_price, "$4.00")
        (summary,) = subs.summary
        self.assertEqual(summary.bills, 1, "a refund is no bill of its own in the count")
        self.assertIn("refunded EUR 19.20 on 2026-10-04", summary.last_bill)

    def test_the_bills_window_lists_the_refund_directly_under_its_bill(self):
        self.machine.bills_file([PRO, bill(EMAIL_A, "2026-11-20", 6, kind="topup", plan=None),
                                 bill(EMAIL_A, "2026-11-02", 6, kind="topup", plan=None), REFUND])
        rows = read_list(self.machine.paths).rows
        kinds = [(r.what, r.date) for r in rows]
        self.assertEqual(kinds, [("top-up", "2026-11-20"), ("top-up", "2026-11-02"), ("Pro", "2026-09-28"),
                                 ("refund", "2026-10-04")])
        self.assertEqual(rows[-1].amount, "EUR 19.20")
        self.assertTrue(all(r.editable for r in rows))
        self.assertFalse(takes_plan("refund") or takes_period("refund"))

    def test_a_refund_is_recorded_only_against_a_bill_read_now(self):
        manifest = self.machine.manifest(manifest_rows(EMAIL_A, "A01", "2026-09-28", "24.00", "Claude Pro",
                                                       "2026-09-28..2026-10-28", invoice="A-1"))
        self.machine.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(manifest)}]})
        form = BillForm(account=EMAIL_A, date="2026-10-04", kind="refund", amount="19.20", currency="EUR",
                        reference="A-2")
        outcome = actions_model.record_bill(self.machine.paths, form)
        self.assertFalse(outcome.ok)
        self.assertIn("no bill of alpha@example.com read now has the reference A-2", outcome.message)
        outcome = actions_model.record_bill(self.machine.paths, BillForm(**dict(form.__dict__, reference="A-1")))
        self.assertTrue(outcome.ok, outcome.message)
        self.assertIn("refund of the bill A-1 EUR 19.20", outcome.message)
        bill_set = load_bills(self.machine.paths)
        self.assertEqual(bill_set.refund_of(next(b for b in bill_set.bills if b.kind == "subscription")).origin,
                         "bills.json bill 1", "the bills file's refund credits the archive's bill")

    def test_a_refund_and_its_bill_left_out_for_contradicting_each_other_can_be_put_right(self):
        self.machine.bills_file([PRO, dict(REFUND, currency="USD")])
        listing = read_list(self.machine.paths)
        self.assertEqual(load_bills(self.machine.paths).bills, (), "both are left out")
        refund_row = next(r for r in listing.rows if r.bill.kind == "refund")
        form = BillForm(account=EMAIL_A, date="2026-10-04", kind="refund", amount="19.20", currency="EUR",
                        reference="A-1")
        outcome = actions_model.replace_bill(self.machine.paths, refund_row.bill, form)
        self.assertTrue(outcome.ok, outcome.message)
        bill_set = load_bills(self.machine.paths)
        self.assertEqual([b.kind for b in bill_set.bills], ["subscription", "refund"])
        self.assertFalse(bill_set.unread)

    def test_a_bill_is_not_changed_so_that_its_refund_contradicts_it(self):
        self.machine.bills_file([PRO, REFUND])
        pro_row = next(r for r in read_list(self.machine.paths).rows if r.bill.kind == "subscription")
        form = BillForm(account=EMAIL_A, date="2026-09-28", kind="subscription", plan="Pro", amount="12.00",
                        currency="EUR", start="2026-09-28", end="2026-10-28", reference="A-1")
        outcome = actions_model.replace_bill(self.machine.paths, pro_row.bill, form)
        self.assertFalse(outcome.ok)
        self.assertIn("returns more than", outcome.message)
        self.assertEqual(read_bills_file(self.machine.paths.bills_file)[0].amount, Decimal(24))

    def test_the_command_line_records_a_refund_against_its_bill(self):
        self.machine.bills_file([PRO])
        data = str(self.machine.paths.data_dir)
        args = ["--data-dir", data, "--claude-home", str(self.machine.paths.claude_home), "bills", "add",
                "--account", EMAIL_A, "--date", "2026-10-04", "--kind", "refund", "--amount", "19.20",
                "--currency", "EUR"]
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args + ["--reference", "A-9"]), 2)
        self.assertIn("read now has the reference A-9", err.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(args + ["--reference", "A-1"]), 0)
        self.assertIn("refund of the bill A-1 EUR 19.20", out.getvalue())
        entries = json.loads(self.machine.paths.bills_file.read_text(encoding="utf-8"))["bills"]
        self.assertEqual(entries[-1], {"account": EMAIL_A, "date": "2026-10-04", "kind": "refund", "amount": 19.20,
                                       "currency": "EUR", "reference": "A-1"})


if __name__ == "__main__":
    unittest.main()
