"""Bills read bill by bill, and what was not read never shown as what does not exist.

A source whose document breaks its contract — a manifest without a column read, a bills file that is not JSON — is
refused whole, and every account's bills are then not wholly read; within a source, a row that cannot be read leaves
out only the bill it belongs to, by its invoice number in a manifest and its reference in the bills file, and a row
belonging to no bill is left out alone, each named, the other bills counted. An account whose bills are not wholly
read is ``unread``: no surface — status.json, the ``status`` and ``bills`` commands, the history page, the window's
cards, header and History — says it has no bills, no plan today, an ended plan, a gap or a sum of nothing, and while
any bill is unread this month's plans at list price is not given as a known figure. Writing stays strict.
"""

import contextlib
import io
import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bill,
                      bridge_line, epoch, manifest_rows, status_account, status_document, status_subscription,
                      user_line)
from windowtally.__main__ import format_bills, format_status, main
from windowtally.accounts import load_registry
from windowtally.billing import billing_report, month_totals_text
from windowtally.bills import BillsError, add_bill, load_bills, make_bill, read_bills_file
from windowtally.bills_manifest import read_manifest, read_manifest_source
from windowtally.history import UNREAD_NOTE, subscriptions as history_subscriptions
from windowtally.service import run_pass
from windowtally_gui import history_model
from windowtally_gui.bills_model import read_list
from windowtally_gui.live_model import live_view
from windowtally_gui.status_model import snapshot_of

NOW = epoch("2026-10-20T20:00:00Z")
ABSENCES = ("no bills recorded", "no recorded bill covers today", "$0 plans at list price", "no plan today",
            "plan ended", "ended 20", "No bills recorded")


def rows(account: str, entry: str, day: str, period: str, invoice: str, line: str = "Max plan - 5x") -> list[dict]:
    return manifest_rows(account, entry, day, "90.00", line, period, invoice=invoice)


class ManifestBillByBillTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()

    def tearDown(self):
        self.machine.close()

    def test_a_row_of_an_unknown_type_leaves_out_only_its_bill(self):
        unknown = dict(rows(EMAIL_A, "A02", "2026-10-05", "2026-10-05..2026-11-05", "A-2")[0], doc_type="Statement")
        manifest = self.machine.manifest(rows(EMAIL_A, "A01", "2026-09-05", "2026-09-05..2026-10-05", "A-1")
                                         + rows(EMAIL_A, "A02", "2026-10-05", "2026-10-05..2026-11-05", "A-2")
                                         + [unknown]
                                         + rows(EMAIL_B, "B01", "2026-10-02", "2026-10-02..2026-11-02", "B-1"))
        read = read_manifest_source(manifest)
        self.assertEqual([b.reference for b in read.bills], ["A-1", "B-1"])
        (left_out,) = read.left_out
        self.assertEqual((left_out.account, left_out.problem, left_out.outcome),
                         (EMAIL_A, "row 6: unknown document type 'Statement'", "the bill A-2 is left out"))
        with self.assertRaises(BillsError) as caught:
            read_manifest(manifest)
        self.assertEqual(caught.exception.problems, ["row 6: unknown document type 'Statement'"])

    def test_a_refund_document_without_its_credit_note_leaves_out_its_bill(self):
        alone = dict(rows(EMAIL_A, "A01", "2026-10-05", "2026-10-05..2026-11-05", "A-1")[1], doc_type="Refund")
        read = read_manifest_source(self.machine.manifest(
            rows(EMAIL_A, "A01", "2026-10-05", "2026-10-05..2026-11-05", "A-1") + [alone]))
        self.assertEqual(read.bills, ())
        self.assertIn("a refund's own document without its credit note", read.left_out[0].problem)

    def test_a_credit_note_naming_another_period_leaves_out_its_bill(self):
        bill_rows = rows(EMAIL_A, "A01", "2026-10-05", "2026-10-05..2026-11-05", "A-1")
        credit = dict(bill_rows[0], doc_type="CreditNote", date="2026-10-09", amount="60.00",
                      service_period="2026-10-05..2026-11-06")
        read = read_manifest_source(self.machine.manifest(bill_rows + [credit]))
        self.assertEqual(read.bills, ())
        self.assertIn("the credit note's period '2026-10-05..2026-11-06' is not its invoice's", read.left_out[0].problem)

    def test_a_paid_row_naming_no_invoice_is_left_out_alone(self):
        stray = dict(rows(EMAIL_B, "B09", "2026-10-07", "2026-10-07..2026-11-07", "B-9")[0], invoice_no="")
        read = read_manifest_source(self.machine.manifest(
            rows(EMAIL_A, "A01", "2026-10-05", "2026-10-05..2026-11-05", "A-1") + [stray]))
        self.assertEqual([b.reference for b in read.bills], ["A-1"])
        self.assertEqual((read.left_out[0].account, read.left_out[0].outcome),
                         (EMAIL_B, "it belongs to no bill, so it is left out alone"))

    def test_a_manifest_without_a_column_is_refused_whole(self):
        data = rows(EMAIL_A, "A01", "2026-10-05", "2026-10-05..2026-11-05", "A-1")
        manifest = self.machine.manifest(data, columns=tuple(c for c in data[0] if c != "line_item"))
        with self.assertRaises(BillsError) as caught:
            read_manifest_source(manifest)
        self.assertIn("no column line_item", str(caught.exception))


class BillsFileBillByBillTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()

    def tearDown(self):
        self.machine.close()

    def test_an_entry_that_breaks_the_contract_leaves_out_its_reference_and_the_rest_count(self):
        self.machine.bills_file([
            bill(EMAIL_A, "2026-10-02", 90, plan="max5x", period="2026-10-02..2026-11-02", reference="A-1"),
            bill(EMAIL_A, "2026-10-09", 60, kind="refund", reference="A-1", currency="EURO"),
            bill(EMAIL_A, "2026-10-12", 6, kind="topup", plan=None, period="2026-10-12..2026-11-12"),
            bill(EMAIL_B, "2026-10-03", 200, period="2026-10-03..2026-11-03", reference="B-1")])
        bill_set = load_bills(self.machine.paths)
        self.assertEqual([b.reference for b in bill_set.bills], ["B-1"])
        self.assertEqual(bill_set.sources[0].bills, 1)
        self.assertEqual(len(bill_set.sources[0].left_out), 2)
        self.assertIn("bill 2: the currency 'EURO' is not an ISO 4217 code; the bill A-1 is left out",
                      bill_set.errors[0])
        self.assertIn("bill 3: a top-up has no service period; it names no reference, so it is left out alone",
                      bill_set.errors[0])
        self.assertEqual((bill_set.unread.everyone, bill_set.unread.emails), (False, {EMAIL_A}))

    def test_a_broken_entry_leaves_out_its_own_accounts_bill_of_a_reference_and_not_anothers(self):
        self.machine.bills_file([
            bill(EMAIL_B, "2026-10-03", 200, period="2026-10-03..2026-11-03", reference="INV-1"),
            bill(EMAIL_A, "2026-10-09", 60, kind="refund", reference="INV-1", currency="EURO"),
            dict(bill(EMAIL_A, "2026-10-10", 60, kind="refund", reference="INV-2"), account=7),
            bill(EMAIL_A, "2026-10-01", 200, period="2026-10-01..2026-11-01", reference="INV-2")])
        bill_set = load_bills(self.machine.paths)
        self.assertEqual([(b.account, b.reference) for b in bill_set.bills], [(EMAIL_B, "INV-1")],
                         "beta's bill of the same number stands; alpha's INV-2 goes with the entry naming no account")
        self.assertEqual((bill_set.unread.everyone, bill_set.unread.emails), (False, {EMAIL_A}),
                         "an entry naming no account is the account's whose bill it leaves out")

    def test_a_document_that_breaks_the_contract_is_refused_whole_and_concerns_everyone(self):
        self.machine.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.machine.paths.bills_file.write_text("{not json", encoding="utf-8")
        bill_set = load_bills(self.machine.paths)
        self.assertEqual((bill_set.sources[0].bills, bill_set.unread.everyone, bill_set.configured), (None, True, True))

    def test_writing_refuses_a_file_that_does_not_read_whole_and_the_window_lists_it_read_only(self):
        path = self.machine.bills_file([
            bill(EMAIL_A, "2026-10-02", 90, plan="max40x", period="2026-10-02..2026-11-02", reference="A-1"),
            bill(EMAIL_B, "2026-10-03", 200, period="2026-10-03..2026-11-03", reference="B-1")])
        new = make_bill(account=EMAIL_B, day=date(2026, 10, 20), kind="topup", plan=None, amount=Decimal(6), currency="EUR",
                        start=None, end=None, reference=None, origin="test", position=0)
        with self.assertRaises(BillsError):
            add_bill(path, new)
        with self.assertRaises(BillsError):
            read_bills_file(path)
        listing = read_list(self.machine.paths)
        self.assertEqual([(r.reference, r.editable) for r in listing.rows], [("B-1", False)])
        self.assertIn("1 left out", " ".join(listing.problems))


