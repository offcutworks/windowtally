"""One order and one name per account across WindowTally: the settings that hold them, the accounts they are applied to,
status.json's order and labels as a pass writes them, and the history, which keeps the order accounts were first seen
in and colours no account by its name."""

import contextlib
import io
import json
import unittest

from fixtures import ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, bill, epoch
from windowtally.__main__ import main
from windowtally.accounts import Account, arranged, default_label, name_key, named
from windowtally.history import account_slots
from windowtally.ledger import Ledger
from windowtally.limits import AccountStanding, Recommendation, WeeklyAnchor, WindowStanding, standings
from windowtally.service import run_pass
from windowtally.settings import (NAME_LIMIT, SettingsError, edit_account_arrangement, load_settings, name_problem,
                                  set_account_arrangement, set_notifications_silenced)
from windowtally.status_file import shown_order, status_document
from windowtally_gui.history_model import compute

NOW = epoch("2026-10-20T20:00:00Z")   # the time the fixtures' watcher view is written at
ACCOUNT_C = "cccccccc-0000-4000-8000-000000000003"
ACCOUNT_D = "dddddddd-0000-4000-8000-000000000004"
ORG_C = "0c0c0c0c-0000-4000-8000-00000000000c"
ORG_D = "0d0d0d0d-0000-4000-8000-00000000000d"
EMAIL_C = "gamma@example.com"
EMAIL_D = "delta@example.com"
STALE = "eeeeeeee-0000-4000-8000-000000000005"   # an account the machine does not know
# Names in a script other than Latin; the second is 16 characters each two columns wide, which the limit counts as 16.
GREEK_NAME = "\u039f\u03b9\u03ba\u03bf\u03b3\u03ad\u03bd\u03b5\u03b9\u03b1"
WIDE_SIXTEEN = "\uac00\ub098\ub2e4\ub77c\ub9c8\ubc14\uc0ac\uc544\uc790\ucc28\uce74\ud0c0\ud30c\ud558\uac70\ub108"


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.path = self.machine.paths.settings_file

    def tearDown(self):
        self.machine.close()

    def test_the_order_and_the_names_are_read_by_uuid_in_lower_case(self):
        self.machine.settings({"v": 1, "accountOrder": [ACCOUNT_B.upper(), ACCOUNT_A],
                               "accountNames": {ACCOUNT_A.upper(): "Work", ACCOUNT_B: GREEK_NAME}})
        settings = load_settings(self.path)
        self.assertEqual(settings.account_order, (ACCOUNT_B, ACCOUNT_A))
        self.assertEqual(settings.names, {ACCOUNT_A: "Work", ACCOUNT_B: GREEK_NAME})

    def test_absent_they_order_and_name_nothing(self):
        self.machine.settings({"v": 1})
        self.assertEqual((load_settings(self.path).account_order, load_settings(self.path).names), ((), {}))

    def test_a_name_is_at_most_sixteen_characters_and_shows_whole(self):
        self.assertEqual(NAME_LIMIT, 16)
        for name in ("exactly16chars..", WIDE_SIXTEEN, "Work", "a b"):
            self.assertIsNone(name_problem(name), name)
        refused = {"seventeen chars..": "longer than 16", "": "empty", " Work": "space", "Work ": "space",
                   "Wo​rk": "U+200B", "Wo\trk": "U+0009", "Wo rk": "U+2028"}
        for name, words in refused.items():
            self.assertIn(words, name_problem(name), repr(name))

    def test_a_file_with_a_bad_order_or_name_is_refused_whole_every_problem_named(self):
        self.machine.settings({"v": 1, "silenceNotifications": True,
                               "accountOrder": [ACCOUNT_A, "not-a-uuid", ACCOUNT_A.upper(), 7],
                               "accountNames": {"alpha": "Work", ACCOUNT_A: "Work", ACCOUNT_B: "work",
                                                ACCOUNT_C: " Lab", ACCOUNT_D: 5}})
        with self.assertRaises(SettingsError) as raised:
            load_settings(self.path)
        words = str(raised.exception)
        for expected in ("accountOrder entry 2 is not an account UUID", f"accountOrder entry 3 repeats {ACCOUNT_A}",
                         "accountOrder entry 4 is not an account UUID", "names 'alpha', which is not an account UUID",
                         f"the name 'work' of {ACCOUNT_B} is also the name of {ACCOUNT_A}, case aside",
                         f"the name of {ACCOUNT_C} cannot be used: it starts or ends with a space",
                         f"the name of {ACCOUNT_D} cannot be used: it is not text"):
            self.assertIn(expected, words)
        for shape in ({"v": 1, "accountOrder": {}}, {"v": 1, "accountNames": []}):
            self.machine.settings(shape)
            with self.assertRaises(SettingsError):
                load_settings(self.path)

    def test_the_arrangement_is_written_together_keeping_every_other_setting(self):
        self.machine.settings({"v": 1, "renewalReminderDays": 3, "silenceNotifications": True})
        written = set_account_arrangement(self.path, [ACCOUNT_B, ACCOUNT_A], {ACCOUNT_A: "Work"})
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data, {"v": 1, "renewalReminderDays": 3, "silenceNotifications": True,
                                "accountOrder": [ACCOUNT_B, ACCOUNT_A], "accountNames": {ACCOUNT_A: "Work"}})
        self.assertEqual(written, load_settings(self.path))
        set_notifications_silenced(self.path, False)
        self.assertEqual(load_settings(self.path).names, {ACCOUNT_A: "Work"}, "another setter keeps the names")
        set_account_arrangement(self.path, [], {})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"v": 1, "renewalReminderDays": 3},
                         "the order by name and no names are written as nothing")

    def test_an_arrangement_the_contract_refuses_is_not_written(self):
        self.machine.settings({"v": 1, "silenceNotifications": True})
        before = self.path.read_text(encoding="utf-8")
        with self.assertRaises(ValueError) as raised:
            set_account_arrangement(self.path, [ACCOUNT_A, ACCOUNT_A], {ACCOUNT_B: "x" * 17})
        self.assertIn("repeats", str(raised.exception))
        self.assertIn("longer than 16", str(raised.exception))
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.machine.settings({"v": 1, "unknown": 1})
        with self.assertRaises(SettingsError):
            set_account_arrangement(self.path, [ACCOUNT_A], {})

    def test_an_arrangement_edited_is_made_from_the_settings_as_they_stand_when_it_is_written(self):
        self.machine.settings({"v": 1, "silenceNotifications": True, "accountOrder": [ACCOUNT_B],
                               "accountNames": {ACCOUNT_A: "Work"}})
        seen = []

        def edit(current):
            seen.append(current)
            return (ACCOUNT_A, *current.account_order), current.names | {ACCOUNT_B: "Home"}

        written = edit_account_arrangement(self.path, edit)
        self.assertEqual([(s.account_order, s.names) for s in seen], [((ACCOUNT_B,), {ACCOUNT_A: "Work"})])
        self.assertEqual(written, load_settings(self.path))
        self.assertEqual((written.account_order, written.names, written.silence_notifications),
                         ((ACCOUNT_A, ACCOUNT_B), {ACCOUNT_A: "Work", ACCOUNT_B: "Home"}, True))

    def test_an_edit_that_refuses_writes_nothing(self):
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_A: "Work"}})
        before = self.path.read_text(encoding="utf-8")

        def edit(_current):
            raise ValueError("changed elsewhere")

        with self.assertRaises(ValueError) as raised:
            edit_account_arrangement(self.path, edit)
        self.assertEqual(str(raised.exception), "changed elsewhere")
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        with self.assertRaises(ValueError) as raised:
            edit_account_arrangement(self.path, lambda current: ((), current.names | {ACCOUNT_B: "work"}))
        self.assertIn("case aside", str(raised.exception), "what the edit makes is held to the contract")
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)


