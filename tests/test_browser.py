"""The browser extension's way into WindowTally: its manifest, the native-messaging host, the host's registration with
Chrome (against a registry kept in memory, never the machine's), the readings' ingestion, and a whole pass."""

import io
import json
import os
import struct
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fixtures import ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, TOOL_ROOT, Machine, epoch
from windowtally import browser_host, history
from windowtally.accounts import by_org, load_registry
from windowtally.browser_host import (EXTENSION_ID, HOST_NAME, REGISTRY_KEY, ReadingError, extension_id,
                                      launcher_text, reading_from, register, serve, unregister)
from windowtally.ingest_browser import ingest_browser
from windowtally.ingest_readings import RETENTION_SECONDS
from windowtally.ledger import Ledger
from windowtally.service import run_pass

NOW = epoch("2026-10-20T20:00:00Z")
EXTENSION = TOOL_ROOT / "extension"


def page_time(epoch_seconds: float) -> str:
    """A reset time as claude.ai's usage response writes it: microseconds and an explicit offset."""
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat(timespec="microseconds")


def message(org: str = ORG_B, t: float = NOW, five_hour=(34, NOW + 7200), weekly=(61, NOW + 2 * 86400), **changes):
    """A reading as the extension sends it, each window as (percent, reset epoch)."""
    body = {"v": 1, "org": org, "t": int(t * 1000), "windows": [
        {"kind": "five_hour", "percentUsed": five_hour[0], "resetsAt": page_time(five_hour[1])},
        {"kind": "seven_day", "percentUsed": weekly[0], "resetsAt": page_time(weekly[1])}]}
    body.update(changes)
    return body


def frame(payload) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return struct.pack("=I", len(body)) + body


def answers(stream: bytes) -> list:
    found, offset = [], 0
    while offset < len(stream):
        (length,) = struct.unpack_from("=I", stream, offset)
        found.append(json.loads(stream[offset + 4:offset + 4 + length]))
        offset += 4 + length
    return found


