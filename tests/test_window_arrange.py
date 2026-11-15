"""The window's side of the one order and the user's names, with no toolkit: the Arrange accounts window's logic, its
reading and writing of the settings, and the menus and the tooltip keeping status.json's order."""

import json
import unittest
from pathlib import Path

from fixtures import ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, Machine, status_account, status_document, status_window
from windowtally.settings import Settings, load_settings
from windowtally_gui import actions_model, switch_model
from windowtally_gui.actions_model import Outcome
from windowtally_gui.arrange_model import Arrangement
from windowtally_gui.live_model import tray_view
from windowtally_gui.status_model import snapshot_of
from windowtally_gui.switch_model import APP, Switches

T0 = 1_800_000_000.0
ACCOUNT_C = "cccccccc-0000-4000-8000-000000000003"
EMAIL_C = "gamma@example.com"
ACCOUNT_UNLISTED = "dddddddd-0000-4000-8000-000000000004"   # named in the settings, listed by no status


def snapshot(accounts: list[dict], **changes):
    return snapshot_of(Path("status.json"), json.dumps(status_document(accounts, at=T0, **changes)))


def three(**changes):
    """A status listing gamma, in use by the app and the CLI, then beta and alpha, beta recommended."""
    accounts = [status_account(ACCOUNT_C, EMAIL_C, at=T0), status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False,
                                                                         cli=False),
                status_account(ACCOUNT_A, EMAIL_A, at=T0, desktop=False, cli=False)]
    base = {"recommended": {"account": ACCOUNT_B, "reason": "beta has room left.", "reliefAt": None,
                            "reliefExact": False}, "oneClickDesktop": True}
    base.update(changes)
    return snapshot(accounts, **base).status


