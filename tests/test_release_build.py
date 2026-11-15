"""The release tooling (``tools/``): the pinned inputs and their fetching, the build's parts and the build record,
without the network and without the inputs.

The build is exercised whole only by building a release, which needs the inputs: here each of its parts is bound on
its own, on the copy of the shared core this folder carries — the label, the notices, the suite's counts and its
verdict against the ledger, the zip and its sums, the assets after the zip — and a commit's tree is read from a git
repository made in a temporary folder. What a release ships is held to what ``install.ps1`` installs from."""

import hashlib
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

import fixtures

TOOLS = fixtures.TOOL_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_release  # noqa: E402
import fetch_build_inputs  # noqa: E402
import release_core  # noqa: E402
from windowtally import release  # noqa: E402
from windowtally_gui.about_model import LICENCE_FILE_NAME, NOTICES_FILE_NAME  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TempFolderTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)


class PinsTest(TempFolderTest):
    def test_the_runtime_s_inputs_are_each_pinned_by_a_digest_and_its_address(self):
        for item in release_core.RUNTIME_INPUTS:
            with self.subTest(item=item.name):
                self.assertRegex(item.sha256, r"^[0-9a-f]{64}$")
                self.assertTrue(item.url.endswith("/" + item.name))
                self.assertTrue(item.url.startswith("https://"))
                self.assertGreater(item.size, 0)

    def test_a_file_is_accepted_only_with_its_pinned_digest(self):
        path = self.tmp / "input.zip"
        path.write_bytes(b"content")
        self.assertEqual(release_core.checked(path, sha256(b"content")), path)
        with self.assertRaises(release_core.InputError):
            release_core.checked(path, "0" * 64)
        with self.assertRaises(release_core.InputError):
            release_core.checked(self.tmp / "missing.zip", sha256(b"content"))


class FetchInputsTest(TempFolderTest):
    def setUp(self):
        super().setUp()
        self.folder = self.tmp / "build-inputs"
        self.served = b"an input"
        self.item = release_core.Input("input.zip", "https://example.invalid/input.zip", sha256(self.served),
                                       len(self.served), "https://example.invalid/listing", "a test input")
        self.requests = []

    def opener(self, request, timeout):
        self.requests.append((request.full_url, request.get_header("User-agent")))
        return io.BytesIO(self.served)

    def test_it_downloads_once_naming_windowtally_and_leaves_an_input_in_place_alone(self):
        path, present = fetch_build_inputs.obtain(self.item, self.folder, opener=self.opener)
        self.assertEqual((path.read_bytes(), present), (self.served, False))
        self.assertEqual(self.requests, [("https://example.invalid/input.zip", fetch_build_inputs.USER_AGENT)])
        self.assertTrue(fetch_build_inputs.USER_AGENT.startswith("windowtally-"))
        path, present = fetch_build_inputs.obtain(self.item, self.folder, opener=self.opener)
        self.assertTrue(present)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual([p.name for p in self.folder.iterdir()], ["input.zip"])

    def test_a_copy_in_the_given_folder_is_used_without_a_download(self):
        source = self.tmp / "downloads"
        source.mkdir()
        (source / "input.zip").write_bytes(self.served)
        path, present = fetch_build_inputs.obtain(self.item, self.folder, source=source, opener=self.opener)
        self.assertEqual((path.read_bytes(), present, self.requests), (self.served, False, []))

    def test_another_content_is_refused_and_nothing_is_left(self):
        self.served = b"something else"
        with self.assertRaises(release_core.InputError):
            fetch_build_inputs.obtain(self.item, self.folder, opener=self.opener)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_an_input_in_place_with_another_content_is_refused(self):
        self.folder.mkdir()
        (self.folder / "input.zip").write_bytes(b"tampered")
        with self.assertRaises(release_core.InputError):
            fetch_build_inputs.obtain(self.item, self.folder, opener=self.opener)
        self.assertEqual(self.requests, [])

    def test_the_command_line_takes_copies_from_one_folder_into_another_and_says_when_it_cannot(self):
        source = self.tmp / "downloads"
        source.mkdir()
        (source / "input.zip").write_bytes(self.served)
        with open(os.devnull, "w") as quiet:
            stdout, stderr = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = quiet
            try:
                placed = release_core.fetch_main(["--from", str(source), "--to", str(self.folder)], [self.item],
                                                 user_agent="test", folder=self.tmp / "unused")
                (source / "input.zip").write_bytes(b"tampered")
                refused = release_core.fetch_main(["--from", str(source), "--to", str(self.tmp / "other")],
                                                  [self.item], user_agent="test", folder=self.tmp / "unused")
            finally:
                sys.stdout, sys.stderr = stdout, stderr
        self.assertEqual((placed, refused), (0, 1))
        self.assertEqual((self.folder / "input.zip").read_bytes(), self.served)
        self.assertFalse((self.tmp / "unused").exists())
        self.assertEqual(fetch_build_inputs.default_folder(), fixtures.TOOL_ROOT / release_core.INPUTS_DIR_NAME)


