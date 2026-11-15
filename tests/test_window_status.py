"""The window's reading of status.json and what it shows: version 3 of the contract read as the plugin reads it, the
the marks (≈) and warning levels, the words of every surface, the tray's tooltip and icon state — and the live path
from a real pass to the window's cards."""

import json
import os
import time
import unittest
from pathlib import Path

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bridge_line,
                      epoch, iso, status_account, status_document, status_subscription, status_window, user_line)
from windowtally.service import run_pass
from windowtally_gui import formatting
from windowtally_gui.live_model import (START_GRACE, STALE_AFTER, TOOLTIP_LIMIT, live_view, still_starting,
                                        tray_view)
from windowtally_gui.status_model import StatusReader, snapshot_of

T0 = epoch("2026-10-20T10:00:00Z")   # a Tuesday


def window(state="running", percent=82.0, resets=T0 + 80 * 60, as_of=T0 - 60, estimated=False, exhausts=None,
           anchor_exact=None) -> dict:
    return status_window(state, percent, resets, as_of, estimated, exhausts, anchor_exact)


def subscription(**changes) -> dict:
    return status_subscription(**changes)


def account(uuid=ACCOUNT_A, email=EMAIL_A, desktop=True, cli=True, five_hour=None, weekly=None, plan=None) -> dict:
    return status_account(uuid, email, at=T0, desktop=desktop, cli=cli, five_hour=five_hour, weekly=weekly,
                          plan=plan)


def document(accounts=None, **changes) -> dict:
    """status.json at T0 with alpha in use and recommended, whatever accounts it lists."""
    base = {"desktopAccount": ACCOUNT_A, "cliAccount": ACCOUNT_A,
            "recommended": {"account": ACCOUNT_A, "reason": "alpha has room left.", "reliefAt": None,
                            "reliefExact": False}}
    base.update(changes)
    return status_document(accounts if accounts is not None else [account()], at=T0, **base)


def snapshot(doc: dict):
    return snapshot_of(Path("status.json"), json.dumps(doc))


class FormattingTest(unittest.TestCase):
    def test_spans_and_ages_read_as_the_band_writes_them(self):
        self.assertEqual([formatting.span(s) for s in (30, 49 * 60, 65 * 60, 97 * 3600)], ["<1m", "49m", "1h 05m",
                                                                                          "4d 1h"])
        self.assertEqual((formatting.ago(30), formatting.ago(120)), ("just now", "2m ago"))

    def test_a_percentage_rounds_half_up_as_the_band_does(self):
        self.assertEqual([formatting.percent_text(v) for v in (62.5, 62.4, 0.5)], ["63%", "62%", "1%"])

    def test_days_and_moments_are_named_in_english(self):
        self.assertEqual(formatting.day_text("2026-11-07"), "Sat 7 Nov")
        self.assertEqual(formatting.day_text("not a day"), "not a day")
        local = time.localtime(T0)
        clock = f"{formatting.DAYS[local.tm_wday]} {local.tm_hour:02d}:{local.tm_min:02d}"
        self.assertEqual(formatting.when(T0), clock)
        self.assertEqual(formatting.when(T0, True), clock.replace(" ", f" {local.tm_mday} "
                                                                         f"{formatting.MONTHS[local.tm_mon - 1]} ", 1))


