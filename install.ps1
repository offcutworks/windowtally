<#
.SYNOPSIS
Installs, removes or reports WindowTally on this machine.

.DESCRIPTION
Install
  1. The account sync. Copies sync\WindowTallySync.ps1 and sync\claude.cmd into %USERPROFILE%\.claude\bin, where
     the sync's logon task and the user PATH already point, after keeping a copy of each file it replaces under
     %USERPROFILE%\.claude\windowtally\backup\<time>\. It then restarts the watcher through the script's own
     UninstallWatcher and InstallWatcher modes: a watcher still running the replaced code holds the watch mutex,
     and only UninstallWatcher stops it. -SkipSync leaves the sync untouched.
  2. The ledger service. Copies the windowtally package to %USERPROFILE%\.claude\windowtally\app — the service
     runs from that copy, so editing this folder never changes the running service — with LICENSE beside it, which
     the About window reads its copyright line from, and, from a release, its THIRD-PARTY-NOTICES.txt and build.json,
     which the About window opens and names the release by. Run with a release's own interpreter, runtime\ beside
     this script, it copies that runtime\ beside the installed packages too, and the installed copy runs under that
     copy: the release's interpreter imports the packages beside its own folder, never the working folder's, so only
     a copy beside the installed packages runs the installed copy, and the unpacked release can then be deleted. An
     interpreter -Python names elsewhere is used where it is; the installed copy's own is refused, since Install
     replaces it. While anything still runs from the installed copy's runtime once the service, the window and the
     browser extension's host are stopped, it names what runs and refuses. It then registers the logon task
     \WindowTally\Service, which runs `pythonw.exe -m windowtally run` there, and starts it.
  3. The window. Copies the windowtally_gui package beside the service's, so the window always runs the service's
     version of WindowTally, and registers the logon task \WindowTally\Window, which runs
     `pythonw.exe -m windowtally_gui --tray` there — the window, started into the tray — then starts it. Its Start
     menu entry is written by the window's own code, in a one-off task (\WindowTally\Setup, removed again once it
     ran): the Start menu lies under AppData, which this script cannot write when it runs inside the desktop app.
     The same run draws the logo into windowtally.ico beside the packages, which the entry shows.
  4. The browser extension's host. Copies extension\ to %USERPROFILE%\.claude\windowtally\extension, which the user
     loads into Chrome once, unpacked (chrome://extensions, Developer mode), to bring chat on claude.ai in a
     browser into WindowTally; the extension is optional, and WindowTally stands whole without it. Then registers its
     native-messaging host in a one-off task, as the Start menu entry is written: the host's manifest and launcher
     in %USERPROFILE%\.claude\windowtally\browser-host, and the one key that names the manifest under
     HKCU\Software\Google\Chrome\NativeMessagingHosts. The host runs under the python.exe beside the installed copy's
     interpreter. It comes before the plugin, whose step stops the script on a machine with no Claude Code CLI.
  5. The desktop plugin. Copies plugin\ (its manifests, hooks and types, not its tests) to
     %USERPROFILE%\.claude\windowtally\plugin and installs it from there at user scope, so every Claude Code
     session, the desktop app's Code tab included, loads it: the copy is added as the marketplace
     windowtally-local, and Claude Code reads a folder marketplace's plugin in place, so a later Install that
     refreshes the copy reaches each session at its next start or /reload-plugins.
  Nothing is written under AppData or the registry by this script itself: run from a terminal inside the Claude
  desktop app, writes there land in the app's private storage, which the logon tasks, Chrome and Windows itself
  cannot see. Every task WindowTally registers, the sync's included, sits in the Task Scheduler folder \WindowTally\.
Uninstall
  Uninstalls the plugin and removes its marketplace and copy; stops the window and removes its task and its Start
  menu entry; removes the browser extension's host, its registry key and the extension's copy (an extension loaded
  in Chrome is removed there by the user); then stops and removes the service's task and the installed copy, the
  service, the window and the runtime copied beside them. The data (ledger, status, history page, readings, the
  user's bills and settings, the window's record) is kept unless -RemoveData. The account sync is left in place; its
  own UninstallWatcher mode removes it, and whichever of the two removes the last task removes the folder. It runs
  under the installed copy's own interpreter where Install copied a release's runtime there, so any release's folder,
  or a source folder, uninstalls it; otherwise, like Install, it refuses before it changes anything when -Python names
  no interpreter: the Start menu entry and the host are removed by the installed copy's own code, run under it.
Status
  The three tasks and their priority, the plugin's installation, the browser extension's host, whether each installed
  copy (the licence's, a release's notices, build record and runtime included) matches this folder, whether the
  Start menu entry exists, and the standing the service last wrote. A copy that differs from this folder
  only in line endings matches: Git's core.autocrlf rewrites a checkout's LF as CRLF, and either runs the same.

.PARAMETER Python
The interpreter the service and the window run under (pythonw.exe: no console window). The default is the one a
release carries, runtime\pythonw.exe beside this script, which Install copies beside the installed packages; a source
folder carries none, so Install from one needs -Python, which the installed copy then runs under where it is. Status
shows the service's standing only through the python.exe beside the installed copy's interpreter. The service needs
only the standard library of Python 3.11 or later; the window needs PySide6 as well (PySide6-Essentials is enough),
which a release's own interpreter carries; Install refuses, before it changes anything, any other interpreter that
cannot import it.

.PARAMETER Claude
The Claude Code CLI that installs and lists the plugin. The default is the native install's executable, called
directly rather than through the account sync's claude.cmd, which would run a sync first.
#>
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Uninstall', 'Status')]
    [string]$Mode = 'Status',
    [string]$Python,
    [string]$Claude = (Join-Path $env:USERPROFILE '.local\bin\claude.exe'),
    [switch]$SkipSync,
    [switch]$RemoveData
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$Source = $PSScriptRoot
# The default is taken here, not in param(): Windows PowerShell 5.1 leaves $PSScriptRoot empty while an advanced
# script's parameters bind.
$RuntimeFolder = 'runtime'
if (-not $Python) { $Python = Join-Path $Source "$RuntimeFolder\pythonw.exe" }
$BinDir = Join-Path $env:USERPROFILE '.claude\bin'
$SyncFiles = @('WindowTallySync.ps1', 'claude.cmd')
$DataDir = Join-Path $env:USERPROFILE '.claude\windowtally'
$AppDir = Join-Path $DataDir 'app'
$Packages = @('windowtally', 'windowtally_gui')
# The files the installed copy keeps beside its packages: the licence the About window reads its copyright line from,
# and a release's third-party notices and build record (windowtally\release.py), which it opens and names the release
# by.
$BesidePackages = @('LICENSE', 'THIRD-PARTY-NOTICES.txt', 'build.json')
# Every task sits in one Task Scheduler folder, where a person finds them together; the plugin runs the window's by
# its qualified name (plugin\hooks\window.ts) and the sync names its own (sync\WindowTallySync.ps1).
$TaskPath = '\WindowTally\'
$ServiceTask = 'Service'
$WindowTask = 'Window'
$SetupTask = 'Setup'
$SyncTask = 'Sync'
# Task Scheduler cannot make the folder while a task at its root bears the folder's name in any case (measured on the
# development machine, 2026-11-03: the folder's first task is refused as a path not found), so Install refuses first.
if ($Mode -eq 'Install') {
    $blocking = Get-ScheduledTask -TaskPath '\' -TaskName $TaskPath.Trim('\') -ErrorAction SilentlyContinue
    if ($blocking) {
        throw "The task \$($blocking.TaskName) at Task Scheduler's root stands where the folder $TaskPath goes; remove it first."
    }
}
# The service's and the window's task priority: 5 starts them in the normal priority class, beside the programs the
# user starts. Task Scheduler's default, 7, ran them below normal, at low I/O priority and memory priority 2 (measured
# on the development machine, 2026-10-23), the first to lose their cached pages when memory runs short.
$TaskPriority = 5
$PluginDir = Join-Path $DataDir 'plugin'
$PluginParts = @('.claude-plugin', 'hooks', 'types')
$PluginName = 'windowtally'
$Marketplace = 'windowtally-local'
$ExtensionDir = Join-Path $DataDir 'extension'
# The host's registration, as windowtally\browser_host.py writes it.
$BrowserKey = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\windowtally.browser'
$HostManifest = Join-Path $DataDir 'browser-host\windowtally.browser.json'

function Get-FileDigest([string]$Path) {
    # Line endings do not count: Git's core.autocrlf rewrites a checkout's LF as CRLF, and either runs the same.
    # Latin-1 maps every byte to one character and back, so only the CR before each LF is dropped.
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $latin1 = [System.Text.Encoding]::GetEncoding(28591)
    $text = $latin1.GetString([System.IO.File]::ReadAllBytes($Path)).Replace("`r`n", "`n")
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return [System.BitConverter]::ToString($sha.ComputeHash($latin1.GetBytes($text))) } finally { $sha.Dispose() }
}