class AccountsTest(unittest.TestCase):
    def test_an_account_is_shown_by_the_users_name_else_by_its_e_mail(self):
        account = Account(uuid=ACCOUNT_A, email=EMAIL_A)
        self.assertEqual((account.label, account.default_label), ("alpha", "alpha"))
        renamed = named({ACCOUNT_A: account, ACCOUNT_B: Account(uuid=ACCOUNT_B)}, {ACCOUNT_A: "Work"})
        self.assertEqual((renamed[ACCOUNT_A].label, renamed[ACCOUNT_A].default_label), ("Work", "alpha"))
        self.assertEqual(renamed[ACCOUNT_B].label, ACCOUNT_B[:8])
        self.assertEqual(default_label(ACCOUNT_A, None), ACCOUNT_A[:8])

    def test_the_users_order_then_the_rest_by_name_case_aside(self):
        names = {"a": "beta", "b": "alpha", "c": "Alpha", "d": "gamma", "e": "Delta"}
        self.assertEqual(arranged(names, [], str, names.get), ["c", "b", "a", "e", "d"],
                         "case aside first, then the name itself, so the order is total")
        self.assertTrue(name_key("Alpha") < name_key("alpha") < name_key("beta") < name_key("Delta"))
        self.assertEqual(arranged(names, ["d", "nobody", "a"], str, names.get), ["d", "a", "c", "b", "e"],
                         "a listed UUID no account has is passed over")

    def test_accounts_shown_by_one_name_stand_by_uuid_whatever_order_they_come_in(self):
        names = {ACCOUNT_D: "alpha", ACCOUNT_B: "alpha", ACCOUNT_C: "Alpha"}
        for items in (list(names), list(reversed(names))):
            self.assertEqual(arranged(items, [], str, names.get), [ACCOUNT_C, ACCOUNT_B, ACCOUNT_D])

    def test_the_standings_stand_by_name_case_aside_and_accounts_shown_by_one_name_by_uuid(self):
        accounts = [Account(uuid=ACCOUNT_A, email=EMAIL_A, name="Zed"), Account(uuid=ACCOUNT_D, email="gamma@other.example"),
                    Account(uuid=ACCOUNT_C, email=EMAIL_C), Account(uuid=ACCOUNT_B, email=EMAIL_B, name="Alpha")]
        machine = Machine()
        ledger = Ledger.open(machine.paths.ledger_db)
        try:
            for given in (accounts, list(reversed(accounts))):
                self.assertEqual([s.account.uuid for s in standings(ledger, given, NOW)],
                                 [ACCOUNT_B, ACCOUNT_C, ACCOUNT_D, ACCOUNT_A],
                                 "Alpha, then the two shown as gamma by UUID, then Zed: case aside, as names are ordered")
        finally:
            ledger.close()
            machine.close()


