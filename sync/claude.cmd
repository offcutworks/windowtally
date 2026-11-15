@echo off
rem Launches the Claude Code CLI signed in to the same account as the Claude desktop app.
rem `claude auth ...` passes straight through and then stores whatever sign-in it produced.
setlocal
set "CLAUDE_CLI=%USERPROFILE%\.local\bin\claude.exe"
set "ACCOUNT_SYNC=powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0WindowTallySync.ps1""

if /i "%~1"=="auth" goto auth

%ACCOUNT_SYNC% -Mode Sync
if errorlevel 1 exit /b %errorlevel%
"%CLAUDE_CLI%" %*
exit /b %errorlevel%

:auth
"%CLAUDE_CLI%" %*
set "CLI_EXIT=%errorlevel%"
rem A `claude auth login` that succeeded is a sign-in seen happen, so the sync takes the label it left.
set "SIGNED_IN="
if /i "%~2"=="login" if "%CLI_EXIT%"=="0" set "SIGNED_IN=-SignedIn"
%ACCOUNT_SYNC% -Mode Snapshot %SIGNED_IN%
exit /b %CLI_EXIT%
