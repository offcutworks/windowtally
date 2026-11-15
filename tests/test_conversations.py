"""Every account's Code sessions as the Conversations window lists them: read from the ledger — each session's title,
folder, last activity, account and use — then named, sorted into projects, searched and filtered, the line saying where
one opens, and the command that resumes one in a terminal."""

import json
import time
import unittest
from pathlib import Path

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, epoch,
                      status_account, status_document, user_line)
from test_sessions import RESETS, prompt_line, stop_line, title_line
from windowtally.attribution import attribute
from windowtally.history import UNATTRIBUTED
from windowtally.ingest_sync import ingest_sync_events
from windowtally.ingest_transcripts import ingest_transcripts
from windowtally.ledger import Ledger
from windowtally.service import run_pass
from windowtally.sessions import Conversation, conversations, sessions_of
from windowtally_gui import conversations_model
from windowtally_gui.conversations_model import (APP_UNKNOWN, NO_STATUS, NOT_RUNNING, SIGNED_OUT, SWITCHING,
                                                 UNKNOWN_ACCOUNT, Refresh, Row, count_words, handed_words, last_text,
                                                 matches, opening, project_of, resume_command, rows_of, search_words)
from windowtally_gui.status_model import parse_status

T0 = epoch("2026-11-08T10:00:00Z")


def in_folder(lines: list[dict], folder: str) -> list[dict]:
    """The lines of a response as Claude Code writes them in ``folder``."""
    for line in lines:
        line["cwd"] = folder
    return lines


def events(machine: Machine, *points: tuple[float, str, str]) -> None:
    machine.sync_events(list(points))


