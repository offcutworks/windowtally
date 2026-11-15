"""Build a release of WindowTally from a commit: its zip and ``SHA256SUMS``.

    python tools/build_release.py --label YEAR.MONTH.N [--commit REV] [--inputs DIR]
                                  [--out DIR] [--no-suite]

from any folder, with any Python 3.14 or later; the build itself needs the inputs
``fetch_build_inputs.py`` obtains, and git. It downloads nothing: every input is checked
against its pin before it is used.

The order of the build and every step that belongs to no one tool are
``release_core.py``'s, beside this file: the commit's tree read through ``git archive``
(the snapshot exporter's mechanism, so a build and a snapshot of one commit carry the
same files), the label, ``runtime/`` — CPython's embeddable package with Tk — the
bytecode bound to each source's hash, the refusal of a file naming the build folder or
the builder's home, the whole suite under the assembled interpreter judged against
``tests/TEST_LEDGER.md`` (``--no-suite`` skips it and says so), the zip with the first day
of the label's month as every file's time, and ``SHA256SUMS``. That file is shared byte
for byte with the maintainer's other published tools; this one holds what is WindowTally's:

- what a release ships from the commit: the ledger service's and the window's packages,
  the account sync, the plugin's manifests, hooks and types (not its tests), the browser
  extension, ``install.ps1``, ``LICENSE`` and ``README.md``;
- the Qt the window uses, in ``runtime/Lib/site-packages``: only what it imports and the
  platform needs, from the wheels ``build_inputs.py`` pins;
- the third-party notices: Python's, then Qt's with the software Qt incorporates, read from
  Qt's source archive, which ``build_inputs.py`` pins too. WindowTally bundles nothing else,
  its plugin running inside Claude Code and its extension inside Chrome;
- ``build.json``, the build record naming the label and the interpreter's version, and no
  commit (``windowtally.release``);
- how ``tests/TEST_LEDGER.md`` names the reds it records, and how the suite's runner reports.

It writes ``<out>/<label>/WindowTally-<label>.zip``, the release's files at its top level.
A user unpacks it and runs ``install.ps1`` there, which copies the packages, the licence,
the notices, the build record and ``runtime/`` into the installed copy: the installed copy
runs whole, and the unpacked folder serves only ``install.ps1`` itself.

Two builds with one label of commits holding the same files make the same zip, byte for
byte, wherever the repository and the build lie, so a build of the published repository's
tag for a label is that release: the build record names no commit, and the core reads the
commit's files as the commit holds them. A build that is to reproduce another runs under
the same CPython version, whose zlib compresses the zip.

Exit status: 0 built, 1 refused or failed, 2 usage.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
import textwrap
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Set

TOOLS = Path(__file__).resolve().parent
PROJECT = TOOLS.parent
for _path in (TOOLS, PROJECT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from build_inputs import PYSIDE6, QT_INPUTS, QT_SOURCE, QT_VERSION, SHIBOKEN6  # noqa: E402
from release_core import (PYTHON_VERSION, SITE_PACKAGES, Assembly, BuildError, BuildResult, Component,  # noqa: E402
                          EMBEDDABLE, FULL_PYTHON, InputError, Suite, SuiteResult, Tool, extract_member, failed_tests,
                          marked_flaky, python_licences, verdict)
import release_core  # noqa: E402
from windowtally.release import Release, write_release  # noqa: E402
from windowtally_gui.about_model import LICENCE_FILE_NAME, NOTICES_FILE_NAME  # noqa: E402

NAME = "WindowTally"
LEDGER = "tests/TEST_LEDGER.md"
SUITE = "tests/run_all.py"
SUITE_FOLDER = "tests"
PACKAGES = ("windowtally", "windowtally_gui")
SHIPPED = (*PACKAGES, "sync", "plugin/.claude-plugin", "plugin/hooks", "plugin/types", "extension", "install.ps1",
           LICENCE_FILE_NAME, "README.md")
"""What ``install.ps1`` installs from, and what it reads to do so: the plugin's three parts are the ones it copies."""

NOTICES_INTRO = ("This release of WindowTally carries the following software, each under its own",
                 "licence, reproduced below. WindowTally itself is released under the MIT License",
                 "in LICENSE.")