class LabelTest(unittest.TestCase):
    def test_a_release_label_is_year_month_and_count(self):
        for label in ("2026.10.1", "2026.1.12", "2031.12.3"):
            self.assertEqual(release_core.check_label(label), label)
        for label in ("2026.13.1", "2026.10.0", "26.10.1", "2026.10", "2026.010.1", "1.0.0-2026"):
            with self.subTest(label=label), self.assertRaises(release_core.BuildError):
                release_core.check_label(label)

    def test_every_file_of_a_release_carries_the_first_day_of_its_month(self):
        self.assertEqual(release_core.label_time("2026.10.3"), (2026, 10, 1, 0, 0, 0))

    def test_the_core_s_release_label_is_the_build_record_s(self):
        self.assertEqual(release_core.LABEL_PATTERN.pattern, release.LABEL_PATTERN.pattern)


PAGE = """<html><body>
<section id="other"><h2>Other<a class="headerlink" href="#other">&#182;</a></h2><p>not wanted</p></section>
<section id="wanted">
<h2>Incorporated   software<a class="headerlink" href="#wanted">&#182;</a></h2>
<p>An introduction that runs on
across lines.</p>
<section id="part"><h3>A part<a class="headerlink" href="#part">&#182;</a></h3>
<div class="highlight"><pre><span></span>Copyright (C) 2001 Someone
  kept    as it is
</pre></div>
</section>
</section>
<section id="after"><p>also not wanted</p></section>
</body></html>"""


class NoticesTest(unittest.TestCase):
    def test_a_page_section_becomes_text_with_its_subsections_and_nothing_else(self):
        text = release_core.page_section_text(PAGE, "wanted")
        self.assertEqual(text, "Incorporated software\n=====================\n\n"
                               "An introduction that runs on across lines.\n\n"
                               "A part\n------\n\n"
                               "Copyright (C) 2001 Someone\n  kept    as it is")
        with self.assertRaises(release_core.BuildError):
            release_core.page_section_text(PAGE, "absent")

    def test_the_notices_name_python_with_tcl_tk_and_carry_its_licences(self):
        text = build_release.notices_text("2026.10.1", python_licence="PSF LICENSE\r\n", incorporated="EXPAT TEXT",
                                          components=())
        self.assertTrue(text.startswith("Third-party notices for WindowTally 2026.10.1\n"))
        for part in ("PSF LICENSE", "EXPAT TEXT", "WindowTally itself is released under the MIT License",
                     f"- Python {release_core.PYTHON_VERSION}, with Tcl/Tk, in runtime\\"):
            self.assertIn(part, text)
        self.assertNotIn("\r", text)


