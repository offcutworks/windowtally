"""The sync store's desktop switching state, as the service reads it for ``status.json``: the sync's two switches in
its settings file, and which accounts have a stored desktop login.

Neither holds a credential this module reads: an archive is only looked for, never opened.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

DESKTOP_ARCHIVE_FILE = "desktop-login.dpapi"


def desktop_archived_accounts(accounts_dir: Path) -> set[str]:
    """The accounts whose desktop login the sync has stored: a folder of the store holding the archive file."""
    if not accounts_dir.is_dir():
        return set()
    return {folder.name.lower() for folder in accounts_dir.iterdir()
            if folder.is_dir() and (folder / DESKTOP_ARCHIVE_FILE).is_file()}


def read_sync_settings(path: Path) -> tuple[bool, bool]:
    """``(follows_desktop, one_click_desktop)`` from the sync's settings file: both on while the file or a key is
    absent, and a value that is not true or false leaves that key on."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True, True
    except (OSError, ValueError) as exc:
        log.warning("Cannot read the sync settings %s: %s", path, exc)
        return True, True
    if not isinstance(data, dict):
        return True, True
    follows, one_click = data.get("followsDesktop"), data.get("oneClickDesktop")
    return (follows if isinstance(follows, bool) else True), (one_click if isinstance(one_click, bool) else True)
