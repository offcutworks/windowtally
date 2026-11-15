"""An account with no 5-hour limit: read off its readings, and shown and judged by its weekly window alone.

Anthropic removes the 5-hour limit account by account; from then on the server sends that account's weekly window
alone, and every source leaves out the window it was not sent. Claude Code already hands on such a reading for a moment
where a 5-hour window has just ended (measured on the development machine, 2026-10), so one reading, or two seconds
apart, removes nothing; readings without the window across ``NO_LIMIT_SPAN`` do, and the next reading that carries a
5-hour figure restores the limit.
"""

import json
import unittest
from pathlib import Path

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bridge_line,
                      epoch, iso, status_account, status_document, status_window, user_line)
from windowtally.__main__ import format_status
from windowtally.accounts import Account
from windowtally.dashboard import AccountView, _cards
from windowtally.ledger import Ledger
from windowtally.limits import (NO_LIMIT_SPAN, AccountStanding, WindowStanding, account_standing, five_hour_removed,
                                recommend)
from windowtally.service import run_pass
from windowtally.status_file import status_document as written_status
from windowtally_gui.formatting import when
from windowtally_gui.live_model import live_view, tray_view
from windowtally_gui.status_model import snapshot_of
from windowtally_gui.logo_model import FIVE_HOUR, TRACK, WEEKLY, geometry, rgba
from windowtally_gui.tray_model import icon_rows

T0 = epoch("2026-11-02T10:00:00Z")
WEEK_RESET = T0 + 3 * 86400


