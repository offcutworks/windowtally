"""The About window in words (Help menu): which version and release this is, its copyright and licence, that it is free
and where its official copies come from, what WindowTally reads and stores, and the third-party notices a release
ships. No toolkit.

The copyright line is read from the licence file beside the packages — the notice the MIT License asks to travel with
every copy — so it is written once, there, and the window shows what the licence says: the source folder holds it,
and install.ps1 copies it into the installed copy. A copy whose licence file is missing or cannot be read says so,
and offers no licence to open. Every copy names the same official source, so that a user sold a copy can find out it
is free. A release also carries the notices of the software it bundles, which the window opens, and its build record,
from which the window names the release, the in-code version being the same in every release; a copy run from
source, or installed from one, ships neither, offers no notices and says it is no release.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from windowtally import __version__
from windowtally.release import read_release, release_name

COPY_ROOT = Path(__file__).resolve().parent.parent   # the folder holding the packages
LICENCE_FILE_NAME = "LICENSE"
NOTICES_FILE_NAME = "THIRD-PARTY-NOTICES.txt"
OFFICIAL_COPIES = "https://github.com/offcutworks/windowtally"

NAME = "WindowTally"
WINDOW_TITLE = "About WindowTally"
LICENCE_TITLE = "WindowTally licence"
NOTICES_TITLE = "WindowTally third-party notices"
FREE = "Free, under the MIT License."
OFFICIAL = "Official copies only from:"
MISSING_LICENCE = "This copy's licence file is missing."
NO_COPYRIGHT = "This copy's licence file has no copyright line."
READS = ("WindowTally sends no network request of its own. It reads Claude Code's transcripts on this computer and "
         "keeps, in its ledger there, each session's use and title, the turns a plan limit stopped and the background "
         "tasks it started. Sign-ins stay on this computer, sealed for your Windows account; only the account sync "
         "handles them, to put them back into Claude's own apps.")


def read_text(path: Path) -> str | None:
    """A shipped file's text; None when it is missing or cannot be read as text."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def copyright_line(licence: str | None) -> str | None:
    """The licence's copyright notice, as written there."""
    for line in (licence or "").splitlines():
        if line.strip().lower().startswith("copyright"):
            return line.strip()
    return None


@dataclass(frozen=True)
class AboutContent:
    version: str                 # the in-code version and the release, as one line
    licence: str | None          # the licence's text; None when the copy's file cannot be read
    notices: str | None = None   # the third-party notices' text; None when the copy ships none

    @property
    def copyright(self) -> str:
        """The copyright line, or why there is none to show."""
        if self.licence is None:
            return MISSING_LICENCE
        return copyright_line(self.licence) or NO_COPYRIGHT


def about_content(root: Path = COPY_ROOT) -> AboutContent:
    """What the About window shows for the copy whose packages sit in ``root``."""
    return AboutContent(f"Version {__version__}, {release_name(read_release(root))}",
                        read_text(Path(root) / LICENCE_FILE_NAME), read_text(Path(root) / NOTICES_FILE_NAME))
