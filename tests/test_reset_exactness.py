"""A reset time read exactly reads as exact on every surface, whatever its window's figure.

status.json's ``estimated`` covers a window's figure and its reset time together; ``anchorExact``, on every window,
says whether the reset time came from a plugin reading, and every surface marks a reset time ≈ only where it did not.
Expected values follow that rule and the window rules — a plugin reading carries the exact reset time; without one the
5-hour window ends five hours after the first message of its run — never read back from the code.
"""

import json
import unittest
from pathlib import Path

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bridge_line,
                      epoch, status_account, status_document as status_doc, status_window, user_line)
from windowtally.__main__ import format_status
from windowtally.accounts import Account, by_org, load_registry
from windowtally.attribution import attribute
from windowtally.dashboard import render_dashboard
from windowtally.ingest_app_history import ingest_app_history
from windowtally.ingest_transcripts import ingest_transcripts
from windowtally.ledger import Ledger, Observation
from windowtally.limits import (FIVE_HOURS, AccountStanding, Recommendation, WeeklyAnchor, WindowStanding,
                                five_hour_standing, recommend, weekly_anchor, weekly_standing)
from windowtally.service import run_pass
from windowtally.status_file import status_document
from windowtally_gui.live_model import live_view, tray_view
from windowtally_gui.status_model import snapshot_of

T0 = epoch("2026-10-20T10:00:00Z")


def obs(t, percent, kind="five_hour", resets_at=None, source="plugin"):
    return Observation(source, "ref", t, kind, percent, resets_at, ACCOUNT_A)


class SpentSinceReading:
    """The ledger as the estimate asks it: $2 of priced use since the reading, whatever the span."""

    def cost_between(self, account, start, end):
        return 2.0


class StandingTest(unittest.TestCase):
    def test_a_reading_s_five_hour_reset_time_stays_exact_under_an_estimated_rise(self):
        w = five_hour_standing([obs(T0, 26, resets_at=T0 + 3 * 3600)], [], T0 + 600, rate=1.5,
                               ledger=SpentSinceReading(), account=ACCOUNT_A)
        # 26 % read, plus 1.5 points per dollar for $2 since: an estimated figure beside an exact reset time.
        self.assertEqual((w.percent, w.estimated, w.resets_at, w.reset_exact), (29.0, True, T0 + 3 * 3600, True))

    def test_a_five_hour_reset_time_inferred_from_the_app_s_samples_is_not_exact(self):
        samples = [obs(T0, 0, source="app"), obs(T0 + 900, 5, source="app"), obs(T0 + 1800, 12, source="app")]
        w = five_hour_standing(samples, [T0 + 300], T0 + 2000)
        self.assertEqual((w.resets_at, w.reset_exact), (T0 + 300 + FIVE_HOURS, False))

    def test_a_window_a_later_message_opened_has_an_inferred_reset_time(self):
        end = T0 + 3600
        w = five_hour_standing([obs(T0, 26, resets_at=end)], [end + 100], end + 300)
        self.assertEqual((w.resets_at, w.reset_exact), (end + 100 + FIVE_HOURS, False))

    def test_a_window_with_no_reset_time_is_not_exact(self):
        w = five_hour_standing([obs(T0, 26, resets_at=T0 + 3600)], [T0 - 60], T0 + 7200)
        self.assertEqual((w.state, w.resets_at, w.reset_exact), ("not_started", None, False))

    def test_a_weekly_reset_time_is_exact_as_its_schedule_is(self):
        reading = [obs(T0, 60, kind="seven_day", resets_at=T0 + 86400)]
        self.assertTrue(weekly_standing(reading, weekly_anchor(reading), T0 + 3600).reset_exact)
        sample = [obs(T0, 60, kind="seven_day", source="app")]
        self.assertFalse(weekly_standing(sample, WeeklyAnchor(T0 + 86400, exact=False), T0 + 3600).reset_exact)
        self.assertFalse(weekly_standing(sample, None, T0 + 3600).reset_exact)


class StatusFileTest(unittest.TestCase):
    def test_every_window_says_whether_its_reset_time_was_read(self):
        s = AccountStanding(Account(uuid=ACCOUNT_A, email=EMAIL_A),
                            WindowStanding("five_hour", "running", 29.0, T0 + 3600, T0 - 60, True, reset_exact=True),
                            WindowStanding("seven_day", "current", 60.0, T0 + 86400, T0 - 60, True, reset_exact=False),
                            WeeklyAnchor(T0 + 86400, exact=False), T0 - 30, True, True)
        doc = status_document([s], Recommendation(ACCOUNT_A, "alpha has room left.", None), now=T0,
                              desktop_account=ACCOUNT_A, cli_account=ACCOUNT_A, cli_condition=None)
        entry = doc["accounts"][0]
        self.assertEqual((entry["fiveHour"]["estimated"], entry["fiveHour"]["anchorExact"]), (True, True))
        self.assertEqual((entry["weekly"]["estimated"], entry["weekly"]["anchorExact"]), (True, False))


