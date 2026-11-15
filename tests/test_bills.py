"""bills, bills_manifest and settings: WindowTally's own bills file, a bill archive's manifest, the settings that list
sources, every source read into one list, and the command line that writes them."""

import contextlib
import io
import json
import unittest
from datetime import date
from decimal import Decimal
from unittest import mock

from fixtures import EMAIL_A, EMAIL_B, Machine, bill, epoch, manifest_rows
from windowtally.__main__ import main
from windowtally.bills import (BillsError, Unread, add_bill, add_source, load_bills, make_bill, read_bills_file,
                               remove_bill, remove_source, replace_bill)
from windowtally.bills_manifest import read_manifest
from windowtally.settings import (BillSource, Settings, SettingsError, load_settings, save_settings,
                                  set_renewal_reminder)

NON_LATIN = "\uccad\uad6c"   # a name outside ASCII (two Hangul syllables), as in a path a console code page garbles


class BillsFileTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()

    def tearDown(self):
        self.machine.close()

    def test_a_bill_reads_back_exactly(self):
        path = self.machine.bills_file([
            bill(EMAIL_A, "2026-10-12", 121.37, plan="ultra", period="2026-10-12..2026-11-12", reference="INV-1"),
            bill(EMAIL_A.upper(), "2026-10-14", 6, kind="topup", plan=None)])
        first, second = read_bills_file(path)
        self.assertEqual((first.account, first.date, first.kind, first.plan, first.amount, first.currency),
                         (EMAIL_A, date(2026, 10, 12), "subscription", "ultra", Decimal("121.37"), "EUR"))
        self.assertEqual((first.start, first.end, first.reference), (date(2026, 10, 12), date(2026, 11, 12), "INV-1"))
        self.assertEqual((second.account, second.kind, second.amount, second.start), (EMAIL_A, "topup", Decimal(6), None))

    def test_a_file_with_one_broken_bill_is_refused_whole_naming_every_problem(self):
        path = self.machine.bills_file([
            bill(EMAIL_A, "2026-10-11", 180, period="2026-10-11..2026-11-11"),
            bill(EMAIL_A, "2026-10-11", 180, plan="max10x", period="2026-10-11..2026-11-11"),
            bill(EMAIL_A, "2026-10-12", 6, kind="topup", plan=None, period="2026-10-12..2026-11-12"),
            dict(bill(EMAIL_A, "2026-10-13", 180, period="2026-10-13..2026-10-13"), currrency="EUR")])
        with self.assertRaises(BillsError) as caught:
            read_bills_file(path)
        problems = caught.exception.problems
        self.assertEqual(len(problems), 3, problems)
        self.assertIn("bill 2: the plan 'max10x' is not one of pro, max5x, ultra", problems[0])
        self.assertIn("bill 3: a top-up has no service period", problems[1])
        self.assertIn("bill 4: unknown field 'currrency'", problems[2])

    def test_a_period_must_end_after_it_starts_and_a_subscription_needs_one(self):
        path = self.machine.bills_file([bill(EMAIL_A, "2026-10-11", 180, period="2026-10-11..2026-10-11"),
                                        bill(EMAIL_A, "2026-10-11", 180)])
        with self.assertRaises(BillsError) as caught:
            read_bills_file(path)
        self.assertIn("ends before it starts", caught.exception.problems[0])
        self.assertIn("a subscription needs its service period", caught.exception.problems[1])

    def test_a_plan_that_is_not_text_is_refused_like_any_other_broken_bill(self):
        path = self.machine.bills_file([dict(bill(EMAIL_A, "2026-10-12", 90, period="2026-10-12..2026-11-12"),
                                             plan=["max5x"])])
        with self.assertRaises(BillsError) as caught:
            read_bills_file(path)
        self.assertIn("bill 1: the plan ['max5x'] is not one of pro, max5x, ultra", str(caught.exception))

    def test_another_version_and_text_amounts_are_refused(self):
        with self.assertRaises(BillsError) as caught:
            read_bills_file(self.machine.bills_file([], version=2))
        self.assertIn("version 2; this version of WindowTally reads version 1", str(caught.exception))
        path = self.machine.bills_file([dict(bill(EMAIL_A, "2026-10-11", 0, period="2026-10-11..2026-11-11"),
                                             amount="180.00")])
        with self.assertRaises(BillsError) as caught:
            read_bills_file(path)
        self.assertIn("the amount '180.00' is not a number", str(caught.exception))