class SnapshotTest(unittest.TestCase):
    def test_version_3_reads_and_another_version_is_never_guessed_at(self):
        self.assertEqual(snapshot(document()).kind, "ok")
        for version in (1, 2):
            other = snapshot(dict(document(), v=version))
            self.assertEqual((other.kind, other.problem), ("unknown-version", str(version)))

    def test_what_is_not_the_version_3_shape_is_said(self):
        self.assertEqual(snapshot_of(Path("s"), "{").kind, "unreadable")
        broken = snapshot(document(accounts=[{"label": "no uuid"}]))
        self.assertEqual(broken.kind, "unreadable")
        self.assertIn("not in the version-3 shape", broken.problem)
        missing = snapshot(dict(document(), accounts=None))
        self.assertIn("no accounts list", missing.problem)

    def test_the_file_is_read_again_only_when_it_changes(self):
        machine = Machine()
        try:
            path = machine.paths.status_file
            reader = StatusReader(path)
            self.assertEqual(reader.poll().kind, "missing")
            self.assertIsNone(reader.poll())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document()), encoding="utf-8")
            self.assertEqual(reader.poll().kind, "ok")
            self.assertIsNone(reader.poll(), "unchanged: not read again")
            path.write_text(json.dumps(document(cliCondition="a CLI is running")), encoding="utf-8")
            os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000_000))
            self.assertEqual(reader.poll().status.cli_condition, "a CLI is running")
            path.unlink()
            self.assertEqual(reader.poll().kind, "missing")
        finally:
            machine.close()

    def test_a_file_that_reads_but_breaks_the_contract_is_not_read_again_until_it_changes(self):
        machine = Machine()
        try:
            path = machine.paths.status_file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document(accounts=[{"label": "no uuid"}])), encoding="utf-8")
            reader = StatusReader(path)
            self.assertEqual(reader.poll().kind, "unreadable")
            self.assertIsNone(reader.poll(), "a broken file stays as it was read: no reading on a timer")
            path.write_text(json.dumps(document()), encoding="utf-8")
            os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000_000))
            self.assertEqual(reader.poll().kind, "ok")
        finally:
            machine.close()


