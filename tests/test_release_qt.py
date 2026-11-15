"""The Qt a release carries: its pinned inputs, the files of the wheels the build keeps, and the notices it reads from
Qt's source archive, each bound on a small invented wheel and archive, without the network and without the build's
inputs. Whether the window starts from what is kept is the release suite's: it runs under the release's own interpreter."""

import ast
import io
import json
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

import fixtures

TOOLS = fixtures.TOOL_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import PySide6  # noqa: E402

import build_inputs  # noqa: E402
import build_release  # noqa: E402
import fetch_build_inputs  # noqa: E402
import release_core  # noqa: E402


class TempFolderTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)


class PinsTest(unittest.TestCase):
    def test_a_release_is_built_from_the_runtime_s_inputs_and_qt_s_each_pinned_by_a_digest_and_its_address(self):
        self.assertEqual(fetch_build_inputs.INPUTS, (*release_core.RUNTIME_INPUTS, *build_inputs.QT_INPUTS))
        self.assertEqual(build_release.windowtally().inputs, build_inputs.QT_INPUTS)
        for item in build_inputs.QT_INPUTS:
            with self.subTest(item=item.name):
                self.assertRegex(item.sha256, r"^[0-9a-f]{64}$")
                self.assertTrue(item.url.endswith("/" + item.name))
                self.assertTrue(item.url.startswith("https://"))
                self.assertGreater(item.size, 0)

    def test_the_two_wheels_and_the_source_are_one_release_of_qt_the_one_the_suite_runs_on(self):
        for item in build_inputs.QT_INPUTS:
            with self.subTest(item=item.name):
                self.assertIn(f"-{build_inputs.QT_VERSION}", item.name)
        self.assertEqual(PySide6.__version__, build_inputs.QT_VERSION)


class KeptFilesTest(TempFolderTest):
    def wheel(self, name, package, files, extra=()):
        path = self.tmp / name
        with zipfile.ZipFile(path, "w") as bundle:
            for member in (*files, *extra):
                bundle.writestr(f"{package}/{member}", f"bytes of {package}/{member}")
        return path

    def wheels(self, *, without=()):
        kept = [name for name in build_release.PYSIDE6_FILES if name not in without]
        pyside6 = self.wheel("pyside6.whl", "PySide6", kept,
                             ("Qt6Quick.dll", "opengl32sw.dll", "plugins/imageformats/qjpeg.dll",
                              "translations/qtbase_de.qm", "QtNetwork.pyd"))
        return pyside6, self.wheel("shiboken6.whl", "shiboken6", build_release.SHIBOKEN6_FILES, ("Shiboken.pyi",))

    def test_only_the_files_named_reach_site_packages_as_the_wheel_holds_them(self):
        runtime = self.tmp / "runtime"
        build_release.assemble_qt(runtime, *self.wheels())
        site = runtime / release_core.SITE_PACKAGES
        found = {path.relative_to(site).as_posix() for path in site.rglob("*") if path.is_file()}
        self.assertEqual(found, {*(f"PySide6/{name}" for name in build_release.PYSIDE6_FILES),
                                 *(f"shiboken6/{name}" for name in build_release.SHIBOKEN6_FILES)})
        self.assertEqual((site / "PySide6" / "Qt6Core.dll").read_bytes(), b"bytes of PySide6/Qt6Core.dll")

    def test_a_wheel_lacking_a_file_refuses_the_build_naming_it(self):
        pyside6, shiboken6 = self.wheels(without=("plugins/styles/qmodernwindowsstyle.dll",))
        with self.assertRaisesRegex(release_core.BuildError, "qmodernwindowsstyle"):
            build_release.assemble_qt(self.tmp / "runtime", pyside6, shiboken6)

    def test_each_module_the_window_imports_is_carried_with_its_library(self):
        imported = set()
        for path in (fixtures.TOOL_ROOT / "windowtally_gui").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                imported |= {name.split(".")[1] for name in names if name.startswith("PySide6.")}
        self.assertLessEqual(imported, set(build_release.QT_MODULES))
        self.assertTrue(imported)
        for module in build_release.QT_MODULES:
            with self.subTest(module=module):
                self.assertIn(f"{module}.pyd", build_release.PYSIDE6_FILES)
                self.assertIn(f"{module.replace('Qt', 'Qt6', 1)}.dll", build_release.PYSIDE6_FILES)

    def test_the_platform_and_the_style_the_window_starts_with_are_carried(self):
        for plugin in ("platforms/qwindows.dll", "styles/qmodernwindowsstyle.dll"):
            with self.subTest(plugin=plugin):
                self.assertIn(f"plugins/{plugin}", build_release.PYSIDE6_FILES)


