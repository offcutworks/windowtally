"""The sections shown in one of two views at a time — the cost or the token chart, the token tables by week or by
month, a full window by plan or by week — in the History window's blocks, on the page and in the export, and in the
window itself, headless: which view stands first, what a choice shows, and that the window keeps a choice through
another span and into its export."""

import re
import tempfile
import time
import unittest
from html import escape
from pathlib import Path

from qt_support import APP

from PySide6.QtCore import Qt

from fixtures import (ACCOUNT_A, ACCOUNT_B, EMAIL_A, EMAIL_B, ORG_A, ORG_B, Machine, assistant_lines, bill,
                      bridge_line)
from windowtally import history
from windowtally.dashboard import render_history
from windowtally.service import run_pass
from windowtally_gui import history_model
from windowtally_gui.history_model import Heading, Note, Switch, Table
from windowtally_gui.history_view import HistoryWindow
from windowtally_gui.table_view import TableView
from windowtally_gui.theme_view import Theme

NOW = time.time()
DAY = 86400.0
KEYS = (history.COLUMNS_SWITCH, history.TOKEN_TABLES_SWITCH, history.CAPACITY_SWITCH)


def seeded() -> Machine:
    """Two accounts answering on alternate days for twenty days, and a plan billed today, so every section has its
    figures."""
    machine = Machine()
    machine.add_account(ACCOUNT_A, EMAIL_A, ORG_A)
    machine.add_account(ACCOUNT_B, EMAIL_B, ORG_B)
    machine.app_history([(NOW - 20 * DAY + i * 3 * 3600, org, 30.0, (i % 50) * 1.8)
                         for i in range(150) for org in (ORG_A, ORG_B)])
    events = []
    for day in range(20):
        session = f"s{day}"
        owner = ACCOUNT_A if day % 2 else ACCOUNT_B
        answered = NOW - (20 - day) * DAY + 600
        events.append((answered - 60, "desktop_account", owner))
        machine.transcript(session, [bridge_line(session, owner, ORG_A)]
                           + assistant_lines(f"m{day}", answered, session))
    machine.sync_events(events)
    today = time.strftime("%Y-%m-%d", time.gmtime(NOW))
    machine.bills_file([bill(EMAIL_A, today, 90.0, plan="max5x", period=f"{today}..2099-01-01")])
    run_pass(machine.paths, now=NOW, dashboard=True)
    return machine


def switches(blocks) -> dict[str, Switch]:
    return {b.key: b for b in blocks if isinstance(b, Switch)}