PYSIDE6_FILES = ("__init__.py", "_config.py", "_git_pyside_version.py", "QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd",
                 "pyside6.abi3.dll", "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "msvcp140.dll", "msvcp140_1.dll",
                 "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll", "plugins/platforms/qwindows.dll",
                 "plugins/platforms/qoffscreen.dll", "plugins/styles/qmodernwindowsstyle.dll")
SHIBOKEN6_FILES = ("__init__.py", "_config.py", "_git_shiboken_module_version.py", "Shiboken.pyd",
                   "shiboken6.abi3.dll", "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")
"""The Qt a release carries: ``QtCore``, ``QtGui`` and ``QtWidgets`` with their bindings, the libraries those need by
their import tables, Microsoft's C++ runtime among them, since a Windows without the redistributable holds none, the
Windows platform with its Windows 11 style, and the offscreen platform, on which the suite runs the window under the
release's own interpreter. Left out: every other module and tool of the wheel, the software OpenGL renderer, the image
formats and the translations, none of which the window reaches. Each library stays a file of its own, which the LGPL
lets a user replace."""
QT_MODULES = ("QtCore", "QtGui", "QtWidgets")
"""The modules the window imports."""

QT_SOURCE_ROOT = f"qtbase-everywhere-src-{QT_VERSION}"
QT_NOTICE_MODULES = ("qtcore", "qtgui")
"""The documentation modules whose third-party components a release carries: every library and plugin of it is built
from Qt Core, Qt GUI and Qt Widgets, and Qt lists none under Qt Widgets. Qt's lists are not cut down by platform."""
QT_LIBRARY_PART = "libs"
QT_ATTRIBUTION_FILE = "qt_attribution.json"
QT_LICENCES = ("LGPL-3.0-only", "GPL-3.0-only")
PYSIDE6_SOURCE = (f"https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{QT_VERSION}-src/"
                  f"pyside-setup-everywhere-src-{QT_VERSION}.tar.xz")
QT_WHERE = f"{PureWindowsPath(release_core.RUNTIME_DIR_NAME, SITE_PACKAGES)}\\"
QT_TERMS = "\n\n".join((
    textwrap.fill(f"Qt's libraries and plugins, PySide6 and shiboken6, version {QT_VERSION}, are carried unmodified as the "
                  "wheels of PySide6-Essentials and shiboken6 published on PyPI hold them, and are used under the GNU "
                  "Lesser General Public License, version 3, reproduced below with the GNU General Public License, "
                  f"version 3, it builds on. They are separate files in {QT_WHERE}PySide6\\ and shiboken6\\, loaded when "
                  "the program starts, and another build of them of the same version can take their place.", 79),
    f"Their source:\n- Qt: {QT_SOURCE.url}\n- PySide6 and shiboken6: {PYSIDE6_SOURCE}"))
CPP_RUNTIME_TERMS = textwrap.fill("msvcp140.dll, msvcp140_1.dll, msvcp140_2.dll, vcruntime140.dll and vcruntime140_1.dll, "
                                  "Microsoft's redistributable C++ runtime, come with the wheels above and are "
                                  "redistributed unmodified.", 79)

_RAN = re.compile(r"^Ran (\d+) tests? in ")
_OUTCOME = re.compile(r"^(OK|FAILED)(?: \((.*)\))?$")
_COUNT = re.compile(r"([a-z ]+)=(\d+)")
_FIELD = re.compile(r"^- \*\*([a-z]+):\*\*(.*)$")
_ITEM = re.compile(r"`([^`]+)`")
_PATH = re.compile(r"[\w./-]+\.(?:py|tsx?|js)")
_CLASS_TEST = re.compile(r"([A-Za-z_]\w*)\.(test\w*)")
_TEST = re.compile(r"test\w*")


# --- the notices -----------------------------------------------------------------------

def _archive_texts(archive: Path, wanted: Callable[[str], bool]) -> Dict[str, str]:
    """The text of every file of Qt's source archive whose path below its root ``wanted`` accepts, by that path."""
    found: Dict[str, str] = {}
    prefix = f"{QT_SOURCE_ROOT}/"
    with tarfile.open(archive, "r:xz") as bundle:
        for member in bundle:
            if member.isfile() and member.name.startswith(prefix) and wanted(member.name[len(prefix):]):
                found[member.name[len(prefix):]] = bundle.extractfile(member).read().decode("utf-8")
    return found


def _is_attribution(path: str) -> bool:
    return PurePosixPath(path).name == QT_ATTRIBUTION_FILE