CORE = {"QDocModule": "qtcore", "Name": "Zeta Library", "Version": "1.2", "License": "MIT License",
        "LicenseId": "MIT", "LicenseFile": "LICENSE", "Copyright": "Copyright (c) 2001 Zeta"}
SHARED = {"QDocModule": "qtgui", "Name": "Alpha Rasterizer", "LicenseId": "FTL OR GPL-2.0-only",
          "LicenseFile": "../../3rdparty/alpha/LICENSE.txt", "Copyright": ["Copyright 2002 One", "Copyright 2003 Two"]}
NO_FILE = {"QDocModule": "qtgui", "Name": "Beta Data", "LicenseId": "Unicode-3.0 AND MIT"}
TWO_FILES = {"QDocModule": "qtgui", "Name": "Gamma Codec", "LicenseId": "IJG AND BSD-3-Clause",
             "LicenseFiles": ["LICENSE", "ijg-license.txt"], "Copyright": "See the file",
             "CopyrightFile": "COPYRIGHT.txt"}
TOOL_ONLY = {"QDocModule": "qtcore", "Name": "Build Helper", "LicenseId": "Apache-2.0", "QtParts": ["tools"],
             "LicenseFile": "ABSENT"}
ELSEWHERE = {"QDocModule": "qtnetwork", "Name": "Network Thing", "LicenseId": "MIT", "LicenseFile": "ABSENT"}