class SwitchedBlocksTest(unittest.TestCase):
    """The window's blocks and the page's markup, without a display."""

    @classmethod
    def setUpClass(cls):
        cls.machine = seeded()
        cls.month = history_model.compute(cls.machine.paths, "30d", now=NOW)
        cls.half_year = history_model.compute(cls.machine.paths, "6mo", now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls.machine.close()

    def test_each_switch_stands_where_its_two_sections_stood(self):
        blocks = list(history_model.blocks(self.month))
        found = [b.key for b in blocks if isinstance(b, Switch)]
        self.assertEqual(found, list(KEYS))
        at = {b.key: i for i, b in enumerate(blocks) if isinstance(b, Switch)}
        heading = {b.text: i for i, b in enumerate(blocks) if isinstance(b, Heading)}
        family = min(i for text, i in heading.items() if text.endswith(" cost by model family"))
        self.assertLess(heading[history.WEEKLY_HEADING], at[history.COLUMNS_SWITCH])
        self.assertLess(at[history.COLUMNS_SWITCH], family)
        self.assertLess(family, at[history.TOKEN_TABLES_SWITCH])
        self.assertLess(at[history.TOKEN_TABLES_SWITCH], heading["Subscriptions"])
        self.assertLess(heading[history.GAPS_HEADING], at[history.CAPACITY_SWITCH])
        self.assertLess(at[history.CAPACITY_SWITCH], heading[history.EXHAUSTED_HEADING])
        for text in ("Tokens per day", "Tokens by week", "Tokens by month", "API-equivalent cost per day",
                     history.CAPACITY_HEADING, "Full window, by week"):
            self.assertNotIn(text, heading, "a view's heading stands in its switch, never beside it")

    def test_each_view_has_the_switch_s_word_its_heading_and_its_blocks(self):
        found = switches(history_model.blocks(self.month))
        for key in KEYS:
            self.assertEqual(tuple(v.choice for v in found[key].views), history.SWITCH_VIEWS[key])
            for view in found[key].views:
                self.assertFalse(any(isinstance(b, (Heading, Switch)) for b in view.blocks), view)
        cost, tokens = found[history.COLUMNS_SWITCH].views
        self.assertEqual(cost.heading, Heading(history.cost_heading("day")))
        self.assertEqual(tokens.heading, Heading(history.tokens_heading("day"), history.TOKENS_NOTE))
        week, month = found[history.TOKEN_TABLES_SWITCH].views
        for view, first in ((week, "Week"), (month, "Month")):
            self.assertEqual(view.heading, Heading(history.TOKENS_BY))
            table, = view.blocks
            self.assertEqual(table.columns[0][0], first)
            self.assertEqual(table.rows[-1][0], "In all")
        by_plan, by_week = found[history.CAPACITY_SWITCH].views
        for view, first in ((by_plan, "Plan"), (by_week, "Week")):
            self.assertEqual(view.heading, Heading(history.CAPACITY_BY, history.CAPACITY_NOTE))
            self.assertEqual(view.blocks[0], Note(history.CAPACITY_CAVEAT), "the caveat before its figures")
            if isinstance(view.blocks[1], Table):
                self.assertEqual(view.blocks[1].columns[0][0], first)
            else:
                self.assertEqual(view.blocks[1], Note(history.SPAN_NO_CAPACITY_WEEKS))

    def test_a_long_span_shows_the_tokens_by_month_first_and_a_short_one_by_week(self):
        for h, tables in ((self.month, "week"), (self.half_year, "month")):
            found = switches(history_model.blocks(h))
            shown = {key: found[key].views[found[key].shown].choice for key in KEYS}
            self.assertEqual(shown, {history.COLUMNS_SWITCH: "Cost", history.TOKEN_TABLES_SWITCH: tables,
                                     history.CAPACITY_SWITCH: "plan"}, h.span.key)

    def test_a_chosen_view_is_shown_and_a_word_no_switch_has_is_not(self):
        chosen = {history.COLUMNS_SWITCH: "Tokens", history.TOKEN_TABLES_SWITCH: "month", history.CAPACITY_SWITCH: "week"}
        found = switches(history_model.blocks(self.month, chosen))
        self.assertEqual({key: found[key].views[found[key].shown].choice for key in KEYS}, chosen)
        found = switches(history_model.blocks(self.half_year, {history.TOKEN_TABLES_SWITCH: "fortnight"}))
        self.assertEqual(found[history.TOKEN_TABLES_SWITCH].shown, 1, "the span's own first view")

    def pane_headings(self, page: str, key: str) -> list[str]:
        start = page.index(f'<input type="radio" name="switch-{key}"')
        end = page.find('<div class="switch">', start)
        end = len(page) if end == -1 else end
        return re.findall(r'<div class="view v\d"><h2>(.*?)</h2>', page[start:end])

    def checked(self, page: str, key: str) -> list[int]:
        return [int(i) for i in re.findall(rf'<input type="radio" name="switch-{key}" id="switch-{key}-(\d)"'
                                           rf' class="v\1" aria-label="[^"]*" checked>', page)]

    def test_the_export_holds_every_view_and_opens_at_the_window_s(self):
        page = render_history(self.half_year)
        for key in KEYS:
            self.assertEqual(page.count(f'<input type="radio" name="switch-{key}"'), len(history.SWITCH_VIEWS[key]))
            shown = switches(history_model.blocks(self.half_year))[key].shown
            self.assertEqual(self.checked(page, key), [shown])
            headings = self.pane_headings(page, key)
            self.assertEqual(len(headings), len(history.SWITCH_VIEWS[key]))
            for index, heading in enumerate(headings):
                labels = re.findall(rf'<label for="switch-{key}-(\d)"( class="on")?>([^<]*)</label>', heading)
                self.assertEqual([(int(i), word) for i, _on, word in labels],
                                 list(enumerate(history.SWITCH_VIEWS[key])))
                self.assertEqual([int(i) for i, on, _word in labels if on], [index], "its own word filled")
        chosen = {history.TOKEN_TABLES_SWITCH: "week", history.CAPACITY_SWITCH: "week"}
        page = render_history(self.half_year, chosen)
        self.assertEqual(self.checked(page, history.TOKEN_TABLES_SWITCH), [0])
        self.assertEqual(self.checked(page, history.CAPACITY_SWITCH), [1])
        self.assertEqual(self.checked(page, history.COLUMNS_SWITCH), [0])

    def test_the_style_sheet_shows_the_checked_view_alone(self):
        page = render_history(self.month)
        self.assertIn(".windowtally .switch > .view { display:none; }", page)
        for index in range(2):
            self.assertIn(f".windowtally .switch > input.v{index}:checked ~ .view.v{index} {{ display:block; }}", page)

    def test_each_view_s_heading_carries_its_own_hint_and_words(self):
        page = render_history(self.half_year)
        cost, tokens = self.pane_headings(page, history.COLUMNS_SWITCH)
        self.assertTrue(cost.startswith(escape(history.cost_heading("week")) + " "), cost)
        self.assertIn(f'title="{escape(history.BY_WEEK_NOTE)}"', cost)
        self.assertTrue(tokens.startswith(escape(history.tokens_heading("week")) + " "), tokens)
        self.assertIn(f'title="{escape(history.TOKENS_NOTE)}"', tokens)
        for heading in self.pane_headings(page, history.TOKEN_TABLES_SWITCH):
            self.assertTrue(heading.startswith(history.TOKENS_BY + " "), heading)
            self.assertNotIn('class="help"', heading)

    def test_the_page_says_each_token_table_s_range_after_the_switch(self):
        page = self.machine.paths.dashboard_file.read_text(encoding="utf-8")
        week, month = self.pane_headings(page, history.TOKEN_TABLES_SWITCH)
        self.assertTrue(week.endswith("</span>, last six weeks"), week)
        self.assertTrue(month.endswith("</span>, whole history"), month)
        self.assertEqual(self.checked(page, history.TOKEN_TABLES_SWITCH), [0])
        for heading in self.pane_headings(page, history.CAPACITY_SWITCH):
            self.assertIn("</span>, last six weeks", heading)


class SwitchWindowTest(unittest.TestCase):
    """The History window on the same machine, on a lane each test ends by hand."""

    class Lane:
        def __init__(self):
            self.jobs = []

        @property
        def running(self):
            return "history" if self.jobs else None

        def start(self, _name, job, deliver, failed):
            if self.jobs:
                return False
            self.jobs.append((job, deliver, failed))
            return True

        def finish(self):
            job, deliver, failed = self.jobs.pop(0)
            try:
                result = job()
            except Exception as exc:
                failed(exc)
            else:
                deliver(result)

    @classmethod
    def setUpClass(cls):
        cls.machine = seeded()
        cls.theme = Theme(APP, "light")

    @classmethod
    def tearDownClass(cls):
        cls.machine.close()

    def setUp(self):
        self.theme.apply("light")
        self.lane = self.Lane()
        self.answer, self.opened = "", []

    def shown(self) -> HistoryWindow:
        window = HistoryWindow(self.theme, self.machine.paths, lambda: (), self.lane,
                               choose_file=lambda _parent, _folder, _name: self.answer, open_url=self.opened.append)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.hide)
        window.open()
        self.lane.finish()
        APP.processEvents()
        return window

    @staticmethod
    def switch(window: HistoryWindow, key: str):
        found = [s for s in window.switches if s.switch.key == key]
        assert len(found) == 1, [s.switch.key for s in window.switches]
        return found[0]

    @staticmethod
    def tables(switch) -> list:
        return [t.table for t in switch.findChildren(TableView) if t.isVisibleTo(switch)]

    def test_a_switch_shows_one_view_and_a_click_shows_the_other(self):
        window = self.shown()
        self.assertEqual([s.switch.key for s in window.switches], list(KEYS))
        tables = self.switch(window, history.TOKEN_TABLES_SWITCH)
        self.assertEqual([b.isChecked() for b in tables.buttons], [True, False])
        self.assertEqual(tables.head.title.text(), history.TOKENS_BY)
        weeks, = [t for t in tables.findChildren(TableView) if t.isVisibleTo(tables)]
        self.assertEqual(weeks.table.columns[0][0], "Week")
        tables.buttons[1].click()
        APP.processEvents()
        self.assertEqual([b.isChecked() for b in tables.buttons], [False, True])
        shown, = self.tables(tables)
        self.assertEqual(shown.columns[0][0], "Month")
        self.assertEqual(window.choices, {history.TOKEN_TABLES_SWITCH: "month"})
        tables.buttons[0].click()
        APP.processEvents()
        again, = [t for t in tables.findChildren(TableView) if t.isVisibleTo(tables)]
        self.assertIs(again, weeks, "a view chosen again is the one left, as it was left")

    def test_the_heading_s_words_and_hint_follow_the_view(self):
        window = self.shown()
        columns = self.switch(window, history.COLUMNS_SWITCH)
        head = columns.head
        self.assertEqual(head.title.text(), history.cost_heading("day"))
        self.assertTrue(head.mark is None or not head.mark.isVisibleTo(window), "no hint for the cost per day")
        cost, = columns.charts
        columns.buttons[1].click()
        APP.processEvents()
        self.assertEqual(head.title.text(), history.tokens_heading("day"))
        self.assertTrue(head.mark.isVisibleTo(window))
        self.assertEqual(head.mark.focusPolicy(), Qt.FocusPolicy.TabFocus)
        self.assertEqual([h.text for h in head.hints], [history.TOKENS_NOTE, history.TOKENS_NOTE])
        tokens, = columns.charts
        self.assertIsNot(tokens, cost)
        self.assertTrue(tokens.isVisibleTo(window))
        self.assertFalse(cost.isVisibleTo(window))
        columns.buttons[0].click()
        APP.processEvents()
        self.assertFalse(head.mark.isVisibleTo(window), "the hint goes with the view that has it")
        self.assertEqual(head.mark.focusPolicy(), Qt.FocusPolicy.NoFocus)

    def test_a_choice_stays_through_another_span_and_into_the_export(self):
        window = self.shown()
        self.switch(window, history.CAPACITY_SWITCH).buttons[1].click()
        window.span_buttons["6mo"].click()
        self.lane.finish()
        APP.processEvents()
        self.assertEqual(window.shown_history.span.key, "6mo")
        capacity = self.switch(window, history.CAPACITY_SWITCH)
        self.assertEqual([b.isChecked() for b in capacity.buttons], [False, True])
        tables = self.switch(window, history.TOKEN_TABLES_SWITCH)
        self.assertEqual([b.isChecked() for b in tables.buttons], [False, True], "never chosen: the span's own first")
        with tempfile.TemporaryDirectory() as folder:
            self.answer = str(Path(folder) / "out.html")
            window.export()
            written = Path(self.answer).read_text(encoding="utf-8")
        self.assertEqual(written, render_history(window.shown_history, {history.CAPACITY_SWITCH: "week"}))
        self.assertNotEqual(written, render_history(window.shown_history))


if __name__ == "__main__":
    unittest.main()