class ArrangementTest(unittest.TestCase):
    def arrangement(self, order=(), names=None) -> Arrangement:
        return Arrangement.of(three(), Settings(account_order=tuple(order), account_names=tuple((names or {}).items())))

    def shown(self, arrangement: Arrangement) -> list[str]:
        return [r.shown for r in arrangement.rows]

    def test_the_window_shows_the_users_order_without_the_accounts_in_use_first(self):
        self.assertEqual(self.shown(self.arrangement()), ["alpha", "beta", "gamma"])
        self.assertEqual(self.shown(self.arrangement([ACCOUNT_B, "eeeeeeee-0000-4000-8000-000000000005"])),
                         ["beta", "alpha", "gamma"], "a listed account first, the rest by name, a stale UUID passed")
        self.assertEqual(self.shown(self.arrangement(names={ACCOUNT_C: "Apple"})), ["alpha", "Apple", "beta"])

    def test_an_account_moves_one_place_at_a_time_within_the_list(self):
        a = self.arrangement()
        self.assertFalse(a.can_move(ACCOUNT_A, -1))
        self.assertFalse(a.move(ACCOUNT_A, -1))
        self.assertTrue(a.move(ACCOUNT_A, 1))
        self.assertEqual(self.shown(a), ["beta", "alpha", "gamma"])
        self.assertTrue(a.move(ACCOUNT_A, 1))
        self.assertFalse(a.can_move(ACCOUNT_A, 1))
        self.assertEqual(a.order(), (ACCOUNT_B, ACCOUNT_C, ACCOUNT_A))

    def test_two_accounts_shown_by_one_name_can_be_put_in_either_order(self):
        accounts = [status_account(ACCOUNT_C, "alpha@other.example", at=T0),
                    status_account(ACCOUNT_A, EMAIL_A, at=T0, desktop=False, cli=False)]
        status = snapshot(accounts).status
        a = Arrangement.of(status, Settings())
        self.assertEqual([r.uuid for r in a.rows], [ACCOUNT_A, ACCOUNT_C], "by name, the two shown as alpha by UUID")
        self.assertEqual(a.order(), ())
        self.assertTrue(a.move(ACCOUNT_C, -1))
        self.assertFalse(a.is_by_name())
        self.assertEqual(a.order(), (ACCOUNT_C, ACCOUNT_A), "the order set between them is written")
        self.assertEqual([r.uuid for r in Arrangement.of(status, Settings(account_order=a.order())).rows],
                         [ACCOUNT_C, ACCOUNT_A])

    def test_the_default_order_by_name_is_written_as_no_order(self):
        a = self.arrangement([ACCOUNT_C, ACCOUNT_A])
        self.assertFalse(a.is_by_name())
        a.by_name()
        self.assertEqual(self.shown(a), ["alpha", "beta", "gamma"])
        self.assertTrue(a.is_by_name())
        self.assertEqual(a.order(), ())
        self.assertTrue(a.changed())

    def test_a_name_is_held_to_the_naming_rules_and_differs_from_every_other_shown_name(self):
        a = self.arrangement(names={ACCOUNT_C: "Lab"})
        self.assertIn("longer than 16", a.rename(ACCOUNT_A, "seventeen chars.."))
        self.assertIn("U+200B", a.rename(ACCOUNT_A, "Wo​rk"))
        self.assertEqual(a.rename(ACCOUNT_A, "BETA"), f"Not usable: another account ({EMAIL_B}) is shown as beta.")
        self.assertIn("is shown as Lab", a.rename(ACCOUNT_A, "lab"))
        self.assertEqual(a.row(ACCOUNT_A).shown, "alpha", "a refused name leaves the name as it was")
        self.assertIsNone(a.rename(ACCOUNT_A, "  Work  "))
        self.assertEqual((a.row(ACCOUNT_A).name, a.row(ACCOUNT_A).shown), ("Work", "Work"), "the spaces around dropped")
        self.assertIsNone(a.rename(ACCOUNT_A, "exactly16chars.."))
        self.assertIsNone(a.rename(ACCOUNT_B, "Alpha"), "another account's default is free once it is renamed")

    def test_clearing_a_name_or_typing_the_default_shows_the_default(self):
        a = self.arrangement(names={ACCOUNT_A: "Work"})
        self.assertFalse(a.changed())
        self.assertIsNone(a.rename(ACCOUNT_A, ""))
        self.assertEqual((a.row(ACCOUNT_A).name, a.row(ACCOUNT_A).shown), (None, "alpha"))
        self.assertTrue(a.changed())
        self.assertIsNone(a.rename(ACCOUNT_A, "alpha"))
        self.assertIsNone(a.row(ACCOUNT_A).name)
        self.assertIsNone(a.rename(ACCOUNT_A, "Work"))
        self.assertFalse(a.changed(), "back to what was saved")
        self.assertEqual(a.names(), {ACCOUNT_A: "Work"})

    def test_the_names_of_accounts_the_window_does_not_list_are_kept(self):
        a = self.arrangement(names={ACCOUNT_UNLISTED: "Old", ACCOUNT_C: "Lab"})
        self.assertEqual([r.uuid for r in a.rows], [ACCOUNT_A, ACCOUNT_B, ACCOUNT_C], "status's accounts only")
        self.assertFalse(a.changed(), "a kept name is no change")
        self.assertTrue(a.move(ACCOUNT_C, -1))
        self.assertIsNone(a.rename(ACCOUNT_A, ""))
        self.assertIsNone(a.rename(ACCOUNT_C, "Bench"))
        self.assertEqual(a.names(), {ACCOUNT_C: "Bench", ACCOUNT_UNLISTED: "Old"})
        self.assertEqual(Arrangement(a.rows, {ACCOUNT_C: "Lab", ACCOUNT_UNLISTED: "Old"}).names(),
                         {ACCOUNT_C: "Bench", ACCOUNT_UNLISTED: "Old"}, "a listed account's name is its row's")

    def test_a_name_the_settings_keep_for_an_account_not_listed_is_refused_where_it_is_typed(self):
        a = self.arrangement(names={ACCOUNT_UNLISTED: "Old"})
        self.assertEqual(a.rename(ACCOUNT_A, "OLD"),
                         f"Not usable: settings.json keeps it for an unlisted account ({ACCOUNT_UNLISTED}); remove it "
                         f"there to free it.")
        self.assertEqual((a.row(ACCOUNT_A).name, a.row(ACCOUNT_A).shown), (None, "alpha"), "the name left as it was")
        self.assertFalse(a.changed())


class ArrangementActionsTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()

    def tearDown(self):
        self.machine.close()

    def test_the_window_reads_the_arrangement_and_writes_it_back_with_every_other_setting(self):
        self.machine.settings({"v": 1, "silenceNotifications": True, "accountNames": {ACCOUNT_C: "Lab"},
                               "accountOrder": ["eeeeeeee-0000-4000-8000-000000000005", ACCOUNT_B]})
        a = actions_model.arrangement(self.machine.paths, three())
        self.assertIsInstance(a, Arrangement)
        self.assertEqual([r.shown for r in a.rows], ["beta", "alpha", "Lab"])
        a.move(ACCOUNT_C, -1)
        self.assertIsNone(a.rename(ACCOUNT_A, "Aaron"))
        outcome = actions_model.set_arrangement(self.machine.paths, a)
        self.assertEqual(outcome, Outcome(True, "Accounts saved."))
        settings = load_settings(self.machine.paths.settings_file)
        self.assertEqual(settings.account_order, (ACCOUNT_B, ACCOUNT_C, ACCOUNT_A), "the stale UUID dropped")
        self.assertEqual(settings.names, {ACCOUNT_C: "Lab", ACCOUNT_A: "Aaron"})
        self.assertTrue(settings.silence_notifications)

    def test_a_save_keeps_the_names_the_settings_hold_for_accounts_the_window_does_not_list(self):
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_UNLISTED: "Old", ACCOUNT_C: "Lab"}})
        a = actions_model.arrangement(self.machine.paths, three())
        self.assertIsInstance(a, Arrangement)
        self.assertNotIn(ACCOUNT_UNLISTED, [r.uuid for r in a.rows])
        a.move(ACCOUNT_A, 1)
        self.assertIsNone(a.rename(ACCOUNT_C, ""))
        self.assertTrue(actions_model.set_arrangement(self.machine.paths, a).ok)
        settings = load_settings(self.machine.paths.settings_file)
        self.assertEqual(settings.names, {ACCOUNT_UNLISTED: "Old"})
        self.assertEqual(settings.account_order, (ACCOUNT_B, ACCOUNT_A, ACCOUNT_C))

    def test_settings_that_cannot_be_read_are_not_arranged_over(self):
        self.machine.settings({"v": 1, "unknown": True})
        outcome = actions_model.arrangement(self.machine.paths, three())
        self.assertIsInstance(outcome, Outcome)
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.message.startswith("Cannot arrange the accounts: "), outcome.message)
        self.machine.settings({"v": 1})
        a = actions_model.arrangement(self.machine.paths, three())
        self.machine.settings({"v": 2})
        refused = actions_model.set_arrangement(self.machine.paths, a)
        self.assertFalse(refused.ok)
        self.assertTrue(refused.message.startswith("Not changed: "), refused.message)


