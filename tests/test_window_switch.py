"""The window's switching of accounts, the logic with no toolkit: what the status says of it, what a card or a menu
offers, what asking leads to, the sync script run as a process, and the flow that waits, runs and answers."""

import json
import os
import sys
import time
import unittest
from pathlib import Path

from fixtures import ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, Machine, register_session, status_account, status_document
from windowtally_gui import actions_model, flow_model, switch_model, sync_model
from windowtally_gui.flow_model import AskCliIdle, Done, NeedsCliLogin, SwitchFlow
from windowtally_gui.live_model import live_view, tray_view
from windowtally_gui.status_model import snapshot_of
from windowtally_gui.switch_model import APP, CLI, Switches
from windowtally_gui.sync_model import Result, SyncRun

T0 = 1_800_000_000.0
ACCOUNT_C = "cccccccc-0000-4000-8000-000000000003"


def status(*, follows: bool = True, one_click: bool = True, sessions: int = 0, recommended: str = ACCOUNT_B,
           archived: tuple[str, ...] = (ACCOUNT_B,), desktop: str = ACCOUNT_A, cli: str = ACCOUNT_A):
    """A status of three accounts: alpha in use by the app and the CLI, beta recommended, gamma idle."""
    accounts = [status_account(ACCOUNT_A, EMAIL_A, at=T0), status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False, cli=False),
                status_account(ACCOUNT_C, "gamma@example.com", at=T0, desktop=False, cli=False)]
    for entry in accounts:
        entry["isDesktop"] = entry["uuid"] == desktop
        entry["isCli"] = entry["uuid"] == cli
        if entry["uuid"] in archived:
            entry["desktopArchived"] = True
    changes: dict = {"recommended": {"account": recommended, "reason": "beta has room left.", "reliefAt": None,
                                     "reliefExact": False}}
    if not follows:
        changes["syncFollows"] = False
    if one_click:
        changes["oneClickDesktop"] = True
    if sessions:
        changes["workingSessions"] = sessions
    return snapshot_of(Path("status.json"), json.dumps(status_document(accounts, at=T0, **changes))).status


def switches_of(s) -> Switches:
    return switch_model.switches_of(s)


class StatusReadingTest(unittest.TestCase):
    def test_the_optional_keys_are_read_as_the_contract_says_of_a_key_that_is_absent(self):
        s = status(one_click=False)
        self.assertTrue(s.sync_follows)
        self.assertFalse(s.one_click_desktop)
        self.assertEqual(s.working_sessions, 0)
        self.assertEqual([a.desktop_archived for a in s.accounts], [False, True, False])

    def test_the_optional_keys_when_present(self):
        s = status(follows=False, one_click=True, sessions=3)
        self.assertEqual((s.sync_follows, s.one_click_desktop, s.working_sessions), (False, True, 3))

    def test_a_value_that_is_not_the_contracts_is_read_as_absent(self):
        doc = status_document([status_account(ACCOUNT_A, EMAIL_A, at=T0)], at=T0, syncFollows="no", oneClickDesktop=1,
                              workingSessions=-2)
        s = snapshot_of(Path("status.json"), json.dumps(doc)).status
        self.assertEqual((s.sync_follows, s.one_click_desktop, s.working_sessions), (True, False, 0))


