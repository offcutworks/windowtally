"""Every location WindowTally reads or writes, derived from three roots so a test can relocate all of them."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DATA_FOLDER_NAME = "windowtally"


@dataclass(frozen=True)
class MachinePaths:
    """The three roots; every other path is a property derived from one of them."""

    claude_home: Path   # Claude Code's configuration folder (~/.claude)
    desktop_data: Path  # the Claude desktop app's data folder (%APPDATA%/Claude)
    data_dir: Path      # WindowTally's own folder (~/.claude/windowtally)

    # --- sources, read only -------------------------------------------------------------------------------

    @property
    def projects_dir(self) -> Path:
        return self.claude_home / "projects"

    @property
    def accounts_dir(self) -> Path:
        """The account sync's store: one folder per account, plus its log, events and watcher view."""
        return self.claude_home / "accounts"

    @property
    def sync_events(self) -> Path:
        return self.accounts_dir / "events.jsonl"

    @property
    def sync_log(self) -> Path:
        return self.accounts_dir / "sync.log"

    @property
    def sync_watch_state(self) -> Path:
        return self.accounts_dir / "watch.json"

    @property
    def plan_usage_history(self) -> Path:
        return self.desktop_data / "plan-usage-history.json"

    @property
    def registry_dir(self) -> Path:
        """Claude Code's own session registry: one file per running Claude Code process (``registry``)."""
        return self.claude_home / "sessions"

    # --- the one program WindowTally runs ---------------------------------------------------------------------------

    @property
    def sync_script(self) -> Path:
        """The account sync's installed script (install.ps1 puts it in ``~/.claude/bin``), which the window runs to
        switch an account and to turn the sync's switches: the window never touches a credential itself."""
        return self.claude_home / "bin" / "WindowTallySync.ps1"

    # --- WindowTally's own files --------------------------------------------------------------------------------

    @property
    def ledger_db(self) -> Path:
        return self.data_dir / "ledger.sqlite3"

    @property
    def status_file(self) -> Path:
        """The live standing the desktop plugin reads (contract: status_file.STATUS_VERSION)."""
        return self.data_dir / "status.json"

    @property
    def readings_dir(self) -> Path:
        """Where the desktop plugin writes one reading file per session (contract: ingest_readings)."""
        return self.data_dir / "readings"

    @property
    def browser_dir(self) -> Path:
        """Where the browser extension's host writes one reading file per organization (contract: browser_host)."""
        return self.data_dir / "browser"

    @property
    def browser_host_dir(self) -> Path:
        """The browser extension's host as Chrome finds it: its manifest and its launcher (browser_host.register)."""
        return self.data_dir / "browser-host"

    @property
    def sync_settings(self) -> Path:
        """The account sync's desktop-switching settings (followsDesktop, oneClickDesktop)."""
        return self.accounts_dir / "sync-settings.json"

    @property
    def bills_file(self) -> Path:
        """WindowTally's own bills file, which the user writes (contract: bills.BILLS_VERSION)."""
        return self.data_dir / "bills.json"

    @property
    def settings_file(self) -> Path:
        """What the user tells WindowTally that no file says (contract: settings.SETTINGS_VERSION)."""
        return self.data_dir / "settings.json"

    @property
    def dashboard_file(self) -> Path:
        return self.data_dir / "dashboard.html"

    @property
    def log_file(self) -> Path:
        return self.data_dir / "service.log"

    @property
    def lock_file(self) -> Path:
        return self.data_dir / "service.lock"

    @property
    def pass_lock(self) -> Path:
        """Held by whichever process runs a pass — the service, the command line, the window — for the pass."""
        return self.data_dir / "pass.lock"

    # --- the window's own files -----------------------------------------------------------------------------------

    @property
    def window_state(self) -> Path:
        """The window's own record: its place, whether it stays on top, the notices it already gave."""
        return self.data_dir / "window.json"

    @property
    def window_lock(self) -> Path:
        """Held by the running window, so that a second start shows it rather than opening another."""
        return self.data_dir / "window.lock"

    @property
    def window_request(self) -> Path:
        """Written by a second start, asking the running window to show itself."""
        return self.data_dir / "window.request"

    @property
    def window_log(self) -> Path:
        """What went wrong in the window, which pythonw runs without a console to say it on."""
        return self.data_dir / "window.log"


def default_paths() -> MachinePaths:
    """The machine's real locations.

    Claude Code's folder is always ``~/.claude``: the account sync keeps its store there whatever CLAUDE_CONFIG_DIR
    says, and WindowTally must read the folder the sync writes.

    WindowTally's own folder is ``~/.claude/windowtally``, beside the sync's store, and never under AppData: a process
    started from inside the Claude desktop app (a Claude Code session, the desktop plugin) has its AppData writes
    redirected into the app's private storage, where a logon task cannot see them (measured on the development
    machine, 2026-10-20). Files under ``~/.claude`` are the same for both.
    """
    home = Path.home()
    claude_home = home / ".claude"
    appdata = os.environ.get("APPDATA")
    desktop_data = Path(appdata) / "Claude" if appdata else home / ".config" / "Claude"
    return MachinePaths(claude_home=claude_home, desktop_data=desktop_data, data_dir=claude_home / DATA_FOLDER_NAME)
