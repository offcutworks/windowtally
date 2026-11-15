"""The sessions a switch of the desktop app carries: each session's title and the turns a plan limit refused, read from
the transcripts — the part already read of each read once more for them — their accounts, and the sessions of an
account the window offers."""

import json
import time
import unittest

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, epoch, iso,
                      user_line)
from windowtally.attribution import attribute
from windowtally.ingest_sync import ingest_sync_events
from windowtally.ingest_transcripts import KINDS, KINDS_KEY, ingest_transcripts
from windowtally.ledger import Ledger
from windowtally.service import run_pass
from windowtally.sessions import CARRY_SPAN, sessions_of
from windowtally_gui import actions_model

T0 = epoch("2026-11-08T10:00:00Z")
RESETS = epoch("2026-11-08T15:00:00Z")


def title_line(session_id: str, title: str, source: str = "custom") -> dict:
    """A title line as Claude Code 2.1 writes it: the app's ``custom-title``, or its own ``ai-title``."""
    if source == "custom":
        return {"type": "custom-title", "customTitle": title, "sessionId": session_id}
    return {"type": "ai-title", "aiTitle": title, "sessionId": session_id}


def prompt_line(session_id: str, prompt_id: str, t: float, mode: str, *, sidechain: bool = False) -> dict:
    """A prompt's line naming the permission mode its turn runs in, as Claude Code 2.1.321 writes it."""
    return dict(user_line(session_id, prompt_id, t, sidechain=sidechain), permissionMode=mode)


def mode_line(session_id: str, mode: str) -> dict:
    """The line Claude Code 2.1.321 writes as a session's permission mode changes: no time, no prompt."""
    return {"type": "permission-mode", "permissionMode": mode, "sessionId": session_id}


def stop_line(session_id: str, t: float, uuid: str, *, kind: str = "five_hour", resets: float | None = RESETS,
              shape: str = "new", agent_id: str | None = None, error: str = "rate_limit", flagged: bool = True) -> dict:
    """The line of a turn a plan limit refused: ``new`` as from Claude Code 2.1.299, naming the window and its reset,
    ``old`` as before, naming neither."""
    window = "session" if kind == "five_hour" else "weekly"
    line = {"parentUuid": "parent-" + uuid, "isSidechain": bool(agent_id), "userType": "external",
            "cwd": "D:\\Work\\Project", "sessionId": session_id, "version": "2.1.308", "gitBranch": "main",
            "entrypoint": "claude-desktop", "type": "assistant", "uuid": uuid, "timestamp": iso(t),
            "message": {"id": "msg-" + uuid, "model": "<synthetic>", "role": "assistant", "type": "message",
                        "content": [{"type": "text", "text": f"You've hit your {window} limit · resets 3pm"}],
                        "usage": {"input_tokens": 0, "output_tokens": 0}},
            "error": error, "isApiErrorMessage": flagged, "apiErrorStatus": 429, "requestId": "req-" + uuid}
    if agent_id:
        line["agentId"] = agent_id
    if shape == "new":
        info = {"status": "rejected", "resetsAt": int(resets), "rateLimitType": kind, "overageStatus": "rejected",
                "isUsingOverage": False}
        line.update(apiError="usage_limit_reached", quotaLimits=dict(info, unifiedRateLimitFallbackAvailable=False),
                    apiErrorParams={"rate_limit_info": info})
    return line


def start_line(session_id: str, t: float, task: str, *, kind: str = "command", sidechain: bool = False) -> dict:
    """The tool result on which a background task starts, as Claude Code 2.1.308 writes it: a command's, or a
    subagent's."""
    result = {"stdout": "", "stderr": "", "interrupted": False, "backgroundTaskId": task} if kind == "command" \
        else {"isAsync": True, "status": "async_launched", "agentId": task, "description": "Look it up"}
    return {"type": "user", "timestamp": iso(t), "sessionId": session_id, "promptId": "p-" + task,
            "isSidechain": sidechain, "entrypoint": "claude-desktop", "toolUseResult": result,
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu-" + task,
                                                     "content": "Running in the background: " + task}]}}


