"""The week's use by product, end to end: the extension handing it on, the host keeping it apart from the windows, the
ledger's reports of it, which report is an account's current one, status.json's optional key, the window's card, the
history's table — and every way WindowTally reads and shows as before without it."""

import io
import json
import os
import sqlite3
import struct
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, TOOL_ROOT, Machine, epoch,
                      status_account, status_document, status_window)
from windowtally import history, products
from windowtally.accounts import by_org, load_registry
from windowtally.browser_host import reading_from, serve
from windowtally.ingest_browser import ingest_browser
from windowtally.ledger import SCHEMA_VERSION, Ledger
from windowtally.limits import WEEK
from windowtally.service import run_pass
from windowtally_gui import history_model
from windowtally_gui.history_model import Heading, Note, Table
from windowtally_gui.live_model import live_view
from windowtally_gui.status_model import snapshot_of

NOW = epoch("2026-10-20T20:00:00Z")
RESET = NOW + 5 * 86400               # the weekly window's end, as the readings give it
START = RESET - WEEK                  # its start, as claude.ai's use by product names it
EXTENSION = TOOL_ROOT / "extension"
SPLIT = (("claude_code", "Claude Code", 99), ("chat", "Chats", 1), ("cowork", "Cowork", 0), ("other", "Other", 0))


def page_time(epoch_seconds: float) -> str:
    """A time as claude.ai's usage response writes it: microseconds and an explicit offset."""
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat(timespec="microseconds")


def split(as_of: float = NOW - 30, start: float = START, rows=SPLIT) -> dict:
    """The week's use by product as the extension sends it."""
    return {"asOf": page_time(as_of), "windowStartedAt": page_time(start),
            "rows": [{"key": key, "name": name, "percent": percent} for key, name, percent in rows]}


def message(org: str = ORG_A, t: float = NOW, weekly: float = 61, by_product: dict | None = None, **changes) -> dict:
    """A reading as the extension sends it: 34 % of a 5-hour window, ``weekly`` % of the week ending at RESET."""
    body = {"v": 1, "org": org, "t": int(t * 1000), "windows": [
        {"kind": "five_hour", "percentUsed": 34, "resetsAt": page_time(NOW + 7200)},
        {"kind": "seven_day", "percentUsed": weekly, "resetsAt": page_time(RESET)}]}
    if by_product is not None:
        body["weeklyByProduct"] = by_product
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


class ExtensionTest(unittest.TestCase):
    def test_the_page_hands_on_the_weeks_use_by_product_beside_the_windows_and_the_worker_passes_it(self):
        page = (EXTENSION / "page.js").read_text(encoding="utf-8")
        for name in ("seven_day_breakdown", "window_started_at", "display_name", "weeklyByProduct"):
            self.assertIn(name, page)
        for script in ("relay.js", "background.js"):
            self.assertIn("weeklyByProduct", (EXTENSION / script).read_text(encoding="utf-8"), script)
        self.assertIn("answer.dropped", (EXTENSION / "background.js").read_text(encoding="utf-8"))

    def test_the_manifests_description_fits_chromes_limit(self):
        manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
        self.assertLessEqual(len(manifest["description"]), 132)


class HostTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.folder = self.machine.paths.browser_dir

    def tearDown(self):
        self.machine.close()

    def written(self) -> dict:
        return json.loads((self.folder / f"{ORG_A}.json").read_text(encoding="utf-8"))

    def test_a_reading_keeps_its_use_by_product_from_its_checked_fields_alone(self):
        sent = split()
        sent["extra"] = "dropped"
        sent["rows"][1].update(name="  Chats ", extra="dropped too")
        kept = reading_from(message(by_product=sent))["weeklyByProduct"]
        self.assertEqual(kept, {"asOf": page_time(NOW - 30), "windowStartedAt": page_time(START), "rows": [
            {"key": "claude_code", "name": "Claude Code", "percent": 99}, {"key": "chat", "name": "Chats", "percent": 1},
            {"key": "cowork", "name": "Cowork", "percent": 0}, {"key": "other", "name": "Other", "percent": 0}]})

    def test_one_not_in_its_shape_is_dropped_alone_the_windows_written_and_the_answer_says_so(self):
        def row(**changes):
            sent = split()
            sent["rows"][0].update(changes)
            return sent
        dropped = {
            "not an object": ["claude_code", 99],
            "no time it was computed": dict(split(), asOf="yesterday"),
            "no window start": dict(split(), windowStartedAt=None),
            "no rows": dict(split(), rows=[]),
            "rows that are not a list": dict(split(), rows={"claude_code": 99}),
            "too many rows": dict(split(), rows=[{"key": f"p{i}", "name": "P", "percent": 1} for i in range(33)]),
            "a key in capitals": row(key="Claude_Code"),
            "a key that would be a path": row(key="..\\x"),
            "a key twice": dict(split(), rows=[split()["rows"][0]] * 2),
            "no name": row(name="  "),
            "a negative share": row(percent=-1),
            "a share that is not a number": row(percent=float("nan")),
            "a share that is a flag": row(percent=True),
        }
        for case, sent in dropped.items():
            with self.subTest(case):
                out = io.BytesIO()
                self.assertEqual(serve(io.BytesIO(frame(message(by_product=sent))), out, self.folder), 0)
                [answer] = answers(out.getvalue())
                self.assertTrue(answer["ok"])
                self.assertIsInstance(answer["dropped"], str)
                self.assertEqual(self.written(), reading_from(message()), "the windows as without it")

    def test_a_reading_without_it_is_answered_and_written_as_before(self):
        out = io.BytesIO()
        serve(io.BytesIO(frame(message())), out, self.folder)
        self.assertEqual(answers(out.getvalue()), [{"ok": True}])
        self.assertNotIn("weeklyByProduct", self.written())

    def test_a_reading_that_is_not_one_is_refused_whatever_use_by_product_it_carries(self):
        out = io.BytesIO()
        serve(io.BytesIO(frame(message(v=2, by_product=split()))), out, self.folder)
        self.assertFalse(answers(out.getvalue())[0]["ok"])
        self.assertFalse(self.folder.exists())