LEDGER = """# Test Debt Ledger

Fields: **tests · commit · delta · disposition · since**.

---

### The service — a unit whose two tests went red
- **tests:** `tests/test_alpha.py` `AlphaTest.test_one`,
  `test_two`, `tests/test_beta.py` `BetaTest.test_three`
- **commit:** the change of 2027-05-07 that names `tests/test_gamma.py` `GammaTest.test_never` in its own field
- **delta:** what changed
- **disposition:** `none`
- **since:** 2027-05-07

### The band — a unit of the plugin's
- **tests:** `plugin/tests/band.test.tsx` "a band of every account", `plugin/tests/panel.test.tsx` "the panel"
- **commit:** the change of 2027-05-08
"""


class SuiteVerdictTest(unittest.TestCase):
    def test_the_ledger_names_each_python_test_as_much_as_changed_since_the_one_before(self):
        self.assertEqual(build_release.ledger_tests(LEDGER), {"test_alpha.AlphaTest.test_one",
                                                              "test_alpha.AlphaTest.test_two",
                                                              "test_beta.BetaTest.test_three"})

    def test_a_ledger_entry_this_build_cannot_match_refuses_the_release(self):
        for field in ("- **tests:** `AlphaTest.test_one` in `tests/test_alpha.py`",
                      "- **tests:** `tests/test_alpha.py` all of `AlphaTest`",
                      "- **tests:** `tests/test_alpha.py` `test_one`"):
            with self.subTest(field=field), self.assertRaises(release_core.BuildError):
                build_release.ledger_tests(f"### A unit\n{field}\n- **commit:** a change\n")

    def test_the_ledger_this_folder_holds_is_read(self):
        ledger = (fixtures.TOOL_ROOT / build_release.LEDGER).read_text(encoding="utf-8")
        self.assertIsInstance(build_release.ledger_tests(ledger), set)

    def test_failures_are_read_in_both_unittest_spellings(self):
        output = ("FAIL: test_one (test_a.ATest)\n"
                  "ERROR: test_two (test_b.BTest.test_two)\n"
                  "ok\n")
        self.assertEqual(release_core.failed_tests(output), {"test_a.ATest.test_one", "test_b.BTest.test_two"})

    def test_the_counts_are_read_from_unittest_s_own_last_lines(self):
        for tail, summary in (("Ran 809 tests in 123.456s\n\nOK\n", "809 tests, 0 failed, 0 skipped"),
                              ("Ran 1 test in 0.001s\n\nOK (skipped=1)\n", "1 tests, 0 failed, 1 skipped"),
                              ("Ran 12 tests in 1.5s\n\nFAILED (failures=2, errors=1, skipped=3)\n",
                               "12 tests, 3 failed, 3 skipped")):
            with self.subTest(tail=tail):
                self.assertEqual(build_release.suite_summary("test_x (m.C.test_x) ... ok\n" + "-" * 70 + "\n" + tail),
                                 summary)
        for broken in ("FAIL: test_one (test_a.ATest.test_one)\n", "Ran 3 tests in 0.1s\n\n"):
            with self.subTest(broken=broken), self.assertRaises(release_core.BuildError):
                build_release.suite_summary(broken)

    def test_a_build_needs_exactly_the_ledger_s_failures(self):
        tail = "\nRan 10 tests in 1.0s\n\nFAILED (failures=3)\n"
        same = build_release.judge_suite("FAIL: test_one (test_alpha.AlphaTest.test_one)\n"
                                         "FAIL: test_two (test_alpha.AlphaTest.test_two)\n"
                                         "FAIL: test_three (test_beta.BetaTest.test_three)\n" + tail, LEDGER)
        self.assertTrue(same.matches_ledger)
        self.assertEqual(same.summary, "10 tests, 3 failed, 0 skipped")
        other = build_release.judge_suite("FAIL: test_one (test_alpha.AlphaTest.test_one)\n"
                                          "FAIL: test_two (test_alpha.AlphaTest.test_two)\n"
                                          "FAIL: test_new (test_gamma.GammaTest.test_new)\n" + tail, LEDGER)
        self.assertFalse(other.matches_ledger)
        self.assertEqual((other.unexpected, other.recovered),
                         (("test_gamma.GammaTest.test_new",), ("test_beta.BetaTest.test_three",)))