def notification(task: str, status: str | None = "completed", summary: str = "It ran") -> str:
    """A task's notification; one with no status is an event of a task that watches."""
    return (f"<task-notification>\n<task-id>{task}</task-id>\n<tool-use-id>toolu-{task}</tool-use-id>\n"
            + (f"<status>{status}</status>\n" if status else "") + f"<summary>{summary}</summary>\n</task-notification>")


def queued_line(session_id: str, t: float, task: str, status: str | None = "completed",
                summary: str = "It ran") -> dict:
    """The notification as it is queued when the task ends."""
    return {"type": "queue-operation", "operation": "enqueue", "timestamp": iso(t), "sessionId": session_id,
            "content": notification(task, status, summary)}


def notified_line(session_id: str, t: float, task: str, status: str = "completed") -> dict:
    """The notification as it reaches an idle session, a turn of its own."""
    return {"type": "user", "timestamp": iso(t), "sessionId": session_id, "promptId": "n-" + task,
            "isSidechain": False, "entrypoint": "claude-desktop",
            "origin": {"kind": "task-notification", "producer": "session-task"},
            "message": {"role": "user", "content": notification(task, status)}}


def stopped_line(session_id: str, t: float, task: str) -> dict:
    """The result of a stop the session made itself."""
    return {"type": "user", "timestamp": iso(t), "sessionId": session_id, "promptId": "s-" + task,
            "isSidechain": False, "entrypoint": "claude-desktop",
            "toolUseResult": {"message": "Successfully stopped task: " + task, "task_id": task,
                              "task_type": "local_bash", "command": "run"},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu-stop-" + task,
                                                     "content": "Stopped"}]}}


class TranscriptCase(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.ledger = Ledger.open(self.machine.paths.ledger_db)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def ingest(self):
        return ingest_transcripts(self.ledger, self.machine.paths.projects_dir)

    def titles(self):
        return dict(self.ledger.db.execute("SELECT session_id, title FROM session_titles"))

    def stops(self):
        return self.ledger.db.execute("SELECT line_uuid, session_id, t, kind, resets_at FROM limit_stops "
                                      "ORDER BY line_uuid").fetchall()

    def tasks(self):
        return self.ledger.db.execute("SELECT task_id, session_id, kind, started, ended FROM background_tasks "
                                      "ORDER BY task_id").fetchall()


class TitleTest(TranscriptCase):
    def test_the_apps_title_stands_before_claude_codes_own_and_the_one_read_last_stands(self):
        self.machine.transcript("s1", [title_line("s1", "Made up", "ai"), title_line("s1", "Mine"),
                                       title_line("s1", "Made up later", "ai")])
        self.machine.transcript("s2", [title_line("s2", "First"), title_line("s2", "Renamed")])
        self.machine.transcript("s3", [title_line("s3", "Only its own", "ai")])
        self.assertEqual(self.ingest().titles, 6)
        self.assertEqual(self.titles(), {"s1": "Mine", "s2": "Renamed", "s3": "Only its own"})

    def test_a_title_read_at_a_later_pass_replaces_the_one_before(self):
        self.machine.transcript("s1", [title_line("s1", "First")])
        self.ingest()
        self.machine.transcript("s1", [title_line("s1", "Second")], append=True)
        self.ingest()
        self.assertEqual(self.titles(), {"s1": "Second"})

    def test_a_title_with_no_words_is_no_title(self):
        self.machine.transcript("s1", [title_line("s1", "  "), title_line("s1", "", "ai")])
        self.ingest()
        self.assertEqual(self.titles(), {})


class ModeTest(TranscriptCase):
    def modes(self):
        return dict(self.ledger.db.execute("SELECT session_id, mode FROM session_modes"))

    def test_the_mode_a_main_transcript_names_last_stands_on_a_prompt_or_a_mode_line(self):
        self.machine.transcript("s1", [prompt_line("s1", "p1", T0, "auto"), mode_line("s1", "plan")])
        self.machine.transcript("s2", [mode_line("s2", "acceptEdits"), prompt_line("s2", "p2", T0, "default")])
        stats = self.ingest()
        self.assertEqual(self.modes(), {"s1": "plan", "s2": "default"})
        self.assertEqual(stats.modes, 4)
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM prompts").fetchone()[0], 2,
                         "a prompt naming its mode is still a prompt")

    def test_a_mode_read_at_a_later_pass_replaces_the_one_before(self):
        self.machine.transcript("s1", [prompt_line("s1", "p1", T0, "auto")])
        self.ingest()
        self.machine.transcript("s1", [mode_line("s1", "bypassPermissions")], append=True)
        self.ingest()
        self.assertEqual(self.modes(), {"s1": "bypassPermissions"})

    def test_a_subagents_lines_and_a_line_naming_no_mode_name_none(self):
        self.machine.transcript("s1", [prompt_line("s1", "p1", T0, "auto"), user_line("s1", "p2", T0 + 5),
                                       mode_line("s1", "")])
        self.machine.transcript("s1", [prompt_line("s1", "p3", T0 + 9, "plan", sidechain=True),
                                       mode_line("s1", "dontAsk")], agent="a1")
        self.ingest()
        self.assertEqual(self.modes(), {"s1": "auto"})


