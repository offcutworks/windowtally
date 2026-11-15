"""The Start menu entry that starts the window by hand: a shortcut in the user's Start menu Programs folder.

install.ps1 has this module write it, and remove it, in a process the Task Scheduler starts (``python -m
windowtally_gui --shortcut create`` or ``remove``): the Start menu folder lies under AppData, and a process started from
inside the Claude desktop app — a terminal in it included — has its AppData writes land in the app's private storage,
where Windows never looks for the Start menu (measured on the development machine, 2026-10-20, for WindowTally's data
folder). A shortcut is a shell link, which Windows PowerShell writes through WScript.Shell: a console program, started
with CREATE_NO_WINDOW as every console program the window's code starts is, and handed its values in its environment,
so that no path is ever quoted into a command.

The entry shows the logo: the same run draws it (``logo_model``) into an icon file beside the packages, ``ICON_NAME``,
which the shortcut names, so the file is the installed copy's own drawing, never an image kept in the source. Removing
the entry removes the icon file too.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .logo_model import icon_file

NAME = "WindowTally.lnk"
ICON_NAME = "windowtally.ico"
DESCRIPTION = "WindowTally: every account's standing, live"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_WRITE = ("$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK_SHORTCUT); "
          "$link.TargetPath = $env:LINK_TARGET; $link.Arguments = $env:LINK_ARGUMENTS; "
          "$link.WorkingDirectory = $env:LINK_FOLDER; $link.Description = $env:LINK_DESCRIPTION; "
          "if ($env:LINK_ICON) { $link.IconLocation = $env:LINK_ICON + ',0' }; $link.Save()")


def shortcut_path() -> Path | None:
    """Where the entry lives; None where the environment names no AppData folder."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / NAME


def _powershell() -> str:
    return str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0"
               / "powershell.exe")


def create_shortcut(path: Path, target: Path, arguments: str, folder: Path, icon: Path | None = None,
                    run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
    """Writes the shell link at ``path``, starting ``target arguments`` in ``folder`` and showing ``icon`` (the
    target's own icon where None); OSError when it was not written. An entry already there under another spelling of
    the name is removed first: Windows keeps a file's own spelling when it is written over under another case, so
    only a fresh write gives the entry this name's spelling. One spelt as ``path`` is written over in place, so a
    write that fails leaves it standing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for entry in path.parent.iterdir():
        if entry.name.lower() == path.name.lower() and entry.name != path.name:
            remove_shortcut(entry)
    environment = dict(os.environ, LINK_SHORTCUT=str(path), LINK_TARGET=str(target), LINK_ARGUMENTS=arguments,
                       LINK_FOLDER=str(folder), LINK_DESCRIPTION=DESCRIPTION, LINK_ICON=str(icon) if icon else "")
    result = run([_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _WRITE],
                 env=environment, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=120)
    if result.returncode != 0 or not path.is_file():
        raise OSError(f"the shortcut {path} was not written: {(result.stderr or '').strip() or result.returncode}")


def write_icon(path: Path) -> Path:
    """Draws the logo into the icon file at ``path``; OSError when it cannot be written."""
    path.write_bytes(icon_file())
    return path


def remove_shortcut(path: Path) -> bool:
    """Whether there was a shortcut to remove."""
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def main(action: str) -> int:
    """``create`` or ``remove`` the entry; the exit status the Task Scheduler reports to install.ps1."""
    path = shortcut_path()
    if path is None:
        print("The environment names no AppData folder, so there is no Start menu to write to.", file=sys.stderr)
        return 1
    folder = Path(__file__).resolve().parent.parent
    try:
        if action == "create":
            icon = write_icon(folder / ICON_NAME)
            create_shortcut(path, Path(sys.executable), "-m windowtally_gui", folder, icon=icon)
        else:
            remove_shortcut(path)
            (folder / ICON_NAME).unlink(missing_ok=True)
    except (OSError, subprocess.SubprocessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0