FLAKY_LEDGER = LEDGER + """
### The sync — a test red only sometimes
- **tests:** `tests/test_delta.py`
  `DeltaTest.test_seldom`
- **commit:** no change caused it.
- **delta:** flaky-quarantine. Seen red once, beside a busy machine.
- **disposition:** none
- **since:** 2027-05-09
"""


class FlakyMarkTest(unittest.TestCase):
    TAIL = "\nRan 10 tests in 1.0s\n\nFAILED (failures=3)\n"
    RED = ("FAIL: test_one (test_alpha.AlphaTest.test_one)\n"
           "FAIL: test_two (test_alpha.AlphaTest.test_two)\n"
           "FAIL: test_three (test_beta.BetaTest.test_three)\n")

    def test_an_entry_whose_delta_carries_the_mark_names_its_tests_apart(self):
        self.assertEqual(build_release.flaky_tests(FLAKY_LEDGER), {"test_delta.DeltaTest.test_seldom"})
        self.assertEqual(build_release.ledger_tests(FLAKY_LEDGER), build_release.ledger_tests(LEDGER))
        self.assertEqual(build_release.flaky_tests(LEDGER), set())

    def test_a_marked_test_refuses_no_build_whether_it_fails_or_passes(self):
        passing = build_release.judge_suite(self.RED + self.TAIL, FLAKY_LEDGER)
        self.assertTrue(passing.matches_ledger)
        self.assertEqual(passing.flaky, ())
        failing = build_release.judge_suite(self.RED + "FAIL: test_seldom (test_delta.DeltaTest.test_seldom)\n"
                                            + self.TAIL, FLAKY_LEDGER)
        self.assertTrue(failing.matches_ledger)
        self.assertEqual((failing.unexpected, failing.flaky), ((), ("test_delta.DeltaTest.test_seldom",)))

    def test_beside_a_marked_test_any_other_difference_still_refuses_the_build(self):
        other = build_release.judge_suite("FAIL: test_one (test_alpha.AlphaTest.test_one)\n"
                                          "FAIL: test_two (test_alpha.AlphaTest.test_two)\n"
                                          "FAIL: test_seldom (test_delta.DeltaTest.test_seldom)\n"
                                          "FAIL: test_new (test_gamma.GammaTest.test_new)\n" + self.TAIL,
                                          FLAKY_LEDGER)
        self.assertFalse(other.matches_ledger)
        self.assertEqual((other.unexpected, other.recovered),
                         (("test_gamma.GammaTest.test_new",), ("test_beta.BetaTest.test_three",)))

    def test_a_mark_spelled_otherwise_refuses_the_release(self):
        for delta in ("Flaky-quarantine. Seen red once.", "flaky quarantine. Seen red once.", "flaky. Seen red once.",
                      "`flaky-quarantine.` Seen red once.", "**flaky-quarantine.** Seen red once."):
            ledger = FLAKY_LEDGER.replace("flaky-quarantine. Seen red once, beside a busy machine.", delta)
            with self.subTest(delta=delta), self.assertRaises(release_core.BuildError):
                build_release.ledger_tests(ledger)

    def test_a_test_recorded_both_as_red_and_as_red_only_sometimes_refuses_the_release(self):
        ledger = FLAKY_LEDGER.replace("`DeltaTest.test_seldom`", "`DeltaTest.test_seldom`, `tests/test_alpha.py` "
                                                                  "`AlphaTest.test_one`")
        with self.assertRaises(release_core.BuildError):
            build_release.judge_suite(self.RED + self.TAIL, ledger)

    def test_a_field_written_twice_in_one_entry_loses_none_of_its_tests(self):
        ledger = FLAKY_LEDGER.replace("- **commit:** no change caused it.",
                                      "- **tests:** `tests/test_epsilon.py` `EpsilonTest.test_rare`\n"
                                      "- **commit:** no change caused it.")
        self.assertEqual(build_release.flaky_tests(ledger), {"test_delta.DeltaTest.test_seldom",
                                                             "test_epsilon.EpsilonTest.test_rare"})

    def test_the_ledger_this_folder_holds_records_no_test_both_ways(self):
        ledger = (fixtures.TOOL_ROOT / build_release.LEDGER).read_text(encoding="utf-8")
        self.assertEqual(build_release.ledger_tests(ledger) & build_release.flaky_tests(ledger), set())