class OfferTest(unittest.TestCase):
    def buttons(self, s, uuid: str, switches: Switches | None = None) -> list[tuple[str, str, bool]]:
        account = s.account(uuid)
        return [(b.client, b.text, b.accent) for b in
                switch_model.switch_buttons(s, account, switches or switches_of(s))]

    def test_with_the_cli_following_a_card_offers_one_button_and_the_account_in_use_none(self):
        s = status()
        self.assertEqual(self.buttons(s, ACCOUNT_A), [])
        self.assertEqual(self.buttons(s, ACCOUNT_B), [(APP, "Switch here", True)])
        self.assertEqual(self.buttons(s, ACCOUNT_C), [(APP, "Switch here", False)])

    def test_with_the_two_apart_a_card_offers_a_button_for_each_client_that_is_not_on_it(self):
        s = status(follows=False)
        self.assertEqual(self.buttons(s, ACCOUNT_B), [(APP, "Switch app here", True), (CLI, "Switch CLI here", False)],
                         "only the first button of the recommended card is the accent")
        self.assertEqual(self.buttons(s, ACCOUNT_C), [(APP, "Switch app here", False), (CLI, "Switch CLI here", False)])
        self.assertEqual(self.buttons(s, ACCOUNT_A), [])
        apart = status(follows=False, desktop=ACCOUNT_B, cli=ACCOUNT_A)
        self.assertEqual(self.buttons(apart, ACCOUNT_A), [(APP, "Switch app here", False)])
        self.assertEqual(self.buttons(apart, ACCOUNT_B), [(CLI, "Switch CLI here", True)],
                         "the recommended card's only button is its accent")

    def test_with_one_click_off_the_app_is_not_offered_but_the_cli_still_is_when_apart(self):
        self.assertEqual(self.buttons(status(one_click=False), ACCOUNT_B), [])
        self.assertEqual(self.buttons(status(follows=False, one_click=False), ACCOUNT_B), [(CLI, "Switch CLI here", True)])

    def test_there_is_one_accent_in_the_view_and_it_is_the_recommended_accounts(self):
        for follows in (True, False):
            s = status(follows=follows)
            accents = [a.uuid for a in s.accounts for b in switch_model.switch_buttons(s, a, switches_of(s)) if b.accent]
            self.assertEqual(accents, [ACCOUNT_B])

    def test_menu_entries_list_the_other_accounts_and_say_which_is_next(self):
        s = status(follows=False, recommended=ACCOUNT_C)
        sw = switches_of(s)
        in_order = switch_model.switch_entries(s, APP, sw)
        self.assertEqual([(e.uuid, e.label) for e in in_order],
                         [(ACCOUNT_B, "beta"), (ACCOUNT_C, "gamma  (use next)")])
        self.assertEqual({e.client for e in in_order}, {APP})

    def test_menu_entries_of_a_client_that_cannot_be_switched_alone_are_none(self):
        s = status()
        self.assertEqual(switch_model.switch_entries(s, CLI, switches_of(s)), (), "the CLI follows the app")
        off = status(one_click=False, follows=False)
        self.assertEqual(switch_model.switch_entries(off, APP, switches_of(off)), ())
        self.assertEqual([e.uuid for e in switch_model.switch_entries(off, CLI, switches_of(off))],
                         [ACCOUNT_B, ACCOUNT_C])

    def test_the_header_says_how_the_two_switch(self):
        s = status()
        self.assertEqual(switch_model.mode_words(switches_of(s)), "the CLI follows the app")
        self.assertEqual(switch_model.mode_words(Switches(follows=False)), "the CLI and the app switch apart")

    def test_a_change_the_user_made_stands_until_a_status_written_after_it_is_read(self):
        old = status(follows=True)                        # written at T0
        mine = Switches(follows=False, one_click=True)
        self.assertEqual(switch_model.switches_to_show(old, mine, changed_at=T0 + 5), mine)
        self.assertEqual(switch_model.switches_to_show(old, mine, changed_at=T0 - 5), switches_of(old))
        self.assertEqual(switch_model.switches_to_show(old, mine, changed_at=None), switches_of(old))
        self.assertEqual(switch_model.switches_to_show(None, mine, changed_at=None), mine)


class PlanTest(unittest.TestCase):
    def test_a_switch_windowtally_can_make_runs_unless_sessions_are_at_work(self):
        s = status()
        beta = s.account(ACCOUNT_B)
        self.assertEqual(switch_model.plan_app_switch(beta, 0), switch_model.Plan(switch_model.RUN))
        self.assertEqual(switch_model.plan_app_switch(beta, 2), switch_model.Plan(switch_model.CONFIRM_SESSIONS, 2))

    def test_an_account_with_no_stored_desktop_login_is_explained_whatever_else(self):
        gamma = status().account(ACCOUNT_C)
        self.assertEqual(switch_model.plan_app_switch(gamma, 0), switch_model.Plan(switch_model.NEEDS_LOGIN))
        self.assertEqual(switch_model.plan_app_switch(gamma, 3), switch_model.Plan(switch_model.NEEDS_LOGIN))

    def test_storing_the_login_in_use_closes_the_app_too(self):
        self.assertEqual(switch_model.plan_close(0), switch_model.Plan(switch_model.RUN))
        self.assertEqual(switch_model.plan_close(1), switch_model.Plan(switch_model.CONFIRM_SESSIONS, 1))


