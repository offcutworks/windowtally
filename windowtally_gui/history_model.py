"""The History view's logic: the history over a span computed from the ledger, which span is asked for and which is
shown, and the view's blocks — headings, the summary's tiles, notes, legends, charts, tables, and the switches that show
one of a section's two views at a time — in the history page's order. No toolkit.

What it shows is the history page's content over the span the user chooses (``windowtally.history``), every figure and
word from the figures layer the page itself draws from; it leaves out what the main window shows live — the account
cards and the recommendation. The computation opens the ledger read-only, reads the user's bills and settings as a
pass does — the accounts named as the user named them, standing in the order they were first seen — and reads no
account profile: the window reads the sync's store only through a pass it runs, so the subscriptions' summary shows
no profile check, which the live cards carry. Where two of WindowTally's accounts share one e-mail, the
subscription takes the page's account, the one whose profile is on this machine, by the accounts the last pass
recorded in the ledger as having one. The source problems listed under Coverage are the ones status.json carries, the
same list the page is written with.

A computation can take seconds over a long span, so it runs off the window's thread, one at a time; the content shown
stays until the next is ready, and the last span chosen wins: a result for a span no longer chosen is dropped and the
chosen one computed instead, and an ask while one runs is followed by one more computation. The history is computed when
the window opens, when a span is chosen and on Recompute, never on a clock.

The history shown is what the window exports as HTML (``export_name``, ``actions_model.export_history``): the span's
sections as the window shows them, each switch at the view the window shows, written by the page's markup
(``windowtally.dashboard.render_history``) and not computed again.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Mapping

from windowtally import history
from windowtally.accounts import named
from windowtally.billing import billing_report, usd_text
from windowtally.bills import load_bills
from windowtally.charts import nice_ceiling
from windowtally.history import History, SPAN_OF
from windowtally.ledger import Ledger
from windowtally.paths import MachinePaths
from windowtally.timeutil import local_datetime

from .plot_model import ColumnPlot, ColumnStack, LinePlot, Marker, Series

DEFAULT_SPAN = "30d"


def compute(paths: MachinePaths, key: str, errors: tuple[str, ...] = (), now: float | None = None) -> History:
    """The history over the span ``key``, read from the ledger and the bills; the ledger is opened read-only."""
    now = time.time() if now is None else now
    ledger = Ledger.open_readonly(paths.ledger_db)
    try:
        bill_set = load_bills(paths)
        accounts = named(ledger.known_accounts(), bill_set.settings.names)
        billing = billing_report(bill_set, accounts, {}, ledger, now, on_machine=ledger.profiles_on_machine())
        return history.history(ledger, accounts, SPAN_OF[key], now, billing=billing, errors=list(errors))
    finally:
        ledger.close()


def export_name(h: History) -> str:
    """The exported file's name the save dialog offers: the span and the local day it is as of."""
    return f"windowtally-history-{h.span.key}-{local_datetime(h.now).date().isoformat()}.html"


# --- which span is asked for, and which is shown ------------------------------------------------------------------------

class Requests:
    """The span chosen, the one being computed, and the history shown. The last choice wins."""

    def __init__(self, key: str = DEFAULT_SPAN):
        self.chosen = key
        self.running: str | None = None
        self.again = False                       # asked for while one ran: compute once more when it ends
        self.shown: History | None = None
        self.failure: str | None = None          # why the chosen span's last computation failed

    def want(self, key: str) -> str | None:
        """``key`` chosen, or asked for again; the span to start computing now, or None while one runs — which is
        then followed by one more computation of the span chosen last, since the running one read the ledger as it
        was before the ask."""
        self.chosen = key
        if self.running is not None:
            self.again = True
            return None
        self.running, self.again = key, False
        return key

    def done(self, key: str, result: History | None = None, failure: str | None = None) -> str | None:
        """A computation of ``key`` ended with ``result`` or ``failure``; the span to start next, or None. A result
        for a span no longer chosen is dropped."""
        self.running = None
        if key == self.chosen:
            if result is not None:
                self.shown, self.failure = result, None
            else:
                self.failure = failure
        if key != self.chosen or self.again:
            return self.want(self.chosen)
        return None

    def status(self) -> tuple[str, bool]:
        """The line above the content, and whether it says something failed."""
        if self.running is not None:
            return f"Computing {SPAN_OF[self.chosen].words}…", False
        if self.failure is not None:
            return f"Not computed: {self.failure}", True
        if self.shown is not None:
            h = self.shown
            return (f"{h.span.label} from {history.day_text(h.first)} · as of {history.weekday_clock(h.now)}"
                    + ("" if h.span.key == self.chosen else f"; {SPAN_OF[self.chosen].label} not shown yet")), False
        return "", False