class ChangingBillsTest(unittest.TestCase):
    """A bill of WindowTally's own file is replaced or removed by its place, and only while that place holds it as read."""

    def setUp(self):
        self.machine = Machine()
        self.path = self.machine.bills_file([
            bill(EMAIL_A, "2026-10-07", 180, period="2026-10-07..2026-11-07", reference="A-1"),
            dict(bill(EMAIL_A, "2026-11-07", 180, period="2026-11-07..2026-12-07", reference="A-2"), note="renewal")])

    def tearDown(self):
        self.machine.close()

    def entries(self):
        return json.loads(self.path.read_text(encoding="utf-8"))["bills"]

    def new_bill(self, **changes):
        values = dict(account=EMAIL_A, day=date(2026, 11, 7), kind="subscription", plan="max5x", amount=Decimal("90"),
                      currency="EUR", start=date(2026, 11, 7), end=date(2026, 12, 7), reference="A-2",
                      origin="test", position=0, note="lower plan")
        values.update(changes)
        return make_bill(**values)

    def test_a_note_reads_back_and_one_that_is_not_text_refuses_the_file(self):
        self.assertEqual([b.note for b in read_bills_file(self.path)], [None, "renewal"])
        self.machine.bills_file([dict(bill(EMAIL_A, "2026-10-07", 180, period="2026-10-07..2026-11-07"), note=5)])
        with self.assertRaises(BillsError) as caught:
            read_bills_file(self.path)
        self.assertIn("bill 1: the note 5 is not text", str(caught.exception))

    def test_a_bill_is_replaced_in_its_place(self):
        first, second = read_bills_file(self.path)
        replace_bill(self.path, second, self.new_bill())
        entries = self.entries()
        self.assertEqual(entries[0]["reference"], "A-1")
        self.assertEqual((entries[1]["plan"], entries[1]["amount"], entries[1]["note"]), ("max5x", 90, "lower plan"))
        self.assertEqual(len(entries), 2)

    def test_a_bill_is_removed_and_the_others_kept(self):
        first, _second = read_bills_file(self.path)
        remove_bill(self.path, first)
        self.assertEqual([e["reference"] for e in self.entries()], ["A-2"])

    def test_a_list_read_before_the_file_changed_changes_nothing(self):
        first, second = read_bills_file(self.path)
        remove_bill(self.path, first)  # another writer: the second bill now holds the first place
        before = self.path.read_bytes()
        for attempt in (lambda: remove_bill(self.path, first), lambda: replace_bill(self.path, second, self.new_bill())):
            with self.assertRaises(BillsError) as caught:
                attempt()
            self.assertIn("is no longer the bill that was read", str(caught.exception))
        self.assertEqual(self.path.read_bytes(), before)

    def test_a_replacement_may_not_repeat_another_bill_s_reference(self):
        first, _second = read_bills_file(self.path)
        with self.assertRaises(BillsError) as caught:
            replace_bill(self.path, first, self.new_bill(reference="A-2"))
        self.assertIn("already holds the bill A-2", str(caught.exception))

    def test_a_bill_added_keeps_its_note(self):
        add_bill(self.path, self.new_bill(reference="A-3", note="kept"))
        self.assertEqual(self.entries()[-1]["note"], "kept")


