<#
.SYNOPSIS
Keeps the Claude Code CLI signed in to the same account as the Claude desktop app.

.DESCRIPTION
The desktop app records its signed-in account as lastKnownAccountUuid in %APPDATA%\Claude\config.json.
The CLI keeps its sign-in in ~/.claude/.credentials.json and its account profile in the oauthAccount
object of ~/.claude.json. Desktop sessions authenticate through the app itself and read neither file,
so swapping them changes what every CLI process uses, however it was started, and nothing else.

Sync snapshots the CLI's current sign-in into a per-account store (~/.claude/accounts/<accountUuid>/)
and restores the stored sign-in of the desktop's account, so a switch never repeats the browser login.
An account with no stored sign-in, or whose refresh token has expired, falls back to one interactive
`claude auth login`, whose result is then stored. Credentials are stored DPAPI-encrypted for the
current Windows user; the oauthAccount object is stored as its exact source text so a restore splices
it back byte-for-byte and leaves the rest of ~/.claude.json untouched.

Most CLI processes never pass through the launcher: headless callers run claude.exe by its path. Watch
therefore follows the desktop account from a logon task instead of from a launch. It polls the
desktop's account, switches whenever no CLI is running, defers while one runs, and never signs in: an
account with no usable stored sign-in is logged and left to the next interactive `claude`.

Refresh tokens rotate on use, so the live file is the only current copy of the active account while a
CLI runs. A switch is therefore refused while any CLI process is running. One named mutex serialises
every check-and-act, so the launcher and the watcher never interleave a swap.

The CLI's account is read from the oauthAccount label, which the sign-in file does not name, and
~/.claude.json is shared with the desktop app's own Claude Code, which writes the label of the account
the app signs in to (measured: 4 seconds after a sign-in in the app, 2026-10-26). Three writers leave
three marks: a sign-in writes the label and the sign-in file within seconds of each other, in either
order; a token refresh, or the CLI signing itself out, writes the sign-in file alone; the app's Claude
Code writes the label alone. So a label naming another account than the trusted one is trusted only
when the sign-in file was written within -SignInWindowSeconds of the span in which the label appeared
(after the last look that saw another label, by the look that first saw it), and not by the sync's own
restore; or when the launcher has just run a `claude auth login` that succeeded (Snapshot -SignedIn).
Any other foreign label was written by another program. While the sign-in file is still the one the
trusted label was last seen with, it is that account's: once no CLI runs it is stored under that
account, which keeps its own stored profile, and the CLI follows the desktop app as usual, or that
account's label is put back. Once the file has been rewritten after the label appeared, by a refresh of
a CLI that ran across it or by a sign-in the sync did not see, whose sign-in it holds is not known:
nothing is stored or switched until the label returns or a sign-in through the launcher settles it.
state.json in the store records the trusted label beside the sign-in file it was seen with, the file
the sync's last restore left, when the sync last looked and when it first saw the label then standing.
A label written by another program within the window of a token refresh is taken for a sign-in; that
window is accepted, and it spans the time between two looks, 15 seconds while the watcher runs.

A sign-in file without a pair of OAuth tokens holds no sign-in, and the CLI is taken to have signed out:
a CLI whose sign-in could no longer be refreshed rewrote its file smaller and reported itself signed out
(2026-10-26). Such a file is never stored: it would replace the account's last good sign-in. A CLI signed out of the desktop app's account is a standing condition,
not switched to that account's stored sign-in again; one signed out of another account follows the
desktop app as a CLI with no account does.

Notes go to stderr and to sync.log in the store, and a routine snapshot prints nothing, so through the
launcher stdout carries only the CLI's own output: `claude auth status --json` stays parseable.

The store also carries two machine-readable records, which WindowTally's ledger reads: events.jsonl,
one line per change of the CLI's trusted account (kind cli_account), of the account the desktop app is signed
in to (kind desktop_account: as Watch sees it, as a switch makes it, or as StartDesktop starts the app on it) or of
the app left at its sign-in page (kind desktop_signed_out: as Watch sees it, as a desktop mode reads it in the app's
log, or as StartDesktop starts the app there, naming the account the app's storage still names), each with the account's UUID and when; and watch.json, the watcher's current
view (the desktop account, the CLI account, and the standing condition that keeps the CLI from following, or
null; while the app is at its sign-in page no desktop account, and desktopSignedIn false, a key written only
then; while none of the app's processes runs, desktopRunning false, a key written only then). Like the log, a
record that cannot be written never fails the caller.

The watcher rewrites watch.json whenever its view changes, and on every look while the app is not running, so
that a reader can set the view's time against an event a mode wrote: a switch writes desktop_account and starts
the app, so an event newer than the view answers whether the app runs. A look that finds another of the sync's
acts holding the act mutex (a switch, an add, a store, a start) leaves the view as published and writes nothing: the
act closes and starts the app and changes the logins and the CLI itself, and records what it changed as events.

Desktop switching. SwitchDesktop changes the account the desktop app is signed in to without a browser
login. The app keeps its sign-in in config.json (the oauth:tokenCacheV2 and lastKnownAccountUuid values) and
in the Network\Cookies file. Both are stored per account, DPAPI-encrypted beside the account's CLI sign-in
(desktop-login.dpapi), whenever the app is closed for a switch away from that account. A switch closes the app
gracefully (WM_QUERYENDSESSION, then WM_ENDSESSION, to every window the app's processes own; the app is never
killed), waits up to -CloseSeconds for the processes it asked to end, stores the login it leaves, puts the target's
back and starts the app, whether or not it was running. The app writes a sign-in's
cookie to its Cookies file only some seconds after the sign-in, and a close this way ends it before it has, so every
desktop mode that closes the app first reads the app's log for a sign-in made in the last 35 seconds and waits until
the file has been written since, or until those seconds are up. After a switch it reads what the restarted app
writes to its own log (main.log, an undocumented text) about its sign-in: where the app says it is signed out, it
refused the login it was given, one that held no sign-in cookie or whose web session had ended (a sign-out in the
app ends it), which the app's start-up state tells apart and the note names, and the switch ends with exit 5, the
refused login set aside (desktop-login.refused.dpapi) so that the account counts as having no stored login until
one is stored again. Watch sets a stored login aside the same way, before any switch puts it back, once the app's log
shows that the web session it holds has ended: whenever the app is no longer signed in to the account Watch last saw
it on, and at Watch's first look at an app at its sign-in page, it reads the log from the time that account's login
was stored, and a line of the app leaving that account's sign-in, with no sign-in to it before, ended the stored
session. A sign-in to it first is a session of the app's own, and the stored one is kept, as it is where the log does
not reach back that far. It is refused, with
no login changed, when the app's own multi-account support is present (feature flag 96101707 in fcache), when
config.json or the Cookies file is not laid out as expected, when the app does not close, and when the script
itself runs inside the app, which closing the app would end. A target with no stored login is exit 3. An app
that refuses to close is left as it was; one told the session ends that is still running -CloseSeconds later, or
that was started again while it closed, may be partly closed, and its note says so.

A signed-out app keeps both login values, still naming the account it left, so what tells its storage from a
signed-in one is the boolean windowSizeWasSignedIn beside them in config.json, which the app keeps true while it
is signed in and false once it is not. A signed-out app is no account's: Sync and Watch leave the CLI where it is
and keep its stored sign-in fresh, as while the CLI does not follow the app, and publish no desktop account. No
store files a signed-out app as an account's login: a switch away from one stores nothing and keeps the account's
refused login set aside, SnapshotDesktop refuses, and a switch to the account a signed-out app still names puts
that account's login back. AddDesktop is how an account is added: with the app closed it stores the login the app
holds, then leaves the app at its sign-in page without signing out, so that stored login stays good, and starts
it; the login signed in to there is stored at the next switch away.
It removes the Cookies file to do so, which a signed-out app does without until it makes a new one.
StartDesktop starts the desktop app when none of its processes runs, and starts nothing when it runs; it holds the
act mutex, so it never starts the app in the middle of another act, touches no login, and records the app's account,
or its sign-in page, as a switch records it.
SwitchCli changes the CLI's account on its own, for the time the CLI does not follow the desktop app. Settings
keeps two switches in sync-settings.json: whether the CLI follows the desktop app (Sync and Watch honour it) and
whether one-click desktop switching is offered; both are on until turned off.

This depends on undocumented Claude Code and desktop-app file layouts. When a layout no longer matches,
the script throws instead of guessing, and the launcher does not start the CLI.

Exit codes: 0 = in sync (launch), 2 = refused (no sign-in or login changed, do not launch), 3 = no stored sign-in for the
account asked for (SwitchDesktop, SwitchCli; nothing changed), or, for SwitchCli, the CLI signed out of that account,
whose stored sign-in is then not put back, 4 = a CLI is running (SwitchCli refused for that
alone; nothing changed), 5 = the desktop app was switched but came up signed out (SwitchDesktop: it refused the
stored login, which is set aside), 1 = error. AddDesktop ends 0 once the app is at its sign-in page, or was
already, or was started for it with no word from its log; 1 when the app came up signed in all the same.
StartDesktop ends 0 when it started the app or found it running, 2 when another of the sync's acts stays busy, 1 on
an error. Watch exits 0 at once when another watcher already runs.

.PARAMETER Mode
Sync             Align the CLI with the desktop account (the launcher's default).
Snapshot         Store the CLI's current sign-in only (run after a manual `claude auth ...`; -SignedIn after a
                 `claude auth login` that succeeded).
Status           Show the desktop and CLI accounts, the stored accounts, the switches and the watcher; writes nothing.
Watch            Follow the desktop account until stopped (what the logon task runs).
SwitchDesktop    Switch the desktop app to the account -Account, and start it.
SnapshotDesktop  Store the desktop app's current login; the app is closed and started again if it was running.
AddDesktop       Store the desktop app's current login and leave the app at its sign-in page, to add an account.
StartDesktop     Start the desktop app if it is not running.
SwitchCli        Switch the CLI to the account -Account while the CLI does not follow the desktop app.
Settings         Turn -Follows and -OneClick On or Off.
InstallWatcher   Register the logon task that runs Watch, and start it now.
UninstallWatcher Stop the watcher and remove its logon task.
Install          Add this folder to the user PATH so `claude` resolves to claude.cmd here.
Uninstall        Remove this folder from the user PATH.

.PARAMETER Account
The UUID of the account SwitchDesktop and SwitchCli switch to.

.PARAMETER Follows
Settings: whether the CLI follows the desktop app's account.

.PARAMETER OneClick
Settings: whether one-click desktop switching is offered.

.PARAMETER DesktopAppDir
The folder the desktop app is installed in; the processes under it that run outside Windows session 0 are the ones
SwitchDesktop closes. The Windows service the package also holds runs in session 0 and outlives every close of the
app, so it is not one of them. The installed Claude package's folder when not given. Given with a -DesktopConfig of
its own, so that a simulated desktop never closes the real app. The watcher reads from it whether the app runs.

.PARAMETER DesktopLauncher
A program that starts the desktop app, in place of its Start menu entry; the script waits for it to return.
StartDesktop given a -DesktopAppDir of its own needs one, so that a simulated desktop, whose app never runs, never
starts the real app.

.PARAMETER DesktopLog
The desktop app's own log, which every desktop mode reads for a sign-in just made before it closes the app, and
SwitchDesktop and AddDesktop read after they start the app again. A simulated desktop (a -DesktopConfig of its own)
reads only a log given with it, never the real app's.

.PARAMETER SignInSeconds
Seconds SwitchDesktop and AddDesktop watch the restarted app's log for its word on its sign-in before they report
the outcome as unconfirmed.

.PARAMETER CloseSeconds
Seconds SwitchDesktop, SnapshotDesktop and AddDesktop wait for the desktop app's processes to end once it has agreed
to close. A wait of 30 seconds has ended with the app's processes still listed 38 seconds after it logged its quit,
none left 85 seconds after it (the development machine, 2026-10-26), so the wait is two minutes.

.PARAMETER CookieSaveSeconds
How long after a sign-in at the app's sign-in page its Cookies file holds the sign-in cookie for certain, and so how
long a desktop mode waits for that before it closes the app. The app's cookie store writes a change to that file within
30 seconds, not at once (after each of two starts the file was first written 30 seconds later, the development machine,
2026-10-26), the cookie is set before the sign-in's log line is written (the app used the new account a second before
it), and 5 seconds are a margin, so the wait is 35 seconds, and can be made longer but never shorter.

.PARAMETER SignedIn
Snapshot: the launcher has just run a `claude auth login` that succeeded, so the label it leaves is the sign-in's.

.PARAMETER SignInWindowSeconds
How far apart a sign-in may write the CLI's label and its sign-in file and still be taken for one sign-in.

.PARAMETER IntervalSeconds
Seconds between two checks in Watch.

.PARAMETER MaxTicks
Checks Watch makes before it returns; 0 runs until stopped.
#>
[CmdletBinding()]
param(
    [ValidateSet('Sync', 'Snapshot', 'Status', 'Watch', 'SwitchDesktop', 'SnapshotDesktop', 'AddDesktop', 'StartDesktop',
        'SwitchCli', 'Settings', 'InstallWatcher', 'UninstallWatcher', 'Install', 'Uninstall')]
    [string]$Mode = 'Sync',
    [string]$Account,
    [ValidateSet('On', 'Off')]
    [string]$Follows,
    [ValidateSet('On', 'Off')]
    [string]$OneClick,
    [string]$ClaudeHome = $env:USERPROFILE,
    [string]$DesktopConfig = (Join-Path $env:APPDATA 'Claude\config.json'),
    [string]$CliExe = (Join-Path $env:USERPROFILE '.local\bin\claude.exe'),
    [string]$DesktopAppDir,
    [string]$DesktopLauncher,
    [string]$DesktopLog = (Join-Path $env:LOCALAPPDATA 'Claude\Logs\main.log'),
    [ValidateRange(1, 600)]
    [int]$CloseSeconds = 120,
    [ValidateRange(1, 600)]
    [int]$SignInSeconds = 60,
    [ValidateRange(35, 600)]
    [int]$CookieSaveSeconds = 35,
    [switch]$SignedIn,
    [ValidateRange(1, 600)]
    [int]$SignInWindowSeconds = 30,
    [ValidateRange(1, 3600)]
    [int]$IntervalSeconds = 15,
    [ValidateRange(0, 2147483647)]
    [int]$MaxTicks = 0
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security

$CredentialsPath = Join-Path $ClaudeHome '.claude\.credentials.json'
$StatePath = Join-Path $ClaudeHome '.claude.json'
$StoreRoot = Join-Path $ClaudeHome '.claude\accounts'
# The entropy every stored sign-in is sealed under. It is part of the seal, not a label: change it
# and every file already in the store opens under neither string and is unreadable for good.
$Entropy = [Text.Encoding]::UTF8.GetBytes('WindowTallySync')
$Utf8NoBom = New-Object Text.UTF8Encoding($false)
$TrustPath = Join-Path $StoreRoot 'state.json'
$LogPath = Join-Path $StoreRoot 'sync.log'
$EventsPath = Join-Path $StoreRoot 'events.jsonl'
$WatchStatePath = Join-Path $StoreRoot 'watch.json'
# The watcher's logon task, in the Task Scheduler folder that holds every WindowTally task (install.ps1).
$TaskPath = '\WindowTally\'
$TaskName = 'Sync'
$ScriptParameters = $PSBoundParameters
# Mutex names carry the store's path, so a simulated home never contends with the real one.
$InstanceKey = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash(
    [Text.Encoding]::UTF8.GetBytes($StoreRoot.ToLowerInvariant()))).Replace('-', '').Substring(0, 12)
$ActMutexName = "Local\WindowTally-Act-$InstanceKey"
$WatchMutexName = "Local\WindowTally-Watch-$InstanceKey"
$SyncSettingsPath = Join-Path $StoreRoot 'sync-settings.json'
$DesktopDataRoot = Split-Path $DesktopConfig
$DesktopCookiesPath = Join-Path $DesktopDataRoot 'Network\Cookies'
$DesktopFlagCachePath = Join-Path $DesktopDataRoot 'fcache'
$DesktopArchiveFile = 'desktop-login.dpapi'
# A stored login found dead - refused by the app, or its web session ended since it was stored - kept beside the
# account's store under a name no reader counts as a stored login.
$DesktopRefusedFile = 'desktop-login.refused.dpapi'
# A simulated desktop never reads the real app's log.
$DesktopLogPath = if ($ScriptParameters.ContainsKey('DesktopLog') -or -not $ScriptParameters.ContainsKey('DesktopConfig')) {
    $DesktopLog } else { $null }
# What the app writes to its log as it starts (measured on the development machine over its logs of 2026-10-08 to
# 2026-10-25, Claude desktop up to 2.42304): every start writes the first line, signed in or not; a start whose login
# was refused (its web session ended) or that had none then writes one of the others within a second or two, as does a
# sign-out in the app, and no start that stayed signed in wrote any of them.
$DesktopStartedLine = 'claude.ai account active and logged in'
$DesktopSignedOutLines = 'synthesizing logged-out', 'User logged out during IPC wait', 'User is logged out'
# How long after the first line a start with no signed-out line counts as signed in.
$SignInSettleSeconds = 8
# The start-up state every start writes before its first line says whether the app's Cookies file held a sign-in
# cookie, which tells a refused login that held none from one whose web session had ended (measured on the development
# machine, 2026-10-26, Claude desktop 2.42304.0: false at the start of a login stored 15 seconds after its sign-in;
# true, then a sign-out line, at the start of a login stored before a sign-out in the app).
$DesktopCookieStatePattern = 'sign_in_cookie_present: (true|false)'
# What the app writes as it signs in at its sign-in page, to the account it left or another: a line that opens with its
# local time to the second and holds this text, then an arrow to false (measured on the development machine,
# 2026-10-26, Claude desktop 2.42304.0).
$DesktopSignInLine = 'Login-state transition (loggedOut: true'
# Every change of the app's sign-in writes such a line, naming the sign-in mark's old and new value and the account it
# leaves and the one it reaches, arrows between them (measured on the development machine over its logs of 2026-10-25 to
# 2026-11-01, Claude desktop 2.42304.0): `loggedOut: false -> true, uuid: <account> -> <none>` at each of four sign-outs
# in the app, each ending that account's web session, and at no start, neither one refusing the login it was given nor
# one at its sign-in page for an add; `loggedOut: true -> false, uuid: <left> -> <account>` at each sign-in at its
# sign-in page, which makes a web session of its own. Groups: time, old value, new value, account left, account reached.
$DesktopTransitionPattern = '(?m)^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) [^\r\n]*Login-state transition \(loggedOut: (true|false) \S+ (true|false), uuid: (\S+) \S+ ([^)\s]+)\)'
$DesktopLogTimePattern = '(?m)^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) '
$DesktopPackageFamily = 'Claude_pzs8sxrjxfjjc'
$DesktopAppId = "$DesktopPackageFamily!Claude"
# The desktop app's own multi-account support, announced by this flag in its feature-flag cache.
$DesktopMultiAccountFlag = '96101707'
# Claude Code's own session registry, one <pid>.json per running Claude Code process; read as windowtally/registry.py
# reads it, and never a .key file beside them.
$SessionRegistryDir = Join-Path $ClaudeHome '.claude\sessions'

# Appends to sync.log, rotating it past 512 KB. A log that cannot be written never fails the caller.
function Write-Log([string]$Message) {
    try {
        New-Item -ItemType Directory -Force -Path $StoreRoot | Out-Null
        if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -gt 512KB) {
            Move-Item -LiteralPath $LogPath -Destination "$LogPath.1" -Force
        }
        $now = [DateTimeOffset]::Now.ToString('yyyy-MM-ddTHH:mm:sszzz', [Globalization.CultureInfo]::InvariantCulture)
        $line = '{0} [{1}] {2}' -f $now, $Mode.ToLowerInvariant(), $Message
        [IO.File]::AppendAllText($LogPath, "$line`n", $Utf8NoBom)
    } catch { }
}