# --- the view's blocks --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Heading:
    text: str
    hint: str = ""                               # what the section's figures mean: behind the heading, never at rest


@dataclass(frozen=True)
class Note:
    text: str                                    # state: an empty section, a caveat the figures need, a setting


@dataclass(frozen=True)
class Legend:
    items: tuple[tuple[str, str], ...]           # (label, palette token)
    marks: tuple[tuple[str, str], ...] = ()      # the line chart's reset markers, explained: (words, shape)


@dataclass(frozen=True)
class Chart:
    plot: LinePlot | ColumnPlot
    height: float                                # in lines of the default font


@dataclass(frozen=True)
class Table:
    columns: tuple[tuple[str, str], ...]         # (heading, alignment: w for words, e for figures)
    rows: tuple[tuple[str, ...], ...]
    totals: tuple[int, ...] = ()                 # rows set in bold


@dataclass(frozen=True)
class Bullets:
    items: tuple[str, ...]


@dataclass(frozen=True)
class Tiles:
    items: tuple[tuple[str, str], ...]           # (caption, figure), in a row wrapping where the width ends
    bars: tuple[tuple[float, str] | None, ...] = ()   # per item: (share 0 to 1, palette token) drawn under it, or None


@dataclass(frozen=True)
class View:
    """One of a switched section's views."""
    choice: str                                  # its word on the switch
    heading: Heading                             # the words before the switch, and the view's hint
    blocks: tuple[Block, ...]                    # notes, legends, charts and tables, never a heading


@dataclass(frozen=True)
class Switch:
    """A section shown in one of its views at a time, the switch beside its heading choosing."""
    key: str                                     # a key of ``history.SWITCH_VIEWS``
    views: tuple[View, ...]                      # in the switch's order
    shown: int                                   # the view shown until another is chosen


Block = Heading | Note | Legend | Chart | Table | Bullets | Tiles | Switch

WORDS, FIGURES = "w", "e"


def _weekly_blocks(h: History) -> list[Block]:
    usage = h.weekly
    blocks: list[Block] = [Heading(history.WEEKLY_HEADING, history.PRODUCTS_NOTE if h.products.rows else "")]
    if not usage.lines:
        return blocks + [Note(history.SPAN_NO_WEEKLY)] + _product_blocks(h.products) + _reset_blocks(h.resets)
    markers = tuple(Marker(r.after, r.value, r.entity.token, history.reset_words(r), history.RESET_MARKS[r.kind])
                    for r in usage.resets)
    plot = LinePlot(tuple(Series(line.entity.label, line.entity.token, line.points) for line in usage.lines), markers,
                    (usage.start, usage.end), (0.0, 100.0), history.time_ticks(usage.start, usage.end),
                    tuple((v, f"{v:.0f}%") for v in (0.0, 25.0, 50.0, 75.0, 100.0)), history.LINE_BREAK)
    legend = Legend(tuple((line.entity.label, line.entity.token) for line in usage.lines), history.reset_legend(usage))
    return blocks + [legend, Chart(plot, 13)] + _product_blocks(h.products) + _reset_blocks(h.resets)


def _reset_blocks(table: history.ResetTable) -> list[Block]:
    """The weeks with a reset outside the schedule, after the weekly chart, how they are counted behind the heading."""
    blocks: list[Block] = [Heading(history.RESETS_HEADING, history.RESETS_NOTE)]
    if not table.rows:
        return blocks + [Note(history.RESETS_NONE)]
    aligns = (WORDS, WORDS) + (FIGURES,) * (len(table.columns) - 2)
    return blocks + [Table(tuple(zip(table.columns, aligns)), table.rows)]