class LiveViewTest(unittest.TestCase):
    def view(self, doc: dict, now: float = T0 + 30):
        return live_view(snapshot(doc), now)

    def test_a_5_hour_reset_time_is_marked_with_its_estimated_figure(self):
        five = self.view(document(accounts=[account(five_hour=window(estimated=True))])).cards[0].five_hour
        self.assertEqual(five.figure, "≈82%")
        self.assertRegex(five.detail, r"^resets in 1h 19m \(≈[A-Z][a-z]{2} \d\d:\d\d\)$")

    def test_a_weekly_reset_time_is_marked_only_when_its_schedule_was_inferred(self):
        exact = window("current", 69.0, T0 + 3 * 86400, estimated=True, anchor_exact=True)
        card = self.view(document(accounts=[account(weekly=exact)])).cards[0]
        self.assertEqual(card.weekly.figure, "≈69%")
        self.assertNotIn("≈", card.weekly.detail)
        inferred = window("current", 69.0, T0 + 3 * 86400, estimated=True, anchor_exact=False)
        card = self.view(document(accounts=[account(weekly=inferred)])).cards[0]
        self.assertIn("resets ≈", card.weekly.detail)
        self.assertNotIn("inferred", card.weekly.note, "≈ says it; no words repeat it")

    def test_levels_follow_each_window_s_warning_figures(self):
        def levels(five: float, week: float):
            card = self.view(document(accounts=[account(five_hour=window(percent=five),
                                                        weekly=window("current", week, T0 + 86400,
                                                                      anchor_exact=True))])).cards[0]
            return card.five_hour.level, card.weekly.level

        self.assertEqual(levels(79, 69), (0, 0))
        self.assertEqual(levels(80, 70), (1, 1))
        self.assertEqual(levels(95, 90), (2, 2))

    def test_a_window_not_started_and_one_never_read(self):
        idle = window("not_started", 0.0, None)
        unread = window("unknown", None, None, as_of=None)
        card = self.view(document(accounts=[account(five_hour=idle, weekly=unread)])).cards[0]
        self.assertEqual((card.five_hour.figure, card.five_hour.detail, card.five_hour.note), ("not started", "", ""),
                         "a window not started says nothing under its name")
        self.assertEqual((card.weekly.figure, card.weekly.detail, card.weekly.note),
                         ("unknown", "reset time unknown", "no reading yet"))
        no_schedule = window("current", 12.0, None, anchor_exact=False)
        card = self.view(document(accounts=[account(weekly=no_schedule)])).cards[0]
        self.assertEqual(card.weekly.detail, "reset time unknown")
        self.assertNotIn("inferred", card.weekly.note, "no reset time, so none was inferred")

    def test_the_pace_and_the_reading_beneath_a_window(self):
        card = self.view(document(accounts=[account(five_hour=window(exhausts=T0 + 3600))]), now=T0 + 120).cards[0]
        self.assertRegex(card.five_hour.note, r"^full at this pace ≈[A-Z][a-z]{2} \d\d:\d\d$")
        self.assertEqual((card.heading, card.weekly.note), ("last response 12m ago", ""),
                         "a reading taken since the last response and minutes old: its age is said nowhere")
        before = T0 - 900   # the account's last response, 10 minutes before T0, came after a reading taken then
        week = window("current", 69.0, T0 + 3 * 86400, as_of=before, anchor_exact=True)
        one = account(five_hour=window(exhausts=T0 + 3600, as_of=before), weekly=week)
        card = self.view(document(accounts=[one]), now=T0 + 120).cards[0]
        self.assertRegex(card.five_hour.note, r"^full at this pace ≈[A-Z][a-z]{2} \d\d:\d\d$")
        self.assertTrue(card.heading.endswith(" · read 17m ago"), "both windows rest on one reading: said once")
        self.assertEqual(card.weekly.note, "")
        differing = account(five_hour=window(exhausts=T0 + 3600, as_of=before))
        card = self.view(document(accounts=[differing]), now=T0 + 120).cards[0]
        self.assertRegex(card.five_hour.note, r"^full at this pace ≈[A-Z][a-z]{2} \d\d:\d\d · read 17m ago$")
        self.assertEqual(card.weekly.note, "", "the weekly reading, taken since the last response, says no age")
        self.assertNotIn("read ", card.heading)
        both = account(five_hour=window(exhausts=T0 + 3600, as_of=before),
                       weekly=window("current", 69.0, T0 + 3 * 86400, as_of=before - 300, anchor_exact=True))
        card = self.view(document(accounts=[both]), now=T0 + 120).cards[0]
        self.assertRegex(card.five_hour.note, r"^full at this pace ≈[A-Z][a-z]{2} \d\d:\d\d · read 17m ago$")
        self.assertEqual(card.weekly.note, "read 22m ago")
        self.assertNotIn("read ", card.heading)

    def test_the_plan_line_by_the_bills(self):
        def plan(**changes):
            return self.view(document(accounts=[account(plan=subscription(**changes))])).cards[0]

        card = plan()
        self.assertEqual(card.plan.text, "Ultra · paid until Sat 7 Nov", "18 days off: the date alone")
        self.assertEqual((card.plan.tone, card.plan.note), ("normal", ""), "no cost this month on a card")
        self.assertEqual(plan(daysLeft=8).plan.text, "Ultra · paid until Sat 7 Nov")
        self.assertEqual(plan(daysLeft=7).plan.text, "Ultra · paid until Sat 7 Nov (7 days left)",
                         "within a week of the renewal the days left are said")
        card = plan(renewSoon=True, daysLeft=2, profileCheck="differs", profilePlan="max5x")
        self.assertEqual((card.plan.tone, card.renew_tag), ("warning", "renew in 2 days"))
        self.assertIn("the profile names Max 5x", card.plan.note)
        self.assertEqual(plan(renewSoon=True, daysLeft=0).renew_tag, "renew today")
        self.assertEqual(plan(state="ended", paidUntil="2026-10-01").plan.text, "ended Thu 1 Oct")
        self.assertEqual(plan(state="none", thisMonthListPrice=0.0).plan.tone, "muted")
        self.assertIsNone(self.view(document()).cards[0].plan)

    def test_the_roles_an_account_holds(self):
        other = account(ACCOUNT_B, EMAIL_B, desktop=False, cli=False)
        doc = document(accounts=[account(cli=False), other],
                       recommended={"account": ACCOUNT_B, "reason": "beta has room left.", "reliefAt": None})
        alpha, beta = self.view(doc).cards
        self.assertEqual((alpha.tags, beta.tags), (("desktop app",), ("use next",)))
        self.assertEqual(alpha.heading, "last response 10m ago", "a name its e-mail gives: no e-mail")
        named = document(accounts=[dict(account(cli=False), label="Work"), other])
        self.assertEqual(self.view(named).cards[0].heading, "alpha@example.com · last response 10m ago")

    def test_the_header_says_a_stale_status_and_every_account_at_its_limit(self):
        header = self.view(document(), now=T0 + 30).header
        self.assertFalse(header.stale)
        self.assertEqual(header.in_use_line, "the CLI follows the app", "alpha's card names both clients on its chips")
        header = self.view(document(), now=T0 + STALE_AFTER + 1).header
        self.assertTrue(header.stale)
        self.assertIn("the service may not be running", header.status_line)
        opens = formatting.when(T0 + 7200)
        blocked = document(recommended={"account": None,
                                        "reason": f"Every account is at its limit. The first opens {opens}.",
                                        "reliefAt": iso(T0 + 7200), "reliefExact": True})
        header = self.view(blocked).header
        self.assertTrue(header.all_blocked)
        self.assertEqual(header.next_line, f"Next: Every account is at its limit. The first opens {opens} (in 1h 59m).")

    def test_with_every_account_at_or_near_its_limit_the_header_names_one_and_no_block(self):
        returns = formatting.when(T0 + 7200)
        near = document(recommended={"account": ACCOUNT_A,
                                     "reason": "Every account is at or near its limit. alpha has the most left. "
                                               f"Room returns {returns}.",
                                     "reliefAt": iso(T0 + 7200), "reliefExact": True})
        header = self.view(near).header
        self.assertFalse(header.all_blocked)
        self.assertEqual(header.next_line, "Next: Every account is at or near its limit. alpha has the most left. "
                                           f"Room returns {returns} (in 1h 59m).")
        tray = tray_view(snapshot(near), T0 + 30)
        self.assertEqual(tray.level, 1)
        self.assertIn("Next: alpha, all at or near the limit", tray.tooltip.split("\n"))

    def test_without_standings_the_window_says_why(self):
        self.assertEqual(live_view(None, T0).problem, "Reading WindowTally's status…")
        missing = live_view(snapshot_of(Path("x"), "{"), T0)
        self.assertTrue(missing.problem.startswith("The status file cannot be read: it is not JSON"))
        self.assertEqual(live_view(snapshot(document(accounts=[])), T0).problem, "No account is known yet.")
        self.assertIn("version 2, which this window does not read",
                      live_view(snapshot(dict(document(), v=2)), T0).problem)