function Get-DifferingFiles([string]$From, [string]$To, [string[]]$Parts) {
    # The files under $From's parts whose copy under $To is missing or differs, as relative paths.
    $differing = @()
    foreach ($part in $Parts) {
        $root = Join-Path $From $part
        if (-not (Test-Path -LiteralPath $root)) { continue }
        foreach ($file in Get-ChildItem -LiteralPath $root -Recurse -File -Force) {
            $relative = $file.FullName.Substring($From.TrimEnd('\').Length + 1)
            if ((Get-FileDigest $file.FullName) -ne (Get-FileDigest (Join-Path $To $relative))) { $differing += $relative }
        }
    }
    return $differing
}

function Invoke-Claude([string[]]$Arguments) {
    # Runs the CLI, its standard output returned as one string; a failure stops the script.
    $output = & $Claude @Arguments
    if ($LASTEXITCODE -ne 0) { throw "claude $($Arguments -join ' ') exited with $LASTEXITCODE" }
    return ($output -join "`n")
}

function Get-PluginEntry {
    # The plugin's installed entry as `claude plugin list` reports it, or $null.
    $list = Invoke-Claude @('plugin', 'list', '--json') | ConvertFrom-Json
    return $list | Where-Object { $_.id -eq "$PluginName@$Marketplace" } | Select-Object -First 1
}

function Get-MarketplaceEntry {
    # The marketplace's entry as `claude plugin marketplace list` reports it, or $null.
    $list = Invoke-Claude @('plugin', 'marketplace', 'list', '--json') | ConvertFrom-Json
    return $list | Where-Object { $_.name -eq $Marketplace } | Select-Object -First 1
}

function Get-EntryFolder($Entry, [string[]]$Names) {
    # The first of the named properties an entry carries: the CLI lists different fields for different sources.
    foreach ($name in $Names) {
        $property = $Entry.PSObject.Properties[$name]
        if ($property -and $property.Value) { return [string]$property.Value }
    }
    return $null
}

function Test-SameFolder([string]$A, [string]$B) {
    if (-not $A -or -not $B) { return $false }
    return [System.IO.Path]::GetFullPath($A).TrimEnd('\', '/') -ieq [System.IO.Path]::GetFullPath($B).TrimEnd('\', '/')
}

function Test-ReleaseInterpreter {
    # Whether -Python is a release's own interpreter, in runtime\ beside this script.
    return Test-SameFolder (Split-Path -Parent $Python) (Join-Path $Source $RuntimeFolder)
}

function Test-WindowToolkit {
    # Whether -Python imports what the window is drawn with, PySide6's QtCore, QtGui and QtWidgets: asked of it in a
    # process of its own, waited for, since pythonw.exe has no console to wait on. -E and -P keep the PYTHON* variables
    # and the working folder out of the answer, which this shell may have and the logon task's start need not: PySide6
    # must be in the interpreter's own site-packages or the user's. A release's own interpreter carries it and is not
    # asked.
    if (Test-ReleaseInterpreter) { return $true }
    $import = '"from PySide6 import QtCore, QtGui, QtWidgets"'
    $probe = Start-Process -FilePath $Python -ArgumentList '-E', '-P', '-c', $import -WindowStyle Hidden -Wait -PassThru
    return $probe.ExitCode -eq 0
}

function Get-InstalledPython {
    # The interpreter the installed copy runs under: the copy of a release's runtime\ beside its packages, where Install
    # put one there, and the one -Python names otherwise.
    $installed = Join-Path (Join-Path $AppDir $RuntimeFolder) (Split-Path -Leaf $Python)
    if (Test-Path -LiteralPath $installed) { return $installed }
    return $Python
}

function Get-ConsolePython {
    # The console interpreter beside the installed copy's: the browser extension's host runs under it, and Status reads
    # the service's standing through it.
    return Join-Path (Split-Path -Parent (Get-InstalledPython)) 'python.exe'
}

function Wait-InstalledRuntime {
    # Whatever runs from the installed copy's runtime\ holds its libraries open, which could then be neither replaced
    # nor removed. The service, the window and the browser extension's host are stopped first, and Windows lets go of a
    # stopped process within moments; anything still running after that — a command the user started under the
    # installed copy's Python, say — is named, and the script refuses rather than end it.
    $runtime = (Join-Path $AppDir $RuntimeFolder) + '\'
    $deadline = (Get-Date).AddSeconds(10)
    while ($true) {
        $running = @(Get-CimInstance Win32_Process | Where-Object {
            $_.ExecutablePath -and $_.ExecutablePath.StartsWith($runtime, [StringComparison]::OrdinalIgnoreCase)
        })
        if (-not $running.Count) { return }
        if ((Get-Date) -ge $deadline) { break }
        Start-Sleep -Milliseconds 500
    }
    $names = ($running | ForEach-Object { "$($_.Name) ($($_.ProcessId))" }) -join ', '
    throw "Still running under the installed copy's Python: $names. End it, then run again."
}

function Copy-InstalledCopy {
    # The packages, the files beside them and, from a release, its runtime\, copied into the installed copy.
    Wait-InstalledRuntime
    foreach ($name in $Packages) {
        $package = Join-Path $AppDir $name
        if (Test-Path -LiteralPath $package) { Remove-Item -LiteralPath $package -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $package | Out-Null
        Copy-Item -Path (Join-Path $Source "$name\*.py") -Destination $package
    }
    # A file this folder does not ship is removed, so a copy installed from source names no release.
    foreach ($name in $BesidePackages) {
        $from = Join-Path $Source $name
        $to = Join-Path $AppDir $name
        if (Test-Path -LiteralPath $from) { Copy-Item -LiteralPath $from -Destination $to -Force }
        elseif (Test-Path -LiteralPath $to) { Remove-Item -LiteralPath $to -Force }
    }
    # A release's interpreter imports the packages beside its own folder and never the working folder's (measured on the
    # development machine with a release's CPython 3.14.8 and its path file, 2026-11-03), so it runs the installed copy
    # only as a copy beside the installed packages. Any other interpreter runs the installed copy from the working
    # folder its tasks start in, so a runtime\ an earlier release left there is removed.
    $runtime = Join-Path $AppDir $RuntimeFolder
    if (Test-Path -LiteralPath $runtime) { Remove-Item -LiteralPath $runtime -Recurse -Force }
    if (Test-ReleaseInterpreter) {
        Copy-Item -LiteralPath (Join-Path $Source $RuntimeFolder) -Destination $runtime -Recurse
    }
}

function Install-Sync {
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    $backup = Join-Path $DataDir ('backup\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    foreach ($name in $SyncFiles) {
        $target = Join-Path $BinDir $name
        $new = Join-Path $Source "sync\$name"
        if ((Get-FileDigest $target) -and (Get-FileDigest $target) -ne (Get-FileDigest $new)) {
            New-Item -ItemType Directory -Force -Path $backup | Out-Null
            Copy-Item -LiteralPath $target -Destination (Join-Path $backup $name)
            Write-Host "Kept the replaced $name in $backup"
        }
        # Windows keeps a file's own spelling when it is written over under another case, so a file spelt otherwise
        # is removed first and the copy takes this name's spelling.
        Get-ChildItem -LiteralPath $BinDir -File | Where-Object { $_.Name -ieq $name -and $_.Name -cne $name } |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
        Copy-Item -LiteralPath $new -Destination $target -Force
    }
    $script = Join-Path $BinDir 'WindowTallySync.ps1'
    $ps = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    foreach ($syncMode in 'UninstallWatcher', 'InstallWatcher') {
        & $ps -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script -Mode $syncMode
        if ($LASTEXITCODE -ne 0) { throw "WindowTallySync.ps1 -Mode $syncMode exited with $LASTEXITCODE" }
    }
    Write-Host "The account sync in $BinDir is current and its watcher restarted."
}

function Stop-LedgerService {
    if (Get-ScheduledTask -TaskPath $TaskPath -TaskName $ServiceTask -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskPath $TaskPath -TaskName $ServiceTask -ErrorAction SilentlyContinue
    }
    # A service started by hand, or one the task's stop left behind.
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" | Where-Object {
        $_.CommandLine -and $_.CommandLine -match '-m\s+windowtally\s+run\b'
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Stop-Window {
    if (Get-ScheduledTask -TaskPath $TaskPath -TaskName $WindowTask -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskPath $TaskPath -TaskName $WindowTask -ErrorAction SilentlyContinue
    }
    # A window started by hand, from the Start menu or a terminal.
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" | Where-Object {
        $_.CommandLine -and $_.CommandLine -match '-m\s+windowtally_gui\b'
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Stop-BrowserHost {
    # The browser extension's host, which Chrome starts for each message the extension sends: one still running holds
    # the installed copy's runtime open, which could then be neither replaced nor removed.
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
        $_.CommandLine -and $_.CommandLine -match '-m\s+windowtally\.browser_host\b'
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Get-ShortcutPath {
    # Where the window's own code writes the Start menu entry (windowtally_gui\shortcut.py).
    return Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\WindowTally.lnk'
}

function Invoke-OutsideApp([string]$Arguments, [string]$What) {
    # Runs the installed copy's code once from a task of its own and waits for it. A process the Task Scheduler starts
    # writes under AppData and the registry where Windows and Chrome read them; this script, run from a terminal inside
    # the Claude desktop app, would write into the app's private storage instead.
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute (Get-InstalledPython) -Argument $Arguments -WorkingDirectory $AppDir
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
    $task = New-ScheduledTask -Action $action -Principal $principal -Settings $settings `
        -Description 'WindowTally: a one-off step of install.ps1, removed once it ran.'
    Register-ScheduledTask -TaskPath $TaskPath -TaskName $SetupTask -InputObject $task -Force | Out-Null
    try {
        Start-ScheduledTask -TaskPath $TaskPath -TaskName $SetupTask
        $deadline = (Get-Date).AddSeconds(90)
        do {
            Start-Sleep -Milliseconds 500
            $state = (Get-ScheduledTask -TaskPath $TaskPath -TaskName $SetupTask).State
            $result = (Get-ScheduledTaskInfo -TaskPath $TaskPath -TaskName $SetupTask).LastTaskResult
            # 267011 (0x41303): not run yet; 267009 (0x41301): running.
        } while (($state -eq 'Running' -or $result -eq 267011 -or $result -eq 267009) -and (Get-Date) -lt $deadline)
        if ($state -eq 'Running' -or $result -eq 267011 -or $result -eq 267009) { throw "$What did not finish within 90 s." }
        if ($result -ne 0) { throw "$What failed: its task ended with $result." }
    } finally {
        Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $SetupTask -Confirm:$false -ErrorAction SilentlyContinue
    }
}

function Install-App {
    Stop-LedgerService
    Stop-Window
    Stop-BrowserHost
    Copy-InstalledCopy
    $python = Get-InstalledPython
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute $python -Argument '-m windowtally run' -WorkingDirectory $AppDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -Priority $TaskPriority
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
        -Description 'WindowTally: keeps the per-account usage ledger and status.json current (python -m windowtally run).'
    Register-ScheduledTask -TaskPath $TaskPath -TaskName $ServiceTask -InputObject $task -Force | Out-Null
    Start-ScheduledTask -TaskPath $TaskPath -TaskName $ServiceTask
    Write-Host "Registered and started the logon task $TaskPath$ServiceTask; it runs $AppDir with $python."
}

function Install-Window {
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute (Get-InstalledPython) -Argument '-m windowtally_gui --tray' `
        -WorkingDirectory $AppDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -Priority $TaskPriority
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
        -Description 'WindowTally: the window, started into the tray at logon (python -m windowtally_gui --tray).'
    Register-ScheduledTask -TaskPath $TaskPath -TaskName $WindowTask -InputObject $task -Force | Out-Null
    Invoke-OutsideApp '-m windowtally_gui --shortcut create' 'Writing the Start menu entry'
    Start-ScheduledTask -TaskPath $TaskPath -TaskName $WindowTask
    Write-Host "Registered and started the logon task $TaskPath$WindowTask (the window, in the tray); its Start menu entry is $(Get-ShortcutPath)."
}

# Each removal below says what it did, and a step that failed says so in its warning and is never reported done.
function Uninstall-Window {
    Stop-Window
    $entryRemoved = $false
    if (Test-Path -LiteralPath (Join-Path $AppDir 'windowtally_gui')) {
        try {
            Invoke-OutsideApp '-m windowtally_gui --shortcut remove' 'Removing the Start menu entry'
            $entryRemoved = $true
        } catch { Write-Warning "$($_.Exception.Message) The Start menu entry, if there is one, was left." }
    } elseif (Test-Path -LiteralPath (Get-ShortcutPath)) {
        Write-Warning "No installed WindowTally to remove the Start menu entry with, so $(Get-ShortcutPath) was left."
    }
    if (Get-ScheduledTask -TaskPath $TaskPath -TaskName $WindowTask -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $WindowTask -Confirm:$false
    }
    Write-Host "Removed the task $TaskPath$WindowTask$(if ($entryRemoved) { " and the window's Start menu entry" })."
}

function Install-BrowserHost {
    # The extension's ID is fixed by the public key in its manifest, so a refreshed copy keeps the ID the host allows.
    if (Test-Path -LiteralPath $ExtensionDir) { Remove-Item -LiteralPath $ExtensionDir -Recurse -Force }
    Copy-Item -LiteralPath (Join-Path $Source 'extension') -Destination $ExtensionDir -Recurse
    $console = Get-ConsolePython
    if (-not (Test-Path -LiteralPath $console)) {
        Write-Warning "The browser extension's host was not registered: it runs under python.exe, and there is none at $console."
        return
    }
    Invoke-OutsideApp "-m windowtally browser register --python `"$console`"" "Registering the browser extension's host"
    Write-Host "Registered the browser extension's host with Chrome. To bring chat on claude.ai into WindowTally, load $ExtensionDir unpacked in chrome://extensions (Developer mode)."
}

function Uninstall-BrowserHost {
    $hostRemoved = $false
    if (Test-Path -LiteralPath (Join-Path $AppDir 'windowtally')) {
        try {
            Invoke-OutsideApp '-m windowtally browser unregister' "Removing the browser extension's host"
            $hostRemoved = $true
        } catch { Write-Warning "$($_.Exception.Message) The browser extension's host, if it is registered, was left." }
    } elseif (Test-Path -LiteralPath $BrowserKey) {
        Write-Warning "No installed WindowTally to remove the browser extension's host with, so its key $BrowserKey was left."
    }
    if (Test-Path -LiteralPath $ExtensionDir) { Remove-Item -LiteralPath $ExtensionDir -Recurse -Force }
    $removed = if ($hostRemoved) { "the browser extension's host and the extension's copy" } else { "the extension's copy" }
    Write-Host "Removed $removed; an extension loaded in Chrome is removed there."
}

function Get-BrowserHostText {
    # Read from inside the desktop app, the registry may show the app's private view rather than the one Chrome reads.
    if (-not (Test-Path -LiteralPath $BrowserKey)) { return 'not registered' }
    $manifest = (Get-Item -LiteralPath $BrowserKey).GetValue('')
    if (-not (Test-SameFolder $manifest $HostManifest)) { return "registered to $manifest, NOT WindowTally's host" }
    if (-not (Test-Path -LiteralPath $HostManifest)) { return "registered, but its manifest $HostManifest is MISSING" }
    return 'registered'
}

function Install-Plugin {
    if (-not (Test-Path -LiteralPath $Claude)) { throw "No Claude Code CLI at $Claude; pass -Claude." }
    if (Test-Path -LiteralPath $PluginDir) { Remove-Item -LiteralPath $PluginDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $PluginDir | Out-Null
    foreach ($part in $PluginParts) {
        Copy-Item -LiteralPath (Join-Path $Source "plugin\$part") -Destination $PluginDir -Recurse
    }
    # A marketplace of this name added from another folder (a working copy, say) would keep every session on that
    # folder, and a client that serves the plugin from its own cached copy keeps the old one until it is installed
    # again: either is taken down and installed afresh from WindowTally's copy.
    $market = Get-MarketplaceEntry
    if ($market -and -not (Test-SameFolder (Get-EntryFolder $market @('path', 'installLocation')) $PluginDir)) {
        if (Get-PluginEntry) { Invoke-Claude @('plugin', 'uninstall', "$PluginName@$Marketplace", '--scope', 'user') | Out-Null }
        Invoke-Claude @('plugin', 'marketplace', 'remove', $Marketplace, '--scope', 'user') | Out-Null
        $market = $null
    }
    if (-not $market) { Invoke-Claude @('plugin', 'marketplace', 'add', $PluginDir, '--scope', 'user') | Out-Null }
    $entry = Get-PluginEntry
    if ($entry -and -not (Test-SameFolder (Get-EntryFolder $entry @('readFromFolder')) $PluginDir)) {
        Invoke-Claude @('plugin', 'uninstall', "$PluginName@$Marketplace", '--scope', 'user') | Out-Null
        $entry = $null
    }
    if (-not $entry) { Invoke-Claude @('plugin', 'install', "$PluginName@$Marketplace", '--scope', 'user') | Out-Null }
    $entry = Get-PluginEntry
    if (-not $entry -or -not $entry.enabled) { throw "The plugin $PluginName@$Marketplace is not installed and enabled after the install." }
    Write-Host "Installed the plugin $PluginName at user scope from $PluginDir; each Claude Code session loads it at its next start or /reload-plugins."
}

function Uninstall-Plugin {
    if (Test-Path -LiteralPath $Claude) {
        if (Get-PluginEntry) { Invoke-Claude @('plugin', 'uninstall', "$PluginName@$Marketplace", '--scope', 'user') | Out-Null }
        if (Get-MarketplaceEntry) { Invoke-Claude @('plugin', 'marketplace', 'remove', $Marketplace, '--scope', 'user') | Out-Null }
    } else {
        Write-Warning "No Claude Code CLI at $Claude, so the plugin's user-scope entry, if any, was left; pass -Claude."
    }
    if (Test-Path -LiteralPath $PluginDir) { Remove-Item -LiteralPath $PluginDir -Recurse -Force }
    Write-Host "Removed the plugin $PluginName and its copy."
}

function Uninstall-App {
    Stop-LedgerService
    Stop-BrowserHost
    Wait-InstalledRuntime
    if (Get-ScheduledTask -TaskPath $TaskPath -TaskName $ServiceTask -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $ServiceTask -Confirm:$false
    }
    Remove-EmptyTaskFolder
    if (Test-Path -LiteralPath $AppDir) { Remove-Item -LiteralPath $AppDir -Recurse -Force }
    if ($RemoveData -and (Test-Path -LiteralPath $DataDir)) { Remove-Item -LiteralPath $DataDir -Recurse -Force }
    Write-Host "Removed the task $TaskPath$ServiceTask and the installed copy$(if ($RemoveData) { ' and the data' } else { '; the data is kept' })."
}

# Task Scheduler keeps a folder once its last task is gone. The sync's UninstallWatcher removes its own task, so
# whichever of the two removes the last one removes the folder, and the same check stands in both: each script is
# installed and run on its own, so neither can call the other's. An empty folder is no registration that runs, so a
# failure to remove it is a warning and never stops the uninstall.
function Remove-EmptyTaskFolder {
    try {
        $service = New-Object -ComObject Schedule.Service
        $service.Connect()
        try { $folder = $service.GetFolder($TaskPath.TrimEnd('\')) } catch { return }
        if ($folder.GetTasks(1).Count -eq 0 -and $folder.GetFolders(0).Count -eq 0) {
            $service.GetFolder('\').DeleteFolder($folder.Name, 0)
        }
    } catch {
        Write-Warning "The Task Scheduler folder $TaskPath was left: $($_.Exception.Message)"
    }
}

function Get-PackageCopy([string]$Package) {
    # Whether the installed copy of a package matches this folder's.
    if (-not (Test-Path -LiteralPath (Join-Path $AppDir $Package))) { return 'not installed' }
    $stale = @(Get-ChildItem -Path (Join-Path $Source "$Package\*.py") | Where-Object {
        (Get-FileDigest $_.FullName) -ne (Get-FileDigest (Join-Path $AppDir "$Package\$($_.Name)"))
    })
    if ($stale.Count) { return "DIFFERS ($($stale.Name -join ', '))" }
    return 'matches'
}

function Get-BesideCopy([string]$Name) {
    # Whether the installed copy of a file beside the packages matches this folder's.
    $installed = Join-Path $AppDir $Name
    if (-not (Test-Path -LiteralPath $installed)) { return 'not installed' }
    if (-not (Test-Path -LiteralPath (Join-Path $Source $Name))) { return 'installed; this folder ships none' }
    if ((Get-FileDigest $installed) -ne (Get-FileDigest (Join-Path $Source $Name))) { return 'DIFFERS' }
    return 'matches'
}

function Get-FolderHashes([string]$Folder) {
    # Every file under $Folder by its relative path (a hashtable's keys ignore case, as Windows' file names do), with
    # the SHA-256 of its bytes.
    $hashes = @{}
    foreach ($file in Get-ChildItem -LiteralPath $Folder -Recurse -File -Force) {
        $relative = $file.FullName.Substring($Folder.TrimEnd('\').Length + 1)
        $hashes[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    }
    return $hashes
}

function Get-RuntimeCopy {
    # Whether the installed copy's runtime matches the one this folder carries, file for file and byte for byte — a
    # program's files, whose line endings are their own: none where the installed copy runs under an interpreter
    # -Python named, installed where this folder carries none.
    $installed = Join-Path $AppDir $RuntimeFolder
    $carried = Join-Path $Source $RuntimeFolder
    if (-not (Test-Path -LiteralPath $installed)) {
        return 'none: the installed copy runs under the interpreter Install was given'
    }
    if (-not (Test-Path -LiteralPath $carried)) { return 'installed; this folder carries none' }
    $ours = Get-FolderHashes $carried
    $theirs = Get-FolderHashes $installed
    $differing = @(@($ours.Keys) + @($theirs.Keys) | Sort-Object -Unique | Where-Object { $ours[$_] -ne $theirs[$_] })
    if ($differing.Count) { return "DIFFERS ($($differing.Count) files)" }
    return 'matches'
}

function Show-Status {
    foreach ($name in $SyncTask, $ServiceTask, $WindowTask) {
        $task = Get-ScheduledTask -TaskPath $TaskPath -TaskName $name -ErrorAction SilentlyContinue
        $text = if ($task) {
            "$($task.State); last result $((Get-ScheduledTaskInfo -TaskPath $TaskPath -TaskName $name).LastTaskResult); priority $($task.Settings.Priority)"
        } else { 'not registered' }
        Write-Host ("{0,-25}: {1}" -f "Task $TaskPath$name", $text)
    }
    foreach ($name in $SyncFiles) {
        $same = (Get-FileDigest (Join-Path $BinDir $name)) -eq (Get-FileDigest (Join-Path $Source "sync\$name"))
        Write-Host ("{0,-25}: {1}" -f $name, $(if ($same) { 'installed copy matches' } else { 'installed copy DIFFERS' }))
    }
    Write-Host ("{0,-25}: {1}" -f 'Service copy', (Get-PackageCopy 'windowtally'))
    Write-Host ("{0,-25}: {1}" -f 'Window copy', (Get-PackageCopy 'windowtally_gui'))
    Write-Host ("{0,-25}: {1}" -f 'Licence copy', (Get-BesideCopy 'LICENSE'))
    Write-Host ("{0,-25}: {1}" -f 'Notices copy', (Get-BesideCopy 'THIRD-PARTY-NOTICES.txt'))
    Write-Host ("{0,-25}: {1}" -f 'Build record copy', (Get-BesideCopy 'build.json'))
    Write-Host ("{0,-25}: {1}" -f 'Runtime copy', (Get-RuntimeCopy))
    # Read from inside the desktop app, AppData may show the app's private view rather than the folder Windows reads.
    $entry = if (Test-Path -LiteralPath (Get-ShortcutPath)) { 'present' } else { 'absent' }
    Write-Host ("{0,-25}: {1}" -f 'Start menu entry', $entry)
    $pluginText = if (-not (Test-Path -LiteralPath $Claude)) { "unknown: no Claude Code CLI at $Claude" } else {
        try {
            $entry = Get-PluginEntry
            if (-not $entry) { 'not installed' } else {
                $state = if ($entry.enabled) { 'enabled' } else { 'DISABLED' }
                $folder = Get-EntryFolder $entry @('readFromFolder')
                $from = if (Test-SameFolder $folder $PluginDir) { 'read from the installed copy' }
                        elseif ($folder) { "read from $folder, NOT the installed copy" }
                        else { 'served from its install cache, NOT the installed copy' }
                "installed at $($entry.scope) scope, $state, $from"
            }
        } catch {
            "unknown: $($_.Exception.Message)"
        }
    }
    Write-Host ("{0,-25}: {1}" -f "Plugin $PluginName", $pluginText)
    $differing = @(Get-DifferingFiles (Join-Path $Source 'plugin') $PluginDir $PluginParts)
    $pluginCopy = if (-not (Test-Path -LiteralPath $PluginDir)) { 'not installed' }
                  elseif ($differing.Count) { "DIFFERS ($($differing -join ', '))" } else { 'matches' }
    Write-Host ("{0,-25}: {1}" -f 'Plugin copy', $pluginCopy)
    Write-Host ("{0,-25}: {1}" -f 'Browser host', (Get-BrowserHostText))
    $differing = @(Get-DifferingFiles $Source $DataDir @('extension'))
    $extensionCopy = if (-not (Test-Path -LiteralPath $ExtensionDir)) { 'not installed' }
                     elseif ($differing.Count) { "DIFFERS ($($differing -join ', '))" } else { 'matches' }
    Write-Host ("{0,-25}: {1}" -f 'Extension copy', $extensionCopy)
    if (-not (Test-Path -LiteralPath $AppDir)) { return }
    $console = Get-ConsolePython
    if (-not (Test-Path -LiteralPath $console)) {
        # The installed copy's own runtime is used whatever -Python names, so only installing again repairs it.
        $ownRuntime = Test-SameFolder (Split-Path -Parent $console) (Join-Path $AppDir $RuntimeFolder)
        $remedy = if ($ownRuntime) { 'install again' } else { 'pass -Python' }
        Write-Host ("{0,-25}: {1}" -f 'Standing', "not shown: no interpreter at $console; $remedy")
        return
    }
    Push-Location $AppDir
    try { & $console -m windowtally status } finally { Pop-Location }
}

function Assert-Interpreter {
    # Install and Uninstall refuse before they change anything: Install replaces the sync and restarts its watcher, and
    # Uninstall removes the Start menu entry and the browser extension's host by running the installed copy's code under
    # its interpreter, before it deletes that copy; without one both would be left behind for good. Install refuses the
    # installed copy's own Python as -Python too: it replaces that runtime, the interpreter with it. And it refuses an
    # interpreter the window cannot start under, which would leave a logon task that never opens a window.
    if ($Mode -eq 'Status') { return }
    $interpreter = if ($Mode -eq 'Install') { $Python } else { Get-InstalledPython }
    if (-not (Test-Path -LiteralPath $interpreter)) { throw "No interpreter at $interpreter; pass -Python." }
    if ($Mode -ne 'Install') { return }
    if (Test-SameFolder (Split-Path -Parent $Python) (Join-Path $AppDir $RuntimeFolder)) {
        throw ("$Python is the installed copy's own Python, which Install replaces; pass a release's or another " +
               "interpreter.")
    }
    if (-not (Test-WindowToolkit)) {
        throw ("$Python cannot import PySide6, which the window is drawn with: install PySide6-Essentials into it " +
               "(python -m pip install PySide6-Essentials, run with the python.exe beside it), or pass an " +
               "interpreter that holds it.")
    }
}

Assert-Interpreter
switch ($Mode) {
    'Install' { if (-not $SkipSync) { Install-Sync }; Install-App; Install-Window; Install-BrowserHost; Install-Plugin }
    'Uninstall' { Uninstall-Plugin; Uninstall-Window; Uninstall-BrowserHost; Uninstall-App }
    'Status' { Show-Status }
}