class RemovedTest(unittest.TestCase):
    """Readings written row by row: one reading's windows share its source, reference and moment."""

    def setUp(self):
        self.machine = Machine()
        self.ledger = Ledger.open(self.machine.paths.ledger_db)
        self.responses = 0

    def tearDown(self):
        self.ledger.close()
        self.machine.close()

    def reading(self, t, *, five_hour=None, weekly=40.0, source="plugin", ref="s1"):
        for kind, percent, resets in (("five_hour", five_hour, t + 3600), ("seven_day", weekly, WEEK_RESET)):
            if percent is not None:
                self.ledger.db.execute(
                    "INSERT INTO observations(source, ref, t, kind, percent, resets_at, account_uuid, account_source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'test')", (source, ref, t, kind, float(percent), resets, ACCOUNT_A))

    def response(self, t, dollars=1.0):
        self.responses += 1
        self.ledger.db.execute(
            "INSERT INTO responses(message_id, t, session_id, input_tokens, output_tokens, thinking_tokens, "
            "cache_read_tokens, cache_write_5m_tokens, cache_write_1h_tokens, web_search_requests, web_fetch_requests, "
            "cost_usd, account_uuid) VALUES (?, ?, 's', 0, 0, 0, 0, 0, 0, 0, 0, ?, ?)",
            (f"m{self.responses}", t, dollars, ACCOUNT_A))

    def removed(self):
        return five_hour_removed(self.ledger, ACCOUNT_A)

    def test_while_readings_carry_the_window_the_limit_holds(self):
        self.reading(T0, five_hour=20)
        self.reading(T0 + NO_LIMIT_SPAN + 60, five_hour=30)
        self.assertIsNone(self.removed())

    def test_one_reading_without_the_window_removes_nothing(self):
        # As measured: a reading with the weekly window alone where a 5-hour window had just ended.
        self.reading(T0, five_hour=73)
        self.reading(T0 + 3, five_hour=None)
        self.assertIsNone(self.removed())

    def test_two_readings_seconds_apart_remove_nothing(self):
        self.reading(T0, five_hour=73)
        self.reading(T0 + 3, five_hour=None, ref="s1")
        self.reading(T0 + 5, five_hour=None, ref="s2")
        self.assertIsNone(self.removed())

    def test_readings_without_the_window_across_the_span_remove_it(self):
        self.reading(T0, five_hour=20)
        self.reading(T0 + 60, five_hour=None)
        self.reading(T0 + 60 + NO_LIMIT_SPAN, five_hour=None, ref="s2")
        self.assertEqual(self.removed(), T0 + 60 + NO_LIMIT_SPAN)

    def test_short_of_the_span_the_limit_holds(self):
        self.reading(T0, five_hour=20)
        self.reading(T0 + 60, five_hour=None)
        self.reading(T0 + NO_LIMIT_SPAN, five_hour=None)
        self.assertIsNone(self.removed())

    def test_every_source_counts(self):
        # An app sample whose 5-hour figure is absent is ingested as its weekly figure alone.
        self.reading(T0, five_hour=20, source="app", ref=ORG_A)
        self.reading(T0 + 60, five_hour=None, source="app", ref=ORG_A)
        self.reading(T0 + 60 + NO_LIMIT_SPAN, five_hour=None, source="browser", ref=ORG_A)
        self.assertEqual(self.removed(), T0 + 60 + NO_LIMIT_SPAN)

    def test_an_account_never_read_with_the_window_has_none(self):
        self.reading(T0, five_hour=None)
        self.reading(T0 + NO_LIMIT_SPAN, five_hour=None)
        self.assertEqual(self.removed(), T0 + NO_LIMIT_SPAN)

    def test_a_reading_that_carries_the_window_again_restores_it(self):
        self.reading(T0, five_hour=None)
        self.reading(T0 + NO_LIMIT_SPAN, five_hour=None)
        self.reading(T0 + NO_LIMIT_SPAN + 60, five_hour=5)
        self.assertIsNone(self.removed())

    def test_another_account_s_readings_say_nothing_of_this_one(self):
        self.reading(T0, five_hour=None)
        self.ledger.db.execute(
            "INSERT INTO observations(source, ref, t, kind, percent, resets_at, account_uuid, account_source) "
            "VALUES ('plugin', 'other', ?, 'seven_day', 10, NULL, ?, 'test')", (T0 + NO_LIMIT_SPAN, ACCOUNT_B))
        self.assertIsNone(self.removed())

    def test_with_no_limit_nothing_is_inferred_from_the_responses(self):
        # The window rule applied to these responses would open a window at the first of them and estimate a rise.
        self.reading(T0 - 86400, five_hour=50)
        self.reading(T0, five_hour=None)
        self.reading(T0 + NO_LIMIT_SPAN, five_hour=None, ref="s2")
        for minutes in range(20, 60, 5):
            self.response(T0 + NO_LIMIT_SPAN + minutes * 60, 2.0)
        now = T0 + NO_LIMIT_SPAN + 3600
        s = account_standing(self.ledger, Account(ACCOUNT_A, EMAIL_A), now)
        w = s.five_hour
        self.assertEqual((w.state, w.percent, w.resets_at, w.exhausts_at, w.estimated, w.as_of),
                         ("no_limit", None, None, None, False, T0 + NO_LIMIT_SPAN))
        self.assertEqual((s.weekly.state, s.weekly.percent), ("current", 40.0))

    def test_with_the_limit_the_responses_still_open_a_window(self):
        # The same responses after one reading without the window: the limit holds, and so does the window rule.
        self.reading(T0 - 86400, five_hour=50)
        self.reading(T0, five_hour=None)
        for minutes in range(20, 60, 5):
            self.response(T0 + minutes * 60, 2.0)
        w = account_standing(self.ledger, Account(ACCOUNT_A, EMAIL_A), T0 + 3600).five_hour
        self.assertEqual((w.state, w.resets_at), ("running", T0 + 20 * 60 + 5 * 3600))


def standing(uuid, label, *, weekly, five_hour=None, resets=WEEK_RESET):
    five = five_hour or WindowStanding("five_hour", "no_limit", None, None, T0, False)
    week = WindowStanding("seven_day", "current", weekly, resets, T0, False, reset_exact=True)
    return AccountStanding(Account(uuid, f"{label}@example.com"), five, week, None, T0, False, False)


