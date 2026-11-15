"""The sync store's desktop switching state (windowtally/sync_store.py), and the service's carrying of it into
status.json."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from fixtures import ACCOUNT_A, ACCOUNT_B, EMAIL_A, ORG_A, Machine, epoch, register_session
from windowtally.service import run_pass
from windowtally.sync_store import DESKTOP_ARCHIVE_FILE, desktop_archived_accounts, read_sync_settings

NOW = epoch("2026-10-25T12:00:00Z")


class DesktopArchivedAccountsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="archivetest-")
        self.accounts = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_no_store_and_an_empty_store_have_no_archive(self):
        self.assertEqual(desktop_archived_accounts(self.accounts / "absent"), set())
        self.assertEqual(desktop_archived_accounts(self.accounts), set())

    def test_an_account_has_one_when_its_folder_holds_the_archive_file(self):
        (self.accounts / ACCOUNT_A.upper()).mkdir()
        (self.accounts / ACCOUNT_A.upper() / DESKTOP_ARCHIVE_FILE).write_bytes(b"sealed")
        (self.accounts / ACCOUNT_B).mkdir()
        (self.accounts / ACCOUNT_B / "oauthAccount.json").write_text("{}", encoding="utf-8")
        (self.accounts / "events.jsonl").write_text("", encoding="utf-8")
        self.assertEqual(desktop_archived_accounts(self.accounts), {ACCOUNT_A})


class ReadSyncSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="settingstest-")
        self.path = Path(self.temp.name) / "sync-settings.json"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, text: str) -> None:
        self.path.write_text(text, encoding="utf-8")

    def test_both_switches_are_on_until_turned_off(self):
        self.assertEqual(read_sync_settings(self.path), (True, True))

    def test_each_is_read_on_its_own(self):
        self.write(json.dumps({"followsDesktop": False, "oneClickDesktop": True}))
        self.assertEqual(read_sync_settings(self.path), (False, True))
        self.write(json.dumps({"oneClickDesktop": False}))
        self.assertEqual(read_sync_settings(self.path), (True, False))

    def test_a_value_that_is_not_true_or_false_leaves_that_switch_on(self):
        self.write(json.dumps({"followsDesktop": "no", "oneClickDesktop": 0}))
        self.assertEqual(read_sync_settings(self.path), (True, True))

    def test_a_file_that_cannot_be_read_leaves_both_on_and_says_so(self):
        self.write("not json")
        with self.assertLogs("windowtally.sync_store", level="WARNING"):
            self.assertEqual(read_sync_settings(self.path), (True, True))
        self.write("[1, 2]")
        self.assertEqual(read_sync_settings(self.path), (True, True))


class PassTest(unittest.TestCase):
    """A pass carries the switching state into status.json: the switches, the archives, the sessions at work."""

    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.paths = self.machine.paths

    def tearDown(self):
        self.machine.close()

    def status(self) -> dict:
        run_pass(self.paths, now=NOW)
        return json.loads(self.paths.status_file.read_text(encoding="utf-8"))

    def test_a_machine_with_none_of_it_reads_as_follows_on_one_click_on_no_archive_no_session_at_work(self):
        doc = self.status()
        self.assertNotIn("syncFollows", doc)
        self.assertIs(doc["oneClickDesktop"], True)
        self.assertNotIn("workingSessions", doc)
        self.assertNotIn("desktopArchived", doc["accounts"][0])

    def test_the_switches_the_archives_and_the_sessions_at_work_are_carried(self):
        self.paths.sync_settings.write_text(json.dumps({"followsDesktop": False, "oneClickDesktop": False}),
                                            encoding="utf-8")
        (self.paths.accounts_dir / ACCOUNT_A / DESKTOP_ARCHIVE_FILE).write_bytes(b"sealed")
        for name, pid in (("one", None), ("two", os.getppid())):
            register_session(self.paths.claude_home, name, pid=pid)
        doc = self.status()
        self.assertIs(doc["syncFollows"], False)
        self.assertNotIn("oneClickDesktop", doc, "off is the key's absence, which a reader reads as unavailable")
        self.assertEqual(doc["workingSessions"], 2)
        self.assertIs(doc["accounts"][0]["desktopArchived"], True)


if __name__ == "__main__":
    unittest.main()