class CardsTest(unittest.TestCase):
    def test_the_cards_and_the_header_carry_the_offers_and_the_mode(self):
        snapshot = snapshot_of(Path("status.json"), json.dumps(status_document(
            [status_account(ACCOUNT_A, EMAIL_A, at=T0), status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False, cli=False)],
            at=T0, oneClickDesktop=True, syncFollows=False)))
        view = live_view(snapshot, T0 + 30)
        alpha, beta = view.cards
        self.assertEqual(alpha.switches, ())
        self.assertEqual([b.text for b in beta.switches], ["Switch app here", "Switch CLI here"])
        self.assertTrue(view.header.in_use_line.endswith("the CLI and the app switch apart"))

    def test_the_switches_the_user_just_set_are_what_the_cards_follow(self):
        snapshot = snapshot_of(Path("status.json"), json.dumps(status_document(
            [status_account(ACCOUNT_A, EMAIL_A, at=T0), status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False, cli=False)],
            at=T0, oneClickDesktop=True)))
        view = live_view(snapshot, T0 + 30, Switches(follows=False, one_click=False))
        self.assertEqual([b.text for b in view.cards[1].switches], ["Switch CLI here"])
        self.assertIn("switch apart", view.header.in_use_line)


class SyncCommandTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.paths = self.machine.paths

    def tearDown(self):
        self.machine.close()

    def test_the_command_runs_the_installed_script_by_path_in_the_mode_asked(self):
        argv = sync_model.command(self.paths, "SwitchDesktop", account=ACCOUNT_B)
        self.assertTrue(os.path.isabs(argv[0]) and argv[0].endswith("powershell.exe"), "Windows PowerShell by its path")
        self.assertEqual(argv[argv.index("-File") + 1], str(self.paths.claude_home / "bin" / "WindowTallySync.ps1"))
        self.assertEqual(argv[argv.index("-Mode") + 1:], ["SwitchDesktop", "-Account", ACCOUNT_B])
        self.assertIn("-NonInteractive", argv)

    def test_a_switch_is_turned_with_on_or_off(self):
        self.assertEqual(sync_model.command(self.paths, "Settings", follows=False)[-2:], ["-Follows", "Off"])
        self.assertEqual(sync_model.command(self.paths, "Settings", one_click=True)[-2:], ["-OneClick", "On"])

    def test_the_login_terminal_runs_the_launchers_auth_login_in_a_console_of_its_own(self):
        seen = {}

        def popen(argv, **kwargs):
            seen.update(argv=argv, kwargs=kwargs)

        sync_model.open_login_terminal(self.paths, popen=popen)
        self.assertIn("-NoExit", seen["argv"])
        self.assertTrue(seen["argv"][-1].endswith("claude.cmd' auth login"))
        self.assertEqual(seen["kwargs"]["creationflags"], sync_model._NEW_CONSOLE)

    def test_the_reason_is_the_scripts_last_note_without_its_marker(self):
        self.assertEqual(sync_model.reason(Result(2, ("Closing the desktop app...", "Refused: the app refused. Nothing was changed."))),
                         "the app refused. Nothing was changed.")
        self.assertEqual(sync_model.reason(Result(1, ("Error: boom",))), "boom")
        self.assertEqual(sync_model.reason(Result(1, ())), "the sync script ended with exit code 1")


def child(code: str) -> list[str]:
    return [sys.executable, "-I", "-u", "-c", code]


