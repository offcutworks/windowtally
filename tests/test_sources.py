"""The small sources: the desktop app's usage history, the plugin's readings, and the account sync's records."""

import json
import os
import unittest

from fixtures import ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, epoch
from windowtally.accounts import by_email, by_org, load_registry
from windowtally.ingest_app_history import AppHistoryFormatError, ingest_app_history
from windowtally.ingest_readings import RETENTION_SECONDS, ingest_readings
from windowtally.ingest_sync import ingest_sync_events, ingest_sync_log, read_watch_view
from windowtally.ledger import Ledger

T0 = epoch("2026-10-20T10:00:00Z")


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        self.registry, warnings = load_registry(self.machine.paths.accounts_dir)
        self.assertEqual(warnings, [])

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def observations(self, source):
        return self.ledger.db.execute(
            "SELECT ref, t, kind, percent, resets_at, account_uuid FROM observations WHERE source=? ORDER BY t, kind",
            (source,)).fetchall()

    def test_registry_reads_profiles_only(self):
        self.assertEqual(set(self.registry), {ACCOUNT_A, ACCOUNT_B})
        self.assertEqual(self.registry[ACCOUNT_A].label, "alpha")
        self.assertEqual(by_org(self.registry), {ORG_A: ACCOUNT_A, ORG_B: ACCOUNT_B})
        self.assertEqual(by_email(self.registry)[EMAIL_B], ACCOUNT_B)

    def test_app_history_samples_become_observations(self):
        self.machine.app_history([(T0, ORG_A, 12, 40), (T0 + 900, ORG_A, 15, 41)])
        added = ingest_app_history(self.ledger, self.machine.paths.plan_usage_history, by_org(self.registry))
        self.assertEqual(added, 4)
        self.assertEqual(self.observations("app"), [
            (ORG_A, T0, "five_hour", 12.0, None, ACCOUNT_A), (ORG_A, T0, "seven_day", 40.0, None, ACCOUNT_A),
            (ORG_A, T0 + 900, "five_hour", 15.0, None, ACCOUNT_A), (ORG_A, T0 + 900, "seven_day", 41.0, None, ACCOUNT_A)])
        self.assertEqual(ingest_app_history(self.ledger, self.machine.paths.plan_usage_history, by_org(self.registry)), 0)

    def test_app_history_of_an_organization_registered_later(self):
        self.machine.app_history([(T0, ORG_B, 5, 50)])
        ingest_app_history(self.ledger, self.machine.paths.plan_usage_history, {})
        self.assertEqual({row[5] for row in self.observations("app")}, {None})
        self.machine.app_history([(T0, ORG_B, 5, 50), (T0 + 900, ORG_B, 6, 50)])
        ingest_app_history(self.ledger, self.machine.paths.plan_usage_history, by_org(self.registry))
        self.assertEqual({row[5] for row in self.observations("app")}, {ACCOUNT_B})

    def test_app_history_in_an_unknown_format_is_refused(self):
        self.machine.app_history([(T0, ORG_A, 1, 1)], version=3)
        with self.assertRaises(AppHistoryFormatError):
            ingest_app_history(self.ledger, self.machine.paths.plan_usage_history, by_org(self.registry))

    def test_a_missing_app_history_is_no_error(self):
        self.assertEqual(ingest_app_history(self.ledger, self.machine.paths.plan_usage_history, {}), 0)

    def test_plugin_readings(self):
        five_hour_reset, weekly_reset = epoch("2026-10-20T14:00:00.086Z"), epoch("2026-10-25T22:00:00.086Z")
        self.machine.reading("s1", T0, (26, five_hour_reset), (60, weekly_reset))
        self.assertEqual(ingest_readings(self.ledger, self.machine.paths.readings_dir, now=T0), 2)
        self.assertEqual(self.observations("plugin"), [
            ("s1", T0, "five_hour", 26.0, five_hour_reset, None), ("s1", T0, "seven_day", 60.0, weekly_reset, None)])

    def test_a_reading_in_another_version_is_skipped(self):
        self.machine.reading("s1", T0, (26, T0), (60, T0), version=2)
        with self.assertLogs("windowtally.ingest_readings", level="WARNING"):
            self.assertEqual(ingest_readings(self.ledger, self.machine.paths.readings_dir, now=T0), 0)

    def test_a_malformed_window_is_skipped_and_the_rest_is_read(self):
        self.machine.paths.readings_dir.mkdir(parents=True, exist_ok=True)
        path = self.machine.paths.readings_dir / "s1.json"
        path.write_text(json.dumps({"v": 1, "t": int(T0 * 1000), "sessionId": "s1", "windows": [
            "junk", {"kind": "five_hour", "percentUsed": 10, "resetsAt": "2026-10-20T14:00:00Z"}]}), encoding="utf-8")
        with self.assertLogs("windowtally.ingest_readings", level="WARNING"):
            self.assertEqual(ingest_readings(self.ledger, self.machine.paths.readings_dir, now=T0), 1)
        self.assertEqual(ingest_readings(self.ledger, self.machine.paths.readings_dir, now=T0), 0, "read once, not retried")

    def test_old_readings_are_removed_once_ingested(self):
        path = self.machine.reading("s1", T0, (26, T0 + 3600), (60, T0 + 86400))
        old = T0 - RETENTION_SECONDS - 60
        os.utime(path, (old, old))
        self.assertEqual(ingest_readings(self.ledger, self.machine.paths.readings_dir, now=T0), 2)
        self.assertFalse(path.exists())
        self.assertEqual(len(self.observations("plugin")), 2, "what was read stays in the ledger")

    def test_sync_events_including_the_rotated_file(self):
        self.machine.sync_events([(T0, "cli_account", ACCOUNT_A)], rotated=True)
        self.machine.sync_events([(T0 + 60, "desktop_account", ACCOUNT_B.upper()), (T0 + 61, "cli_account", ACCOUNT_B)])
        with self.machine.paths.sync_events.open("a", encoding="utf-8") as handle:
            handle.write("not json\n" + json.dumps({"t": "2026-10-20T10:02:00Z", "kind": "other", "account": "x"}) + "\n")
        with self.assertLogs("windowtally.ingest_sync", level="WARNING"):
            added = ingest_sync_events(self.ledger, self.machine.paths.sync_events)
        self.assertEqual(added, 3)
        rows = self.ledger.db.execute("SELECT t, kind, account_uuid, source FROM account_events ORDER BY t").fetchall()
        self.assertEqual(rows, [(T0, "cli_account", ACCOUNT_A, "events"), (T0 + 60, "desktop_account", ACCOUNT_B, "events"),
                                (T0 + 61, "cli_account", ACCOUNT_B, "events")])

    def test_sync_log_switches_and_sign_ins(self):
        self.machine.sync_log([
            "2026-10-19T08:41:12-05:00 [installwatcher] Registered the logon task WindowTallySync and started it.",
            f"2026-10-19T09:58:30-05:00 [watch] Switched the CLI to {EMAIL_B} to match the desktop app.",
            f"2026-10-19T10:33:05-05:00 [sync] Signed in as {EMAIL_A} and stored it; later switches need no login.",
            "2026-10-19T10:47:50-05:00 [watch] Switched the CLI to stranger@example.com to match the desktop app.",
        ])
        self.assertEqual(ingest_sync_log(self.ledger, self.machine.paths.sync_log, by_email(self.registry)), 2)
        rows = self.ledger.db.execute("SELECT t, kind, account_uuid, source FROM account_events ORDER BY t").fetchall()
        self.assertEqual(rows, [(epoch("2026-10-19T14:58:30Z"), "cli_account", ACCOUNT_B, "sync-log"),
                                (epoch("2026-10-19T15:33:05Z"), "cli_account", ACCOUNT_A, "sync-log")])

    def test_watch_view(self):
        self.assertIsNone(read_watch_view(self.machine.paths.sync_watch_state))
        self.machine.watch_view(ACCOUNT_A.upper(), ACCOUNT_B, "waiting for a CLI to exit")
        view = read_watch_view(self.machine.paths.sync_watch_state)
        self.assertEqual((view.desktop_account, view.cli_account, view.condition),
                         (ACCOUNT_A, ACCOUNT_B, "waiting for a CLI to exit"))
        self.assertEqual(view.t, epoch("2026-10-20T20:00:00Z"))

    def test_a_desktop_app_at_its_sign_in_page_in_the_events_and_the_view(self):
        self.machine.watch_view(ACCOUNT_A, ACCOUNT_A)
        self.assertFalse(read_watch_view(self.machine.paths.sync_watch_state).desktop_signed_out,
                         "a view without the key is of an app that is not signed out")
        self.machine.sync_events([(T0, "desktop_account", ACCOUNT_A), (T0 + 60, "desktop_signed_out", ACCOUNT_A)])
        self.assertEqual(ingest_sync_events(self.ledger, self.machine.paths.sync_events), 2)
        rows = self.ledger.db.execute("SELECT t, kind, account_uuid FROM account_events ORDER BY t").fetchall()
        self.assertEqual(rows, [(T0, "desktop_account", ACCOUNT_A), (T0 + 60, "desktop_signed_out", ACCOUNT_A)])

        self.machine.watch_view(ACCOUNT_A, ACCOUNT_A, signed_out=True)
        view = read_watch_view(self.machine.paths.sync_watch_state)
        self.assertEqual((view.desktop_account, view.desktop_signed_out, view.cli_account), (None, True, ACCOUNT_A))

        # A view that names an account beside the signed-out key is read as the key says: the app is no account's.
        data = json.loads(self.machine.paths.sync_watch_state.read_text(encoding="utf-8"))
        data["desktopAccount"] = ACCOUNT_A
        self.machine.paths.sync_watch_state.write_text(json.dumps(data), encoding="utf-8")
        self.assertIsNone(read_watch_view(self.machine.paths.sync_watch_state).desktop_account)


if __name__ == "__main__":
    unittest.main()