class RecommendTest(unittest.TestCase):
    def test_an_account_with_no_limit_is_judged_by_its_week(self):
        free = standing(ACCOUNT_A, "alpha", weekly=50.0)
        busy = standing(ACCOUNT_B, "beta", weekly=10.0, resets=WEEK_RESET + 86400,
                        five_hour=WindowStanding("five_hour", "running", 92.0, T0 + 3600, T0, False))
        self.assertEqual(recommend([free, busy]).account_uuid, ACCOUNT_A)

    def test_its_week_past_the_ceiling_keeps_it_from_being_recommended(self):
        full = standing(ACCOUNT_A, "alpha", weekly=96.0)
        room = standing(ACCOUNT_B, "beta", weekly=10.0, resets=WEEK_RESET + 86400,
                        five_hour=WindowStanding("five_hour", "running", 20.0, T0 + 3600, T0, False))
        self.assertEqual(recommend([full, room]).account_uuid, ACCOUNT_B)

    def test_when_room_returns_it_waits_for_its_week(self):
        near = standing(ACCOUNT_A, "alpha", weekly=97.0)
        recommendation = recommend([near])
        self.assertEqual((recommendation.account_uuid, recommendation.relief_at), (ACCOUNT_A, WEEK_RESET))


class StatusTest(unittest.TestCase):
    def document(self):
        a = standing(ACCOUNT_A, "alpha", weekly=50.0)
        return written_status([a], recommend([a]), now=T0, desktop_account=ACCOUNT_A, cli_account=ACCOUNT_A,
                              cli_condition=None)

    def test_the_status_file_keeps_the_window_and_says_there_is_no_limit(self):
        five = self.document()["accounts"][0]["fiveHour"]
        self.assertEqual(five, {"state": "no_limit", "percent": None, "resetsAt": None, "asOf": iso(T0),
                                "estimated": False, "exhaustsAt": None, "anchorExact": False})

    def test_the_status_command_leads_with_the_week(self):
        lines = format_status(self.document()).splitlines()
        self.assertTrue(lines[1].startswith("    weekly : 50%"), lines)
        self.assertEqual(lines[2], "    5-hour : no limit on this account")

    def test_the_history_page_s_card_leads_with_the_week(self):
        a = standing(ACCOUNT_A, "alpha", weekly=50.0)
        html = _cards([a], {ACCOUNT_A: AccountView(ACCOUNT_A, "alpha", "var(--s1)")}, recommend([a]), T0)
        self.assertLess(html.index(">Weekly<"), html.index(">5-hour<"))
        self.assertIn('<i class="key off"></i>5-hour</span><span><b>no limit</b></span></div>', html)
        self.assertIn('<div class="line"><i class="key off"></i>this account has no 5-hour limit</div>', html)
        self.assertNotIn(" · this account has no 5-hour limit", html)


def window_document(**changes):
    no_limit = status_window("no_limit", None, None, as_of=T0 - 60)
    alpha = status_account(ACCOUNT_A, EMAIL_A, at=T0, five_hour=no_limit,
                           weekly=status_window("current", 75.0, T0 + 3 * 86400, as_of=T0 - 60, anchor_exact=True))
    beta = status_account(ACCOUNT_B, EMAIL_B, at=T0, desktop=False, cli=False)
    return status_document([alpha, beta], at=T0, **changes)


def snapshot(doc):
    return snapshot_of(Path("status.json"), json.dumps(doc))