# Notes go to stderr, never stdout: through the launcher, stdout carries only the CLI's own output.
function Write-Note([string]$Message) {
    [Console]::Error.WriteLine("[windowtally-sync] $Message")
    Write-Log $Message
}

# The machine-readable records' time: ISO 8601 with milliseconds and the local offset, culture-invariant.
function Get-RecordTime {
    return [DateTimeOffset]::Now.ToString('yyyy-MM-ddTHH:mm:ss.fffzzz', [Globalization.CultureInfo]::InvariantCulture)
}

# Such a time read back, as UTC; $null for a value that is not one. Windows PowerShell's ConvertFrom-Json leaves it a
# string, a later PowerShell makes it a DateTime.
function ConvertFrom-RecordTime($Value) {
    if ($Value -is [DateTime]) { return $Value.ToUniversalTime() }
    $time = [DateTimeOffset]::MinValue
    if ($Value -is [string] -and [DateTimeOffset]::TryParse($Value, [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None, [ref]$time)) { return $time.UtcDateTime }
    return $null
}

# Appends one account change to events.jsonl, rotating it past 512 KB. Like the log, a record that cannot be
# written never fails the caller.
function Write-AccountEvent([string]$Kind, [string]$Uuid) {
    try {
        New-Item -ItemType Directory -Force -Path $StoreRoot | Out-Null
        if ((Test-Path -LiteralPath $EventsPath) -and (Get-Item -LiteralPath $EventsPath).Length -gt 512KB) {
            Move-Item -LiteralPath $EventsPath -Destination "$EventsPath.1" -Force
        }
        $record = [ordered]@{ t = (Get-RecordTime); kind = $Kind; account = $Uuid }
        [IO.File]::AppendAllText($EventsPath, (($record | ConvertTo-Json -Compress) + "`n"), $Utf8NoBom)
    } catch { }
}

# Acquires a named mutex; one abandoned by a holder that died counts as acquired.
function Enter-Mutex([Threading.Mutex]$Mutex, [int]$TimeoutMs) {
    try { return $Mutex.WaitOne($TimeoutMs) } catch [Threading.AbandonedMutexException] { return $true }
}

# Writes a file whole through a temporary file moved over it. The temporary file's bytes reach the disk before the move:
# NTFS journals the move and the file's length but not its bytes, which Windows writes later, so a crash after the move
# and before those bytes were written leaves the file its new length in zero bytes (state.json, on the development
# machine, 2026-11-05) - a sign-in or a config.json lost, not a file left as it was. The move is refused while another
# process holds the file or the temporary file open without sharing deletion - a reader, or Windows looking at a file
# just written - with a sharing violation, or with access denied while a deletion of the file is pending; either is
# waited out for up to $ReplacePatienceMs, as the service's writer waits out every refusal of its move. A hold that
# outlasts it refuses the write, this file left as it was and the temporary file removed.
$ReplacePatienceMs = 2000
function Write-FileAtomic([string]$Path, [byte[]]$Bytes) {
    $tmp = "$Path.sync-tmp"
    Write-StagedFile $tmp $Bytes
    try {
        Invoke-PastHold {
            if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($tmp, $Path, [NullString]::Value) }
            else { [IO.File]::Move($tmp, $Path) }
        }
    } catch { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue; throw }
}

# Writes $Bytes to $Path and flushes them to the disk; a write or flush that fails removes the file and throws.
function Write-StagedFile([string]$Path, [byte[]]$Bytes) {
    $stream = New-Object IO.FileStream($Path, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        try {
            $stream.Write($Bytes, 0, $Bytes.Length)
            $stream.Flush($true)
        } finally { $stream.Dispose() }
    } catch { Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue; throw }
}

# Runs $Action, a move, replace or deletion of files, again after every refusal another process's hold explains, for up
# to $ReplacePatienceMs; any other failure, or a hold that outlasts the patience, is thrown as it is. $Action reads the
# caller's variables, so the names here are ones no caller uses.
function Invoke-PastHold([scriptblock]$Action) {
    $holdDeadline = [DateTime]::UtcNow.AddMilliseconds($ReplacePatienceMs)
    while ($true) {
        try {
            & $Action
            return
        } catch {
            $holdCause = Get-Cause $_
            # 32 ERROR_SHARING_VIOLATION, 33 ERROR_LOCK_VIOLATION: another process holds one of the two files; access
            # denied: the file's deletion is still pending, the refusal the service's writer also waits out.
            $holdHeld = ($holdCause -is [IO.IOException] -and (($holdCause.HResult -band 0xFFFF) -in 32, 33)) -or
                $holdCause -is [UnauthorizedAccessException]
            if (-not $holdHeld -or [DateTime]::UtcNow -ge $holdDeadline) { throw }
            Start-Sleep -Milliseconds 50
        }
    }
}

# The exception an error record carries, unwrapped from the "Exception calling ..." PowerShell puts around a .NET
# method's, and its message.
function Get-Cause($ErrorRecord) {
    $cause = $ErrorRecord.Exception
    if ($cause -is [Management.Automation.MethodInvocationException] -and $cause.InnerException) { $cause = $cause.InnerException }
    return $cause
}
function Get-CauseMessage($ErrorRecord) { return (Get-Cause $ErrorRecord).Message }

# A file's identity as the sync stamps a sign-in file: last write time and length.
function Get-FileStamp([string]$Path) {
    $item = Get-Item -LiteralPath $Path
    return '{0}:{1}' -f $item.LastWriteTimeUtc.Ticks, $item.Length
}

# Writes files that are read together - the CLI's sign-in file beside its profile, the desktop app's Cookies file beside
# its config.json - so that the set ends either wholly written or as it was: Write-FileAtomic file by file would leave
# the earlier files new beside an old later one whenever a hold on the later one outlasted the patience. $Files lists
# the files in the order they are put in place, each Path and Bytes: the new content, $null for a file that is to be
# absent (removed where present), or a scriptblock that returns the content once the entries before it are staged,
# given a table of each such path's staged file - a stamp of a file staged before it, since a replace or a move keeps
# the staged file's write time (measured on the development machine, 2026-11-14). A path may be listed twice, as a
# journal removed before its database is replaced and written after it.
# Every new content is staged first, beside its file, flushed as Write-FileAtomic flushes it; a staging that fails
# changes nothing. Each file is then replaced in turn, its old version kept beside it, or moved aside where it is to be
# absent, each move waiting out a hold as Write-FileAtomic's does. A move refused past that patience puts back the files
# done before it, last first, and throws naming the file refused and saying the set is as it was; a file that cannot be
# put back is named too, with where its old version is. Once every file is in place the old versions are deleted, and
# one that cannot be is logged and left. A crash part way leaves the set part written, the old versions beside it. The
# staged and old files are named after their file with .sync-new- or .sync-old-, a token drawn for each write and the
# entry's place, so that no write ever deletes an old version an earlier one left for the user to put back.
function Write-FileSet([object[]]$Files) {
    $token = [guid]::NewGuid().ToString('N').Substring(0, 8)
    $entries = New-Object Collections.ArrayList
    $staged = @{}
    try {
        foreach ($file in $Files) {
            $at = $entries.Count
            $entry = @{ Path = [string]$file.Path; Staged = $null; Old = "$($file.Path).sync-old-$token-$at"; Kept = $false; Done = $false }
            [void]$entries.Add($entry)
            $bytes = $file.Bytes
            if ($bytes -is [scriptblock]) { $bytes = [byte[]](& $bytes $staged) }
            if ($null -ne $bytes) {
                $entry.Staged = "$($file.Path).sync-new-$token-$at"
                Write-StagedFile $entry.Staged $bytes
                $staged[$entry.Path] = $entry.Staged
            }
        }
    } catch {
        foreach ($entry in $entries) {
            if ($entry.Staged) { Remove-Item -LiteralPath $entry.Staged -Force -ErrorAction SilentlyContinue }
        }
        throw
    }
    foreach ($entry in $entries) {
        $present = $false
        try {
            $present = Test-Path -LiteralPath $entry.Path
            if ($entry.Staged -and $present) {
                try { Invoke-PastHold { [IO.File]::Replace($entry.Staged, $entry.Path, $entry.Old) } }
                catch {
                    $replaceFailure = $_
                    # A replace refused once it had renamed the file aside leaves its path empty: the file goes back.
                    if (-not (Test-Path -LiteralPath $entry.Path) -and (Test-Path -LiteralPath $entry.Old)) {
                        try { Invoke-PastHold { [IO.File]::Move($entry.Old, $entry.Path) } } catch { }
                    }
                    throw $replaceFailure
                }
                $entry.Kept = $true
                $entry.Done = $true
            } elseif ($entry.Staged) {
                Invoke-PastHold { [IO.File]::Move($entry.Staged, $entry.Path) }
                $entry.Done = $true
            } elseif ($present) {
                Invoke-PastHold { [IO.File]::Move($entry.Path, $entry.Old) }
                $entry.Kept = $true
                $entry.Done = $true
            }
        } catch {
            $failure = Get-CauseMessage $_
            $stuck = @()
            if ($present -and -not (Test-Path -LiteralPath $entry.Path)) {
                $stuck += "$($entry.Path) (moved aside and not put back; its old version is $($entry.Old))"
            }
            for ($i = $entries.IndexOf($entry) - 1; $i -ge 0; $i--) {
                $done = $entries[$i]
                if (-not $done.Done) { continue }
                try {
                    if ($done.Staged -and $done.Kept) { Invoke-PastHold { [IO.File]::Replace($done.Old, $done.Path, [NullString]::Value) } }
                    elseif ($done.Staged) { Invoke-PastHold { [IO.File]::Delete($done.Path) } }
                    else { Invoke-PastHold { [IO.File]::Move($done.Old, $done.Path) } }
                } catch {
                    $where = if ($done.Kept) { "its old version is $($done.Old)" } else { 'the set created it' }
                    $stuck += "$($done.Path) ($(Get-CauseMessage $_); $where)"
                }
            }
            foreach ($left in $entries) {
                if ($left.Staged) { Remove-Item -LiteralPath $left.Staged -Force -ErrorAction SilentlyContinue }
            }
            $written = @($entries | Where-Object { $_.Done } | ForEach-Object { $_.Path } | Select-Object -Unique).Count
            if ($stuck.Count -eq 0) {
                $undone = if ($written -eq 0) { 'nothing of its set had been written yet' }
                    elseif ($written -eq 1) { 'the one file of its set written before it was put back' }
                    else { "the $written files of its set written before it were put back" }
                throw "$($entry.Path) could not be written ($failure); $undone, so the set is as it was."
            }
            throw "$($entry.Path) could not be written ($failure), and its set could not all be put back as it was: $($stuck -join '; ')."
        }
    }
    foreach ($entry in $entries) {
        if ($entry.Kept) {
            try { Invoke-PastHold { [IO.File]::Delete($entry.Old) } }
            catch { Write-Log "The old version of $($entry.Path) could not be removed once its set was written: $(Get-CauseMessage $_)" }
        }
    }
}

# A text read as one JSON object; throws naming $What when it is not one, since the parser's own message
# ("Invalid JSON primitive: .") names nothing. The type named in full: [pscustomobject] is PSObject, which every value
# converted from JSON passes for, a bare string or number included. -Secret leaves the parser's message out, since it
# quotes the text it stopped at, and a sign-in's text never enters a message or the log.
function ConvertFrom-JsonObject([string]$Text, [string]$What, [switch]$Secret) {
    $problem = $null
    try { $data = ConvertFrom-Json -InputObject $Text -ErrorAction Stop } catch {
        $data = $null
        if (-not $Secret) { $problem = $_.Exception.Message }
    }
    if ($data -isnot [Management.Automation.PSCustomObject]) {
        throw "$What is not a JSON object$(if ($problem) { " ($problem)" })."
    }
    return $data
}

# A file read as one JSON object, named by its path when it is not one; a file that cannot be read throws as the read does.
function Read-JsonObject([string]$Path) { return (ConvertFrom-JsonObject ([IO.File]::ReadAllText($Path)) $Path) }