class LivePathTest(unittest.TestCase):
    """Alpha's desktop session wrote a plugin reading; beta's 5-hour window is known only from the app's samples."""

    def test_a_pass_writes_a_read_reset_time_as_exact_and_an_inferred_one_as_not(self):
        now = epoch("2026-10-20T20:00:00Z")
        m = Machine()
        try:
            m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
            m.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
            m.app_history([(now - 3 * 3600, ORG_B, 30, 70), (now - 2.5 * 3600, ORG_B, 32, 71),
                           (now - 3600, ORG_A, 10, 50)])
            m.sync_events([(now - 7200, "desktop_account", ACCOUNT_A), (now - 7100, "cli_account", ACCOUNT_A)])
            m.watch_view(ACCOUNT_A, ACCOUNT_A)
            m.transcript("desk", [bridge_line("desk", ACCOUNT_A, ORG_A), user_line("desk", "p1", now - 900)]
                         + assistant_lines("d1", now - 890, "desk"))
            m.reading("desk", now - 60, (26, now + 3 * 3600), (60, now + 5 * 86400))
            report = run_pass(m.paths, now, dashboard=False)
            self.assertEqual(report.errors, [])
            doc = json.loads(m.paths.status_file.read_text(encoding="utf-8"))
        finally:
            m.close()
        by_label = {a["label"]: a for a in doc["accounts"]}
        alpha, beta = by_label["alpha"]["fiveHour"], by_label["beta"]["fiveHour"]
        # Alpha's figures are its reading's: read figure, read reset time.
        self.assertEqual((alpha["percent"], alpha["estimated"], alpha["anchorExact"]), (26.0, False, True))
        # Beta's window began with its first sample of the run, three hours ago, and ends five hours after it.
        self.assertEqual((beta["state"], beta["percent"], beta["estimated"], beta["anchorExact"]),
                         ("running", 32.0, True, False))
        self.assertEqual(beta["resetsAt"], "2026-10-20T22:00:00.000Z")


class HistoryPageTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.machine.app_history([(T0 - 3600, ORG_A, 20, 50), (T0 - 1800, ORG_A, 25, 52)])
        self.machine.transcript("s1", [bridge_line("s1", ACCOUNT_A, ORG_A)] + assistant_lines("m1", T0 - 2000, "s1"))
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        self.registry, _ = load_registry(self.machine.paths.accounts_dir)
        ingest_app_history(self.ledger, self.machine.paths.plan_usage_history, by_org(self.registry))
        ingest_transcripts(self.ledger, self.machine.paths.projects_dir)
        attribute(self.ledger)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def page(self, exact: bool) -> str:
        # The weekly window has no reset time, so every "resets" on the card is the 5-hour window's.
        s = AccountStanding(Account(uuid=ACCOUNT_A, email=EMAIL_A),
                            WindowStanding("five_hour", "running", 29.0, T0 + 3600, T0 - 60, True, reset_exact=exact),
                            WindowStanding("seven_day", "current", 40.0, None, T0 - 60, False),
                            None, T0 - 30, True, True)
        return render_dashboard(self.ledger, self.registry, [s], recommend([s]), T0)

    def test_the_card_marks_a_five_hour_reset_time_only_where_it_was_inferred(self):
        exact = self.page(True)
        self.assertIn("≈29%", exact)
        self.assertIn("resets ", exact)
        self.assertNotIn("resets ≈", exact)
        self.assertIn("resets ≈", self.page(False))


def five_hour_document(five_hour: dict) -> dict:
    """status.json at T0 with alpha alone, in use and recommended, its 5-hour window as given."""
    return status_doc([status_account(ACCOUNT_A, EMAIL_A, at=T0, five_hour=five_hour)], at=T0,
                      recommended={"account": ACCOUNT_A, "reason": "alpha has room left.", "reliefAt": None})


def snapshot(doc: dict):
    return snapshot_of(Path("status.json"), json.dumps(doc))