class UnreadIsNeverAbsentTest(unittest.TestCase):
    """Alpha is on the desktop app and the CLI; beta was used yesterday. Their bills are in a manifest."""

    def setUp(self):
        self.machine = m = Machine()
        m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        m.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        m.sync_events([(NOW - 7200, "desktop_account", ACCOUNT_A), (NOW - 7100, "cli_account", ACCOUNT_A)])
        m.watch_view(ACCOUNT_A, ACCOUNT_A)
        m.transcript("desk", [bridge_line("desk", ACCOUNT_A, ORG_A), user_line("desk", "p1", NOW - 900)]
                     + assistant_lines("d1", NOW - 890, "desk"))
        m.reading("desk", NOW - 60, (26, NOW + 3 * 3600), (60, NOW + 5 * 86400))
        self.rows = (rows(EMAIL_A, "A01", "2026-10-02", "2026-10-02..2026-11-02", "A-1", "Max plan - 20x")
                     + rows(EMAIL_B, "B01", "2026-10-05", "2026-10-05..2026-11-05", "B-1"))

    def tearDown(self):
        self.machine.close()

    def pass_over(self, manifest: Path) -> tuple[dict, str]:
        self.machine.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(manifest)}]})
        run_pass(self.machine.paths, NOW, dashboard=True)
        doc = json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))
        return doc, self.machine.paths.dashboard_file.read_text(encoding="utf-8")

    def surfaces(self, doc: dict, page: str) -> dict[str, str]:
        """Every surface's words: the status command, the bills command, the history page, the window's cards and
        header, and its History."""
        bill_set = load_bills(self.machine.paths)
        registry, _ = load_registry(self.machine.paths.accounts_dir)   # as the bills command reads the accounts
        report = billing_report(bill_set, registry, registry, None, NOW)
        view = live_view(snapshot_of(self.machine.paths.status_file, json.dumps(doc)), NOW)
        window = " | ".join([view.header.totals_line or ""] + [c.plan.text + " " + c.plan.note for c in view.cards])
        blocks = history_model.blocks(history_model.compute(self.machine.paths, "30d", tuple(doc["sourceErrors"]),
                                                            now=NOW))
        return {"status": format_status(doc), "bills": format_bills(report), "page": page, "window": window,
                "history": " | ".join(repr(b) for b in blocks)}

    def test_a_manifest_without_a_column_leaves_every_account_unread_on_every_surface(self):
        manifest = self.machine.manifest(self.rows, columns=tuple(c for c in self.rows[0] if c != "service_period"))
        doc, page = self.pass_over(manifest)
        subscriptions = {a["label"]: a["subscription"] for a in doc["accounts"]}
        for label in ("alpha", "beta"):
            self.assertEqual(subscriptions[label], {
                "state": "unread", "plan": None, "planName": None, "paidUntil": None, "daysLeft": None,
                "renewSoon": False, "thisMonthListPrice": None, "profilePlan": "ultra", "profileCheck": "unread"})
        self.assertEqual((doc["billsUnread"], doc["thisMonth"]["plansAtListPrice"]), (True, None))
        self.assertIn("has no column service_period", " ".join(doc["sourceErrors"]))
        self.assertEqual(doc["recommended"]["account"], ACCOUNT_A, "an account not wholly read is still weighed")
        surfaces = self.surfaces(doc, page)
        for name, text in surfaces.items():
            with self.subTest(name):
                for absence in ABSENCES:
                    self.assertNotIn(absence, text)
        self.assertIn("its bills could not all be read; see the source problems", surfaces["status"])
        self.assertIn("plans at list price not known: some bills could not be read", surfaces["status"])
        self.assertIn("its bills could not all be read; see the source problems", surfaces["bills"])
        self.assertIn("bills not all read", surfaces["page"])
        self.assertIn(UNREAD_NOTE, surfaces["page"])
        self.assertIn("plans at list price not known", surfaces["window"])
        self.assertEqual(surfaces["window"].count("bills not all read · see the source problems"), 2)
        self.assertIn("('Plans at list price', 'not known')", surfaces["history"])
        self.assertIn(UNREAD_NOTE, surfaces["history"])

    def test_a_bill_left_out_leaves_only_its_account_unread(self):
        broken = dict(rows(EMAIL_B, "B01", "2026-10-05", "2026-10-05..2026-11-05", "B-1")[0], amount="ninety")
        earlier = rows(EMAIL_A, "A00", "2026-09-01", "2026-09-01..2026-09-21", "A-0", "Max plan - 20x")
        doc, page = self.pass_over(self.machine.manifest(earlier + self.rows[:2] + [broken] + self.rows[3:]))
        subscriptions = {a["label"]: a["subscription"] for a in doc["accounts"]}
        self.assertEqual((subscriptions["alpha"]["state"], subscriptions["alpha"]["paidUntil"]), ("active", "2026-11-02"))
        self.assertEqual((subscriptions["beta"]["state"], subscriptions["beta"]["thisMonthListPrice"]), ("unread", None))
        self.assertEqual((doc["billsUnread"], doc["thisMonth"]["plansAtListPrice"]), (True, None))
        report = billing_report(load_bills(self.machine.paths), {}, {}, None, NOW)
        subs = history_subscriptions(report, [], NOW)
        self.assertEqual({r.label for r in subs.periods}, {"alpha"}, "an account not wholly read has no period shown")
        # Alpha had no plan 21 Sep to 2 Oct; beta, not wholly read, may have had one then.
        self.assertEqual([(g.label, g.days, g.covered) for g in subs.gaps], [("alpha", 11, "none by the bills read")])
        self.assertEqual(subs.coverage, "2026-09-01 to 2026-11-02: a plan on 51 of 62 days by the bills read; the bills "
                                        "not read may hold the other 11.")
        self.assertIn("none by the bills read", page)

    def test_every_bill_read_writes_no_unread_mark(self):
        doc, _ = self.pass_over(self.machine.manifest(self.rows))
        self.assertNotIn("billsUnread", doc)
        self.assertEqual({a["subscription"]["state"] for a in doc["accounts"]}, {"active"})
        self.assertIsNotNone(doc["thisMonth"]["plansAtListPrice"])

    def test_settings_that_cannot_be_read_leave_every_account_unread(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-10-02", 200, period="2026-10-02..2026-11-02")])
        self.machine.paths.settings_file.write_text("{not json", encoding="utf-8")
        bill_set = load_bills(self.machine.paths)
        self.assertTrue(bill_set.unread.everyone)
        report = billing_report(bill_set, {}, {}, None, NOW)
        self.assertEqual({s.state for s in report.subscriptions}, {"unread"})
        self.assertIsNone(report.this_month)


class UnreadWordsTest(unittest.TestCase):
    def test_the_months_totals_say_the_plans_are_not_known(self):
        self.assertEqual(month_totals_text(1283.56, None, unread=True),
                         "This month: $1,284 API-equivalent · plans at list price not known: some bills could not be read")
        self.assertEqual(month_totals_text(None, None, unread=True),
                         "This month: plans at list price not known: some bills could not be read")

    def test_the_window_reads_a_null_sum_only_on_an_account_not_wholly_read(self):
        unread = status_subscription(state="unread", plan=None, planName=None, paidUntil=None, daysLeft=None,
                                     thisMonthListPrice=None, profileCheck="unread")
        good = snapshot_of(Path("status.json"), json.dumps(status_document(
            [status_account(ACCOUNT_A, EMAIL_A, at=NOW, plan=unread)], at=NOW, billsUnread=True)))
        self.assertEqual((good.kind, good.status.bills_unread, good.status.accounts[0].subscription.this_month),
                         ("ok", True, None))
        bad = snapshot_of(Path("status.json"), json.dumps(status_document(
            [status_account(ACCOUNT_A, EMAIL_A, at=NOW, plan=status_subscription(thisMonthListPrice=None))], at=NOW)))
        self.assertEqual(bad.kind, "unreadable")

    def test_the_command_line_bills_listing_names_what_was_left_out(self):
        machine = Machine()
        try:
            broken = dict(rows(EMAIL_B, "B01", "2026-10-05", "2026-10-05..2026-11-05", "B-1")[0], status="disputed")
            manifest = machine.manifest(rows(EMAIL_A, "A01", "2026-10-02", "2026-10-02..2026-11-02", "A-1") + [broken])
            machine.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(manifest)}]})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--data-dir", str(machine.paths.data_dir), "--claude-home", str(machine.paths.claude_home),
                             "bills"])
            self.assertEqual(code, 1)
            self.assertIn(f"Source: {manifest} (manifest): 1 bill, 1 left out", out.getvalue())
            self.assertIn("row 4: unknown status 'disputed'; the bill B-1 is left out", out.getvalue())
        finally:
            machine.close()



if __name__ == "__main__":
    unittest.main()
