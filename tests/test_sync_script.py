"""The account sync (sync/WindowTallySync.ps1), run for real against a simulated home.

The script takes its home, the desktop app's config and the CLI's path as parameters, and its mutex names carry its
store's path, so a simulated home never touches or contends with the real one. The CLI path points at a file that
does not exist, so no running process is ever mistaken for the simulated CLI; a test that needs a CLI running starts
a stand-in at a path of its own. Credentials are fake and are sealed with the current Windows user's DPAPI key,
exactly as the script seals real ones. One test runs the launcher, claude.cmd, itself, under a home of its own with
stand-ins for the CLI and the sync beside it.

The desktop app is simulated the same way, and with more care, because the script closes the app it finds: every
call carries a ``-DesktopAppDir`` that holds no real app, and the script refuses a ``-DesktopConfig`` of its own
without one (``test_a_simulated_desktop_must_come_with_an_app_folder_of_its_own``). A test that needs a running app
starts a fake one from that folder: a copy of powershell.exe renamed Claude.exe, hosting a window that answers
WM_QUERYENDSESSION and exits on WM_ENDSESSION as the real app is said to; the script waits for it as long as for the
real app, save in the tests that mean it to outlive that wait (``REFUSAL_CLOSE_SECONDS``). A switch reads the
restarted app's log for its word on the login, and a simulated desktop reads only a log given with it: the tests'
launcher writes to a log of the test's the lines the real app writes as it starts. A signed-in desktop's config.json
carries the sign-in mark ``windowSizeWasSignedIn`` true, as the real app's does; a test leaves the app at its sign-in
page as a sign-out in it does, the login values kept and the mark set false.

The app's package folder also holds a Windows service, which runs in session 0 and outlives every close of the app.
A test cannot register a service, so ``run_sync(..., service=True)`` runs the script with an entry for one added to
the process list it reads: a session-0 process of the app folder whose id belongs to no live process. The tests that
start a fake app run only from a user session, which is where the real app's own processes run.
"""

import base64
import ctypes
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import fixtures  # noqa: F401  (puts the tool folder on the import path)

SCRIPT = fixtures.TOOL_ROOT / "sync" / "WindowTallySync.ps1"
POWERSHELL = shutil.which("powershell.exe")
ALPHA = "aaaaaaaa-0000-4000-8000-000000000001"
BETA = "bbbbbbbb-0000-4000-8000-000000000002"
GAMMA = "cccccccc-0000-4000-8000-000000000003"
RELEASE_WAIT_S = 10.0  # how long a test's folder may stay held by Windows after its processes have ended
# The -CloseSeconds of the tests that mean the fake app to outlive its close, short so that they end soon. Every other
# run keeps the script's own, which a closing app never reaches: the wait ends at the first listing that finds the app
# gone, which came 0.01 s after it was told the session ends, and the app was gone 0.02 to 0.21 s after it, with every
# processor busy and the whole suite running beside it (60 closes, measured on the development machine, 2026-11-14).
# A bound this short on a run whose subject is not the close turns a stall of the machine into the test's red.
REFUSAL_CLOSE_SECONDS = "5"

# A stored CLI sign-in unsealed as the script seals it, written out in base64.
UNSEAL = r"""
Add-Type -AssemblyName System.Security
$sealed = [IO.File]::ReadAllBytes(@PATH@)
$plain = [Security.Cryptography.ProtectedData]::Unprotect($sealed, [Text.Encoding]::UTF8.GetBytes('WindowTallySync'), 'CurrentUser')
[Console]::Out.Write([Convert]::ToBase64String($plain))
"""

# A stand-in for the CLI that claude.cmd runs: it ends with the exit code FAKE_CLI_EXIT names, 0 by default.
BUILD_FAKE_CLI = r"""
$source = @'
public static class FakeCli {
    public static int Main(string[] args) {
        string code = System.Environment.GetEnvironmentVariable("FAKE_CLI_EXIT");
        return string.IsNullOrEmpty(code) ? 0 : int.Parse(code);
    }
}
'@
Add-Type -TypeDefinition $source -OutputAssembly @EXE@ -OutputType ConsoleApplication
"""

# A stand-in for the sync beside claude.cmd, recording the mode it was run in and whether it was told of a sign-in.
LAUNCHER_SYNC_STAND_IN = r"""
param([string]$Mode, [switch]$SignedIn)
[IO.File]::WriteAllText(@CALLS@, $Mode + $(if ($SignedIn) { ' signed-in' } else { '' }))
"""

# -Linger keeps the process for that many seconds once its window has closed, as the real app's processes outlive its
# quit; -Respawn starts another instance as it closes, writing that instance's process id to the file it names. Beside
# the ready file it writes the moment it is told the session ends (.told) and the moment its window loop ends (.ended),
# which a failing run's message carries (SyncHomeTestCase.fake_app_marks).
FAKE_APP = r"""
param([string]$ReadyFile, [switch]$Refuse, [switch]$NoWindow, [int]$Linger, [string]$Respawn)
if ($NoWindow) { [IO.File]::WriteAllText($ReadyFile, 'ready'); Start-Sleep -Seconds 600; return }
Add-Type -AssemblyName System.Windows.Forms
Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition @'
public class FakeDesktopForm : System.Windows.Forms.Form {
    public static bool Refuse;
    public static string ToldMark;
    protected override void WndProc(ref System.Windows.Forms.Message m) {
        if (m.Msg == 0x0011) { m.Result = (System.IntPtr)(Refuse ? 0 : 1); return; }
        if (m.Msg == 0x0016 && m.WParam != System.IntPtr.Zero) {
            System.IO.File.WriteAllText(ToldMark, System.DateTime.UtcNow.ToString("o"));
            System.Windows.Forms.Application.Exit();
            return;
        }
        base.WndProc(ref m);
    }
}
'@
[FakeDesktopForm]::Refuse = [bool]$Refuse
[FakeDesktopForm]::ToldMark = $ReadyFile + '.told'
$form = New-Object FakeDesktopForm
$form.ShowInTaskbar = $false
$form.WindowState = [System.Windows.Forms.FormWindowState]::Minimized
$form.Add_Shown({ [IO.File]::WriteAllText($ReadyFile, 'ready') })
[System.Windows.Forms.Application]::Run($form)
[IO.File]::WriteAllText($ReadyFile + '.ended', [DateTime]::UtcNow.ToString('o'))
if ($Respawn) {
    $again = Start-Process -FilePath ([Diagnostics.Process]::GetCurrentProcess().MainModule.FileName) -PassThru `
        -WindowStyle Hidden -ArgumentList @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        ('"' + $PSCommandPath + '"'), '-ReadyFile', ('"' + $ReadyFile + '.again"'), '-NoWindow')
    [IO.File]::WriteAllText($Respawn, [string]$again.Id)
}
if ($Linger) { Start-Sleep -Seconds $Linger }
"""

# Runs the script beside the package's service: the Get-Process the script calls gains a session-0 process of the app
# folder that never exits. Its id must belong to no live process, or the windows that process owned would be asked to
# close, so the command checks it. A marker file records that the stand-in was handed to the script, so that a test
# cannot pass for want of the script ever asking for the process list the stand-in joins.
BESIDE_SERVICE = r"""
$id = @ID@
if (Microsoft.PowerShell.Management\Get-Process -Id $id -ErrorAction SilentlyContinue) { throw 'the service stand-in id is a live process' }
function Get-Process {
    Microsoft.PowerShell.Management\Get-Process @args
    if ($args.Count -eq 0) {
        [IO.File]::WriteAllText(@LISTED@, 'listed')
        [pscustomobject]@{ Id = $id; ProcessName = 'cowork-svc'; SessionId = 0; Path = @PATH@ }
    }
}
& @COMMAND@
exit $LASTEXITCODE
"""
SERVICE_ID = 2147483644  # beyond any process id Windows hands out


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def in_user_session() -> bool:
    """Whether this process runs in a user's Windows session; services run in session 0."""
    if os.name != "nt":
        return False
    session = ctypes.c_uint32()
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
    return session.value != 0


USER_SESSION = in_user_session()

COOKIES_TOO_LARGE = b"x" * (1024 * 1024 + 1)  # one byte over what the script accepts as a sign-in's cookies

# The note a desktop mode writes while it waits for the app to save a sign-in just made, before it closes the app.
WAITING_NOTE = "Waiting for the desktop app to save its sign-in"
# A -CookieSaveSeconds no run takes to reach the app's log: the sign-in a test logs is still in the window whenever the
# script reads it, however slow the machine, and the wait it begins is ended by the Cookies file's write the test makes.
LONG_SAVE = "150"

# Get-DesktopAppProcess read in isolation: the script dot-sourced, then called against the real process list and
# against a made-up one.
APP_PROCESS_PROBE = r"""
$ErrorActionPreference = 'Stop'
. @SCRIPT@ -DesktopAppDir @APP@ -DesktopConfig @CONFIG@ -ClaudeHome @HOME@
'real=' + @(Get-DesktopAppProcess).Count
function Get-Process {
    [pscustomobject]@{ Id = 11; SessionId = 0; Path = @APP@ + '\app\resources\cowork-svc.exe' }
    [pscustomobject]@{ Id = 12; SessionId = 1; Path = @APP@ + '\app\Claude.exe' }
    [pscustomobject]@{ Id = 13; SessionId = 2; Path = (@APP@).ToUpperInvariant() + '\APP\CLAUDE.EXE' }
    [pscustomobject]@{ Id = 14; SessionId = 1; Path = @APP@ + '-other\app\Claude.exe' }
    [pscustomobject]@{ Id = 15; SessionId = 1; Path = $null }
    [pscustomobject]@{ Id = 16; SessionId = 1; Path = 'C:\elsewhere\claude.exe' }
    $unreadable = [pscustomobject]@{ Id = 17; SessionId = 1 }
    Add-Member -InputObject $unreadable -MemberType ScriptProperty -Name Path -Value { throw 'access denied' }
    $unreadable
}
'ids=' + ((Get-DesktopAppProcess | ForEach-Object { $_.Id }) -join ',')
"""

# Write-FileAtomic read in isolation: the script dot-sourced, then one file written whole while the test holds it open.
# Each pause after a refused move writes @REFUSED@ first, so that the test lets the file go only once a move has been
# refused, however long the machine takes to get there.
ATOMIC_WRITE_PROBE = r"""
$ErrorActionPreference = 'Stop'
. @SCRIPT@ -DesktopAppDir @APP@ -DesktopConfig @CONFIG@ -ClaudeHome @HOME@
function Start-Sleep {
    [IO.File]::WriteAllText(@REFUSED@, 'refused')
    Microsoft.PowerShell.Utility\Start-Sleep @args
}
try { Write-FileAtomic @PATH@ ([Text.Encoding]::UTF8.GetBytes('new')); 'written' }
catch { 'refused: ' + $_.Exception.Message }
"""

# Write-FileSet read in isolation: the script dot-sourced, then a set of three files written - @FIRST@ replaced, @SECOND@
# created, @LAST@ replaced - while the test holds @LAST@ open. With @STICK@ 'yes', the first pause after a refused move
# also opens @FIRST@ as the test holds a file, so that putting it back is refused in turn. Each file's content is
# printed after the write.
FILE_SET_PROBE = r"""
$ErrorActionPreference = 'Stop'
. @SCRIPT@ -DesktopAppDir @APP@ -DesktopConfig @CONFIG@ -ClaudeHome @HOME@
$script:stuck = $null
function Start-Sleep {
    if (@STICK@ -eq 'yes' -and $null -eq $script:stuck) { $script:stuck = [IO.File]::Open(@FIRST@, 'Open', 'Read', 'ReadWrite') }
    Microsoft.PowerShell.Utility\Start-Sleep @args
}
$utf8 = New-Object Text.UTF8Encoding($false)
try {
    Write-FileSet @(
        @{ Path = @FIRST@; Bytes = $utf8.GetBytes('first-new') }
        @{ Path = @SECOND@; Bytes = $utf8.GetBytes('second-new') }
        @{ Path = @LAST@; Bytes = $utf8.GetBytes('last-new') }
    )
    'written'
} catch { 'refused: ' + $_.Exception.Message } finally { if ($script:stuck) { $script:stuck.Dispose() } }
foreach ($path in @FIRST@, @SECOND@, @LAST@) {
    if (Test-Path -LiteralPath $path) { [IO.File]::ReadAllText($path) } else { 'absent' }
}
"""

# One watcher's views in a row, read in isolation: the script dot-sourced, then Update-WatchState called as the watch
# calls it, each view it returns printed, with the app's sign-in mark turned between the looks and config.json held
# against reading for one of them, as the app holds it while it writes it.
WATCH_PROBE = r"""
$ErrorActionPreference = 'Stop'
. @SCRIPT@ -DesktopAppDir @APP@ -DesktopConfig @CONFIG@ -ClaudeHome @HOME@ -CliExe @CLI@
function Set-SignInMark([string]$Value) {
    $text = [IO.File]::ReadAllText(@CONFIG@)
    $marked = $text -replace '"windowSizeWasSignedIn": (true|false)', ('"windowSizeWasSignedIn": ' + $Value)
    [IO.File]::WriteAllText(@CONFIG@, $marked)
}
$view = Update-WatchState $null $null
$view | ConvertTo-Json -Compress
Set-SignInMark 'false'
$view = Update-WatchState $view $null
$view | ConvertTo-Json -Compress
$view = Update-WatchState $view $null
$view | ConvertTo-Json -Compress
$held = [IO.File]::Open(@CONFIG@, 'Open', 'Read', 'None')
try { $view = Update-WatchState $view $null } finally { $held.Dispose() }
$view | ConvertTo-Json -Compress
Set-SignInMark 'true'
$view = Update-WatchState $view $null
$view | ConvertTo-Json -Compress
"""

# One watcher's rounds in a row, read in isolation: the script dot-sourced, then Invoke-WatchRound called as the watch
# calls it, each view it returns printed. The second round looks again at an app that is still not running; the third
# finds the act mutex held by another act, on a thread of its own, as a switch holds it; the fourth looks again once
# the act has let it go.
ROUND_PROBE = r"""
$ErrorActionPreference = 'Stop'
. @SCRIPT@ -DesktopAppDir @APP@ -DesktopConfig @CONFIG@ -ClaudeHome @HOME@ -CliExe @CLI@
$view = Invoke-WatchRound $null
$view | ConvertTo-Json -Compress
Start-Sleep -Milliseconds 50
$view = Invoke-WatchRound $view
$view | ConvertTo-Json -Compress
$holder = [powershell]::Create()
[void]$holder.AddScript({
    param($Name, $Held, $Release)
    $mutex = New-Object Threading.Mutex($false, $Name)
    [void]$mutex.WaitOne()
    [IO.File]::WriteAllText($Held, 'held')
    while (-not (Test-Path -LiteralPath $Release)) { Start-Sleep -Milliseconds 50 }
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}).AddArgument($ActMutexName).AddArgument(@HELD@).AddArgument(@RELEASE@)
$async = $holder.BeginInvoke()
while (-not (Test-Path -LiteralPath @HELD@)) { Start-Sleep -Milliseconds 50 }
Start-Sleep -Milliseconds 50
$view = Invoke-WatchRound $view
$view | ConvertTo-Json -Compress
[IO.File]::WriteAllText(@RELEASE@, 'go')
[void]$holder.EndInvoke($async)
$holder.Dispose()
Start-Sleep -Milliseconds 50
$view = Invoke-WatchRound $view
$view | ConvertTo-Json -Compress
"""