class SurfacesTest(unittest.TestCase):
    """The status command, the window's card and its tray tooltip, from status.json as the service writes it."""

    def test_the_status_command_marks_a_five_hour_reset_time_only_where_it_was_inferred(self):
        def line(exact: bool) -> str:
            doc = five_hour_document(status_window(percent=26.0, resets=T0 + 3600, estimated=True, anchor_exact=exact))
            return next(row for row in format_status(doc).splitlines() if "5-hour" in row)

        self.assertRegex(line(True), r"5-hour : ≈26%, resets [A-Z][a-z]{2} ")
        self.assertIn("5-hour : ≈26%, resets ≈", line(False))

    def test_the_window_s_card_marks_a_five_hour_reset_time_only_where_it_was_inferred(self):
        def row(exact: bool):
            doc = five_hour_document(status_window(resets=T0 + 80 * 60, as_of=T0 - 60, estimated=True,
                                                   anchor_exact=exact))
            return live_view(snapshot(doc), T0).cards[0].five_hour

        exact = row(True)
        self.assertEqual(exact.figure, "≈82%")
        self.assertRegex(exact.detail, r"^resets in 1h 20m \([A-Z][a-z]{2} \d\d:\d\d\)$")
        self.assertRegex(row(False).detail, r"^resets in 1h 20m \(≈[A-Z][a-z]{2} \d\d:\d\d\)$")

    def test_the_tooltip_marks_a_countdown_with_no_figure_only_where_its_reset_time_was_inferred(self):
        def first_line(exact: bool) -> str:
            doc = five_hour_document(status_window(percent=None, resets=T0 + 80 * 60, estimated=True,
                                                   anchor_exact=exact))
            return tray_view(snapshot(doc), T0 + 30).tooltip.split("\n")[0]

        self.assertTrue(first_line(False).startswith("alpha (app, CLI)  5h running ↻≈1h 19m · week "))
        self.assertTrue(first_line(True).startswith("alpha (app, CLI)  5h running ↻1h 19m · week "))


def limited(weekly_percent: float, weekly_reset: float, anchor: WeeklyAnchor | None,
            five_percent: float = 0.0, five_reset: float | None = None, five_exact: bool = False) -> AccountStanding:
    five_state = "running" if five_reset is not None else "not_started"
    return AccountStanding(Account(uuid=ACCOUNT_A, email=EMAIL_A),
                           WindowStanding("five_hour", five_state, five_percent, five_reset, None, True,
                                          reset_exact=five_exact),
                           WindowStanding("seven_day", "current", weekly_percent, weekly_reset, None, False),
                           anchor, None, True, True)


class ReliefTest(unittest.TestCase):
    """With every account at its limit, the moment the first opens is a reset time, marked as the windows are; with
    every account only at or near it, so is the moment room returns."""

    def test_a_five_hour_reset_names_the_first_opening_exactly_only_where_it_was_read(self):
        def reason(exact: bool) -> str:
            rec = recommend([limited(50, T0 + 5 * 86400, None, 99, T0 + 3600, exact)])
            self.assertEqual((rec.account_uuid, rec.relief_at), (None, T0 + 3600))
            return rec.reason

        self.assertRegex(reason(True), r"^Every account is at its limit\. The first opens [A-Z][a-z]{2} \d\d:\d\d\.$")
        self.assertRegex(reason(False), r"^Every account is at its limit\. The first opens ≈[A-Z][a-z]{2} \d\d:\d\d\.$")

    def test_a_weekly_reset_names_it_exactly_only_where_its_schedule_was_read(self):
        reset = T0 + 2 * 86400
        exact = recommend([limited(99, reset, WeeklyAnchor(reset - 7 * 86400, exact=True))]).reason
        inferred = recommend([limited(99, reset, WeeklyAnchor(reset - 7 * 86400, exact=False))]).reason
        self.assertNotIn("≈", exact)
        self.assertIn("The first opens ≈", inferred)

    def test_at_or_near_the_limit_room_returns_at_a_five_hour_reset_exactly_only_where_it_was_read(self):
        def reason(exact: bool) -> str:
            rec = recommend([limited(50, T0 + 5 * 86400, None, 96, T0 + 3600, exact)])
            self.assertEqual((rec.account_uuid, rec.relief_at), (ACCOUNT_A, T0 + 3600))
            return rec.reason

        sentence = r"^Every account is at or near its limit\. alpha has the most left\. Room returns "
        self.assertRegex(reason(True), sentence + r"[A-Z][a-z]{2} \d\d:\d\d\.$")
        self.assertRegex(reason(False), sentence + r"≈[A-Z][a-z]{2} \d\d:\d\d\.$")

    def test_at_or_near_the_limit_room_returns_at_a_weekly_reset_exactly_only_where_its_schedule_was_read(self):
        reset = T0 + 2 * 86400
        exact = recommend([limited(97, reset, WeeklyAnchor(reset - 7 * 86400, exact=True))])
        inferred = recommend([limited(97, reset, WeeklyAnchor(reset - 7 * 86400, exact=False))])
        self.assertEqual((exact.account_uuid, exact.relief_at), (ACCOUNT_A, reset))
        self.assertNotIn("≈", exact.reason)
        self.assertIn("Room returns ≈", inferred.reason)


if __name__ == "__main__":
    unittest.main()
