"""service: what a pass records of its own time, and the lines the service logs of every pass."""

import logging
import threading
import unittest
from unittest import mock

from fixtures import ACCOUNT_A, EMAIL_A, ORG_A, Machine, assistant_lines, epoch
from windowtally import service
from windowtally.service import PassLock, PassReport, pass_log_lines, run_pass

NOW = epoch("2026-10-21T18:30:00Z")
PHASES = ["ledger open", "registry", "sync events", "sync log", "desktop app history", "plugin readings",
          "browser readings", "transcripts", "prices", "attribution", "bills", "accounts in use", "standings",
          "billing", "recommendation", "use by product", "status.json"]


class PassTimingTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.machine.transcript("s1", assistant_lines("msg_1", NOW - 600, "s1"))

    def tearDown(self):
        self.machine.close()

    def test_a_pass_times_every_phase_in_the_order_they_ran(self):
        report = run_pass(self.machine.paths, NOW, dashboard=True)
        self.assertEqual([name for name, _ in report.phases], PHASES + [service.HISTORY_PAGE, "ledger close"])
        self.assertTrue(all(seconds >= 0 for _, seconds in report.phases))
        self.assertLessEqual(sum(seconds for _, seconds in report.phases), report.duration)

    def test_a_pass_without_the_page_has_no_page_phase(self):
        report = run_pass(self.machine.paths, NOW, dashboard=False)
        self.assertEqual([name for name, _ in report.phases], PHASES + ["ledger close"])

    def test_a_failing_source_keeps_its_phase_time(self):
        with mock.patch.object(service, "ingest_sync_events", side_effect=OSError("denied")):
            report = run_pass(self.machine.paths, NOW, dashboard=False)
        self.assertEqual(report.errors, ["sync events: denied"])
        self.assertEqual([name for name, _ in report.phases], PHASES + ["ledger close"])

    def test_a_pass_that_fails_says_where_its_time_went_before_it_failed(self):
        with mock.patch.object(service, "standings", side_effect=RuntimeError("broken")), \
                self.assertLogs("windowtally.service", logging.WARNING) as logged, self.assertRaises(RuntimeError):
            run_pass(self.machine.paths, NOW, dashboard=False)
        self.assertEqual(len(logged.records), 1)
        self.assertRegex(logged.records[0].getMessage(),
                         r"^A pass failed after [\d.]+ s, by phase: ledger open [\d.]+ s, registry [\d.]+ s, .*"
                         r"accounts in use [\d.]+ s, standings [\d.]+ s$")

    def test_the_wait_for_another_pass_is_kept_apart_from_the_pass_s_own_time(self):
        lock = PassLock(self.machine.paths.pass_lock)
        lock.__enter__()
        threading.Timer(1.2, lock.__exit__, args=(None, None, None)).start()
        report = run_pass(self.machine.paths, NOW, dashboard=False)
        self.assertGreaterEqual(report.lock_wait, 1.0)
        self.assertLess(report.duration, report.lock_wait)


class PassLogTest(unittest.TestCase):
    def report(self, **changes) -> PassReport:
        report = PassReport(started=NOW, duration=2.04, phases=[("registry", 0.01), ("transcripts", 0.5)])
        for name, value in changes.items():
            setattr(report, name, value)
        return report

    def test_a_pass_that_read_nothing_new_still_gives_its_time(self):
        self.assertEqual(pass_log_lines(self.report()),
                         [(logging.INFO, "Pass: 0 responses, 0 observations, 0 events, 0 attributed in 2.0 s")])

    def test_a_pass_with_source_problems_gives_its_time_and_names_them(self):
        lines = pass_log_lines(self.report(errors=["transcripts: denied", "bills: broken"]))
        self.assertEqual(lines[0], (logging.INFO, "Pass: 0 responses, 0 observations, 0 events, 0 attributed in 2.0 s"))
        self.assertEqual(lines[1], (logging.WARNING, "Pass finished with source problems: transcripts: denied; "
                                                     "bills: broken"))
        self.assertEqual(len(lines), 2)

    def test_the_line_gives_the_history_page_s_share_and_a_wait_for_another_pass(self):
        report = self.report(duration=8.0, dashboard_written=True, lock_wait=3.24,
                             phases=[("transcripts", 0.5), (service.HISTORY_PAGE, 6.04)])
        self.assertEqual(pass_log_lines(report), [(logging.INFO, (
            "Pass: 0 responses, 0 observations, 0 events, 0 attributed in 8.0 s; the history page took 6.0 s of it; "
            "it waited 3.2 s for another pass first"))])

    def test_a_short_wait_is_not_named(self):
        self.assertNotIn("waited", pass_log_lines(self.report(lock_wait=0.4))[0][1])

    def test_a_slow_pass_gives_the_time_of_every_phase(self):
        report = self.report(duration=service.SLOW_PASS + 2.3,
                             phases=[("registry", 0.0), ("transcripts", 11.84), ("status.json", 0.46)])
        lines = pass_log_lines(report)
        self.assertEqual(lines[-1], (logging.INFO, "Slow pass, 12.3 s by phase: registry 0.0 s, transcripts 11.8 s, "
                                                   "status.json 0.5 s"))
        self.assertEqual(len(lines), 2)

    def test_the_pass_line_keeps_the_words_it_was_counted_by(self):
        line = pass_log_lines(self.report(duration=1.0))[0][1]
        self.assertRegex(line, r"^Pass: \d+ responses, \d+ observations, \d+ events, \d+ attributed in [\d.]+ s")


if __name__ == "__main__":
    unittest.main()