class StopTest(TranscriptCase):
    def test_a_main_sessions_stop_is_recorded_with_its_window_and_reset(self):
        self.machine.transcript("s1", assistant_lines("msg_1", T0 - 60, "s1") + [
            stop_line("s1", T0, "u1"), stop_line("s1", T0 + 30, "u2", kind="seven_day", resets=RESETS + 86400)])
        stats = self.ingest()
        self.assertEqual((stats.responses, stats.limit_stops), (2, 2))
        self.assertEqual(self.stops(), [("u1", "s1", T0, "five_hour", RESETS),
                                        ("u2", "s1", T0 + 30, "seven_day", RESETS + 86400)])

    def test_a_stop_written_before_claude_code_named_its_window_is_recorded_without_one(self):
        self.machine.transcript("s1", [stop_line("s1", T0, "u1", shape="old")])
        self.ingest()
        self.assertEqual(self.stops(), [("u1", "s1", T0, None, None)])

    def test_a_subagents_stop_and_any_other_error_or_synthetic_line_are_not_stops(self):
        self.machine.transcript("s1", [stop_line("s1", T0, "u1", error="server_error"),
                                       stop_line("s1", T0 + 1, "u2", flagged=False)]
                                + assistant_lines("msg_1", T0 + 2, "s1", model="<synthetic>"))
        self.machine.transcript("s1", [stop_line("s1", T0 + 3, "u3", agent_id="a1")], agent="a1")
        self.ingest()
        self.assertEqual(self.stops(), [])

    def test_a_stop_read_twice_is_one_row(self):
        self.machine.transcript("s1", [stop_line("s1", T0, "u1"), stop_line("s1", T0 + 30, "u2")])
        self.ingest()
        self.machine.transcript("s1", [stop_line("s1", T0, "u1")])   # shrunk: read again from the start
        self.ingest()
        self.assertEqual([row[0] for row in self.stops()], ["u1", "u2"])


