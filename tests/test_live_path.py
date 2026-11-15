"""The whole pass on a synthetic machine, through the command line, as the service runs it."""

import contextlib
import io
import json
import time
import unittest

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bill,
                      bridge_line, epoch, manifest_rows, scripts_on, user_line)
from windowtally.__main__ import main
from windowtally.limits import FIVE_HOURS, WEEK
from windowtally.service import NOT_RUNNING_FRESH, run_pass

NOW = epoch("2026-10-20T20:00:00Z")


class LivePathTest(unittest.TestCase):
    """Account A is on the desktop app and the CLI; account B was used yesterday and has been idle since."""

    def setUp(self):
        self.machine = Machine()
        m = self.machine
        m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        m.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        self.b_weekly_reset = NOW + 2 * 86400
        m.app_history([(NOW - 86400 - 1800, ORG_B, 30, 70), (NOW - 86400, ORG_B, 40, 72),
                       (NOW - 3600, ORG_A, 10, 50)])
        m.sync_events([(NOW - 7200, "desktop_account", ACCOUNT_A), (NOW - 7100, "cli_account", ACCOUNT_A)])
        m.watch_view(ACCOUNT_A, ACCOUNT_A)
        m.transcript("desk", [bridge_line("desk", ACCOUNT_A, ORG_A), user_line("desk", "p1", NOW - 900)]
                     + assistant_lines("d1", NOW - 890, "desk"))
        m.transcript("cli", assistant_lines("c1", NOW - 600, "cli", entrypoint="sdk-cli", model="claude-sonnet-5-5",
                                            effort="high"), project="C--Temp-Review")
        self.five_hour_reset = NOW + 3 * 3600
        self.weekly_reset = NOW + 5 * 86400
        m.reading("desk", NOW - 60, (26, self.five_hour_reset), (60, self.weekly_reset))

    def tearDown(self):
        self.machine.close()

    def test_a_pass_produces_the_status_and_the_page(self):
        report = run_pass(self.machine.paths, NOW, dashboard=True)
        self.assertEqual(report.errors, [])
        self.assertTrue(report.dashboard_written)
        doc = json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))
        self.assertEqual((doc["desktopAccount"], doc["cliAccount"]), (ACCOUNT_A, ACCOUNT_A))
        by_label = {a["label"]: a for a in doc["accounts"]}
        alpha, beta = by_label["alpha"], by_label["beta"]
        # A's plugin reading is the freshest: exact figures and reset times.
        self.assertEqual((alpha["fiveHour"]["state"], alpha["fiveHour"]["percent"], alpha["fiveHour"]["estimated"]),
                         ("running", 26.0, False))
        self.assertEqual(alpha["weekly"]["percent"], 60.0)
        self.assertTrue(alpha["weekly"]["anchorExact"])
        # B's 5-hour window ended long ago and nothing has been sent since; its weekly figure stands.
        self.assertEqual(beta["fiveHour"]["state"], "not_started")
        self.assertEqual(beta["weekly"]["percent"], 72.0)
        # Both have room; A's weekly allowance resets in 5 days, B's reset time is unknown.
        self.assertEqual(doc["recommended"]["account"], ACCOUNT_A)
        self.assertTrue(self.machine.paths.dashboard_file.is_file())

    def test_responses_get_their_accounts(self):
        run_pass(self.machine.paths, NOW, dashboard=False)
        import sqlite3
        db = sqlite3.connect(self.machine.paths.ledger_db)
        rows = dict(((m, (a, s)) for m, a, s in db.execute("SELECT message_id, account_uuid, account_source FROM responses")))
        db.close()
        self.assertEqual(rows, {"d1": (ACCOUNT_A, "desktop-timeline"), "c1": (ACCOUNT_A, "cli-timeline")})

    def test_a_newer_sample_outranks_a_stale_watcher_view(self):
        # The watcher's view (written at NOW) says A; a later app sample says the app is now on B: the watcher
        # was not running when the account changed.
        self.machine.app_history([(NOW - 3600, ORG_A, 10, 50), (NOW + 1800, ORG_B, 1, 72)])
        run_pass(self.machine.paths, NOW + 2400, dashboard=False)
        doc = json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))
        self.assertEqual(doc["desktopAccount"], ACCOUNT_B)

    def desktop_after_pass(self, at: float) -> tuple:
        """What a pass at ``at`` writes of the desktop app: its account, the sign-in key, the accounts marked as the
        app's, and the CLI's account."""
        run_pass(self.machine.paths, at, dashboard=False)
        doc = json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))
        marked = {a["label"] for a in doc["accounts"] if a["isDesktop"]}
        return doc["desktopAccount"], doc.get("desktopSignedIn"), marked, doc["cliAccount"]

    def test_a_desktop_app_at_its_sign_in_page_is_no_account_s(self):
        # The watcher's view, newer than every point of the timeline, says the app is at its sign-in page.
        self.machine.watch_view(ACCOUNT_A, ACCOUNT_A, at=NOW, signed_out=True)
        self.assertEqual(self.desktop_after_pass(NOW + 60), (None, False, set(), ACCOUNT_A),
                         "the CLI keeps its own account")

    def test_a_sign_out_recorded_after_the_watchers_view_outranks_it(self):
        # An add read the app at its sign-in page in its log and recorded it before the watcher's next look.
        self.machine.sync_events([(NOW + 30, "desktop_signed_out", ACCOUNT_A)])
        self.assertEqual(self.desktop_after_pass(NOW + 60), (None, False, set(), ACCOUNT_A))

    def test_a_switch_recorded_after_a_signed_out_view_names_its_account(self):
        self.machine.watch_view(ACCOUNT_A, ACCOUNT_A, at=NOW, signed_out=True)
        self.machine.sync_events([(NOW + 30, "desktop_account", ACCOUNT_B)])
        self.assertEqual(self.desktop_after_pass(NOW + 60), (ACCOUNT_B, None, {"beta"}, ACCOUNT_A))

    def test_a_view_that_names_no_desktop_account_leaves_it_to_the_timeline(self):
        # No config.json the watcher could read: no word on the app, so the timeline's last point stands.
        self.machine.watch_view(None, ACCOUNT_A, at=NOW)
        self.assertEqual(self.desktop_after_pass(NOW + 60), (ACCOUNT_A, None, {"alpha"}, ACCOUNT_A))

    def running_after_pass(self, at: float) -> tuple:
        """What a pass at ``at`` writes of whether the desktop app runs: the key, its account, the accounts marked as
        the app's."""
        run_pass(self.machine.paths, at, dashboard=False)
        doc = json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))
        return doc.get("desktopRunning"), doc["desktopAccount"], {a["label"] for a in doc["accounts"] if a["isDesktop"]}

    def test_a_desktop_app_that_is_not_running_keeps_its_account(self):
        # The watcher's view, newer than every point of the timeline, says the app is not running: its account is
        # still the one it starts on.
        self.machine.watch_view(ACCOUNT_A, ACCOUNT_A, at=NOW, running=False)
        self.assertEqual(self.running_after_pass(NOW + 60), (False, ACCOUNT_A, {"alpha"}))

    def test_a_running_app_writes_no_key(self):
        self.machine.watch_view(ACCOUNT_A, ACCOUNT_A, at=NOW)
        self.assertEqual(self.running_after_pass(NOW + 60), (None, ACCOUNT_A, {"alpha"}))

    def test_a_switch_recorded_after_a_not_running_view_says_the_app_was_started(self):
        # A switch starts the app and records its account before the watcher's next look: the view is stale.
        self.machine.watch_view(ACCOUNT_A, ACCOUNT_A, at=NOW, running=False)
        self.machine.sync_events([(NOW + 30, "desktop_account", ACCOUNT_B)])
        self.assertEqual(self.running_after_pass(NOW + 60), (None, ACCOUNT_B, {"beta"}))

    def test_a_start_recorded_after_a_not_running_view_says_the_app_was_started(self):
        # The sync started the app and recorded its account before the watcher's next look.
        self.machine.watch_view(ACCOUNT_A, ACCOUNT_A, at=NOW, running=False)
        self.machine.sync_events([(NOW + 30, "desktop_account", ACCOUNT_A)])
        self.assertEqual(self.running_after_pass(NOW + 60), (None, ACCOUNT_A, {"alpha"}))

    def test_a_not_running_view_the_watcher_stopped_rewriting_says_nothing(self):
        # The watcher writes such a view at every look; one older than that bound means it stopped looking, and the
        # app may have been started by hand since.
        self.machine.watch_view(ACCOUNT_A, ACCOUNT_A, at=NOW, running=False)
        self.assertEqual(self.running_after_pass(NOW + NOT_RUNNING_FRESH), (False, ACCOUNT_A, {"alpha"}))
        self.assertEqual(self.running_after_pass(NOW + NOT_RUNNING_FRESH + 1), (None, ACCOUNT_A, {"alpha"}))

    def test_an_app_at_its_sign_in_page_and_not_running_says_both(self):
        self.machine.watch_view(ACCOUNT_A, ACCOUNT_A, at=NOW, signed_out=True, running=False)
        run_pass(self.machine.paths, NOW + 60, dashboard=False)
        doc = json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))
        self.assertEqual((doc["desktopAccount"], doc["desktopSignedIn"], doc["desktopRunning"]), (None, False, False))

    def test_the_command_line_says_an_app_that_is_not_running(self):
        p = self.machine.paths
        roots = ["--claude-home", str(p.claude_home), "--desktop-data", str(p.desktop_data), "--data-dir", str(p.data_dir)]
        # The command line's pass runs at the clock's time, so the watcher's view is written then.
        self.machine.watch_view(ACCOUNT_A, ACCOUNT_A, at=time.time(), running=False)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(roots + ["once"]), 0)
            self.assertEqual(main(roots + ["status"]), 0)
        self.assertIn("alpha  [desktop, not running, CLI]", out.getvalue())

    def test_the_command_line(self):
        p = self.machine.paths
        roots = ["--claude-home", str(p.claude_home), "--desktop-data", str(p.desktop_data), "--data-dir", str(p.data_dir)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(roots + ["once"]), 0)
            self.assertEqual(main(roots + ["status"]), 0)
        text = out.getvalue()
        self.assertIn("alpha  [desktop, CLI]", text)
        self.assertIn("beta", text)
        self.assertIn("Next: alpha", text)

    def bills(self):
        """A's bill in WindowTally's own bills file, B's in a bill archive's manifest the settings list."""
        m = self.machine
        m.bills_file([bill(EMAIL_A, "2026-10-03", 180, period="2026-10-03..2026-11-03", reference="A-1")])
        manifest = m.manifest(manifest_rows(EMAIL_B, "B01", "2026-09-23", "90.00", "Max plan - 5x",
                                            "2026-09-23..2026-10-23", invoice="B-1"))
        m.settings({"v": 1, "billSources": [{"format": "manifest", "path": str(manifest)}], "renewalReminderDays": 3})

    def test_a_pass_sets_each_account_s_bills_against_its_standing(self):
        self.bills()
        report = run_pass(self.machine.paths, NOW, dashboard=True)
        self.assertEqual(report.errors, [])
        doc = json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))
        self.assertEqual((doc["v"], doc["renewalReminderDays"]), (3, 3))
        by_label = {a["label"]: a["subscription"] for a in doc["accounts"]}
        # A month of Ultra at $200: 29 of the period's 31 days fall in October.
        self.assertEqual(by_label["alpha"], {
            "state": "active", "plan": "ultra", "planName": "Ultra", "paidUntil": "2026-11-03", "daysLeft": 14,
            "renewSoon": False, "thisMonthListPrice": 187.10, "profilePlan": "ultra", "profileCheck": "matches"})
        beta = by_label["beta"]
        # A month of Max 5x at $100: 22 of the period's 30 days fall in October; the profile still names Ultra.
        self.assertEqual((beta["plan"], beta["daysLeft"], beta["renewSoon"], beta["thisMonthListPrice"],
                          beta["profileCheck"]), ("max5x", 3, True, 73.33, "differs"))
        # The month's total comes from the exact values: $200 × 29/31 + $100 × 22/30.
        self.assertEqual(doc["thisMonth"]["plansAtListPrice"], 260.43)
        page = self.machine.paths.dashboard_file.read_text(encoding="utf-8")
        for heading in ("Plans at list price, by month", "Plan periods", "Gaps between periods"):
            self.assertIn(heading, page)
        self.assertIn("renew soon", page)
        # The page's own script, inline, and no other: none loaded from elsewhere, none in an attribute or a link.
        self.assertEqual(scripts_on(page), ["<script>"])

    def test_a_broken_bill_is_a_source_problem_not_a_failed_pass(self):
        self.bills()
        self.machine.bills_file([bill(EMAIL_A, "2026-10-03", 180, plan="max40x", period="2026-10-03..2026-11-03")])
        report = run_pass(self.machine.paths, NOW, dashboard=True)
        self.assertEqual(len(report.errors), 1, report.errors)
        self.assertIn("bills.json was read in part, 1 left out: bill 1: the plan 'max40x'", report.errors[0])
        doc = json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))
        # A's bills could not all be read, so nothing says it has none; B's manifest still counts.
        self.assertEqual({a["label"]: a["subscription"]["state"] for a in doc["accounts"]},
                         {"alpha": "unread", "beta": "active"})
        self.assertIs(doc.get("billsUnread"), True)
        self.assertTrue(self.machine.paths.dashboard_file.is_file())

    def test_without_bills_the_status_carries_no_subscription(self):
        run_pass(self.machine.paths, NOW, dashboard=True)
        doc = json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))
        self.assertEqual([a["subscription"] for a in doc["accounts"]], [None, None])
        self.assertIsNone(doc["renewalReminderDays"])
        self.assertIn("No bills recorded; <code>python -m windowtally bills add</code> records one",
                      self.machine.paths.dashboard_file.read_text(encoding="utf-8"))

    def test_the_status_command_shows_each_plan_and_refuses_another_version(self):
        self.bills()
        p = self.machine.paths
        roots = ["--claude-home", str(p.claude_home), "--desktop-data", str(p.desktop_data), "--data-dir", str(p.data_dir)]
        run_pass(p, NOW, dashboard=False)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main(roots + ["status"]), 0)
            doc = json.loads(p.status_file.read_text(encoding="utf-8"))
            p.status_file.write_text(json.dumps(dict(doc, v=1)), encoding="utf-8")
            self.assertEqual(main(roots + ["status"]), 1)
        self.assertIn("plan   : Ultra, paid until 2026-11-03 (14 days left)\n", out.getvalue(),
                      "no cost this month on a plan line")
        # $0.01 of use against $200 × 29/31 + $100 × 22/30 of plans: the window header's words, before Next:.
        self.assertIn("\nThis month: $0 API-equivalent · $260 plans at list price · 0.0×\nNext: ", out.getvalue())
        self.assertIn("Max 5x, paid until 2026-10-23 (3 days left), renew soon", out.getvalue())
        self.assertIn("is version 1; this version of WindowTally reads version 3", err.getvalue())


if __name__ == "__main__":
    unittest.main()