class SyncRunTest(unittest.TestCase):
    def finish(self, run: SyncRun) -> Result:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = run.poll()
            if result is not None:
                return result
            time.sleep(0.02)
        self.fail("the run did not end")

    def wait_for_note(self, run: SyncRun, text: str) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            run.poll()
            if any(note.startswith(text) for note in run.notes):
                return
            time.sleep(0.02)
        self.fail(f"no note {text!r}")

    def test_the_notes_and_the_exit_code_come_back_whole(self):
        run = SyncRun(child("import sys; print('[windowtally-sync] one', file=sys.stderr); "
                            "print('[windowtally-sync] Refused: two', file=sys.stderr); sys.exit(2)"))
        result = self.finish(run)
        self.assertEqual((result.code, result.notes), (2, ("one", "Refused: two")))

    def test_a_run_that_writes_nothing_has_its_code_and_no_notes(self):
        result = self.finish(SyncRun(child("raise SystemExit(0)")))
        self.assertEqual((result.code, result.notes), (0, ()))

    def test_a_run_can_be_called_off_before_the_app_is_closed(self):
        run = SyncRun(child("import sys, time; print('[windowtally-sync] Switching', file=sys.stderr); time.sleep(60)"))
        self.wait_for_note(run, "Switching")
        self.assertFalse(run.closing)
        self.assertTrue(run.cancel())
        result = self.finish(run)
        self.assertTrue(run.cancelled)
        self.assertNotEqual(result.code, 0)

    def test_a_run_cannot_be_called_off_once_the_app_is_closing(self):
        run = SyncRun(child("import sys, time; print('[windowtally-sync] Closing the desktop app...', file=sys.stderr); "
                            "time.sleep(60)"))
        try:
            self.wait_for_note(run, "Closing the desktop app")
            self.assertTrue(run.closing)
            self.assertFalse(run.cancel())
            self.assertFalse(run.cancelled)
        finally:
            run.process.kill()
            run.process.wait()

    def test_a_run_says_when_the_app_is_starting_again(self):
        run = SyncRun(child("import sys; print('[windowtally-sync] Closing the desktop app...', file=sys.stderr); "
                            "print('[windowtally-sync] Starting the desktop app on beta and watching it sign in...', "
                            "file=sys.stderr)"))
        self.finish(run)
        self.assertTrue(run.closing and run.starting)

    def test_a_run_that_waits_for_the_app_to_save_a_sign_in_says_so_and_can_still_be_called_off(self):
        run = SyncRun(child("import sys, time; print('[windowtally-sync] Waiting for the desktop app to save its sign-in of "
                            "09:41:07 before closing it...', file=sys.stderr); time.sleep(60)"))
        self.wait_for_note(run, "Waiting for the desktop app")
        self.assertTrue(run.saving)
        self.assertFalse(run.closing)
        self.assertTrue(run.cancel())
        self.finish(run)
        self.assertTrue(run.cancelled)

    def test_a_run_that_is_over_cannot_be_called_off(self):
        run = SyncRun(child("pass"))
        self.finish(run)
        self.assertFalse(run.cancel())