def standing(uuid: str, email: str, *, desktop: bool = False, cli: bool = False, name: str | None = None):
    return AccountStanding(Account(uuid=uuid, email=email, name=name),
                           WindowStanding("five_hour", "not_started", None, None, None, False, None),
                           WindowStanding("seven_day", "unknown", None, None, None, False, None),
                           WeeklyAnchor(NOW + 86400, exact=False), None, desktop, cli)


class StatusOrderTest(unittest.TestCase):
    def setUp(self):
        self.standings = [standing(ACCOUNT_A, EMAIL_A), standing(ACCOUNT_B, EMAIL_B, cli=True),
                          standing(ACCOUNT_C, EMAIL_C, desktop=True), standing(ACCOUNT_D, EMAIL_D)]

    def order(self, order=(), standings=None) -> list[str]:
        doc = status_document(standings or self.standings, Recommendation(None, "", None), now=NOW,
                              desktop_account=None, cli_account=None, cli_condition=None, account_order=order)
        return [a["uuid"] for a in doc["accounts"]]

    def test_the_app_s_account_then_the_cli_s_then_the_users_order(self):
        self.assertEqual(self.order(), [ACCOUNT_C, ACCOUNT_B, ACCOUNT_A, ACCOUNT_D], "the rest by name")
        self.assertEqual(self.order([ACCOUNT_D, ACCOUNT_B, ACCOUNT_A]), [ACCOUNT_C, ACCOUNT_B, ACCOUNT_D, ACCOUNT_A],
                         "the accounts in use stand first wherever the user put them")
        self.assertEqual(self.order([ACCOUNT_D]), [ACCOUNT_C, ACCOUNT_B, ACCOUNT_D, ACCOUNT_A])

    def test_one_account_in_both_clients_stands_first_once(self):
        both = [standing(ACCOUNT_A, EMAIL_A), standing(ACCOUNT_B, EMAIL_B, desktop=True, cli=True)]
        self.assertEqual(self.order([ACCOUNT_A], both), [ACCOUNT_B, ACCOUNT_A])
        signed_out = [standing(ACCOUNT_A, EMAIL_A), standing(ACCOUNT_B, EMAIL_B, cli=True)]
        self.assertEqual(self.order([], signed_out), [ACCOUNT_B, ACCOUNT_A], "with no app account, the CLI's first")

    def test_the_rest_stand_by_the_names_they_are_shown_by(self):
        named_standings = [standing(ACCOUNT_A, EMAIL_A, name="zed"), standing(ACCOUNT_D, EMAIL_D)]
        self.assertEqual([s.account.uuid for s in shown_order(named_standings)], [ACCOUNT_D, ACCOUNT_A])