class ReportTest(unittest.TestCase):
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

    def ingest(self, *sent: dict) -> None:
        """Each reading written over the organization's file and read, the file given a time of its own so that one
        of the same size is not taken for the one already read."""
        for index, one in enumerate(sent):
            serve(io.BytesIO(frame(one)), io.BytesIO(), self.folder)
            path = self.folder / f"{one['org']}.json"
            os.utime(path, (NOW - 100 + index, NOW - 100 + index))
            ingest_browser(self.ledger, self.folder, self.orgs, NOW)

    def test_a_report_is_its_products_in_the_pages_order_beside_the_weekly_figure_it_came_with(self):
        self.ingest(message(weekly=75, by_product=split()))
        [report] = products.reports(self.ledger, ACCOUNT_A)
        self.assertEqual((report.account_uuid, report.ref, report.t, report.as_of, report.window_start, report.weekly),
                         (ACCOUNT_A, ORG_A, NOW, NOW - 30, START, 75.0))
        self.assertEqual([(s.key, s.name, s.percent) for s in report.shares], [tuple(r) for r in SPLIT])
        self.assertEqual([s.name for s in report.used], ["Claude Code", "Chats"])
        self.assertEqual(products.shares_text(report.used), "Claude Code 99%, Chats 1%")

    def test_a_report_received_twice_is_kept_once_and_a_later_one_beside_it(self):
        self.ingest(message(by_product=split()), message(t=NOW + 5, by_product=split()),
                    message(t=NOW + 60, by_product=split(as_of=NOW + 50, rows=(("claude_code", "Claude Code", 98),
                                                                                ("chat", "Chats", 2)))))
        found = products.reports(self.ledger, ACCOUNT_A)
        self.assertEqual([(r.as_of, len(r.shares)) for r in found], [(NOW - 30, 4), (NOW + 50, 2)])

    def test_a_report_received_again_with_a_product_added_stands_as_the_first_reading_that_carried_it(self):
        self.ingest(message(weekly=61, by_product=split(rows=SPLIT[:2])),
                    message(t=NOW + 5, weekly=62, by_product=split(rows=(SPLIT[2],) + SPLIT[:2])))
        [report] = products.reports(self.ledger, ACCOUNT_A)
        self.assertEqual((report.t, report.weekly), (NOW, 61.0))
        self.assertEqual([s.key for s in report.shares], ["claude_code", "chat", "cowork"])

    def test_the_historys_columns_follow_the_latest_reports_order_then_older_products(self):
        self.ingest(message(by_product=split(as_of=NOW - 8 * 86400, start=START - WEEK,
                                             rows=SPLIT[:2] + (("design", "Design", 0),))),
                    message(t=NOW + 5, by_product=split(rows=(SPLIT[2], SPLIT[1], SPLIT[0]))))
        table = history.product_table(self.ledger, [history.Entity(ACCOUNT_A, "alpha", "series-1")], 0, NOW + 60)
        self.assertEqual([name for _, name in table.products], ["Cowork", "Chats", "Claude Code", "Design"])

    def test_a_report_of_an_organization_registered_later_gets_its_account_then(self):
        self.ingest(message(org=ORG_B, by_product=split()))
        self.assertEqual(products.reports(self.ledger, ACCOUNT_B), [])
        self.machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        ingest_browser(self.ledger, self.folder, by_org(registry), NOW)
        self.assertEqual(len(products.reports(self.ledger, ACCOUNT_B)), 1)

    def test_the_current_report_is_of_the_weekly_window_in_effect(self):
        self.ingest(message(by_product=split()))
        cases = {
            "the window its exact reset time ends": (NOW, RESET, True, True),
            "a reset time inferred hours off": (NOW, RESET + 5 * 3600, False, True),
            "no reset time": (NOW, None, False, True),
            "a reset granted outside the schedule": (NOW, NOW + WEEK - 3600, True, False),
            "a window that has ended": (RESET + 60, RESET + WEEK, True, False),
        }
        for case, (now, resets_at, exact, current) in cases.items():
            with self.subTest(case):
                report = products.current(self.ledger, ACCOUNT_A, now, resets_at, exact)
                self.assertEqual(report is not None, current)

    def test_each_window_stands_by_its_last_report_whatever_its_start_jitters(self):
        self.ingest(message(by_product=split(as_of=NOW - 3600)),
                    message(t=NOW + 1, by_product=split(as_of=NOW - 30, start=START - 0.74)),
                    message(t=NOW + 2, by_product=split(as_of=NOW + 100, start=START + WEEK)))
        last = products.last_of_windows(self.ledger, ACCOUNT_A, NOW - WEEK, NOW + WEEK)
        self.assertEqual([r.as_of for r in last], [NOW - 30, NOW + 100])


class OlderLedgerTest(unittest.TestCase):
    """A ledger last opened by code that predates the use by product has no table for it."""

    def setUp(self):
        self.machine = Machine()
        path = self.machine.paths.ledger_db
        Ledger.open(path).close()
        connection = sqlite3.connect(str(path))
        connection.execute("DROP TABLE product_shares")
        connection.commit()
        connection.close()

    def tearDown(self):
        self.machine.close()

    def test_it_reads_as_no_report_and_gains_the_table_on_the_next_open_at_the_same_version(self):
        path = self.machine.paths.ledger_db
        reader = Ledger.open_readonly(path)
        try:
            self.assertFalse(reader.has_table(products.TABLE))
            self.assertEqual(products.reports(reader, ACCOUNT_A), [])
            self.assertEqual(history.product_table(reader, [history.Entity(ACCOUNT_A, "alpha", "series-1")], 0, NOW),
                             history.ProductTable((), ()))
        finally:
            reader.close()
        writer = Ledger.open(path)
        try:
            self.assertTrue(writer.has_table(products.TABLE))
            self.assertEqual(writer.get_meta("schema_version"), str(SCHEMA_VERSION))
            self.assertEqual(SCHEMA_VERSION, 1)
        finally:
            writer.close()