# Two rounds of one watcher, read in isolation, as the watch calls them: the first on the app as the test left it, then
# @BETWEEN@ moves the app to another account — a config written in its place, as a sign-out in the app and a sign-in at
# its sign-in page within one look leave it, or a switch made in the same process — and the second round; the last view
# is printed.
LEFT_PROBE = r"""
$ErrorActionPreference = 'Stop'
. @SCRIPT@ -DesktopAppDir @APP@ -DesktopConfig @CONFIG@ -ClaudeHome @HOME@ -CliExe @CLI@ -DesktopLog @LOG@ -DesktopLauncher @LAUNCHER@ -SignInSeconds 2
$seen = @{}
$view = Invoke-WatchRound $null $seen
@BETWEEN@
$view = Invoke-WatchRound $view $seen
$view | ConvertTo-Json -Compress
"""


def left_sign_in(account: str) -> str:
    """The app's log line as it leaves its sign-in to ``account``, the arrows as the app writes them."""
    return f"[account] Login-state transition (loggedOut: false → true, uuid: {account} → <none>), clearing oauth cache"


def made_sign_in(left: str, account: str) -> str:
    """The app's log line as it signs in to ``account`` at its sign-in page, having last named ``left``."""
    return (f"[account] Login-state transition (loggedOut: true → false, uuid: {left} → {account}), "
            "clearing oauth cache")