class PassTest(unittest.TestCase):
    """Four accounts: gamma on the desktop app, beta on the CLI, alpha and delta idle."""

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

    def test_status_json_lists_the_accounts_in_use_first_then_the_users_order_by_the_users_names(self):
        names = {ACCOUNT_A: "Work", ACCOUNT_B: "Home", ACCOUNT_C: "Lab", ACCOUNT_D: "Spare"}
        self.machine.settings({"v": 1, "accountOrder": [STALE, ACCOUNT_D, ACCOUNT_A], "accountNames": names})
        doc = self.status()
        self.assertEqual([a["uuid"] for a in doc["accounts"]], [ACCOUNT_C, ACCOUNT_B, ACCOUNT_D, ACCOUNT_A])
        self.assertEqual([a["label"] for a in doc["accounts"]], ["Lab", "Home", "Spare", "Work"])
        self.assertEqual([a["email"] for a in doc["accounts"]], [EMAIL_C, EMAIL_B, EMAIL_D, EMAIL_A],
                         "the e-mail stays whatever the name")
        self.assertEqual(doc["sourceErrors"], [])
        recommended = next(a for a in doc["accounts"] if a["uuid"] == doc["recommended"]["account"])
        self.assertTrue(doc["recommended"]["reason"].startswith(f"{recommended['label']} — room left"),
                        doc["recommended"]["reason"])
        page = self.machine.paths.dashboard_file.read_text(encoding="utf-8")
        self.assertIn("Spare", page)

    def test_without_an_order_the_rest_stand_by_name_and_unnamed_accounts_by_their_e_mail(self):
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_A: "zed"}})
        doc = self.status()
        self.assertEqual([a["label"] for a in doc["accounts"]], ["gamma", "beta", "delta", "zed"])

    def test_settings_that_cannot_be_read_name_and_order_nothing_and_are_said(self):
        self.machine.settings({"v": 1, "accountOrder": [ACCOUNT_D], "accountNames": {ACCOUNT_A: " Work"}})
        doc = self.status()
        self.assertEqual([a["label"] for a in doc["accounts"]], ["gamma", "beta", "alpha", "delta"])
        self.assertTrue(any(e.startswith("settings: ") for e in doc["sourceErrors"]), doc["sourceErrors"])

    def test_a_rename_moves_no_colour(self):
        run_pass(self.machine.paths, NOW, dashboard=False)
        ledger = Ledger.open_readonly(self.machine.paths.ledger_db)
        try:
            known = ledger.known_accounts()
            before = {a.uuid: token for a, token in account_slots(ledger, known)}
            renamed = named(known, {ACCOUNT_A: "zzz", ACCOUNT_D: "aaa"})
            after = {a.uuid: token for a, token in account_slots(ledger, renamed)}
        finally:
            ledger.close()
        self.assertEqual(after, before)

    def test_the_history_window_and_the_bills_command_name_the_accounts_as_the_user_did(self):
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_A: "Work"}})
        self.machine.bills_file([bill(EMAIL_A, "2026-10-01", 200, period="2026-10-01..2026-11-01")])
        run_pass(self.machine.paths, NOW, dashboard=False)
        shown = {e.uuid: e.label for e in compute(self.machine.paths, "30d", now=NOW).accounts if e.uuid}
        self.assertEqual(shown[ACCOUNT_A], "Work")
        self.assertEqual(shown[ACCOUNT_B], "beta")
        p = self.machine.paths
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            main(["--claude-home", str(p.claude_home), "--desktop-data", str(p.desktop_data),
                  "--data-dir", str(p.data_dir), "bills"])
        self.assertIn(f"Work  ({EMAIL_A})", out.getvalue())
        self.assertIn(f"beta  ({EMAIL_B})", out.getvalue())


if __name__ == "__main__":
    unittest.main()