class CatchUpTest(TranscriptCase):
    def read_before_titles_and_stops(self):
        """A ledger as code reading no titles or stops left it: its rows of both gone and its kinds unrecorded."""
        with self.ledger.transaction():
            self.ledger.db.execute("DELETE FROM session_titles")
            self.ledger.db.execute("DELETE FROM limit_stops")
            self.ledger.db.execute("DELETE FROM meta WHERE key=?", (KINDS_KEY,))

    def test_what_was_already_read_is_read_once_more_for_titles_and_stops_alone(self):
        self.machine.transcript("s1", [title_line("s1", "Mine")] + assistant_lines("msg_1", T0 - 60, "s1")
                                + [stop_line("s1", T0, "u1")])
        self.ingest()
        self.read_before_titles_and_stops()
        stats = self.ingest()
        self.assertEqual((stats.caught_up, stats.titles, stats.limit_stops), (1, 1, 1))
        self.assertEqual(stats.responses, 0, "no response is read again")
        self.assertEqual(self.titles(), {"s1": "Mine"})
        self.assertEqual([row[0] for row in self.stops()], ["u1"])
        self.assertEqual(self.ledger.get_meta(KINDS_KEY), KINDS)
        self.assertEqual(self.ingest().caught_up, 0, "once")

    def test_a_new_ledger_has_nothing_to_catch_up_and_records_its_kinds(self):
        self.machine.transcript("s1", [title_line("s1", "Mine")])
        stats = self.ingest()
        self.assertEqual((stats.caught_up, stats.titles), (0, 1))
        self.assertEqual(self.ledger.get_meta(KINDS_KEY), KINDS)

    def test_the_older_part_is_read_before_the_new_lines_so_the_title_read_last_stands(self):
        self.machine.transcript("s1", [title_line("s1", "Old")])
        self.ingest()
        self.read_before_titles_and_stops()
        self.machine.transcript("s1", [title_line("s1", "New")], append=True)
        self.ingest()
        self.assertEqual(self.titles(), {"s1": "New"})

    def test_a_catch_up_run_again_puts_no_older_title_back_and_an_apps_title_still_beats_claude_codes(self):
        self.machine.transcript("s1", [title_line("s1", "Old")])
        self.machine.transcript("s2", [title_line("s2", "The app's")])
        self.ingest()
        with self.ledger.transaction():
            self.ledger.db.execute("UPDATE session_titles SET title='Newer' WHERE session_id='s1'")
            self.ledger.db.execute("UPDATE session_titles SET title='Its own', source='ai' WHERE session_id='s2'")
            self.ledger.db.execute("DELETE FROM meta WHERE key=?", (KINDS_KEY,))
        self.ingest()
        self.assertEqual(self.titles(), {"s1": "Newer", "s2": "The app's"})

    def test_a_ledger_read_before_modes_is_read_once_more_for_them_and_a_mode_read_since_stands(self):
        self.machine.transcript("s1", [prompt_line("s1", "p1", T0, "auto"), mode_line("s1", "plan")]
                                + assistant_lines("msg_1", T0 + 5, "s1"))
        self.machine.transcript("s2", [prompt_line("s2", "p2", T0, "acceptEdits")])
        self.ingest()
        with self.ledger.transaction():
            self.ledger.db.execute("DELETE FROM session_modes WHERE session_id='s1'")
            self.ledger.db.execute("UPDATE session_modes SET mode='auto' WHERE session_id='s2'")
            self.ledger.set_meta(KINDS_KEY, "2")
        stats = self.ingest()
        self.assertEqual((stats.caught_up, stats.modes, stats.responses), (2, 2, 0))
        self.assertEqual(dict(self.ledger.db.execute("SELECT session_id, mode FROM session_modes")),
                         {"s1": "plan", "s2": "auto"}, "the older lines fill a gap and replace nothing")
        self.assertEqual(self.ledger.get_meta(KINDS_KEY), KINDS)
        self.assertEqual(self.ingest().caught_up, 0, "once")

    def test_a_subagents_file_and_one_that_shrank_are_not_caught_up(self):
        self.machine.transcript("s1", assistant_lines("msg_sub", T0, "s1", agent_id="a1"), agent="a1")
        path = self.machine.transcript("s2", [title_line("s2", "Long gone"), title_line("s2", "Gone")])
        self.ingest()
        self.read_before_titles_and_stops()
        path.write_text(json.dumps(title_line("s2", "Rewritten"), separators=(",", ":")) + "\n", encoding="utf-8")
        stats = self.ingest()
        self.assertEqual(stats.caught_up, 0)
        self.assertEqual(self.titles(), {"s2": "Rewritten"}, "the reader itself reads a rewritten file whole")


def events(machine: Machine, *points: tuple[float, str]) -> None:
    """The desktop app's account at each moment, as the account sync records a switch."""
    machine.sync_events([(t, "desktop_account", account) for t, account in points])