class MemoryRegistry:
    """The default values of HKEY_CURRENT_USER keys, kept in a dictionary."""

    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class ExtensionTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))

    def test_the_id_the_host_allows_is_the_one_chrome_derives_from_the_manifests_key(self):
        self.assertEqual(extension_id(self.manifest["key"]), EXTENSION_ID)

    def test_the_extension_asks_for_native_messaging_alone_and_runs_on_claude_ai_alone(self):
        self.assertEqual(self.manifest["permissions"], ["nativeMessaging"])
        self.assertNotIn("host_permissions", self.manifest)
        self.assertNotIn("optional_permissions", self.manifest)
        self.assertEqual({tuple(s["matches"]) for s in self.manifest["content_scripts"]}, {("https://claude.ai/*",)})

    def test_the_name_carries_no_other_companys_mark(self):
        self.assertNotIn("claude", self.manifest["name"].lower())

    def test_the_service_worker_names_this_host_and_its_version(self):
        worker = (EXTENSION / "background.js").read_text(encoding="utf-8")
        self.assertIn(f'const HOST = "{HOST_NAME}";', worker)
        self.assertIn(f"const VERSION = {browser_host.READING_VERSION};", worker)

    def test_no_script_names_a_network_api_of_its_own(self):
        for name in ("page.js", "relay.js", "background.js"):
            script = (EXTENSION / name).read_text(encoding="utf-8")
            for api in ("XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "document.cookie", "chrome.cookies"):
                self.assertNotIn(api, script, f"{name} names {api}")
        # page.js calls fetch only as the page's own, through the wrapper it installs.
        page = (EXTENSION / "page.js").read_text(encoding="utf-8")
        self.assertEqual(page.count("pageFetch.apply("), 1)
        self.assertNotIn("fetch(", page.replace("pageFetch.apply(", "").replace("window.fetch = function", ""))


class ReadingTest(unittest.TestCase):
    def test_a_message_becomes_the_file_from_its_checked_fields_alone(self):
        sent = message(org=ORG_B.upper(), extra="dropped")
        sent["windows"][0]["extra"] = "dropped too"
        reading = reading_from(sent)
        self.assertEqual(reading, {"v": 1, "t": int(NOW * 1000), "org": ORG_B, "windows": [
            {"kind": "five_hour", "percentUsed": 34, "resetsAt": page_time(NOW + 7200)},
            {"kind": "seven_day", "percentUsed": 61, "resetsAt": page_time(NOW + 2 * 86400)}]})

    def test_a_window_without_a_reset_time_is_kept(self):
        sent = message()
        sent["windows"][1]["resetsAt"] = None
        self.assertIsNone(reading_from(sent)["windows"][1]["resetsAt"])

    def test_what_is_not_a_reading_is_refused(self):
        def window(**changes):
            sent = message()
            sent["windows"][0].update(changes)
            return sent
        refused = {
            "another version": message(v=2),
            "no organization": message(org=None),
            "an organization that would name another file": message(org="..\\..\\settings"),
            "a time that is a flag": dict(message(), t=True),
            "a time before the epoch": dict(message(), t=-1),
            "no windows": message(windows=[]),
            "windows that are not a list": message(windows={"five_hour": 3}),
            "an unknown window": window(kind="seven_day_opus"),
            "a window twice": message(windows=[message()["windows"][0]] * 2),
            "a negative figure": window(percentUsed=-1),
            "a figure that is not a number": window(percentUsed=float("nan")),
            "a figure that is a flag": window(percentUsed=False),
            "a reset time that is not text": window(resetsAt=1793000000),
            "not an object": ["v", 1],
        }
        for case, sent in refused.items():
            with self.subTest(case), self.assertRaises(ReadingError):
                reading_from(sent)


class HostTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.folder = self.machine.paths.browser_dir

    def tearDown(self):
        self.machine.close()

    def test_each_message_is_answered_and_only_a_reading_is_written(self):
        out = io.BytesIO()
        status = serve(io.BytesIO(frame(message()) + frame(message(org=ORG_A, v=9))), out, self.folder)
        self.assertEqual(status, 0)
        replies = answers(out.getvalue())
        self.assertEqual(replies[0], {"ok": True})
        self.assertFalse(replies[1]["ok"])
        self.assertIn("version", replies[1]["error"])
        self.assertEqual([p.name for p in self.folder.iterdir()], [f"{ORG_B}.json"])
        written = json.loads((self.folder / f"{ORG_B}.json").read_text(encoding="utf-8"))
        self.assertEqual(written, reading_from(message()))

    def test_a_later_reading_replaces_the_earlier(self):
        serve(io.BytesIO(frame(message(five_hour=(34, NOW + 7200)))), io.BytesIO(), self.folder)
        serve(io.BytesIO(frame(message(t=NOW + 60, five_hour=(36, NOW + 7200)))), io.BytesIO(), self.folder)
        written = json.loads((self.folder / f"{ORG_B}.json").read_text(encoding="utf-8"))
        self.assertEqual((written["t"], written["windows"][0]["percentUsed"]), (int((NOW + 60) * 1000), 36))

    def test_a_frame_that_cannot_be_read_is_answered_and_ends_the_session(self):
        cases = {
            "cut inside its length": b"\x10\x00",
            "cut inside its body": struct.pack("=I", 50) + b"{}",
            "too long to be a reading": struct.pack("=I", browser_host.MAX_MESSAGE + 1),
            "not JSON": struct.pack("=I", 3) + b"{x}",
        }
        for case, stream in cases.items():
            with self.subTest(case):
                out = io.BytesIO()
                self.assertEqual(serve(io.BytesIO(stream + frame(message())), out, self.folder), 1)
                self.assertEqual(len(answers(out.getvalue())), 1)
                self.assertFalse(answers(out.getvalue())[0]["ok"])
        self.assertFalse(self.folder.exists(), "nothing after an unreadable frame is written")


class RegistrationTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.registry = MemoryRegistry()
        root = self.machine.paths.claude_home.parent
        self.python = root / "runtime" / "python.exe"
        self.app = root / "app"

    def tearDown(self):
        self.machine.close()

    def test_registering_writes_the_launcher_the_manifest_and_the_one_key(self):
        manifest_path = register(self.machine.paths, self.python, self.app, self.registry)
        self.assertEqual(self.registry.values, {REGISTRY_KEY: str(manifest_path)})
        self.assertEqual(REGISTRY_KEY, r"Software\Google\Chrome\NativeMessagingHosts\windowtally.browser")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        launcher = self.machine.paths.browser_host_dir / "host.cmd"
        self.assertEqual(manifest, {
            "name": HOST_NAME, "description": manifest["description"], "path": str(launcher), "type": "stdio",
            "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"]})
        self.assertEqual(launcher.read_bytes().decode("utf-8"),
                         launcher_text(self.python, self.app, self.machine.paths.browser_dir))

    def test_the_launcher_runs_the_package_from_its_folder_into_the_registered_data_folder(self):
        folder = self.machine.paths.browser_dir
        lines = launcher_text(self.python, self.app, folder).split("\r\n")
        self.assertEqual(lines, ["@echo off", "chcp 65001 >nul", f'cd /d "{self.app}"',
                                 f'"{self.python}" -m windowtally.browser_host "{folder}" %*', ""])

    def test_a_path_a_batch_file_cannot_quote_is_refused(self):
        for bad in ("100%", 'say "hi"'):
            with self.subTest(bad), self.assertRaises(ValueError):
                launcher_text(self.python, self.app / bad, self.machine.paths.browser_dir)

    def test_unregistering_removes_the_key_and_the_files(self):
        register(self.machine.paths, self.python, self.app, self.registry)
        self.registry.set(r"Software\Other", "kept")
        unregister(self.machine.paths, self.registry)
        self.assertEqual(self.registry.values, {r"Software\Other": "kept"})
        self.assertFalse(self.machine.paths.browser_host_dir.exists())
        unregister(self.machine.paths, self.registry)   # twice is no error