class WindowTest(unittest.TestCase):
    def test_the_card_leads_with_the_week_and_says_there_is_no_limit(self):
        alpha, beta = live_view(snapshot(window_document()), T0 + 30).cards
        self.assertEqual([w.name for w in alpha.windows], ["Weekly", "5-hour"])
        five = alpha.windows[1]
        self.assertEqual((five.figure, five.level, five.fraction, five.detail, five.note),
                         ("no limit", 0, 0.0, "", ""), "its name and no limit alone: no second line")
        self.assertEqual([w.name for w in beta.windows], ["5-hour", "Weekly"])

    def test_the_tray_leads_with_the_week_and_draws_its_meter_alone(self):
        tray = tray_view(snapshot(window_document()), T0 + 30)
        self.assertIn(f"alpha (app, CLI)  week 75% ↻{when(T0 + 3 * 86400)} · 5h no limit", tray.tooltip)
        self.assertEqual((tray.weekly_only, tray.five_hour, tray.weekly, tray.level), (True, None, 0.75, 1))

    def test_a_stale_status_greys_the_one_meter_rather_than_drawing_two(self):
        tray = tray_view(snapshot(window_document()), T0 + 3600)
        self.assertEqual((tray.level, tray.weekly_only), (-1, True))

    def test_the_weekly_ring_alone_is_as_thick_as_both_rings(self):
        two = icon_rows(32, "#2a78d6", "#fab219", "#d03b3b", five_hour=0.0, weekly=1.0)
        one = icon_rows(32, "#2a78d6", "#fab219", "#d03b3b", five_hour=None, weekly=1.0, weekly_only=True)
        shape = geometry(32)
        middle = 16

        def below_centre(rows, band):
            return rows[middle + int(sum(band) / 2)][middle]

        self.assertEqual(below_centre(two, shape.outer), rgba(WEEKLY))
        self.assertEqual(below_centre(two, shape.inner), rgba(TRACK), "the 5-hour ring, not started")
        self.assertEqual(below_centre(one, shape.outer), rgba(WEEKLY))
        self.assertEqual(below_centre(one, shape.inner), rgba(WEEKLY), "the one ring reaches the inner ring's place")
        gap = (shape.inner[1], shape.outer[0])
        self.assertEqual(below_centre(one, gap), rgba(WEEKLY), "and covers the gap between the two")
        self.assertNotIn(rgba(FIVE_HOUR), {pixel for row in one for pixel in row})
        blue_in = lambda rows: sum(pixel == rgba(WEEKLY) for row in rows for pixel in row)
        self.assertLess(blue_in(two), blue_in(one))


class LivePathTest(unittest.TestCase):
    """Account A's readings stop carrying the 5-hour window — the plugin's and the desktop app's alike — while A is
    used; account B's still carry it."""

    def setUp(self):
        self.machine = m = Machine()
        self.now = now = epoch("2026-11-02T20:00:00Z")
        m.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
        m.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
        m.sync_events([(now - 7200, "desktop_account", ACCOUNT_A), (now - 7100, "cli_account", ACCOUNT_A)])
        m.watch_view(ACCOUNT_A, ACCOUNT_A)
        m.app_history([(now - 3 * 3600, ORG_A, 30, 50), (now - 3000, ORG_A, None, 52), (now - 86400, ORG_B, 40, 72)])
        m.transcript("desk", [bridge_line("desk", ACCOUNT_A, ORG_A), user_line("desk", "p1", now - 900)]
                     + assistant_lines("d1", now - 890, "desk") + assistant_lines("d2", now - 300, "desk"))
        m.paths.readings_dir.mkdir(parents=True, exist_ok=True)
        (m.paths.readings_dir / "desk.json").write_text(json.dumps({"v": 1, "t": int((now - 120) * 1000),
            "sessionId": "desk", "windows": [{"kind": "seven_day", "percentUsed": 55,
                                              "resetsAt": iso(now + 4 * 86400)}]}), encoding="utf-8")

    def tearDown(self):
        self.machine.close()

    def test_a_pass_writes_no_limit_and_the_command_line_leads_with_the_week(self):
        report = run_pass(self.machine.paths, self.now, dashboard=True)
        self.assertEqual(report.errors, [])
        doc = json.loads(self.machine.paths.status_file.read_text(encoding="utf-8"))
        by_label = {a["label"]: a for a in doc["accounts"]}
        alpha, beta = by_label["alpha"], by_label["beta"]
        self.assertEqual((alpha["fiveHour"]["state"], alpha["fiveHour"]["percent"]), ("no_limit", None))
        self.assertEqual(alpha["weekly"]["percent"], 55.0)
        self.assertEqual(beta["fiveHour"]["state"], "not_started")
        self.assertIn("no limit", self.machine.paths.dashboard_file.read_text(encoding="utf-8"))
        status = format_status(doc)
        self.assertLess(status.index("alpha"), status.index("    weekly : 55%"))
        self.assertLess(status.index("    weekly : 55%"), status.index("    5-hour : no limit on this account"))


if __name__ == "__main__":
    unittest.main()
