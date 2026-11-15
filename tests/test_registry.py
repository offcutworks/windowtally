"""Claude Code's session registry (windowtally/registry.py), and every count of the sessions at work that reads it: the
pass's ``workingSessions`` and its source problems, the window's count, names and its check whether the ledger is
behind a session, and the account sync's ``Status``.

Expected values follow the source's statement in ``windowtally/registry.py`` and the status file's in
``windowtally/status_file.py``. The reader's own cases run against a synthetic registry and a stand-in process table;
the counts the pass, the window and the sync take run on the live path, the registry naming this test's own process,
whose creation time Windows reports, as PowerShell's ``Get-Process`` reads it.
"""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from fixtures import ACCOUNT_A, EMAIL_A, ORG_A, Machine, epoch, iso, status_account, status_document
from test_sync_script import SyncHomeTestCase
from windowtally.registry import (DESKTOP_ENTRYPOINT, PROBLEMS_SPELT_OUT, SOURCE, WindowsProcesses,
                                  read_registry)
from windowtally.service import run_pass
from windowtally_gui import actions_model
from windowtally_gui.status_model import snapshot_of

NOW = epoch("2026-11-11T12:00:00Z")
SESSION = "11111111-2222-4333-8444-555555555555"
OTHER = "66666666-7777-4888-8999-aaaaaaaaaaaa"


class Table:
    """A stand-in process table: pid → creation FILETIME of the processes alive."""

    def __init__(self, created: dict[int, int]):
        self.table = dict(created)
        self.asked: list[int] = []

    def created(self, pid: int) -> int | None:
        self.asked.append(pid)
        return self.table.get(pid)


def entry(pid: int, start: int, *, session: str = SESSION, status: object = "busy",
          entrypoint: object = DESKTOP_ENTRYPOINT, changed: object = None, start_key: str = "procStart",
          **extra) -> dict:
    data = {"pid": pid, "sessionId": session, "cwd": "C:\\work", start_key: str(start), "kind": "interactive",
            "entrypoint": entrypoint, "version": "2.1.321", **extra}
    if status is not None:
        data["status"] = status
    if changed is not None:
        data["statusUpdatedAt"] = changed
        data["updatedAt"] = changed
    return data


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="registrytest-")
        self.dir = Path(self.temp.name) / "sessions"
        self.dir.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, data: object, name: str | None = None) -> Path:
        path = self.dir / (name or f"{data['pid']}.json")
        path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
        return path