def _shipped_components(attributions: Mapping[str, str]) -> List[tuple]:
    """Each component of ``QT_NOTICE_MODULES`` that a library of Qt holds, as its attribution file's folder and its
    entry, in one order: an entry of a build tool's holds nothing a release carries. Qt's files hold raw line breaks
    inside their strings, which only a lax reading of JSON accepts."""
    found = []
    for path in sorted(attributions):
        entries = json.loads(attributions[path], strict=False)
        for entry in entries if isinstance(entries, list) else [entries]:
            if (entry.get("QDocModule") in QT_NOTICE_MODULES
                    and QT_LIBRARY_PART in entry.get("QtParts", [QT_LIBRARY_PART])):
                found.append((PurePosixPath(path).parent, entry))
    return sorted(found, key=lambda item: (item[1]["Name"].casefold(), str(item[0])))


def _archive_path(folder: PurePosixPath, name: str) -> str:
    """The file an entry names, resolved against its folder as a path of the archive."""
    parts: List[str] = []
    for part in (folder / name).parts:
        if part == "..":
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def _licence_paths(folder: PurePosixPath, entry: Mapping) -> List[str]:
    """Where a component's licence texts stand in the archive: the files its entry names, or, for an entry naming
    none, Qt's own copy of each licence and exception its identifier names."""
    named = [*entry.get("LicenseFiles", ()), *([entry["LicenseFile"]] if entry.get("LicenseFile") else [])]
    if named:
        return [_archive_path(folder, name) for name in named]
    ids = [word for word in re.split(r"\s+|[()]", entry["LicenseId"]) if word and word not in ("AND", "OR", "WITH")]
    return [f"LICENSES/{licence}.txt" for licence in ids]


def _copyright_path(folder: PurePosixPath, entry: Mapping) -> Optional[str]:
    """The file holding a component's copyright, for an entry that gives it there rather than in its own words."""
    return _archive_path(folder, entry["CopyrightFile"]) if entry.get("CopyrightFile") else None


def _component_text(entry: Mapping, copyright_file: Optional[str], licences: Sequence[str]) -> str:
    """One component as the notices give it: its name and version, its licence's name, its copyright, the texts."""
    version = entry.get("Version")
    title = f"{entry['Name']}, version {version}" if version else entry["Name"]
    copyright_text = entry.get("Copyright", "")
    if not isinstance(copyright_text, str):
        copyright_text = "\n".join(copyright_text)
    if copyright_file is not None:
        copyright_text = f"{copyright_text}\n{copyright_file}"
    lines = [release_core.heading(title), "", f"License: {entry.get('License') or entry['LicenseId']}"]
    if copyright_text.strip():
        lines += ["", copyright_text.strip()]
    for text in licences:
        lines += ["", text.strip("\n")]
    return "\n".join(lines)


def _read_components(archive: Path) -> List[Component]:
    components = _shipped_components(_archive_texts(archive, _is_attribution))
    if not components:
        raise BuildError(f"{archive.name} lists no third-party component of {', '.join(QT_NOTICE_MODULES)}")
    named = [_licence_paths(folder, entry) for folder, entry in components]
    copyrights = [_copyright_path(folder, entry) for folder, entry in components]
    wanted = {path for paths in named for path in paths} | {f"LICENSES/{licence}.txt" for licence in QT_LICENCES}
    wanted |= {path for path in copyrights if path}
    texts = _archive_texts(archive, wanted.__contains__)
    missing = sorted(wanted - set(texts))
    if missing:
        raise BuildError(f"{archive.name} holds no {', '.join(missing)}")
    incorporated = tuple(_component_text(entry, texts[copyright_path] if copyright_path else None,
                                         [texts[path] for path in paths])
                         for (_, entry), paths, copyright_path in zip(components, named, copyrights))
    return [Component(f"Qt, PySide6 and shiboken6 {QT_VERSION}", QT_WHERE,
                      (QT_TERMS, *(texts[f"LICENSES/{licence}.txt"] for licence in QT_LICENCES))),
            Component(f"Software incorporated in Qt {QT_VERSION}, as Qt's source lists it", QT_WHERE, incorporated),
            Component("Microsoft's C++ runtime", QT_WHERE, (CPP_RUNTIME_TERMS,))]