class NoticesTest(TempFolderTest):
    FILES = {"LICENSES/LGPL-3.0-only.txt": "LESSER WORDS\n", "LICENSES/GPL-3.0-only.txt": "GENERAL WORDS\n",
             "LICENSES/MIT.txt": "MIT TEXT\n", "LICENSES/Unicode-3.0.txt": "UNICODE TEXT\n",
             "src/3rdparty/zeta/LICENSE": "ZETA LICENCE\r\n", "src/3rdparty/alpha/LICENSE.txt": "ALPHA LICENCE\n",
             "src/3rdparty/gamma/LICENSE": "GAMMA ONE\n", "src/3rdparty/gamma/ijg-license.txt": "GAMMA TWO\n",
             "src/3rdparty/gamma/COPYRIGHT.txt": "GAMMA COPYRIGHT\n",
             "src/other/README": "not read\n"}

    def archive(self, files=None, *, attributions=None):
        attributions = attributions if attributions is not None else {
            "src/3rdparty/zeta/qt_attribution.json": json.dumps(CORE).replace('Zeta"}', 'Zeta\n"}'),
            "src/gui/painting/qt_attribution.json": json.dumps([SHARED, NO_FILE]),
            "src/3rdparty/gamma/qt_attribution.json": json.dumps([TWO_FILES, TOOL_ONLY, ELSEWHERE])}
        path = self.tmp / "qtbase.tar.xz"
        with tarfile.open(path, "w:xz") as bundle:
            for name, text in {**(self.FILES if files is None else files), **attributions}.items():
                data = text.encode("utf-8")
                info = tarfile.TarInfo(f"{build_release.QT_SOURCE_ROOT}/{name}")
                info.size = len(data)
                bundle.addfile(info, io.BytesIO(data))
        return path

    def text(self, archive):
        return build_release.notices_text("2026.11.1", python_licence="PSF LICENSE", incorporated="EXPAT TEXT",
                                          components=build_release.qt_components(archive))

    def test_the_notices_list_python_qt_what_qt_incorporates_and_the_c_runtime(self):
        listed = [line for line in self.text(self.archive()).splitlines() if line.startswith("- ")
                  and " in runtime\\" in line]
        self.assertEqual(len(listed), 4)
        for line, name in zip(listed, (f"Python {release_core.PYTHON_VERSION}, with Tcl/Tk",
                                       f"Qt, PySide6 and shiboken6 {build_inputs.QT_VERSION}",
                                       f"Software incorporated in Qt {build_inputs.QT_VERSION}",
                                       "Microsoft's C++ runtime")):
            self.assertTrue(line.startswith(f"- {name}"), line)

    def test_qt_is_named_under_the_lgpl_with_both_licences_and_where_its_source_is_had(self):
        text = " ".join(self.text(self.archive()).split())
        for part in ("LESSER WORDS", "GENERAL WORDS", "GNU Lesser General Public License, version 3",
                     build_inputs.QT_SOURCE.url, build_release.PYSIDE6_SOURCE):
            with self.subTest(part=part):
                self.assertIn(part, text)

    def test_each_component_of_a_library_is_named_with_its_copyright_and_licence_in_one_order(self):
        text = self.text(self.archive())
        names = [text.index(name) for name in ("Alpha Rasterizer", "Beta Data", "Gamma Codec", "Zeta Library, version 1.2")]
        self.assertEqual(names, sorted(names))
        for part in ("License: MIT License", "Copyright (c) 2001 Zeta", "Copyright 2002 One\nCopyright 2003 Two",
                     "ZETA LICENCE", "ALPHA LICENCE", "GAMMA ONE", "GAMMA TWO", "See the file", "GAMMA COPYRIGHT"):
            with self.subTest(part=part):
                self.assertIn(part, text)
        self.assertNotIn("\r", text)

    def test_a_component_naming_no_file_takes_qt_s_copy_of_each_licence_its_identifier_names(self):
        text = self.text(self.archive())
        component = text[text.index("Beta Data"):text.index("Gamma Codec")]
        self.assertIn("UNICODE TEXT", component)
        self.assertIn("MIT TEXT", component)

    def test_a_licence_exception_in_an_identifier_is_taken_like_a_licence(self):
        entry = {"QDocModule": "qtcore", "Name": "Delta", "LicenseId": "GPL-3.0-only WITH Qt-GPL-exception-1.0"}
        archive = self.archive({**self.FILES, "LICENSES/Qt-GPL-exception-1.0.txt": "EXCEPTION WORDS\n"},
                               attributions={"src/delta/qt_attribution.json": json.dumps(entry)})
        self.assertIn("EXCEPTION WORDS", self.text(archive))

    def test_a_build_tool_s_component_and_another_module_s_are_left_out(self):
        text = self.text(self.archive())
        self.assertNotIn("Build Helper", text)
        self.assertNotIn("Network Thing", text)

    def test_a_licence_the_lists_name_and_the_archive_lacks_refuses_the_build_naming_it(self):
        files = {name: text for name, text in self.FILES.items() if name != "src/3rdparty/alpha/LICENSE.txt"}
        with self.assertRaisesRegex(release_core.BuildError, "src/3rdparty/alpha/LICENSE.txt"):
            build_release.qt_components(self.archive(files))
        files = {name: text for name, text in self.FILES.items() if name != "LICENSES/LGPL-3.0-only.txt"}
        with self.assertRaisesRegex(release_core.BuildError, "LGPL-3.0-only"):
            build_release.qt_components(self.archive(files))

    def test_attributions_these_fields_do_not_fit_refuse_the_build_rather_than_end_it_with_a_traceback(self):
        unnamed = json.dumps({"QDocModule": "qtcore", "LicenseId": "MIT"})
        above_the_root = json.dumps({"QDocModule": "qtcore", "Name": "Epsilon", "LicenseFile": "../../../LICENSE"})
        for text in ("not json", unnamed, above_the_root):
            with self.subTest(text=text), self.assertRaises(release_core.BuildError):
                build_release.qt_components(self.archive(attributions={"src/qt_attribution.json": text}))

    def test_an_archive_listing_no_component_refuses_the_build(self):
        with self.assertRaises(release_core.BuildError):
            build_release.qt_components(self.archive(attributions={}))

    def test_one_archive_makes_one_text(self):
        archive = self.archive()
        self.assertEqual(self.text(archive), self.text(archive))


if __name__ == "__main__":
    unittest.main()