class TrayViewTest(unittest.TestCase):
    def test_the_tooltip_puts_the_account_in_use_first_and_fits_windows(self):
        other = account(ACCOUNT_B, EMAIL_B, desktop=False, cli=False,
                        five_hour=window("not_started", 0.0, None), weekly=window("current", 12.0, None))
        doc = document(accounts=[account(), other])   # the service's order: the account in use first
        view = tray_view(snapshot(doc), T0 + 30)
        lines = view.tooltip.split("\n")
        self.assertEqual(lines[0], f"alpha (app, CLI)  5h 82% ↻1h 19m · week 69% ↻{formatting.when(T0 + 3 * 86400)}")
        self.assertEqual(lines[1], "Next: alpha", "the accounts in use, then Next:, then the others")
        self.assertEqual(lines[2], "beta  5h not started · week 12%")
        many = document(accounts=[account(f"{i:08d}-0000-4000-8000-000000000000", f"account{i}@example.com",
                                          desktop=i == 0, cli=False) for i in range(6)])
        self.assertLessEqual(len(tray_view(snapshot(many), T0 + 30).tooltip), TOOLTIP_LIMIT)

    def test_the_icon_shows_the_account_in_use_and_greys_without_a_fresh_status(self):
        view = tray_view(snapshot(document()), T0 + 30)
        self.assertEqual((view.level, view.account), (1, ACCOUNT_A))
        self.assertAlmostEqual(view.five_hour, 0.82)
        stale = tray_view(snapshot(document()), T0 + STALE_AFTER + 1)
        self.assertEqual(stale.level, -1)
        self.assertTrue(stale.tooltip.startswith("Status 5m old: is the service running?"))
        blocked = document(recommended={"account": None, "reason": "Every account is at its limit.",
                                        "reliefAt": iso(T0 + 600)})
        self.assertEqual(tray_view(snapshot(blocked), T0 + 30).level, 2)
        self.assertEqual(tray_view(None, T0).level, -1)

    def test_each_ring_takes_its_own_window_s_level(self):
        view = tray_view(snapshot(document()), T0 + 30)
        self.assertEqual((view.five_hour_level, view.weekly_level), (1, 0), "the 5-hour window at 82 %, the week at 69 %")
        weekly_error = account(five_hour=window(percent=20.0), weekly=window("current", 93.0, None))
        view = tray_view(snapshot(document(accounts=[weekly_error])), T0 + 30)
        self.assertEqual((view.five_hour_level, view.weekly_level, view.level), (0, 2, 2))
        self.assertAlmostEqual(view.weekly, 0.93)

    def test_while_every_account_is_at_its_limit_both_rings_take_an_error_s_level(self):
        blocked = document(accounts=[account(five_hour=window(percent=20.0), weekly=window("current", 30.0, None))],
                           recommended={"account": None, "reason": "Every account is at its limit.",
                                        "reliefAt": iso(T0 + 600)})
        view = tray_view(snapshot(blocked), T0 + 30)
        self.assertEqual((view.five_hour_level, view.weekly_level, view.level), (2, 2, 2))
        self.assertAlmostEqual(view.five_hour, 0.20, msg="the rings still fill as far as each window is used")


