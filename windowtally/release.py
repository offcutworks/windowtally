"""A release's build record: which release a copy of WindowTally is.

``build.json`` sits beside the packages in a release, and ``install.ps1`` copies it into the installed copy with
them. The build that made the release writes it; the program only reads it. Its label — ``YEAR.MONTH.N``, the N-th
release of that month — is the only place WindowTally learns which release it is: the in-code version stays 1.0.0 and
promises nothing. A copy with no record was run or installed from a source folder.

The record names no commit: nothing in a release may depend on the repository it was built from, so that the release
rebuilt from the published repository's tag for its label is the same zip, byte for byte. The label is what leads
from a release to its source.

A record that cannot be read still marks a release, whose label is then unknown and said so.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

BUILD_FILE_NAME = "build.json"
BUILD_FORMAT = "windowtally-build"
BUILD_SCHEMA = 1
LABEL_PATTERN = re.compile(r"\d{4}\.(?:[1-9]|1[0-2])\.[1-9]\d*")
KEYS = ("format", "schema_version", "label", "python")


@dataclass(frozen=True)
class Release:
    label: Optional[str]            # YEAR.MONTH.N; None when the record cannot be read
    python: Optional[str] = None    # the version of the interpreter the release carries

    @property
    def readable(self) -> bool:
        return self.label is not None

    def to_document(self) -> dict:
        return {"format": BUILD_FORMAT, "schema_version": BUILD_SCHEMA, "label": self.label, "python": self.python}

    @classmethod
    def from_document(cls, doc) -> "Release":
        """The release a record's document names; ValueError when it is not a build record of this schema."""
        if not isinstance(doc, dict) or set(doc) != set(KEYS):
            raise ValueError(f"a build record holds exactly {', '.join(KEYS)}")
        schema = doc["schema_version"]
        if doc["format"] != BUILD_FORMAT or type(schema) is not int or schema != BUILD_SCHEMA:   # True == 1 in Python
            raise ValueError(f"not a build record of schema {BUILD_SCHEMA}")
        label, python = doc["label"], doc["python"]
        if not isinstance(label, str) or not LABEL_PATTERN.fullmatch(label):
            raise ValueError("its label is not a release label (YEAR.MONTH.N)")
        if not isinstance(python, str) or not python:
            raise ValueError("it names no interpreter version")
        return cls(label, python)


def read_release(root: Path) -> Optional[Release]:
    """The release whose packages sit in ``root``; None when ``root`` holds no build record, and a release with an
    unknown label when it holds one that cannot be read."""
    path = Path(root) / BUILD_FILE_NAME
    if not path.is_file():
        return None
    try:
        return Release.from_document(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return Release(None)


def write_release(root: Path, release: Release) -> Path:
    """Write a release's build record into ``root`` — the build's step, never the program's."""
    document = Release.from_document(release.to_document()).to_document()
    path = Path(root) / BUILD_FILE_NAME
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def release_name(release: Optional[Release]) -> str:
    """How a copy names its release to the user, in a few words beside the version: a release by its label, and a copy
    run or installed from a source folder as one from source."""
    if release is None:
        return "from source"
    return f"release {release.label}" if release.readable else "release unknown"
