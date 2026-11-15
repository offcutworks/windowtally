"""Accounts the user hides, and accounts whose plan has ended: the setting that holds the hidden ones, the
recommendation that weighs neither, status.json's mark, the command line's status, and the window, whose every list
leaves a hidden account out while its Arrange accounts window shows it again.

Expected values follow the rules: an account the user hid is left out of every live list while neither client uses
it, the history keeps it, and the recommendation weighs no account the user hid nor one whose bills record a plan that
has ended — such an account takes no readings, so its weekly figure, rolled forward through its resets, stands at
nothing. For the same reason the tray's tooltip writes ``plan ended`` in place of the windows of an account whose plan
has ended and that neither client uses."""

import contextlib
import io
import json
import unittest
from pathlib import Path

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, bill, epoch, status_account,
                      status_document, status_subscription, status_window)
from windowtally.__main__ import main
from windowtally.accounts import Account
from windowtally.limits import AccountStanding, WindowStanding, recommend
from windowtally.service import run_pass
from windowtally.settings import (SettingsError, edit_account_arrangement, load_settings, set_account_arrangement,
                                  set_notifications_silenced)
from windowtally_gui import actions_model, switch_model
from windowtally_gui.arrange_model import Arrangement
from windowtally_gui.live_model import live_view, tray_view
from windowtally_gui.notices_model import Notices
from windowtally_gui.state_model import WindowState
from windowtally_gui.status_model import snapshot_of
from windowtally_gui.switch_model import APP, CLI, Switches

NOW = epoch("2026-10-20T20:00:00Z")   # the time the fixtures' watcher view is written at
ACCOUNT_C = "cccccccc-0000-4000-8000-000000000003"
ACCOUNT_D = "dddddddd-0000-4000-8000-000000000004"
ORG_C = "0c0c0c0c-0000-4000-8000-00000000000c"
ORG_D = "0d0d0d0d-0000-4000-8000-00000000000d"
EMAIL_C = "gamma@example.com"
EMAIL_D = "delta@example.com"
UNLISTED = "eeeeeeee-0000-4000-8000-000000000005"   # hidden in the settings, listed by no status


def standing(label: str, weekly_percent: float | None, weekly_reset: float | None,
             five_percent: float = 0.0) -> AccountStanding:
    """An account idle in its 5-hour window, at ``weekly_percent`` of a week that resets at ``weekly_reset``."""
    five = (WindowStanding("five_hour", "running", five_percent, NOW + 3600, None, False) if five_percent
            else WindowStanding("five_hour", "not_started", 0.0, None, None, False))
    return AccountStanding(Account(uuid=label, email=f"{label}@example.com"), five,
                           WindowStanding("seven_day", "current", weekly_percent, weekly_reset, None, False),
                           None, None, False, False)


class HiddenSettingTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.path = self.machine.paths.settings_file

    def tearDown(self):
        self.machine.close()

    def test_the_hidden_accounts_are_read_by_uuid_in_lower_case_and_absent_hide_nothing(self):
        self.machine.settings({"v": 1, "hiddenAccounts": [ACCOUNT_B.upper(), ACCOUNT_A]})
        settings = load_settings(self.path)
        self.assertEqual(settings.hidden_accounts, (ACCOUNT_B, ACCOUNT_A))
        self.assertEqual(settings.hidden, frozenset({ACCOUNT_A, ACCOUNT_B}))
        self.machine.settings({"v": 1})
        self.assertEqual(load_settings(self.path).hidden, frozenset())

    def test_a_file_with_a_bad_list_of_hidden_accounts_is_refused_whole_every_problem_named(self):
        self.machine.settings({"v": 1, "hiddenAccounts": [ACCOUNT_A, "not-a-uuid", ACCOUNT_A.upper(), 7]})
        with self.assertRaises(SettingsError) as raised:
            load_settings(self.path)
        words = str(raised.exception)
        for expected in ("hiddenAccounts entry 2 is not an account UUID", f"hiddenAccounts entry 3 repeats {ACCOUNT_A}",
                         "hiddenAccounts entry 4 is not an account UUID"):
            self.assertIn(expected, words)
        self.machine.settings({"v": 1, "hiddenAccounts": {}})
        with self.assertRaises(SettingsError) as raised:
            load_settings(self.path)
        self.assertIn("hiddenAccounts is not a list", str(raised.exception))

    def test_the_hidden_accounts_are_written_with_the_arrangement_and_kept_by_every_other_setter(self):
        self.machine.settings({"v": 1, "silenceNotifications": True})
        set_account_arrangement(self.path, [], {ACCOUNT_A: "Work"}, [ACCOUNT_B])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")),
                         {"v": 1, "silenceNotifications": True, "accountNames": {ACCOUNT_A: "Work"},
                          "hiddenAccounts": [ACCOUNT_B]})
        set_notifications_silenced(self.path, False)
        self.assertEqual(load_settings(self.path).hidden_accounts, (ACCOUNT_B,), "another setter keeps them")
        set_account_arrangement(self.path, [ACCOUNT_A], {})
        self.assertEqual(load_settings(self.path).hidden_accounts, (ACCOUNT_B,),
                         "an arrangement given no hidden accounts leaves them as the file holds them")
        set_account_arrangement(self.path, [], {}, [])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"v": 1},
                         "none hidden is written as nothing")

    def test_an_edit_gives_the_hidden_accounts_third_or_leaves_them_as_they_stand(self):
        self.machine.settings({"v": 1, "hiddenAccounts": [ACCOUNT_A]})
        written = edit_account_arrangement(self.path, lambda current: ((), {}))
        self.assertEqual(written.hidden_accounts, (ACCOUNT_A,))
        written = edit_account_arrangement(self.path, lambda current: ((), {}, (*current.hidden_accounts, ACCOUNT_B)))
        self.assertEqual(written.hidden_accounts, (ACCOUNT_A, ACCOUNT_B))
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaises(ValueError) as raised:
            edit_account_arrangement(self.path, lambda current: ((), {}, [ACCOUNT_A, ACCOUNT_A]))
        self.assertIn("hiddenAccounts entry 2 repeats", str(raised.exception))
        self.assertEqual(self.path.read_text(encoding="utf-8"), before, "what the contract refuses is not written")


class RecommendationTest(unittest.TestCase):
    def test_an_excluded_account_is_not_recommended_though_its_week_resets_first(self):
        accounts = [standing("ended", 0.0, NOW + 86400), standing("live", 40.0, NOW + 3 * 86400)]
        self.assertEqual(recommend(accounts).account_uuid, "ended", "weighed, its empty week wins")
        rec = recommend(accounts, {"ended"})
        self.assertEqual(rec.account_uuid, "live")
        self.assertTrue(rec.reason.startswith("live — room left"), rec.reason)

    def test_an_excluded_account_neither_counts_as_room_nor_is_waited_on(self):
        accounts = [standing("ended", 0.0, NOW + 3600), standing("live", 99.5, NOW + 2 * 86400)]
        rec = recommend(accounts, {"ended"})
        self.assertEqual((rec.account_uuid, rec.relief_at), (None, NOW + 2 * 86400),
                         "every weighed account is at its limit; the first to open is the live one")
        self.assertTrue(rec.reason.startswith("Every account is at its limit. The first opens"), rec.reason)

    def test_with_every_account_excluded_none_is_recommended_and_nothing_is_waited_on(self):
        rec = recommend([standing("ended", 0.0, NOW + 3600), standing("hidden", 20.0, NOW + 7200)],
                        {"ended", "hidden"})
        self.assertEqual((rec.account_uuid, rec.relief_at), (None, None))
        self.assertEqual(rec.reason, "No account is left to recommend: every account is hidden or its plan has ended.")
        self.assertEqual(recommend([]).reason, "No account is known yet.")