class DesktopNotRunningTest(unittest.TestCase):
    """A desktop app the status reports not running, as PROJECT.md has the window and the tray say it, and the
    start the window shows until a status answers it."""

    closed = document(desktopRunning=False)

    def test_the_status_reads_the_key_as_the_contract_says(self):
        self.assertFalse(snapshot(self.closed).status.desktop_running)
        self.assertTrue(snapshot(document()).status.desktop_running, "absent: it runs, or that is not known")

    def test_the_header_says_it_and_offers_the_start(self):
        header = live_view(snapshot(self.closed), T0 + 30).header
        self.assertEqual(header.in_use_line, "Desktop app: alpha (not running) · CLI: alpha · the CLI follows the app")
        self.assertTrue(header.not_running)
        running = live_view(snapshot(document()), T0 + 30).header
        self.assertEqual(running.in_use_line, "the CLI follows the app", "running, the cards' chips name the clients")
        self.assertFalse(running.not_running)
        at_sign_in = document(desktopAccount=None, desktopSignedIn=False, desktopRunning=False)
        self.assertTrue(live_view(snapshot(at_sign_in), T0 + 30).header.in_use_line.startswith(
            "Desktop app: at its sign-in page (not running) · "))

    def test_a_start_the_window_made_withholds_it(self):
        header = live_view(snapshot(self.closed), T0 + 30, starting=True).header
        self.assertEqual(header.in_use_line, "the CLI follows the app", "as while the app runs: no word of the clients")
        self.assertFalse(header.not_running)
        tray = tray_view(snapshot(self.closed), T0 + 30, starting=True)
        self.assertFalse(tray.can_start)
        self.assertFalse(tray.tooltip.startswith("Desktop app not running"))

    def test_the_tooltip_says_it_first_and_the_tray_offers_the_start(self):
        view = tray_view(snapshot(self.closed), T0 + 30)
        self.assertEqual(view.tooltip.split("\n")[:2],
                         ["Desktop app not running",
                          f"alpha (app, CLI)  5h 82% ↻1h 19m · week 69% ↻{formatting.when(T0 + 3 * 86400)}"])
        self.assertTrue(view.can_start)
        self.assertEqual((view.level, view.account), (1, ACCOUNT_A), "the icon is unchanged")
        running = tray_view(snapshot(document()), T0 + 30)
        self.assertFalse(running.can_start)
        self.assertTrue(tray_view(snapshot(self.closed), T0 + STALE_AFTER + 1).tooltip.startswith(
            "Desktop app not running\nStatus 5m old"))

    def test_a_start_stands_until_a_status_says_the_app_runs_or_one_written_late_enough_says_it_does_not(self):
        started = T0 + 100
        closed_at = lambda at: snapshot(document(desktopRunning=False, generatedAt=iso(at))).status
        running_at = lambda at: snapshot(document(generatedAt=iso(at))).status
        self.assertFalse(still_starting(closed_at(T0), None, started + 1), "no start, nothing stands")
        self.assertTrue(still_starting(None, started, started + 1), "no status read yet")
        self.assertTrue(still_starting(closed_at(T0), started, started + 1), "the status from before the start")
        self.assertTrue(still_starting(closed_at(started + START_GRACE - 1), started, started + 30),
                        "a status too soon after the start for the watcher to have looked")
        self.assertFalse(still_starting(closed_at(started + START_GRACE), started, started + 30),
                         "a status late enough says the start came to nothing")
        self.assertFalse(still_starting(running_at(started + 5), started, started + 6), "the app runs")
        self.assertFalse(still_starting(closed_at(T0), started, started + STALE_AFTER + 1),
                         "no answer at all lets the start go after a stale status's time")


