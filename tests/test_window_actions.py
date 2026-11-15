"""The window's buttons that reach past the bills — a pass now, the data folder — and the machinery
around them: work done off the window's thread, one window per user, the Start menu entry."""

import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from fixtures import ACCOUNT_A, EMAIL_A, ORG_A, Machine
from windowtally import service
from windowtally.service import PassLock
from windowtally_gui import actions_model, instance_model, logo_model, shortcut
from windowtally_gui.background import Background


class PassActionsTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.paths = self.machine.paths

    def tearDown(self):
        self.machine.close()

    def test_refresh_runs_a_pass_and_says_how_it_went(self):
        outcome = actions_model.refresh(self.paths)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertRegex(outcome.message, r"^Refreshed in \d+\.\d s\.$")
        self.assertTrue(self.paths.status_file.is_file())

    def test_a_refresh_waiting_past_another_pass_says_so(self):
        with PassLock(self.paths.pass_lock), mock.patch.object(service, "PASS_LOCK_PATIENCE", 0.2):
            outcome = actions_model.refresh(self.paths)
        self.assertFalse(outcome.ok)
        self.assertIn("Not refreshed: another pass has held", outcome.message)

    def test_an_opener_that_fails_is_said(self):
        def refuse(_target):
            raise OSError("no browser")

        self.assertEqual(actions_model.data_folder(self.paths, refuse).message,
                         "The data folder was not opened: no browser")
        opened = []
        self.assertTrue(actions_model.data_folder(self.paths, opened.append).ok)
        self.assertEqual(opened, [self.paths.data_dir])


class PassAfterChangeTest(unittest.TestCase):
    """What the status line says of a pass that follows a change: the change's words first, in its colour."""

    def test_a_pass_on_its_own_says_only_its_own_word(self):
        refreshed = actions_model.Outcome(True, "Refreshed in 1.2 s.")
        self.assertEqual(actions_model.after(None, refreshed), refreshed)

    def test_a_change_that_was_done_keeps_its_words_ahead_of_the_pass(self):
        saved = actions_model.Outcome(True, "Recorded the bill.")
        self.assertEqual(actions_model.after(saved, actions_model.Outcome(True, "Refreshed in 1.2 s.")),
                         actions_model.Outcome(True, "Recorded the bill. Refreshed in 1.2 s."))
        self.assertEqual(actions_model.after(saved, actions_model.Outcome(False, "Not refreshed: locked.")),
                         actions_model.Outcome(False, "Recorded the bill. Not refreshed: locked."),
                         "a pass that fails is said in the warning colour")

    def test_a_change_that_was_not_done_keeps_the_warning_colour_through_the_pass(self):
        refused = actions_model.Outcome(False, "Switched the desktop app to beta, but the app refused the login.")
        for pass_said in ("Reading every source…", "Refreshed in 1.2 s."):
            said = actions_model.after(refused, actions_model.Outcome(True, pass_said))
            self.assertEqual(said, actions_model.Outcome(False, f"{refused.message} {pass_said}"))


class BackgroundTest(unittest.TestCase):
    def wait(self, background: Background) -> None:
        deadline = time.monotonic() + 5
        while background.running is not None and time.monotonic() < deadline:
            background.poll()
            time.sleep(0.01)

    def test_one_job_at_a_time_its_result_delivered_where_poll_runs(self):
        background, got = Background(), []
        self.assertTrue(background.start("refresh", lambda: (time.sleep(0.1), 42)[1], got.append, got.append))
        self.assertFalse(background.start("history", lambda: 0, got.append, got.append), "a second job is refused")
        self.assertEqual(background.running, "refresh")
        self.wait(background)
        self.assertEqual((got, background.running), ([42], None))

    def test_a_job_that_raises_reaches_the_window_as_its_failure(self):
        background, got = Background(), []

        def fail():
            raise RuntimeError("broken")

        background.start("refresh", fail, got.append, lambda error: got.append(f"failed: {error}"))
        self.wait(background)
        self.assertEqual(got, ["failed: broken"])

    def test_a_failure_handler_that_raises_leaves_no_job_running(self):
        background = Background()

        def fail():
            raise RuntimeError("broken")

        def describe(_error):
            raise ValueError("cannot say")

        background.start("refresh", fail, print, describe)
        deadline = time.monotonic() + 5
        while background.running is not None and time.monotonic() < deadline:
            try:
                background.poll()
            except ValueError:
                pass  # the window's own error report takes it there
            time.sleep(0.01)
        self.assertIsNone(background.running)
        self.assertTrue(background.start("refresh", lambda: 1, print, print), "the next job starts")


class InstanceTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.paths = self.machine.paths

    def tearDown(self):
        self.machine.close()

    def test_a_second_start_asks_the_first_to_show_itself(self):
        first = instance_model.claim(self.paths)
        self.assertIsNotNone(first)
        try:
            self.assertIsNone(instance_model.claim(self.paths), "the lock is held")
            self.assertFalse(instance_model.take_request(self.paths))
            instance_model.ask_to_show(self.paths)
            self.assertTrue(instance_model.take_request(self.paths))
            self.assertFalse(instance_model.take_request(self.paths), "a request is taken once")
        finally:
            first.handle.close()

    def test_a_request_left_with_no_window_running_does_not_show_the_next(self):
        instance_model.ask_to_show(self.paths)
        lock = instance_model.claim(self.paths)
        try:
            self.assertFalse(instance_model.take_request(self.paths))
        finally:
            lock.handle.close()


class ShortcutTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.link = self.machine.paths.data_dir / "Start Menu" / "Programs" / shortcut.NAME

    def tearDown(self):
        self.machine.close()

    def test_the_entry_is_written_by_powershell_without_a_console_and_with_no_path_in_its_command(self):
        calls = []

        def run(command, **options):
            calls.append((command, options))
            self.link.write_text("link", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        target, folder = Path(r"C:\Tools\runtime\pythonw.exe"), Path(r"C:\Tools\app")
        shortcut.create_shortcut(self.link, target, "-m windowtally_gui", folder, run=run)
        ((command, options),) = calls
        self.assertTrue(command[0].lower().endswith("powershell.exe"))
        self.assertEqual(options["creationflags"], subprocess.CREATE_NO_WINDOW)
        self.assertNotIn(str(target), " ".join(command))
        environment = options["env"]
        self.assertEqual((environment["LINK_TARGET"], environment["LINK_ARGUMENTS"], environment["LINK_FOLDER"]),
                         (str(target), "-m windowtally_gui", str(folder)))
        self.assertTrue(shortcut.remove_shortcut(self.link))
        self.assertFalse(shortcut.remove_shortcut(self.link))

    def test_an_entry_already_there_under_another_case_takes_this_names_spelling(self):
        self.link.parent.mkdir(parents=True)
        self.link.with_name(shortcut.NAME.lower()).write_text("old link", encoding="utf-8")

        def run(command, **options):
            self.link.write_text("link", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        shortcut.create_shortcut(self.link, Path("pythonw.exe"), "-m windowtally_gui", Path("."), run=run)
        self.assertEqual([entry.name for entry in self.link.parent.iterdir()], [shortcut.NAME])
        self.assertEqual(self.link.read_text(encoding="utf-8"), "link")

    def test_an_entry_spelt_as_the_name_stands_when_its_rewrite_fails(self):
        self.link.parent.mkdir(parents=True)
        self.link.write_text("old link", encoding="utf-8")

        def run(command, **_options):
            return subprocess.CompletedProcess(command, 1, "", "access denied")

        with self.assertRaises(OSError):
            shortcut.create_shortcut(self.link, Path("pythonw.exe"), "-m windowtally_gui", Path("."), run=run)
        self.assertEqual(self.link.read_text(encoding="utf-8"), "old link")

    def test_a_shortcut_powershell_did_not_write_is_an_error(self):
        def run(command, **_options):
            return subprocess.CompletedProcess(command, 1, "", "access denied")

        with self.assertRaises(OSError) as caught:
            shortcut.create_shortcut(self.link, Path("pythonw.exe"), "-m windowtally_gui", Path("."), run=run)
        self.assertIn("access denied", str(caught.exception))

    def test_the_entry_lives_in_the_start_menu_of_appdata(self):
        with mock.patch.dict("os.environ", {"APPDATA": r"C:\Users\someone\AppData\Roaming"}):
            self.assertEqual(shortcut.shortcut_path(),
                             Path(r"C:\Users\someone\AppData\Roaming\Microsoft\Windows\Start Menu\Programs")
                             / shortcut.NAME)
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(shortcut.shortcut_path())

    def test_the_entry_shows_the_icon_it_is_handed_and_otherwise_its_target_s(self):
        calls = []

        def run(command, **options):
            calls.append((command, options))
            self.link.write_text("link", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        icon = Path(r"C:\Tools\app") / shortcut.ICON_NAME
        shortcut.create_shortcut(self.link, Path("pythonw.exe"), "-m windowtally_gui", Path("."), icon=icon, run=run)
        shortcut.create_shortcut(self.link, Path("pythonw.exe"), "-m windowtally_gui", Path("."), run=run)
        (with_icon, with_options), (_without, without_options) = calls
        self.assertEqual(with_options["env"]["LINK_ICON"], str(icon))
        self.assertEqual(without_options["env"]["LINK_ICON"], "")
        self.assertNotIn(str(icon), " ".join(with_icon), "the icon's path is handed in the environment")
        self.assertIn("$link.IconLocation = $env:LINK_ICON + ',0'", with_icon[-1])

    def test_the_icon_file_is_the_logo_drawn_at_every_size(self):
        icon = self.machine.paths.data_dir / "app" / shortcut.ICON_NAME
        icon.parent.mkdir(parents=True)
        self.assertEqual(shortcut.write_icon(icon), icon)
        data = icon.read_bytes()
        self.assertEqual(data[:4], b"\x00\x00\x01\x00", "a Windows icon file")
        self.assertEqual(data[4:6], len(logo_model.ICON_SIZES).to_bytes(2, "little"))


if __name__ == "__main__":
    unittest.main()