class ZipTest(TempFolderTest):
    def folder(self) -> Path:
        folder = self.tmp / "release"
        for name, data in (("b.txt", b"b"), ("a/inner.bin", bytes(range(256))), ("a/z.txt", b"z" * 1000)):
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(data)
        return folder

    def test_one_folder_makes_one_zip_whatever_its_files_times(self):
        folder = self.folder()
        first = self.tmp / "first.zip"
        self.assertEqual(release_core.write_zip(folder, first, (2026, 10, 1, 0, 0, 0)), 3)
        os.utime(folder / "b.txt", (1_000_000_000, 1_000_000_000))
        second = self.tmp / "second.zip"
        release_core.write_zip(folder, second, (2026, 10, 1, 0, 0, 0))
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as bundle:
            infos = bundle.infolist()
            self.assertEqual([i.filename for i in infos], ["a/inner.bin", "a/z.txt", "b.txt"])
            self.assertEqual({i.date_time for i in infos}, {(2026, 10, 1, 0, 0, 0)})
            self.assertEqual(bundle.read("a/inner.bin"), bytes(range(256)))

    def test_a_file_naming_the_build_folder_is_found_in_any_spelling(self):
        folder = self.folder()
        built = r"C:\Builds\Some Account\windowtally-build-x"
        (folder / "a" / "code.pyc").write_bytes(b"\x00co_filename " + built.upper().encode("utf-8") + b"\\m.py\x00")
        (folder / "wide.dll").write_bytes(b"MZ" + built.replace("\\", "/").encode("utf-16-le"))
        self.assertEqual(release_core.files_naming(folder, [built]), ["a/code.pyc", "wide.dll"])
        self.assertEqual(release_core.files_naming(folder, [r"C:\Elsewhere"]), [])

    def test_the_sums_name_each_file_with_its_digest(self):
        asset = self.tmp / "WindowTally-2026.10.1.zip"
        asset.write_bytes(b"zip bytes")
        sums = release_core.write_sums(self.tmp / "SHA256SUMS", [asset])
        self.assertEqual(sums.read_bytes(), f"{sha256(b'zip bytes')}  WindowTally-2026.10.1.zip\n".encode())


class CommitTreeTest(TempFolderTest):
    """A build reads the commit, never the working tree: a repository made here holds the project in a sub-folder,
    an export-ignored folder, and a change made after the commit."""

    def git(self, *args):
        env = dict(os.environ, GIT_AUTHOR_NAME="suite", GIT_AUTHOR_EMAIL="", GIT_COMMITTER_NAME="suite",
                   GIT_COMMITTER_EMAIL="")
        done = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
                              cwd=str(self.tmp), capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def test_the_commit_s_tree_is_read_without_its_export_ignored_paths_or_later_changes(self):
        project = self.tmp / "project"
        for name, text in (("tool.py", "committed\n"), ("private/plan.md", "private\n"),
                           (".gitattributes", "/private export-ignore\n/.gitattributes export-ignore\n")):
            (project / name).parent.mkdir(parents=True, exist_ok=True)
            (project / name).write_text(text, encoding="utf-8")
        self.git("init", "-q")
        self.git("add", "--all")
        self.git("commit", "-q", "-m", "one")
        (project / "tool.py").write_text("changed after the commit\n", encoding="utf-8")
        (project / "untracked.py").write_text("never committed\n", encoding="utf-8")
        commit, tree = release_core.resolve_commit(project, "HEAD")
        self.assertEqual(commit, self.git("rev-parse", "HEAD"))
        target = self.tmp / "archive"
        self.assertEqual(release_core.archive(project, tree, target), ["tool.py"])
        self.assertEqual((target / "tool.py").read_text(encoding="utf-8"), "committed\n")
        with self.assertRaises(release_core.BuildError):
            release_core.resolve_commit(project, "no-such-revision")