def qt_components(archive: Path) -> List[Component]:
    """What the notices add to Python's, from Qt's source archive: Qt with PySide6 and shiboken6 under the LGPL, whose
    texts the wheels do not carry, the software Qt lists as incorporated, and Microsoft's C++ runtime. The archive is
    read twice, an xz archive being read in order: first for the lists, then for the files they name. An archive of
    another release of Qt that these fields do not fit refuses the build, as a missing file does."""
    try:
        return _read_components(archive)
    except (KeyError, IndexError, ValueError) as exc:
        raise BuildError(f"{archive.name} does not read as Qt's attributions: {exc!r}") from None


def notices_text(label: str, *, python_licence: str, incorporated: str, components: Sequence[Component]) -> str:
    """The third-party notices a release ships: Python, with Tcl/Tk, and its licence, then ``components``."""
    return release_core.notices_text(f"Third-party notices for {NAME} {label}", NOTICES_INTRO,
                                     python_licence=python_licence, incorporated=incorporated, components=components)


def write_notices(target: Path, label: str, embeddable: Path, full: Path, qt_source: Path) -> Path:
    python_licence, incorporated = python_licences(embeddable, full)
    target.write_text(notices_text(label, python_licence=python_licence, incorporated=incorporated,
                                   components=qt_components(qt_source)), encoding="utf-8", newline="\n")
    return target


# --- Qt --------------------------------------------------------------------------------

def assemble_wheel(runtime: Path, wheel: Path, package: str, files: Sequence[str]) -> None:
    """The ``files`` of ``package`` in ``wheel`` put into the runtime's ``site-packages``; a wheel that lacks one
    refuses the build, since a release without it would fail only when the window starts."""
    with zipfile.ZipFile(wheel) as bundle:
        names = set(bundle.namelist())
        for name in files:
            member = f"{package}/{name}"
            if member not in names:
                raise BuildError(f"{wheel.name} holds no {member}")
            extract_member(bundle, member, runtime / SITE_PACKAGES / member)


def assemble_qt(runtime: Path, pyside6: Path, shiboken6: Path) -> None:
    assemble_wheel(runtime, pyside6, "PySide6", PYSIDE6_FILES)
    assemble_wheel(runtime, shiboken6, "shiboken6", SHIBOKEN6_FILES)


# --- the suite -------------------------------------------------------------------------

def ledger_tests(ledger: str) -> Set[str]:
    """The tests of the Python suite that ``TEST_LEDGER.md`` records as red, as module.Class.test:
    those of every entry whose delta does not carry the mark of a test red only sometimes.

    An entry's ``tests`` field lists its tests as backticked items, each naming as much as
    changed since the one before it: a file (``tests/test_x.py``), a class and test
    (``SomeTest.test_one``), or a test of the class last named (``test_two``). The plugin's
    tests (``plugin/tests/...``) run under Claude Code's own runner, not in this suite, so
    an item naming a test after one of their files is not this suite's."""
    return _ledger(ledger)[0]


def flaky_tests(ledger: str) -> Set[str]:
    """The tests of the Python suite that ``TEST_LEDGER.md`` records as red only sometimes: those of
    every entry whose delta carries the core's ``FLAKY_MARK``, named as ``ledger_tests`` reads them."""
    return _ledger(ledger)[1]


def _ledger(ledger: str) -> tuple[Set[str], Set[str]]:
    red: Set[str] = set()
    flaky: Set[str] = set()
    for entry in _entries(ledger):
        tests = _tests_field(entry.get("tests", ""))
        (flaky if marked_flaky(entry.get("delta", "")) else red).update(tests)
    return red, flaky


def _entries(ledger: str) -> List[Dict[str, str]]:
    """Each entry's fields, an entry running from its ``### `` heading to the next and a field's
    lines indented by two spaces joined to it; a field written twice in one entry is joined to
    its first writing, so no test it names is lost, and what stands before the first heading is
    read as one entry too, so a field there is not lost either."""
    entries: List[Dict[str, str]] = [{}]
    field: Optional[str] = None
    for line in ledger.splitlines():
        if line.startswith("### "):
            entries.append({})
            field = None
            continue
        m = _FIELD.match(line)
        if m:
            field = m.group(1)
            entries[-1][field] = (entries[-1][field] + " " if field in entries[-1] else "") + m.group(2)
        elif field and line.startswith("  "):
            entries[-1][field] += " " + line
        else:
            field = None
    return entries