def _product_blocks(table: history.ProductTable) -> list[Block]:
    """The weekly windows' use by product under the weekly chart; nothing where claude.ai reported none."""
    if not table.rows:
        return []
    heads = history.product_columns(table)
    aligns = (WORDS, WORDS) + (FIGURES,) * (len(heads) - 3) + (WORDS,)
    return [Table(tuple(zip(heads, aligns)), tuple(history.product_cells(table, row) for row in table.rows))]


def _cost_plot(columns: tuple[history.Column, ...], stacks: tuple[history.Stack, ...], ticks: int,
               figure=history.usd) -> ColumnPlot:
    """``figure`` writes a value, in a mark's words and on the value axis."""
    titles = [history.column_title(c) for c in columns]
    y_max = nice_ceiling(max(sum(s.values[i] for s in stacks) for i in range(len(columns))))
    return ColumnPlot(tuple(history.column_label(c) for c in columns),
                      tuple(ColumnStack(s.label, s.token, s.values,
                                        tuple(f"{titles[i]} · {s.label}: {figure(v)}" for i, v in enumerate(s.values)))
                            for s in stacks),
                      y_max, tuple((y_max * f, figure(y_max * f)) for f in
                                   ((0, 0.25, 0.5, 0.75, 1.0) if ticks == 5 else (0, 0.5, 1.0))))


def _switch(key: str, views: list[View], chosen: Mapping[str, str], by_week: bool = False) -> Switch:
    """``views`` in the order and words of ``history.SWITCH_VIEWS[key]``; the one shown is ``history.shown_view``'s."""
    shown = history.shown_view(key, chosen, by_week)
    return Switch(key, tuple(views), [view.choice for view in views].index(shown))


def _column_blocks(h: History, chosen: Mapping[str, str]) -> list[Block]:
    """The cost chart or the token chart on the same columns, a switch choosing; then each account's cost by model
    family, under whichever is shown; then the token tables, by week or by month."""
    unit = "week" if h.by_week else "day"
    costs, use = h.costs, h.tokens
    cost, tokens = history.SWITCH_VIEWS[history.COLUMNS_SWITCH]
    if costs.accounts:
        cost_view = View(cost, Heading(history.cost_heading(unit), history.BY_WEEK_NOTE if h.by_week else ""),
                         (Legend(tuple((s.label, s.token) for s in costs.accounts)),
                          Chart(_cost_plot(costs.columns, costs.accounts, 5), 12)))
    else:
        cost_view = View(cost, Heading(history.cost_heading(unit)), (Note(history.SPAN_NO_COST),))
    token_view = View(tokens, Heading(history.tokens_heading(unit), history.TOKENS_NOTE),
                      (Legend(tuple((s.label, s.token) for s in use.accounts)),
                       Chart(_cost_plot(use.columns, use.accounts, 5, history.count), 12)) if use.accounts
                      else (Note(history.SPAN_NO_TOKENS),))
    blocks: list[Block] = [_switch(history.COLUMNS_SWITCH, [cost_view, token_view], chosen)]
    for entry in costs.families:
        blocks += [Heading(history.family_heading(entry.entity.label)),
                   Legend(tuple((s.label, s.token) for s in entry.families)),
                   Chart(_cost_plot(costs.columns, entry.families, 3), 9)]
    week, month = history.SWITCH_VIEWS[history.TOKEN_TABLES_SWITCH]
    heading = Heading(history.TOKENS_BY)
    blocks.append(_switch(history.TOKEN_TABLES_SWITCH, [View(week, heading, _token_table(use.weeks, "Week")),
                                                        View(month, heading, _token_table(use.months, "Month"))],
                          chosen, h.by_week))
    return blocks


def _token_table(table: history.TokenTable, first: str) -> tuple[Block, ...]:
    """``first`` heads the period column; the last row, the span in all, is set in bold."""
    if not table.rows:
        return (Note(history.NO_TOKENS_NOTE),)
    columns = ((first, WORDS),) + tuple((label, FIGURES) for label in table.labels + history.TOKEN_COLUMNS)
    rows = tuple((row.period,) + history.token_cells(row) for row in table.rows)
    return (Table(columns, rows, (len(rows) - 1,)),)


