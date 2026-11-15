"""install.ps1's Status mode, and the copying of the installed copy, run for real against a simulated home.

Status compares the installed copies with the folder the script runs from, so the test copies this tool's files
into a temporary source folder — where it can give them the CRLF endings a Git checkout under core.autocrlf
writes — and points USERPROFILE, APPDATA and LOCALAPPDATA at a temporary home holding LF copies and, where a test
writes one, a Start menu entry. PowerShell runs in the temporary folder, so whatever it writes by a relative path
stays there. The Claude Code CLI path names a file that does not exist, or a stub that prints a canned plugin
list, so no Claude Code command runs; the scheduled tasks and the browser extension's registry key are only read.

Install and Uninstall are not run: they register and remove the machine's own scheduled tasks, whose names no
environment redirects, so even a test of their refusal of a missing interpreter would register or remove real tasks
the moment that refusal failed. Install's copying of the installed copy, which touches no task, is run on its own:
the script is dot-sourced in Status mode, which defines its functions, and its copying function is then called.
A release-shaped source folder holds a runtime\\ of stand-in files, never started.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import fixtures

POWERSHELL = shutil.which("powershell.exe")
PYTHONW = Path(sys.executable).with_name("pythonw.exe")
TOOL = fixtures.TOOL_ROOT
PACKAGES = ("windowtally", "windowtally_gui")
PLUGIN_PARTS = (".claude-plugin", "hooks", "types")
PLUGIN_ID = "windowtally@windowtally-local"
START_MENU = Path("AppData") / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"

# A stand-in for the CLI: `plugin list --json` prints plugins.json (or exits 1 beside a file named fail), and
# `plugin marketplace list --json` prints an empty list. CRLF throughout: cmd.exe misreads labels in LF batch files.
STUB_CLI = "\r\n".join([
    "@echo off",
    'if "%1 %2 %3"=="plugin list --json" goto list',
    'if "%1 %2 %3 %4"=="plugin marketplace list --json" goto markets',
    "exit /b 9",
    ":list",
    'if exist "%~dp0fail" exit /b 1',
    'type "%~dp0plugins.json"',
    "exit /b 0",
    ":markets",
    "echo []",
    "exit /b 0",
    "",
])


def copy_with_endings(source: Path, target: Path, crlf: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes().replace(b"\r\n", b"\n")
    target.write_bytes(data.replace(b"\n", b"\r\n") if crlf else data)


def tool_files() -> list[Path]:
    """The files of this tool that Install copies or Status compares, relative to the tool folder."""
    files = [Path("install.ps1")]
    for package in PACKAGES:
        files += [p.relative_to(TOOL) for p in (TOOL / package).glob("*.py")]
    files += [p.relative_to(TOOL) for p in (TOOL / "sync").iterdir() if p.is_file()]
    for part in PLUGIN_PARTS:
        files += [p.relative_to(TOOL) for p in (TOOL / "plugin" / part).rglob("*") if p.is_file()]
    files += [p.relative_to(TOOL) for p in (TOOL / "extension").rglob("*") if p.is_file()]
    return files


@unittest.skipUnless(os.name == "nt" and POWERSHELL and PYTHONW.is_file(), "install.ps1 runs on Windows PowerShell")
class InstallStatusTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="installtest-")
        root = Path(self.temp.name)
        self.source = root / "source"
        self.home = root / "home"
        self.data = self.home / ".claude" / "windowtally"
        # Windows PowerShell resolves its local application data folder from USERPROFILE, not LOCALAPPDATA; with none
        # in the home it writes its module analysis cache into the working directory instead.
        (self.home / "AppData" / "Local").mkdir(parents=True)
        for relative in tool_files():
            copy_with_endings(TOOL / relative, self.source / relative, crlf=True)

    def tearDown(self):
        self.temp.cleanup()

    def install_copies(self) -> None:
        """LF copies where Install puts them, and a status for the service's own report to print."""
        for name in ("WindowTallySync.ps1", "claude.cmd"):
            copy_with_endings(TOOL / "sync" / name, self.home / ".claude" / "bin" / name, crlf=False)
        for package in PACKAGES:
            for module in (TOOL / package).glob("*.py"):
                copy_with_endings(module, self.data / "app" / package / module.name, crlf=False)
        for relative in tool_files():
            if relative.parts[0] in ("plugin", "extension"):
                copy_with_endings(TOOL / relative, self.data / Path(*relative.parts), crlf=False)
        status = fixtures.status_document([], at=time.time(),
                                          recommended={"account": None, "reason": "No account is known yet.",
                                                       "reliefAt": None, "reliefExact": False},
                                          thisMonth={"apiEquivalent": None, "plansAtListPrice": None})
        (self.data / "status.json").write_text(json.dumps(status), encoding="utf-8")

    def stub_cli(self, plugins: list[dict], fail: bool = False) -> Path:
        folder = self.home / "stub-cli"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "claude.cmd").write_bytes(STUB_CLI.encode("ascii"))
        (folder / "plugins.json").write_text(json.dumps(plugins), encoding="utf-8")
        if fail:
            (folder / "fail").write_text("", encoding="utf-8")
        return folder / "claude.cmd"

    def status(self, cli: Path | None = None, python: Path | None = PYTHONW) -> str:
        """Status's report; ``python`` None names no interpreter, leaving the script to its default."""
        environment = dict(os.environ, USERPROFILE=str(self.home), APPDATA=str(self.home / "AppData" / "Roaming"),
                           LOCALAPPDATA=str(self.home / "AppData" / "Local"))
        interpreter = ["-Python", str(python)] if python is not None else []
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
             str(self.source / "install.ps1"), "-Mode", "Status", *interpreter,
             "-Claude", str(cli or self.home / "no-such-dir" / "claude.exe")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, env=environment,
            cwd=self.temp.name)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_copies_that_differ_only_in_line_endings_match(self):
        self.install_copies()
        report = self.status()
        self.assertRegex(report, r"WindowTallySync\.ps1\s*: installed copy matches")
        self.assertRegex(report, r"claude\.cmd\s*: installed copy matches")
        self.assertRegex(report, r"Service copy\s*: matches")
        self.assertRegex(report, r"Window copy\s*: matches")
        self.assertRegex(report, r"Plugin copy\s*: matches")
        self.assertRegex(report, r"Plugin windowtally\s*: unknown: no Claude Code CLI at ")
        self.assertRegex(report, r"Task \\WindowTally\\Window\s*: ")
        self.assertIn("No account is known yet.", report, "the service's own report follows")

    def test_a_copy_that_differs_in_content_still_differs(self):
        self.install_copies()
        changed = self.data / "plugin" / "hooks" / "band.tsx"
        changed.write_bytes(changed.read_bytes() + b"// changed\n")
        (self.home / ".claude" / "bin" / "claude.cmd").write_bytes(b"@echo off\n")
        window = self.data / "app" / "windowtally_gui" / "main_view.py"
        window.write_bytes(window.read_bytes() + b"# changed\n")
        report = self.status()
        self.assertRegex(report, r"Plugin copy\s*: DIFFERS \(hooks\\band\.tsx\)")
        self.assertRegex(report, r"claude\.cmd\s*: installed copy DIFFERS")
        self.assertRegex(report, r"Window copy\s*: DIFFERS \(main_view\.py\)")
        self.assertRegex(report, r"Service copy\s*: matches")

    def test_the_extensions_copy_and_its_host_are_reported(self):
        """The host's line reads the machine's own registry, which the test only reads: what it says depends on this
        machine, so only that it is reported is checked."""
        report = self.status()
        self.assertRegex(report, r"Extension copy\s*: not installed")
        self.assertRegex(report, r"Browser host\s*: \S")
        self.install_copies()
        self.assertRegex(self.status(), r"Extension copy\s*: matches")
        page = self.data / "extension" / "page.js"
        page.write_bytes(page.read_bytes() + b"// changed\n")
        self.assertRegex(self.status(), r"Extension copy\s*: DIFFERS \(extension\\page\.js\)")

    def test_the_licence_s_copy_is_reported_beside_the_packages(self):
        self.install_copies()
        self.assertRegex(self.status(), r"Licence copy\s*: not installed")
        copy_with_endings(TOOL / "LICENSE", self.source / "LICENSE", crlf=True)
        copy_with_endings(TOOL / "LICENSE", self.data / "app" / "LICENSE", crlf=False)
        self.assertRegex(self.status(), r"Licence copy\s*: matches")
        installed = self.data / "app" / "LICENSE"
        installed.write_bytes(installed.read_bytes().replace(b"2026", b"2025"))
        self.assertRegex(self.status(), r"Licence copy\s*: DIFFERS")

    def test_status_after_uninstall_reports_rather_than_fails(self):
        report = self.status()
        self.assertRegex(report, r"Service copy\s*: not installed")
        self.assertRegex(report, r"Window copy\s*: not installed")
        self.assertRegex(report, r"Plugin copy\s*: not installed")
        self.assertRegex(report, r"Start menu entry\s*: absent")

    def test_the_start_menu_entry_is_reported_where_windows_reads_it(self):
        entry = self.home / START_MENU / "WindowTally.lnk"
        entry.parent.mkdir(parents=True)
        entry.write_bytes(b"a link")
        self.assertRegex(self.status(), r"Start menu entry\s*: present")

    def test_the_folder_sessions_read_the_plugin_from_is_reported(self):
        self.install_copies()
        entry = {"id": PLUGIN_ID, "version": "1.0.0", "scope": "user", "enabled": True}
        report = self.status(self.stub_cli([dict(entry, readFromFolder=str(self.data / "plugin"))]))
        self.assertRegex(report, r"Plugin windowtally\s*: installed at user scope, enabled, read from the installed copy")
        report = self.status(self.stub_cli([dict(entry, readFromFolder=r"D:\work\plugin")]))
        self.assertIn(r"read from D:\work\plugin, NOT the installed copy", report)
        report = self.status(self.stub_cli([entry]))
        self.assertIn("served from its install cache, NOT the installed copy", report)

    def test_a_failing_cli_leaves_the_rest_of_the_report(self):
        self.install_copies()
        report = self.status(self.stub_cli([], fail=True))
        self.assertRegex(report, r"Plugin windowtally\s*: unknown: claude plugin list --json exited with 1")
        self.assertRegex(report, r"Plugin copy\s*: matches")
        self.assertIn("No account is known yet.", report)

    def release_shape(self) -> Path:
        """The source folder made a release's: its runtime\\ of stand-in files, its notices and its build record. The
        runtime holds no python.exe, so Status, which reads the standing through the console interpreter beside the
        installed copy's, starts nothing; its stand-in pythonw.exe is never started either."""
        runtime = self.source / "runtime"
        for name, data in (("pythonw.exe", b"MZ stand-in"), ("python314.dll", b"a library"),
                           ("Lib/tkinter/__init__.py", b"# tk\n")):
            (runtime / name).parent.mkdir(parents=True, exist_ok=True)
            (runtime / name).write_bytes(data)
        copy_with_endings(TOOL / "LICENSE", self.source / "LICENSE", crlf=True)
        (self.source / "THIRD-PARTY-NOTICES.txt").write_text("Third-party notices\n", encoding="utf-8")
        (self.source / "build.json").write_text('{"label": "2027.5.1"}\n', encoding="utf-8")
        return runtime / "pythonw.exe"

    def dot_sourced(self, python: Path, commands: str, *, refused: bool = False) -> str:
        """The script dot-sourced in Status mode with ``python`` as -Python, then ``commands`` run with its functions;
        what they printed, or, where ``refused``, what the refusal said."""
        environment = dict(os.environ, USERPROFILE=str(self.home), APPDATA=str(self.home / "AppData" / "Roaming"),
                           LOCALAPPDATA=str(self.home / "AppData" / "Local"))
        script = (f"& {{ . '{self.source / 'install.ps1'}' -Mode Status -Python '{python}' "
                  f"-Claude '{self.home / 'no-such-dir' / 'claude.exe'}'; {commands} }}")
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                                 script], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=180, env=environment, cwd=self.temp.name)
        if refused:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            return " ".join((result.stdout + result.stderr).split())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def copy_installed(self, python: Path) -> str:
        """Install's copying of the installed copy, run alone with ``python`` as -Python; the interpreter the installed
        copy then runs under, as the script reads it."""
        output = self.dot_sourced(python, "Copy-InstalledCopy; Write-Output ('INSTALLED=' + (Get-InstalledPython))")
        return next(line[len("INSTALLED="):] for line in output.splitlines() if line.startswith("INSTALLED="))

    def test_a_release_s_runtime_notices_and_build_record_are_copied_beside_the_installed_packages(self):
        release_python = self.release_shape()
        installed = self.copy_installed(release_python)
        app = self.data / "app"
        self.assertEqual(Path(installed), app / "runtime" / "pythonw.exe", "the installed copy runs under its own")
        for name in ("pythonw.exe", "python314.dll", "Lib/tkinter/__init__.py"):
            self.assertEqual((app / "runtime" / name).read_bytes(), (self.source / "runtime" / name).read_bytes())
        for name in ("LICENSE", "THIRD-PARTY-NOTICES.txt", "build.json"):
            self.assertTrue((app / name).is_file(), name)
        self.assertTrue((app / "windowtally" / "release.py").is_file())
        report = self.status(python=release_python)
        for line in ("Licence copy", "Notices copy", "Build record copy", "Runtime copy"):
            self.assertRegex(report, line + r"\s*: matches")
        self.assertIn(str(app / "runtime" / "python.exe") + "; install again", report,
                      "the standing is read through the console interpreter beside the installed copy's, whatever "
                      "-Python names")

    def test_an_interpreter_given_elsewhere_runs_the_installed_copy_where_it_is_and_takes_a_release_s_files_away(self):
        self.copy_installed(self.release_shape())
        for name in ("THIRD-PARTY-NOTICES.txt", "build.json"):
            (self.source / name).unlink()
        shutil.rmtree(self.source / "runtime")
        report = self.status()
        self.assertRegex(report, r"Notices copy\s*: installed; this folder ships none")
        self.assertRegex(report, r"Build record copy\s*: installed; this folder ships none")
        self.assertRegex(report, r"Runtime copy\s*: installed; this folder carries none")
        installed = self.copy_installed(PYTHONW)
        app = self.data / "app"
        self.assertEqual(Path(installed), PYTHONW)
        self.assertFalse((app / "runtime").exists(), "a runtime an earlier release left is removed")
        self.assertFalse((app / "THIRD-PARTY-NOTICES.txt").exists())
        self.assertFalse((app / "build.json").exists(), "a copy installed from source names no release")
        self.assertTrue((app / "LICENSE").is_file())
        self.install_copies()
        report = self.status()
        self.assertRegex(report, r"Notices copy\s*: not installed")
        self.assertRegex(report, r"Runtime copy\s*: none: the installed copy runs under the interpreter Install was")

    def test_a_process_still_running_from_the_installed_runtime_is_named_and_nothing_is_replaced(self):
        """A copy of ping stands in for a command the user started under the installed copy's Python: Windows refuses
        to delete a running program's file, and the script ends no process of the user's, so it refuses, naming it,
        and replaces the runtime once the process has ended."""
        release_python = self.release_shape()
        self.copy_installed(release_python)
        stand_in = self.data / "app" / "runtime" / "stand-in.exe"
        shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32" / "PING.EXE", stand_in)
        process = subprocess.Popen([str(stand_in), "-n", "120", "127.0.0.1"], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        refusal = self.dot_sourced(release_python, "Copy-InstalledCopy", refused=True)
        self.assertIn(f"Still running under the installed copy's Python: stand-in.exe ({process.pid})", refusal)
        self.assertIsNone(process.poll(), "the user's process is left running")
        self.assertTrue(stand_in.is_file(), "nothing was replaced")
        process.kill()
        process.wait()
        self.copy_installed(release_python)
        self.assertFalse(stand_in.exists(), "the runtime was replaced by the release's")
        self.assertTrue((self.data / "app" / "runtime" / "pythonw.exe").is_file())

    def test_install_refuses_the_installed_copy_s_own_python_which_it_would_replace(self):
        self.copy_installed(self.release_shape())
        own = self.data / "app" / "runtime" / "pythonw.exe"
        refusal = self.dot_sourced(PYTHONW, f"$Mode = 'Install'; $Python = '{own}'; Assert-Interpreter", refused=True)
        self.assertIn("is the installed copy's own Python, which Install replaces", refusal)
        self.dot_sourced(PYTHONW, f"$Mode = 'Uninstall'; $Python = '{own}'; Assert-Interpreter")
        self.dot_sourced(PYTHONW, "$Mode = 'Install'; Assert-Interpreter")

    def test_install_refuses_an_interpreter_the_window_cannot_start_under_and_asks_nothing_of_a_release_s_own(self):
        """A copy of ping stands in for an interpreter without PySide6: asked to import it, it exits on an option it
        cannot take. A release's own interpreter, a stand-in file that cannot be started, is not asked; nor is any
        interpreter for Uninstall, which starts no window."""
        stand_in = Path(self.temp.name) / "no-qt" / "pythonw.exe"
        stand_in.parent.mkdir()
        shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32" / "PING.EXE", stand_in)
        refusal = self.dot_sourced(PYTHONW, f"$Mode = 'Install'; $Python = '{stand_in}'; Assert-Interpreter",
                                   refused=True)
        squeezed = refusal.replace(" ", "")     # PowerShell wraps an error at its width, within a word too
        self.assertIn("cannotimportPySide6,whichthewindowisdrawnwith", squeezed)
        self.assertIn("installPySide6-Essentialsintoit", squeezed)
        release_python = self.release_shape()
        self.dot_sourced(PYTHONW, f"$Mode = 'Install'; $Python = '{release_python}'; Assert-Interpreter")
        self.dot_sourced(PYTHONW, f"$Mode = 'Uninstall'; $Python = '{stand_in}'; Assert-Interpreter")

    def test_a_release_s_runtime_copy_that_differs_is_reported(self):
        release_python = self.release_shape()
        self.copy_installed(release_python)
        (self.data / "app" / "runtime" / "python314.dll").write_bytes(b"another library")
        (self.data / "app" / "runtime" / "left-over.dll").write_bytes(b"a library no release carries")
        (self.data / "app" / "build.json").write_text('{"label": "2027.4.1"}\n', encoding="utf-8")
        report = self.status(python=release_python)
        self.assertRegex(report, r"Runtime copy\s*: DIFFERS \(2 files\)")
        self.assertRegex(report, r"Build record copy\s*: DIFFERS")
        self.assertRegex(report, r"Notices copy\s*: matches")

    def test_without_an_interpreter_status_says_it_shows_no_standing(self):
        """A source folder carries no runtime\\ of its own, so with no -Python the default names none that exists."""
        self.install_copies()
        report = self.status(python=None)
        self.assertRegex(report, r"Service copy\s*: matches")
        self.assertRegex(report, r"Standing\s*: not shown: no interpreter at ")
        self.assertIn(str(self.source / "runtime" / "python.exe") + "; pass -Python", report)
        self.assertNotIn("No account is known yet.", report)


if __name__ == "__main__":
    unittest.main()