def _tests_field(text: str) -> Set[str]:
    found: Set[str] = set()
    module: Optional[str] = None
    in_suite: Optional[bool] = None     # None until the field names a file
    test_class: Optional[str] = None
    for item in _ITEM.findall(text):
        if _PATH.fullmatch(item):
            path = PurePosixPath(item)
            in_suite = path.suffix == ".py" and path.parts[0] == SUITE_FOLDER
            module = ".".join(path.with_suffix("").parts[1:]) if in_suite else None
            test_class = None
            continue
        if in_suite is None:
            raise BuildError(f"the ledger names {item!r} before the file that holds it")
        if not in_suite:
            continue
        m = _CLASS_TEST.fullmatch(item)
        if m:
            test_class = m.group(1)
            found.add(f"{module}.{test_class}.{m.group(2)}")
        elif _TEST.fullmatch(item) and test_class:
            found.add(f"{module}.{test_class}.{item}")
        else:
            raise BuildError(f"the ledger names {item!r} under {module}, which is no test this build can match")
    return found


def suite_summary(output: str) -> str:
    """The suite's count line in the form a build reports — ``N tests, F failed, S skipped`` —
    from unittest's own last lines: ``Ran N tests in ...`` and ``OK`` or ``FAILED (...)``."""
    lines = [line.strip() for line in output.splitlines()]
    ran = [i for i, line in enumerate(lines) if _RAN.match(line)]
    if not ran:
        raise BuildError("the suite ended without unittest's count of the tests it ran")
    count = int(_RAN.match(lines[ran[-1]]).group(1))
    outcome = next((_OUTCOME.match(line) for line in lines[ran[-1] + 1:] if line), None)
    if outcome is None:
        raise BuildError("the suite ended without unittest's verdict")
    counts = {key.strip(): int(value) for key, value in _COUNT.findall(outcome.group(2) or "")}
    failed = counts.get("failures", 0) + counts.get("errors", 0)
    return f"{count} tests, {failed} failed, {counts.get('skipped', 0)} skipped"


def judge_suite(output: str, ledger: str) -> SuiteResult:
    """A ``run_all.py`` transcript against ``TEST_LEDGER.md``: its counts, and the tests unittest
    reports failed or in error, against those the ledger records as red and as red only sometimes."""
    red, flaky = _ledger(ledger)
    return verdict(suite_summary(output), failed_tests(output), red, flaky=flaky)


# --- the build -------------------------------------------------------------------------

def assemble(a: Assembly) -> None:
    assemble_qt(a.runtime, a.inputs[PYSIDE6.name], a.inputs[SHIBOKEN6.name])
    write_notices(a.release / NOTICES_FILE_NAME, a.label, a.inputs[EMBEDDABLE.name], a.inputs[FULL_PYTHON.name],
                  a.inputs[QT_SOURCE.name])
    write_release(a.release, Release(a.label, PYTHON_VERSION))


def windowtally() -> Tool:
    """WindowTally's part of a release build."""
    return Tool(NAME, SHIPPED, Suite(SUITE, LEDGER, judge_suite, skipped="the suite was not run (--no-suite)"),
                inputs=QT_INPUTS, assembly=(assemble,), bytecode=PACKAGES)


def build(project: Path, *, label: str, commit: str = "HEAD", inputs: Optional[Path] = None,
          out: Optional[Path] = None, suite: bool = True,
          say: Callable[[str], None] = lambda _: None) -> BuildResult:
    """Build the release ``label`` of ``commit``. Raises BuildError (or InputError)."""
    return release_core.build(Path(project).resolve(), windowtally(), label=label, commit=commit, inputs=inputs,
                              out=out, suite=suite, say=say)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Build a release of WindowTally from a commit: its zip.")
    parser.add_argument("--label", required=True, help="the release label, YEAR.MONTH.N")
    parser.add_argument("--commit", default="HEAD", help="the commit to build (default HEAD)")
    parser.add_argument("--inputs", type=Path, default=None,
                        help=f"the folder holding the pinned inputs (default: {release_core.INPUTS_DIR_NAME} "
                             "beside tools/)")
    parser.add_argument("--out", type=Path, default=None, help="where to write <label>/ (default: dist beside tools/)")
    parser.add_argument("--no-suite", action="store_true", help="skip the suite; the build is then not verified")
    args = parser.parse_args(argv)
    try:
        build(PROJECT, label=args.label, commit=args.commit, inputs=args.inputs, out=args.out,
              suite=not args.no_suite, say=lambda line: print(line, flush=True))
    except (BuildError, InputError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