class SourceSettingsTest(unittest.TestCase):
    """The functions behind the command line's `bills source` and `bills remind`, which the window calls too."""

    def setUp(self):
        self.machine = Machine()
        self.manifest = self.machine.manifest(manifest_rows(EMAIL_A, "A01", "2026-10-02", "90.00", "Max plan - 5x",
                                                            "2026-10-02..2026-11-02", invoice="A-1"))

    def tearDown(self):
        self.machine.close()

    def test_a_source_is_listed_once_read_and_removed_however_it_is_spelt(self):
        settings, count = add_source(self.machine.paths, "manifest", self.manifest)
        self.assertEqual((settings.bill_sources, count), ((BillSource("manifest", self.manifest),), 1))
        settings, _ = add_source(self.machine.paths, "manifest", self.manifest.parent / ".." / self.manifest.parent.name
                                 / self.manifest.name)
        self.assertEqual(len(settings.bill_sources), 1)
        self.assertEqual(remove_source(self.machine.paths, self.manifest).bill_sources, ())

    def test_what_cannot_be_listed_leaves_the_settings_as_they_were(self):
        with self.assertRaises(ValueError) as caught:
            add_source(self.machine.paths, "bills", self.machine.paths.bills_file)
        self.assertIn("is read whenever it exists", str(caught.exception))
        rows = manifest_rows(EMAIL_A, "A01", "2026-10-02", "90.00", "Max plan - 5x", "2026-10-02..2026-11-02",
                             invoice="A-1")
        broken = self.machine.manifest(rows, name="broken.csv", columns=tuple(c for c in rows[0] if c != "service_period"))
        with self.assertRaises(BillsError):
            add_source(self.machine.paths, "manifest", broken)
        with self.assertRaises(ValueError):
            add_source(self.machine.paths, "pdf", self.manifest)
        with self.assertRaises(ValueError):
            remove_source(self.machine.paths, self.manifest)
        self.assertFalse(self.machine.paths.settings_file.exists())

    def test_a_manifest_with_an_unknown_line_is_not_listed(self):
        broken = self.machine.manifest(manifest_rows(EMAIL_A, "A01", "2026-10-02", "90.00", "Claude Max",
                                                     "2026-10-02..2026-11-02", invoice="A-1"), name="broken.csv")
        with self.assertRaises(BillsError):
            add_source(self.machine.paths, "manifest", broken)
        self.assertFalse(self.machine.paths.settings_file.exists())

    def test_the_reminder_is_set_and_cleared_keeping_the_sources(self):
        add_source(self.machine.paths, "manifest", self.manifest)
        self.assertEqual(set_renewal_reminder(self.machine.paths.settings_file, 5).renewal_reminder_days, 5)
        settings = set_renewal_reminder(self.machine.paths.settings_file, None)
        self.assertEqual(settings, Settings((BillSource("manifest", self.manifest),), None))
        for days in (0, 32, True):
            with self.subTest(days=days), self.assertRaises(ValueError):
                set_renewal_reminder(self.machine.paths.settings_file, days)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()

    def tearDown(self):
        self.machine.close()

    def test_no_file_means_the_defaults(self):
        self.assertEqual(load_settings(self.machine.paths.settings_file), Settings())

    def test_a_non_ascii_path_survives_a_round_trip(self):
        source = BillSource("manifest", self.machine.paths.data_dir / NON_LATIN / "_manifest.csv")
        save_settings(self.machine.paths.settings_file, Settings((source,), 3))
        self.assertEqual(load_settings(self.machine.paths.settings_file), Settings((source,), 3))
        self.assertIn(NON_LATIN, self.machine.paths.settings_file.read_text(encoding="utf-8"))

    def test_a_relative_source_is_taken_from_the_data_folder(self):
        self.machine.settings({"v": 1, "billSources": [{"format": "bills", "path": "more/bills.json"}]})
        (source,) = load_settings(self.machine.paths.settings_file).bill_sources
        self.assertEqual(source.path, self.machine.paths.data_dir / "more" / "bills.json")

    def test_a_misspelt_key_or_a_wrong_value_refuses_the_file(self):
        for data, problem in (({"v": 1, "renewalReminderDay": 3}, "unknown key 'renewalReminderDay'"),
                              ({"v": 1, "renewalReminderDays": 0}, "renewalReminderDays is 0"),
                              ({"v": 1, "renewalReminderDays": True}, "renewalReminderDays is True"),
                              ({"v": 1, "billSources": [{"format": "pdf", "path": "x"}]}, "the format 'pdf'"),
                              ({"v": 2}, "version 2; this version of WindowTally reads version 1")):
            self.machine.settings(data)
            with self.subTest(problem), self.assertRaises(SettingsError) as caught:
                load_settings(self.machine.paths.settings_file)
            self.assertIn(problem, str(caught.exception))


