"""The service's keep-awake (windowtally/keep_awake.py) and its switch: the power request held while a Claude Code
session works and the switch allows it, released otherwise; the request's kinds and words; the switch kept in the
settings, on by default, and the window's View and tray menus that turn it.

Expected values follow the module's statement in ``windowtally/keep_awake.py`` and the settings' in
``windowtally/settings.py``. No test here holds a power request on the machine: the power API is a stand-in, and so is
Windows' kernel32 where the request itself is read.
"""

import ctypes
import json
import threading
import unittest

from fixtures import Machine
from windowtally.keep_awake import REASON, KeepAwake, ReasonContext, WindowsPowerRequests
from windowtally.registry import Reading, Session
from windowtally.settings import (Settings, SettingsError, load_settings, save_settings, set_keep_awake,
                                  set_notifications_silenced)
from windowtally_gui import actions_model


class Power:
    """A stand-in for Windows' power requests, recording what was asked."""

    def __init__(self, refuse: bool = False):
        self.calls: list[str] = []
        self.refuse = refuse

    def hold(self, reason: str) -> None:
        self.calls.append(f"hold {reason}")
        if self.refuse:
            raise OSError("refused")

    def release(self) -> None:
        self.calls.append("release")


def session(status: str | None, entrypoint: str = "claude-desktop", sid: str = "s") -> Session:
    return Session(1, sid, status, entrypoint, None)


class Registry:
    """A stand-in for the registry's reading, set by the test between looks."""

    def __init__(self):
        self.reading = Reading()

    def __call__(self, _dir, _processes):
        return self.reading


class KeepAwakeTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.paths = self.machine.paths
        self.power = Power()
        self.registry = Registry()
        self.keeper = KeepAwake(self.paths.registry_dir, self.paths.settings_file, self.power, read=self.registry)

    def tearDown(self):
        self.machine.close()

    def at_work(self, *sessions: Session, problems: tuple[str, ...] = ()) -> None:
        self.registry.reading = Reading(tuple(sessions), problems)

    def test_nothing_is_held_while_no_session_is_at_work(self):
        self.at_work(session("idle"), session("waiting"), session("shell"), session(None))
        self.assertFalse(self.keeper.look())
        self.assertEqual(self.power.calls, [])

    def test_a_session_at_work_holds_the_request_once_and_its_end_releases_it(self):
        self.at_work(session("busy"))
        self.assertTrue(self.keeper.look())
        self.assertTrue(self.keeper.look())
        self.at_work(session("busy", sid="a"), session("busy", "cli", sid="b"))
        self.assertTrue(self.keeper.look())
        self.assertEqual(self.power.calls, [f"hold {REASON}"], "held once, however many sessions work")
        self.at_work(session("idle"))
        self.assertFalse(self.keeper.look())
        self.assertEqual(self.power.calls, [f"hold {REASON}", "release"])

    def test_a_terminals_and_a_scripted_runs_session_hold_it_as_the_desktop_apps_does(self):
        for entrypoint in ("cli", "sdk-cli", "claude-desktop"):
            with self.subTest(entrypoint):
                self.at_work(session("busy", entrypoint))
                self.assertTrue(self.keeper.look())
                self.at_work()
                self.assertFalse(self.keeper.look())

    def test_the_switch_off_releases_the_request_and_on_takes_it_again(self):
        self.at_work(session("busy"))
        self.keeper.look()
        set_keep_awake(self.paths.settings_file, False)
        self.assertFalse(self.keeper.look())
        self.assertFalse(self.keeper.look())
        set_keep_awake(self.paths.settings_file, True)
        self.assertTrue(self.keeper.look())
        self.assertEqual(self.power.calls, [f"hold {REASON}", "release", f"hold {REASON}"])

    def test_settings_that_cannot_be_read_keep_the_computer_awake(self):
        self.machine.settings({"v": 1, "keepAwakeOff": "yes"})
        with self.assertRaises(SettingsError):
            load_settings(self.paths.settings_file)
        self.at_work(session("busy"))
        self.assertTrue(self.keeper.look())

    def test_a_refused_request_is_logged_once_and_tried_again_at_the_next_look(self):
        self.keeper.power = Power(refuse=True)
        self.at_work(session("busy"))
        with self.assertLogs("windowtally.keep_awake", level="WARNING") as said:
            self.assertFalse(self.keeper.look())
            self.assertFalse(self.keeper.look())
        self.assertEqual(len(said.records), 1)
        self.assertEqual(len(self.keeper.power.calls), 2, "each look tries again")
        self.keeper.power.refuse = False
        self.assertTrue(self.keeper.look())

    def test_the_registrys_problems_are_logged_when_they_change_not_at_every_look(self):
        self.at_work(problems=("registry: 1.json is odd",))
        with self.assertLogs("windowtally.keep_awake", level="WARNING") as said:
            self.keeper.look()
            self.keeper.look()
            self.at_work(problems=("registry: 2.json is odd",))
            self.keeper.look()
        self.assertEqual([r.getMessage() for r in said.records], ["registry: 1.json is odd", "registry: 2.json is odd"])

    def test_the_loop_outlives_a_failing_look_and_releases_when_stopped(self):
        stop = threading.Event()
        looks = []

        def read(_dir, _processes):
            looks.append(1)
            if len(looks) == 1:
                raise RuntimeError("a look that fails")
            if len(looks) >= 3:
                stop.set()
            return Reading((session("busy"),))

        self.keeper._read = read
        with self.assertLogs("windowtally.keep_awake", level="ERROR"):
            self.keeper.run(stop, interval=0.01)
        self.assertGreaterEqual(len(looks), 3)
        self.assertEqual(self.power.calls[0], f"hold {REASON}")
        self.assertEqual(self.power.calls[-1], "release")
        self.assertFalse(self.keeper.holding)