class ComposedBuildTest(TempFolderTest):
    """WindowTally's part of the build composed with the shared core beside it."""

    def test_windowtally_supplies_what_it_ships_its_suite_and_its_packages(self):
        tool = build_release.windowtally()
        self.assertEqual((tool.name, tool.shipped, tool.bytecode),
                         ("WindowTally", build_release.SHIPPED, ("windowtally", "windowtally_gui")))
        self.assertEqual((tool.suite.path, tool.suite.ledger), ("tests/run_all.py", "tests/TEST_LEDGER.md"))
        self.assertEqual((tool.required, tool.after_zip), ((), ()))
        for name in (*tool.shipped, tool.suite.path, tool.suite.ledger):
            with self.subTest(name=name):
                self.assertTrue((fixtures.TOOL_ROOT / name).exists())

    def test_a_release_ships_what_install_ps1_installs_from_and_not_the_tests(self):
        script = (fixtures.TOOL_ROOT / "install.ps1").read_text(encoding="utf-8")
        parts = re.search(r"^\$PluginParts = @\(([^)]*)\)", script, re.MULTILINE).group(1)
        plugin = {f"plugin/{part.strip(chr(39))}" for part in re.findall(r"'[^']+'", parts)}
        shipped = set(build_release.SHIPPED)
        self.assertEqual({name for name in shipped if name.startswith("plugin/")}, plugin)
        self.assertLessEqual({"windowtally", "windowtally_gui", "sync", "extension", "install.ps1", LICENCE_FILE_NAME},
                             shipped)
        self.assertFalse({"tests", "plugin", "plugin/tests", "private", "PROJECT.md"} & shipped)

    def test_a_pinned_input_sharing_a_file_name_refuses_the_build_before_anything_is_written(self):
        tool = build_release.windowtally()
        shadow = release_core.Input(release_core.EMBEDDABLE.name.upper(), release_core.EMBEDDABLE.url, "0" * 64, 1,
                                    release_core.EMBEDDABLE.listed_by, "a shadow")
        with self.assertRaises(release_core.BuildError):
            release_core.build(self.tmp, replace(tool, inputs=(shadow,)), label="2026.11.1",
                               inputs=self.tmp / "inputs", out=self.tmp / "out")
        self.assertFalse((self.tmp / "out").exists())

    def test_an_asset_after_the_zip_is_a_file_beside_it_under_a_name_of_its_own(self):
        destination = self.tmp / "2026.11.1"
        destination.mkdir()
        (destination / "Extra.bin").write_bytes(b"extra")
        (self.tmp / "elsewhere.bin").write_bytes(b"elsewhere")
        taken = ["WindowTally-2026.11.1.zip", "SHA256SUMS"]
        self.assertEqual(release_core.checked_assets(destination, [destination / "Extra.bin"], taken),
                         [destination / "Extra.bin"])
        (destination / "SHA256SUMS").write_bytes(b"sums")
        for refused in ([self.tmp / "elsewhere.bin"], [destination / "missing.bin"], [destination / "SHA256SUMS"],
                        [destination / "sha256sums"], [destination / "Extra.bin", destination / "Extra.bin"]):
            with self.subTest(refused=[p.name for p in refused]), self.assertRaises(release_core.BuildError):
                release_core.checked_assets(destination, refused, taken)

    def test_the_assembly_keeps_qt_and_writes_the_notices_and_the_build_record_the_window_reads(self):
        kept, written = [], []
        assembly = release_core.Assembly("2026.11.1", "0" * 40, self.tmp / "source", self.tmp, self.tmp / "runtime",
                                         {release_core.EMBEDDABLE.name: Path("embed.zip"),
                                          release_core.FULL_PYTHON.name: Path("full.zip"),
                                          build_release.PYSIDE6.name: Path("pyside6.whl"),
                                          build_release.SHIBOKEN6.name: Path("shiboken6.whl"),
                                          build_release.QT_SOURCE.name: Path("qt.tar.xz")})
        originals = build_release.assemble_qt, build_release.write_notices
        build_release.assemble_qt = lambda runtime, pyside6, shiboken6: kept.append((runtime, pyside6, shiboken6))
        build_release.write_notices = lambda target, label, embeddable, full, qt_source: written.append(
            (target, label, embeddable, full, qt_source))
        try:
            build_release.assemble(assembly)
        finally:
            build_release.assemble_qt, build_release.write_notices = originals
        self.assertEqual(kept, [(self.tmp / "runtime", Path("pyside6.whl"), Path("shiboken6.whl"))])
        self.assertEqual(written, [(self.tmp / NOTICES_FILE_NAME, "2026.11.1", Path("embed.zip"), Path("full.zip"),
                                    Path("qt.tar.xz"))])
        self.assertEqual(release.read_release(self.tmp), release.Release("2026.11.1", release_core.PYTHON_VERSION))