# Locates the value of the single "oauthAccount" key. Returns $null when the key is absent;
# otherwise Start/Length of the value token (an object honouring strings and escapes, or null).
function Find-OauthAccountValue([string]$Text) {
    $keys = [regex]::Matches($Text, '"oauthAccount"\s*:\s*')
    if ($keys.Count -eq 0) { return $null }
    if ($keys.Count -gt 1) { throw "Found $($keys.Count) oauthAccount keys in $StatePath; expected one." }
    $start = $keys[0].Index + $keys[0].Length
    if ([string]::CompareOrdinal($Text, $start, 'null', 0, 4) -eq 0) { return @{ Start = $start; Length = 4 } }
    if ($Text[$start] -ne [char]'{') { throw "oauthAccount in $StatePath is neither an object nor null." }
    $depth = 0; $inString = $false; $escaped = $false
    for ($i = $start; $i -lt $Text.Length; $i++) {
        $c = $Text[$i]
        if ($inString) {
            if ($escaped) { $escaped = $false }
            elseif ($c -eq [char]'\') { $escaped = $true }
            elseif ($c -eq [char]'"') { $inString = $false }
            continue
        }
        if ($c -eq [char]'"') { $inString = $true }
        elseif ($c -eq [char]'{') { $depth++ }
        elseif ($c -eq [char]'}') {
            $depth--
            if ($depth -eq 0) { return @{ Start = $start; Length = $i - $start + 1 } }
        }
    }
    throw "oauthAccount object in $StatePath is unterminated."
}

# Locates the value of a named key in a JSON text; returns Start/Length of the value, or $null when absent.
function Find-JsonKeyValue([string]$Text, [string]$Key) {
    $pattern = '"' + [regex]::Escape($Key) + '"\s*:\s*'
    $keys = [regex]::Matches($Text, $pattern)
    if ($keys.Count -eq 0) { return $null }
    if ($keys.Count -gt 1) { throw "Found $($keys.Count) `"$Key`" keys; expected at most one." }
    $start = $keys[0].Index + $keys[0].Length
    if ([string]::CompareOrdinal($Text, $start, 'null', 0, 4) -eq 0) { return @{ Start = $start; Length = 4 } }
    if ([string]::CompareOrdinal($Text, $start, 'true', 0, 4) -eq 0) { return @{ Start = $start; Length = 4 } }
    if ([string]::CompareOrdinal($Text, $start, 'false', 0, 5) -eq 0) { return @{ Start = $start; Length = 5 } }
    $c = $Text[$start]
    if ($c -eq [char]'"') {
        $escaped = $false
        for ($i = $start + 1; $i -lt $Text.Length; $i++) {
            if ($escaped) { $escaped = $false; continue }
            if ($Text[$i] -eq [char]'\') { $escaped = $true; continue }
            if ($Text[$i] -eq [char]'"') { return @{ Start = $start; Length = $i - $start + 1 } }
        }
        throw "`"$Key`" string value is unterminated."
    }
    if ($c -eq [char]'{' -or $c -eq [char]'[') {
        $close = if ($c -eq [char]'{') { [char]'}' } else { [char]']' }
        $depth = 0; $inStr = $false; $esc = $false
        for ($i = $start; $i -lt $Text.Length; $i++) {
            $ch = $Text[$i]
            if ($inStr) {
                if ($esc) { $esc = $false } elseif ($ch -eq [char]'\') { $esc = $true } elseif ($ch -eq [char]'"') { $inStr = $false }
                continue
            }
            if ($ch -eq [char]'"') { $inStr = $true }
            elseif ($ch -eq $c) { $depth++ }
            elseif ($ch -eq $close) { $depth--; if ($depth -eq 0) { return @{ Start = $start; Length = $i - $start + 1 } } }
        }
        throw "`"$Key`" value is unterminated."
    }
    $m = [regex]::Match($Text.Substring($start), '^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?')
    if ($m.Success) { return @{ Start = $start; Length = $m.Length } }
    throw "Cannot parse `"$Key`" value."
}

# The live CLI: its account label (the oauthAccount source text and its parsed form) and its sign-in file's stamp and
# write time (Unix ms), or $null when either is absent. SignedOut says the file holds no sign-in to store.
function Get-CliAccount {
    if (-not (Test-Path -LiteralPath $StatePath) -or -not (Test-Path -LiteralPath $CredentialsPath)) { return $null }
    $text = [IO.File]::ReadAllText($StatePath)
    $span = Find-OauthAccountValue $text
    if ($null -eq $span -or $span.Length -eq 4) { return $null }
    $raw = $text.Substring($span.Start, $span.Length)
    $parsed = ConvertFrom-JsonObject $raw "oauthAccount in $StatePath"
    if (-not $parsed.accountUuid) { throw "oauthAccount in $StatePath has no accountUuid." }
    # The stamp is taken on both sides of the read, so that what is judged of the content is the file the stamp names.
    $item = Get-Item -LiteralPath $CredentialsPath
    $content = [IO.File]::ReadAllText($CredentialsPath)
    $then = Get-Item -LiteralPath $CredentialsPath
    if ($then.LastWriteTimeUtc -ne $item.LastWriteTimeUtc -or $then.Length -ne $item.Length) {
        throw "The CLI's sign-in file changed while it was being read; it is read again at the next look."
    }
    return @{
        Uuid = [string]$parsed.accountUuid; Email = [string]$parsed.emailAddress; Raw = $raw
        Stamp = '{0}:{1}' -f $item.LastWriteTimeUtc.Ticks, $item.Length
        WrittenMs = ([DateTimeOffset]$item.LastWriteTimeUtc).ToUnixTimeMilliseconds()
        SignedOut = -not (Test-SignInHeld $content)
    }
}

# Whether a sign-in file's text holds a sign-in: an OAuth access token and refresh token, both non-empty. A CLI whose
# sign-in could no longer be refreshed rewrote its file at about half the size its sign-in had taken (the development
# machine, 2026-10-26; only the size was seen, never the content), and reported itself signed out; whatever shape
# such a file has, one without the pair holds nothing to store. A text that is not a JSON object is a layout this
# script does not know.
function Test-SignInHeld([string]$Text) {
    if ($Text.Trim() -eq '') { return $false }
    $data = ConvertFrom-JsonObject $Text "The CLI's sign-in file $CredentialsPath" -Secret
    $oauth = $data.PSObject.Properties['claudeAiOauth']
    if (-not $oauth -or $oauth.Value -isnot [Management.Automation.PSCustomObject]) { return $false }
    foreach ($key in 'accessToken', 'refreshToken') {
        $token = $oauth.Value.PSObject.Properties[$key]
        if (-not $token -or $token.Value -isnot [string] -or $token.Value -eq '') { return $false }
    }
    return $true
}

# The desktop app's account as Sync and Watch follow it. Account is the account the app is signed in to, $null when it
# is at its sign-in page or has no config.json; SignedOut, whether its sign-in mark says it is at its sign-in page;
# Named, the account its storage names, which a signed-out app goes on naming after it left it. A mark this cannot
# read is no word on the sign-in, and the account named is followed as it was before the app had the mark: the desktop
# modes refuse such a layout, but the CLI's following does not stop for it.
function Get-DesktopState {
    $state = New-DesktopState
    if (-not (Test-Path -LiteralPath $DesktopConfig)) { return $state }
    $text = [IO.File]::ReadAllText($DesktopConfig)
    $m = [regex]::Match($text, '"lastKnownAccountUuid"\s*:\s*"([0-9a-fA-F-]{36})"')
    if ($m.Success) { $state.Named = $m.Groups[1].Value.ToLowerInvariant() }
    $mark = $null
    try { $mark = Find-JsonKeyValue $text $DesktopSignedInKey } catch { }
    $state.SignedOut = ($null -ne $mark -and $text.Substring($mark.Start, $mark.Length) -eq 'false')
    if (-not $state.SignedOut) { $state.Account = $state.Named }
    return $state
}

# The desktop state of an app nothing is known of, the shape Get-DesktopState returns.
function New-DesktopState { return @{ Account = $null; SignedOut = $false; Named = $null } }

function Get-RunningCli {
    @(Get-Process -Name claude -ErrorAction SilentlyContinue | Where-Object {
        $p = $null
        try { $p = $_.Path } catch { }
        $p -and ($p -ieq $CliExe)
    })
}

function Get-StoreDir([string]$Uuid) { Join-Path $StoreRoot $Uuid.ToLowerInvariant() }

# The stored account's e-mail address, or the UUID itself when the store has none.
function Get-AccountName([string]$Uuid) {
    $meta = Join-Path (Get-StoreDir $Uuid) 'oauthAccount.json'
    if (Test-Path -LiteralPath $meta) {
        $email = (Read-JsonObject $meta).emailAddress
        if ($email) { return [string]$email }
    }
    return $Uuid
}

# The sign-in file's identity: last write time and length. A sign-in, a token refresh and a restore
# all rewrite the file; a label written by anything else leaves it as it was.
function Get-CredentialsStamp {
    if (-not (Test-Path -LiteralPath $CredentialsPath)) { return '' }
    return (Get-FileStamp $CredentialsPath)
}

# state.json: the trusted pairing (accountUuid, and credentialsStamp, the sign-in file it was last seen with), the
# file the sync's own last restore left (restoredStamp), when the sync last looked (lookedAt, Unix ms) and the label
# that look saw (seen: its account, the look that first saw it, and the look before that one). A key absent from an
# older file is null. A file that is not a JSON object stops every look until it is removed: without it, which account
# the CLI's sign-in belongs to is not known, and a look that took the label's word for it would trust a label another
# program wrote. Absent, the next look writes it again, the label then trusted as the first look ever trusts it. A read
# the system refuses (another program holding the file) is thrown as it is, the file being whole.
function Read-TrustState {
    $state = @{ accountUuid = $null; credentialsStamp = $null; restoredStamp = $null; lookedAt = $null; seen = $null }
    if (-not (Test-Path -LiteralPath $TrustPath)) { return $state }
    $text = [IO.File]::ReadAllText($TrustPath)
    try { $data = ConvertFrom-JsonObject $text $TrustPath } catch {
        throw ("$($_.Exception.Message) It records whose sign-in the CLI holds; remove it, and the next look writes it " +
            "again, taking the account the CLI's label names as the CLI's.")
    }
    foreach ($key in 'accountUuid', 'credentialsStamp', 'restoredStamp', 'lookedAt') {
        $property = $data.PSObject.Properties[$key]
        if ($property) { $state[$key] = $property.Value }
    }
    $seen = $data.PSObject.Properties['seen']
    if ($seen -and $seen.Value -is [Management.Automation.PSCustomObject]) {
        $state.seen = @{ account = $null; at = $null; after = $null }
        foreach ($key in 'account', 'at', 'after') {
            $property = $seen.Value.PSObject.Properties[$key]
            if ($property) { $state.seen[$key] = $property.Value }
        }
    }
    return $state
}

function Write-TrustState($State) {
    New-Item -ItemType Directory -Force -Path $StoreRoot | Out-Null
    $record = [ordered]@{ accountUuid = $State.accountUuid; credentialsStamp = $State.credentialsStamp }
    if ($State.restoredStamp) { $record.restoredStamp = $State.restoredStamp }
    if ($null -ne $State.lookedAt) { $record.lookedAt = [int64]$State.lookedAt }
    if ($State.seen) { $record.seen = [ordered]@{ account = $State.seen.account; at = $State.seen.at; after = $State.seen.after } }
    Write-FileAtomic $TrustPath $Utf8NoBom.GetBytes(($record | ConvertTo-Json -Compress -Depth 3))
}

# Records the label as trusted beside the sign-in file it was seen with, when either has changed; -Restored, that the
# sync's own restore wrote that file. Every sign-in, restore and switch passes through here, so a change of the
# trusted account is the moment the CLI's account changed, and it is published as a cli_account event.
function Set-TrustedPairing([string]$Uuid, [switch]$Restored) {
    $state = Read-TrustState
    $stamp = Get-CredentialsStamp
    if ($state.accountUuid -eq $Uuid -and $state.credentialsStamp -eq $stamp -and
        (-not $Restored -or $state.restoredStamp -eq $stamp)) { return }
    $previous = $state.accountUuid
    $state.accountUuid = $Uuid
    $state.credentialsStamp = $stamp
    if ($Restored) { $state.restoredStamp = $stamp }
    Write-TrustState $state
    if ($previous -ne $Uuid) { Write-AccountEvent 'cli_account' $Uuid }
}

# One look at the CLI: its label and sign-in file (Live, $null when either is absent), whether the label is trusted,
# whose sign-in the file holds or last held (Owner, $null where that is not known), whether the file holds none
# (SignedOut), and Note, why a label is not trusted. -Record keeps the look in state.json, so that a later look can
# tell when the label it sees appeared; Status looks without recording. -Witnessed: the caller has just run a
# `claude auth login` that succeeded, so a file written within the window is that sign-in's, label and all.
function Resolve-CliSignIn([switch]$Record, [switch]$Witnessed) {
    $state = Read-TrustState
    $live = Get-CliAccount
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $window = [int64]$SignInWindowSeconds * 1000
    $label = if ($live) { $live.Uuid } else { $null }
    $seen = if ($state.seen -and $state.seen.account -eq $label) { $state.seen } else {
        @{ account = $label; at = $now; after = $state.lookedAt } }
    if ($Record) {
        $state.lookedAt = $now
        $state.seen = $seen
        Write-TrustState $state
    }
    $cli = @{ Live = $live; Trusted = $false; Owner = $null; SignedOut = [bool]($live -and $live.SignedOut); Note = $null }
    if ($null -eq $live) { return $cli }
    $trusted = $state.accountUuid
    if (-not $trusted -or $live.Uuid -eq $trusted -or
        ($Witnessed -and $live.WrittenMs -ge $now - $window) -or (Test-WrittenWithLabel $live $state $seen $window)) {
        $cli.Trusted = $true
        $cli.Owner = $live.Uuid
        return $cli
    }
    $name = Get-AccountName $trusted
    $storedProfile = Join-Path (Get-StoreDir $trusted) 'oauthAccount.json'
    if ($live.Stamp -eq $state.credentialsStamp -and (Test-Path -LiteralPath $storedProfile)) {
        $cli.Owner = $trusted
        $cli.Note = ("the CLI's account label names $($live.Email), written by another program while its sign-in " +
            "stayed $name's")
        return $cli
    }
    $cli.Note = ("The CLI's account label names $($live.Email), but its sign-in file has been written since that label " +
        "appeared, without a sign-in the sync saw, so whether it holds $name's sign-in or another is not known. " +
        'Nothing was stored or switched; run claude auth login and choose the account to use.')
    return $cli
}

# Whether the sign-in file was written with the label it stands beside: by a sign-in, which writes both within seconds,
# in either order. The label appeared after the look before the one that first saw it, so a file written within the
# window of that span was written with it, unless the sync's own restore wrote it. With no earlier look to bound the
# span (a state.json from before the sync recorded its looks) no file counts, since a refresh then looks like a
# sign-in: the label is placed by the file being the trusted one's, or by a sign-in the launcher saw.
function Test-WrittenWithLabel($Live, $State, $Seen, [int64]$Window) {
    if ($State.restoredStamp -and $Live.Stamp -eq $State.restoredStamp) { return $false }
    if ($null -eq $Seen.after) { return $false }
    return ($Live.WrittenMs -ge [int64]$Seen.after - $Window -and $Live.WrittenMs -le [int64]$Seen.at + $Window)
}

# Whether a look leaves nothing to do but say why: a sign-in file holding tokens whose account is not known.
function Test-CliBlocked($Cli) { return [bool]($Cli.Live -and -not $Cli.SignedOut -and -not $Cli.Owner) }

# Whether an account's stored copy predates the live sign-in file.
function Test-SnapshotStale([string]$Uuid) {
    $file = Join-Path (Get-StoreDir $Uuid) 'credentials.stamp'
    if (-not (Test-Path -LiteralPath $file)) { return $true }
    return ([IO.File]::ReadAllText($file) -ne (Get-CredentialsStamp))
}

function Read-StoredCredentials([string]$Uuid) {
    $file = Join-Path (Get-StoreDir $Uuid) 'credentials.dpapi'
    if (-not (Test-Path -LiteralPath $file)) { return $null }
    $sealed = [IO.File]::ReadAllBytes($file)
    return [Security.Cryptography.ProtectedData]::Unprotect($sealed, $Entropy, 'CurrentUser')
}

# A stored sign-in is usable when both halves exist and its refresh token outlives the next hour.
function Test-StoredAccount([string]$Uuid) {
    $dir = Get-StoreDir $Uuid
    if (-not (Test-Path -LiteralPath (Join-Path $dir 'oauthAccount.json'))) { return $false }
    $bytes = Read-StoredCredentials $Uuid
    if ($null -eq $bytes) { return $false }
    $oauth = ($Utf8NoBom.GetString($bytes) | ConvertFrom-Json).claudeAiOauth
    if ($null -eq $oauth) { return $false }
    $expiry = $oauth.PSObject.Properties['refreshTokenExpiresAt']
    if ($null -eq $expiry -or $null -eq $expiry.Value) { return $true }
    $limit = [DateTimeOffset]::UtcNow.AddHours(1).ToUnixTimeMilliseconds()
    return ([int64]$expiry.Value -gt $limit)
}

# Stores the live sign-in under the account a look found it holds, verifies the sealed copy round-trips, and records
# the pairing; returns that account's UUID and e-mail address, or $null when there is nothing to store. The profile
# stored beside it is the label's where the label is trusted; under a label another program wrote, the account keeps
# the profile it has. A file that holds no sign-in is never stored, since it would replace the account's last good
# one, and a file rewritten since the look is not stored on that look's word.
function Save-CliAccount($Cli) {
    if ($null -eq $Cli.Live -or $Cli.SignedOut -or -not $Cli.Owner) { return $null }
    $uuid = $Cli.Owner
    $name = if ($Cli.Trusted) { $Cli.Live.Email } else { Get-AccountName $uuid }
    $dir = Get-StoreDir $uuid
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $stamp = Get-CredentialsStamp
    $bytes = [IO.File]::ReadAllBytes($CredentialsPath)
    if ($stamp -ne $Cli.Live.Stamp -or (Get-CredentialsStamp) -ne $stamp) {
        throw "The CLI's sign-in file changed while it was being stored for $name; nothing was stored or switched."
    }
    $sealed = [Security.Cryptography.ProtectedData]::Protect($bytes, $Entropy, 'CurrentUser')
    Write-FileAtomic (Join-Path $dir 'credentials.dpapi') $sealed
    if ($Cli.Trusted) { Write-FileAtomic (Join-Path $dir 'oauthAccount.json') $Utf8NoBom.GetBytes($Cli.Live.Raw) }
    $check = Read-StoredCredentials $uuid
    if ([Convert]::ToBase64String($check) -ne [Convert]::ToBase64String($bytes)) {
        throw "Stored credentials for $name did not round-trip."
    }
    Write-FileAtomic (Join-Path $dir 'credentials.stamp') $Utf8NoBom.GetBytes($stamp)
    Set-TrustedPairing $uuid
    return @{ Uuid = $uuid; Email = $name }
}

# Keeps the CLI on the account a look found its sign-in file holds, for a moment no CLI runs: stores the file when the
# account's stored copy predates it, and where the label is another program's, puts the account's own label back by
# restoring the copy just stored, the same bytes.
function Update-StoredCliAccount($Cli) {
    if ($null -eq $Cli.Live -or $Cli.SignedOut -or -not $Cli.Owner) { return }
    if ($Cli.Trusted) {
        if (Test-SnapshotStale $Cli.Owner) { Save-CliAccount $Cli | Out-Null }
        return
    }
    Save-CliAccount $Cli | Out-Null
    Restore-StoredAccount $Cli.Owner
    Write-Note "Put the CLI's account label back to $(Get-AccountName $Cli.Owner): $($Cli.Note)."
}

# Puts a stored account back as the live sign-in and records its label as trusted. ~/.claude.json is
# re-read immediately before the splice so a concurrent writer's changes outside oauthAccount are kept. The stored
# profile is spliced in as its text, once that text is known to be a JSON object, so a damaged one never reaches it.
# The sign-in file, ~/.claude.json and the stored stamp of the file are one set (Write-FileSet), so the CLI is never
# left with one account's sign-in beside another's label; the stamp is the staged sign-in file's, which the file keeps
# where the volume keeps a moved file's write time, and is taken again from the file in place where it does not.
function Restore-StoredAccount([string]$Uuid) {
    $dir = Get-StoreDir $Uuid
    $profilePath = Join-Path $dir 'oauthAccount.json'
    $raw = [IO.File]::ReadAllText($profilePath)
    ConvertFrom-JsonObject $raw $profilePath | Out-Null
    $bytes = Read-StoredCredentials $Uuid
    $text = [IO.File]::ReadAllText($StatePath)
    $span = Find-OauthAccountValue $text
    if ($null -eq $span) {
        $open = $text.IndexOf('{')
        if ($open -lt 0) { throw "$StatePath is not a JSON object." }
        $text = $text.Insert($open + 1, "`n  `"oauthAccount`": $raw,")
    } else {
        $text = $text.Remove($span.Start, $span.Length).Insert($span.Start, $raw)
    }
    $stampPath = Join-Path $dir 'credentials.stamp'
    Write-FileSet @(
        @{ Path = $CredentialsPath; Bytes = $bytes }
        @{ Path = $StatePath; Bytes = $Utf8NoBom.GetBytes($text) }
        @{ Path = $stampPath; Bytes = { param($Staged) $Utf8NoBom.GetBytes((Get-FileStamp $Staged[$CredentialsPath])) } }
    )
    # A volume whose replace gives the file a write time of its own (a network share, say) is met by stamping the file
    # in place; the CLI's two files are already one account's.
    $live = Get-CredentialsStamp
    if ([IO.File]::ReadAllText($stampPath) -ne $live) { Write-FileAtomic $stampPath $Utf8NoBom.GetBytes($live) }
    Set-TrustedPairing $Uuid -Restored
}

# Aligns the CLI with the desktop account under the act mutex, waiting up to 30 s for another check.
function Invoke-Sync {
    $lock = New-Object Threading.Mutex($false, $ActMutexName)
    try {
        if (-not (Enter-Mutex $lock 30000)) {
            Write-Note 'Another account sync is still running; nothing was changed. Run claude again in a moment.'
            return 2
        }
        try { return (Sync-WithDesktop) } finally { $lock.ReleaseMutex() }
    } finally { $lock.Dispose() }
}

# What a CLI signed out of the desktop app's account is told: its stored sign-in is the one whose refresh failed, or
# an older copy of it, so the sync does not put it back.
function Get-SignedOutCondition([string]$Uuid) {
    $name = Get-AccountName $Uuid
    return "The CLI is signed out of ${name}: its sign-in has ended. Run claude auth login in a terminal and choose $name."
}

function Sync-WithDesktop {
    $desktop = Get-DesktopState
    $target = $desktop.Account
    $cli = Resolve-CliSignIn -Record
    if ($cli.Trusted) { Set-TrustedPairing $cli.Live.Uuid }
    if (Test-CliBlocked $cli) { Write-Note $cli.Note; return 2 }
    $idle = @(Get-RunningCli).Count -eq 0
    if (-not (Read-SyncSettings).followsDesktop) {
        if ($idle) { Update-StoredCliAccount $cli }
        return 0
    }
    if ($null -eq $target) {
        # An app at its sign-in page is no account's, so the CLI stays where it is. That is no problem to report, and
        # every launch would repeat it, so it goes to the log alone.
        if ($desktop.SignedOut) { Write-Log 'The desktop app is at its sign-in page; keeping the current CLI sign-in.' }
        else { Write-Note 'Desktop account unknown; keeping the current CLI sign-in.' }
        if ($idle) { Update-StoredCliAccount $cli }
        return 0
    }
    if ($cli.Owner -eq $target) {
        # Signed out of the desktop app's account, the CLI asks for a sign-in itself as it starts.
        if ($cli.SignedOut) { Write-Note (Get-SignedOutCondition $target); return 0 }
        if ($idle) { Update-StoredCliAccount $cli }
        return 0
    }
    if (-not $idle) {
        $from = if ($cli.Owner -and -not $cli.SignedOut) { Get-AccountName $cli.Owner } else { 'no account' }
        Write-Note "The desktop app uses another account than the CLI ($from), but a CLI is still running."
        Write-Note 'Close every running claude window, then run claude again. Nothing was changed.'
        return 2
    }
    Save-CliAccount $cli | Out-Null
    if (Test-StoredAccount $target) {
        Restore-StoredAccount $target
        Write-Note "Switched the CLI to $((Get-CliAccount).Email) to match the desktop app."
        return 0
    }
    Write-Note 'The desktop account has no usable stored sign-in yet; opening a one-time browser login.'
    Write-Note 'Choose the same account the desktop app is signed in to.'
    if (Test-Path -LiteralPath $CredentialsPath) { Remove-Item -LiteralPath $CredentialsPath }
    # Start-Process keeps the login on this console without its output joining the return value.
    Start-Process -FilePath $CliExe -ArgumentList 'auth', 'login' -NoNewWindow -Wait
    $after = Resolve-CliSignIn -Record -Witnessed
    if ($after.Trusted) { Set-TrustedPairing $after.Live.Uuid }
    $saved = Save-CliAccount $after
    if ($null -eq $saved) { Write-Note $(if ($after.Note) { $after.Note } else { 'Login did not complete.' }); return 2 }
    if ($saved.Uuid -ne $target) {
        Write-Note "Signed in as $($saved.Email), which is not the desktop app's account. It was stored for later; run claude again to retry."
        return 2
    }
    Write-Note "Signed in as $($saved.Email) and stored it; later switches need no login."
    return 0
}

# Stores the CLI's sign-in after a `claude auth ...` command; -SignedIn after a `claude auth login` that succeeded,
# whose label is then the sign-in's whatever stood before it. A routine store prints nothing, so the launcher's output
# stays the CLI's own; it is logged instead.
function Invoke-Snapshot {
    $lock = New-Object Threading.Mutex($false, $ActMutexName)
    try {
        if (-not (Enter-Mutex $lock 30000)) {
            Write-Note 'Another account sync is still running; the sign-in was not stored.'
            return 0
        }
        try {
            $cli = Resolve-CliSignIn -Record -Witnessed:$SignedIn
            if ($cli.Trusted) { Set-TrustedPairing $cli.Live.Uuid }
            if (Test-CliBlocked $cli) { Write-Note $cli.Note; return 0 }
            $saved = Save-CliAccount $cli
            if ($saved) { Write-Log "Stored the CLI sign-in of $($saved.Email)." } else { Write-Log 'CLI is signed out; nothing stored.' }
        } finally { $lock.ReleaseMutex() }
    } finally { $lock.Dispose() }
    return 0
}

# Whether the desktop app runs: $true or $false, or $null where its processes cannot be listed (the package is not
# installed, or the listing failed), which says nothing of it. About half a second on the development machine
# (2026-10-27).
function Test-DesktopAppRunning {
    try { return (@(Get-DesktopAppProcess).Count -gt 0) } catch { return $null }
}

# One check of the watcher. It acts only when no CLI is running and never signs in, and returns the
# standing condition that keeps the CLI from following the desktop, or $null when nothing is pending.
# A check that finds the act mutex taken leaves this round to the act holding it. $Look records whether the check
# held the mutex (Held) and, if it did, whether the desktop app runs (Running), read under the mutex so that an act
# closing and starting the app is never caught half done. It carries in the account the last check found the app on
# (Left) and whether no check has read it yet (First), and carries out the account this one found (Saw), so that the
# stored login of an account the app has left is judged once, as it leaves it.
function Invoke-WatchTick([hashtable]$Look = @{}) {
    $lock = New-Object Threading.Mutex($false, $ActMutexName)
    try {
        if (-not (Enter-Mutex $lock 0)) { return $null }
        try {
            $Look.Held = $true
            $Look.Running = Test-DesktopAppRunning
            $desktop = Get-DesktopState
            $target = $desktop.Account
            # A sign-out in the app, a sign-in to another account at its sign-in page within one look of it, and an
            # act's switch or add all leave the account the last check found; the first look knows only the one an app
            # at its sign-in page still names.
            $left = if ($Look.First) { if ($desktop.SignedOut) { $desktop.Named } } elseif ($Look.Left -ne $target) { $Look.Left }
            if ($left) { Set-EndedDesktopArchiveAside $left }
            $Look.Saw = $target
            $cli = Resolve-CliSignIn -Record
            if ($cli.Trusted) { Set-TrustedPairing $cli.Live.Uuid }
            if (Test-CliBlocked $cli) { return $cli.Note }
            $running = @(Get-RunningCli).Count
            # With no desktop account to follow (the app at its sign-in page, or unknown), as while the CLI does not
            # follow the app, the CLI stays where it is and its stored sign-in is kept fresh. A CLI signed out there is
            # not reported: the condition is what keeps the CLI from following the app.
            if ($null -eq $target -or -not (Read-SyncSettings).followsDesktop) {
                if ($running -eq 0) { Update-StoredCliAccount $cli }
                return $null
            }
            if ($cli.Owner -eq $target) {
                if ($cli.SignedOut) { return (Get-SignedOutCondition $target) }
                if ($running -eq 0) { Update-StoredCliAccount $cli }
                return $null
            }
            $name = Get-AccountName $target
            if ($running -gt 0) { return "The desktop app uses $name; switching once every running CLI process has exited." }
            if (-not (Test-StoredAccount $target)) {
                return "The desktop app uses $name, which has no usable stored sign-in; run claude in a terminal to sign in once."
            }
            Save-CliAccount $cli | Out-Null
            Restore-StoredAccount $target
            Write-Note "Switched the CLI to $name to match the desktop app."
            return $null
        } finally { $lock.ReleaseMutex() }
    } finally { $lock.Dispose() }
}

# Publishes the watcher's view to watch.json whenever it differs from $Previous, and an event whenever the desktop
# app's account or sign-in does: desktop_account when the app is signed in to an account it was not, after another
# or after its sign-in page, and desktop_signed_out when it is left at its sign-in page, naming the account its
# storage still names. So the first view after a start publishes both. A view of an app at its sign-in page names no
# desktop account and carries desktopSignedIn false, a key written only then. It reads only what a tick reads, and
# a view that cannot be read or written never stops the watch. A look that cannot read the app's config.json (held
# while the app writes it) is no word on the app: the desktop half of the view published stands, rather than flapping
# to no account and back with the event repeated. $Running says whether the app runs ($null: not known); a view of
# an app that does not run carries desktopRunning false, a key written only then, and is written again at every look
# while it stands, so that its time stays newer than any event written before that look. Returns the view published.
function Update-WatchState($Previous, [string]$Condition, $Running = $null) {
    $desktop = $null
    $cli = $null
    try { $desktop = Get-DesktopState } catch { }
    if ($null -eq $desktop) {
        $desktop = New-DesktopState
        if ($Previous) { $desktop.Account = $Previous.desktopAccount; $desktop.SignedOut = $Previous.Contains('desktopSignedIn') }
    }
    try { $live = Get-CliAccount; if ($live) { $cli = $live.Uuid } } catch { }
    $standing = if ($Condition) { $Condition } else { $null }
    $wasSignedOut = $Previous -and $Previous.Contains('desktopSignedIn')
    $closed = $Running -eq $false
    $wasClosed = $Previous -and $Previous.Contains('desktopRunning')
    if ($Previous -and $Previous.desktopAccount -eq $desktop.Account -and $wasSignedOut -eq $desktop.SignedOut -and
        $Previous.cliAccount -eq $cli -and $Previous.condition -eq $standing -and -not $wasClosed -and
        -not $closed) { return $Previous }
    if ($desktop.Account -and (-not $Previous -or $Previous.desktopAccount -ne $desktop.Account)) {
        Write-AccountEvent 'desktop_account' $desktop.Account
    }
    if ($desktop.SignedOut -and $desktop.Named -and -not $wasSignedOut) {
        Write-AccountEvent 'desktop_signed_out' $desktop.Named
    }
    $view = [ordered]@{ t = (Get-RecordTime); desktopAccount = $desktop.Account; cliAccount = $cli; condition = $standing }
    if ($desktop.SignedOut) { $view['desktopSignedIn'] = $false }
    if ($closed) { $view['desktopRunning'] = $false }
    try {
        New-Item -ItemType Directory -Force -Path $StoreRoot | Out-Null
        Write-FileAtomic $WatchStatePath $Utf8NoBom.GetBytes(($view | ConvertTo-Json -Compress))
    } catch { }
    return $view
}

# One round of the watch after the view $View: a check, then the view published from what it read, a standing
# condition logged when it begins, a check that failed among them. A check that finds the act mutex taken by another act
# leaves $View as published, writing nothing, the watcher's first round included: the act closes and starts the app and changes the logins and the CLI itself, records what it changed
# in events.jsonl, and a view read half way through it would be newer than those events and wrong. The next round
# reads everything again. $Seen carries from round to round the desktop account the last check that read the app's
# storage found there (Account, absent before the first): the view is read again after the check, so a change between
# the two would otherwise leave the departure unjudged. Returns the view published.
function Invoke-WatchRound($View, [hashtable]$Seen = @{}) {
    $look = @{ Held = $false; Running = $null; First = -not $Seen.ContainsKey('Account'); Left = $Seen['Account'] }
    $failed = $false
    try { $condition = Invoke-WatchTick $look } catch { $condition = "Error: $($_.Exception.Message)"; $failed = $true }
    if ($look.ContainsKey('Saw')) { $Seen['Account'] = $look.Saw }
    if (-not $look.Held -and -not $failed) { return $View }
    if ($condition -and -not ($View -and $View.condition -eq $condition)) { Write-Log $condition }
    return (Update-WatchState $View $condition $look.Running)
}

# Follows the desktop account until stopped, logging each standing condition once, when it begins.
function Invoke-Watch {
    $instance = New-Object Threading.Mutex($false, $WatchMutexName)
    try {
        if (-not (Enter-Mutex $instance 0)) { return 0 }
        try {
            Write-Log "Watching the desktop account every $IntervalSeconds s."
            $view = $null
            $seen = @{}
            for ($tick = 1; $MaxTicks -eq 0 -or $tick -le $MaxTicks; $tick++) {
                $view = Invoke-WatchRound $view $seen
                if ($MaxTicks -eq 0 -or $tick -lt $MaxTicks) { Start-Sleep -Seconds $IntervalSeconds }
            }
        } finally { $instance.ReleaseMutex() }
    } finally { $instance.Dispose() }
    return 0
}

# What the CLI itself reports in a plain terminal, so the variables a parent Claude Code session
# exports are dropped first. The report reads local state only (measured: it answers the same with the
# network unreachable), so it shows that the CLI is signed in, never whose token it holds.
function Get-CliSelfReport {
    if (-not (Test-Path -LiteralPath $CliExe)) { return "unavailable (no CLI at $CliExe)" }
    Get-ChildItem env: | Where-Object { $_.Name -match '^(CLAUDE|ANTHROPIC)' } |
        ForEach-Object { Remove-Item -LiteralPath "env:$($_.Name)" }
    $ErrorActionPreference = 'Continue'
    $text = ((& $CliExe auth status --json 2>$null) | Out-String).Trim()
    try { $report = ConvertFrom-Json -InputObject $text -ErrorAction Stop } catch { return 'unreadable' }
    $fields = $report.PSObject.Properties
    if (-not ($fields['loggedIn'] -and $report.loggedIn -eq $true)) { return 'signed out' }
    $method = if ($fields['authMethod']) { $report.authMethod } else { 'unknown method' }
    $email = if ($fields['email']) { $report.email } else { 'an unknown account' }
    return "signed in ($method) as $email"
}

# The logon task's state, and whether a watcher holds this store's watch mutex.
function Get-WatcherState {
    $task = Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
    $taskText = if ($task) { "logon task $($task.State)" } else { 'no logon task' }
    $mutex = $null
    $running = [Threading.Mutex]::TryOpenExisting($WatchMutexName, [ref]$mutex)
    if ($mutex) { $mutex.Dispose() }
    return "$taskText; watcher $(if ($running) { 'running' } else { 'not running' })"
}

function Show-Status {
    $desktop = Get-DesktopState
    $target = $desktop.Account
    $unreadable = $null
    try { $cli = Resolve-CliSignIn } catch {
        $unreadable = $_.Exception.Message
        $cli = @{ Live = $null; Trusted = $false; Owner = $null; SignedOut = $false; Note = $null }
    }
    $live = $cli.Live
    $trust = if ($unreadable) { 'unknown' } elseif ($cli.Trusted -or -not $live) { 'yes' } elseif ($cli.Owner) {
        "no - $($cli.Note); the sync puts $(Get-AccountName $cli.Owner)'s label back, or follows the desktop app, once no CLI runs"
    } else { "NO - $($cli.Note)" }
    $named = $desktop.Named
    $desktopWords = if ($target) { $target } elseif ($desktop.SignedOut) { 'none: the app is at its sign-in page' } else { 'unknown' }
    if ($named) {
        $name = Get-AccountName $named
        $shown = "$named$(if ($name -ne $named) { "  $name" })"
        if ($target) { $desktopWords = $shown } elseif ($desktop.SignedOut) { $desktopWords += "; its storage still names $shown" }
    }
    Write-Host "Desktop account : $desktopWords"
    $cliWords = if ($unreadable) { "unknown ($unreadable)" } elseif (-not $live) { 'signed out' } elseif ($cli.SignedOut) {
        "$($live.Uuid)  $($live.Email)  (signed out: its sign-in has ended)" } else { "$($live.Uuid)  $($live.Email)" }
    Write-Host "CLI account     : $cliWords"
    Write-Host "In sync         : $(if ($desktop.SignedOut) { 'n/a (no desktop account to follow; the CLI keeps its own)' } else { [bool]($cli.Owner -and -not $cli.SignedOut -and $target -and $cli.Owner -eq $target) })"
    Write-Host "Label trusted   : $trust"
    Write-Host "CLI self-report : $(Get-CliSelfReport)"
    Write-Host "Running CLIs    : $(@(Get-RunningCli).Count)"
    Write-Host "Watcher         : $(Get-WatcherState)"
    Write-Host 'Stored accounts :'
    if (Test-Path -LiteralPath $StoreRoot) {
        Get-ChildItem -LiteralPath $StoreRoot -Directory | ForEach-Object {
            $meta = Join-Path $_.FullName 'oauthAccount.json'
            $email = if (Test-Path -LiteralPath $meta) { (Read-JsonObject $meta).emailAddress } else { '?' }
            Write-Host "  $($_.Name)  $email  usable=$(Test-StoredAccount $_.Name)  desktop-login=$(Test-DesktopArchive $_.Name)"
        }
    }
    $settings = Read-SyncSettings
    Write-Host "CLI follows app : $(if ($settings.followsDesktop) { 'on' } else { 'off' })"
    Write-Host "One-click switch: $(if ($settings.oneClickDesktop) { 'on' } else { 'off' })"
    if ($settings.problem) { Write-Host "Switch settings : unreadable ($($settings.problem)); both count as on" }
    Write-Host "Desktop switch  : $(Get-DesktopSwitchState)"
    Write-Host "Desktop sign-in : $(Get-DesktopSignInState)"
    Write-Host "Working sessions: $(Get-WorkingSessionCount)"
    if (Test-Path -LiteralPath $LogPath) { Write-Host "Last log line   : $(Get-Content -LiteralPath $LogPath -Tail 1)" }
}

# Whether the desktop app can be switched now, for Status: available, or the reason it is refused.
function Get-DesktopSwitchState {
    try {
        $refusal = Get-DesktopSwitchRefusal
        if ($refusal) { return "refused: $refusal" }
        return 'available'
    } catch { return "unknown ($($_.Exception.Message))" }
}

# Whether the desktop app's storage says it is signed in, for Status.
function Get-DesktopSignInState {
    try {
        if (-not (Test-Path -LiteralPath $DesktopConfig)) { return "unknown (no config.json at $DesktopConfig)" }
        if ((Read-DesktopLogin).SignedIn) { return 'signed in' }
        return 'at its sign-in page'
    } catch { return "unknown ($($_.Exception.Message))" }
}

# How many desktop-hosted Claude Code sessions have a turn in progress, as Claude Code's session registry says: an
# entry of the desktop app's whose status is busy and whose process still runs, the process that wrote it (its id, and
# its creation time as a FILETIME, procStartFt or procStart). windowtally/registry.py states the source; an entry this cannot read counts as not
# at work, as there.
function Get-WorkingSessionCount {
    if (-not (Test-Path -LiteralPath $SessionRegistryDir)) { return 0 }
    $count = 0
    foreach ($file in Get-ChildItem -LiteralPath $SessionRegistryDir -Filter '*.json' -File) {
        if ($file.Name -notmatch '^(\d+)\.json$') { continue }
        $filePid = [int]$Matches[1]
        try {
            $entry = @{}
            ([IO.File]::ReadAllText($file.FullName) | ConvertFrom-Json).PSObject.Properties |
                ForEach-Object { $entry[$_.Name] = $_.Value }
            if ($entry['entrypoint'] -ne 'claude-desktop' -or $entry['status'] -ne 'busy' -or [int]$entry['pid'] -ne $filePid) { continue }
            $start = if ($null -ne $entry['procStartFt']) { $entry['procStartFt'] } else { $entry['procStart'] }
            $process = Get-Process -Id $filePid -ErrorAction Stop
            # StartTime is the creation FILETIME in local time; the entry's FILETIME is converted the same way, so the
            # two agree even in the hour a change back from summer time repeats.
            if ($process.StartTime -eq [DateTime]::FromFileTime([int64]$start)) { $count++ }
        } catch { }
    }
    return $count
}

# Edits the raw (unexpanded) user PATH so %VAR% entries survive, then broadcasts the change.
function Set-UserPathEntry([bool]$Present) {
    $dir = $PSScriptRoot.TrimEnd('\')
    $key = Get-Item -LiteralPath 'HKCU:\Environment'
    $raw = [string]$key.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
    $entries = @($raw -split ';' | Where-Object { $_ -ne '' -and $_.TrimEnd('\') -ine $dir })
    if ($Present) { $entries += $dir }
    $kind = if ($raw) { $key.GetValueKind('Path') } else { [Microsoft.Win32.RegistryValueKind]::ExpandString }
    Set-ItemProperty -LiteralPath 'HKCU:\Environment' -Name Path -Value ($entries -join ';') -Type $kind
    [Environment]::SetEnvironmentVariable('WINDOWTALLY_BROADCAST', '1', 'User')
    [Environment]::SetEnvironmentVariable('WINDOWTALLY_BROADCAST', $null, 'User')
    $verb = if ($Present) { 'added to' } else { 'removed from' }
    Write-Note "$dir $verb the user PATH. Open a new terminal for it to take effect."
}

# The logon task that runs Watch. conhost --headless gives the watcher a console with no window, where
# -WindowStyle Hidden still opens a visible one when Windows Terminal is the default terminal.
function New-WatcherTask {
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $ps = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = "--headless `"$ps`" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Mode Watch -IntervalSeconds $IntervalSeconds"
    foreach ($name in 'ClaudeHome', 'DesktopConfig', 'CliExe') {
        if ($ScriptParameters.ContainsKey($name)) { $arguments += " -$name `"$($ScriptParameters[$name])`"" }
    }
    $action = New-ScheduledTaskAction -Execute (Join-Path $env:WINDIR 'System32\conhost.exe') -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    return New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
        -Description 'Keeps the Claude Code CLI on the Claude desktop app account (WindowTallySync.ps1 -Mode Watch).'
}

function Install-Watcher {
    Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -InputObject (New-WatcherTask) -Force | Out-Null
    Start-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName
    Write-Note "Registered the logon task $TaskPath$TaskName and started it; the CLI now follows the desktop account."
}

# Task Scheduler keeps a folder once its last task is gone. install.ps1 removes the other WindowTally tasks, so
# whichever of the two removes the last one removes the folder, and the same check stands in both: each script is
# installed and run on its own, so neither can call the other's. An empty folder is no registration that runs, so a
# failure to remove it is a note and never stops the uninstall.
function Remove-EmptyTaskFolder {
    try {
        $service = New-Object -ComObject Schedule.Service
        $service.Connect()
        try { $folder = $service.GetFolder($TaskPath.TrimEnd('\')) } catch { return }
        if ($folder.GetTasks(1).Count -eq 0 -and $folder.GetFolders(0).Count -eq 0) {
            $service.GetFolder('\').DeleteFolder($folder.Name, 0)
        }
    } catch {
        Write-Note "The Task Scheduler folder $TaskPath was left: $($_.Exception.Message)"
    }
}

function Uninstall-Watcher {
    if (Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Confirm:$false
    }
    Remove-EmptyTaskFolder
    # A watcher started by hand, or one the task's stop left behind.
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {
        $_.CommandLine -and $_.CommandLine.IndexOf($PSCommandPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $_.CommandLine -match '-Mode\s+Watch\b'
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Note "Removed the logon task $TaskPath$TaskName and stopped the watcher."
}

# ---- The two switches ------------------------------------------------------------------------------------------

# What the WindowTally window turns, kept in the store: whether the CLI follows the desktop app, and whether one-click
# desktop switching is offered. Both are on until turned off, and a key that is neither true nor false counts as
# on. `problem` says why the file could not be read, for Status.
function Read-SyncSettings {
    $settings = @{ followsDesktop = $true; oneClickDesktop = $true; problem = $null }
    if (-not (Test-Path -LiteralPath $SyncSettingsPath)) { return $settings }
    try {
        $data = Read-JsonObject $SyncSettingsPath
        foreach ($key in 'followsDesktop', 'oneClickDesktop') {
            $property = $data.PSObject.Properties[$key]
            if ($property -and $property.Value -is [bool]) { $settings[$key] = $property.Value }
        }
    } catch { $settings.problem = $_.Exception.Message }
    return $settings
}

function Set-SyncSettings {
    $settings = Read-SyncSettings
    if ($Follows) { $settings.followsDesktop = ($Follows -eq 'On') }
    if ($OneClick) { $settings.oneClickDesktop = ($OneClick -eq 'On') }
    New-Item -ItemType Directory -Force -Path $StoreRoot | Out-Null
    $json = [pscustomobject]@{
        followsDesktop = $settings.followsDesktop; oneClickDesktop = $settings.oneClickDesktop
    } | ConvertTo-Json -Compress
    Write-FileAtomic $SyncSettingsPath $Utf8NoBom.GetBytes($json)
    Write-Log "Settings: the CLI follows the desktop app: $($settings.followsDesktop); one-click desktop switching: $($settings.oneClickDesktop)."
}

# ---- The desktop app's login ------------------------------------------------------------------------------------

# The two values of config.json that carry the sign-in; the Network\Cookies file carries the rest.
$DesktopLoginKeys = 'lastKnownAccountUuid', 'oauth:tokenCacheV2'

# The boolean beside them that says whether the app is signed in: true in every signed-in look, false in every
# signed-out one, set false by a sign-out in the app and by a start whose login it refused (measured on the development
# machine, 2026-10-26, Claude desktop 2.42304.0). A sign-out leaves both login values strings, lastKnownAccountUuid
# still naming the account signed out of, so this is what tells a signed-out app's storage from a signed-in one's.
$DesktopSignedInKey = 'windowSizeWasSignedIn'

# The two values as their raw JSON text, the account uuid they name, and whether the app is signed in. Throws when
# either login key is absent, repeated or not a string, the uuid is not one, or the sign-in mark is absent, repeated
# or not a boolean: the storage is then not laid out as this script knows it, and it never guesses.
function Read-DesktopLogin {
    $text = [IO.File]::ReadAllText($DesktopConfig)
    $values = [ordered]@{}
    foreach ($key in $DesktopLoginKeys) {
        $span = Find-JsonKeyValue $text $key
        if ($null -eq $span) { throw "config.json has no `"$key`" key" }
        $raw = $text.Substring($span.Start, $span.Length)
        if (-not $raw.StartsWith('"')) { throw "`"$key`" is not a string" }
        $values[$key] = $raw
    }
    $uuid = $values['lastKnownAccountUuid'].Trim('"')
    if ($uuid -notmatch '^[0-9a-fA-F-]{36}$') { throw '"lastKnownAccountUuid" is not an account uuid' }
    $mark = Find-JsonKeyValue $text $DesktopSignedInKey
    if ($null -eq $mark) { throw "config.json has no `"$DesktopSignedInKey`" key" }
    $flag = $text.Substring($mark.Start, $mark.Length)
    if ($flag -ne 'true' -and $flag -ne 'false') { throw "`"$DesktopSignedInKey`" is not a boolean" }
    return @{ Uuid = $uuid.ToLowerInvariant(); Values = $values; SignedIn = ($flag -eq 'true') }
}

# Writes the sign-in mark, every other byte of config.json kept.
function Set-DesktopSignedIn([bool]$SignedIn) {
    $text = [IO.File]::ReadAllText($DesktopConfig)
    $span = Find-JsonKeyValue $text $DesktopSignedInKey
    if ($null -eq $span) { throw "config.json has no `"$DesktopSignedInKey`" key" }
    $flag = if ($SignedIn) { 'true' } else { 'false' }
    Write-FileAtomic $DesktopConfig $Utf8NoBom.GetBytes($text.Remove($span.Start, $span.Length).Insert($span.Start, $flag))
}

# The app's login files as they stand: config.json, the Cookies file and its journal, the last two $null where absent
# (a signed-out app may have no Cookies file). What a restore that fails returns to, whether or not the login they hold
# was stored.
function Read-DesktopFiles {
    $journal = "$DesktopCookiesPath-journal"
    $files = @{ Config = [IO.File]::ReadAllBytes($DesktopConfig); Cookies = $null; Journal = $null }
    if (Test-Path -LiteralPath $DesktopCookiesPath) { $files.Cookies = [IO.File]::ReadAllBytes($DesktopCookiesPath) }
    if (Test-Path -LiteralPath $journal) { $files.Journal = [IO.File]::ReadAllBytes($journal) }
    return $files
}

# Writes such a set of files as one set (Write-FileSet), one given as $null removed: it ends wholly written or as it
# was, so the app never starts with one login's cookies beside another's config.json. The journal present is removed
# before the Cookies file is replaced, or it would be rolled into the new one; a journal given is written after it.
function Write-DesktopFiles($Files) {
    $journal = "$DesktopCookiesPath-journal"
    $set = @(
        @{ Path = $journal; Bytes = $null }
        @{ Path = $DesktopCookiesPath; Bytes = $Files.Cookies }
    )
    if ($null -ne $Files.Journal) { $set += @{ Path = $journal; Bytes = $Files.Journal } }
    $set += @{ Path = $DesktopConfig; Bytes = $Files.Config }
    Write-FileSet $set
}

function Test-DesktopArchive([string]$Uuid) {
    return (Test-Path -LiteralPath (Join-Path (Get-StoreDir $Uuid) $DesktopArchiveFile))
}

# The stored desktop login of an account, or $null: version 1, its account, the two config values as raw JSON text
# and the Cookies file in base64, sealed for the current Windows user.
function Read-DesktopArchive([string]$Uuid) {
    $file = Join-Path (Get-StoreDir $Uuid) $DesktopArchiveFile
    if (-not (Test-Path -LiteralPath $file)) { return $null }
    $bytes = [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($file), $Entropy, 'CurrentUser')
    return ($Utf8NoBom.GetString($bytes) | ConvertFrom-Json)
}

# Why switching the desktop app's account is refused now, or $null. Nothing here guesses: a layout that is not the
# one the switch was written for is a reason to stop.
function Get-DesktopSwitchRefusal {
    if (Test-Path -LiteralPath $DesktopFlagCachePath) {
        $cache = [Text.Encoding]::GetEncoding(28591).GetString([IO.File]::ReadAllBytes($DesktopFlagCachePath))
        if ($cache.Contains($DesktopMultiAccountFlag)) {
            return "the desktop app's own multi-account support is present (feature flag $DesktopMultiAccountFlag in its flag cache), and a switch here could conflict with it."
        }
    }
    if (-not (Test-Path -LiteralPath $DesktopConfig)) { return "the desktop app has no config.json at $DesktopConfig." }
    try { $login = Read-DesktopLogin } catch { return "config.json is not laid out as this switch expects ($($_.Exception.Message))." }
    # A signed-out app needs no Cookies file: an add removes it, and the app makes a new one in its own time.
    if ($login.SignedIn -and -not (Test-Path -LiteralPath $DesktopCookiesPath)) {
        return "the desktop app has no Network\Cookies file at $DesktopCookiesPath."
    }
    return $null
}

# Stores the login the desktop app holds now under its account and returns the account; $Login is that login as
# Read-DesktopLogin read it. The app must be closed: the Cookies file is locked while it runs. A signed-out app holds
# no login, and storing it would replace the account's.
function Save-DesktopLogin($Login) {
    if (-not $Login.SignedIn) { throw 'The desktop app is at its sign-in page; its storage holds no login to store.' }
    $cookies = [IO.File]::ReadAllBytes($DesktopCookiesPath)
    if ($cookies.Length -gt 1MB) { throw "The Cookies file is $($cookies.Length) bytes, far larger than a sign-in's; its layout is not the one this script knows." }
    $dir = Get-StoreDir $login.Uuid
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $archive = [ordered]@{
        v = 1; account = $login.Uuid; savedAt = (Get-RecordTime); config = $login.Values
        cookies = [Convert]::ToBase64String($cookies)
    }
    $sealed = [Security.Cryptography.ProtectedData]::Protect(
        $Utf8NoBom.GetBytes(($archive | ConvertTo-Json -Compress -Depth 4)), $Entropy, 'CurrentUser')
    Write-FileAtomic (Join-Path $dir $DesktopArchiveFile) $sealed
    $check = Read-DesktopArchive $login.Uuid
    if ($check.cookies -ne $archive.cookies -or $check.config.'oauth:tokenCacheV2' -ne $login.Values['oauth:tokenCacheV2']) {
        throw "The stored desktop login of $(Get-AccountName $login.Uuid) did not round-trip."
    }
    # A login the app refused earlier is worth nothing once a fresh one is stored.
    $refused = Join-Path $dir $DesktopRefusedFile
    try { if (Test-Path -LiteralPath $refused) { Remove-Item -LiteralPath $refused -Force } }
    catch { Write-Log "The refused desktop login beside $dir could not be removed: $($_.Exception.Message)" }
    return $login.Uuid
}

# Sets a stored login the app refused aside, so that the account counts as having none. Returns $null, or why it could
# not be.
function Set-DesktopArchiveAside([string]$Uuid) {
    $dir = Get-StoreDir $Uuid
    try {
        Move-Item -LiteralPath (Join-Path $dir $DesktopArchiveFile) -Destination (Join-Path $dir $DesktopRefusedFile) -Force
        return $null
    } catch { return $_.Exception.Message }
}

# Whether the web session the stored desktop login of $Uuid holds has ended since it was stored, read from the app's log:
# the first line after the store that names the app leaving that account's sign-in or making one decides. Leaving it
# ended the session the app then held, the stored one, since only a sign-in makes another; a sign-in first means the app
# went on with a session of its own, and a sign-out after it says nothing of the stored one, which may still be good.
# Returns Ended, At (UTC) when it ended, and a Note saying why the log could not tell, $null where it simply holds no
# such line or there is no log to read. Throws where the stored login cannot be opened.
function Test-DesktopArchiveEnded([string]$Uuid) {
    $archive = Read-DesktopArchive $Uuid
    if ($null -eq $archive) { return @{ Ended = $false; At = $null; Note = $null } }
    $stamp = $archive.PSObject.Properties['savedAt']
    $saved = if ($stamp) { ConvertFrom-RecordTime $stamp.Value } else { $null }
    if ($null -eq $saved) { return @{ Ended = $false; At = $null; Note = 'it records no time it was stored' } }
    $span = Read-DesktopLogSpan $saved
    if ($null -eq $span) { return @{ Ended = $false; At = $null; Note = $null } }
    # A log that no longer reaches the store may have lost a sign-in to the account before the sign-out it still holds.
    if (-not $span.Reaches) {
        return @{ Ended = $false; At = $null; Note = "the desktop app's log no longer reaches back to when it was stored" }
    }
    # The log's times are whole seconds; the app is closed while a login is stored, so a line in that second is later.
    $from = $saved.AddTicks(-($saved.Ticks % [TimeSpan]::TicksPerSecond))
    $account = $Uuid.ToLowerInvariant()
    foreach ($match in [regex]::Matches($span.Text, $DesktopTransitionPattern)) {
        $time = ConvertFrom-DesktopLogTime $match.Groups[1].Value
        if ($null -eq $time -or $time -lt $from) { continue }
        $old = $match.Groups[2].Value
        $new = $match.Groups[3].Value
        if ($old -eq 'true' -and $new -eq 'false' -and $match.Groups[5].Value.ToLowerInvariant() -eq $account) {
            return @{ Ended = $false; At = $null; Note = $null }
        }
        if ($old -eq 'false' -and $new -eq 'true' -and $match.Groups[4].Value.ToLowerInvariant() -eq $account) {
            return @{ Ended = $true; At = $time; Note = $null }
        }
    }
    return @{ Ended = $false; At = $null; Note = $null }
}

# Sets the stored desktop login of $Uuid aside where its web session has ended since it was stored, so that the account
# counts as having none and a switch to it asks for a sign-in instead of closing the app to put back a login the app
# would refuse. Called under the act mutex, so no switch reads the login meanwhile. It never throws: a login that cannot
# be judged stays stored, and a refused switch still sets it aside.
function Set-EndedDesktopArchiveAside([string]$Uuid) {
    try {
        $verdict = Test-DesktopArchiveEnded $Uuid
        $name = Get-AccountName $Uuid
        if ($verdict.Ended) {
            $at = $verdict.At.ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture)
            $problem = Set-DesktopArchiveAside $Uuid
            $aside = if ($problem) { "It could not be set aside ($problem)." } else { "It is set aside, so that a switch to $name asks for a sign-in rather than closing the app for a login it would refuse." }
            Write-Note "The desktop app left its sign-in to $name at $at, ending the web session of the login stored for it. $aside"
        } elseif ($verdict.Note) {
            Write-Log "The desktop login stored for $name is kept, though the app has left it: $($verdict.Note)."
        }
    } catch {
        Write-Log "Whether the desktop login stored for $Uuid still holds its web session could not be read: $($_.Exception.Message)"
    }
}

# Puts a stored desktop login back: its two values spliced into config.json and the sign-in mark set true, since a
# login is stored only from a signed-in app, with every other value kept as it stands, and its Cookies file in place
# of the app's, with no journal: a journal belongs to the file it was written beside. The app must be closed.
function Restore-DesktopLogin([string]$Uuid) {
    $archive = Read-DesktopArchive $Uuid
    if ($null -eq $archive) { throw "There is no stored desktop login for $Uuid." }
    if ($archive.v -ne 1 -or $archive.account -ne $Uuid.ToLowerInvariant()) {
        throw "The stored desktop login for $Uuid is not in the layout this script writes."
    }
    $text = [IO.File]::ReadAllText($DesktopConfig)
    foreach ($key in $DesktopLoginKeys) {
        $span = Find-JsonKeyValue $text $key
        if ($null -eq $span) { throw "config.json has no `"$key`" key to put the stored login in." }
        $text = $text.Remove($span.Start, $span.Length).Insert($span.Start, [string]$archive.config.$key)
    }
    $mark = Find-JsonKeyValue $text $DesktopSignedInKey
    if ($null -eq $mark) { throw "config.json has no `"$DesktopSignedInKey`" key to mark the stored login signed in." }
    $text = $text.Remove($mark.Start, $mark.Length).Insert($mark.Start, 'true')
    Write-DesktopFiles @{
        Config = $Utf8NoBom.GetBytes($text); Cookies = [Convert]::FromBase64String([string]$archive.cookies); Journal = $null
    }
    $after = (Read-DesktopLogin).Uuid
    if ($after -ne $Uuid.ToLowerInvariant()) { throw "config.json names $after after the restore, not $Uuid." }
}

# ---- The desktop app's processes --------------------------------------------------------------------------------

# The folder the app runs from: the one given, or the installed package's.
function Get-DesktopAppDir {
    if ($DesktopAppDir) { return $DesktopAppDir.TrimEnd('\') }
    $package = @(Get-AppxPackage -Name ($DesktopPackageFamily.Split('_')[0]) |
        Where-Object { $_.PackageFamilyName -eq $DesktopPackageFamily })
    if ($package.Count -eq 0) { throw "The Claude desktop app ($DesktopPackageFamily) is not installed for this user." }
    return ([string]$package[0].InstallLocation).TrimEnd('\')
}

# Every process that runs from the app's folder outside Windows session 0, which is how the app's own processes are
# told from the Claude Code engine it hosts and from the CLI. The package also holds a Windows service
# (CoworkVMService: started at boot, owns no window, outlives every close of the app), and a service runs in session
# 0 whatever its name or path, so counting it would leave the app never closed. The script's own session is not the
# test: run from another session, it would take a running app for absent and rewrite its files.
# A process's Path walks its module list, which over every process outside session 0 takes many times as long as one
# CIM query of every process's image path (measured on the development machine, 2026-10-26). So a live process is read
# through that query, taken after the list, so that every process listed and still alive is in it; anything else the list
# holds (the tests' stand-ins) is read by its Path, as is every process when the query fails.
function Get-DesktopAppProcess {
    $prefix = (Get-DesktopAppDir) + '\'
    $listed = @(Get-Process)
    $paths = $null
    try {
        $paths = @{}
        foreach ($row in @(Get-CimInstance Win32_Process -Property ProcessId, ExecutablePath -ErrorAction Stop)) {
            $paths[[int]$row.ProcessId] = [string]$row.ExecutablePath
        }
    } catch { $paths = $null }
    @($listed | Where-Object {
        $p = $null
        try {
            if ($_.SessionId -ne 0) {
                $p = if ($null -ne $paths -and $_ -is [Diagnostics.Process]) { $paths[$_.Id] } else { $_.Path }
            }
        } catch { }
        $p -and $p.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
    })
}

# Whether this script runs inside the desktop app: a terminal or a tool the app started ends when the app does.
function Test-InsideDesktopApp {
    $prefix = (Get-DesktopAppDir) + '\'
    $parents = @{}
    $paths = @{}
    foreach ($process in Get-CimInstance Win32_Process) {
        $parents[[int]$process.ProcessId] = [int]$process.ParentProcessId
        $paths[[int]$process.ProcessId] = [string]$process.ExecutablePath
    }
    $id = $PID
    for ($depth = 0; $depth -lt 32 -and $parents.ContainsKey($id); $depth++) {
        $id = $parents[$id]
        $path = $paths[$id]
        if ($path -and $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

# Compiled on first use (Windows PowerShell's C# is version 5), so the launcher and the watcher never pay for it.
function Initialize-WindowApi {
    if ('WindowTallySyncWindows' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class WindowTallySyncWindows {
    private delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumProc proc, IntPtr lParam);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam,
        uint flags, uint timeoutMs, out IntPtr result);
    private const uint WM_QUERYENDSESSION = 0x0011;
    private const uint WM_ENDSESSION = 0x0016;
    private const uint SMTO_ABORTIFHUNG = 0x0002;

    // The top-level windows, shown or hidden, that the given processes own.
    public static IntPtr[] WindowsOf(uint[] processIds) {
        List<uint> ids = new List<uint>(processIds);
        List<IntPtr> found = new List<IntPtr>();
        EnumWindows(delegate (IntPtr hWnd, IntPtr lParam) {
            uint owner;
            GetWindowThreadProcessId(hWnd, out owner);
            if (ids.Contains(owner)) found.Add(hWnd);
            return true;
        }, IntPtr.Zero);
        return found.ToArray();
    }

    // 1 = the window agrees to the session ending, 0 = it refuses, -1 = it did not answer in time.
    public static int QueryEndSession(IntPtr hWnd, uint timeoutMs) {
        IntPtr result;
        if (SendMessageTimeout(hWnd, WM_QUERYENDSESSION, IntPtr.Zero, IntPtr.Zero, SMTO_ABORTIFHUNG, timeoutMs,
            out result) == IntPtr.Zero) return -1;
        return result == IntPtr.Zero ? 0 : 1;
    }

    // Tells the window the session is ending (true), or that the end was called off (false).
    public static bool EndSession(IntPtr hWnd, bool isEnding, uint timeoutMs) {
        IntPtr result;
        return SendMessageTimeout(hWnd, WM_ENDSESSION, isEnding ? new IntPtr(1) : IntPtr.Zero, IntPtr.Zero,
            SMTO_ABORTIFHUNG, timeoutMs, out result) != IntPtr.Zero;
    }
}
'@
}

# Closes the desktop app the way Windows closes a program when a session ends, and never by force: every window its
# processes own is asked, and only if all agree is the end announced. Returns $null once no process of the app is left,
# or why the app could not be closed: Reason, and Told, whether the end had been announced, after which the app
# may be partly closed, its Code sessions ended. Its processes can outlive the end by a minute and more, so the wait
# runs to -CloseSeconds, and ends only once no process of the app is left: one that was not among those asked was
# started since, and a login stored or restored under it would race it. Such a process is not refused on sight, since
# the app may start a short-lived one as it quits; one still there at the end of the wait names the refusal.
function Stop-DesktopApp {
    Initialize-WindowApi
    $processes = @(Get-DesktopAppProcess)
    if ($processes.Count -eq 0) { return $null }
    $asked = @($processes | ForEach-Object { $_.Id })
    $windows = @([WindowTallySyncWindows]::WindowsOf([uint32[]]$asked))
    if ($windows.Count -eq 0) { return @{ Reason = 'the desktop app is running but owns no window to ask to close'; Told = $false } }
    foreach ($window in $windows) {
        $answer = [WindowTallySyncWindows]::QueryEndSession($window, 5000)
        if ($answer -ne 1) {
            foreach ($other in $windows) { [WindowTallySyncWindows]::EndSession($other, $false, 1000) | Out-Null }
            if ($answer -eq 0) { return @{ Reason = 'the desktop app refused to close'; Told = $false } }
            return @{ Reason = 'the desktop app did not answer the request to close'; Told = $false }
        }
    }
    foreach ($window in $windows) { [WindowTallySyncWindows]::EndSession($window, $true, 5000) | Out-Null }
    # A listing takes seconds, and what it shows is as old as its start: only a listing begun once the wait is up can
    # refuse, or an app that ended while a listing ran is refused as still running.
    $deadline = [DateTime]::UtcNow.AddSeconds($CloseSeconds)
    while ($true) {
        $listedAt = [DateTime]::UtcNow
        $left = @(Get-DesktopAppProcess)
        if ($left.Count -eq 0) { return $null }
        if ($listedAt -ge $deadline) { break }
        Start-Sleep -Milliseconds 500
    }
    if (@($left | Where-Object { $asked -contains $_.Id }).Count -eq 0) {
        return @{ Reason = "the desktop app closed, but was started again within the $CloseSeconds seconds its close was given"; Told = $true }
    }
    return @{ Reason = "the desktop app was still running $CloseSeconds seconds after it was told to close"; Told = $true }
}

function Start-DesktopApp {
    if ($DesktopLauncher) { Start-Process -FilePath $DesktopLauncher -WindowStyle Hidden -Wait }
    else { Start-Process "shell:AppsFolder\$DesktopAppId" }
}

# The app's log file, opened for reading beside the app's own writes, renames included; $null when it cannot be.
function Open-DesktopLogFile {
    try {
        return [IO.File]::Open($DesktopLogPath, [IO.FileMode]::Open, [IO.FileAccess]::Read,
            [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
    } catch { return $null }
}

# Opens the app's log where it ends now, while the app is closed, so that only what the app writes once started is
# read; a log not yet written is read from its start once it appears. $null when there is no log to read: none was
# given to a simulated desktop, or the log's folder does not exist.
function Open-DesktopLog {
    if (-not $DesktopLogPath -or -not (Test-Path -LiteralPath (Split-Path $DesktopLogPath))) { return $null }
    $log = @{ Readers = New-Object Collections.ArrayList }
    $stream = Open-DesktopLogFile
    if ($stream) {
        $stream.Position = $stream.Length
        [void]$log.Readers.Add(@{ Reader = New-Object IO.StreamReader($stream, $Utf8NoBom); Carry = '' })
    }
    return $log
}

function Close-DesktopLog($Log) {
    if ($Log) { foreach ($entry in $Log.Readers) { $entry.Reader.Dispose() } }
}

# Which of the start-up lines the app has written since the last read, and whether its start-up state said its Cookies
# file held a sign-in cookie ($null where no state was read). The app rotates its log by renaming it (at about 10 MB)
# and starting a new one: a file already open is read on through the rename, and once the log's path names a file
# shorter than the newest one read, that file is read from its start as well. Each file is read only where the last
# read stopped, a line split across two reads matched through the tail kept from the first.
function Read-DesktopLog($Log) {
    $newest = if ($Log.Readers.Count -gt 0) { $Log.Readers[$Log.Readers.Count - 1] } else { $null }
    $current = Get-Item -LiteralPath $DesktopLogPath -ErrorAction SilentlyContinue
    if ($current -and ($null -eq $newest -or $current.Length -lt $newest.Reader.BaseStream.Position)) {
        $stream = Open-DesktopLogFile
        if ($stream) { [void]$Log.Readers.Add(@{ Reader = New-Object IO.StreamReader($stream, $Utf8NoBom); Carry = '' }) }
    }
    $seen = @{ Started = $false; SignedOut = $false; CookiePresent = $null }
    foreach ($entry in $Log.Readers) {
        $text = $entry.Carry + $entry.Reader.ReadToEnd()
        if ($text.Contains($DesktopStartedLine)) { $seen.Started = $true }
        foreach ($line in $DesktopSignedOutLines) { if ($text.Contains($line)) { $seen.SignedOut = $true } }
        $state = [regex]::Match($text, $DesktopCookieStatePattern)
        if ($state.Success) { $seen.CookiePresent = ($state.Groups[1].Value -eq 'true') }
        $entry.Carry = $text.Substring([Math]::Max(0, $text.Length - 100))
    }
    return $seen
}

# The started app's word on the login it was given, from its log: Taken once it has started and written no signed-out
# line $SignInSettleSeconds later, Refused as soon as it writes one, otherwise neither, with the Reason no word came;
# CookiePresent, what its start-up state said of a sign-in cookie in its Cookies file, $null where none was read.
# Closes the log.
function Wait-DesktopSignIn($Log) {
    if ($null -eq $Log) {
        $where = if ($DesktopLogPath) { "no log folder of the desktop app at $(Split-Path $DesktopLogPath)" } else { 'no log of the simulated desktop app was given' }
        return @{ Taken = $false; Refused = $false; Reason = $where; CookiePresent = $null }
    }
    try {
        $deadline = [DateTime]::UtcNow.AddSeconds($SignInSeconds)
        $settled = $null
        $cookie = $null
        while ($true) {
            $seen = Read-DesktopLog $Log
            if ($null -eq $cookie) { $cookie = $seen.CookiePresent }
            if ($seen.SignedOut) { return @{ Taken = $false; Refused = $true; Reason = $null; CookiePresent = $cookie } }
            $now = [DateTime]::UtcNow
            if ($null -eq $settled -and $seen.Started) { $settled = $now.AddSeconds($SignInSettleSeconds) }
            if ($null -ne $settled -and $now -ge $settled) { return @{ Taken = $true; Refused = $false; Reason = $null; CookiePresent = $cookie } }
            if ($null -eq $settled -and $now -ge $deadline) {
                return @{ Taken = $false; Refused = $false; Reason = "the desktop app's log said nothing of its sign-in within $SignInSeconds seconds"; CookiePresent = $cookie }
            }
            Start-Sleep -Milliseconds 500
        }
    } finally { Close-DesktopLog $Log }
}

# A time the app's log writes, its local time to the second, as UTC; $null for a text that is not one. Times are
# compared in UTC, so a sign-in just before the clocks go forward is not taken for an hour old; a local time the clocks
# going back repeat is read as its later instance, which can only make a wait longer.
function ConvertFrom-DesktopLogTime([string]$Text) {
    $time = [DateTime]::MinValue
    $style = [Globalization.DateTimeStyles]::AssumeLocal -bor [Globalization.DateTimeStyles]::AdjustToUniversal
    if ([DateTime]::TryParseExact($Text, 'yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture, $style,
            [ref]$time)) { return $time }
    return $null
}

# The text a log file ends with, from a line stamped before $Since (UTC) to its end, read from the end in growing blocks
# so that a long log costs only its tail, a block that starts inside a line read from the next one, the whole file where
# no line is that old. Reaches says its first line is stamped before $Since, so it holds every line written from then
# on; the whole file read without one may be missing some. $null when the file is absent or cannot be read.
function Read-DesktopLogSince([string]$Path, [DateTime]$Since) {
    $stream = $null
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read,
            [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
    } catch { return $null }
    try {
        $block = 256KB
        while ($true) {
            $length = $stream.Length
            $start = [Math]::Max(0, $length - $block)
            $buffer = New-Object byte[] ($length - $start)
            $stream.Position = $start
            $read = 0
            while ($read -lt $buffer.Length) {
                $count = $stream.Read($buffer, $read, $buffer.Length - $read)
                if ($count -le 0) { break }
                $read += $count
            }
            $text = $Utf8NoBom.GetString($buffer, 0, $read)
            if ($start -gt 0) { $text = $text.Substring($text.IndexOf("`n") + 1) }
            $first = [regex]::Match($text, $DesktopLogTimePattern)
            $time = if ($first.Success) { ConvertFrom-DesktopLogTime $first.Groups[1].Value } else { $null }
            $reaches = $null -ne $time -and $time -lt $Since
            if ($reaches -or $start -eq 0) { return @{ Text = $text; Reaches = $reaches } }
            $block *= 4
        }
    } finally { $stream.Dispose() }
}

# The app's log from a line stamped before $Since (UTC) to its end, oldest text first, read back through the files its
# rotations left (main1.log, main2.log ... beside main.log, the higher the older) as far as that line. Reaches says such a
# line was found, so nothing the log wrote from $Since on is missing; where every file kept was read without one, the
# text is what is left. $null when there is no log to read.
function Read-DesktopLogSpan([DateTime]$Since) {
    if (-not $DesktopLogPath) { return $null }
    $folder = Split-Path $DesktopLogPath
    $stem = [IO.Path]::GetFileNameWithoutExtension($DesktopLogPath)
    $extension = [IO.Path]::GetExtension($DesktopLogPath)
    $parts = New-Object Collections.ArrayList
    $path = $DesktopLogPath
    for ($k = 1; $true; $k++) {
        $tail = Read-DesktopLogSince $path $Since
        if ($null -eq $tail) { break }
        $parts.Insert(0, $tail.Text)
        if ($tail.Reaches) { return @{ Text = ($parts -join "`n"); Reaches = $true } }
        $path = Join-Path $folder "$stem$k$extension"
    }
    if ($parts.Count -eq 0) { return $null }
    return @{ Text = ($parts -join "`n"); Reaches = $false }
}

# The time (UTC) of the app's latest sign-in at its sign-in page that its log holds from $Since (UTC) on, or $null.
function Get-DesktopLastSignIn([DateTime]$Since) {
    $span = Read-DesktopLogSpan $Since
    if ($null -eq $span) { return $null }
    $signIn = $DesktopLogTimePattern + '[^\r\n]*' + [regex]::Escape($DesktopSignInLine)
    $latest = $null
    foreach ($match in [regex]::Matches($span.Text, $signIn)) {
        $time = ConvertFrom-DesktopLogTime $match.Groups[1].Value
        if ($null -ne $time -and $time -ge $Since -and ($null -eq $latest -or $time -gt $latest)) { $latest = $time }
    }
    return $latest
}

# When (UTC) the app's Cookies file was last written, or $null where there is none.
function Get-DesktopCookiesWritten {
    if (-not (Test-Path -LiteralPath $DesktopCookiesPath)) { return $null }
    return [IO.File]::GetLastWriteTimeUtc($DesktopCookiesPath)
}

# Waits, before the running app is closed, until a sign-in it made at its sign-in page in the last $CookieSaveSeconds is
# in its Cookies file. The app's cookie store writes the sign-in cookie there only some seconds after the sign-in, and a
# close by this script ends the app before its own quit has written it: a login stored 15 seconds after its sign-in held
# no sign-in cookie, and the app refused it when it was put back (measured on the development machine, 2026-10-26). The
# file holds the cookie once it has been written after the sign-in line's second, a second left for that write to end,
# and at the latest $CookieSaveSeconds after the line. No log, or no sign-in in it in that time, is no wait. The note
# comes before the one that the app is closing, so a run can still be called off while it waits.
function Wait-DesktopSignInSaved {
    if (-not $DesktopLogPath) { return }
    $now = [DateTime]::UtcNow
    $signedIn = Get-DesktopLastSignIn $now.AddSeconds(-$CookieSaveSeconds)
    if ($null -eq $signedIn) { return }
    $at = $signedIn.ToLocalTime().ToString('HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture)
    # A line stamped later than now, as a clock turned back leaves one, waits no longer than a sign-in made now.
    $until = $signedIn.AddSeconds($CookieSaveSeconds)
    if ($until -gt $now.AddSeconds($CookieSaveSeconds)) { $until = $now.AddSeconds($CookieSaveSeconds) }
    $noted = $false
    while ($true) {
        $written = Get-DesktopCookiesWritten
        $now = [DateTime]::UtcNow
        if ($null -ne $written -and $written -ge $signedIn.AddSeconds(1) -and $now -ge $written.AddSeconds(1)) {
            Write-Log "The desktop app's sign-in of $at is in its Cookies file, written at $($written.ToLocalTime().ToString('HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture))."
            return
        }
        if ($now -ge $until) {
            Write-Log "Closing the desktop app $CookieSaveSeconds seconds after its sign-in of $at, by when its Cookies file holds it."
            return
        }
        if (-not $noted) {
            Write-Note "Waiting for the desktop app to save its sign-in of $at before closing it..."
            $noted = $true
        }
        Start-Sleep -Milliseconds 500
    }
}

# Closes the app if it is running, once a sign-in it has just made is in its Cookies file. WasRunning says whether it
# was; Reason, why it could not be closed, and Told, whether it had been told the session ends.
function Close-DesktopApp {
    if (@(Get-DesktopAppProcess).Count -eq 0) { return @{ WasRunning = $false; Reason = $null; Told = $false } }
    Wait-DesktopSignInSaved
    Write-Note 'Closing the desktop app...'
    $refusal = Stop-DesktopApp
    if ($null -eq $refusal) { return @{ WasRunning = $true; Reason = $null; Told = $true } }
    return @{ WasRunning = $true; Reason = $refusal.Reason; Told = $refusal.Told }
}

# Says why a desktop mode stopped at the close, and returns its exit code: refused, no login changed. An app told the
# session ends may be partly closed, its Code sessions ended, so its note does not say nothing changed.
function Write-CloseRefusal($App) {
    if ($App.Told) {
        Write-Note "Refused: $($App.Reason). No login was stored or changed, but the app was told the session ends and may be partly closed; close it yourself, then try again."
    } else {
        Write-Note "Refused: $($App.Reason). Nothing was changed; close the app yourself and try again."
    }
    return 2
}

# ---- The modes --------------------------------------------------------------------------------------------------

# Runs $Action under the act mutex, waiting up to 30 s for another check, and returns its exit code; 2 when another
# check stays busy.
function Invoke-Acting([scriptblock]$Action) {
    $lock = New-Object Threading.Mutex($false, $ActMutexName)
    try {
        if (-not (Enter-Mutex $lock 30000)) {
            Write-Note 'Another account sync is still running; nothing was changed. Try again in a moment.'
            return 2
        }
        try { return (& $Action) } finally { $lock.ReleaseMutex() }
    } finally { $lock.Dispose() }
}

# A desktop of its own with the real app is how a simulated test would close the real app, so the two are only
# given together.
function Assert-DesktopIsolated {
    if ($ScriptParameters.ContainsKey('DesktopConfig') -and -not $ScriptParameters.ContainsKey('DesktopAppDir')) {
        throw 'A -DesktopConfig of its own needs a -DesktopAppDir of its own, so that a simulated desktop never closes the real app.'
    }
}

function Get-TargetAccount {
    if (-not $Account) { throw "-Mode $Mode needs -Account <uuid>." }
    if ($Account -notmatch '^[0-9a-fA-F-]{36}$') { throw "-Account $Account is not an account uuid." }
    return $Account.ToLowerInvariant()
}

# What every desktop mode checks before it touches anything: the exit code to stop with, or $null.
function Test-DesktopModeAllowed {
    if (Test-InsideDesktopApp) {
        Write-Note 'Refused: this script runs inside the desktop app, and closing the app would end it. Run it from a terminal outside the app. Nothing was changed.'
        return 2
    }
    $refusal = Get-DesktopSwitchRefusal
    if ($refusal) { Write-Note "Refused: $refusal Nothing was changed."; return 2 }
    return $null
}

# Stores the login the closed app holds and returns its account, or $null when the app is at its sign-in page: it then
# holds no login, and storing it would replace the account's good one, and clear the one the app refused, with a
# signed-out app. A store that fails starts the app again, if it was running, before the error goes on: the app was
# closed only for this, and nothing of its own was touched.
function Save-DesktopLoginOfClosedApp($App) {
    try {
        $login = Read-DesktopLogin
        if (-not $login.SignedIn) {
            Write-Note "The desktop app is at its sign-in page, so it holds no login of $(Get-AccountName $login.Uuid) to store."
            return $null
        }
        Write-Note "Storing the desktop login of $(Get-AccountName $login.Uuid)..."
        return (Save-DesktopLogin $login)
    } catch {
        Write-Note "Storing the desktop login failed ($($_.Exception.Message)); the app's own login was not touched."
        if ($App.WasRunning) { Start-DesktopApp }
        throw
    }
}

# A switch to the account a signed-out app still names is a switch like any other: only a signed-in app is on it. A
# switch to the account the app is already signed in to records that account all the same: asked for, WindowTally showed
# the app elsewhere, which a change the watcher never saw can leave it doing, and the event puts that right at once. A
# switch starts the app whether or not it was running, so that its log says whether it took the login: one it refuses
# leaves it at its sign-in page, which the switch records at once. A switch that fails starts only an app it closed.
function Switch-DesktopAccount([string]$Target) {
    $stop = Test-DesktopModeAllowed
    if ($null -ne $stop) { return $stop }
    $login = Read-DesktopLogin
    $name = Get-AccountName $Target
    if ($login.Uuid -eq $Target -and $login.SignedIn) {
        Write-AccountEvent 'desktop_account' $Target
        Write-Note "The desktop app is already signed in to $name."
        return 0
    }
    if (-not (Test-DesktopArchive $Target)) {
        Write-Note "No desktop login is stored for $name, so the desktop app cannot be switched to it in one step. Run AddDesktop to store the login the app holds and leave the app at its sign-in page, then sign in to $name there; WindowTally stores that login when you next switch away. Nothing was changed."
        return 3
    }
    $app = Close-DesktopApp
    if ($app.Reason) { return (Write-CloseRefusal $app) }
    Save-DesktopLoginOfClosedApp $app | Out-Null
    $before = $null
    try {
        $before = Read-DesktopFiles
        Restore-DesktopLogin $Target
    } catch {
        # A put-back that fails in turn leaves the app closed, since its files may then be no one login's, and the
        # restore's own error is the one that goes on.
        $failure = $_
        $start = $app.WasRunning
        if ($before) {
            Write-Note "Restoring the desktop login of $name failed ($($failure.Exception.Message)); putting the previous one back."
            try { Write-DesktopFiles $before } catch {
                $start = $false
                Write-Note "Putting the previous desktop login back failed too ($($_.Exception.Message)); the app is left closed."
            }
        } else {
            Write-Note "Restoring the desktop login of $name failed ($($failure.Exception.Message)) before anything was written."
        }
        if ($start) { Start-DesktopApp }
        throw $failure
    }
    Write-AccountEvent 'desktop_account' $Target
    $log = Open-DesktopLog
    Write-Note "Starting the desktop app on $name and watching it sign in..."
    Start-DesktopApp
    $signIn = Wait-DesktopSignIn $log
    if ($signIn.Taken) { Write-Note "Switched the desktop app to $name."; return 0 }
    if ($signIn.Refused) {
        Write-AccountEvent 'desktop_signed_out' $Target
        $problem = Set-DesktopArchiveAside $Target
        $aside = if ($problem) { "It could not be set aside ($problem)." } else { 'It is set aside.' }
        # The restarted app's start-up state tells the two refusals apart; where it was not read, neither is named.
        $why = if ($signIn.CookiePresent -eq $false) {
            ": that login held no sign-in cookie, as it was stored before the app had saved its sign-in."
        } elseif ($signIn.CookiePresent -eq $true) {
            ": that login's web session had ended, as a sign-out in the app ends it."
        } else { '.' }
        Write-Note "Switched the desktop app to $name, but the app refused the login stored for it and is at its sign-in page$why $aside Sign in to $name in the app; WindowTally stores that login when you next switch away."
        return 5
    }
    Write-Note "Switched the desktop app to $name; whether the app took the login could not be confirmed ($($signIn.Reason))."
    return 0
}

function Save-DesktopAccount {
    $stop = Test-DesktopModeAllowed
    if ($null -ne $stop) { return $stop }
    if (-not (Read-DesktopLogin).SignedIn) {
        Write-Note 'Refused: the desktop app is at its sign-in page, so it holds no login to store; sign in there first. Nothing was changed.'
        return 2
    }
    $app = Close-DesktopApp
    if ($app.Reason) { return (Write-CloseRefusal $app) }
    $uuid = Save-DesktopLoginOfClosedApp $app
    if ($app.WasRunning) { Start-DesktopApp }
    if ($null -eq $uuid) {
        Write-Note 'Refused: the desktop app was at its sign-in page once closed, so it held no login to store; it was started again if it was running.'
        return 2
    }
    Write-Note "Stored the desktop login of $(Get-AccountName $uuid)."
    return 0
}

# Makes the closed app's storage read as a signed-out app's, with nothing sent to the server: the sign-in mark set
# false, and the Network\Cookies file removed with its journal. The app looks for its sign-in cookie in that file as it
# starts: a start after a sign-out in the app had reached the file reported sign_in_cookie_present false in its start-up
# state and came up signed out (measured on the development machine, 2026-10-26). So it starts at its sign-in page, and
# the web session of the login it held, stored beforehand, is never ended, as a sign-out in the app would end it; the
# log read after the start says whether it got there. The whole file goes, not the sign-in cookie
# alone: picking one cookie out needs an SQLite engine and the cookie's name, and the account's whole file is in its
# stored login. The mark is written first, so that the storage never reads as a signed-in app's without its cookie;
# should a later step fail, the steps done are undone, the journal written back and the mark set true. A failure starts
# the app again, if it was running, before the error goes on.
function Clear-DesktopSignIn($App) {
    $journal = "$DesktopCookiesPath-journal"
    $journalBytes = $null
    $done = 0
    try {
        if (Test-Path -LiteralPath $journal) { $journalBytes = [IO.File]::ReadAllBytes($journal) }
        Set-DesktopSignedIn $false
        $done = 1
        if ($null -ne $journalBytes) { Remove-Item -LiteralPath $journal -Force }
        $done = 2
        Remove-Item -LiteralPath $DesktopCookiesPath -Force
    } catch {
        $failure = $_
        $state = 'nothing of its storage was changed'
        if ($done -gt 0) {
            try {
                if ($done -gt 1 -and $null -ne $journalBytes) { Write-FileAtomic $journal $journalBytes }
                Set-DesktopSignedIn $true
                $state = 'its storage is as it was'
            } catch { $state = "its storage could not be put back as it was ($($_.Exception.Message))" }
        }
        Write-Note "Leaving the desktop app at its sign-in page failed ($($failure.Exception.Message)); its login was stored, and $state."
        if ($App.WasRunning) { Start-DesktopApp }
        throw $failure
    }
}

# Adds an account without the app's own sign-out, which would end the web session of the login it leaves: with the app
# closed, the login it holds is stored under its account and the storage made to read as signed out
# (Clear-DesktopSignIn); the app is then started whether or not it was running, since its sign-in page is the point,
# and its log read for its word. A signed-out line is the sign-in page reached, recorded at once as desktop_signed_out:
# the window reads WindowTally's figures as soon as the add ends, before the watcher's next look. The start line with none
# after it is an app that came up signed in all the same, an error; no word in time is reported as unconfirmed. Neither
# is recorded: an event the app's word does not back could name the app signed out while it is not, with no change for
# the watcher to see. An app found at its sign-in page once closed has nothing stored and nothing changed. Whether it is
# signed in is read only once it is closed: the mark of a running app may not yet say what the app has just done.
function Add-DesktopAccount {
    $stop = Test-DesktopModeAllowed
    if ($null -ne $stop) { return $stop }
    $then = 'Sign in there to the account to add; WindowTally stores that login when you next switch away from it.'
    $app = Close-DesktopApp
    if ($app.Reason) { return (Write-CloseRefusal $app) }
    $left = Save-DesktopLoginOfClosedApp $app
    if ($null -ne $left) { Clear-DesktopSignIn $app }
    $stored = if ($null -ne $left) { "The login of $(Get-AccountName $left) is stored and still good. " } else { '' }
    $log = Open-DesktopLog
    Write-Note 'Starting the desktop app at its sign-in page...'
    Start-DesktopApp
    $signIn = Wait-DesktopSignIn $log
    if ($signIn.Taken) {
        Write-Note "Error: the desktop app came up signed in, so it could not be left at its sign-in page. $($stored)To add an account, sign out in the app and sign in to it; signing out ends the web session of the login it leaves."
        return 1
    }
    if ($signIn.Refused) {
        $named = $null
        try { $named = (Get-DesktopState).Named } catch { }
        if ($named) { Write-AccountEvent 'desktop_signed_out' $named }
        Write-Note "The desktop app is at its sign-in page. $stored$then"
        return 0
    }
    Write-Note "The desktop app was started at its sign-in page; whether it got there could not be confirmed ($($signIn.Reason)). $stored$then"
    return 0
}

# A simulated desktop's app folder holds no running app, so StartDesktop would start the real one through its Start
# menu entry; an app folder of its own is therefore only given with a launcher of its own.
function Assert-StartIsolated {
    if ($ScriptParameters.ContainsKey('DesktopAppDir') -and -not $ScriptParameters.ContainsKey('DesktopLauncher')) {
        throw 'A -DesktopAppDir of its own needs a -DesktopLauncher of its own, so that a simulated desktop never starts the real app.'
    }
}

# Starts the desktop app where none of its processes runs; an app that runs is left as it is. It runs under the act
# mutex, so it never starts the app while a switch or an add has it closed, and it touches no login: the app starts on
# the account its storage names, or at its sign-in page. That is recorded as a switch records it — desktop_account, or
# desktop_signed_out naming the account the storage still names — so that WindowTally's next pass reads the app as started,
# an event newer than the watcher's view outranking its word that the app is not running; storage it cannot read records
# nothing, and the watcher's next look says it.
function Open-DesktopApp {
    if (@(Get-DesktopAppProcess).Count -gt 0) {
        Write-Note 'The desktop app is already running; nothing was started.'
        return 0
    }
    Write-Note 'Starting the desktop app...'
    Start-DesktopApp
    try {
        $state = Get-DesktopState
        if ($state.Account) { Write-AccountEvent 'desktop_account' $state.Account }
        elseif ($state.SignedOut -and $state.Named) { Write-AccountEvent 'desktop_signed_out' $state.Named }
    } catch { }
    Write-Note 'Started the desktop app.'
    return 0
}

# Changes the CLI's account on its own, for the time the CLI does not follow the desktop app: while it does, the
# next check would undo the switch.
function Switch-CliAccount([string]$Target) {
    if ((Read-SyncSettings).followsDesktop) {
        Write-Note 'Refused: the CLI follows the desktop app, so a switch of the CLI alone would be undone at the next check. Turn off "CLI follows the app" first, or switch the desktop app. Nothing was changed.'
        return 2
    }
    $name = Get-AccountName $Target
    $cli = Resolve-CliSignIn -Record
    if ($cli.Trusted) { Set-TrustedPairing $cli.Live.Uuid }
    if (Test-CliBlocked $cli) { Write-Note "Refused: $($cli.Note)"; return 2 }
    if ($cli.Owner -eq $Target -and -not $cli.SignedOut) {
        if (@(Get-RunningCli).Count -eq 0) { Update-StoredCliAccount $cli }
        Write-Note "The CLI is already signed in to $name."
        return 0
    }
    # Signed out of the account asked for, its stored sign-in is the one that ended, or an older copy: as for an
    # account with none, the window opens a terminal to sign in.
    if ($cli.Owner -eq $Target) { Write-Note "$(Get-SignedOutCondition $Target) Nothing was changed."; return 3 }
    if (@(Get-RunningCli).Count -gt 0) {
        Write-Note "Refused: a CLI is still running, and its sign-in is the only current copy. Close every running claude window, then switch the CLI to $name. Nothing was changed."
        return 4
    }
    if (-not (Test-StoredAccount $Target)) {
        Write-Note "No usable CLI sign-in is stored for $name; sign in with claude auth login first. Nothing was changed."
        return 3
    }
    Save-CliAccount $cli | Out-Null
    Restore-StoredAccount $Target
    Write-Note "Switched the CLI to $name."
    return 0
}

# Dot-sourcing loads the functions without running a mode.
if ($MyInvocation.InvocationName -eq '.') { return }

try {
    switch ($Mode) {
        'Sync' { exit (Invoke-Sync) }
        'Snapshot' { exit (Invoke-Snapshot) }
        'Status' { Show-Status; exit 0 }
        'Watch' { exit (Invoke-Watch) }
        'SwitchDesktop' {
            Assert-DesktopIsolated
            $target = Get-TargetAccount
            exit (Invoke-Acting { Switch-DesktopAccount $target })
        }
        'SnapshotDesktop' {
            Assert-DesktopIsolated
            exit (Invoke-Acting { Save-DesktopAccount })
        }
        'AddDesktop' {
            Assert-DesktopIsolated
            exit (Invoke-Acting { Add-DesktopAccount })
        }
        'StartDesktop' {
            Assert-DesktopIsolated
            Assert-StartIsolated
            exit (Invoke-Acting { Open-DesktopApp })
        }
        'SwitchCli' {
            $target = Get-TargetAccount
            exit (Invoke-Acting { Switch-CliAccount $target })
        }
        'Settings' { Set-SyncSettings; exit 0 }
        'InstallWatcher' { Install-Watcher; exit 0 }
        'UninstallWatcher' { Uninstall-Watcher; exit 0 }
        'Install' { Set-UserPathEntry $true; exit 0 }
        'Uninstall' { Set-UserPathEntry $false; exit 0 }
    }
} catch {
    Write-Note "Error: $($_.Exception.Message)"
    exit 1
}