class StopAccountTest(TranscriptCase):
    def test_a_stop_takes_the_account_the_desktop_app_was_on_at_its_moment(self):
        events(self.machine, (T0 - 3600, ACCOUNT_A), (T0 + 600, ACCOUNT_B))
        self.machine.transcript("s1", [stop_line("s1", T0, "u1"), stop_line("s1", T0 + 900, "u2")])
        self.ingest()
        ingest_sync_events(self.ledger, self.machine.paths.sync_events)
        self.assertEqual(attribute(self.ledger), 2)
        rows = self.ledger.db.execute("SELECT line_uuid, account_uuid, account_source FROM limit_stops "
                                      "ORDER BY line_uuid").fetchall()
        self.assertEqual(rows, [("u1", ACCOUNT_A, "desktop-timeline"), ("u2", ACCOUNT_B, "desktop-timeline")])

    def test_a_timeline_point_written_late_moves_the_stop_with_the_answers(self):
        self.machine.transcript("s1", [stop_line("s1", T0, "u1")])
        self.ingest()
        events(self.machine, (T0 - 3600, ACCOUNT_A))
        ingest_sync_events(self.ledger, self.machine.paths.sync_events)
        attribute(self.ledger)
        events(self.machine, (T0 - 60, ACCOUNT_B))
        ingest_sync_events(self.ledger, self.machine.paths.sync_events)
        attribute(self.ledger)
        self.assertEqual(self.ledger.db.execute("SELECT account_uuid FROM limit_stops").fetchone()[0], ACCOUNT_B)


class BackgroundTaskTest(TranscriptCase):
    def test_a_command_and_a_subagent_started_in_the_background_are_recorded_and_a_subagents_own_is_not(self):
        self.machine.transcript("s1", [start_line("s1", T0, "task-a"), start_line("s1", T0 + 5, "task-b", kind="agent")])
        self.machine.transcript("s1", [start_line("s1", T0 + 9, "task-c", sidechain=True)], agent="a1")
        stats = self.ingest()
        self.assertEqual(self.tasks(), [("task-a", "s1", "command", T0, None), ("task-b", "s1", "agent", T0 + 5, None)])
        self.assertEqual((stats.tasks_started, stats.tasks_ended), (2, 0))

    def test_a_notification_queued_or_delivered_and_a_stop_by_the_session_each_end_a_task(self):
        self.machine.transcript("s1", [
            start_line("s1", T0, "task-a"), start_line("s1", T0, "task-b"), start_line("s1", T0, "task-c"),
            start_line("s1", T0, "task-d"),
            queued_line("s1", T0 + 60, "task-a"), notified_line("s1", T0 + 61, "task-a"),
            notified_line("s1", T0 + 70, "task-b", "failed"), stopped_line("s1", T0 + 80, "task-c")])
        stats = self.ingest()
        self.assertEqual([(task, ended) for task, _session, _kind, _started, ended in self.tasks()],
                         [("task-a", T0 + 61), ("task-b", T0 + 70), ("task-c", T0 + 80), ("task-d", None)])
        self.assertEqual(stats.tasks_ended, 4, "task-a's end was written twice, queued and delivered")

    def test_an_event_of_a_task_that_watches_ends_nothing(self):
        self.machine.transcript("s1", [start_line("s1", T0, "task-a"), queued_line("s1", T0 + 60, "task-a", None)])
        self.ingest()
        self.assertEqual(self.tasks(), [("task-a", "s1", "command", T0, None)])

    def test_a_task_is_ended_only_by_its_own_notification_or_a_stop_and_not_by_words_that_quote_it(self):
        quoting = "It read <task-id>task-b</task-id> and <status>completed</status> in a log"
        asked = stopped_line("s1", T0 + 40, "task-c")
        asked["toolUseResult"]["message"] = "Still running: task-c"
        typed = queued_line("s1", T0 + 50, "task-d")
        typed["content"] = "Look at this: " + typed["content"]
        self.machine.transcript("s1", [
            start_line("s1", T0, "task-a"), start_line("s1", T0, "task-b"), start_line("s1", T0, "task-c"),
            start_line("s1", T0, "task-d"), start_line("s1", T0, "task-e"),
            queued_line("s1", T0 + 30, "task-a", summary=quoting), asked, typed,
            queued_line("s1", T0 + 60, "task-e", None, summary="an event saying <status>completed</status>")])
        self.ingest()
        self.assertEqual([(task, ended) for task, _session, _kind, _started, ended in self.tasks()],
                         [("task-a", T0 + 30), ("task-b", None), ("task-c", None), ("task-d", None), ("task-e", None)])

    def test_a_start_on_a_line_that_quotes_an_assistants_type_is_still_read(self):
        start = start_line("s1", T0, "task-a")
        start["message"]["content"][0]["content"] = 'It printed {"type":"assistant"} and went on'
        self.machine.transcript("s1", [start])
        self.ingest()
        self.assertEqual(self.tasks(), [("task-a", "s1", "command", T0, None)])

    def test_an_end_written_into_another_transcript_ends_the_task_whichever_is_read_first(self):
        self.machine.transcript("went-on", [queued_line("went-on", T0 + 900, "task-a", "stopped")])
        self.ingest()
        self.assertEqual(self.tasks(), [("task-a", None, None, None, T0 + 900)])
        self.machine.transcript("s1", [start_line("s1", T0, "task-a"), start_line("s1", T0, "task-b")])
        self.machine.transcript("went-on", [notified_line("went-on", T0 + 950, "task-b", "stopped")], append=True)
        self.ingest()
        self.assertEqual(self.tasks(), [("task-a", "s1", "command", T0, T0 + 900),
                                        ("task-b", "s1", "command", T0, T0 + 950)])

    def test_a_transcript_read_again_records_its_tasks_once(self):
        self.machine.transcript("s1", [start_line("s1", T0, "task-a"), queued_line("s1", T0 + 60, "task-a"),
                                       start_line("s1", T0 + 90, "task-b")])
        self.ingest()
        self.machine.transcript("s1", [start_line("s1", T0, "task-a"), queued_line("s1", T0 + 60, "task-a")])
        self.ingest()
        self.assertEqual([(task, ended) for task, _session, _kind, _started, ended in self.tasks()],
                         [("task-a", T0 + 60), ("task-b", None)])