@unittest.skipUnless(os.name == "nt", "Chrome starts a host through cmd.exe on Windows")
class LauncherTest(unittest.TestCase):
    """The launcher run as Chrome runs it — cmd.exe, Chrome's two arguments, the message on standard input — with the
    console interpreter on this tool's folder and the home pointed at a temporary folder."""

    def setUp(self):
        self.machine = Machine()
        self.paths = self.machine.paths
        python = Path(sys.executable).with_name("python.exe")
        register(self.paths, python, TOOL_ROOT, MemoryRegistry())

    def tearDown(self):
        self.machine.close()

    def test_a_message_through_the_launcher_is_answered_and_written(self):
        launcher = self.paths.browser_host_dir / "host.cmd"
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", str(launcher), f"chrome-extension://{EXTENSION_ID}/", "--parent-window=0"],
            input=frame(message()), capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(answers(result.stdout), [{"ok": True}])
        written = self.paths.browser_dir / f"{ORG_B}.json"
        self.assertEqual(json.loads(written.read_text(encoding="utf-8")), reading_from(message()))


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        self.orgs = by_org(registry)
        self.folder = self.machine.paths.browser_dir

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def write(self, sent) -> None:
        serve(io.BytesIO(frame(sent)), io.BytesIO(), self.folder)

    def rows(self):
        return self.ledger.db.execute("SELECT ref, t, kind, percent, resets_at, account_uuid, account_source "
                                      "FROM observations WHERE source='browser' ORDER BY t, kind").fetchall()

    def test_a_reading_becomes_its_accounts_observations_with_exact_reset_times(self):
        self.write(message(org=ORG_A))
        self.assertEqual(ingest_browser(self.ledger, self.folder, self.orgs, NOW), 2)
        self.assertEqual(self.rows(), [
            (ORG_A, NOW, "five_hour", 34.0, NOW + 7200, ACCOUNT_A, "org"),
            (ORG_A, NOW, "seven_day", 61.0, NOW + 2 * 86400, ACCOUNT_A, "org")])
        self.assertEqual(ingest_browser(self.ledger, self.folder, self.orgs, NOW), 0, "an unchanged file is not re-read")

    def test_a_reading_of_an_organization_registered_later_gets_its_account_then(self):
        self.write(message(org=ORG_B))
        ingest_browser(self.ledger, self.folder, self.orgs, NOW)
        self.assertEqual({r[5] for r in self.rows()}, {None})
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        ingest_browser(self.ledger, self.folder, by_org(registry), NOW)
        self.assertEqual({(r[5], r[6]) for r in self.rows()}, {(ACCOUNT_B, "org")})

    def test_a_file_the_host_would_not_have_written_is_skipped_with_a_warning(self):
        unknown_window = message(org=ORG_A)
        unknown_window["windows"][1]["kind"] = "seven_day_opus"
        for case, sent in {"another version": message(org=ORG_A, v=2), "an unknown window": unknown_window}.items():
            with self.subTest(case):
                self.folder.mkdir(parents=True, exist_ok=True)
                (self.folder / f"{ORG_A}.json").write_text(json.dumps(sent), encoding="utf-8")
                with self.assertLogs("windowtally.ingest_browser", "WARNING"):
                    self.assertEqual(ingest_browser(self.ledger, self.folder, self.orgs, NOW), 0)
                self.assertEqual(self.rows(), [])
                (self.folder / f"{ORG_A}.json").unlink()

    def test_an_old_file_is_deleted_once_ingested(self):
        self.write(message(org=ORG_A))
        path = self.folder / f"{ORG_A}.json"
        old = NOW - RETENTION_SECONDS - 60
        os.utime(path, (old, old))
        ingest_browser(self.ledger, self.folder, self.orgs, NOW)
        self.assertFalse(path.exists())
        self.assertEqual(len(self.rows()), 2, "its readings stay in the ledger")