def _cost_figure_blocks(c: history.CostFigures) -> list[Block]:
    cell = history.money_cell
    blocks: list[Block] = [Heading(history.PLAN_COST_HEADING, history.COST_NOTE)]
    if c.stacks:
        titles = list(c.months)
        y_max = nice_ceiling(max(sum(s.values[i] for s in c.stacks) for i in range(len(c.months))))
        plot = ColumnPlot(tuple(history.month_label(m) for m in c.months),
                          tuple(ColumnStack(s.label, s.token, s.values,
                                            tuple(f"{titles[i]} · {s.label}: {usd_text(v)}"
                                                  for i, v in enumerate(s.values)))
                                for s in c.stacks),
                          y_max, tuple((y_max * f, history.money_tick(y_max * f)) for f in (0, 0.25, 0.5, 0.75, 1.0)))
        blocks += [Legend(tuple((s.label, s.token) for s in c.stacks)), Chart(plot, 12)]
    columns = ((("Month", WORDS),) + tuple(col for label in c.labels for col in ((label, FIGURES),
                                                                                    (f"{label} per day", FIGURES)))
               + (("All accounts", FIGURES), ("Days with a plan", FIGURES), ("Per day", FIGURES)))
    rows = [(row.month,) + tuple(text for x in row.cells for text in (cell(x.cost), cell(x.per_day)))
            + (cell(row.total), str(row.days), cell(row.per_day)) for row in c.cost_months]
    rows.append(("In all",) + tuple(text for x in c.totals for text in (usd_text(x.cost), cell(x.per_day)))
                + (usd_text(c.all_cost), str(c.all_days), cell(c.all_per_day)))
    return blocks + [Table(columns, tuple(rows), (len(rows) - 1,))]


def _subscription_blocks(subs: history.Subscriptions | None) -> list[Block]:
    blocks: list[Block] = [Heading("Subscriptions")]
    if subs is None or not subs.configured:
        return blocks + [Note(history.NO_BILLS_NOTE)]
    summary = tuple((row.subscription.label, "".join(row.plan) + (" · renew soon" if row.subscription.renew_soon else ""),
                     f"{row.bills:,}", row.last_bill) for row in subs.summary)
    days = subs.reminder_days
    blocks += [Table((("Account", WORDS), ("Plan today", WORDS), ("Bills", FIGURES), ("Last bill", WORDS)), summary),
               Note(history.reminder_text(days))]
    if subs.unread:
        blocks.append(Note(history.UNREAD_NOTE))
    if subs.costs is not None:
        blocks += _cost_figure_blocks(subs.costs)
    if subs.periods:
        blocks += [Heading("Plan periods", history.PERIODS_NOTE),
                   Table((("Account", WORDS), ("Bill", WORDS), ("Plan", WORDS), ("How it began", WORDS),
                          ("In effect", WORDS), ("At list price", FIGURES), ("API-equivalent in effect", FIGURES)),
                         tuple((p.label, p.bill, p.plan, p.began, p.in_effect, p.list_price, p.api)
                               for p in subs.periods))]
    blocks.append(Heading(history.GAPS_HEADING))
    if subs.gaps:
        blocks.append(Table((("Account", WORDS), ("From", WORDS), ("Until", WORDS), ("Days", FIGURES),
                             ("Covered by another", WORDS)),
                            tuple((g.label, g.start.isoformat(), g.until.isoformat(), str(g.days), g.covered)
                                  for g in subs.gaps)))
    else:
        blocks.append(Note(history.GAPS_NONE[subs.unread]))
    if subs.coverage:
        blocks.append(Note(subs.coverage))
    return blocks