class SessionsOfTest(TranscriptCase):
    """Alpha's app over the morning: the app on alpha until T0 + 1 h, then on beta."""

    def setUp(self):
        super().setUp()
        events(self.machine, (T0 - 2 * 86400, ACCOUNT_A), (T0 + 3600, ACCOUNT_B))

    def build(self):
        self.ingest()
        ingest_sync_events(self.ledger, self.machine.paths.sync_events)
        attribute(self.ledger)

    def test_an_accounts_sessions_with_their_titles_stops_and_last_activity(self):
        self.machine.transcript("stopped", [title_line("stopped", "Refactor the parser")]
                                + assistant_lines("m1", T0 - 600, "stopped") + [user_line("stopped", "p1", T0 - 30),
                                                                                stop_line("stopped", T0, "u1")])
        self.machine.transcript("answered", assistant_lines("m2", T0 - 900, "answered")
                                + [stop_line("answered", T0 - 800, "u2")] + assistant_lines("m3", T0 - 100, "answered"))
        self.machine.transcript("old-stop", [stop_line("old-stop", T0 - 1200, "u3", shape="old")])
        self.build()
        lines = sessions_of(self.ledger, ACCOUNT_A, T0 + 60)
        self.assertEqual([line.session_id for line in lines], ["stopped", "answered", "old-stop"],
                         "the latest activity first")
        stopped, answered, old = lines
        self.assertEqual((stopped.title, stopped.stop_kind, stopped.stop_resets, stopped.last_activity),
                         ("Refactor the parser", "five_hour", RESETS, T0))
        self.assertTrue(stopped.stopped)
        self.assertEqual(stopped.project, "D:\\Work\\Project")
        self.assertEqual((answered.title, answered.stopped), (None, False), "answered after its stop: none stands")
        self.assertEqual((old.stop_kind, old.project, old.last_activity), ("", None, T0 - 1200))

    def test_a_session_carried_on_since_on_another_account_is_that_accounts(self):
        self.machine.transcript("carried", assistant_lines("m1", T0 - 600, "carried") + [stop_line("carried", T0, "u1")]
                                + assistant_lines("m2", T0 + 4000, "carried"))
        self.build()
        self.assertEqual(sessions_of(self.ledger, ACCOUNT_A, T0 + 4100), [])
        self.assertEqual([line.session_id for line in sessions_of(self.ledger, ACCOUNT_B, T0 + 4100)], ["carried"])

    def test_a_session_older_than_the_span_and_one_of_the_cli_alone_are_not_offered(self):
        self.machine.transcript("yesterday", assistant_lines("m1", T0 - CARRY_SPAN - 60, "yesterday"))
        self.machine.transcript("cli", assistant_lines("m2", T0 - 60, "cli", entrypoint="cli"))
        self.machine.transcript("today", assistant_lines("m3", T0 - 60, "today"))
        self.build()
        self.assertEqual([line.session_id for line in sessions_of(self.ledger, ACCOUNT_A, T0)], ["today"])

    def test_a_stop_of_a_cli_session_offers_it_no_more_than_its_answers_do(self):
        cli_stop = stop_line("cli-stopped", T0 - 30, "u1")
        cli_stop["entrypoint"] = "cli"
        self.machine.transcript("cli-stopped", assistant_lines("m1", T0 - 600, "cli-stopped", entrypoint="cli")
                                + [cli_stop])
        self.build()
        self.assertEqual(self.ledger.db.execute("SELECT entrypoint FROM limit_stops").fetchall(), [("cli",)])
        self.assertEqual(sessions_of(self.ledger, ACCOUNT_A, T0), [])

    def test_a_ledger_no_pass_of_this_code_opened_offers_its_sessions_without_titles_or_stops(self):
        self.machine.transcript("s1", [title_line("s1", "Mine")] + assistant_lines("m1", T0 - 60, "s1")
                                + [stop_line("s1", T0, "u1")])
        self.build()
        with self.ledger.transaction():
            self.ledger.db.execute("DROP TABLE session_titles")
            self.ledger.db.execute("DROP TABLE limit_stops")
        reader = Ledger.open_readonly(self.machine.paths.ledger_db)
        try:
            [line] = sessions_of(reader, ACCOUNT_A, T0 + 60)
        finally:
            reader.close()
        self.assertEqual((line.session_id, line.title, line.stopped, line.last_activity), ("s1", None, False, T0 - 60))

    def test_a_session_counts_the_background_tasks_it_started_within_the_span_that_never_ended(self):
        self.machine.transcript("busy", assistant_lines("m1", T0 - 600, "busy") + [
            start_line("busy", T0 - 500, "task-a"), start_line("busy", T0 - 400, "task-b", kind="agent"),
            start_line("busy", T0 - 300, "task-c"), queued_line("busy", T0 - 200, "task-a")])
        self.machine.transcript("done", assistant_lines("m2", T0 - 700, "done") + [
            start_line("done", T0 - 650, "task-d"), stopped_line("done", T0 - 640, "task-d")])
        self.machine.transcript("long-ago", [start_line("long-ago", T0 - CARRY_SPAN - 60, "task-e")]
                                + assistant_lines("m3", T0 - 800, "long-ago"))
        self.build()
        found = {line.session_id: line.unfinished for line in sessions_of(self.ledger, ACCOUNT_A, T0)}
        self.assertEqual(found, {"busy": 2, "done": 0, "long-ago": 0})

    def test_a_task_started_again_under_its_id_is_unfinished_until_it_ends_again(self):
        self.machine.transcript("s1", assistant_lines("m1", T0 - 900, "s1") + [
            start_line("s1", T0 - 800, "task-a", kind="agent"), queued_line("s1", T0 - 700, "task-a"),
            start_line("s1", T0 - 300, "task-a", kind="agent")])
        self.build()
        self.assertEqual([line.unfinished for line in sessions_of(self.ledger, ACCOUNT_A, T0)], [1])
        self.machine.transcript("s1", [queued_line("s1", T0 - 100, "task-a")], append=True)
        self.build()
        self.assertEqual([line.unfinished for line in sessions_of(self.ledger, ACCOUNT_A, T0)], [0])

    def test_a_session_says_the_effort_of_its_latest_main_answer_and_the_mode_it_last_named(self):
        self.machine.transcript("s1", [prompt_line("s1", "p1", T0 - 900, "auto")]
                                + assistant_lines("m1", T0 - 800, "s1", effort="high")
                                + assistant_lines("m2", T0 - 600, "s1", effort="max")
                                + assistant_lines("m3", T0 - 500, "s1", effort="low", agent_id="a1"))
        self.machine.transcript("s2", assistant_lines("m4", T0 - 300, "s2", effort=None))
        self.build()
        found = {line.session_id: (line.effort, line.mode) for line in sessions_of(self.ledger, ACCOUNT_A, T0)}
        self.assertEqual(found, {"s1": ("max", "auto"), "s2": (None, None)}, "a subagent's effort is not its own")

    def test_a_ledger_with_no_table_of_modes_names_none(self):
        self.machine.transcript("s1", [prompt_line("s1", "p1", T0 - 90, "auto")] + assistant_lines("m1", T0 - 60, "s1"))
        self.build()
        with self.ledger.transaction():
            self.ledger.db.execute("DROP TABLE session_modes")
        reader = Ledger.open_readonly(self.machine.paths.ledger_db)
        try:
            [line] = sessions_of(reader, ACCOUNT_A, T0)
        finally:
            reader.close()
        self.assertEqual((line.effort, line.mode), ("xhigh", None))

    def test_a_ledger_with_no_table_of_background_tasks_counts_none(self):
        self.machine.transcript("s1", assistant_lines("m1", T0 - 60, "s1") + [start_line("s1", T0 - 30, "task-a")])
        self.build()
        with self.ledger.transaction():
            self.ledger.db.execute("DROP TABLE background_tasks")
        reader = Ledger.open_readonly(self.machine.paths.ledger_db)
        try:
            [line] = sessions_of(reader, ACCOUNT_A, T0)
        finally:
            reader.close()
        self.assertEqual(line.unfinished, 0)


