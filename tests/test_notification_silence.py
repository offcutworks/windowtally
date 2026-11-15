"""The user's setting that silences WindowTally's notifications: kept in the settings, off by default, switched by the
window, and carried by every pass into status.json, where the desktop plugin reads it; and the moment the first
account opens again, which status.json says was read or inferred as it says of a window's reset time.

Expected values follow the contracts' statements in ``windowtally/settings.py`` and ``windowtally/status_file.py``.
"""

import json
import unittest
from pathlib import Path

from fixtures import ACCOUNT_A, EMAIL_A, ORG_A, Machine, epoch, iso, status_account, status_document
from windowtally.accounts import Account
from windowtally.limits import AccountStanding, WeeklyAnchor, WindowStanding, recommend
from windowtally.service import run_pass
from windowtally.settings import (BillSource, Settings, SettingsError, load_settings, save_settings,
                                  set_notifications_silenced, set_renewal_reminder)
from windowtally.status_file import status_document as written_status_document
from windowtally_gui import actions_model
from windowtally_gui.formatting import when
from windowtally_gui.live_model import live_view
from windowtally_gui.status_model import snapshot_of

T0 = epoch("2026-10-20T10:00:00Z")


class SettingTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.path = self.machine.paths.settings_file

    def tearDown(self):
        self.machine.close()

    def test_off_by_default_and_absent_from_the_file_while_off(self):
        self.assertFalse(load_settings(self.path).silence_notifications)
        set_renewal_reminder(self.path, 3)
        self.assertNotIn("silenceNotifications", json.loads(self.path.read_text(encoding="utf-8")))

    def test_switched_on_and_off_keeping_every_other_setting(self):
        source = BillSource("manifest", self.machine.paths.data_dir / "_manifest.csv")
        save_settings(self.path, Settings((source,), 3))
        set_notifications_silenced(self.path, True)
        self.assertEqual(load_settings(self.path), Settings((source,), 3, True))
        self.assertIs(json.loads(self.path.read_text(encoding="utf-8"))["silenceNotifications"], True)
        set_notifications_silenced(self.path, False)
        self.assertEqual(load_settings(self.path), Settings((source,), 3, False))

    def test_a_value_that_is_not_true_or_false_refuses_the_file(self):
        for value in (1, "yes", None):
            self.machine.settings({"v": 1, "silenceNotifications": value})
            with self.subTest(value), self.assertRaises(SettingsError) as caught:
                load_settings(self.path)
            self.assertIn(f"silenceNotifications is {value!r}, not true or false", str(caught.exception))

    def test_a_broken_file_is_not_switched(self):
        self.machine.settings({"v": 1, "silenceNotifications": "yes"})
        with self.assertRaises(SettingsError):
            set_notifications_silenced(self.path, True)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"v": 1, "silenceNotifications": "yes"})


class PassTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.paths = self.machine.paths

    def tearDown(self):
        self.machine.close()

    def status(self) -> dict:
        run_pass(self.paths, now=T0)
        return json.loads(self.paths.status_file.read_text(encoding="utf-8"))

    def test_a_pass_carries_the_setting_into_status_json(self):
        self.assertIs(self.status()["notificationsSilenced"], False)
        set_notifications_silenced(self.paths.settings_file, True)
        self.assertIs(self.status()["notificationsSilenced"], True)

    def test_settings_that_cannot_be_read_leave_the_notifications_raised_and_are_named(self):
        self.machine.settings({"v": 1, "silenceNotifications": "yes"})
        doc = self.status()
        self.assertIs(doc["notificationsSilenced"], False)
        self.assertTrue(any(e.startswith("settings: ") and "silenceNotifications" in e for e in doc["sourceErrors"]))


class WindowActionTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.paths = self.machine.paths

    def tearDown(self):
        self.machine.close()

    def test_the_window_switches_the_setting_and_reads_it_back(self):
        self.assertIs(actions_model.silenced(self.paths), False)
        on = actions_model.set_silenced(self.paths, True)
        self.assertTrue(on.ok, on.message)
        self.assertIn("silenced", on.message)
        self.assertIs(actions_model.silenced(self.paths), True)
        off = actions_model.set_silenced(self.paths, False)
        self.assertTrue(off.ok, off.message)
        self.assertEqual(off.message, "WindowTally's notifications are raised again.")
        self.assertIs(actions_model.silenced(self.paths), False)

    def test_settings_that_cannot_be_read_are_said_and_read_back_as_unknown(self):
        self.machine.settings({"v": 2})
        outcome = actions_model.set_silenced(self.paths, True)
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.message.startswith("Not changed: "))
        self.assertIsNone(actions_model.silenced(self.paths))


def limited(five_reset: float, five_exact: bool) -> AccountStanding:
    """An account at 96 % of a running 5-hour window, half its week used."""
    return AccountStanding(Account(uuid=ACCOUNT_A, email=EMAIL_A),
                           WindowStanding("five_hour", "running", 96.0, five_reset, None, True,
                                          reset_exact=five_exact),
                           WindowStanding("seven_day", "current", 50.0, T0 + 5 * 86400, None, False),
                           WeeklyAnchor(T0 - 2 * 86400, exact=True), None, True, True)


class ReliefExactTest(unittest.TestCase):
    def test_the_first_opening_is_exact_only_where_its_reset_time_was_read(self):
        for exact in (True, False):
            rec = recommend([limited(T0 + 3600, exact)])
            self.assertEqual((rec.relief_at, rec.relief_exact), (T0 + 3600, exact))
            doc = written_status_document([limited(T0 + 3600, exact)], rec, now=T0, desktop_account=ACCOUNT_A,
                                      cli_account=ACCOUNT_A, cli_condition=None)
            self.assertIs(doc["recommended"]["reliefExact"], exact)

    def test_with_an_account_usable_there_is_no_exact_first_opening(self):
        usable = AccountStanding(Account(uuid=ACCOUNT_A, email=EMAIL_A),
                                 WindowStanding("five_hour", "running", 10.0, T0 + 3600, None, False, reset_exact=True),
                                 WindowStanding("seven_day", "current", 50.0, T0 + 5 * 86400, None, False),
                                 WeeklyAnchor(T0 - 2 * 86400, exact=True), None, True, True)
        rec = recommend([usable])
        self.assertEqual((rec.account_uuid, rec.relief_at, rec.relief_exact), (ACCOUNT_A, None, False))

    def test_the_window_marks_the_first_opening_only_where_it_was_inferred(self):
        def next_line(exact):
            mark = "" if exact else "≈"
            recommended = {"account": None, "reason": f"Every account is at its limit. The first opens "
                                                      f"{mark}{when(T0 + 7200)}.", "reliefAt": iso(T0 + 7200)}
            if exact is not None:
                recommended["reliefExact"] = exact
            doc = status_document([status_account(ACCOUNT_A, EMAIL_A, at=T0)], at=T0, recommended=recommended)
            return live_view(snapshot_of(Path("status.json"), json.dumps(doc)), T0).header.next_line

        self.assertTrue(next_line(True).endswith(f" The first opens {when(T0 + 7200)} (in 2h 00m)."), next_line(True))
        self.assertTrue(next_line(False).endswith(f" The first opens ≈{when(T0 + 7200)} (in ≈2h 00m)."))
        self.assertTrue(next_line(None).endswith(f" The first opens ≈{when(T0 + 7200)} (in ≈2h 00m)."),
                        "a status without the key: inferred")


if __name__ == "__main__":
    unittest.main()