def _usage_blocks(tables: history.UsageTables) -> list[Block]:
    count, usd = history.count, history.usd
    return [
        Heading("Sessions"),
        Table((("Account", WORDS), ("Sessions", FIGURES), ("of them CLI", FIGURES), ("Prompts", FIGURES),
               ("Subagents", FIGURES), ("Subagent cost share", FIGURES)),
              tuple((r.label, f"{r.sessions:,}", f"{r.cli:,}", f"{r.prompts:,}", f"{r.agents:,}", f"{r.agent_share:.0f}%")
                    for r in tables.sessions)),
        Heading("Models"),
        Table((("Account", WORDS), ("Model", WORDS), ("Responses", FIGURES), ("Sessions", FIGURES), ("Input", FIGURES),
               ("Output", FIGURES), ("of it thinking", FIGURES), ("Cache read", FIGURES), ("Cache write", FIGURES),
               ("API-equivalent", FIGURES)),
              tuple((r.label, r.model, f"{r.responses:,}", f"{r.sessions:,}", count(r.input), count(r.output),
                     count(r.thinking), count(r.cache_read), count(r.cache_write),
                     usd(r.cost or 0.0) + ("" if r.cost is not None else " (unpriced)")) for r in tables.models)),
        Heading("Effort"),
        Table((("Account", WORDS), ("Effort", WORDS), ("Responses", FIGURES), ("Output", FIGURES),
               ("API-equivalent", FIGURES)),
              tuple((r.label, r.effort, f"{r.responses:,}", count(r.output), usd(r.cost or 0.0)) for r in tables.efforts)),
        Heading(history.CONTEXT_HEADING, history.CONTEXT_NOTE),
        Table(tuple((c, WORDS if j == 0 else FIGURES) for j, c in enumerate(history.CONTEXT_COLUMNS)),
              tuple(history.context_cells(r) for r in tables.context),
              (len(tables.context) - 1,) if tables.context else ()),
        Note(history.rewrite_text(tables.rewrites)),
    ]


def _capacity_blocks(c: history.Capacity, chosen: Mapping[str, str] | None = None) -> list[Block]:
    """What a full window held, by plan or by week, a switch choosing; in either view the caveat before the figures it
    qualifies, how it is counted behind the heading."""
    if not c.known:
        return [Heading(history.CAPACITY_HEADING), Note(history.CAPACITY_NO_BILLS)]
    five, weekly = history.CAPACITY_COLUMNS
    caveat = Note(history.CAPACITY_CAVEAT)
    plans = Table((("Plan", WORDS), (five, FIGURES), (weekly, FIGURES), (history.CAPACITY_WINDOWS, FIGURES),
                   ("Held by", WORDS)),
                  tuple((p.plan, p.five_hour, p.weekly, p.windows, p.held_by) for p in c.plans))
    weeks = (Table((("Week", WORDS), ("Plan", WORDS), (five, FIGURES), (weekly, FIGURES),
                    (history.CAPACITY_WINDOWS, FIGURES)),
                   tuple((f"week of {w.monday.isoformat()}", w.plan, w.five_hour, w.weekly, w.windows)
                         for w in c.weeks))
             if c.weeks else Note(history.SPAN_NO_CAPACITY_WEEKS))
    by_plan, by_week = history.SWITCH_VIEWS[history.CAPACITY_SWITCH]
    heading = Heading(history.CAPACITY_BY, history.CAPACITY_NOTE)
    return [_switch(history.CAPACITY_SWITCH, [View(by_plan, heading, (caveat, plans)),
                                              View(by_week, heading, (caveat, weeks))], chosen or {})]


def summary_block(s: history.Summary) -> Tiles:
    """The summary's tiles, each account's share with its bar."""
    tiles = history.summary_tiles(s)
    return Tiles(tuple((t.caption, t.figure) for t in tiles),
                 tuple((t.share, t.token) if t.share is not None else None for t in tiles))


def blocks(h: History, chosen: Mapping[str, str] | None = None) -> tuple[Block, ...]:
    """The history page's sections over the span, in its order, without the cards and the recommendation: the
    summary first, so it is what the window shows on opening and after each change of span. ``chosen`` names, by a
    switch's key, the view the user chose; a switch it does not name shows ``history.shown_view``'s."""
    chosen = chosen or {}
    found: list[Block] = [Heading(history.SUMMARY_HEADING), summary_block(h.summary)]
    found += (_weekly_blocks(h) + _column_blocks(h, chosen) + _subscription_blocks(h.subscriptions)
              + _capacity_blocks(h.capacity, chosen))
    found += [Heading(history.EXHAUSTED_HEADING, history.EXHAUSTED_NOTE),
              Table((("Week", WORDS), (history.EXHAUSTED_COLUMN, FIGURES)),
                    tuple((f"week of {w.monday.isoformat()}", history.exhausted_text(w)) for w in h.exhausted))]
    found += _usage_blocks(h.usage)
    found += [Heading("Coverage", history.COVERAGE_NOTE), Bullets(h.coverage)]
    return tuple(found)