class EditedElsewhereTest(unittest.TestCase):
    """The settings edited by hand while the window stands open: what the window left alone stays as the edit left
    it, and nothing the edit changed is undone without the window saying so."""

    def setUp(self):
        self.machine = Machine()
        self.path = self.machine.paths.settings_file

    def tearDown(self):
        self.machine.close()

    def opened(self, data: dict) -> Arrangement:
        self.machine.settings(data)
        a = actions_model.arrangement(self.machine.paths, three())
        self.assertIsInstance(a, Arrangement)
        return a

    def save(self, a: Arrangement) -> Outcome:
        return actions_model.set_arrangement(self.machine.paths, a)

    def test_names_set_cleared_or_changed_by_hand_meanwhile_survive_a_save(self):
        a = self.opened({"v": 1, "accountNames": {ACCOUNT_A: "Work", ACCOUNT_C: "Lab"}})
        self.assertTrue(a.move(ACCOUNT_B, 1))
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_B: "Home", ACCOUNT_C: "Bench"}})
        self.assertTrue(self.save(a).ok)
        settings = load_settings(self.path)
        self.assertEqual(settings.names, {ACCOUNT_B: "Home", ACCOUNT_C: "Bench"}, "named, renamed and un-named by hand")
        self.assertEqual(settings.account_order, (ACCOUNT_C, ACCOUNT_B, ACCOUNT_A), "the window's own move")

    def test_an_order_set_by_hand_meanwhile_survives_a_rename_in_the_window(self):
        a = self.opened({"v": 1})
        self.assertIsNone(a.rename(ACCOUNT_A, "Aaron"))
        self.machine.settings({"v": 1, "accountOrder": [ACCOUNT_C, ACCOUNT_UNLISTED, ACCOUNT_B]})
        self.assertTrue(self.save(a).ok)
        settings = load_settings(self.path)
        self.assertEqual(settings.account_order, (ACCOUNT_C, ACCOUNT_B),
                         "as the edit left it, less the UUID no listed account has, dropped at every save")
        self.assertEqual(settings.names, {ACCOUNT_A: "Aaron"})

    def test_an_order_set_by_hand_meanwhile_survives_the_window_going_back_to_its_own(self):
        a = self.opened({"v": 1})
        self.assertTrue(a.move(ACCOUNT_A, 1))
        self.machine.settings({"v": 1, "accountOrder": [ACCOUNT_C, ACCOUNT_A]})
        self.assertFalse(self.save(a).ok)
        a.by_name()
        self.assertFalse(a.changed(), "back to the order the window opened with")
        self.assertIsNone(a.rename(ACCOUNT_B, "Bob"))
        self.assertTrue(self.save(a).ok)
        self.assertEqual(load_settings(self.path).account_order, (ACCOUNT_C, ACCOUNT_A),
                         "an order the window left alone is the settings' as they stand")

    def test_without_a_change_elsewhere_the_window_writes_the_order_it_shows(self):
        a = self.opened({"v": 1, "accountOrder": [ACCOUNT_C, ACCOUNT_UNLISTED]})
        self.assertEqual([r.uuid for r in a.rows], [ACCOUNT_C, ACCOUNT_A, ACCOUNT_B])
        self.assertIsNone(a.rename(ACCOUNT_A, "Zed"))
        self.assertTrue(self.save(a).ok)
        self.assertEqual(load_settings(self.path).account_order, (ACCOUNT_C, ACCOUNT_A, ACCOUNT_B),
                         "a rename re-sorts nothing, and the UUID no listed account has is dropped")

    def test_an_order_written_otherwise_by_hand_that_puts_the_accounts_alike_is_no_conflict(self):
        a = self.opened({"v": 1})
        self.assertTrue(a.move(ACCOUNT_C, -1))
        self.machine.settings({"v": 1, "accountOrder": [ACCOUNT_A, ACCOUNT_C, ACCOUNT_UNLISTED]})
        self.assertTrue(self.save(a).ok)
        self.assertEqual(load_settings(self.path).account_order, (ACCOUNT_A, ACCOUNT_C, ACCOUNT_B))

    def test_laying_the_window_onto_the_settings_changes_nothing_of_the_window(self):
        a = self.opened({"v": 1})
        self.assertIsNone(a.rename(ACCOUNT_B, "Bob"))
        current = Settings(account_names=((ACCOUNT_B, "Bert"),))
        for _ in range(2):
            with self.assertRaises(ValueError) as raised:
                a.onto(current)
            self.assertIn(f"the name of {EMAIL_B}, now 'Bert'", str(raised.exception))
        self.assertEqual(load_settings(self.path).names, {}, "only a save is told")

    def test_the_names_of_accounts_the_window_does_not_list_are_the_settings_as_they_stand(self):
        other = "eeeeeeee-0000-4000-8000-000000000005"
        a = self.opened({"v": 1, "accountNames": {ACCOUNT_UNLISTED: "Old"}})
        self.assertIsNone(a.rename(ACCOUNT_A, "Aaron"))
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_UNLISTED: "New", other: "Eve"}})
        self.assertTrue(self.save(a).ok)
        self.assertEqual(load_settings(self.path).names, {ACCOUNT_A: "Aaron", ACCOUNT_UNLISTED: "New", other: "Eve"})
        a = self.opened({"v": 1, "accountNames": {ACCOUNT_UNLISTED: "Old"}})
        self.assertIsNone(a.rename(ACCOUNT_B, "Bob"))
        self.machine.settings({"v": 1})
        self.assertTrue(self.save(a).ok)
        self.assertEqual(load_settings(self.path).names, {ACCOUNT_B: "Bob"}, "a kept name removed by hand stays so")

    def test_a_name_changed_both_here_and_by_hand_is_said_and_saved_over_only_by_ok_again(self):
        a = self.opened({"v": 1, "accountNames": {ACCOUNT_C: "Lab"}})
        self.assertIsNone(a.rename(ACCOUNT_B, "Bob"))
        self.assertIsNone(a.rename(ACCOUNT_C, "Bench"))
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_B: "Bert"}})
        before = self.path.read_text(encoding="utf-8")
        refused = self.save(a)
        self.assertFalse(refused.ok)
        self.assertEqual(refused.message,
                         f"Not changed: settings.json changed meanwhile: the name of {EMAIL_B}, now 'Bert'; the name "
                         f"of {EMAIL_C}, now none. OK again overwrites it; Cancel keeps it.")
        self.assertEqual(self.path.read_text(encoding="utf-8"), before, "nothing written")
        self.assertTrue(self.save(a).ok)
        self.assertEqual(load_settings(self.path).names, {ACCOUNT_B: "Bob", ACCOUNT_C: "Bench"})

    def test_a_change_made_by_hand_after_the_window_said_so_is_said_again(self):
        a = self.opened({"v": 1})
        self.assertIsNone(a.rename(ACCOUNT_B, "Bob"))
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_B: "Bert"}})
        self.assertFalse(self.save(a).ok)
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_B: "Ben"}})
        refused = self.save(a)
        self.assertFalse(refused.ok)
        self.assertIn(f"the name of {EMAIL_B}, now 'Ben'", refused.message)
        self.assertEqual(load_settings(self.path).names, {ACCOUNT_B: "Ben"})

    def test_an_order_changed_both_here_and_by_hand_is_said_and_saved_over_only_by_ok_again(self):
        a = self.opened({"v": 1})
        self.assertTrue(a.move(ACCOUNT_A, 1))
        self.machine.settings({"v": 1, "accountOrder": [ACCOUNT_C, ACCOUNT_A]})
        refused = self.save(a)
        self.assertFalse(refused.ok)
        self.assertIn("the order of the accounts", refused.message)
        self.assertEqual(load_settings(self.path).account_order, (ACCOUNT_C, ACCOUNT_A), "nothing written")
        self.assertTrue(self.save(a).ok)
        self.assertEqual(load_settings(self.path).account_order, (ACCOUNT_B, ACCOUNT_A, ACCOUNT_C))

    def test_a_change_made_by_hand_as_the_window_makes_it_is_no_conflict(self):
        a = self.opened({"v": 1})
        self.assertTrue(a.move(ACCOUNT_A, 1))
        self.assertIsNone(a.rename(ACCOUNT_B, "Bob"))
        self.machine.settings({"v": 1, "accountOrder": [ACCOUNT_B, ACCOUNT_A, ACCOUNT_C],
                               "accountNames": {ACCOUNT_B: "Bob"}})
        self.assertTrue(self.save(a).ok)
        settings = load_settings(self.path)
        self.assertEqual((settings.account_order, settings.names), ((ACCOUNT_B, ACCOUNT_A, ACCOUNT_C),
                                                                    {ACCOUNT_B: "Bob"}))

    def test_a_name_another_account_took_by_hand_meanwhile_is_refused(self):
        a = self.opened({"v": 1})
        self.assertIsNone(a.rename(ACCOUNT_A, "Lab"))
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_C: "lab"}})
        before = self.path.read_text(encoding="utf-8")
        for _ in range(2):
            refused = self.save(a)
            self.assertEqual(refused.message,
                             f"Not changed: settings.json now shows another account ({EMAIL_C}) as lab; rename "
                             f"{EMAIL_A}.", "OK again saves no clash over")
            self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        a = self.opened({"v": 1})
        self.assertIsNone(a.rename(ACCOUNT_A, "Lab"))
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_UNLISTED: "LAB"}})
        self.assertEqual(self.save(a).message,
                         f"Not changed: settings.json now keeps LAB for an unlisted account ({ACCOUNT_UNLISTED}); rename "
                         f"{EMAIL_A}.")

    def test_a_default_name_freed_by_hand_meanwhile_is_refused_to_another_account(self):
        a = self.opened({"v": 1, "accountNames": {ACCOUNT_B: "Bob"}})
        self.assertIsNone(a.rename(ACCOUNT_A, "beta"), "free while beta is shown as Bob")
        self.machine.settings({"v": 1})
        refused = self.save(a)
        self.assertFalse(refused.ok)
        self.assertIn(f"shows another account ({EMAIL_B}) as beta", refused.message)
        self.assertEqual(load_settings(self.path).names, {})