class ReaderTest(RegistryTestCase):
    def test_no_folder_holds_no_session_and_no_problem(self):
        reading = read_registry(self.dir.parent / "absent", Table({}))
        self.assertEqual((reading.sessions, reading.problems), ((), ()))

    def test_a_busy_session_of_a_live_process_is_at_work_and_idle_waiting_and_shell_are_not(self):
        for pid, status in ((10, "busy"), (11, "idle"), (12, "waiting"), (13, "shell")):
            self.write(entry(pid, 1000 + pid, session=f"s{pid}", status=status))
        reading = read_registry(self.dir, Table({pid: 1000 + pid for pid in (10, 11, 12, 13)}))
        self.assertEqual(reading.problems, ())
        self.assertEqual(len(reading.sessions), 4)
        self.assertEqual([s.session_id for s in reading.working()], ["s10"])
        self.assertEqual(reading.desktop_working_ids(), frozenset({"s10"}))

    def test_a_process_that_is_gone_or_another_with_its_id_does_not_count(self):
        self.write(entry(20, 500, session="gone"))
        self.write(entry(21, 600, session="reused"))
        reading = read_registry(self.dir, Table({21: 601}))
        self.assertEqual((reading.sessions, reading.problems), ((), ()))

    def test_the_creation_time_is_read_under_either_of_its_names(self):
        self.write(entry(30, 3000, session="new", start_key="procStartFt"))
        self.write(entry(31, 3100, session="old"))
        self.write(entry(32, 3200, session="null-new", procStartFt=None))
        reading = read_registry(self.dir, Table({30: 3000, 31: 3100, 32: 3200}))
        self.assertEqual(reading.problems, ())
        self.assertEqual(reading.desktop_working_ids(), frozenset({"new", "old", "null-new"}),
                         "a procStartFt written as null leaves procStart to say, as the account sync reads it")

    def test_a_terminal_and_a_scripted_run_are_at_work_but_not_the_desktop_apps(self):
        self.write(entry(40, 1, session="desktop"))
        self.write(entry(41, 2, session="terminal", entrypoint="cli"))
        self.write(entry(42, 3, session="scripted", entrypoint="sdk-cli"))
        reading = read_registry(self.dir, Table({40: 1, 41: 2, 42: 3}))
        self.assertEqual({s.session_id for s in reading.working()}, {"desktop", "terminal", "scripted"})
        self.assertEqual(reading.desktop_working_ids(), frozenset({"desktop"}))

    def test_a_process_that_has_not_reported_yet_is_live_but_not_at_work_and_no_problem(self):
        self.write(entry(50, 5, status=None))
        reading = read_registry(self.dir, Table({50: 5}))
        self.assertEqual(reading.problems, ())
        self.assertEqual(len(reading.sessions), 1)
        self.assertEqual(reading.working(), ())

    def test_only_a_name_of_digits_ending_in_json_is_opened(self):
        for name in ("60.0123abcd.key", "notes.json", "60.json.tmp", "x60.json"):
            (self.dir / name).write_text("not JSON at all", encoding="utf-8")
        self.write(entry(60, 6))
        reading = read_registry(self.dir, Table({60: 6}))
        self.assertEqual(reading.problems, ())
        self.assertEqual(reading.desktop_working_ids(), frozenset({SESSION}))

    def test_a_file_it_does_not_recognise_is_a_named_problem_and_counts_as_not_at_work(self):
        cases = {
            "70.json": "{ not json",
            "71.json": json.dumps([1, 2]),
            "72.json": json.dumps(entry(99, 7)),                        # names another process
            "73.json": json.dumps({**entry(73, 7), "sessionId": None}),
            "74.json": json.dumps({k: v for k, v in entry(74, 7).items() if k != "procStart"}),
            "75.json": json.dumps(entry(75, 7, status="thinking")),
            "76.json": json.dumps(entry(76, 7, entrypoint=None)),
            "77.json": json.dumps(entry(77, 7, changed="soon")),
        }
        for name, text in cases.items():
            with self.subTest(name):
                for old in self.dir.iterdir():
                    old.unlink()
                self.write(text, name)
                reading = read_registry(self.dir, Table({pid: 7 for pid in range(70, 100)}))
                self.assertEqual(reading.sessions, ())
                self.assertEqual(len(reading.problems), 1)
                self.assertTrue(reading.problems[0].startswith(f"{SOURCE}: {name} "), reading.problems[0])
                self.assertTrue(reading.problems[0].endswith("such a session counts as not at work"))

    def test_an_unknown_status_is_named_with_its_value(self):
        self.write(entry(75, 7, status="thinking"))
        problem = read_registry(self.dir, Table({75: 7})).problems[0]
        self.assertIn("75.json has the status 'thinking', which this version of WindowTally does not know", problem)

    def test_many_files_it_does_not_recognise_make_one_problem_that_counts_the_rest(self):
        for pid in range(80, 80 + PROBLEMS_SPELT_OUT + 2):
            self.write(entry(pid, 8, status="new-status"))
        self.write(entry(90, 9, session="fine"))
        reading = read_registry(self.dir, Table({90: 9}))
        self.assertEqual(len(reading.problems), 1)
        self.assertEqual(reading.problems[0].count("new-status"), PROBLEMS_SPELT_OUT)
        self.assertIn("; and 2 more files;", reading.problems[0])
        self.assertEqual(reading.desktop_working_ids(), frozenset({"fine"}), "the files it reads still count")

    def test_the_last_change_of_a_desktop_session_is_its_newest_status_change(self):
        self.write(entry(100, 1, session="a", status="idle", changed=int((NOW - 300) * 1000)))
        self.write(entry(101, 2, session="b", status="idle", changed=int((NOW - 60) * 1000)))
        self.write(entry(102, 3, session="c", status="busy", entrypoint="cli", changed=int(NOW * 1000)))
        reading = read_registry(self.dir, Table({100: 1, 101: 2, 102: 3}))
        self.assertEqual(reading.last_desktop_change(), NOW - 60, "a terminal's change is not the desktop's")
        self.assertIsNone(read_registry(self.dir.parent / "absent", Table({})).last_desktop_change())


def own_creation() -> int:
    """This process's creation time as PowerShell's Get-Process reads it: an instrument other than the reader's own."""
    script = f"(Get-Process -Id {os.getpid()}).StartTime.ToFileTimeUtc()"
    out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                         text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    return int(out.strip())


class LiveProcessTest(unittest.TestCase):
    """The reader's process table is Windows': this test's own process, and one that ran and ended."""

    @classmethod
    def setUpClass(cls):
        cls.start = own_creation()

    def test_windows_reports_this_process_created_when_get_process_says(self):
        self.assertEqual(WindowsProcesses().created(os.getpid()), self.start)

    def test_a_process_that_ended_is_not_reported(self):
        ended = subprocess.Popen(["cmd.exe", "/c", "exit 0"], creationflags=subprocess.CREATE_NO_WINDOW)
        ended.wait()
        self.assertIsNone(WindowsProcesses().created(ended.pid))