class LivePathTest(unittest.TestCase):
    """Account B was last seen by the desktop app yesterday; since then it has been used in a browser alone."""

    def setUp(self):
        self.machine = Machine()
        m = self.machine
        m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        m.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        m.app_history([(NOW - 86400 - 1800, ORG_B, 30, 70), (NOW - 86400, ORG_B, 40, 72)])

    def tearDown(self):
        self.machine.close()

    def beta(self):
        doc = json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))
        return {a["label"]: a for a in doc["accounts"]}["beta"]

    def test_without_the_extension_the_browser_use_does_not_show(self):
        run_pass(self.machine.paths, NOW, dashboard=False)
        self.assertEqual(self.beta()["fiveHour"]["state"], "not_started")
        self.assertEqual(self.beta()["weekly"]["percent"], 72.0)

    def test_a_browser_reading_gives_the_account_its_figures_and_exact_reset_times(self):
        five_hour_reset, weekly_reset = NOW + 7200, NOW + 2 * 86400
        serve(io.BytesIO(frame(message(org=ORG_B, t=NOW - 120, five_hour=(34, five_hour_reset),
                                       weekly=(75, weekly_reset)))), io.BytesIO(), self.machine.paths.browser_dir)
        report = run_pass(self.machine.paths, NOW, dashboard=True)
        self.assertEqual(report.errors, [])
        beta = self.beta()
        self.assertEqual((beta["fiveHour"]["state"], beta["fiveHour"]["percent"], beta["fiveHour"]["estimated"]),
                         ("running", 34.0, False))
        self.assertEqual(epoch(beta["fiveHour"]["resetsAt"]), five_hour_reset)
        self.assertEqual(beta["weekly"]["percent"], 75.0)
        self.assertTrue(beta["weekly"]["anchorExact"])
        self.assertEqual(epoch(beta["weekly"]["resetsAt"]), weekly_reset)
        self.assertIn("Browser readings since", self.machine.paths.dashboard_file.read_text(encoding="utf-8"))

    def test_the_coverage_says_reset_times_are_inferred_only_where_no_reading_gives_them(self):
        ledger = Ledger.open(self.machine.paths.ledger_db)
        try:
            run_pass(self.machine.paths, NOW, dashboard=False)
            items = history.coverage(ledger, [ACCOUNT_A, ACCOUNT_B], NOW, [])
            self.assertIn("No plugin readings yet: reset times are inferred (≈).", items)
            self.assertFalse(any(i.startswith("Browser readings") for i in items))
            serve(io.BytesIO(frame(message(org=ORG_B, t=NOW - 120))), io.BytesIO(), self.machine.paths.browser_dir)
            run_pass(self.machine.paths, NOW, dashboard=False)
            items = history.coverage(ledger, [ACCOUNT_A, ACCOUNT_B], NOW, [])
            self.assertIn("No plugin readings yet.", items)
            self.assertTrue(any(i.startswith("Browser readings since") for i in items))
        finally:
            ledger.close()


if __name__ == "__main__":
    unittest.main()