class PassTest(unittest.TestCase):
    """Four accounts with no reading yet: gamma on the desktop app, beta on the CLI, alpha and delta idle. With no
    figure, each has room left and none resets first, so the recommendation takes the first by name: alpha."""

    def setUp(self):
        self.machine = Machine()
        m = self.machine
        for uuid, email, org in ((ACCOUNT_A, EMAIL_A, ORG_A), (ACCOUNT_B, EMAIL_B, ORG_B), (ACCOUNT_C, EMAIL_C, ORG_C),
                                 (ACCOUNT_D, EMAIL_D, ORG_D)):
            m.add_account(uuid, email, org)
        m.watch_view(ACCOUNT_C, ACCOUNT_B)

    def tearDown(self):
        self.machine.close()

    def status(self) -> dict:
        run_pass(self.machine.paths, NOW, dashboard=True)
        return json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))

    def test_with_nothing_hidden_and_no_bills_no_account_is_marked_and_alpha_is_recommended(self):
        doc = self.status()
        self.assertFalse(any("hidden" in a for a in doc["accounts"]))
        self.assertEqual(doc["recommended"]["account"], ACCOUNT_A)

    def test_an_idle_account_the_user_hid_is_marked_and_not_recommended_and_the_history_keeps_it(self):
        self.machine.settings({"v": 1, "hiddenAccounts": [ACCOUNT_A, UNLISTED]})
        doc = self.status()
        marked = [a["uuid"] for a in doc["accounts"] if a.get("hidden") is True]
        self.assertEqual(marked, [ACCOUNT_A])
        self.assertEqual(len(doc["accounts"]), 4, "status.json still lists it, for the window to show it again")
        self.assertEqual(doc["recommended"]["account"], ACCOUNT_B, "the next by name, alpha weighed not at all")
        self.assertEqual(doc["sourceErrors"], [])
        self.assertIn("alpha", self.machine.paths.dashboard_file.read_text(encoding="utf-8"))

    def test_an_account_the_user_hid_that_a_client_uses_is_listed_but_never_recommended(self):
        self.machine.settings({"v": 1, "hiddenAccounts": [ACCOUNT_B, ACCOUNT_C, ACCOUNT_A]})
        doc = self.status()
        self.assertEqual([a["uuid"] for a in doc["accounts"] if a.get("hidden") is True], [ACCOUNT_A])
        self.assertEqual(doc["recommended"]["account"], ACCOUNT_D)

    def test_an_account_whose_bills_record_a_plan_that_has_ended_is_listed_but_not_recommended(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-09-01", 200, plan="ultra", period="2026-09-01..2026-10-01"),
                                 bill(EMAIL_B, "2026-10-01", 200, plan="ultra", period="2026-10-01..2026-11-01")])
        doc = self.status()
        alpha = next(a for a in doc["accounts"] if a["uuid"] == ACCOUNT_A)
        self.assertEqual(alpha["subscription"]["state"], "ended")
        self.assertNotIn("hidden", alpha, "an ended plan hides nothing: hiding is the user's")
        self.assertEqual(doc["recommended"]["account"], ACCOUNT_B,
                         "delta and gamma, whose bills say nothing, stay weighed; beta comes first by name")

    def test_with_every_account_hidden_or_ended_none_is_recommended(self):
        self.machine.bills_file([bill(EMAIL_A, "2026-09-01", 200, plan="ultra", period="2026-09-01..2026-10-01")])
        self.machine.settings({"v": 1, "hiddenAccounts": [ACCOUNT_B, ACCOUNT_C, ACCOUNT_D]})
        doc = self.status()
        self.assertEqual((doc["recommended"]["account"], doc["recommended"]["reliefAt"]), (None, None))
        self.assertTrue(doc["recommended"]["reason"].startswith("No account is left to recommend"))

    def test_settings_that_cannot_be_read_hide_nothing_and_are_said(self):
        self.machine.settings({"v": 1, "hiddenAccounts": [ACCOUNT_A, "x"]})
        doc = self.status()
        self.assertFalse(any("hidden" in a for a in doc["accounts"]))
        self.assertEqual(doc["recommended"]["account"], ACCOUNT_A)
        self.assertTrue(any(e.startswith("settings: ") for e in doc["sourceErrors"]), doc["sourceErrors"])

    def test_the_status_command_lists_every_account_and_marks_a_hidden_one(self):
        self.machine.settings({"v": 1, "hiddenAccounts": [ACCOUNT_A]})
        run_pass(self.machine.paths, NOW, dashboard=False)
        p = self.machine.paths
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            main(["--claude-home", str(p.claude_home), "--desktop-data", str(p.desktop_data),
                  "--data-dir", str(p.data_dir), "status"])
        lines = out.getvalue().splitlines()
        self.assertIn("alpha  [hidden]", lines)
        self.assertIn("delta", lines)