# StartDesktop's guard read in isolation: the script dot-sourced with an app folder of its own, without a launcher and
# with one, and the guard's answer printed. Nothing is started: a dot-sourced script runs no mode.
START_GUARD_PROBE = r"""
$ErrorActionPreference = 'Stop'
. @SCRIPT@ -DesktopAppDir @APP@ @LAUNCHER@ -ClaudeHome @HOME@
try { Assert-StartIsolated; 'allowed' } catch { 'refused: ' + $_.Exception.Message }
"""


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "the account sync runs on Windows PowerShell")
class SyncHomeTestCase(unittest.TestCase):
    """A simulated home, a simulated desktop app folder and the means to run the script against them."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synctest-")
        self.home = Path(self.temp.name)
        (self.home / ".claude").mkdir()
        self.desktop_dir = self.home / "desktop"  # stands in for %APPDATA%\Claude
        (self.desktop_dir / "Network").mkdir(parents=True)
        self.desktop_config = self.desktop_dir / "config.json"
        self.cookies = self.desktop_dir / "Network" / "Cookies"
        self.cli = self.home / "no-such-dir" / "claude.exe"
        self.app_dir = self.home / "desktop-app"  # stands in for the install folder; holds no real app
        self.launched = self.home / "launched.txt"
        self.launcher = self.home / "launch-app.cmd"
        self.launcher.write_text(f'@echo off\r\necho launched>>"{self.launched}"\r\n', encoding="ascii")
        self.fake_apps: list[subprocess.Popen] = []

    def tearDown(self):
        for process in self.fake_apps:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=30)
        # Windows can go on holding a program copied into the folder for a moment after its process has ended — seen
        # on the fake app's executable, by a holder not measured. That hold is waited out; one outlasting the bound
        # stays an error.
        deadline = time.monotonic() + RELEASE_WAIT_S
        while True:
            try:
                self.temp.cleanup()
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)

    def sign_in(self, uuid: str, email: str, token: str) -> None:
        """What a CLI sign-in leaves behind: the profile in ~/.claude.json and the credentials file."""
        profile = {"accountUuid": uuid, "emailAddress": email, "organizationUuid": "org-" + uuid[:8]}
        (self.home / ".claude.json").write_text(json.dumps({"numStartups": 3, "oauthAccount": profile}, indent=2),
                                               encoding="utf-8")
        credentials = {"claudeAiOauth": {"accessToken": token, "refreshToken": "refresh-" + token,
                                         "refreshTokenExpiresAt": int((time.time() + 30 * 86400) * 1000)}}
        (self.home / ".claude" / ".credentials.json").write_text(json.dumps(credentials), encoding="utf-8")
        time.sleep(0.05)  # the script tells sign-ins apart by the credentials file's write time

    def run_sync(self, *mode: str, expect: int = 0, app_dir: Path | None = None,
                 cli: Path | None = None, service: bool = False) -> subprocess.CompletedProcess:
        """The script in ``mode``, against the simulated home and desktop, the app folder and the launcher always its
        own; ``expect`` is the exit code it must end with, and a run that ends otherwise says what the fake app marked.
        ``service`` runs it beside a stand-in for the package's Windows service."""
        app_dir = app_dir or self.app_dir
        arguments = [str(SCRIPT), *mode, "-ClaudeHome", str(self.home), "-DesktopConfig", str(self.desktop_config),
                     "-CliExe", str(cli or self.cli), "-DesktopAppDir", str(app_dir),
                     "-DesktopLauncher", str(self.launcher)]
        listed = self.home / "service_listed.txt"
        if service:
            listed.unlink(missing_ok=True)
            wrapper = self.home / "run_beside_service.ps1"
            wrapper.write_text(self.beside_service(arguments, app_dir, listed), encoding="utf-8-sig")
            arguments = [str(wrapper)]
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                 *arguments], capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, expect, result.stderr + self.fake_app_marks())
        if service:
            self.assertTrue(listed.exists(), "the script never read a process list that held the service")
        return result

    def fake_app_marks(self) -> str:
        """What the fake desktop app last started marked, for a failing run's message: when it was told the session
        ends and when its window loop ended, in UTC, or that it marked neither; empty when no fake app was started."""
        app = getattr(self, "fake_desktop_app", None)
        if app is None:
            return ""
        ready = self.home / "app-ready.txt"
        marks = []
        for name, what in (("told", "told the session ends"), ("ended", "its window loop ended")):
            mark = ready.with_name(f"{ready.name}.{name}")
            marks.append(f"{what} {mark.read_text(encoding='ascii').strip()}" if mark.exists() else f"never {what}")
        alive = "still running" if app.poll() is None else "ended"
        return f"\n[fake desktop app, {alive}: {'; '.join(marks)}]"

    def beside_service(self, arguments: list[str], app_dir: Path, listed: Path) -> str:
        """The PowerShell that runs the script with ``arguments`` beside a stand-in for the package's service, which
        writes ``listed`` when the script is handed it."""
        call = " ".join(token if re.fullmatch(r"-[A-Za-z]+", token) else ps_quote(token) for token in arguments)
        return (BESIDE_SERVICE.replace("@ID@", str(SERVICE_ID))
                .replace("@LISTED@", ps_quote(str(listed)))
                .replace("@PATH@", ps_quote(str(app_dir / "app" / "resources" / "cowork-svc.exe")))
                .replace("@COMMAND@", call))

    def events(self) -> list[tuple[str, str]]:
        path = self.home / ".claude" / "accounts" / "events.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for record in records:
            self.assertRegex(record["t"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$")
        return [(r["kind"], r["account"]) for r in records]

    def watch_view(self) -> dict:
        return json.loads((self.home / ".claude" / "accounts" / "watch.json").read_text(encoding="utf-8"))

    def stored(self, uuid: str, name: str) -> Path:
        return self.home / ".claude" / "accounts" / uuid / name

    def desktop_state(self, uuid: str, token: str, cookies: bytes) -> str:
        """What a signed-in desktop app holds: the two login values among others in config.json, and its Cookies
        file. Returns config.json's text."""
        text = ('{\n  "darkMode": "dark",\n'
                '  "windowSizeWasSignedIn": true,\n'
                f'  "oauth:tokenCacheV2": "{token}",\n'
                '  "dxt:allowlistEnabled:0a0a": true,\n'
                f'  "lastKnownAccountUuid": "{uuid}",\n'
                '  "bootSidebarPlaceholder": [1, 2, 3]\n}\n')
        self.desktop_config.write_text(text, encoding="utf-8", newline="")
        self.cookies.write_bytes(cookies)
        return text


class SyncScriptTest(SyncHomeTestCase):
    def test_a_switch_publishes_the_cli_and_desktop_accounts(self):
        self.sign_in(BETA, "beta@example.com", "token-beta")
        self.run_sync("-Mode", "Snapshot")
        self.assertEqual(self.events(), [("cli_account", BETA)])

        self.sign_in(ALPHA, "alpha@example.com", "token-alpha")
        self.desktop_config.write_text(json.dumps({"lastKnownAccountUuid": BETA}), encoding="utf-8")
        self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1")
        # The watcher trusts the new sign-in (alpha), switches the CLI back to the desktop's account (beta), and
        # publishes the desktop account with its first view.
        self.assertEqual(self.events(), [("cli_account", BETA), ("cli_account", ALPHA), ("cli_account", BETA),
                                         ("desktop_account", BETA)])
        view = self.watch_view()
        self.assertEqual((view["desktopAccount"], view["cliAccount"], view["condition"]), (BETA, BETA, None))
        state = json.loads((self.home / ".claude.json").read_text(encoding="utf-8"))
        self.assertEqual((state["oauthAccount"]["accountUuid"], state["numStartups"]), (BETA, 3))

        self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1")
        self.assertEqual(self.events()[-1], ("desktop_account", BETA), "a restarted watcher republishes its view")
        self.assertEqual([e for e in self.events() if e[0] == "cli_account"],
                         [("cli_account", BETA), ("cli_account", ALPHA), ("cli_account", BETA)],
                         "an unchanged CLI account publishes nothing")

    def test_a_desktop_account_with_no_stored_sign_in_is_a_standing_condition(self):
        self.sign_in(ALPHA, "alpha@example.com", "token-alpha")
        self.desktop_config.write_text(json.dumps({"lastKnownAccountUuid": BETA}), encoding="utf-8")
        self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1")
        view = self.watch_view()
        self.assertEqual((view["desktopAccount"], view["cliAccount"]), (BETA, ALPHA))
        self.assertIn("no usable stored sign-in", view["condition"])

    def test_a_record_a_crash_left_in_zero_bytes_is_named_and_stops_the_looks_until_it_is_removed(self):
        self.two_stored_cli_accounts()
        state_path = self.home / ".claude" / "accounts" / "state.json"
        state_path.write_bytes(b"\0" * 300)   # zero bytes, as a crash before the flush leaves the file
        self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1")
        condition = self.watch_view()["condition"]
        self.assertIn(str(state_path), condition)
        self.assertIn("remove it", condition)
        self.assertEqual(self.cli_account(), ALPHA, "nothing is switched while the record cannot be read")
        self.assertIn(str(state_path), self.run_sync("-Mode", "Status").stdout)

        state_path.unlink()
        self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1")
        self.assertIsNone(self.watch_view()["condition"])
        trusted = json.loads(state_path.read_text(encoding="utf-8"))["accountUuid"]
        self.assertEqual((self.cli_account(), trusted), (BETA, BETA), "removed, it is written again")

    def test_a_record_another_program_holds_is_not_called_damaged(self):
        self.two_stored_cli_accounts()
        state_path = self.home / ".claude" / "accounts" / "state.json"
        with open(state_path, "r+b"):   # a writer's handle: the script's read is refused, the file being whole
            status = self.run_sync("-Mode", "Status").stdout
        self.assertIn("CLI account     : unknown (", status)
        self.assertNotIn("remove it", status)

    def test_a_damaged_stored_profile_is_named_and_never_reaches_the_clis_label(self):
        self.two_stored_cli_accounts()
        profile = self.stored(BETA, "oauthAccount.json")
        profile.write_bytes(b"\0" * 120)
        self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1")
        self.assertIn(str(profile), self.watch_view()["condition"])
        self.assertEqual(self.cli_account(), ALPHA, "~/.claude.json is left whole, on the account it was on")

    def cli_account(self) -> str:
        return json.loads((self.home / ".claude.json").read_text(encoding="utf-8"))["oauthAccount"]["accountUuid"]

    def two_stored_cli_accounts(self) -> None:
        """Beta and alpha stored, alpha signed in, the desktop app on beta."""
        self.sign_in(BETA, "beta@example.com", "token-beta")
        self.run_sync("-Mode", "Snapshot")
        self.sign_in(ALPHA, "alpha@example.com", "token-alpha")
        self.run_sync("-Mode", "Snapshot")
        self.desktop_config.write_text(json.dumps({"lastKnownAccountUuid": BETA}), encoding="utf-8")

    def test_the_cli_follows_the_desktop_app_until_that_is_turned_off(self):
        self.two_stored_cli_accounts()
        self.run_sync("-Mode", "Settings", "-Follows", "Off")
        self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1")
        self.assertEqual(self.cli_account(), ALPHA, "with the switch off the watcher leaves the CLI where it is")
        self.assertIsNone(self.watch_view()["condition"], "and has no condition to report")

        self.run_sync("-Mode", "Sync")
        self.assertEqual(self.cli_account(), ALPHA, "the launcher's sync leaves it too")

        self.run_sync("-Mode", "Settings", "-Follows", "On")
        self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1")
        self.assertEqual(self.cli_account(), BETA, "turned on again, the next check aligns the CLI with no prompt")

    def test_the_switches_are_on_until_turned_off_and_are_kept_one_by_one(self):
        path = self.home / ".claude" / "accounts" / "sync-settings.json"
        self.run_sync("-Mode", "Settings", "-OneClick", "Off")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"followsDesktop": True, "oneClickDesktop": False})
        self.run_sync("-Mode", "Settings", "-Follows", "Off")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"followsDesktop": False, "oneClickDesktop": False})
        self.run_sync("-Mode", "Settings", "-OneClick", "On", "-Follows", "On")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"followsDesktop": True, "oneClickDesktop": True})

    def test_a_cli_switch_waits_for_the_follow_switch_to_be_off_and_for_a_stored_sign_in(self):
        self.two_stored_cli_accounts()
        refused = self.run_sync("-Mode", "SwitchCli", "-Account", BETA, expect=2)
        self.assertIn("follows the desktop app", refused.stderr)
        self.assertEqual(self.cli_account(), ALPHA)

        self.run_sync("-Mode", "Settings", "-Follows", "Off")
        self.run_sync("-Mode", "SwitchCli", "-Account", BETA)
        self.assertEqual(self.cli_account(), BETA)
        self.assertEqual(self.events()[-1], ("cli_account", BETA))
        again = self.run_sync("-Mode", "SwitchCli", "-Account", BETA)
        self.assertIn("already signed in", again.stderr)

        stranger = "cccccccc-0000-4000-8000-000000000003"
        unknown = self.run_sync("-Mode", "SwitchCli", "-Account", stranger, expect=3)
        self.assertIn("No usable CLI sign-in", unknown.stderr)
        self.assertEqual(self.cli_account(), BETA)

    def test_a_cli_switch_whose_last_file_is_held_leaves_the_cli_as_it_was_and_says_so(self):
        """The sign-in file, ~/.claude.json and the stored stamp are one set: a hold on the stamp, the last of them,
        outlasting the write's patience puts the two written before it back, the very files they were."""
        self.two_stored_cli_accounts()
        self.run_sync("-Mode", "Settings", "-Follows", "Off")
        credentials = self.home / ".claude" / ".credentials.json"
        state = self.home / ".claude.json"
        stamp = self.stored(BETA, "credentials.stamp")
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (credentials, state, stamp)}
        with open(stamp, "rb"):   # held as a plain reader holds it, sharing reading and writing, not deletion
            refused = self.run_sync("-Mode", "SwitchCli", "-Account", BETA, expect=1)
        self.assertIn(f"{stamp} could not be written", refused.stderr)
        self.assertIn("the 2 files of its set written before it were put back, so the set is as it was", refused.stderr)
        for path, (content, written) in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (content, written), f"{path.name} is as it was")
        self.assertEqual(self.cli_account(), ALPHA)
        self.assertEqual(sorted(p.name for p in self.home.rglob("*.sync-*")), [], "nothing staged or kept is left")

    def test_a_cli_switch_refused_for_a_running_cli_has_an_exit_code_of_its_own(self):
        self.two_stored_cli_accounts()
        self.run_sync("-Mode", "Settings", "-Follows", "Off")
        exe = self.home / "cli" / "claude.exe"
        exe.parent.mkdir()
        shutil.copy2(POWERSHELL, exe)   # a CLI the script finds by its path, as it finds the real one
        self.fake_apps.append(subprocess.Popen(
            [str(exe), "-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 600"],
            creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        refused = self.run_sync("-Mode", "SwitchCli", "-Account", BETA, expect=4, cli=exe)
        self.assertIn("a CLI is still running", refused.stderr)
        self.assertEqual(self.cli_account(), ALPHA, "nothing was changed")

    def test_a_cli_switch_needs_an_account(self):
        self.run_sync("-Mode", "SwitchCli", expect=1)
        self.run_sync("-Mode", "SwitchCli", "-Account", "not-a-uuid", expect=1)

    def test_status_shows_the_switches_the_desktop_logins_and_the_working_sessions(self):
        self.two_stored_cli_accounts()
        for name, status, pid, created in (("fresh", "busy", None, None), ("stale", "busy", os.getppid(), 1),
                                           ("idle", "idle", 2 ** 31 - 1, 1)):
            fixtures.register_session(self.home / ".claude", name, status=status, pid=pid, created=created)
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.run_sync("-Mode", "SnapshotDesktop")
        self.run_sync("-Mode", "Settings", "-OneClick", "Off")
        status = self.run_sync("-Mode", "Status").stdout
        self.assertRegex(status, r"CLI follows app : on")
        self.assertRegex(status, r"One-click switch: off")
        self.assertRegex(status, r"Desktop switch  : available")
        self.assertRegex(status, r"Working sessions: 1\b")
        self.assertRegex(status, rf"{ALPHA}\s+alpha@example\.com\s+usable=True\s+desktop-login=True")
        self.assertRegex(status, rf"{BETA}\s+beta@example\.com\s+usable=True\s+desktop-login=False")


class CliSignInTest(SyncHomeTestCase):
    """Whose sign-in the CLI's file holds. A sign-in writes the label and the sign-in file together; a token refresh,
    or the CLI signing itself out, writes the file alone (``refresh``, ``sign_out``); the desktop app's own Claude Code
    writes the label alone (``relabel``). The tests that need two writes apart shorten the window the script allows a
    sign-in's two writes (``-SignInWindowSeconds``) and wait past it, or date the earlier write back; those that need
    two writes taken for one sign-in keep the script's own window, since a look comes only after a start of Windows
    PowerShell, which load stretches (up to 12 s with every processor kept busy, measured on the development machine,
    2026-11-14) and never shortens. A CLI running is a stand-in at the simulated CLI's path."""

    def relabel(self, uuid: str, email: str) -> None:
        """The desktop app's Claude Code writing the label of the account the app signed in to; the file is left."""
        path = self.home / ".claude.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["oauthAccount"] = {"accountUuid": uuid, "emailAddress": email, "organizationUuid": "org-" + uuid[:8]}
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def write_credentials(self, data: dict) -> None:
        (self.home / ".claude" / ".credentials.json").write_text(json.dumps(data), encoding="utf-8")
        time.sleep(0.05)

    def date_back_sign_in(self) -> None:
        """The CLI's sign-in file as last written an hour ago, outside any window the script allows a sign-in."""
        written = time.time() - 3600
        os.utime(self.home / ".claude" / ".credentials.json", (written, written))

    def refresh(self, token: str) -> None:
        """A token refresh: the sign-in file rewritten with new tokens, the label left."""
        self.write_credentials({"claudeAiOauth": {"accessToken": token, "refreshToken": "refresh-" + token,
                                                  "refreshTokenExpiresAt": int((time.time() + 30 * 86400) * 1000)}})

    def sign_out(self, shape: str) -> None:
        """The CLI's sign-in file once the CLI has signed itself out: its tokens emptied, or its OAuth entry gone."""
        if shape == "emptied":
            self.write_credentials({"claudeAiOauth": {"accessToken": "", "refreshToken": "", "expiresAt": 0}})
        else:
            self.write_credentials({"mcpOAuth": {}})

    def desktop_on(self, uuid: str) -> None:
        self.desktop_config.write_text(json.dumps({"lastKnownAccountUuid": uuid}), encoding="utf-8")

    def watch(self, *extra: str, cli: Path | None = None) -> subprocess.CompletedProcess:
        return self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1", *extra, cli=cli)

    def cli_label(self) -> str:
        return json.loads((self.home / ".claude.json").read_text(encoding="utf-8"))["oauthAccount"]["accountUuid"]

    def live_token(self) -> str | None:
        data = json.loads((self.home / ".claude" / ".credentials.json").read_text(encoding="utf-8"))
        return (data.get("claudeAiOauth") or {}).get("accessToken") or None

    def stored_token(self, uuid: str) -> str | None:
        """The access token of the sign-in stored for an account, unsealed as the script seals it."""
        unseal = self.home / "unseal.ps1"
        unseal.write_text(UNSEAL.replace("@PATH@", ps_quote(str(self.stored(uuid, "credentials.dpapi")))),
                          encoding="utf-8-sig")
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                 str(unseal)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(base64.b64decode(result.stdout.strip()).decode("utf-8"))
        return (data.get("claudeAiOauth") or {}).get("accessToken") or None

    def stored_email(self, uuid: str) -> str:
        return json.loads(self.stored(uuid, "oauthAccount.json").read_text(encoding="utf-8"))["emailAddress"]

    def trusted(self) -> str:
        return json.loads((self.home / ".claude" / "accounts" / "state.json").read_text(encoding="utf-8"))["accountUuid"]

    def start_fake_cli(self) -> tuple[Path, subprocess.Popen]:
        exe = self.home / "cli" / "claude.exe"
        exe.parent.mkdir(exist_ok=True)
        shutil.copy2(POWERSHELL, exe)   # a CLI the script finds by its path, as it finds the real one
        process = subprocess.Popen([str(exe), "-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 600"],
                                   creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        self.fake_apps.append(process)
        return exe, process

    @staticmethod
    def stop(process: subprocess.Popen) -> None:
        process.kill()
        process.wait(timeout=30)

    def beta_restored(self) -> None:
        """Beta and alpha stored, the desktop app on beta, and the CLI put on beta by the watcher's restore."""
        self.sign_in(BETA, "beta@example.com", "token-beta")
        self.run_sync("-Mode", "Snapshot")
        self.sign_in(ALPHA, "alpha@example.com", "token-alpha")
        self.run_sync("-Mode", "Snapshot")
        self.desktop_on(BETA)
        self.watch()
        self.assertEqual((self.cli_label(), self.live_token()), (BETA, "token-beta"))

    def test_a_label_another_program_writes_is_not_taken_for_a_sign_in_and_the_cli_still_follows(self):
        self.beta_restored()
        self.desktop_on(ALPHA)
        self.relabel(ALPHA, "alpha@example.com")
        self.watch()
        self.assertEqual(self.stored_token(BETA), "token-beta", "the file beta's sign-in stayed in is stored as beta's")
        self.assertEqual(self.stored_email(BETA), "beta@example.com", "beside beta's own profile, not the label over it")
        self.assertEqual(self.stored_token(ALPHA), "token-alpha", "alpha's stored sign-in is not touched")
        self.assertEqual((self.cli_label(), self.live_token()), (ALPHA, "token-alpha"), "the CLI follows the app to alpha")
        self.assertIsNone(self.watch_view()["condition"])
        self.assertEqual([e for e in self.events() if e[0] == "cli_account"][-2:],
                         [("cli_account", BETA), ("cli_account", ALPHA)], "the CLI was beta's until the switch")

    def test_a_label_another_program_writes_is_put_back_while_the_cli_does_not_follow(self):
        self.beta_restored()
        self.run_sync("-Mode", "Settings", "-Follows", "Off")
        self.relabel(ALPHA, "alpha@example.com")
        result = self.watch()
        self.assertEqual((self.cli_label(), self.live_token()), (BETA, "token-beta"))
        self.assertIn("Put the CLI's account label back to beta@example.com", result.stderr)
        self.assertEqual(self.trusted(), BETA)
        self.assertIsNone(self.watch_view()["condition"])

    def refreshed_under_another_programs_label(self) -> None:
        """Tokens refreshed under another program's label, in small: the CLI on beta by the watcher's restore; the
        desktop app signs in to gamma, whose CLI sign-in is not stored, and its Claude Code writes gamma's label; a CLI
        started by its path then refreshes beta's tokens under that label."""
        self.beta_restored()
        self.desktop_on(GAMMA)
        self.relabel(GAMMA, "gamma@example.com")
        self.watch("-SignInWindowSeconds", "1")
        self.assertIn("no usable stored sign-in", self.watch_view()["condition"])
        time.sleep(1.5)
        self.refresh("token-beta-2")

    def test_a_refresh_under_another_programs_label_moves_no_trust_and_stores_nothing(self):
        self.refreshed_under_another_programs_label()
        self.watch("-SignInWindowSeconds", "1")
        self.assertIn("written since that label appeared", self.watch_view()["condition"])
        self.assertEqual(self.trusted(), BETA, "trust stays with beta")
        self.assertFalse(self.stored(GAMMA, "credentials.dpapi").exists(), "nothing is filed under gamma")
        self.assertEqual(self.stored_token(BETA), "token-beta", "nor under beta, whose sign-in it may not hold")
        self.assertNotIn(("cli_account", GAMMA), self.events())
        refused = self.run_sync("-Mode", "Sync", "-SignInWindowSeconds", "1", expect=2)
        self.assertIn("run claude auth login", refused.stderr)
        status = self.run_sync("-Mode", "Status", "-SignInWindowSeconds", "1").stdout
        self.assertRegex(status, r"Label trusted   : NO - ")

    def test_a_sign_in_the_launcher_saw_settles_a_label_the_sync_could_not_place(self):
        self.refreshed_under_another_programs_label()
        self.sign_in(GAMMA, "gamma@example.com", "token-gamma")   # claude auth login, as gamma, under gamma's label
        self.run_sync("-Mode", "Snapshot", "-SignInWindowSeconds", "1")
        self.assertFalse(self.stored(GAMMA, "credentials.dpapi").exists(), "a store with no sign-in seen places nothing")
        self.run_sync("-Mode", "Snapshot", "-SignedIn")
        self.assertEqual(self.stored_token(GAMMA), "token-gamma")
        self.assertEqual(self.stored_email(GAMMA), "gamma@example.com")
        self.assertEqual(self.trusted(), GAMMA)
        self.assertEqual(self.events()[-1], ("cli_account", GAMMA))

    def test_a_sign_in_that_writes_its_file_before_its_label_is_trusted(self):
        self.sign_in(BETA, "beta@example.com", "token-beta")
        self.run_sync("-Mode", "Snapshot")
        self.desktop_on(BETA)
        exe, cli = self.start_fake_cli()
        self.refresh("token-alpha")             # the sign-in's first write, with a look before its second
        self.watch(cli=exe)
        self.relabel(ALPHA, "alpha@example.com")
        self.stop(cli)
        self.watch(cli=exe)
        self.assertEqual((self.stored_token(ALPHA), self.stored_email(ALPHA)), ("token-alpha", "alpha@example.com"))
        self.assertEqual(self.stored_token(BETA), "token-beta", "beta's stored sign-in never took alpha's tokens")
        self.assertIn(("cli_account", ALPHA), self.events())
        self.assertEqual((self.cli_label(), self.live_token()), (BETA, "token-beta"), "and the CLI follows the app back")

    def test_a_sign_in_that_writes_its_label_before_its_file_is_trusted(self):
        self.sign_in(BETA, "beta@example.com", "token-beta")
        self.date_back_sign_in()                   # beta's file is no part of the sign-in to come
        self.run_sync("-Mode", "Snapshot")
        self.desktop_on(BETA)
        exe, cli = self.start_fake_cli()
        self.watch(cli=exe)
        self.relabel(ALPHA, "alpha@example.com")   # the sign-in's first write, with a look before its second
        self.watch(cli=exe)
        self.assertEqual(self.trusted(), BETA, "a label beside beta's old file is no sign-in yet")
        self.refresh("token-alpha")
        self.stop(cli)
        self.watch(cli=exe)
        self.assertEqual((self.stored_token(ALPHA), self.stored_email(ALPHA)), ("token-alpha", "alpha@example.com"))
        self.assertEqual(self.stored_token(BETA), "token-beta")
        self.assertIn(("cli_account", ALPHA), self.events())
        self.assertEqual((self.cli_label(), self.live_token()), (BETA, "token-beta"))

    def test_a_cli_signed_out_of_the_desktop_apps_account_is_never_stored_and_is_said(self):
        self.beta_restored()
        for shape in ("emptied", "dropped"):
            with self.subTest(shape=shape):
                self.sign_out(shape)
                self.watch()
                view = self.watch_view()
                self.assertIn("The CLI is signed out of beta@example.com", view["condition"])
                self.assertEqual(view["cliAccount"], BETA)
                self.assertEqual(self.stored_token(BETA), "token-beta", "the account's last good sign-in stays")
                self.assertIsNone(self.live_token(), "and is not put back: it may be the one that ended")
                launch = self.run_sync("-Mode", "Sync")
                self.assertIn("signed out of beta@example.com", launch.stderr)
                self.run_sync("-Mode", "Snapshot")
                self.assertEqual(self.stored_token(BETA), "token-beta")
                self.assertIn("(signed out: its sign-in has ended)", self.run_sync("-Mode", "Status").stdout)

    def test_a_signed_out_cli_follows_the_desktop_app_to_another_account(self):
        self.beta_restored()
        self.sign_out("emptied")
        self.desktop_on(ALPHA)
        self.watch()
        self.assertEqual((self.cli_label(), self.live_token()), (ALPHA, "token-alpha"))
        self.assertEqual(self.stored_token(BETA), "token-beta")
        self.assertIsNone(self.watch_view()["condition"])

    def test_a_signed_out_cli_is_not_said_while_it_does_not_follow_the_app(self):
        self.beta_restored()
        self.run_sync("-Mode", "Settings", "-Follows", "Off")
        self.sign_out("emptied")
        self.watch()
        self.assertIsNone(self.watch_view()["condition"], "the condition is what keeps the CLI from following")
        self.assertEqual(self.stored_token(BETA), "token-beta")
        self.assertIsNone(self.live_token())

    def test_a_cli_switch_to_the_account_the_cli_signed_out_of_asks_for_a_sign_in(self):
        self.beta_restored()
        self.run_sync("-Mode", "Settings", "-Follows", "Off")
        self.sign_out("emptied")
        refused = self.run_sync("-Mode", "SwitchCli", "-Account", BETA, expect=3)
        self.assertIn("The CLI is signed out of beta@example.com", refused.stderr)
        self.assertIsNone(self.live_token(), "beta's stored sign-in, perhaps the one that ended, is not put back")
        self.run_sync("-Mode", "SwitchCli", "-Account", ALPHA)
        self.assertEqual((self.cli_label(), self.live_token()), (ALPHA, "token-alpha"), "another account's is")

    def test_a_store_from_before_the_looks_were_recorded_takes_no_foreign_label_on_a_changed_file(self):
        self.sign_in(BETA, "beta@example.com", "token-beta")
        self.run_sync("-Mode", "Snapshot")
        state_path = self.home / ".claude" / "accounts" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state_path.write_text(json.dumps({key: state[key] for key in ("accountUuid", "credentialsStamp")}),
                              encoding="utf-8")   # the two keys an older sync wrote
        self.refresh("token-beta-2")
        self.relabel(ALPHA, "alpha@example.com")
        self.run_sync("-Mode", "Snapshot")
        self.assertFalse(self.stored(ALPHA, "credentials.dpapi").exists(), "a refresh and another program's label "
                         "with no look between them are not taken for a sign-in")
        self.assertEqual(self.trusted(), BETA)

    def test_a_sign_in_file_that_is_not_a_json_object_is_a_layout_the_sync_does_not_know(self):
        self.beta_restored()
        (self.home / ".claude" / ".credentials.json").write_text('"a bare string"', encoding="utf-8")
        self.watch()
        self.assertIn("is not a JSON object", self.watch_view()["condition"])
        self.assertEqual(self.stored_token(BETA), "token-beta")
        self.assertIn("CLI account     : unknown (", self.run_sync("-Mode", "Status").stdout)

    def test_the_launcher_says_a_sign_in_happened_only_after_a_claude_auth_login_that_succeeded(self):
        """claude.cmd itself, beside a stand-in for the sync that records how it was called and a stand-in CLI that
        ends with the exit code it is given, under a home of the test's own."""
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        shutil.copy2(fixtures.TOOL_ROOT / "sync" / "claude.cmd", bin_dir / "claude.cmd")
        calls = self.home / "sync-calls.txt"
        (bin_dir / "WindowTallySync.ps1").write_text(LAUNCHER_SYNC_STAND_IN.replace("@CALLS@", ps_quote(str(calls))),
                                                     encoding="utf-8-sig")
        cli = self.home / ".local" / "bin" / "claude.exe"
        cli.parent.mkdir(parents=True)
        builder = self.home / "build_fake_cli.ps1"
        builder.write_text(BUILD_FAKE_CLI.replace("@EXE@", ps_quote(str(cli))), encoding="utf-8-sig")
        build = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                str(builder)], capture_output=True, text=True, timeout=120)
        self.assertEqual(build.returncode, 0, build.stderr)
        for args, code, expected in ((["auth", "login"], "0", "Snapshot signed-in"),
                                     (["auth", "login"], "1", "Snapshot"),
                                     (["auth", "status"], "0", "Snapshot"),
                                     (["AUTH", "LOGIN"], "0", "Snapshot signed-in")):
            with self.subTest(args=args, code=code):
                calls.unlink(missing_ok=True)
                env = dict(os.environ, USERPROFILE=str(self.home), FAKE_CLI_EXIT=code)
                result = subprocess.run(["cmd.exe", "/d", "/c", str(bin_dir / "claude.cmd"), *args], env=env,
                                        capture_output=True, text=True, timeout=120,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode, int(code), "the launcher ends as the CLI did")
                self.assertEqual(calls.read_text(encoding="utf-8").strip(), expected)


class DesktopSwitchTest(SyncHomeTestCase):
    def store_beta_then_sign_in_to_alpha(self) -> tuple[str, str]:
        """Beta's desktop login stored; the desktop app now signed in to alpha. Returns both config texts."""
        beta = self.desktop_state(BETA, "token-b", b"cookies-b")
        self.run_sync("-Mode", "SnapshotDesktop")
        alpha = self.desktop_state(ALPHA, "token-a", b"cookies-a")
        return alpha, beta

    def start_fake_app(self, *flags: str) -> subprocess.Popen:
        if not USER_SESSION:
            self.skipTest("the script looks for the app's processes outside session 0, where this run is")
        exe = self.app_dir / "app" / "Claude.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(POWERSHELL, exe)
        script = self.home / "fake_desktop_app.ps1"
        script.write_text(FAKE_APP, encoding="ascii")
        ready = self.home / "app-ready.txt"
        for left in (ready, ready.with_name(ready.name + ".told"), ready.with_name(ready.name + ".ended")):
            left.unlink(missing_ok=True)   # an earlier app's, or a second start would not wait for its own
        process = subprocess.Popen([str(exe), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                    str(script), "-ReadyFile", str(ready), *flags],
                                   creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        self.fake_apps.append(process)
        self.fake_desktop_app = process
        deadline = time.time() + 90
        while not ready.exists():
            self.assertIsNone(process.poll(), "the fake app exited before it was ready")
            self.assertLess(time.time(), deadline, "the fake app did not start")
            time.sleep(0.2)
        return process

    def test_a_switch_exchanges_the_logins_and_leaves_the_rest_of_the_config_as_it_was(self):
        alpha, beta = self.store_beta_then_sign_in_to_alpha()
        (self.desktop_dir / "Network" / "Cookies-journal").write_bytes(b"journal of the old cookies")
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA)

        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), beta,
                         "only the two login values changed, every other byte stands")
        self.assertEqual(self.cookies.read_bytes(), b"cookies-b")
        self.assertFalse((self.desktop_dir / "Network" / "Cookies-journal").exists(), "a stale journal is removed")
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file(), "the login it left is stored")
        self.assertEqual(self.events()[-1], ("desktop_account", BETA))
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"],
                         "an app that was not running is started on the account switched to")
        self.assertIn("Starting the desktop app on", result.stderr)

        back = self.run_sync("-Mode", "SwitchDesktop", "-Account", ALPHA)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha, "and back again, byte for byte")
        self.assertEqual(self.cookies.read_bytes(), b"cookies-a")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched", "launched"],
                         "each switch starts the app once")
        said = (self.home / ".claude" / "accounts" / "sync.log").read_text(encoding="utf-8") + result.stderr + back.stderr
        for secret in ("token-a", "token-b", "cookies-a", "cookies-b"):
            self.assertNotIn(secret, said, "no sign-in value is ever written to the log or said")

    def test_a_switch_whose_config_is_held_leaves_the_apps_files_as_they_were_and_says_so(self):
        """The journal, the Cookies file and config.json are one set: a hold on config.json, the last of them,
        outlasting the write's patience puts the journal and the Cookies file back, the very files they were, and the
        previous login put back after it meets the same hold and changes nothing either."""
        alpha, _ = self.store_beta_then_sign_in_to_alpha()
        journal = self.desktop_dir / "Network" / "Cookies-journal"
        journal.write_bytes(b"journal of the old cookies")
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (journal, self.cookies, self.desktop_config)}
        with open(self.desktop_config, "rb"):   # held as a plain reader holds it, sharing reading and writing
            refused = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, expect=1)
        self.assertIn(f"Restoring the desktop login of {BETA} failed ({self.desktop_config} could not be written",
                      refused.stderr)
        self.assertIn("the 2 files of its set written before it were put back, so the set is as it was", refused.stderr)
        self.assertIn("Putting the previous desktop login back failed too", refused.stderr)
        for path, (content, written) in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (content, written), f"{path.name} is as it was")
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)
        events = self.home / ".claude" / "accounts" / "events.jsonl"
        self.assertFalse(events.exists() and ("desktop_account", BETA) in self.events(), "no switch is recorded")
        self.assertFalse(self.launched.exists(), "an app that was not running is not started by a switch that failed")
        self.assertEqual(sorted(p.name for p in self.desktop_dir.rglob("*.sync-*")), [], "nothing staged or kept is left")

    def app_log_writer(self, *lines: str, fresh: bool = False, absent: bool = False,
                       rotate_after: int | None = None) -> Path:
        """A stand-in app log, and a launcher that writes ``lines`` to it as the app does when it starts. The log
        holds an earlier run's sign-out, which a switch must not take for its own, unless ``absent``: no log yet, only
        its folder. ``fresh`` replaces the log in place with the lines; ``rotate_after`` renames it after that many
        lines, as the app's rotation does, the rest going to a new log. Returns the log."""
        log = self.home / "app-logs" / "main.log"
        log.parent.mkdir(exist_ok=True)
        if not absent:
            log.write_text("2026-03-14 09:12:05 [info] [account] Navigated to /logout, synthesizing logged-out\n" * 40,
                           encoding="utf-8")
        writes = ""
        for i, line in enumerate(lines):
            if rotate_after is not None and i == rotate_after:
                writes += f'move /y "{log}" "{log.with_name("main1.log")}" >nul\r\n'
            writes += f'echo 2026-03-14 09:24:27 [info] {line}{">" if fresh and i == 0 else ">>"}"{log}"\r\n'
        self.launcher.write_text(f'@echo off\r\necho launched>>"{self.launched}"\r\n{writes}', encoding="ascii")
        return log

    def test_a_switch_the_app_signs_in_with_is_done(self):
        self.store_beta_then_sign_in_to_alpha()
        log = self.app_log_writer("[oauth-v2] using cached token", "claude.ai account active and logged in")
        self.start_fake_app()
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log))
        self.assertIn("watching it sign in", result.stderr)
        self.assertTrue(result.stderr.rstrip().endswith(f"Switched the desktop app to {BETA}."), result.stderr)
        self.assertTrue(self.stored(BETA, "desktop-login.dpapi").is_file(), "the login it was given stays stored")

    def test_a_login_the_app_refuses_ends_the_switch_signed_out_and_is_set_aside(self):
        _, beta = self.store_beta_then_sign_in_to_alpha()
        log = self.app_log_writer("claude.ai account active and logged in",
                                  "[account] Navigated to /logout, synthesizing logged-out")
        self.start_fake_app()
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log), expect=5)
        self.assertIn("refused the login stored for it", result.stderr)
        self.assertIn("It is set aside.", result.stderr)
        self.assertFalse(self.stored(BETA, "desktop-login.dpapi").exists(), "the account counts as having none")
        self.assertTrue(self.stored(BETA, "desktop-login.refused.dpapi").is_file())
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file(), "the login it left is stored")
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), beta, "the app is on the account it was given")
        self.assertEqual(self.events()[-1], ("desktop_signed_out", BETA), "and at its sign-in page, signed out of it")
        self.assertRegex(self.run_sync("-Mode", "Status").stdout, rf"{BETA}\s+\S+\s+usable=\w+\s+desktop-login=False")

        self.desktop_state(BETA, "token-b2", b"cookies-b2")   # signed in again in the app
        self.run_sync("-Mode", "SnapshotDesktop")
        self.assertTrue(self.stored(BETA, "desktop-login.dpapi").is_file())
        self.assertFalse(self.stored(BETA, "desktop-login.refused.dpapi").exists(), "a fresh store clears the refused one")

    def test_a_sign_out_in_a_log_replaced_in_place_is_read_from_its_start(self):
        self.store_beta_then_sign_in_to_alpha()
        log = self.app_log_writer("[account] Navigated to /logout, synthesizing logged-out", fresh=True)
        self.start_fake_app()
        self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log), expect=5)

    def test_a_sign_out_written_just_before_the_log_is_rotated_is_still_read(self):
        self.store_beta_then_sign_in_to_alpha()
        log = self.app_log_writer("claude.ai account active and logged in",
                                  "[account] User is logged out, skipping account ID wait",
                                  "[info] the first line of the new log", rotate_after=2)
        self.start_fake_app()
        self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log), expect=5)
        self.assertTrue(log.with_name("main1.log").is_file(), "the log was rotated while the switch read it")

    def test_a_log_the_app_writes_only_once_started_is_read(self):
        self.store_beta_then_sign_in_to_alpha()
        log = self.app_log_writer("claude.ai account active and logged in",
                                  "[account] User logged out during IPC wait, stopping early", absent=True)
        self.start_fake_app()
        self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log), expect=5)

    def test_an_app_whose_log_says_nothing_is_switched_unconfirmed(self):
        self.store_beta_then_sign_in_to_alpha()
        log = self.app_log_writer()
        self.start_fake_app()
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log), "-SignInSeconds", "2")
        self.assertIn("could not be confirmed (the desktop app's log said nothing of its sign-in within 2 seconds)",
                      result.stderr)
        self.assertTrue(self.stored(BETA, "desktop-login.dpapi").is_file())

    def test_a_simulated_desktop_never_reads_the_real_apps_log(self):
        self.store_beta_then_sign_in_to_alpha()
        self.start_fake_app()
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA)
        self.assertIn("could not be confirmed (no log of the simulated desktop app was given)", result.stderr)

        self.start_fake_app()
        nowhere = self.home / "no-log-folder" / "main.log"
        back = self.run_sync("-Mode", "SwitchDesktop", "-Account", ALPHA, "-DesktopLog", str(nowhere))
        self.assertIn(f"could not be confirmed (no log folder of the desktop app at {nowhere.parent})", back.stderr)

    def test_a_running_app_is_asked_to_close_then_started_again_on_the_other_account(self):
        _, beta = self.store_beta_then_sign_in_to_alpha()
        app = self.start_fake_app()
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA)
        self.assertIsNotNone(app.poll(), "the app closed itself when the session was said to end")
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), beta)
        self.assertEqual(self.cookies.read_bytes(), b"cookies-b")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"], "and was started once")
        self.assertIn("Closing the desktop app", result.stderr)

    def test_an_app_that_refuses_to_close_is_left_running_and_nothing_is_changed(self):
        alpha, _ = self.store_beta_then_sign_in_to_alpha()
        app = self.start_fake_app("-Refuse")
        refused = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, expect=2)
        self.assertIn("refused to close", refused.stderr)
        self.assertIsNone(app.poll(), "it is never closed by force")
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)
        self.assertEqual(self.cookies.read_bytes(), b"cookies-a")
        self.assertFalse(self.stored(ALPHA, "desktop-login.dpapi").exists())
        self.assertFalse(self.launched.exists())

    def test_an_app_that_does_not_close_in_time_is_left_running_and_nothing_is_changed(self):
        alpha, _ = self.store_beta_then_sign_in_to_alpha()
        app = self.start_fake_app("-NoWindow")
        refused = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, expect=2)
        self.assertIn("Refused", refused.stderr)
        self.assertIsNone(app.poll())
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)
        self.assertFalse(self.stored(ALPHA, "desktop-login.dpapi").exists())

    def test_a_restore_that_fails_puts_the_previous_login_back_and_starts_the_app_again(self):
        alpha, _ = self.store_beta_then_sign_in_to_alpha()
        self.stored(BETA, "desktop-login.dpapi").write_bytes(b"not a sealed login")
        app = self.start_fake_app()
        failed = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, expect=1)
        self.assertIn("putting the previous one back", failed.stderr)
        self.assertIsNotNone(app.poll(), "the app had been closed for the switch")
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)
        self.assertEqual(self.cookies.read_bytes(), b"cookies-a")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"], "and it is started again")

    def test_an_account_with_no_stored_desktop_login_is_not_switched_to(self):
        alpha = self.desktop_state(ALPHA, "token-a", b"cookies-a")
        refused = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, expect=3)
        self.assertIn("No desktop login is stored", refused.stderr)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)
        self.assertEqual(self.cookies.read_bytes(), b"cookies-a")
        self.assertFalse(self.stored(ALPHA, "desktop-login.dpapi").exists(), "nothing was stored either")

    def test_a_switch_to_the_account_in_use_changes_nothing(self):
        alpha = self.desktop_state(ALPHA, "token-a", b"cookies-a")
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", ALPHA)
        self.assertIn("already signed in", result.stderr)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)

    def test_the_apps_own_multi_account_support_refuses_every_desktop_mode(self):
        alpha, _ = self.store_beta_then_sign_in_to_alpha()
        (self.desktop_dir / "fcache").write_text('{"gates":{"96101707":{"value":true}}}', encoding="utf-8")
        for mode in (("-Mode", "SwitchDesktop", "-Account", BETA), ("-Mode", "SnapshotDesktop")):
            refused = self.run_sync(*mode, expect=2)
            self.assertIn("multi-account", refused.stderr)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)
        self.assertIn("refused", self.run_sync("-Mode", "Status").stdout)

    def test_a_layout_the_script_does_not_know_refuses_the_switch(self):
        self.store_beta_then_sign_in_to_alpha()
        broken = {
            "no token cache": '{"lastKnownAccountUuid": "%s"}' % ALPHA,
            "a token cache twice": '{"oauth:tokenCacheV2": "a", "x": {"oauth:tokenCacheV2": "b"}, "lastKnownAccountUuid": "%s"}' % ALPHA,
            "a token cache that is not a string": '{"oauth:tokenCacheV2": {"a": 1}, "lastKnownAccountUuid": "%s"}' % ALPHA,
            "an account that is not a uuid": '{"oauth:tokenCacheV2": "a", "lastKnownAccountUuid": "someone"}',
        }
        for what, text in broken.items():
            self.desktop_config.write_text(text, encoding="utf-8")
            refused = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, expect=2)
            self.assertIn("not laid out", refused.stderr, what)
            self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), text, what)
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.cookies.unlink()
        refused = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, expect=2)
        self.assertIn("no Network\\Cookies file", refused.stderr)

    def test_a_script_that_runs_inside_the_app_does_not_close_it(self):
        alpha, _ = self.store_beta_then_sign_in_to_alpha()
        inside = Path(sys.executable).parent  # an ancestor of the script runs from here, as the app's terminals do
        refused = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, expect=2, app_dir=inside)
        self.assertIn("inside the desktop app", refused.stderr)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)

    def test_a_simulated_desktop_must_come_with_an_app_folder_of_its_own(self):
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                 str(SCRIPT), "-Mode", "SwitchDesktop", "-Account", BETA, "-ClaudeHome", str(self.home),
                                 "-DesktopConfig", str(self.desktop_config), "-CliExe", str(self.cli)],
                                capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("-DesktopAppDir of its own", result.stderr)

    def test_snapshot_stores_the_login_in_use_and_starts_a_running_app_again(self):
        alpha = self.desktop_state(ALPHA, "token-a", b"cookies-a")
        app = self.start_fake_app()
        self.run_sync("-Mode", "SnapshotDesktop")
        self.assertIsNotNone(app.poll())
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file())
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha, "the login itself is untouched")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"])
        self.assertFalse((self.home / ".claude" / "accounts" / "events.jsonl").exists(), "no account changed")

    def test_the_packages_service_does_not_keep_a_running_app_from_closing(self):
        _, beta = self.store_beta_then_sign_in_to_alpha()
        app = self.start_fake_app()
        self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, service=True)
        self.assertIsNotNone(app.poll(), "the app closed itself when the session was said to end")
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), beta)
        self.assertEqual(self.cookies.read_bytes(), b"cookies-b")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"], "and was started once")

    def test_an_app_that_is_closed_is_switched_though_the_packages_service_runs(self):
        _, beta = self.store_beta_then_sign_in_to_alpha()
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, service=True)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), beta)
        self.assertEqual(self.cookies.read_bytes(), b"cookies-b")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"],
                         "an app that was not running is started on the account switched to")
        self.assertIn("Starting the desktop app on", result.stderr)

    def test_snapshot_stores_the_login_though_the_packages_service_runs(self):
        alpha = self.desktop_state(ALPHA, "token-a", b"cookies-a")
        app = self.start_fake_app()
        self.run_sync("-Mode", "SnapshotDesktop", service=True)
        self.assertIsNotNone(app.poll())
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file())
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha, "the login itself is untouched")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"])

    def test_a_login_that_cannot_be_stored_starts_the_closed_app_again(self):
        self.store_beta_then_sign_in_to_alpha()
        alpha = self.desktop_state(ALPHA, "token-a", COOKIES_TOO_LARGE)
        app = self.start_fake_app()
        failed = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, expect=1)
        self.assertIsNotNone(app.poll(), "the app had been closed for the switch")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"], "and it is started again")
        self.assertIn("Storing the desktop login failed", failed.stderr)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha, "the app's login is as it was")
        self.assertEqual(self.cookies.read_bytes(), COOKIES_TOO_LARGE)
        self.assertFalse(self.stored(ALPHA, "desktop-login.dpapi").exists())

    def test_a_snapshot_that_cannot_store_starts_the_closed_app_again(self):
        alpha = self.desktop_state(ALPHA, "token-a", COOKIES_TOO_LARGE)
        app = self.start_fake_app()
        failed = self.run_sync("-Mode", "SnapshotDesktop", expect=1)
        self.assertIsNotNone(app.poll(), "the app had been closed for the store")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"], "and it is started again")
        self.assertIn("Storing the desktop login failed", failed.stderr)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)
        self.assertFalse(self.stored(ALPHA, "desktop-login.dpapi").exists())

    # --- an app at its sign-in page: no store files it as a login, and adding an account leaves the app there -------

    def signed_out(self) -> str:
        """The desktop app as a sign-out in it leaves it: both login values still there, naming the account signed out
        of, and the sign-in mark false. Returns config.json's text."""
        text = self.desktop_config.read_text(encoding="utf-8")
        marked = text.replace('"windowSizeWasSignedIn": true', '"windowSizeWasSignedIn": false')
        self.assertNotEqual(marked, text, "the config was signed in to begin with")
        self.desktop_config.write_text(marked, encoding="utf-8", newline="")
        return marked

    def test_a_switch_away_from_an_app_at_its_sign_in_page_stores_nothing_for_the_account_it_leaves(self):
        _, beta = self.store_beta_then_sign_in_to_alpha()
        self.run_sync("-Mode", "SnapshotDesktop")
        good = self.stored(ALPHA, "desktop-login.dpapi").read_bytes()
        refused = self.stored(ALPHA, "desktop-login.refused.dpapi")
        refused.write_bytes(b"a login the app refused")
        self.desktop_state(ALPHA, "token-a-ended", b"cookies-a-ended")
        self.signed_out()
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA)
        self.assertIn("at its sign-in page, so it holds no login", result.stderr)
        self.assertEqual(self.stored(ALPHA, "desktop-login.dpapi").read_bytes(), good, "the good login stays stored")
        self.assertTrue(refused.is_file(), "and the refused one stays set aside")
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), beta,
                         "the login put back is marked signed in, every other byte as it was")
        self.assertEqual(self.cookies.read_bytes(), b"cookies-b")

    def test_a_store_of_an_app_at_its_sign_in_page_is_refused_with_the_app_left_running(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.run_sync("-Mode", "SnapshotDesktop")
        good = self.stored(ALPHA, "desktop-login.dpapi").read_bytes()
        self.desktop_state(ALPHA, "token-a-ended", b"cookies-a-ended")
        self.signed_out()
        app = self.start_fake_app()
        refused = self.run_sync("-Mode", "SnapshotDesktop", expect=2)
        self.assertIn("at its sign-in page, so it holds no login to store", refused.stderr)
        self.assertIsNone(app.poll(), "the app is not closed for nothing")
        self.assertEqual(self.stored(ALPHA, "desktop-login.dpapi").read_bytes(), good)
        self.assertFalse(self.launched.exists())

    def test_a_switch_to_the_account_an_app_at_its_sign_in_page_still_names_puts_its_login_back(self):
        alpha = self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.run_sync("-Mode", "SnapshotDesktop")
        self.desktop_state(ALPHA, "token-a-ended", b"cookies-a-ended")
        self.signed_out()
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", ALPHA)
        self.assertNotIn("already signed in", result.stderr)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)
        self.assertEqual(self.cookies.read_bytes(), b"cookies-a")
        self.assertEqual(self.events()[-1], ("desktop_account", ALPHA))

    def test_a_restore_that_fails_after_an_app_at_its_sign_in_page_puts_back_what_was_there(self):
        self.store_beta_then_sign_in_to_alpha()
        self.stored(BETA, "desktop-login.dpapi").write_bytes(b"not a sealed login")
        self.desktop_state(ALPHA, "token-a-ended", b"cookies-a-ended")
        marked = self.signed_out()
        journal = self.desktop_dir / "Network" / "Cookies-journal"
        journal.write_bytes(b"journal of the ended cookies")
        app = self.start_fake_app()
        failed = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, expect=1)
        self.assertIn("putting the previous one back", failed.stderr)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), marked)
        self.assertEqual(self.cookies.read_bytes(), b"cookies-a-ended")
        self.assertEqual(journal.read_bytes(), b"journal of the ended cookies", "the journal is put back too")
        self.assertIsNotNone(app.poll(), "the app had been closed for the switch")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"], "and it is started again")
        self.assertFalse(self.stored(ALPHA, "desktop-login.dpapi").exists(), "nothing was stored for the account left")

    def test_status_says_whether_the_app_is_signed_in(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.assertRegex(self.run_sync("-Mode", "Status").stdout, r"Desktop sign-in : signed in")
        self.signed_out()
        self.assertRegex(self.run_sync("-Mode", "Status").stdout, r"Desktop sign-in : at its sign-in page")

    def test_a_config_without_the_sign_in_mark_refuses_every_desktop_mode(self):
        self.store_beta_then_sign_in_to_alpha()
        alpha = self.desktop_config.read_text(encoding="utf-8")
        broken = {"no sign-in mark": alpha.replace('  "windowSizeWasSignedIn": true,\n', ""),
                  "a sign-in mark that is not a boolean": alpha.replace('"windowSizeWasSignedIn": true',
                                                                        '"windowSizeWasSignedIn": "yes"')}
        for what, text in broken.items():
            self.assertNotEqual(text, alpha, what)
            self.desktop_config.write_text(text, encoding="utf-8", newline="")
            for mode in (("-Mode", "SwitchDesktop", "-Account", BETA), ("-Mode", "SnapshotDesktop"),
                         ("-Mode", "AddDesktop")):
                refused = self.run_sync(*mode, expect=2)
                self.assertIn("not laid out", refused.stderr, what)
                self.assertIn("windowSizeWasSignedIn", refused.stderr, what)
            self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), text, what)
            self.assertEqual(self.cookies.read_bytes(), b"cookies-a", what)
        self.assertFalse(self.stored(ALPHA, "desktop-login.dpapi").exists())

    def test_adding_an_account_stores_the_login_and_leaves_the_app_at_its_sign_in_page(self):
        alpha = self.desktop_state(ALPHA, "token-a", b"cookies-a")
        journal = self.desktop_dir / "Network" / "Cookies-journal"
        journal.write_bytes(b"journal of the cookies")
        log = self.app_log_writer("claude.ai account active and logged in",
                                  "[account] User logged out during IPC wait, stopping early")
        app = self.start_fake_app()
        result = self.run_sync("-Mode", "AddDesktop", "-DesktopLog", str(log))
        self.assertIsNotNone(app.poll(), "the app was closed for it")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"], "and started once")
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file(), "the login it held is stored")
        self.assertFalse(self.cookies.exists(), "the file that holds the sign-in cookie is gone")
        self.assertFalse(journal.exists())
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"),
                         alpha.replace('"windowSizeWasSignedIn": true', '"windowSizeWasSignedIn": false'),
                         "the config is marked signed out, every other byte as it was")
        self.assertIn("The desktop app is at its sign-in page.", result.stderr)
        self.assertIn("is stored and still good", result.stderr)
        self.assertEqual(self.events(), [("desktop_signed_out", ALPHA)],
                         "no account changed: the app is recorded at its sign-in page, signed out of alpha")

        # Signed in to beta at the sign-in page, then switched back: the login stored for alpha is put back.
        self.desktop_state(BETA, "token-b", b"cookies-b")
        self.run_sync("-Mode", "SwitchDesktop", "-Account", ALPHA)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)
        self.assertEqual(self.cookies.read_bytes(), b"cookies-a")
        self.assertTrue(self.stored(BETA, "desktop-login.dpapi").is_file(), "the login added is stored as it is left")

    def test_adding_an_account_starts_an_app_that_was_not_running(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        log = self.app_log_writer("claude.ai account active and logged in", "[account] User is logged out")
        result = self.run_sync("-Mode", "AddDesktop", "-DesktopLog", str(log))
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"], "its sign-in page is the point")
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file())
        self.assertFalse(self.cookies.exists())
        self.assertIn("The desktop app is at its sign-in page.", result.stderr)

    def test_an_add_the_apps_log_says_nothing_of_is_unconfirmed(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        log = self.app_log_writer()
        result = self.run_sync("-Mode", "AddDesktop", "-DesktopLog", str(log), "-SignInSeconds", "2")
        self.assertIn("whether it got there could not be confirmed (the desktop app's log said nothing of its sign-in "
                      "within 2 seconds)", result.stderr)
        self.assertFalse(self.cookies.exists())

    def test_an_app_that_comes_up_signed_in_after_the_add_is_an_error(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        log = self.app_log_writer("[oauth-v2] using cached token", "claude.ai account active and logged in")
        self.start_fake_app()
        failed = self.run_sync("-Mode", "AddDesktop", "-DesktopLog", str(log), expect=1)
        self.assertIn("came up signed in, so it could not be left at its sign-in page", failed.stderr)
        self.assertIn("is stored and still good", failed.stderr)
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file())

    def test_adding_an_account_from_an_app_found_at_its_sign_in_page_stores_and_changes_nothing(self):
        self.desktop_state(ALPHA, "token-a-ended", b"cookies-a-ended")
        marked = self.signed_out()
        log = self.app_log_writer("claude.ai account active and logged in", "[account] User is logged out")
        app = self.start_fake_app()
        result = self.run_sync("-Mode", "AddDesktop", "-DesktopLog", str(log))
        self.assertIn("at its sign-in page, so it holds no login", result.stderr)
        self.assertIn("The desktop app is at its sign-in page.", result.stderr)
        self.assertNotIn("is stored and still good", result.stderr)
        self.assertIsNotNone(app.poll(), "whether it is signed in is read once it is closed")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"])
        self.assertFalse(self.stored(ALPHA, "desktop-login.dpapi").exists())
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), marked)
        self.assertEqual(self.cookies.read_bytes(), b"cookies-a-ended")

    def test_after_an_add_with_no_sign_in_another_add_and_the_switch_back_need_no_cookies_file(self):
        alpha = self.desktop_state(ALPHA, "token-a", b"cookies-a")
        log = self.app_log_writer("claude.ai account active and logged in", "[account] User is logged out")
        self.run_sync("-Mode", "AddDesktop", "-DesktopLog", str(log))
        self.assertFalse(self.cookies.exists(), "the app, simulated, never makes a new one")
        self.assertRegex(self.run_sync("-Mode", "Status").stdout, r"Desktop switch  : available")
        again = self.run_sync("-Mode", "AddDesktop", "-DesktopLog", str(log))
        self.assertIn("at its sign-in page, so it holds no login", again.stderr)
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file(), "the login stored first stays")

        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", ALPHA)
        self.assertNotIn("already signed in", result.stderr)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha, "the add called off, the login is back")
        self.assertEqual(self.cookies.read_bytes(), b"cookies-a")

    def test_an_add_whose_cookies_cannot_be_removed_puts_everything_back(self):
        alpha = self.desktop_state(ALPHA, "token-a", b"cookies-a")
        journal = self.desktop_dir / "Network" / "Cookies-journal"
        journal.write_bytes(b"journal of the cookies")
        with open(self.cookies, "rb"):   # held open without leave to delete, as a scanner may hold it
            failed = self.run_sync("-Mode", "AddDesktop", expect=1)
        self.assertIn("Leaving the desktop app at its sign-in page failed", failed.stderr)
        self.assertIn("its storage is as it was", failed.stderr)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha, "marked signed in again")
        self.assertEqual(self.cookies.read_bytes(), b"cookies-a")
        self.assertEqual(journal.read_bytes(), b"journal of the cookies", "with the journal written back")
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file())
        self.assertFalse(self.launched.exists(), "an app that was not running is not started after a failure")

    def test_an_add_whose_journal_cannot_be_removed_puts_the_mark_back(self):
        alpha = self.desktop_state(ALPHA, "token-a", b"cookies-a")
        journal = self.desktop_dir / "Network" / "Cookies-journal"
        journal.write_bytes(b"journal of the cookies")
        app = self.start_fake_app()
        with open(journal, "rb"):
            failed = self.run_sync("-Mode", "AddDesktop", expect=1)
        self.assertIn("its storage is as it was", failed.stderr)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)
        self.assertEqual(self.cookies.read_bytes(), b"cookies-a")
        self.assertEqual(journal.read_bytes(), b"journal of the cookies")
        self.assertIsNotNone(app.poll(), "the app had been closed for the add")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"], "and it is started again")

    def test_an_add_whose_login_cannot_be_stored_leaves_the_app_signed_in_and_starts_it_again(self):
        alpha = self.desktop_state(ALPHA, "token-a", COOKIES_TOO_LARGE)
        app = self.start_fake_app()
        failed = self.run_sync("-Mode", "AddDesktop", expect=1)
        self.assertIn("Storing the desktop login failed", failed.stderr)
        self.assertIsNotNone(app.poll(), "the app had been closed for the add")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"], "and it is started again")
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha, "still marked signed in")
        self.assertEqual(self.cookies.read_bytes(), COOKIES_TOO_LARGE, "with its cookies")

    def test_the_add_is_refused_where_every_desktop_mode_is(self):
        alpha = self.desktop_state(ALPHA, "token-a", b"cookies-a")
        inside = Path(sys.executable).parent  # an ancestor of the script runs from here, as the app's terminals do
        refused = self.run_sync("-Mode", "AddDesktop", expect=2, app_dir=inside)
        self.assertIn("inside the desktop app", refused.stderr)
        (self.desktop_dir / "fcache").write_text('{"gates":{"96101707":{"value":true}}}', encoding="utf-8")
        refused = self.run_sync("-Mode", "AddDesktop", expect=2)
        self.assertIn("multi-account", refused.stderr)
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)
        self.assertEqual(self.cookies.read_bytes(), b"cookies-a")
        self.assertFalse(self.stored(ALPHA, "desktop-login.dpapi").exists())

    def test_the_watcher_publishes_an_app_at_its_sign_in_page_as_no_accounts(self):
        """One watcher's views: the app signed in to alpha, left at its sign-in page, looked at again unchanged and once
        with its config.json held, which is no word on the app and changes nothing, then signed in to alpha again,
        which the watcher publishes as a change though the account is the one it left."""
        self.sign_in(ALPHA, "alpha@example.com", "token-alpha")
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        probe = self.home / "probe_watch.ps1"
        probe.write_text(WATCH_PROBE.replace("@SCRIPT@", ps_quote(str(SCRIPT)))
                         .replace("@APP@", ps_quote(str(self.app_dir)))
                         .replace("@CONFIG@", ps_quote(str(self.desktop_config)))
                         .replace("@HOME@", ps_quote(str(self.home)))
                         .replace("@CLI@", ps_quote(str(self.cli))), encoding="utf-8-sig")
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                 str(probe)], capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        views = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        self.assertEqual([(v["desktopAccount"], v.get("desktopSignedIn"), v["cliAccount"]) for v in views],
                         [(ALPHA, None, ALPHA), (None, False, ALPHA), (None, False, ALPHA), (None, False, ALPHA),
                          (ALPHA, None, ALPHA)])
        self.assertEqual({views[1]["t"], views[2]["t"], views[3]["t"]}, {views[1]["t"]},
                         "neither an unchanged look nor one that could not read the app publishes anything")
        self.assertEqual(self.events(), [("desktop_account", ALPHA), ("desktop_signed_out", ALPHA),
                                         ("desktop_account", ALPHA)])
        self.assertEqual(self.watch_view(), views[4])

    def test_an_app_at_its_sign_in_page_leaves_the_cli_where_it_is(self):
        self.sign_in(ALPHA, "alpha@example.com", "token-alpha")
        self.run_sync("-Mode", "Snapshot")
        self.sign_in(BETA, "beta@example.com", "token-beta")
        self.run_sync("-Mode", "Snapshot")
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.signed_out()

        self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1")
        view = self.watch_view()
        self.assertEqual((view["desktopAccount"], view["desktopSignedIn"], view["cliAccount"], view["condition"]),
                         (None, False, BETA, None), "no account to follow, and nothing keeping the CLI from it")
        self.assertEqual(self.events()[-1], ("desktop_signed_out", ALPHA), "a watcher's first view publishes it")
        launch = self.run_sync("-Mode", "Sync")
        self.assertEqual(launch.stderr, "", "a launch says nothing of an app at its sign-in page")
        self.assertIn("at its sign-in page; keeping the current CLI sign-in",
                      (self.home / ".claude" / "accounts" / "sync.log").read_text(encoding="utf-8"))
        status = self.run_sync("-Mode", "Status").stdout
        self.assertRegex(status, rf"Desktop account : none: the app is at its sign-in page; its storage still names "
                                 rf"{ALPHA}  alpha@example\.com")
        self.assertRegex(status, r"In sync         : n/a")
        state = json.loads((self.home / ".claude.json").read_text(encoding="utf-8"))
        self.assertEqual(state["oauthAccount"]["accountUuid"], BETA, "the CLI stays on its own account")

        self.desktop_state(ALPHA, "token-a2", b"cookies-a2")   # signed in to alpha again in the app
        self.run_sync("-Mode", "Sync")
        state = json.loads((self.home / ".claude.json").read_text(encoding="utf-8"))
        self.assertEqual(state["oauthAccount"]["accountUuid"], ALPHA, "a signed-in app is followed again")

    def test_an_add_records_the_sign_in_page_only_on_the_apps_word(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        events = self.home / ".claude" / "accounts" / "events.jsonl"
        unconfirmed = self.app_log_writer()
        self.run_sync("-Mode", "AddDesktop", "-DesktopLog", str(unconfirmed), "-SignInSeconds", "2")
        self.assertFalse(events.exists(), "no word from the app, nothing recorded")

        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        signed_in = self.app_log_writer("[oauth-v2] using cached token", "claude.ai account active and logged in")
        self.run_sync("-Mode", "AddDesktop", "-DesktopLog", str(signed_in), expect=1)
        self.assertFalse(events.exists(), "an app that came up signed in is not recorded as signed out")

        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        reached = self.app_log_writer("claude.ai account active and logged in", "[account] User is logged out")
        self.run_sync("-Mode", "AddDesktop", "-DesktopLog", str(reached))
        self.assertEqual(self.events(), [("desktop_signed_out", ALPHA)], "the account it was signed out of")

    def test_a_refused_login_records_the_app_at_its_sign_in_page(self):
        self.store_beta_then_sign_in_to_alpha()
        log = self.app_log_writer("claude.ai account active and logged in",
                                  "[account] Navigated to /logout, synthesizing logged-out")
        self.start_fake_app()
        self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log), expect=5)
        self.assertEqual(self.events()[-2:], [("desktop_account", BETA), ("desktop_signed_out", BETA)])

    def test_a_switch_to_the_account_the_app_is_signed_in_to_records_it(self):
        alpha = self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.run_sync("-Mode", "SwitchDesktop", "-Account", ALPHA)
        self.assertEqual(self.events(), [("desktop_account", ALPHA)], "WindowTally showing it elsewhere is put right")
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)

    # --- the app's cookies saved before it is closed, and the refusal named --------------------------------------

    @staticmethod
    def log_sign_in(log: Path, seconds_ago: float) -> int:
        """Appends to ``log`` the line the app writes as it signs in at its sign-in page, stamped ``seconds_ago``
        seconds ago in local time to the second, as the app stamps it. Returns that stamp in epoch seconds."""
        stamp = int(time.time() - seconds_ago)
        line = (f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stamp))} [info] [account] Login-state transition "
                f"(loggedOut: true → false, uuid: {ALPHA} → {ALPHA}), preserving oauth cache (same-user re-login)\n")
        with log.open("a", encoding="utf-8") as file:
            file.write(line)
        return stamp

    def cookies_written(self, at: float) -> None:
        os.utime(self.cookies, (at, at))

    def sync_log(self) -> str:
        return (self.home / ".claude" / "accounts" / "sync.log").read_text(encoding="utf-8")

    def save_cookies_once_waited_on(self) -> threading.Event:
        """Writes the Cookies file as soon as the sync notes, from now on, that it waits for it, as the app's cookie
        store writes it some seconds after a sign-in: however late a run reaches the wait, the write ends it. Set the
        event returned to stop watching."""
        path = self.home / ".claude" / "accounts" / "sync.log"
        start = path.stat().st_size if path.exists() else 0
        stop = threading.Event()

        def save() -> None:
            while not stop.wait(0.2):
                if path.exists() and WAITING_NOTE.encode() in path.read_bytes()[start:]:
                    self.cookies_written(time.time())
                    return

        threading.Thread(target=save, daemon=True).start()
        return stop

    def test_a_close_waits_for_the_app_to_save_a_sign_in_it_has_just_made(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.cookies_written(time.time() - 60)
        log = self.app_log_writer()
        app = self.start_fake_app()
        # A sign-in just made, so that a run reaching the log within all but a second or two of the 35 seconds still
        # waits: the wait to its end is the margin a slow machine is given.
        stamp = self.log_sign_in(log, 1)
        result = self.run_sync("-Mode", "SnapshotDesktop", "-DesktopLog", str(log))
        self.assertGreaterEqual(time.time(), stamp + 35, "the app was closed no sooner than 35 s after its sign-in")
        at = time.strftime("%H:%M:%S", time.localtime(stamp))
        waiting = f"Waiting for the desktop app to save its sign-in of {at} before closing it..."
        self.assertIn(waiting, result.stderr)
        self.assertLess(result.stderr.index(waiting), result.stderr.index("Closing the desktop app"),
                        "the wait comes before the close, while the run can still be called off")
        self.assertIn(f"Closing the desktop app 35 seconds after its sign-in of {at}", self.sync_log())
        self.assertIsNotNone(app.poll(), "and then the app was closed")
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file())

    def test_a_close_waits_only_until_the_cookies_file_is_written_after_the_sign_in(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.cookies_written(time.time() - 60)
        log = self.app_log_writer()
        self.start_fake_app()
        stamp = self.log_sign_in(log, 1)
        writer = self.save_cookies_once_waited_on()
        try:
            result = self.run_sync("-Mode", "SnapshotDesktop", "-DesktopLog", str(log), "-CookieSaveSeconds", LONG_SAVE)
        finally:
            writer.set()
        at = time.strftime('%H:%M:%S', time.localtime(stamp))
        self.assertIn(f"Waiting for the desktop app to save its sign-in of {at} before closing it...", result.stderr)
        self.assertIn(f"sign-in of {at} is in its Cookies file, written at", self.sync_log(), "the wait ended with the write")
        self.assertNotIn("seconds after its sign-in of", self.sync_log(), "not at its end")

    def test_a_sign_in_the_cookies_file_was_written_after_is_no_wait(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        log = self.app_log_writer()
        self.start_fake_app()
        stamp = self.log_sign_in(log, 10)
        self.cookies_written(stamp + 4)
        result = self.run_sync("-Mode", "SnapshotDesktop", "-DesktopLog", str(log), "-CookieSaveSeconds", LONG_SAVE)
        self.assertNotIn("Waiting for the desktop app", result.stderr)
        self.assertIn("is in its Cookies file", self.sync_log())

    def test_an_older_sign_in_a_closed_app_or_no_log_is_no_wait(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.cookies_written(time.time() - 120)
        log = self.app_log_writer()
        self.log_sign_in(log, 40)
        app = self.start_fake_app()
        older = self.run_sync("-Mode", "SnapshotDesktop", "-DesktopLog", str(log))
        self.assertNotIn("Waiting for the desktop app", older.stderr, "a sign-in 40 s ago is in the file")
        self.assertIsNotNone(app.poll(), "the app was closed, and the launcher starts no app again")

        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.cookies_written(time.time() - 120)
        self.log_sign_in(log, 1)
        closed = self.run_sync("-Mode", "SnapshotDesktop", "-DesktopLog", str(log))
        self.assertNotIn("Waiting for the desktop app", closed.stderr, "a closed app has written its cookies")

        self.start_fake_app()
        unlogged = self.run_sync("-Mode", "SnapshotDesktop")
        self.assertNotIn("Waiting for the desktop app", unlogged.stderr, "a simulated desktop with no log is not waited on")
        self.assertNotIn("sign-in of", self.sync_log())

    def test_every_desktop_mode_that_closes_the_app_waits_for_a_sign_in_just_made(self):
        self.store_beta_then_sign_in_to_alpha()
        self.cookies_written(time.time() - 60)
        log = self.app_log_writer()
        self.start_fake_app()
        self.log_sign_in(log, 29)
        writer = self.save_cookies_once_waited_on()
        try:
            switched = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log),
                                     "-SignInSeconds", "2", "-CookieSaveSeconds", LONG_SAVE)
        finally:
            writer.set()
        self.assertIn(WAITING_NOTE, switched.stderr)

        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.cookies_written(time.time() - 60)
        log = self.app_log_writer("claude.ai account active and logged in", "[account] User is logged out")
        self.start_fake_app()
        self.log_sign_in(log, 29)
        writer = self.save_cookies_once_waited_on()
        try:
            added = self.run_sync("-Mode", "AddDesktop", "-DesktopLog", str(log), "-CookieSaveSeconds", LONG_SAVE)
        finally:
            writer.set()
        self.assertIn(WAITING_NOTE, added.stderr)
        self.assertIn("The desktop app is at its sign-in page.", added.stderr)

    def test_a_sign_in_in_the_log_its_rotation_left_is_found(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.cookies_written(time.time() - 60)
        log = self.app_log_writer()
        rotated = log.with_name("main1.log")
        log.replace(rotated)
        self.start_fake_app()
        stamp = self.log_sign_in(rotated, 29)
        log.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stamp + 1))} [info] the new log's first line\n",
                       encoding="utf-8")
        writer = self.save_cookies_once_waited_on()
        try:
            result = self.run_sync("-Mode", "SnapshotDesktop", "-DesktopLog", str(log), "-CookieSaveSeconds", LONG_SAVE)
        finally:
            writer.set()
        self.assertIn(f"save its sign-in of {time.strftime('%H:%M:%S', time.localtime(stamp))}", result.stderr)

    def test_a_refused_login_whose_start_found_no_sign_in_cookie_is_said_to_have_held_none(self):
        self.store_beta_then_sign_in_to_alpha()
        log = self.app_log_writer("[startup-sign-in] state: {", "  sign_in_cookie_present: false,",
                                  "  signed_in_at_last_exit: true,", "claude.ai account active and logged in",
                                  "[account] User logged out during IPC wait, stopping early")
        self.start_fake_app()
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log), expect=5)
        self.assertIn(f"Switched the desktop app to {BETA}, but the app refused the login stored for it and is at its "
                      "sign-in page: that login held no sign-in cookie, as it was stored before the app had saved its "
                      "sign-in. It is set aside.", result.stderr)
        self.assertNotIn("web session", result.stderr)
        self.assertTrue(self.stored(BETA, "desktop-login.refused.dpapi").is_file(), "set aside all the same")

    def test_a_refused_login_whose_start_found_a_sign_in_cookie_is_said_to_have_lost_its_web_session(self):
        self.store_beta_then_sign_in_to_alpha()
        log = self.app_log_writer("[startup-sign-in] state: {", "  sign_in_cookie_present: true,",
                                  "claude.ai account active and logged in",
                                  "[account] Navigated to /logout, synthesizing logged-out")
        self.start_fake_app()
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log), expect=5)
        self.assertIn("is at its sign-in page: that login's web session had ended, as a sign-out in the app ends it. "
                      "It is set aside.", result.stderr)
        self.assertNotIn("sign-in cookie", result.stderr)

    def test_a_refused_login_whose_start_up_state_was_not_read_is_given_no_cause(self):
        self.store_beta_then_sign_in_to_alpha()
        log = self.app_log_writer("claude.ai account active and logged in", "[account] User is logged out")
        self.start_fake_app()
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log), expect=5)
        self.assertIn("refused the login stored for it and is at its sign-in page. It is set aside.", result.stderr)
        self.assertNotIn("web session", result.stderr)
        self.assertNotIn("sign-in cookie", result.stderr)

    def test_an_app_whose_processes_outlive_its_windows_is_waited_for_and_the_switch_finishes(self):
        _, beta = self.store_beta_then_sign_in_to_alpha()
        app = self.start_fake_app("-Linger", "3")
        self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA)
        self.assertIsNotNone(app.poll(), "the switch waited for the app's last process to end")
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), beta)
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"], "and started the app again")

    def test_an_app_still_running_when_the_wait_ends_is_refused_as_perhaps_partly_closed(self):
        alpha, _ = self.store_beta_then_sign_in_to_alpha()
        app = self.start_fake_app("-Linger", "60")
        refused = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-CloseSeconds", REFUSAL_CLOSE_SECONDS,
                                expect=2)
        self.assertIn("still running 5 seconds after it was told to close", refused.stderr)
        self.assertIn("No login was stored or changed, but the app was told the session ends and may be partly closed",
                      refused.stderr)
        self.assertNotIn("Nothing was changed", refused.stderr, "a close that was begun is not said to have changed nothing")
        self.assertIsNone(app.poll(), "it is never closed by force")
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha)
        self.assertFalse(self.stored(ALPHA, "desktop-login.dpapi").exists())
        self.assertFalse(self.launched.exists())

    def test_an_app_started_again_while_it_closed_is_refused_and_its_login_left_alone(self):
        alpha, _ = self.store_beta_then_sign_in_to_alpha()
        again = self.home / "again.pid"
        self.start_fake_app("-Respawn", str(again))
        try:
            refused = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-CloseSeconds", REFUSAL_CLOSE_SECONDS,
                                    expect=2)
            self.assertIn("the desktop app closed, but was started again within the 5 seconds its close was given",
                          refused.stderr)
            self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), alpha, "no login is put under it")
            self.assertFalse(self.stored(ALPHA, "desktop-login.dpapi").exists())
            self.assertFalse(self.launched.exists())
        finally:
            if again.exists():
                try:
                    os.kill(int(again.read_text(encoding="ascii")), signal.SIGTERM)   # TerminateProcess on Windows
                except OSError:
                    pass
                time.sleep(0.5)   # its executable is freed before the folder is removed

    def test_a_switch_starts_an_app_that_was_not_running_and_reads_its_word_on_the_login(self):
        _, beta = self.store_beta_then_sign_in_to_alpha()
        log = self.app_log_writer("claude.ai account active and logged in")
        result = self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log))
        self.assertEqual(self.desktop_config.read_text(encoding="utf-8"), beta)
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"],
                         "the app is started on the account switched to")
        self.assertIn("watching it sign in", result.stderr)
        self.assertTrue(result.stderr.rstrip().endswith(f"Switched the desktop app to {BETA}."), result.stderr)

    def test_a_login_refused_by_an_app_the_switch_started_is_set_aside(self):
        self.store_beta_then_sign_in_to_alpha()
        log = self.app_log_writer("claude.ai account active and logged in",
                                  "[account] Navigated to /logout, synthesizing logged-out")
        self.run_sync("-Mode", "SwitchDesktop", "-Account", BETA, "-DesktopLog", str(log), expect=5)
        self.assertTrue(self.stored(BETA, "desktop-login.refused.dpapi").is_file())
        self.assertFalse(self.stored(BETA, "desktop-login.dpapi").exists())
        self.assertEqual(self.events()[-1], ("desktop_signed_out", BETA))

    # --- a stored login whose web session the app has ended since --------------------------------------------------

    def app_log(self, *lines: tuple[float, str], rotated: tuple[tuple[tuple[float, str], ...], ...] = ()) -> Path:
        """A stand-in app log holding ``lines``, each ``(seconds from now, text)`` and stamped with its local time as
        the app stamps its lines, and the files the log's rotations left, ``rotated`` holding main1.log's lines first,
        then main2.log's and so on. Returns the log."""
        log = self.home / "app-logs" / "main.log"
        log.parent.mkdir(exist_ok=True)
        now = time.time()

        def text(entries: tuple[tuple[float, str], ...]) -> str:
            return "".join(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now + offset))} [info] {line}\n"
                           for offset, line in entries)

        for number, entries in enumerate(rotated, start=1):
            log.with_name(f"main{number}.log").write_text(text(entries), encoding="utf-8")
        log.write_text(text(lines), encoding="utf-8")
        return log

    def run_left_probe(self, log: Path, between: str) -> dict:
        """LEFT_PROBE against the simulated home with ``between`` as its middle step; returns the last view."""
        probe = self.home / "probe_left.ps1"
        probe.write_text(LEFT_PROBE.replace("@BETWEEN@", between)
                         .replace("@SCRIPT@", ps_quote(str(SCRIPT)))
                         .replace("@APP@", ps_quote(str(self.app_dir)))
                         .replace("@CONFIG@", ps_quote(str(self.desktop_config)))
                         .replace("@HOME@", ps_quote(str(self.home)))
                         .replace("@CLI@", ps_quote(str(self.cli)))
                         .replace("@LOG@", ps_quote(str(log)))
                         .replace("@LAUNCHER@", ps_quote(str(self.launcher))), encoding="utf-8-sig")
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                 str(probe)], capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads([line for line in result.stdout.splitlines() if line.startswith("{")][-1])

    def store_beta_signed_out(self) -> None:
        """Beta's desktop login stored now, then the app left at its sign-in page still naming beta."""
        self.desktop_state(BETA, "token-b", b"cookies-b")
        self.run_sync("-Mode", "SnapshotDesktop")
        self.assertTrue(self.stored(BETA, "desktop-login.dpapi").is_file(), "the login to judge was stored")
        self.signed_out()

    def watch_once(self, log: Path) -> subprocess.CompletedProcess:
        return self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1", "-DesktopLog", str(log))

    def sync_log(self) -> str:
        return (self.home / ".claude" / "accounts" / "sync.log").read_text(encoding="utf-8")

    def test_the_watcher_sets_aside_a_stored_login_whose_web_session_a_sign_out_in_the_app_ended(self):
        self.store_beta_signed_out()
        log = self.app_log((-120, "Starting app {"), (2, "[account] Navigated to /logout, synthesizing logged-out"),
                           (2, left_sign_in(BETA)))
        result = self.watch_once(log)
        self.assertFalse(self.stored(BETA, "desktop-login.dpapi").exists(), "the account counts as having none")
        self.assertTrue(self.stored(BETA, "desktop-login.refused.dpapi").is_file(), "set aside as a refused one is")
        self.assertIn(f"The desktop app left its sign-in to {BETA}", result.stderr)
        self.assertIn("It is set aside", result.stderr)
        self.assertRegex(self.run_sync("-Mode", "Status").stdout, rf"{BETA}\s+\S+\s+usable=\w+\s+desktop-login=False")

    def test_a_sign_out_found_only_in_the_file_the_logs_rotation_left_counts(self):
        self.store_beta_signed_out()
        log = self.app_log((3, "Starting app {"), rotated=(((-120, "Starting app {"), (2, left_sign_in(BETA))),))
        self.watch_once(log)
        self.assertTrue(self.stored(BETA, "desktop-login.refused.dpapi").is_file())
        self.assertFalse(self.stored(BETA, "desktop-login.dpapi").exists())

    def test_the_log_is_read_back_through_every_rotation_to_the_store(self):
        self.store_beta_signed_out()
        log = self.app_log((4, "Starting app {"), rotated=(((3, "Starting app {"),),
                                                            ((-120, "Starting app {"), (2, left_sign_in(BETA)))))
        self.watch_once(log)
        self.assertTrue(self.stored(BETA, "desktop-login.refused.dpapi").is_file(), "the sign-out in main2.log was read")

    def test_a_sign_out_after_a_sign_in_of_the_apps_own_keeps_the_stored_login(self):
        self.store_beta_signed_out()
        log = self.app_log((-120, "Starting app {"), (1, made_sign_in(ALPHA, BETA)), (2, left_sign_in(BETA)))
        result = self.watch_once(log)
        self.assertTrue(self.stored(BETA, "desktop-login.dpapi").is_file(),
                        "the sign-out ended the session the app made, not the one stored")
        self.assertNotIn("left its sign-in", result.stderr)

    def test_a_sign_out_before_the_login_was_stored_says_nothing_of_it(self):
        self.store_beta_signed_out()
        log = self.app_log((-120, "Starting app {"), (-60, left_sign_in(BETA)), (-30, made_sign_in(BETA, BETA)))
        self.watch_once(log)
        self.assertTrue(self.stored(BETA, "desktop-login.dpapi").is_file())

    def test_a_log_that_no_longer_reaches_the_store_keeps_the_stored_login(self):
        self.store_beta_signed_out()
        log = self.app_log((1, "Starting app {"), (2, left_sign_in(BETA)))
        self.watch_once(log)
        self.assertTrue(self.stored(BETA, "desktop-login.dpapi").is_file(),
                        "a sign-in to it may have stood in what the rotation dropped")
        self.assertIn("no longer reaches back to when it was stored", self.sync_log())

    def test_an_add_leaves_the_login_it_stored_where_it_is(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        log = self.app_log_writer("claude.ai account active and logged in", "[account] User is logged out")
        self.run_sync("-Mode", "AddDesktop", "-DesktopLog", str(log))
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file(), "the add stored it")
        self.watch_once(log)
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file(), "an add ends no web session")
        self.assertFalse(self.stored(ALPHA, "desktop-login.refused.dpapi").exists())

    def test_a_sign_in_to_another_account_within_one_look_of_the_sign_out_is_judged_too(self):
        beta = self.desktop_state(BETA, "token-b", b"cookies-b")
        self.run_sync("-Mode", "SnapshotDesktop")
        log = self.app_log((-120, "Starting app {"), (2, left_sign_in(BETA)), (3, made_sign_in(BETA, ALPHA)))
        upcoming = self.home / "next-config.json"
        upcoming.write_text(beta.replace(BETA, ALPHA), encoding="utf-8", newline="")
        view = self.run_left_probe(log, f"[IO.File]::WriteAllText({ps_quote(str(self.desktop_config))}, "
                                        f"[IO.File]::ReadAllText({ps_quote(str(upcoming))}))")
        self.assertEqual(view["desktopAccount"], ALPHA, "the second round saw the app on the other account")
        self.assertNotIn("desktopSignedIn", view, "no look ever saw the app at its sign-in page")
        self.assertTrue(self.stored(BETA, "desktop-login.refused.dpapi").is_file())
        self.assertFalse(self.stored(BETA, "desktop-login.dpapi").exists())

    def test_a_switch_away_keeps_the_login_it_stored_though_an_earlier_sign_out_is_in_the_log(self):
        self.store_beta_then_sign_in_to_alpha()
        log = self.app_log((-120, "Starting app {"), (-60, left_sign_in(ALPHA)), (-30, made_sign_in(ALPHA, ALPHA)))
        view = self.run_left_probe(log, f"[void](Switch-DesktopAccount '{BETA}')")
        self.assertEqual(view["desktopAccount"], BETA, "the second round saw the app on the account switched to")
        self.assertTrue(self.stored(ALPHA, "desktop-login.dpapi").is_file(),
                        "the login the switch stored for the account it left holds the session the app had then")
        self.assertFalse(self.stored(ALPHA, "desktop-login.refused.dpapi").exists())

    # --- whether the app runs, and starting it ---------------------------------------------------------------------

    def test_the_watcher_publishes_an_app_that_is_not_running_and_a_running_one_writes_no_key(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1")
        view = self.watch_view()
        self.assertEqual((view["desktopAccount"], view["desktopRunning"]), (ALPHA, False),
                         "the account it starts on, and that it does not run")
        self.start_fake_app()
        self.run_sync("-Mode", "Watch", "-MaxTicks", "1", "-IntervalSeconds", "1")
        self.assertNotIn("desktopRunning", self.watch_view(), "written only while the app does not run")
        self.assertEqual([e for e in self.events() if e[0] == "desktop_account"], [("desktop_account", ALPHA)] * 2,
                         "whether the app runs writes no event; each watcher's first view publishes its account")

    def test_the_watcher_looks_again_while_the_app_is_not_running_and_keeps_its_view_while_an_act_runs(self):
        """Four rounds: a standing condition and an app that is not running; the same again, written anew so its time
        stays newer than any event; a round while another act holds the act mutex, which leaves the view as published
        and writes nothing; and a round once the act is over."""
        self.sign_in(ALPHA, "alpha@example.com", "token-alpha")
        self.desktop_config.write_text(json.dumps({"lastKnownAccountUuid": BETA}), encoding="utf-8")
        probe = self.home / "probe_rounds.ps1"
        probe.write_text(ROUND_PROBE.replace("@SCRIPT@", ps_quote(str(SCRIPT)))
                         .replace("@APP@", ps_quote(str(self.app_dir)))
                         .replace("@CONFIG@", ps_quote(str(self.desktop_config)))
                         .replace("@HOME@", ps_quote(str(self.home)))
                         .replace("@CLI@", ps_quote(str(self.cli)))
                         .replace("@HELD@", ps_quote(str(self.home / "act-held.txt")))
                         .replace("@RELEASE@", ps_quote(str(self.home / "act-release.txt"))), encoding="utf-8-sig")
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                 str(probe)], capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        views = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        self.assertEqual(len(views), 4, result.stdout)
        for view in views:
            self.assertEqual((view["desktopAccount"], view["desktopRunning"]), (BETA, False))
            self.assertIn("no usable stored sign-in", view["condition"], "the condition stands through the act")
        self.assertLess(views[0]["t"], views[1]["t"], "a look at an app that is still not running is written anew")
        self.assertEqual(views[2]["t"], views[1]["t"], "a round while another act runs writes nothing")
        self.assertLess(views[2]["t"], views[3]["t"], "the watcher's own look once the act is over is written")
        self.assertEqual(self.watch_view(), views[3])
        log = (self.home / ".claude" / "accounts" / "sync.log").read_text(encoding="utf-8")
        self.assertEqual(log.count("no usable stored sign-in"), 1, "a standing condition is logged once, when it begins")

    def test_start_desktop_starts_an_app_that_is_not_running_and_leaves_a_running_one(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        config = self.desktop_config.read_bytes()
        result = self.run_sync("-Mode", "StartDesktop")
        self.assertEqual(self.launched.read_text(encoding="ascii").split(), ["launched"])
        self.assertIn("Starting the desktop app...", result.stderr)
        self.assertTrue(result.stderr.rstrip().endswith("Started the desktop app."), result.stderr)
        self.start_fake_app()
        self.launched.unlink()
        result = self.run_sync("-Mode", "StartDesktop")
        self.assertFalse(self.launched.exists(), "a running app is not started again")
        self.assertIn("already running; nothing was started", result.stderr)
        self.assertEqual(self.desktop_config.read_bytes(), config, "a start touches no login")
        self.assertEqual(self.events(), [("desktop_account", ALPHA)],
                         "a start records the account the app starts on, as a switch does; finding it running, nothing")

    def test_start_desktop_at_its_sign_in_page_records_the_sign_in_page(self):
        self.desktop_state(ALPHA, "token-a", b"cookies-a")
        self.signed_out()
        self.run_sync("-Mode", "StartDesktop")
        self.assertEqual(self.events(), [("desktop_signed_out", ALPHA)], "naming the account its storage still names")

    def test_start_desktop_with_an_app_folder_of_its_own_needs_a_launcher_of_its_own(self):
        answers = []
        for launcher in ("", f"-DesktopLauncher {ps_quote(str(self.launcher))}"):
            probe = self.home / "probe_start_guard.ps1"
            probe.write_text(START_GUARD_PROBE.replace("@SCRIPT@", ps_quote(str(SCRIPT)))
                             .replace("@APP@", ps_quote(str(self.app_dir)))
                             .replace("@LAUNCHER@", launcher)
                             .replace("@HOME@", ps_quote(str(self.home))), encoding="utf-8-sig")
            result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                     str(probe)], capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stderr)
            answers.append(result.stdout.strip())
        self.assertTrue(answers[0].startswith("refused: A -DesktopAppDir of its own needs a -DesktopLauncher"),
                        answers[0])
        self.assertEqual(answers[1], "allowed")
        self.assertFalse(self.launched.exists())

    def test_start_desktop_with_a_simulated_desktop_needs_an_app_folder_of_its_own(self):
        # Refused before anything is read: with no app folder of its own it would look at, and start, the real app.
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                 str(SCRIPT), "-Mode", "StartDesktop", "-ClaudeHome", str(self.home),
                                 "-DesktopConfig", str(self.desktop_config), "-DesktopLauncher", str(self.launcher)],
                                capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("-DesktopAppDir of its own", result.stderr)
        self.assertFalse(self.launched.exists())