class LivePathTest(unittest.TestCase):
    """Beta, last seen by the desktop app yesterday, is read through claude.ai's page in a browser."""

    def setUp(self):
        self.machine = Machine()
        m = self.machine
        m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        m.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        m.app_history([(NOW - 86400 - 1800, ORG_B, 30, 70), (NOW - 86400, ORG_B, 40, 72)])

    def tearDown(self):
        self.machine.close()

    def beta(self) -> dict:
        doc = json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))
        return {a["label"]: a for a in doc["accounts"]}["beta"]

    def browse(self, by_product: dict | None) -> None:
        serve(io.BytesIO(frame(message(org=ORG_B, t=NOW - 120, weekly=75, by_product=by_product))), io.BytesIO(),
              self.machine.paths.browser_dir)

    def test_a_pass_gives_the_weekly_window_its_use_by_product_and_the_page_shows_it(self):
        self.browse(split())
        report = run_pass(self.machine.paths, NOW, dashboard=True)
        self.assertEqual(report.errors, [])
        weekly = self.beta()["weekly"]
        self.assertEqual(weekly["percent"], 75.0)
        self.assertEqual(epoch(weekly["byProduct"]["asOf"]), NOW - 30)
        self.assertEqual(weekly["byProduct"]["rows"], [{"key": k, "name": n, "percent": p} for k, n, p in SPLIT])
        self.assertNotIn("byProduct", self.beta()["fiveHour"])
        page = self.machine.paths.dashboard_file.read_text(encoding="utf-8")
        self.assertIn("Claude Code 99%, Chats 1%", page)
        self.assertIn("Window from", page)

    def test_without_a_report_the_status_and_the_page_are_as_before(self):
        self.browse(None)
        run_pass(self.machine.paths, NOW, dashboard=True)
        self.assertNotIn("byProduct", self.beta()["weekly"])
        page = self.machine.paths.dashboard_file.read_text(encoding="utf-8")
        self.assertNotIn("by product", page)
        self.assertNotIn("Window from", page)

    def test_a_report_of_a_window_that_has_ended_is_history_not_status(self):
        self.browse(split(as_of=START - 600, start=START - WEEK))
        run_pass(self.machine.paths, NOW, dashboard=True)
        self.assertNotIn("byProduct", self.beta()["weekly"])
        self.assertIn("Window from", self.machine.paths.dashboard_file.read_text(encoding="utf-8"))


