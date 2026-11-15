"""files, the pass lock and the read-only ledger: what lets the window read and write beside the service — a write
that waits out a reader, two passes that never overlap, and a ledger opened for reading that nothing can write."""

import sqlite3
import threading
import time
import unittest
from unittest import mock

from fixtures import ACCOUNT_A, EMAIL_A, ORG_A, Machine
from windowtally import files, service
from windowtally.files import write_text_atomically
from windowtally.ledger import SCHEMA_VERSION, Ledger, LedgerVersionError
from windowtally.service import PassLock, run_pass


class AtomicWriteTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.path = self.machine.paths.data_dir / "status.json"
        write_text_atomically(self.path, "first")

    def tearDown(self):
        self.machine.close()

    def test_a_write_waits_for_a_reader_holding_the_file(self):
        reader = open(self.path, encoding="utf-8")
        threading.Timer(0.3, reader.close).start()
        started = time.monotonic()
        write_text_atomically(self.path, "second")
        self.assertGreaterEqual(time.monotonic() - started, 0.25)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "second")
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["status.json"])

    def test_a_reader_that_stays_costs_the_write_which_says_so_and_leaves_no_temporary_file(self):
        with open(self.path, encoding="utf-8"), mock.patch.object(files, "REPLACE_PATIENCE", 0.2):
            with self.assertRaises(PermissionError):
                write_text_atomically(self.path, "second")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "first")
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["status.json"])

    def test_the_bytes_reach_the_disk_before_the_move(self):
        calls = []
        fsync, replace = files.os.fsync, files.os.replace
        with mock.patch.object(files.os, "fsync", side_effect=lambda fd: (calls.append("fsync"), fsync(fd))[1]), \
                mock.patch.object(files.os, "replace", side_effect=lambda a, b: (calls.append("replace"), replace(a, b))[1]):
            write_text_atomically(self.path, "second")
        self.assertEqual(calls, ["fsync", "replace"])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "second")

    def test_a_write_that_fails_leaves_the_file_as_it_was_and_no_temporary_file(self):
        with mock.patch.object(files.os, "fsync", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                write_text_atomically(self.path, "second")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "first")
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["status.json"])


class EditLockTest(unittest.TestCase):
    """A read, change and write of the user's bills or settings waits for another's, so neither change is lost."""

    def setUp(self):
        self.machine = Machine()

    def tearDown(self):
        self.machine.close()

    def bill(self, reference: str):
        from datetime import date
        from decimal import Decimal
        from windowtally.bills import make_bill
        return make_bill(account=EMAIL_A, day=date(2026, 10, 7), kind="topup", plan=None, amount=Decimal(6),
                         currency="EUR", start=None, end=None, reference=reference, origin="test", position=0)

    def test_a_change_waits_for_another_to_the_same_file_and_gives_up_after_its_patience(self):
        from windowtally.bills import add_bill, read_bills_file
        path = self.machine.paths.bills_file
        with files.editing(path), mock.patch.object(files, "EDIT_PATIENCE", 0.2):
            with self.assertRaises(TimeoutError) as caught:
                add_bill(path, self.bill("T-1"))
        self.assertIn("another change to the file has held", str(caught.exception))
        self.assertFalse(path.exists())
        hold = files.editing(path)
        hold.__enter__()
        threading.Timer(0.3, hold.__exit__, args=(None, None, None)).start()
        add_bill(path, self.bill("T-1"))
        add_bill(path, self.bill("T-2"))
        self.assertEqual([b.reference for b in read_bills_file(path)], ["T-1", "T-2"])

    def test_the_settings_take_the_same_lock(self):
        from windowtally.settings import set_renewal_reminder
        with files.editing(self.machine.paths.settings_file), mock.patch.object(files, "EDIT_PATIENCE", 0.2):
            with self.assertRaises(TimeoutError):
                set_renewal_reminder(self.machine.paths.settings_file, 3)


class PassLockTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)

    def tearDown(self):
        self.machine.close()

    def test_a_pass_waits_while_another_holds_the_lock_and_gives_up_after_its_patience(self):
        with PassLock(self.machine.paths.pass_lock):
            with mock.patch.object(service, "PASS_LOCK_PATIENCE", 0.3), self.assertRaises(TimeoutError):
                run_pass(self.machine.paths, dashboard=False)
            self.assertFalse(self.machine.paths.status_file.exists(), "nothing written while the lock was held")

    def test_a_pass_runs_once_the_other_ends(self):
        lock = PassLock(self.machine.paths.pass_lock)
        lock.__enter__()
        threading.Timer(0.3, lock.__exit__, args=(None, None, None)).start()
        report = run_pass(self.machine.paths, dashboard=False)
        self.assertEqual(report.errors, [])
        self.assertTrue(self.machine.paths.status_file.is_file())

    def test_the_lock_is_free_after_a_pass(self):
        run_pass(self.machine.paths, dashboard=False)
        with PassLock(self.machine.paths.pass_lock, patience=0):
            pass


class ReadOnlyLedgerTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.path = self.machine.paths.ledger_db

    def tearDown(self):
        self.machine.close()

    def test_it_reads_and_refuses_every_write(self):
        Ledger.open(self.path).close()
        ledger = Ledger.open_readonly(self.path)
        try:
            self.assertEqual(ledger.get_meta("schema_version"), str(SCHEMA_VERSION))
            with self.assertRaises(sqlite3.OperationalError):
                ledger.db.execute("INSERT INTO meta(key, value) VALUES ('x', 'y')")
        finally:
            ledger.close()

    def test_no_ledger_yet_is_said_and_creates_nothing(self):
        with self.assertRaises(FileNotFoundError):
            Ledger.open_readonly(self.path)
        self.assertFalse(self.path.exists())

    def test_another_schema_or_another_file_is_refused(self):
        ledger = Ledger.open(self.path)
        ledger.db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        ledger.db.commit()
        ledger.close()
        with self.assertRaises(LedgerVersionError):
            Ledger.open_readonly(self.path)
        other = self.machine.paths.data_dir / "other.sqlite3"
        other.write_text("not a database", encoding="utf-8")
        with self.assertRaises(LedgerVersionError):
            Ledger.open_readonly(other)


if __name__ == "__main__":
    unittest.main()