class BuildRecordTest(TempFolderTest):
    def test_a_record_names_the_label_and_the_interpreter_and_no_commit(self):
        path = release.write_release(self.tmp, release.Release("2027.5.2", "3.14.8"))
        self.assertEqual(path.name, release.BUILD_FILE_NAME)
        self.assertEqual(set(release.Release("2027.5.2", "3.14.8").to_document()),
                         {"format", "schema_version", "label", "python"})
        self.assertNotIn(b"\r", path.read_bytes())
        found = release.read_release(self.tmp)
        self.assertEqual(found, release.Release("2027.5.2", "3.14.8"))
        self.assertEqual(release.release_name(found), "release 2027.5.2")

    def test_a_copy_with_no_record_is_no_release_and_one_that_cannot_be_read_is_an_unknown_release(self):
        self.assertIsNone(release.read_release(self.tmp))
        self.assertEqual(release.release_name(None), "from source")
        for text in ("not json", '{"format": "windowtally-build", "schema_version": 1, "label": "2027.13.1", '
                                 '"python": "3.14.8"}',
                     '{"format": "windowtally-build", "schema_version": 1, "label": "2027.5.1", "python": "3.14.8", '
                     '"commit": "abc"}',
                     '{"format": "windowtally-build", "schema_version": true, "label": "2027.5.1", '
                     '"python": "3.14.8"}'):
            with self.subTest(text=text):
                (self.tmp / release.BUILD_FILE_NAME).write_text(text, encoding="utf-8")
                found = release.read_release(self.tmp)
                self.assertFalse(found.readable)
                self.assertEqual(release.release_name(found), "release unknown")

    def test_a_record_that_would_not_read_back_is_never_written(self):
        with self.assertRaises(ValueError):
            release.write_release(self.tmp, release.Release("2027.5", "3.14.8"))
        self.assertIsNone(release.read_release(self.tmp))


class SharedNamesTest(unittest.TestCase):
    def test_the_build_writes_what_the_window_and_the_installer_read(self):
        script = (fixtures.TOOL_ROOT / "install.ps1").read_text(encoding="utf-8")
        self.assertIn(LICENCE_FILE_NAME, build_release.SHIPPED)
        for name in (LICENCE_FILE_NAME, NOTICES_FILE_NAME, release.BUILD_FILE_NAME, release_core.RUNTIME_DIR_NAME):
            with self.subTest(name=name):
                self.assertIn(f"'{name}'", script)


if __name__ == "__main__":
    unittest.main()