def snapshot(accounts: list[dict], **changes):
    return snapshot_of(Path("status.json"), json.dumps(status_document(accounts, at=NOW, **changes)))


def hidden(account: dict) -> dict:
    return account | {"hidden": True}


def four(**changes):
    """gamma in use by the app and the CLI; then beta, then alpha, which the user hid, then delta; beta recommended."""
    accounts = [status_account(ACCOUNT_C, EMAIL_C, at=NOW),
                status_account(ACCOUNT_B, EMAIL_B, at=NOW, desktop=False, cli=False),
                hidden(status_account(ACCOUNT_A, EMAIL_A, at=NOW, desktop=False, cli=False,
                                      plan=status_subscription(renewSoon=True, daysLeft=2))),
                status_account(ACCOUNT_D, EMAIL_D, at=NOW, desktop=False, cli=False)]
    base = {"recommended": {"account": ACCOUNT_B, "reason": "beta has room left.", "reliefAt": None,
                            "reliefExact": False}, "oneClickDesktop": True, "renewalReminderDays": 3}
    base.update(changes)
    return snapshot(accounts, **base)


class WindowTest(unittest.TestCase):
    def test_the_window_reads_the_mark_and_keeps_every_account_to_find_by_uuid(self):
        status = four().status
        self.assertEqual([a.uuid for a in status.listed], [ACCOUNT_C, ACCOUNT_B, ACCOUNT_D])
        self.assertTrue(status.account(ACCOUNT_A).hidden)
        self.assertEqual(len(status.accounts), 4)

    def test_the_cards_leave_a_hidden_account_out_and_the_header_counts_it(self):
        view = live_view(four(), NOW + 30)
        self.assertEqual([c.uuid for c in view.cards], [ACCOUNT_C, ACCOUNT_B, ACCOUNT_D])
        self.assertTrue(view.header.in_use_line.endswith(" · 1 account hidden"), view.header.in_use_line)
        self.assertNotIn("hidden", live_view(snapshot([status_account(ACCOUNT_C, EMAIL_C, at=NOW)]),
                                             NOW + 30).header.in_use_line)

    def test_the_tooltip_and_the_switch_menus_leave_a_hidden_account_out(self):
        short = {"five_hour": status_window("not_started", 0.0, None), "weekly": status_window("current", 12.0, None)}
        accounts = [status_account(ACCOUNT_C, EMAIL_C, at=NOW, **short),
                    status_account(ACCOUNT_B, EMAIL_B, at=NOW, desktop=False, cli=False, **short),
                    hidden(status_account(ACCOUNT_A, EMAIL_A, at=NOW, desktop=False, cli=False, **short)),
                    status_account(ACCOUNT_D, EMAIL_D, at=NOW, desktop=False, cli=False, **short)]
        recommended = {"account": ACCOUNT_B, "reason": "beta has room left.", "reliefAt": None, "reliefExact": False}
        lines = tray_view(snapshot(accounts, recommended=recommended), NOW + 30).tooltip.split("\n")
        self.assertEqual([line.split("  ")[0] for line in lines], ["gamma (app, CLI)", "Next: beta", "beta", "delta"],
                         "lines short enough that nothing is cut for length")
        self.assertNotIn("alpha", tray_view(four(), NOW + 30).tooltip)
        apart = Switches(follows=False, one_click=True)
        for client in (APP, CLI):
            self.assertEqual([e.uuid for e in switch_model.switch_entries(four().status, client, apart)],
                             [ACCOUNT_B, ACCOUNT_D])

    def test_with_none_left_to_recommend_the_tooltip_says_so_rather_than_that_all_are_at_their_limit(self):
        one = [status_account(ACCOUNT_C, EMAIL_C, at=NOW, plan=status_subscription(state="ended", plan=None))]
        none = snapshot(one, recommended={"account": None, "reliefAt": None, "reliefExact": False,
                                          "reason": "No account is left to recommend: every account is hidden or its "
                                                    "plan has ended."})
        self.assertTrue(tray_view(none, NOW + 30).tooltip.split("\n")[-1].startswith("No account is left to recommend"),
                        "the tooltip's length cuts the rest")
        blocked = snapshot(one, recommended={"account": None, "reliefAt": None, "reliefExact": False,
                                             "reason": "Every account is at its limit."})
        self.assertEqual(tray_view(blocked, NOW + 30).tooltip.split("\n")[-1], "Every account is at its limit")

    def test_the_tooltip_leaves_out_an_ended_plan_no_client_uses(self):
        ended = status_subscription(state="ended", plan=None, planName=None, paidUntil="2026-09-10", daysLeft=None)
        upcoming = status_subscription(state="upcoming", plan=None, planName=None, paidUntil="2026-10-25",
                                       daysLeft=None)
        lines = tray_view(snapshot([status_account(ACCOUNT_C, EMAIL_C, at=NOW, plan=ended),
                                    status_account(ACCOUNT_B, EMAIL_B, at=NOW, desktop=False, cli=False, plan=ended),
                                    status_account(ACCOUNT_D, EMAIL_D, at=NOW, desktop=False, cli=False,
                                                   plan=upcoming)]),
                          NOW + 30).tooltip.split("\n")
        self.assertTrue(lines[0].startswith("gamma (app, CLI)  5h 82% "), "a client uses it: its readings stay live")
        self.assertEqual(lines[1], "Next: gamma")
        self.assertTrue(lines[2].startswith("delta  5h 82% "), "a plan upcoming is not one that has ended")
        self.assertEqual(len(lines), 3, "beta, its plan ended and no client using it, stands nowhere")
        self.assertNotIn("plan ended", "\n".join(lines), "no tag for one a client uses")

    def test_an_ended_plan_with_no_5_hour_limit_is_left_out_alike_and_no_plan_recorded_keeps_its_windows(self):
        ended = status_subscription(state="ended", plan=None, planName=None, paidUntil="2026-09-10", daysLeft=None)
        no_limit = status_window("no_limit", None, as_of=NOW - 60)
        lines = tray_view(snapshot([status_account(ACCOUNT_C, EMAIL_C, at=NOW),
                                    status_account(ACCOUNT_B, EMAIL_B, at=NOW, desktop=False, cli=False,
                                                   five_hour=no_limit, plan=ended),
                                    status_account(ACCOUNT_A, EMAIL_A, at=NOW, desktop=False, cli=False)]),
                          NOW + 30).tooltip.split("\n")
        self.assertEqual(lines[1], "Next: gamma")
        self.assertTrue(lines[2].startswith("alpha  5h 82% "), "no bill source names it: drawn as before")
        self.assertEqual(len(lines), 3, "beta stands nowhere, its weekly window leading nothing")

    def test_none_left_to_recommend_is_no_limit_so_an_account_shown_again_raises_no_relief(self):
        notices = Notices(NOW)
        state = WindowState()
        none = four(recommended={"account": None, "reliefAt": None, "reliefExact": False,
                                 "reason": "No account is left to recommend: every account is hidden or its plan "
                                           "has ended."})
        said, state = notices.on_status(none, state)
        self.assertEqual([n for n in said if n.kind == "relief"], [])
        said, state = notices.on_status(four(), state)
        self.assertEqual([n for n in said if n.kind == "relief"], [], "no limit was ever reached")

    def test_a_hidden_account_raises_no_renewal_notice(self):
        notices, _state = Notices(NOW).on_status(four(), WindowState())
        self.assertEqual([n for n in notices if n.kind == "renewal"], [])
        listed = [status_account(ACCOUNT_A, EMAIL_A, at=NOW, desktop=False, cli=False,
                                 plan=status_subscription(renewSoon=True, daysLeft=2))]
        notices, _state = Notices(NOW).on_status(snapshot(listed, renewalReminderDays=3), WindowState())
        self.assertEqual([n.title for n in notices if n.kind == "renewal"], ["alpha: the plan ends in 2 days"],
                         "the same account listed raises it")


class ArrangeTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.path = self.machine.paths.settings_file

    def tearDown(self):
        self.machine.close()

    def opened(self, data: dict) -> Arrangement:
        self.machine.settings(data)
        a = actions_model.arrangement(self.machine.paths, four().status)
        self.assertIsInstance(a, Arrangement)
        return a

    def save(self, a: Arrangement):
        return actions_model.set_arrangement(self.machine.paths, a)

    def test_the_window_lists_a_hidden_account_and_shows_it_again(self):
        a = self.opened({"v": 1, "hiddenAccounts": [ACCOUNT_A, UNLISTED]})
        self.assertEqual([(r.shown, r.hidden) for r in a.rows],
                         [("alpha", True), ("beta", False), ("delta", False), ("gamma", False)])
        self.assertFalse(a.changed())
        a.set_shown(ACCOUNT_A, True)
        a.set_shown(ACCOUNT_D, False)
        self.assertTrue(a.changed())
        outcome = self.save(a)
        self.assertEqual(outcome.message, "Accounts saved.")
        self.assertEqual(load_settings(self.path).hidden_accounts, (ACCOUNT_D, UNLISTED),
                         "the account the window does not list kept hidden")

    def test_a_save_that_shows_and_hides_nothing_keeps_what_is_hidden(self):
        a = self.opened({"v": 1, "hiddenAccounts": [ACCOUNT_A]})
        self.assertIsNone(a.rename(ACCOUNT_B, "Bob"))
        self.assertEqual(self.save(a).message, "Accounts saved.")
        self.assertEqual(load_settings(self.path).hidden_accounts, (ACCOUNT_A,))

    def test_hiding_done_by_hand_meanwhile_survives_a_save_that_did_not_touch_it(self):
        a = self.opened({"v": 1})
        self.assertIsNone(a.rename(ACCOUNT_B, "Bob"))
        self.machine.settings({"v": 1, "hiddenAccounts": [ACCOUNT_D, UNLISTED]})
        self.assertTrue(self.save(a).ok)
        settings = load_settings(self.path)
        self.assertEqual((settings.names, settings.hidden_accounts), ({ACCOUNT_B: "Bob"}, (ACCOUNT_D, UNLISTED)))

    def test_the_window_s_own_showing_and_hiding_stand_over_the_settings_and_the_rest_is_theirs(self):
        a = self.opened({"v": 1, "hiddenAccounts": [ACCOUNT_A]})
        a.set_shown(ACCOUNT_A, True)
        a.set_shown(ACCOUNT_D, False)
        # By hand meanwhile: alpha left hidden as it was read, beta hidden, delta hidden as the window hides it.
        self.machine.settings({"v": 1, "hiddenAccounts": [ACCOUNT_A, ACCOUNT_B, ACCOUNT_D]})
        outcome = self.save(a)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(load_settings(self.path).hidden_accounts, (ACCOUNT_B, ACCOUNT_D),
                         "alpha shown and delta hidden, as the window made them; beta hidden, as the hand made it")


if __name__ == "__main__":
    unittest.main()