class ReadCase(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        # The app and the CLI on alpha until T0, then on beta.
        events(self.machine, (T0 - 2 * 86400, "desktop_account", ACCOUNT_A), (T0 - 2 * 86400, "cli_account", ACCOUNT_A),
               (T0, "desktop_account", ACCOUNT_B), (T0, "cli_account", ACCOUNT_B))

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def build(self):
        ingest_transcripts(self.ledger, self.machine.paths.projects_dir)
        ingest_sync_events(self.ledger, self.machine.paths.sync_events)
        attribute(self.ledger)

    def by_id(self) -> dict[str, Conversation]:
        return {c.session_id: c for c in conversations(self.ledger)}


class ReadTest(ReadCase):
    def test_every_accounts_sessions_of_the_app_and_the_cli_the_latest_first(self):
        self.machine.transcript("parser", [title_line("parser", "Refactor the parser")]
                                + assistant_lines("m1", T0 - 7200, "parser"))
        self.machine.transcript("terminal", in_folder(assistant_lines("m2", T0 + 600, "terminal", entrypoint="cli"),
                                                      "D:\\Work\\Tools"))
        self.machine.transcript("headless", assistant_lines("m3", T0 + 900, "headless", entrypoint="sdk-cli"))
        self.build()
        found = conversations(self.ledger)
        self.assertEqual([c.session_id for c in found], ["terminal", "parser"], "an SDK run is left out")
        terminal, parser = found
        self.assertEqual((parser.title, parser.folder, parser.account_uuid, parser.desktop),
                         ("Refactor the parser", "D:\\Work\\Project", ACCOUNT_A, True))
        self.assertEqual((terminal.title, terminal.folder, terminal.account_uuid, terminal.desktop),
                         (None, "D:\\Work\\Tools", ACCOUNT_B, False))
        self.assertIsNone(parser.stop_kind)

    def test_the_folder_is_the_one_it_started_in_and_the_use_counts_its_subagents(self):
        self.machine.transcript("moved", in_folder(assistant_lines("m1", T0 - 900, "moved"), "D:\\Work\\Start")
                                + in_folder(assistant_lines("m2", T0 - 600, "moved"), "D:\\Work\\Start\\deeper"))
        self.machine.transcript("moved", assistant_lines("m3", T0 - 700, "moved", agent_id="a1"), agent="a1")
        self.build()
        moved = self.by_id()["moved"]
        self.assertEqual(moved.folder, "D:\\Work\\Start")
        spent = self.ledger.db.execute("SELECT SUM(cost_usd) FROM responses WHERE session_id='moved'").fetchone()[0]
        self.assertGreater(spent, 0)
        self.assertAlmostEqual(moved.used_usd, spent)
        self.assertEqual(moved.last_activity, T0 - 600, "its latest answer")
        [line] = sessions_of(self.ledger, ACCOUNT_A, T0)
        self.assertEqual(line.project, "D:\\Work\\Start", "the switch names a session by the same folder")

    def test_a_stop_that_stands_gives_the_session_its_account_and_one_answered_after_does_not(self):
        self.machine.transcript("waiting", assistant_lines("m1", T0 - 600, "waiting")
                                + [stop_line("waiting", T0 + 60, "u1", kind="seven_day")])
        self.machine.transcript("answered", assistant_lines("m2", T0 - 900, "answered")
                                + [stop_line("answered", T0 - 800, "u2")] + assistant_lines("m3", T0 - 100, "answered"))
        self.build()
        waiting, answered = self.by_id()["waiting"], self.by_id()["answered"]
        self.assertEqual((waiting.stop_kind, waiting.account_uuid, waiting.last_activity),
                         ("seven_day", ACCOUNT_B, T0 + 60))
        self.assertTrue(waiting.stopped)
        self.assertEqual((answered.stop_kind, answered.account_uuid), (None, ACCOUNT_A))

    def test_a_stop_given_no_account_yet_leaves_the_session_its_latest_answers_on_both_surfaces(self):
        self.machine.transcript("waiting", assistant_lines("m1", T0 - 600, "waiting")
                                + [stop_line("waiting", T0 - 300, "u1")])
        self.build()
        with self.ledger.transaction():
            self.ledger.db.execute("UPDATE limit_stops SET account_uuid=NULL")
        waiting = self.by_id()["waiting"]
        self.assertEqual((waiting.account_uuid, waiting.stop_kind), (ACCOUNT_A, "five_hour"))
        [line] = sessions_of(self.ledger, ACCOUNT_A, T0)
        self.assertEqual((line.session_id, line.stop_kind), ("waiting", "five_hour"))

    def test_a_session_says_the_effort_of_its_latest_main_answer_and_the_mode_it_last_named(self):
        self.machine.transcript("s1", [prompt_line("s1", "p1", T0 - 950, "acceptEdits")]
                                + assistant_lines("m1", T0 - 900, "s1", effort="xhigh")
                                + assistant_lines("m2", T0 - 600, "s1", effort="max"))
        self.machine.transcript("s1", assistant_lines("m3", T0 - 500, "s1", effort="low", agent_id="a1"), agent="a1")
        self.machine.transcript("s2", assistant_lines("m4", T0 - 300, "s2", effort=None))
        self.build()
        found = self.by_id()
        self.assertEqual((found["s1"].effort, found["s1"].mode), ("max", "acceptEdits"),
                         "a subagent's effort is not its session's")
        self.assertEqual((found["s2"].effort, found["s2"].mode), (None, None))

    def test_a_subagents_answer_says_which_client_ran_its_session(self):
        self.machine.transcript("helper", assistant_lines("m1", T0 - 600, "helper", agent_id="a1"), agent="a1")
        self.build()
        helper = self.by_id()["helper"]
        self.assertEqual((helper.desktop, helper.folder, helper.account_uuid), (True, None, ACCOUNT_A))
        self.assertEqual([line.session_id for line in sessions_of(self.ledger, ACCOUNT_A, T0)], ["helper"])

    def test_a_session_a_limit_stopped_before_any_answer_is_listed_with_no_folder(self):
        self.machine.transcript("refused", [user_line("refused", "p1", T0 - 70), stop_line("refused", T0 - 60, "u1")])
        self.build()
        refused = self.by_id()["refused"]
        self.assertEqual((refused.folder, refused.account_uuid, refused.used_usd, refused.stop_kind, refused.desktop),
                         (None, ACCOUNT_A, 0.0, "five_hour", True))

    def test_a_prompt_with_no_answer_or_stop_is_no_session_and_a_later_prompt_is_activity(self):
        self.machine.transcript("empty", [user_line("empty", "p1", T0 - 60)])
        self.machine.transcript("asked", assistant_lines("m1", T0 - 600, "asked") + [user_line("asked", "p2", T0 - 30)])
        self.build()
        found = self.by_id()
        self.assertNotIn("empty", found)
        self.assertEqual(found["asked"].last_activity, T0 - 30)

    def test_an_answer_no_account_could_be_given_to_leaves_the_session_with_none(self):
        self.machine.transcript("before", assistant_lines("m1", T0 - 30 * 86400, "before"))
        self.build()
        self.assertIsNone(self.by_id()["before"].account_uuid, "before either timeline begins, with no owner line")

    def test_a_ledger_no_pass_of_this_code_opened_lists_its_sessions_without_titles_or_stops(self):
        self.machine.transcript("s1", [title_line("s1", "Mine")] + assistant_lines("m1", T0 - 600, "s1")
                                + [stop_line("s1", T0 - 60, "u1")])
        self.build()
        with self.ledger.transaction():
            self.ledger.db.execute("DROP TABLE session_titles")
            self.ledger.db.execute("DROP TABLE limit_stops")
        reader = Ledger.open_readonly(self.machine.paths.ledger_db)
        try:
            [found] = conversations(reader)
        finally:
            reader.close()
        self.assertEqual((found.title, found.stop_kind, found.last_activity), (None, None, T0 - 600))


def conversation(session_id, *, title=None, folder="D:\\Work\\Project", account=ACCOUNT_A, used=1.5, desktop=True,
                 stop=None, last=T0, effort=None, mode=None) -> Conversation:
    return Conversation(session_id, title, folder, last, account, used, desktop, stop, effort, mode)


NAMES = {ACCOUNT_A: "Work", ACCOUNT_B: "Studio"}


def row(session_id, **changes) -> Row:
    exists = changes.pop("exists", True)
    [made] = rows_of([conversation(session_id, **changes)], NAMES, {changes.get("folder", "D:\\Work\\Project"): exists})
    return made


class RowsTest(unittest.TestCase):
    def test_a_row_names_its_session_project_and_account_and_says_its_use_in_dollars(self):
        made = row("s1", title="  Refactor the parser ", used=1234.567)
        self.assertEqual((made.title, made.project, made.project_key, made.account, made.account_key, made.used),
                         ("Refactor the parser", "Project", "d:\\work\\project", "Work", ACCOUNT_A, "$1,234.57"))
        self.assertTrue(made.folder_exists)

    def test_an_untitled_session_is_named_by_its_folder_and_one_no_account_ran_says_so(self):
        made = row("s1", folder="D:\\Work\\Parser", account=None, exists=False)
        self.assertEqual((made.title, made.account, made.account_key, made.folder_exists),
                         ("Untitled session in Parser", UNATTRIBUTED.label, UNKNOWN_ACCOUNT, False))
        self.assertEqual(row("s2", folder=None).title, "Untitled session")
        self.assertEqual(row("s3", account="cccccccc-0000").account, "cccccccc", "an account the ledger does not name")

    def test_a_working_copy_inside_a_repository_stands_under_the_repository(self):
        self.assertEqual(str(project_of("D:\\Work\\Tools\\.claude\\worktrees\\fix-it")), "D:\\Work\\Tools")
        self.assertEqual(str(project_of("D:\\Work\\Tools\\.Claude\\Worktrees\\fix-it\\sub")), "D:\\Work\\Tools")
        self.assertEqual(str(project_of("D:\\Work\\Tools")), "D:\\Work\\Tools")
        self.assertEqual(str(project_of("D:\\Work\\.claude\\worktrees")), "D:\\Work\\.claude\\worktrees",
                         "the folder of working copies is no working copy")
        made = row("s1", folder="D:\\Work\\Tools\\.claude\\worktrees\\fix-it")
        self.assertEqual((made.project, made.project_folder, made.folder),
                         ("Tools", "D:\\Work\\Tools", "D:\\Work\\Tools\\.claude\\worktrees\\fix-it"))
        self.assertEqual(row("s2", folder="D:\\").project, "D:\\")

    def test_the_filters_offer_each_account_by_name_and_each_project_once_told_apart_where_names_meet(self):
        rows = rows_of([conversation("s1", account=ACCOUNT_B, folder="D:\\Work\\Project"),
                        conversation("s2", account=None, folder="E:\\Other\\Project"),
                        conversation("s3", folder="D:\\Work\\Tools\\.claude\\worktrees\\a"),
                        conversation("s4", folder="D:\\Work\\Tools")], NAMES, {})
        accounts, projects = conversations_model._choices(rows)
        self.assertEqual(accounts, ((ACCOUNT_B, "Studio"), (ACCOUNT_A, "Work"), (UNKNOWN_ACCOUNT, UNATTRIBUTED.label)))
        self.assertEqual(projects, (("d:\\work\\project", "Project (D:\\Work)"), ("e:\\other\\project",
                                                                               "Project (E:\\Other)"),
                                    ("d:\\work\\tools", "Tools")))


class FilterTest(unittest.TestCase):
    def test_every_word_of_the_search_is_found_in_the_title_case_aside(self):
        made = row("s1", title="Refactor the Parser")
        self.assertEqual(search_words("  parser  REFACTOR "), ("parser", "refactor"))
        self.assertTrue(matches(made, search_words("parser refactor"), None, None))
        self.assertFalse(matches(made, search_words("parser lexer"), None, None))
        self.assertTrue(matches(made, (), None, None))

    def test_the_filters_keep_the_account_and_the_project_chosen(self):
        made = row("s1", account=ACCOUNT_B)
        self.assertTrue(matches(made, (), ACCOUNT_B, "d:\\work\\project"))
        self.assertFalse(matches(made, (), ACCOUNT_A, None))
        self.assertFalse(matches(made, (), None, "d:\\work\\tools"))
        self.assertTrue(matches(row("s2", account=None), (), UNKNOWN_ACCOUNT, None))

    def test_the_count_says_how_many_stand_of_how_many(self):
        self.assertEqual(count_words(1250, 1250), "1,250 sessions")
        self.assertEqual(count_words(1, 1), "1 session")
        self.assertEqual(count_words(12, 1250), "12 of 1,250 sessions")

    def test_a_last_activity_is_an_age_within_a_day_and_a_date_before(self):
        now = epoch("2026-11-09T12:00:00Z")
        self.assertEqual(last_text(now - 30, now), "just now")
        self.assertEqual(last_text(now - 3 * 3600 - 300, now), "3h 05m ago")
        self.assertRegex(last_text(now - 3 * 86400, now),
                         r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2} \d\d:\d\d$")
        self.assertRegex(last_text(epoch("2025-10-26T12:00:00Z"), now), r"^\d{1,2} Oct 2025$")


def status(**changes):
    now = time.time()
    accounts = [status_account(ACCOUNT_A, EMAIL_A, at=now), status_account(ACCOUNT_B, EMAIL_B, at=now, desktop=False,
                                                                           cli=False)]
    accounts[0]["label"], accounts[1]["label"] = "Work", "Studio"
    document = status_document(accounts, at=now, **{"desktopRunning": True, **changes})
    return parse_status(json.loads(json.dumps(document)))


class OpeningTest(unittest.TestCase):
    def test_a_session_opens_on_the_apps_account_in_the_app_or_with_the_command(self):
        shown = opening(row("s1"), status(), switching=False, working=frozenset())
        self.assertEqual(shown.words, "A session opens on Work, in the desktop app or with the resume command.")
        self.assertEqual((shown.can_open, shown.can_copy), (True, True))
        none = opening(None, status(), switching=False, working=frozenset())
        self.assertEqual((none.words, none.can_open, none.can_copy), (shown.words, False, False))

    def test_where_the_cli_is_on_another_account_the_line_names_both(self):
        shown = opening(row("s1"), status(cliAccount=ACCOUNT_B), switching=False, working=frozenset())
        self.assertEqual(shown.words, "A session opens on Work in the desktop app; the resume command runs on Studio.")

    def test_the_app_not_running_at_its_sign_in_page_switching_or_unknown_opens_nothing_there(self):
        for changes, switching, why in (({"desktopRunning": False}, False, NOT_RUNNING),
                                        ({"desktopSignedIn": False, "desktopAccount": None}, False, SIGNED_OUT),
                                        ({}, True, SWITCHING),
                                        ({"desktopAccount": "dddddddd-0000-4000-8000-000000000004"}, False,
                                         APP_UNKNOWN)):
            with self.subTest(why=why):
                shown = opening(row("s1"), status(**changes), switching=switching, working=frozenset())
                self.assertEqual(shown.words, f"{why} The resume command runs on Work.")
                self.assertEqual((shown.can_open, shown.can_copy), (False, True))
        shown = opening(row("s1"), None, switching=False, working=frozenset())
        self.assertEqual((shown.words, shown.can_open, shown.can_copy), (NO_STATUS, False, True))

    def test_a_session_the_cli_alone_ran_opens_with_the_command_alone(self):
        shown = opening(row("s1", desktop=False), status(), switching=False, working=frozenset())
        self.assertIn("The CLI alone ran it", shown.words)
        self.assertEqual((shown.can_open, shown.can_copy), (False, True))

    def test_a_working_session_gets_no_command_and_a_stopped_or_homeless_one_says_so(self):
        shown = opening(row("s1"), status(), switching=False, working=frozenset({"s1"}))
        self.assertIn("working in the desktop app now", shown.words)
        self.assertEqual((shown.can_open, shown.can_copy), (True, False))
        shown = opening(row("s2", stop="seven_day", exists=False), status(), switching=False, working=frozenset())
        self.assertIn("Stopped by the weekly limit.", shown.words)
        self.assertIn("Its folder is gone", shown.words)


class CommandTest(unittest.TestCase):
    def test_the_command_goes_on_in_the_sessions_own_folder_quoted_for_powershell(self):
        made = row("0b4c-11", folder="D:\\Work\\O'Brien [draft]")
        self.assertEqual(resume_command(made),
                         "Set-Location -LiteralPath 'D:\\Work\\O''Brien [draft]'; claude --resume 0b4c-11")

    def test_where_the_folder_is_gone_the_command_runs_where_it_is_started(self):
        self.assertEqual(resume_command(row("0b4c-11", exists=False)), "claude --resume 0b4c-11")
        self.assertEqual(resume_command(row("0b4c-12", folder=None)), "claude --resume 0b4c-12")

    def test_the_command_goes_on_at_the_effort_and_in_the_mode_the_session_last_ran_with(self):
        self.assertEqual(resume_command(row("0b4c-11", exists=False, effort="max", mode="auto")),
                         "claude --resume 0b4c-11 --effort max --permission-mode auto")
        made = row("0b4c-12", folder="D:\\Work\\Parser", effort="xhigh", mode="plan")
        self.assertEqual(resume_command(made), "Set-Location -LiteralPath 'D:\\Work\\Parser'; "
                                               "claude --resume 0b4c-12 --effort xhigh --permission-mode plan")
        self.assertEqual(made.ran_with, "xhigh · Plan")

    def test_a_value_the_cli_does_not_take_passes_nothing_the_default_passes_as_named_and_a_bypass_is_lowered(self):
        for effort, mode, tail in ((None, "default", " --permission-mode default"),
                                   ("max", "manual", " --effort max --permission-mode manual"),
                                   ("turbo", "auto", " --permission-mode auto"),
                                   ("high", "someNewMode", " --effort high"),
                                   (None, "bypassPermissions", " --permission-mode acceptEdits"),
                                   ("low", "dontAsk", " --effort low --permission-mode dontAsk"),
                                   ("medium", "acceptEdits", " --effort medium --permission-mode acceptEdits")):
            with self.subTest(effort=effort, mode=mode):
                self.assertEqual(resume_command(row("s1", exists=False, effort=effort, mode=mode)),
                                 "claude --resume s1" + tail)


class HandedTest(unittest.TestCase):
    def test_handing_a_session_over_says_what_it_ran_with_where_that_is_known(self):
        self.assertEqual(handed_words(row("s1", title="Lexer tests", effort="max", mode="auto")),
                         "Handed to the desktop app: Lexer tests. The app does not keep its effort and may not keep "
                         "its permission mode: it ran with max · Auto.")
        self.assertEqual(handed_words(row("s2", title="Lexer tests")), "Handed to the desktop app: Lexer tests.")


class RefreshTest(unittest.TestCase):
    def test_an_ask_while_a_read_runs_is_one_more_read_when_it_ends(self):
        refresh = Refresh()
        self.assertTrue(refresh.want())
        self.assertFalse(refresh.want())
        self.assertFalse(refresh.want())
        self.assertTrue(refresh.done(), "one more, for the asks made while it ran")
        self.assertFalse(refresh.done("locked"))
        self.assertEqual((refresh.running, refresh.failure), (False, "locked"))


class LivePathTest(unittest.TestCase):
    """Transcripts and the account sync's records through a whole pass, then read as the window reads them."""

    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)

    def tearDown(self):
        self.machine.close()

    def test_a_pass_records_every_accounts_sessions_and_the_window_names_them_as_the_settings_do(self):
        now = time.time()
        folder = self.machine.paths.claude_home.parent / "work"
        folder.mkdir()
        self.machine.sync_events([(now - 7200, "desktop_account", ACCOUNT_A),
                                  (now - 3600, "desktop_account", ACCOUNT_B)])
        self.machine.settings({"v": 1, "accountNames": {ACCOUNT_B: "Studio"}})
        self.machine.transcript("s1", [title_line("s1", "Mine")] + in_folder(assistant_lines("m1", now - 5400, "s1"),
                                                                              str(folder)))
        self.machine.transcript("s2", in_folder(assistant_lines("m2", now - 600, "s2"), str(folder.parent / "gone")))
        run_pass(self.machine.paths, dashboard=False)
        listing = conversations_model.compute(self.machine.paths, now)
        self.assertEqual([(r.session_id, r.title, r.account) for r in listing.rows],
                         [("s2", "Untitled session in gone", "Studio"), ("s1", "Mine", "alpha")])
        self.assertEqual([r.folder_exists for r in listing.rows], [False, True])
        self.assertEqual(listing.accounts, ((ACCOUNT_A, "alpha"), (ACCOUNT_B, "Studio")))
        self.assertEqual(listing.computed_at, now)

    def test_settings_that_cannot_be_read_name_each_account_by_its_e_mail(self):
        now = time.time()
        self.machine.sync_events([(now - 7200, "desktop_account", ACCOUNT_A)])
        self.machine.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.machine.paths.settings_file.write_text("not json", encoding="utf-8")
        self.machine.transcript("s1", assistant_lines("m1", now - 600, "s1"))
        run_pass(self.machine.paths, dashboard=False)
        [made] = conversations_model.compute(self.machine.paths, now).rows
        self.assertEqual(made.account, "alpha")

    def test_with_no_ledger_yet_the_read_says_so(self):
        with self.assertRaises(FileNotFoundError):
            conversations_model.compute(self.machine.paths)


if __name__ == "__main__":
    unittest.main()