class FakeRun:
    """A run the flow's tests script: it ends with ``result`` at its ``after``-th poll."""

    started: list = []

    def __init__(self, argv, result: Result | None = None, after: int = 1, closing: bool = False,
                 starting: bool = False, saving: bool = False):
        self.argv, self.result, self.after, self.polls = argv, result, after, 0
        self.closing, self.starting, self.cancelled, self.cancel_allowed = closing, starting, False, True
        self.saving = saving
        FakeRun.started.append(self)

    def poll(self):
        self.polls += 1
        return self.result if self.result is not None and self.polls >= self.after else None

    def cancel(self) -> bool:
        if self.closing or not self.cancel_allowed:
            return False
        self.cancelled = True
        self.result = Result(1, ())
        return True


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.paths = self.machine.paths
        FakeRun.started = []
        self.now = 1000.0
        self.at_work = 0
        self.results: list[Result] = []

    def tearDown(self):
        self.machine.close()

    def start(self, argv):
        return FakeRun(argv, self.results.pop(0) if self.results else Result(0, ()))

    def flow(self) -> SwitchFlow:
        return SwitchFlow(self.paths, sessions=lambda: self.at_work, start=self.start, clock=lambda: self.now, retry=5.0)

    def test_an_app_switch_runs_the_script_for_the_account_then_says_so_and_asks_for_a_pass(self):
        flow = self.flow()
        self.assertTrue(flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False))
        self.assertEqual(FakeRun.started[0].argv[-4:], ["-Mode", "SwitchDesktop", "-Account", ACCOUNT_B])
        self.assertEqual(flow.progress.text, "Switching the desktop app to beta…")
        self.assertTrue(flow.progress.cancellable)
        [done] = flow.tick()
        self.assertEqual(done, Done(flow_model.Outcome(True, "Switched the desktop app to beta. The CLI follows it as soon as no CLI is running."), True))
        self.assertFalse(flow.busy)
        self.assertIsNone(flow.progress)

    def test_a_start_of_the_desktop_app_runs_the_script_cannot_be_called_off_and_says_the_scripts_word(self):
        self.results = [Result(0, ("Starting the desktop app...", "Started the desktop app."))]
        flow = self.flow()
        self.assertTrue(flow.start_app())
        self.assertEqual(FakeRun.started[0].argv[-2:], ["-Mode", "StartDesktop"])
        self.assertEqual(flow.progress, flow_model.STARTING)
        self.assertEqual(flow.progress.text, "Starting the desktop app…")
        self.assertFalse(flow.progress.cancellable)
        self.assertFalse(flow.cancel(), "a start is never called off")
        self.assertFalse(FakeRun.started[0].cancelled)
        [done] = flow.tick()
        self.assertEqual(done, Done(flow_model.Outcome(True, "Started the desktop app."), True))
        self.assertEqual(done.kind, flow_model.START)
        self.assertFalse(flow.busy)

    def test_a_start_refused_while_another_act_runs_is_not_done_in_the_scripts_words(self):
        self.results = [Result(2, ("Another account sync is still running; nothing was changed. Try again in a moment.",))]
        flow = self.flow()
        flow.start_app()
        [done] = flow.tick()
        self.assertEqual(done.outcome, flow_model.Outcome(
            False, "Not done: Another account sync is still running; nothing was changed. Try again in a moment."))
        self.assertEqual(done.kind, flow_model.START)

    def test_a_start_waits_its_turn_behind_a_switch(self):
        flow = self.flow()
        flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False)
        self.assertFalse(flow.start_app(), "one job at a time")
        self.assertEqual(len(FakeRun.started), 1)

    def test_with_the_two_apart_the_message_does_not_promise_the_cli(self):
        flow = self.flow()
        flow.switch_app(ACCOUNT_B, "beta", follows=False, wait=False)
        [done] = flow.tick()
        self.assertEqual(done.outcome.message, "Switched the desktop app to beta.")

    def test_one_job_at_a_time(self):
        flow = self.flow()
        self.assertTrue(flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False))
        self.assertFalse(flow.switch_cli(ACCOUNT_B, "beta"))
        self.assertFalse(flow.set_switch(follows=False))
        self.assertEqual(len(FakeRun.started), 1)

    def test_waiting_for_the_sessions_runs_the_switch_once_none_is_at_work(self):
        self.at_work = 2
        flow = self.flow()
        flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=True)
        self.assertEqual(FakeRun.started, [], "nothing is run while sessions work")
        self.assertEqual(flow.progress.text, "Waiting for 2 working sessions to finish before switching the desktop app to beta…")
        self.assertTrue(flow.progress.cancellable)
        self.assertEqual(flow.tick(), [])
        self.at_work = 1
        flow.tick()
        self.assertEqual(flow.progress.text, "Waiting for 1 working session to finish before switching the desktop app to beta…")
        self.at_work = 0
        flow.tick()
        self.assertEqual(len(FakeRun.started), 1)
        self.assertEqual(flow.progress.text, "Switching the desktop app to beta…")

    def test_switching_anyway_does_not_wait(self):
        self.at_work = 3
        flow = self.flow()
        flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False)
        self.assertEqual(len(FakeRun.started), 1)

    def test_a_wait_can_always_be_called_off(self):
        self.at_work = 1
        for job in ("switch", "add"):
            flow = self.flow()
            if job == "switch":
                flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=True)
            else:
                flow.add_account(wait=True)
            self.assertTrue(flow.progress.cancellable, job)
            self.assertTrue(flow.cancel(), job)
            self.assertFalse(flow.busy, job)
            self.assertEqual(flow.tick(), [], job)
        self.assertEqual(FakeRun.started, [])

    def test_a_run_called_off_before_the_app_closes_says_nothing_was_changed(self):
        flow = self.flow()
        flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False)
        FakeRun.started[0].result = None
        self.assertTrue(flow.cancel())
        FakeRun.started[0].result = Result(1, ())
        [done] = flow.tick()
        self.assertEqual(done, Done(flow_model.Outcome(False, "Cancelled; nothing was changed."), False))
        self.assertFalse(flow.busy)

    def test_a_run_cannot_be_called_off_once_the_app_is_closing_and_the_header_says_so(self):
        flow = self.flow()
        flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False)
        run = FakeRun.started[0]
        run.result, run.closing = None, True
        self.assertFalse(flow.progress.cancellable)
        self.assertIn("can no longer be called off", flow.progress.text)
        self.assertFalse(flow.cancel())
        self.assertTrue(flow.busy)

    def test_once_the_app_is_starting_again_the_header_says_it_waits_for_the_sign_in(self):
        flow = self.flow()
        flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False)
        run = FakeRun.started[0]
        run.result, run.closing, run.starting = None, True, True
        self.assertEqual(flow.progress, flow_model.Progress(
            "Switching the desktop app to beta… The desktop app is starting; waiting for it to sign in.", False))
        self.assertFalse(flow.cancel())

    def test_a_switch_the_app_comes_up_signed_out_from_asks_for_a_pass_under_the_scripts_words(self):
        # The script says why the app refused the login and whether it could be set aside; its words stand either way.
        for said in ("Switched the desktop app to beta, but the app refused the login stored for it and is at its "
                     "sign-in page: that login held no sign-in cookie, as it was stored before the app had saved its "
                     "sign-in. It is set aside. Sign in to beta in the app; WindowTally stores that login when you next "
                     "switch away.",
                     "Switched the desktop app to beta, but the app refused the login stored for it and is at its "
                     "sign-in page. It could not be set aside (access denied). Sign in to beta in the app."):
            self.results = [Result(5, ("Starting the desktop app on beta and watching it sign in...", said))]
            flow = self.flow()
            flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False)
            [done] = flow.tick()
            self.assertEqual(done, Done(flow_model.Outcome(False, said), True),
                             "not done, in the script's words, and a pass shows the app at its sign-in page at once")
            self.assertFalse(flow.busy)

    def test_while_the_app_saves_a_sign_in_before_it_closes_the_header_says_so_and_it_can_be_called_off(self):
        for job in ("switch", "add"):
            flow = self.flow()
            if job == "switch":
                flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False)
            else:
                flow.add_account(wait=False)
            run = FakeRun.started[-1]
            run.result, run.saving = None, True
            deed = "Switching the desktop app to beta…" if job == "switch" else "Opening the desktop app's sign-in page…"
            self.assertEqual(flow.progress, flow_model.Progress(
                deed + " The desktop app is saving its sign-in first; this can still be called off.", True))
            run.closing = True
            self.assertEqual(flow.progress, flow_model.Progress(
                deed + " The desktop app is closing; this can no longer be called off.", False),
                "once it closes the app, the close is what the header says")
            run.closing = False
            self.assertTrue(flow.cancel())
            [done] = flow.tick()
            self.assertEqual(done, Done(flow_model.Outcome(False, "Cancelled; nothing was changed."), False))

    def test_a_refusal_is_said_in_the_scripts_words_and_asks_for_no_pass(self):
        self.results = [Result(2, ("Refused: the desktop app refused to close. Nothing was changed; close the app yourself and try again.",))]
        flow = self.flow()
        flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False)
        [done] = flow.tick()
        self.assertEqual(done, Done(flow_model.Outcome(
            False, "Not done: the desktop app refused to close. Nothing was changed; close the app yourself and try again."), False))

    def test_turning_a_switch_says_what_it_did(self):
        flow = self.flow()
        for kwargs, words in (({"follows": True}, "The CLI follows the desktop app again; it is aligned with the app as soon as no CLI is running."),
                              ({"follows": False}, "The CLI no longer follows the desktop app: the app and the CLI switch apart."),
                              ({"one_click": True}, "One-click switching of the desktop app is on."),
                              ({"one_click": False}, "One-click switching of the desktop app is off; the logins already stored are kept.")):
            flow.set_switch(**kwargs)
            self.assertEqual(flow.tick()[0].outcome.message, words)
        self.assertEqual(FakeRun.started[-1].argv[-4:], ["-Mode", "Settings", "-OneClick", "Off"])

    def test_a_cli_that_is_running_is_asked_about_and_the_switch_is_tried_again_until_it_goes_through(self):
        self.results = [Result(4, ("Refused: a CLI is still running.",)), Result(4, ("Refused: a CLI is still running.",)),
                        Result(0, ())]
        flow = self.flow()
        flow.switch_cli(ACCOUNT_B, "beta")
        self.assertEqual(flow.tick(), [AskCliIdle("beta")])
        self.assertTrue(flow.busy)
        self.assertIsNone(flow.progress, "the question is on the screen")
        self.assertEqual(flow.tick(), [], "nothing happens until it is answered")
        flow.wait_for_cli()
        self.assertEqual(flow.progress.text, "Waiting for the running CLI to exit before switching the CLI to beta…")
        self.now += 4.9
        self.assertEqual(flow.tick(), [])
        self.assertEqual(len(FakeRun.started), 1, "not before the retry time")
        self.now += 0.2
        flow.tick()
        self.assertEqual(len(FakeRun.started), 2)
        self.assertEqual(flow.tick(), [], "still running: back to waiting, no second question")
        self.assertEqual(flow.progress.text, "Waiting for the running CLI to exit before switching the CLI to beta…")
        self.now += 5.1
        flow.tick()
        [done] = flow.tick()
        self.assertEqual(done, Done(flow_model.Outcome(True, "Switched the CLI to beta."), True))

    def test_declining_to_wait_ends_the_job(self):
        self.results = [Result(4, ())]
        flow = self.flow()
        flow.switch_cli(ACCOUNT_B, "beta")
        self.assertEqual(flow.tick(), [AskCliIdle("beta")])
        self.assertTrue(flow.cancel())
        self.assertFalse(flow.busy)

    def test_a_cli_with_no_stored_login_sends_the_window_to_a_terminal(self):
        self.results = [Result(3, ("No usable CLI sign-in is stored for beta@example.com.",))]
        flow = self.flow()
        flow.switch_cli(ACCOUNT_B, "beta")
        self.assertEqual(flow.tick(), [NeedsCliLogin("beta")])
        self.assertFalse(flow.busy)

    def test_a_script_that_cannot_be_started_is_said(self):
        def refuse(_argv):
            raise FileNotFoundError("no powershell")

        flow = SwitchFlow(self.paths, sessions=lambda: 0, start=refuse, clock=lambda: 0.0)
        self.assertTrue(flow.switch_app(ACCOUNT_B, "beta", follows=True, wait=False))
        self.assertIsNone(flow.progress)
        [done] = flow.tick()
        self.assertFalse(done.outcome.ok)
        self.assertIn("could not be started (no powershell)", done.outcome.message)
        self.assertFalse(flow.busy)

    def test_adding_an_account_runs_the_add_and_ends_in_the_scripts_words_with_a_pass(self):
        said = ("The desktop app is at its sign-in page. The login of alpha@example.com is stored and still good. Sign "
                "in there to the account to add; WindowTally stores that login when you next switch away from it.")
        self.results = [Result(0, ("Closing the desktop app...", "Starting the desktop app at its sign-in page...", said))]
        flow = self.flow()
        self.assertTrue(flow.add_account(wait=False))
        self.assertEqual(FakeRun.started[0].argv[-2:], ["-Mode", "AddDesktop"])
        self.assertEqual(flow.progress, flow_model.Progress("Opening the desktop app's sign-in page…", True))
        [done] = flow.tick()
        self.assertEqual(done, Done(flow_model.Outcome(True, said), True), "a pass shows the login now stored")
        self.assertFalse(flow.busy)

    def test_an_add_that_says_nothing_ends_in_the_windows_words(self):
        self.results = [Result(0, ())]
        flow = self.flow()
        flow.add_account(wait=False)
        [done] = flow.tick()
        self.assertEqual(done, Done(flow_model.Outcome(
            True, "The desktop app is at its sign-in page: sign in there to the account to add."), True))

    def test_while_the_app_starts_for_an_add_the_header_says_it_waits_for_its_sign_in_page(self):
        flow = self.flow()
        flow.add_account(wait=False)
        run = FakeRun.started[0]
        run.result, run.closing, run.starting = None, True, True
        self.assertEqual(flow.progress, flow_model.Progress(
            "Opening the desktop app's sign-in page… The desktop app is starting; waiting for its sign-in page.", False))
        self.assertFalse(flow.cancel())

    def test_an_add_waits_for_the_sessions_at_work_and_one_that_fails_is_not_done(self):
        self.at_work = 2
        self.results = [Result(1, ("Error: the desktop app came up signed in, so it could not be left at its sign-in "
                                   "page.",))]
        flow = self.flow()
        flow.add_account(wait=True)
        self.assertEqual(FakeRun.started, [], "nothing is run while sessions work")
        self.assertEqual(flow.progress.text,
                         "Waiting for 2 working sessions to finish before opening the desktop app's sign-in page…")
        self.at_work = 0
        self.assertEqual(flow.tick(), [])
        [done] = flow.tick()
        self.assertEqual(done, Done(flow_model.Outcome(
            False, "Not done: the desktop app came up signed in, so it could not be left at its sign-in page."), False))
        self.assertFalse(flow.busy)


class SessionsAtWorkTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()

    def tearDown(self):
        self.machine.close()

    def test_the_count_is_taken_off_the_registry_not_off_the_status(self):
        home = self.machine.paths.claude_home
        self.assertEqual(actions_model.working_sessions(self.machine.paths), 0, "no folder, no session at work")
        for name, status, pid, created in (("a", "busy", None, None), ("b", "busy", os.getppid(), 1),
                                           ("c", "idle", 2 ** 31 - 1, 1)):
            register_session(home, name, status=status, pid=pid, created=created)
        self.assertEqual(actions_model.working_sessions(self.machine.paths), 1)


class SignedOutAppTest(unittest.TestCase):
    """The desktop app at its sign-in page, having left alpha, whose login is stored: no account is the app's."""

    def snapshot(self):
        accounts = [status_account(ACCOUNT_A, EMAIL_A, at=T0, desktop=False),
                    status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False, cli=False)]
        accounts[0]["desktopArchived"] = True
        doc = status_document(accounts, at=T0, desktopAccount=None, desktopSignedIn=False, oneClickDesktop=True)
        return snapshot_of(Path("status.json"), json.dumps(doc))

    def test_the_status_says_so_and_one_without_the_key_does_not(self):
        self.assertFalse(self.snapshot().status.desktop_signed_in)
        self.assertTrue(status().desktop_signed_in)

    def test_every_card_offers_the_app_the_account_left_included_and_the_header_says_where_it_is(self):
        view = live_view(self.snapshot(), T0 + 30)
        alpha, beta = view.cards
        self.assertEqual([b.text for b in alpha.switches], ["Switch here"])
        self.assertEqual([b.text for b in beta.switches], ["Switch here"])
        self.assertEqual(alpha.tags, ("CLI", "use next"))
        self.assertEqual(view.header.in_use_line,
                         "Desktop app: at its sign-in page · CLI: alpha · the CLI follows the app")
        s = self.snapshot().status
        self.assertEqual([e.uuid for e in switch_model.switch_entries(s, APP, switches_of(s))], [ACCOUNT_A, ACCOUNT_B])

    def test_the_account_left_is_switched_back_to_and_one_with_no_stored_login_is_explained(self):
        s = self.snapshot().status
        self.assertEqual(switch_model.plan_app_switch(s.account(ACCOUNT_A), 0), switch_model.Plan(switch_model.RUN))
        self.assertEqual(switch_model.plan_app_switch(s.account(ACCOUNT_B), 0),
                         switch_model.Plan(switch_model.NEEDS_LOGIN))

    def test_the_tray_draws_the_clis_account(self):
        self.assertEqual(tray_view(self.snapshot(), T0 + 30).account, ACCOUNT_A)


if __name__ == "__main__":
    unittest.main()