class OneOrderTest(unittest.TestCase):
    def test_the_switch_menus_keep_the_status_order_and_mark_the_next_account_where_it_stands(self):
        s = three(recommended={"account": ACCOUNT_A, "reason": "alpha has room left.", "reliefAt": None,
                               "reliefExact": False})
        entries = switch_model.switch_entries(s, APP, Switches(follows=True, one_click=True))
        self.assertEqual([(e.uuid, e.label) for e in entries],
                         [(ACCOUNT_B, "beta"), (ACCOUNT_A, "alpha  (use next)")])

    def test_the_tooltip_keeps_the_status_order(self):
        short = {"five_hour": status_window("not_started", 0.0, None), "weekly": status_window("current", 12.0, None)}
        accounts = [status_account(ACCOUNT_C, EMAIL_C, at=T0, **short),
                    status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False, cli=False, **short),
                    status_account(ACCOUNT_A, EMAIL_A, at=T0, desktop=False, cli=False, **short)]
        lines = tray_view(snapshot(accounts, recommended={"account": ACCOUNT_B, "reason": "beta has room left.",
                                                          "reliefAt": None, "reliefExact": False}), T0 + 30).tooltip
        self.assertEqual([line.split("  ")[0] for line in lines.split("\n")],
                         ["gamma (app, CLI)", "Next: beta", "beta", "alpha"],
                         "the accounts in use, Next:, then the others in the status's order, not by name")


if __name__ == "__main__":
    unittest.main()