class WindowTest(unittest.TestCase):
    def card(self, by_product) -> object:
        weekly = status_window("current", 69.0, NOW + 3 * 86400, NOW - 60, anchor_exact=True)
        if by_product is not None:
            weekly["byProduct"] = by_product
        doc = status_document([status_account(ACCOUNT_A, EMAIL_A, at=NOW, weekly=weekly)], at=NOW)
        snapshot = snapshot_of(Path("status.json"), json.dumps(doc))
        self.assertIsNone(snapshot.problem)
        return live_view(snapshot, NOW).cards[0]

    def test_the_weekly_line_ends_with_the_shares_above_zero_and_the_reports_age(self):
        card = self.card({"asOf": page_time(NOW - 300), "rows": [{"key": k, "name": n, "percent": p}
                                                                 for k, n, p in SPLIT]})
        self.assertEqual(card.weekly.products, "by product 5m ago: Claude Code 99%, Chats 1%")
        self.assertEqual(card.five_hour.products, "")

    def test_none_or_one_not_in_its_shape_shows_nothing_and_the_card_reads_as_before(self):
        plain = self.card(None)
        for case, value in {"absent": None, "no time": {"rows": []}, "rows not a list": {"asOf": page_time(NOW),
                            "rows": 3}, "a row without a name": {"asOf": page_time(NOW), "rows": [{"percent": 9}]},
                            "a row without a key": {"asOf": page_time(NOW), "rows": [{"name": "Chats", "percent": 9}]},
                            "no share above zero": {"asOf": page_time(NOW), "rows": [{"key": "chat", "name": "Chats",
                                                                                       "percent": 0}]}}.items():
            with self.subTest(case):
                card = self.card(value)
                self.assertEqual(card.weekly.products, "")
                self.assertEqual((card.weekly.figure, card.weekly.detail, card.weekly.note),
                                 (plain.weekly.figure, plain.weekly.detail, plain.weekly.note))


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.machine = Machine()
        self.machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        registry, _ = load_registry(self.machine.paths.accounts_dir)
        self.registry = registry
        for sent in (message(t=NOW - 8 * 86400, by_product=split(as_of=NOW - 8 * 86400, start=START - WEEK,
                                                                 rows=SPLIT[:2])),
                     message(by_product=split(rows=SPLIT + (("design", "Design", 0),)))):
            serve(io.BytesIO(frame(sent)), io.BytesIO(), self.machine.paths.browser_dir)
            ingest_browser(self.ledger, self.machine.paths.browser_dir, by_org(registry), NOW)

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def test_the_table_has_a_row_per_window_and_a_column_per_product_in_claudes_order(self):
        table = history.product_table(self.ledger, history.entities(self.ledger, self.registry), NOW - 30 * 86400, NOW)
        self.assertEqual(history.product_columns(table), ("Account", "Window from", "Weekly", "Claude Code", "Chats",
                                                          "Cowork", "Other", "Design", "Reported"))
        first, second = (history.product_cells(table, row) for row in table.rows)
        self.assertEqual(first[2:8], ("61%", "99% · 60 pts", "1% · 1 pt", "—", "—", "—"))
        self.assertEqual(second[2:8], ("61%", "99% · 60 pts", "1% · 1 pt", "0%", "0%", "0%"))
        self.assertEqual(first[1], history.moment_text(START - WEEK))

    def test_the_window_shows_it_under_the_weekly_chart_and_nothing_without_it(self):
        h = history.history(self.ledger, self.registry, history.SPAN_OF["30d"], NOW, billing=None, errors=[])
        found = history_model.blocks(h)
        weekly = found.index(Heading(history.WEEKLY_HEADING, history.PRODUCTS_NOTE))
        table = next(i for i, b in enumerate(found) if isinstance(b, Table) and b.columns[1] == ("Window from", "w"))
        self.assertGreater(table, weekly)
        self.assertNotIn(Note(history.PRODUCTS_NOTE), found, "what the table means is the heading's hint alone")
        empty = history_model._product_blocks(history.ProductTable((), ()))
        self.assertEqual(empty, [])

    def test_each_share_stands_beside_the_points_of_the_weekly_limit_it_stands_for(self):
        table = history.product_table(self.ledger, history.entities(self.ledger, self.registry), NOW - 30 * 86400, NOW)
        second = history.product_cells(table, table.rows[1])
        self.assertEqual(second[3:8], ("99% · 60 pts", "1% · 1 pt", "0%", "0%", "0%"))   # 61 % of the week

    def test_points_are_whole_below_one_said_so_and_absent_where_they_cannot_be_known(self):
        self.assertEqual(history.share_text(15, 54), "15% · 8 pts")
        self.assertEqual(history.share_text(99, 92), "99% · 91 pts")
        self.assertEqual(history.share_text(1, 92), "1% · 1 pt")
        self.assertEqual(history.share_text(1, 30), "1% · <1 pt")
        self.assertEqual(history.share_text(0, 92), "0%")
        self.assertEqual(history.share_text(15, None), "15%")


if __name__ == "__main__":
    unittest.main()