class CountsTest(unittest.TestCase):
    """The pass, the window and the sync count the desktop app's sessions at work off the registry of the machine's
    Claude home; this test's own process stands for a Code session."""

    @classmethod
    def setUpClass(cls):
        cls.start = own_creation()

    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.paths = self.machine.paths
        self.paths.registry_dir.mkdir(parents=True)

    def tearDown(self):
        self.machine.close()

    def register(self, status: str = "busy", entrypoint: str = DESKTOP_ENTRYPOINT, changed: float | None = None,
                 start: int | None = None) -> None:
        data = entry(os.getpid(), self.start if start is None else start, status=status, entrypoint=entrypoint,
                     changed=None if changed is None else int(changed * 1000))
        (self.paths.registry_dir / f"{os.getpid()}.json").write_text(json.dumps(data), encoding="utf-8")

    def status(self) -> dict:
        run_pass(self.paths, now=NOW, dashboard=False)
        return json.loads(self.paths.status_file.read_text(encoding="utf-8"))

    def test_a_pass_counts_a_busy_desktop_session_and_nothing_else(self):
        self.assertNotIn("workingSessions", self.status())
        self.register()
        self.assertEqual(self.status()["workingSessions"], 1)
        for status, entrypoint in (("idle", DESKTOP_ENTRYPOINT), ("waiting", DESKTOP_ENTRYPOINT), ("busy", "cli")):
            with self.subTest(status=status, entrypoint=entrypoint):
                self.register(status, entrypoint)
                self.assertNotIn("workingSessions", self.status())

    def test_a_pass_does_not_count_a_file_left_by_another_process(self):
        self.register(start=self.start + 1)
        self.assertNotIn("workingSessions", self.status())

    def test_a_pass_names_a_file_it_does_not_recognise_among_the_source_problems(self):
        self.register(status="pondering")
        doc = self.status()
        self.assertNotIn("workingSessions", doc)
        self.assertTrue(any(e.startswith(f"{SOURCE}: ") and "'pondering'" in e for e in doc["sourceErrors"]),
                        doc["sourceErrors"])

    def test_the_window_counts_and_names_the_desktop_sessions_at_work(self):
        self.assertEqual((actions_model.working_sessions(self.paths), actions_model.working_ids(self.paths)),
                         (0, frozenset()))
        self.register()
        self.assertEqual((actions_model.working_sessions(self.paths), actions_model.working_ids(self.paths)),
                         (1, frozenset({SESSION})))
        self.register(entrypoint="cli")
        self.assertEqual(actions_model.working_sessions(self.paths), 0, "a terminal's session is not the app's")

    @staticmethod
    def written_at(at: float | None):
        doc = status_document([status_account(ACCOUNT_A, EMAIL_A, at=NOW)], at=NOW)
        doc["generatedAt"] = iso(at) if at is not None else None
        return snapshot_of(Path("status.json"), json.dumps(doc)).status

    def test_the_ledger_is_behind_a_desktop_session_at_work_or_changed_since_the_pass(self):
        written = self.written_at(NOW)
        self.assertEqual(written.generated_at, NOW, "the arrangement: a status written at NOW")
        self.assertFalse(actions_model.ledger_behind(self.paths, written), "no session at all")
        self.register("idle", changed=NOW - 30)
        self.assertFalse(actions_model.ledger_behind(self.paths, written), "it changed before the pass")
        self.register("idle", changed=NOW + 30)
        self.assertTrue(actions_model.ledger_behind(self.paths, written), "it changed after the pass")
        self.register("busy", changed=NOW - 30)
        self.assertTrue(actions_model.ledger_behind(self.paths, written), "it is at work")
        self.register("idle", "cli", changed=NOW + 30)
        self.assertFalse(actions_model.ledger_behind(self.paths, written), "a terminal's session is not the app's")
        self.register("idle", changed=NOW - 30)
        unknown = self.written_at(None)
        self.assertIsNone(unknown.generated_at, "the arrangement: a status that says no time")
        self.assertTrue(actions_model.ledger_behind(self.paths, unknown), "no pass time")


class SyncStatusTest(SyncHomeTestCase):
    """The account sync's Status counts the desktop app's sessions at work off the registry, as the window does."""

    def setUp(self):
        super().setUp()
        self.registry = self.home / ".claude" / "sessions"
        self.registry.mkdir(parents=True)
        self.start = own_creation()

    def status(self) -> str:
        return self.run_sync("-Mode", "Status").stdout

    def test_status_counts_busy_desktop_sessions_of_live_processes(self):
        pid = os.getpid()
        (self.registry / f"{pid}.json").write_text(json.dumps(entry(pid, self.start)), encoding="utf-8")
        (self.registry / "4.json").write_text(json.dumps(entry(4, 1, session=OTHER)), encoding="utf-8")
        (self.registry / f"{pid}.0123abcd.key").write_text("never read", encoding="utf-8")
        self.assertRegex(self.status(), r"Working sessions: 1\b")
        (self.registry / f"{pid}.json").write_text(json.dumps(entry(pid, self.start, entrypoint="cli")),
                                                   encoding="utf-8")
        self.assertRegex(self.status(), r"Working sessions: 0\b")


if __name__ == "__main__":
    unittest.main()
