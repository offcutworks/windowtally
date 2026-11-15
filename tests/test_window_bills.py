"""The Bills and sources window's logic: its lists, its form — checked by WindowTally's own bill rules, so it accepts and
refuses what the command line does — and what its buttons write."""

import json
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from fixtures import EMAIL_A, EMAIL_B, Machine, bill, manifest_rows
from windowtally.bills import read_bills_file
from windowtally.settings import BillSource, load_settings
from windowtally_gui import actions_model
from windowtally_gui.bills_model import BillForm, blank_form, check, form_of, next_month, read_list, with_kind


class BillsListTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        m = self.machine
        m.bills_file([bill(EMAIL_A, "2026-09-07", 180, period="2026-09-07..2026-10-07", reference="A-0"),
                      bill(EMAIL_A, "2026-10-07", 180, period="2026-10-07..2026-11-07", reference="A-1")])
        self.manifest = m.manifest(manifest_rows(EMAIL_B, "B01", "2026-09-23", "100.00", "Max plan - 5x",
                                                 "2026-09-23..2026-10-23", invoice="B-1", currency="USD"))
        m.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(self.manifest)}],
                    "renewalReminderDays": 3})

    def tearDown(self):
        self.machine.close()

    def test_every_source_s_bills_newest_first_and_only_the_own_file_s_editable(self):
        listing = read_list(self.machine.paths, ("Gamma@Example.com",))
        self.assertEqual([(r.date, r.account, r.what, r.amount, r.source, r.editable) for r in listing.rows], [
            ("2026-10-07", EMAIL_A, "Ultra", "EUR 180.00", "bills.json", True),
            ("2026-09-23", EMAIL_B, "Max 5x", "USD 100.00", "_manifest.csv", False),
            ("2026-09-07", EMAIL_A, "Ultra", "EUR 180.00", "bills.json", True)])
        self.assertEqual(listing.rows[0].period, "2026-10-07 → 2026-11-07")
        self.assertEqual([(s.format, s.bills, s.own) for s in listing.sources], [("bills", 2, True),
                                                                                 ("manifest", 1, False)])
        self.assertEqual(listing.reminder_days, 3)
        self.assertEqual(listing.accounts, (EMAIL_A, EMAIL_B, "gamma@example.com"))

    def test_a_source_says_how_much_of_it_was_read_and_which_is_the_window_s_own(self):
        own, other = read_list(self.machine.paths).sources
        self.assertEqual((own.count, own.name.endswith("bills.json (own)")), ("2 bills", True))
        self.assertEqual((other.count, other.name), ("1 bill", str(self.manifest)))
        self.assertEqual(replace(other, bills=350, left_out=("a", "b")).count, "350 bills, 2 left out")
        self.assertEqual(replace(other, bills=None).count, "absent")
        self.assertEqual(replace(other, bills=None, problems=("unreadable",)).count, "not read")

    def test_a_copy_left_out_of_the_figures_is_still_listed_so_it_can_be_removed(self):
        self.machine.bills_file([bill(EMAIL_B, "2026-09-23", 90, plan="max5x", period="2026-09-23..2026-10-23",
                                      currency="USD", reference="B-1")])
        listing = read_list(self.machine.paths)
        own = [r for r in listing.rows if r.editable]
        self.assertEqual([r.amount for r in own], ["USD 90.00"])
        self.assertTrue(any("read more than once" in p for p in listing.problems))

    def test_a_new_bill_starts_from_the_account_s_latest_subscription(self):
        listing = read_list(self.machine.paths)
        form = blank_form(listing, EMAIL_A, date(2026, 11, 7))
        self.assertEqual(form, BillForm(account=EMAIL_A, date="2026-11-07", kind="subscription", plan="Ultra",
                                        amount="180.00", currency="EUR", start="2026-11-07", end="2026-12-07"))
        self.assertEqual(blank_form(listing, "new@example.com", date(2026, 1, 31)).end, "2026-02-28")