class ManifestTest(unittest.TestCase):
    """A manifest in a bill archive's shape: one row per document, paid bills as invoice and receipt."""

    def setUp(self):
        self.machine = Machine()

    def tearDown(self):
        self.machine.close()

    def test_each_paid_claude_bill_counts_once(self):
        rows = (manifest_rows(EMAIL_A, "A01", "2026-01-05", "18.00", "Claude Pro", "2026-01-05..2026-02-05",
                              invoice="X-1")
                + manifest_rows(EMAIL_A, "A02", "2026-01-10", "6.00", "Prepaid extra usage", invoice="X-2")
                + manifest_rows(EMAIL_A, "A03", "2026-02-01", "0.00", "Extra usage units", "2026-01-07..2026-01-31",
                                invoice="X-3")
                + manifest_rows(EMAIL_A, "A04", "2026-01-20", "64.00", "Max plan - 5x", "2026-01-20..2026-02-20",
                                invoice="X-4", status="voided")
                + manifest_rows(EMAIL_A, "G01", "2026-01-20", "20.00", "ChatGPT Plus Subscription",
                                "2026-01-20..2026-02-20", invoice="G-1", vendor="OpenAI ChatGPT", currency="USD"))
        bills = read_manifest(self.machine.manifest(rows))
        self.assertEqual([(b.kind, b.plan, b.amount, b.reference) for b in bills],
                         [("subscription", "pro", Decimal("18.00"), "X-1"), ("topup", None, Decimal("6.00"), "X-2"),
                          ("usage", None, Decimal("0.00"), "X-3")])
        self.assertEqual(bills[0].origin, "_manifest.csv row 2")

    def test_ultra_reads_under_its_earlier_line_and_its_own(self):
        rows = (manifest_rows(EMAIL_A, "A01", "2026-10-10", "200.00", "Max plan - 20x", "2026-10-10..2026-11-10",
                              invoice="X-1")
                + manifest_rows(EMAIL_A, "A02", "2026-11-10", "200.00", "Claude Ultra", "2026-11-10..2026-12-10",
                                invoice="X-2"))
        bills = read_manifest(self.machine.manifest(rows))
        self.assertEqual([(b.kind, b.plan, b.reference) for b in bills],
                         [("subscription", "ultra", "X-1"), ("subscription", "ultra", "X-2")])

    def test_a_missing_column_unknown_line_or_unpaired_receipt_refuses_the_manifest(self):
        rows = manifest_rows(EMAIL_A, "A01", "2026-01-05", "18.00", "Claude Pro", "2026-01-05..2026-02-05", invoice="X-1")
        columns = tuple(c for c in rows[0] if c != "service_period")
        with self.assertRaises(BillsError) as caught:
            read_manifest(self.machine.manifest(rows, columns=columns))
        self.assertIn("no column service_period", str(caught.exception))
        rows = (manifest_rows(EMAIL_A, "A01", "2026-01-05", "18.00", "Claude Max", "2026-01-05..2026-02-05",
                              invoice="X-1")
                + manifest_rows(EMAIL_A, "A02", "2026-02-05", "18.00", "Claude Pro", "2026-02-05..2026-03-05",
                                invoice="X-2")[1:])
        with self.assertRaises(BillsError) as caught:
            read_manifest(self.machine.manifest(rows))
        self.assertEqual(caught.exception.problems, ["row 2: unknown line item 'Claude Max'",
                                                     "invoice X-2: 0 invoice rows where a paid bill has one"])


class LoadBillsTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()

    def tearDown(self):
        self.machine.close()

    def test_nothing_configured_is_no_problem(self):
        bill_set = load_bills(self.machine.paths)
        self.assertFalse(bill_set.configured)
        self.assertEqual((bill_set.bills, bill_set.errors), ((), ()))

    def test_the_own_file_and_a_listed_manifest_are_combined(self):
        self.machine.bills_file([bill(EMAIL_B, "2026-10-11", 180, period="2026-10-11..2026-11-11", reference="B-1")])
        manifest = self.machine.manifest(
            manifest_rows(EMAIL_A, "A01", "2026-10-02", "90.00", "Max plan - 5x", "2026-10-02..2026-11-02",
                          invoice="A-1"))
        self.machine.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(manifest)}]})
        bill_set = load_bills(self.machine.paths)
        self.assertTrue(bill_set.configured)
        self.assertEqual(sorted(b.account for b in bill_set.bills), [EMAIL_A, EMAIL_B])
        self.assertEqual([s.bills for s in bill_set.sources], [1, 1])
        self.assertEqual(bill_set.errors, ())

    def test_a_bill_read_twice_counts_once_when_its_copies_agree_and_never_when_they_differ(self):
        self.machine.bills_file([
            bill(EMAIL_A, "2026-10-02", 90, plan="max5x", period="2026-10-02..2026-11-02", reference="A-1"),
            bill(EMAIL_A, "2026-10-06", 180, period="2026-10-06..2026-11-06", reference="A-2")])
        manifest = self.machine.manifest(
            manifest_rows(EMAIL_A, "A01", "2026-10-02", "90.00", "Max plan - 5x", "2026-10-02..2026-11-02",
                          invoice="A-1")
            + manifest_rows(EMAIL_A, "A02", "2026-10-06", "150.00", "Max plan - 20x", "2026-10-06..2026-11-06",
                            invoice="A-2"))
        self.machine.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(manifest)}]})
        bill_set = load_bills(self.machine.paths)
        self.assertEqual([(b.reference, b.origin) for b in bill_set.bills], [("A-1", "bills.json bill 1")])
        self.assertEqual([(d.reference, d.counted) for d in bill_set.duplicates], [("A-1", True), ("A-2", False)])
        self.assertEqual(len(bill_set.errors), 1)
        self.assertIn("2 bills are read more than once: 1 counted once, 1 left out", bill_set.errors[0])

    def test_one_bill_read_twice_is_said_in_the_singular(self):
        entry = bill(EMAIL_A, "2026-10-02", 90, plan="max5x", period="2026-10-02..2026-11-02", reference="A-1")
        self.machine.bills_file([entry, entry])
        self.assertIn("bills: 1 bill is read more than once: 1 counted once", load_bills(self.machine.paths).errors)

    def test_a_bill_that_breaks_the_contract_is_left_out_alone_and_its_account_not_wholly_read(self):
        # The broken entry names no reference, so it belongs to no bill: it alone is left out, its account named.
        self.machine.bills_file([dict(bill(EMAIL_A, "2026-10-02", 90, period="2026-10-02..2026-11-02"),
                                      plan={"name": "max5x"})])
        manifest = self.machine.manifest(manifest_rows(EMAIL_B, "B01", "2026-10-02", "90.00", "Max plan - 5x",
                                                       "2026-10-02..2026-11-02", invoice="B-1"))
        self.machine.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(manifest)}]})
        bill_set = load_bills(self.machine.paths)
        self.assertEqual([b.account for b in bill_set.bills], [EMAIL_B])
        self.assertEqual(len(bill_set.errors), 1)
        self.assertIn("bills.json was read in part, 1 left out: bill 1: the plan", bill_set.errors[0])
        self.assertTrue(bill_set.errors[0].endswith("; it names no reference, so it is left out alone"),
                        bill_set.errors[0])
        self.assertEqual(bill_set.unread, Unread(False, frozenset({EMAIL_A})))

    def test_a_broken_source_is_named_and_leaves_the_others(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-10-02", 90, plan="max5x", period="2026-10-02..2026-11-02")])
        missing = self.machine.paths.data_dir / "elsewhere.csv"
        self.machine.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(missing)}]})
        bill_set = load_bills(self.machine.paths)
        self.assertEqual(len(bill_set.bills), 1)
        self.assertEqual(bill_set.errors, (f"bills: {missing} does not exist",))

    def test_broken_settings_are_named_and_the_own_file_still_read(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-10-02", 90, plan="max5x", period="2026-10-02..2026-11-02")])
        self.machine.settings({"v": 1, "billSource": []})
        bill_set = load_bills(self.machine.paths)
        self.assertEqual(len(bill_set.bills), 1)
        self.assertTrue(bill_set.errors[0].startswith("settings: "), bill_set.errors)


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        p = self.machine.paths
        self.roots = ["--claude-home", str(p.claude_home), "--desktop-data", str(p.desktop_data),
                      "--data-dir", str(p.data_dir)]

    def tearDown(self):
        self.machine.close()

    def run_main(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(self.roots + list(args))
        return code, out.getvalue(), err.getvalue()

    def test_bills_add_writes_the_own_file_and_refuses_a_repeated_reference(self):
        args = ["bills", "add", "--account", EMAIL_A, "--date", "2026-10-12", "--plan", "ultra", "--amount", "121.37",
                "--currency", "EUR", "--period", "2026-10-12..2026-11-12", "--reference", "INV-7", "--note", "upgrade"]
        code, out, _ = self.run_main(*args)
        self.assertEqual(code, 0)
        self.assertIn("Recorded alpha@example.com: 2026-10-12 Ultra EUR 121.37", out)
        (entry,) = json.loads(self.machine.paths.bills_file.read_text(encoding="utf-8"))["bills"]
        self.assertEqual(entry, {"account": EMAIL_A, "date": "2026-10-12", "kind": "subscription", "plan": "ultra",
                                 "amount": 121.37, "currency": "EUR", "start": "2026-10-12", "end": "2026-11-12",
                                 "reference": "INV-7", "note": "upgrade"})
        self.assertEqual(read_bills_file(self.machine.paths.bills_file)[0].amount, Decimal("121.37"))
        code, _, err = self.run_main(*args)
        self.assertEqual(code, 2)
        self.assertIn("already holds the bill INV-7", err)

    def test_bills_add_refuses_a_bill_the_contract_does_not_allow(self):
        code, _, err = self.run_main("bills", "add", "--account", "alpha", "--date", "2026-10-12", "--plan", "pro",
                                     "--amount", "18", "--currency", "eur", "--period", "2026-10-12..2026-11-12")
        self.assertEqual(code, 2)
        self.assertIn("is not an e-mail address", err)
        self.assertIn("is not an ISO 4217 code", err)
        self.assertFalse(self.machine.paths.bills_file.exists())

    def test_bills_source_and_remind_write_the_settings(self):
        manifest = self.machine.manifest(manifest_rows(EMAIL_A, "A01", "2026-10-02", "90.00", "Max plan - 5x",
                                                       "2026-10-02..2026-11-02", invoice="A-1"),
                                         name=f"{NON_LATIN}.csv")
        code, out, _ = self.run_main("bills", "source", "--manifest", str(manifest))
        self.assertEqual(code, 0, out)
        self.assertIn("holds 1 bill.", out)
        code, _, _ = self.run_main("bills", "remind", "--days", "3")
        self.assertEqual(code, 0)
        settings = load_settings(self.machine.paths.settings_file)
        self.assertEqual(settings, Settings((BillSource("manifest", manifest),), 3))
        with mock.patch("time.time", return_value=epoch("2026-10-21T12:00:00Z")):
            code, out, _ = self.run_main("bills")
        self.assertEqual(code, 0, out)
        self.assertIn("Max 5x, paid until 2026-11-02", out)
        self.assertIn("Renewal reminder: within 3 days", out)
        self.assertEqual(self.run_main("bills", "remind", "--off")[0], 0)
        self.assertEqual(self.run_main("bills", "source", "--remove", str(manifest))[0], 0)
        self.assertEqual(load_settings(self.machine.paths.settings_file), Settings())

    def test_bills_source_removes_a_source_however_its_path_was_written(self):
        manifest = self.machine.manifest(manifest_rows(EMAIL_A, "A01", "2026-10-02", "90.00", "Max plan - 5x",
                                                       "2026-10-02..2026-11-02", invoice="A-1"))
        relative = "../" + manifest.relative_to(self.machine.paths.claude_home.parent).as_posix()  # from the data folder
        self.machine.settings({"v": 1, "billSources": [{"format": "manifest", "path": relative}]})
        code, out, _ = self.run_main("bills")
        self.assertIn("Source: ", out)
        self.assertIn("(manifest): 1 bill", out)
        self.assertEqual(self.run_main("bills", "source", "--remove", relative)[0], 0)
        self.assertEqual(load_settings(self.machine.paths.settings_file).bill_sources, ())
        self.machine.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(manifest)}]})
        roundabout = manifest.parent / ".." / manifest.parent.name / manifest.name.upper()
        self.assertEqual(self.run_main("bills", "source", "--remove", str(roundabout))[0], 0)
        self.assertEqual(load_settings(self.machine.paths.settings_file).bill_sources, ())

    def test_bills_source_refuses_a_file_that_does_not_read(self):
        rows = manifest_rows(EMAIL_A, "A01", "2026-10-02", "90.00", "Max plan - 5x", "2026-10-02..2026-11-02",
                             invoice="A-1")
        manifest = self.machine.manifest(rows, columns=tuple(c for c in rows[0] if c != "service_period"))
        code, _, err = self.run_main("bills", "source", "--manifest", str(manifest))
        self.assertEqual(code, 2)
        self.assertIn("no column service_period", err)
        self.assertFalse(self.machine.paths.settings_file.exists())

    def test_bills_source_refuses_a_manifest_with_an_unknown_line(self):
        manifest = self.machine.manifest(manifest_rows(EMAIL_A, "A01", "2026-10-02", "90.00", "Claude Max",
                                                       "2026-10-02..2026-11-02", invoice="A-1"))
        code, _, err = self.run_main("bills", "source", "--manifest", str(manifest))
        self.assertEqual(code, 2)
        self.assertIn("unknown line item 'Claude Max'", err)
        self.assertFalse(self.machine.paths.settings_file.exists())


if __name__ == "__main__":
    unittest.main()