class AtomicWriteTest(SyncHomeTestCase):
    """``Write-FileAtomic`` on its own. Another process can hold a file the sync is about to replace — a reader, or
    Windows looking at a file just written — and the replace is refused while it does: a hold let go within the
    write's patience is waited out, and one that outlasts it refuses the write, the file left as it was and no
    temporary file beside it."""

    def write_while_held(self, let_go_after: float | None) -> tuple[str, Path]:
        """The probe's answer and the file, held open as a plain reader holds it (sharing reading and writing, not
        deletion) from before the write until ``let_go_after`` seconds after a move of it was first refused, or until
        the write has ended."""
        target = self.home / "held.json"
        target.write_text("old", encoding="utf-8")
        refused = self.home / "probe-refused.txt"
        probe = self.home / "probe_atomic_write.ps1"
        probe.write_text(ATOMIC_WRITE_PROBE.replace("@SCRIPT@", ps_quote(str(SCRIPT)))
                         .replace("@APP@", ps_quote(str(self.app_dir)))
                         .replace("@CONFIG@", ps_quote(str(self.desktop_config)))
                         .replace("@HOME@", ps_quote(str(self.home)))
                         .replace("@REFUSED@", ps_quote(str(refused)))
                         .replace("@PATH@", ps_quote(str(target))), encoding="utf-8-sig")
        held = open(target, "rb")
        process = subprocess.Popen([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                    str(probe)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            if let_go_after is not None:
                deadline = time.monotonic() + 120
                while not refused.exists():
                    self.assertIsNone(process.poll(), "the write ended without waiting on the file held")
                    self.assertLess(time.monotonic(), deadline, "no move of the file held was refused")
                    time.sleep(0.02)
                time.sleep(let_go_after)
                held.close()
            out, err = process.communicate(timeout=180)
        finally:
            held.close()
            if process.poll() is None:
                process.kill()
                process.communicate()
        self.assertEqual(process.returncode, 0, err)
        return out.strip(), target

    def test_a_file_held_for_a_moment_is_replaced_once_it_is_let_go(self):
        said, target = self.write_while_held(0.2)
        self.assertEqual(said, "written")
        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        self.assertEqual(sorted(p.name for p in self.home.glob("held.json*")), ["held.json"])

    def test_a_file_held_past_the_patience_is_left_as_it_was_and_the_write_refused(self):
        said, target = self.write_while_held(None)
        self.assertTrue(said.startswith("refused: "), said)
        self.assertIn("being used by another process", said)
        self.assertEqual(target.read_text(encoding="utf-8"), "old")
        self.assertEqual(sorted(p.name for p in self.home.glob("held.json*")), ["held.json"],
                         "no temporary file is left beside it")


class FileSetTest(SyncHomeTestCase):
    """``Write-FileSet`` on its own: files read together end wholly written or as they were. A hold on the last file
    outlasting the patience puts back those written before it; one that also stops a file being put back is named,
    that file's old version left beside it."""

    def write_set(self, stick: bool) -> tuple[list[str], Path, Path, Path]:
        """The probe's lines - its answer, then each file's content - with the last file held for the whole write."""
        first, second, last = (self.home / name for name in ("first.json", "second.json", "last.json"))
        first.write_text("first-old", encoding="utf-8")
        last.write_text("last-old", encoding="utf-8")
        probe = self.home / "probe_file_set.ps1"
        probe.write_text(FILE_SET_PROBE.replace("@SCRIPT@", ps_quote(str(SCRIPT)))
                         .replace("@APP@", ps_quote(str(self.app_dir)))
                         .replace("@CONFIG@", ps_quote(str(self.desktop_config)))
                         .replace("@HOME@", ps_quote(str(self.home)))
                         .replace("@FIRST@", ps_quote(str(first)))
                         .replace("@SECOND@", ps_quote(str(second)))
                         .replace("@LAST@", ps_quote(str(last)))
                         .replace("@STICK@", ps_quote("yes" if stick else "no")), encoding="utf-8-sig")
        with open(last, "rb"):
            result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                     str(probe)], capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip().splitlines(), first, second, last

    def test_a_hold_on_the_last_file_puts_back_those_written_before_it(self):
        lines, first, _, last = self.write_set(stick=False)
        self.assertTrue(lines[0].startswith(f"refused: {last} could not be written ("), lines[0])
        self.assertIn("the 2 files of its set written before it were put back, so the set is as it was", lines[0])
        self.assertEqual(lines[1:], ["first-old", "absent", "last-old"], "the replaced file is back, the created one gone")
        self.assertEqual(sorted(p.name for p in self.home.glob("*.json*")), ["first.json", "last.json"])

    def test_a_file_that_cannot_be_put_back_is_named_and_keeps_its_old_version_beside_it(self):
        lines, first, _, last = self.write_set(stick=True)
        self.assertTrue(lines[0].startswith(f"refused: {last} could not be written ("), lines[0])
        self.assertIn(f"its set could not all be put back as it was: {first} (", lines[0])
        self.assertEqual(lines[1:], ["first-new", "absent", "last-old"],
                         "the file held when it was to be put back keeps its new content; the rest is as it was")
        kept = re.search(r"its old version is (\S+?)\)", lines[0])
        self.assertIsNotNone(kept, lines[0])
        self.assertEqual(Path(kept.group(1)).read_text(encoding="utf-8"), "first-old",
                         "its old version is where the message says, for the user to put back")

    def test_a_later_write_leaves_the_old_version_an_earlier_one_could_not_put_back(self):
        self.write_set(stick=True)
        left = sorted(p.name for p in self.home.glob("first.json.sync-old-*"))
        self.assertEqual(len(left), 1, left)
        self.write_set(stick=False)
        self.assertEqual(sorted(p.name for p in self.home.glob("first.json.sync-old-*")), left,
                         "a later write of the same file draws names of its own")


class DesktopAppProcessTest(SyncHomeTestCase):
    def test_the_apps_processes_are_those_of_its_folder_outside_session_0(self):
        """``Get-DesktopAppProcess`` on its own: the script dot-sourced with an app folder that holds nothing, first
        against the real process list, where it must find nothing, then against one made up for the case."""
        probe = self.home / "probe_app_processes.ps1"
        probe.write_text(APP_PROCESS_PROBE.replace("@SCRIPT@", ps_quote(str(SCRIPT)))
                         .replace("@APP@", ps_quote(str(self.app_dir)))
                         .replace("@CONFIG@", ps_quote(str(self.desktop_config)))
                         .replace("@HOME@", ps_quote(str(self.home))), encoding="utf-8-sig")
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                 str(probe)], capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["real=0", "ids=12,13"],
                         "nothing real matches the folder; of the made-up list the app's processes are the ones in "
                         "a user's session, in whichever case their path is written, and the service, a sibling "
                         "folder, a missing path, an unreadable one and another folder's are not")


if __name__ == "__main__":
    unittest.main()