class FormTest(unittest.TestCase):
    def form(self, **changes) -> BillForm:
        values = dict(account=EMAIL_A, date="2026-10-07", kind="subscription", plan="Max 5x", amount="1,090.50",
                      currency="eur", start="2026-10-07", end="2026-11-07", reference=" INV-9 ", note=" a note ")
        values.update(changes)
        return BillForm(**values)

    def test_the_form_becomes_the_bill_the_command_line_would_record(self):
        made = check(self.form())
        self.assertEqual((made.account, made.date, made.kind, made.plan, made.amount, made.currency),
                         (EMAIL_A, date(2026, 10, 7), "subscription", "max5x", Decimal("1090.50"), "EUR"))
        self.assertEqual((made.start, made.end, made.reference, made.note),
                         (date(2026, 10, 7), date(2026, 11, 7), "INV-9", "a note"))

    def test_a_comma_is_read_only_as_a_thousands_separator(self):
        self.assertEqual(check(self.form(amount="12,345")).amount, Decimal("12345"))
        for written in ("12,50", "1,0905", "1,2,3"):
            with self.subTest(written), self.assertRaises(ValueError) as caught:
                check(self.form(amount=written))
            self.assertIn("write its decimals after a point", str(caught.exception))

    def test_every_problem_is_named_in_windowtally_s_words(self):
        with self.assertRaises(ValueError) as caught:
            check(self.form(date="2026-13-01", amount="ten"))
        self.assertIn("the date '2026-13-01' is not a calendar day", str(caught.exception))
        self.assertIn("the amount 'ten' is not a number", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            check(self.form(account="alpha", end="2026-10-07"))
        self.assertIn("is not an e-mail address", str(caught.exception))
        self.assertIn("ends before it starts", str(caught.exception))

    def test_a_kind_takes_only_the_fields_it_has(self):
        topup = check(self.form(kind="topup", plan="Max 5x", start="2026-10-07", end="2026-11-07"))
        self.assertEqual((topup.plan, topup.start, topup.end), (None, None, None))
        usage = check(self.form(kind="usage"))
        self.assertEqual((usage.plan, usage.start), (None, date(2026, 10, 7)))
        opened = with_kind(self.form(kind="topup", start="", end=""), "usage", date(2026, 1, 1))
        self.assertEqual((opened.start, opened.end), ("2026-10-07", "2026-11-07"))

    def test_a_bill_put_back_in_the_form_reads_as_itself(self):
        made = check(self.form())
        self.assertEqual(check(form_of(made)), made)

    def test_a_month_on_keeps_the_day_where_the_month_has_it(self):
        self.assertEqual([next_month(d) for d in (date(2026, 5, 7), date(2026, 1, 31), date(2026, 12, 15))],
                         [date(2026, 6, 7), date(2026, 2, 28), date(2027, 1, 15)])


class BillActionsTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.paths = self.machine.paths

    def tearDown(self):
        self.machine.close()

    def form(self, **changes) -> BillForm:
        values = dict(account=EMAIL_A, date="2026-10-07", kind="subscription", plan="Ultra", amount="180",
                      currency="EUR", start="2026-10-07", end="2026-11-07", reference="A-1")
        values.update(changes)
        return BillForm(**values)

    def test_record_change_and_remove_a_bill(self):
        outcome = actions_model.record_bill(self.paths, self.form())
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(outcome.message, f"Recorded {EMAIL_A}: 2026-10-07 Ultra EUR 180.00, 2026-10-07..2026-11-07.")
        (recorded,) = read_bills_file(self.paths.bills_file)
        outcome = actions_model.replace_bill(self.paths, recorded, self.form(plan="Max 5x", amount="90"))
        self.assertTrue(outcome.ok, outcome.message)
        (changed,) = read_bills_file(self.paths.bills_file)
        self.assertEqual((changed.plan, changed.amount), ("max5x", Decimal("90")))
        self.assertTrue(actions_model.remove_bill(self.paths, changed).ok)
        self.assertEqual(json.loads(self.paths.bills_file.read_text(encoding="utf-8"))["bills"], [])

    def test_a_refusal_changes_nothing_and_says_why(self):
        outcome = actions_model.record_bill(self.paths, self.form(currency="euros"))
        self.assertFalse(outcome.ok)
        self.assertIn("Not recorded: the currency 'EUROS' is not an ISO 4217 code", outcome.message)
        self.assertFalse(self.paths.bills_file.exists())
        self.assertTrue(actions_model.record_bill(self.paths, self.form()).ok)
        outcome = actions_model.record_bill(self.paths, self.form())
        self.assertIn("already holds the bill A-1", outcome.message)
        (recorded,) = read_bills_file(self.paths.bills_file)
        self.paths.bills_file.write_text(json.dumps({"v": 1, "bills": []}), encoding="utf-8")
        outcome = actions_model.remove_bill(self.paths, recorded)
        self.assertFalse(outcome.ok)
        self.assertIn("is no longer the bill that was read", outcome.message)

    def test_sources_and_the_reminder(self):
        manifest = self.machine.manifest(manifest_rows(EMAIL_A, "A01", "2026-10-02", "90.00", "Max plan - 5x",
                                                       "2026-10-02..2026-11-02", invoice="A-1"))
        outcome = actions_model.add_source(self.paths, "manifest", manifest)
        self.assertEqual((outcome.ok, outcome.message), (True, f"Added {manifest}: 1 bill."))
        self.assertEqual(load_settings(self.paths.settings_file).bill_sources, (BillSource("manifest", manifest),))
        outcome = actions_model.add_source(self.paths, "bills", self.paths.bills_file)
        self.assertFalse(outcome.ok)
        self.assertIn("Not changed:", outcome.message)
        self.assertTrue(actions_model.set_reminder(self.paths, 3).ok)
        self.assertEqual(load_settings(self.paths.settings_file).renewal_reminder_days, 3)
        outcome = actions_model.set_reminder(self.paths, 40)
        self.assertFalse(outcome.ok)
        self.assertIn("from 1 to 31", outcome.message)
        self.assertEqual(actions_model.set_reminder(self.paths, None).message, "Renewal tag: off.")
        self.assertTrue(actions_model.remove_source(self.paths, manifest).ok)
        self.assertFalse(actions_model.remove_source(self.paths, manifest).ok)


if __name__ == "__main__":
    unittest.main()