class LivePathTest(unittest.TestCase):
    """Transcripts and the account sync's records through a whole pass, then read as the window reads them."""

    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)

    def tearDown(self):
        self.machine.close()

    def test_a_pass_records_the_title_and_the_stop_and_the_window_reads_them_as_the_accounts(self):
        now = time.time()
        events(self.machine, (now - 7200, ACCOUNT_A))
        self.machine.transcript("s1", [title_line("s1", "Mine")] + assistant_lines("m1", now - 900, "s1")
                                + [stop_line("s1", now - 600, "u1", resets=now + 3600)])
        run_pass(self.machine.paths, dashboard=False)
        [line] = actions_model.carry_lines(self.machine.paths, ACCOUNT_A, now)
        self.assertEqual((line.session_id, line.title, line.stop_kind), ("s1", "Mine", "five_hour"))
        self.assertEqual(actions_model.carry_lines(self.machine.paths, ACCOUNT_B, now), [])

    def test_a_pass_records_a_background_task_left_unfinished_and_the_window_reads_it(self):
        now = time.time()
        events(self.machine, (now - 7200, ACCOUNT_A))
        self.machine.transcript("s1", assistant_lines("m1", now - 3600, "s1") + [start_line("s1", now - 3590, "task-a")])
        run_pass(self.machine.paths, dashboard=False)
        [line] = actions_model.carry_lines(self.machine.paths, ACCOUNT_A, now)
        self.assertEqual((line.session_id, line.unfinished), ("s1", 1))

    def test_a_pass_records_the_mode_and_the_window_reads_what_the_session_ran_with(self):
        now = time.time()
        events(self.machine, (now - 7200, ACCOUNT_A))
        self.machine.transcript("s1", [prompt_line("s1", "p1", now - 950, "acceptEdits")]
                                + assistant_lines("m1", now - 900, "s1", effort="max"))
        run_pass(self.machine.paths, dashboard=False)
        [line] = actions_model.carry_lines(self.machine.paths, ACCOUNT_A, now)
        self.assertEqual((line.effort, line.mode), ("max", "acceptEdits"))

    def test_with_no_ledger_yet_the_window_is_told_so(self):
        with self.assertRaises(FileNotFoundError):
            actions_model.carry_lines(self.machine.paths, ACCOUNT_A, time.time())


if __name__ == "__main__":
    unittest.main()