class Kernel32:
    """A stand-in for kernel32's power-request functions, recording each call."""

    def __init__(self, refuse_kind: int | None = None):
        self.calls: list[tuple] = []
        self.refuse_kind = refuse_kind
        self.reason: str | None = None

    def PowerCreateRequest(self, context_ref):
        context = context_ref._obj   # what ctypes.byref was given
        assert isinstance(context, ReasonContext), type(context)
        self.reason = context.reason.simple
        self.calls.append(("create", context.version, context.flags))
        return 1234

    def PowerSetRequest(self, handle, kind):
        self.calls.append(("set", handle, kind))
        return 0 if kind == self.refuse_kind else 1

    def PowerClearRequest(self, handle, kind):
        self.calls.append(("clear", handle, kind))
        return 1

    def CloseHandle(self, handle):
        self.calls.append(("close", handle))
        return 1


class WindowsRequestTest(unittest.TestCase):
    """The request Windows is asked for: the system and execution, never the display; nothing in it, or in the look
    that takes it, asks whether the computer runs on battery or on mains, so it is the same on both."""

    SYSTEM, DISPLAY, EXECUTION = 1, 0, 3

    def test_the_request_keeps_the_system_and_execution_and_never_the_display(self):
        k = Kernel32()
        power = WindowsPowerRequests(k)
        power.hold(REASON)
        power.hold(REASON)
        self.assertEqual(k.reason, REASON)
        self.assertEqual(k.calls, [("create", 0, 1), ("set", 1234, self.SYSTEM), ("set", 1234, self.EXECUTION)],
                         "one request, made once, carrying its words as a simple string")
        power.release()
        power.release()
        self.assertEqual(k.calls[3:], [("clear", 1234, self.SYSTEM), ("clear", 1234, self.EXECUTION),
                                       ("close", 1234)])
        self.assertNotIn(self.DISPLAY, [call[2] for call in k.calls if call[0] in ("set", "clear")])

    def test_a_refused_part_closes_the_request_and_raises(self):
        k = Kernel32(refuse_kind=self.EXECUTION)
        power = WindowsPowerRequests(k)
        with self.assertRaises(OSError):
            power.hold(REASON)
        self.assertIn(("close", 1234), k.calls)
        power.release()
        self.assertEqual(k.calls.count(("close", 1234)), 1, "nothing is left to release")


class SwitchSettingTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.path = self.machine.paths.settings_file

    def tearDown(self):
        self.machine.close()

    def test_on_by_default_and_absent_from_the_file_while_on(self):
        self.assertFalse(load_settings(self.path).keep_awake_off)
        set_notifications_silenced(self.path, True)
        self.assertNotIn("keepAwakeOff", json.loads(self.path.read_text(encoding="utf-8")))

    def test_turned_off_and_on_keeping_every_other_setting(self):
        save_settings(self.path, Settings(renewal_reminder_days=3, silence_notifications=True))
        set_keep_awake(self.path, False)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")),
                         {"v": 1, "renewalReminderDays": 3, "silenceNotifications": True, "keepAwakeOff": True})
        self.assertEqual(load_settings(self.path),
                         Settings(renewal_reminder_days=3, silence_notifications=True, keep_awake_off=True))
        set_keep_awake(self.path, True)
        self.assertEqual(load_settings(self.path), Settings(renewal_reminder_days=3, silence_notifications=True))

    def test_a_value_that_is_not_true_or_false_refuses_the_file(self):
        for value in (1, "no", None):
            self.machine.settings({"v": 1, "keepAwakeOff": value})
            with self.subTest(value), self.assertRaises(SettingsError) as caught:
                load_settings(self.path)
            self.assertIn(f"keepAwakeOff is {value!r}, not true or false", str(caught.exception))

    def test_the_window_turns_the_switch_and_reads_it_back(self):
        paths = self.machine.paths
        self.assertIs(actions_model.keep_awake(paths), True)
        off = actions_model.set_keep_awake(paths, False)
        self.assertTrue(off.ok, off.message)
        self.assertIs(actions_model.keep_awake(paths), False)
        on = actions_model.set_keep_awake(paths, True)
        self.assertTrue(on.ok, on.message)
        self.assertIn("screen still turns off", on.message)
        self.assertIs(actions_model.keep_awake(paths), True)

    def test_settings_that_cannot_be_read_are_said_and_read_back_as_unknown(self):
        self.machine.settings({"v": 2})
        outcome = actions_model.set_keep_awake(self.machine.paths, False)
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.message.startswith("Not changed: "))
        self.assertIsNone(actions_model.keep_awake(self.machine.paths))


if __name__ == "__main__":
    unittest.main()