class LivePathTest(unittest.TestCase):
    """A real pass on a synthetic machine, then the window's reading of what it wrote."""

    def test_the_cards_show_what_the_pass_wrote(self):
        machine = Machine()
        try:
            now = time.time()
            machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
            machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
            machine.app_history([(now - 86400, ORG_B, 40, 72)])
            # The app switched to alpha an hour ago, which the watcher's view, written now, still names.
            machine.sync_events([(now - 3600, "desktop_account", ACCOUNT_A)])
            machine.watch_view(ACCOUNT_A, ACCOUNT_A, at=now)
            machine.transcript("desk", [bridge_line("desk", ACCOUNT_A, ORG_A), user_line("desk", "p1", now - 900)]
                               + assistant_lines("d1", now - 890, "desk"))
            machine.reading("desk", now - 60, (26, now + 3 * 3600), (60, now + 5 * 86400))
            self.assertEqual(run_pass(machine.paths, dashboard=False).errors, [])
            view = live_view(StatusReader(machine.paths.status_file).poll(), time.time())
            cards = {card.label: card for card in view.cards}
            self.assertEqual((cards["alpha"].five_hour.figure, cards["alpha"].weekly.figure), ("26%", "60%"))
            self.assertIn("desktop app", cards["alpha"].tags)
            self.assertEqual(cards["beta"].five_hour.figure, "not started")
            self.assertFalse(view.header.stale)
            self.assertIsNone(view.problem)
        finally:
            machine.close()

    def test_an_app_left_at_its_sign_in_page_offers_the_switch_back_on_the_account_it_left(self):
        machine = Machine()
        try:
            now = time.time()
            machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
            machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
            (machine.paths.accounts_dir / ACCOUNT_A / "desktop-login.dpapi").write_bytes(b"a stored login")
            machine.sync_events([(now - 3600, "desktop_account", ACCOUNT_A), (now - 3590, "cli_account", ACCOUNT_A),
                                 (now - 60, "desktop_signed_out", ACCOUNT_A)])
            machine.watch_view(ACCOUNT_A, ACCOUNT_A, at=now - 120)   # written before the add, never looked again
            self.assertEqual(run_pass(machine.paths, dashboard=False).errors, [])
            view = live_view(StatusReader(machine.paths.status_file).poll(), time.time())
            self.assertEqual(view.header.in_use_line,
                             "Desktop app: at its sign-in page · CLI: alpha · the CLI follows the app")
            cards = {card.label: card for card in view.cards}
            self.assertEqual([b.text for b in cards["alpha"].switches], ["Switch here"])
            self.assertNotIn("desktop app", cards["alpha"].tags)
            self.assertIn("CLI", cards["alpha"].tags)
        finally:
            machine.close()


if __name__ == "__main__":
    unittest.main()
