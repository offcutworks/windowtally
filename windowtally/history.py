"""The history's figures: what the history page and the window's History view show, as numbers and plain words,
computed read-only from the ledger and a billing report. Neither surface computes a figure of its own: the page
(``dashboard``) adds its markup and SVG, the window (``windowtally_gui``) its widgets and painting, so the two never
disagree.

Each section is a function of the ledger and a range. The page passes its own fixed ranges — six weeks of weekly use,
of what a full window holds and of exhausted time, thirty local days of the summary, of cost and of the usage tables,
so the summary's total is what the cost charts and the tables add up to. The window passes one span the user chooses
(``SPANS``, ``history``) for every section but the subscriptions, which cover every recorded bill whatever the span:
a month's total, a plan period and a gap are whole only over every bill. What the window shows over a span is also
exported as one HTML file (``dashboard.render_history``). A subscription's cost is its plans' cost at
the US list price, in US dollars (``billing``), beside the API-equivalent figures in the same currency; what a bill was
charged is not shown here, save beside a bill a refund credits, whose sum is listed in its own currency. Over six
months or all, the cost per day is summed into weeks from Monday (``by_week``), so a column stays wide enough to read
and to point at.

Where some bill may not have been read (``billing``, ``bills.Unread``), nothing here states an absence that may be its
doing: an account so concerned is said not to be wholly read and stands in no figure; the plans' cost across the
accounts is not given; and a gap's cover, the days without a plan, a plan held by no account and a table of gaps that
holds none are said of the accounts read alone (``UNREAD_NOTE``).

The summary heads both surfaces: the span's API-equivalent cost in all and per day elapsed, the part of it paid outside
the plans where there is any, the plans' cost at list price on the bills' UTC days that fall on the span's dates, the
use the plans covered as a multiple of that cost and, where the two read differently, the part of it within one window
a week as another — the multiples with resets and without (``plan_use``) — the span's tokens, each account's share of
the API-equivalent cost, the costliest model family and the hours with every account exhausted (``summary``,
``summary_tiles``). A plan period's use is split the same way (``_period_use``), and what a full window holds counts the
plans' dollars alone (``capacity``).

Under the weekly chart, where claude.ai reported any, stands the use by product of each account's weekly windows
(``product_table``): the last split of each window through the browser extension, with the weekly figure it came with,
each share shown as claude.ai gave it beside the points of the weekly limit it stands for, and part of no other figure;
with no report in the range, nothing is shown. The chart marks each reset outside an account's weekly schedule by its
kind — extra, a model's allowance, or not known (``plan_use``) — and a table after it counts them by account and week,
with the points they gave back and the use beyond one window they made room for (``reset_table``).

Tokens (``token_use``) are charted per account on the cost chart's columns, so tokens and dollars stand column for
column, and tabled by week from Monday and by calendar month with every kind and the same responses' API-equivalent
cost: the window passes its span for all three, the page its thirty days, its six weeks and the whole history, so the
page shows tokens over all time without a span to choose. Tokens are summed in the ledger by quarter hour before they
are put on local days, which keeps a range of years from being read response by response.

Every surface shows one of two views at a time where a section holds two of one kind — the cost chart or the token
chart, the token table by week or by month, what a full window held by plan or by week — a switch beside the
section's heading choosing; each surface computes both, so a choice shows at once (``SWITCH_VIEWS``, ``shown_view``).

The usage tables end with the context of the range's requests across every account (``usage_tables``, ``_context``):
the responses, sessions, tokens sent and API-equivalent cost by the size of the request's context, since a turn sends
the whole conversation again, so what a response costs grows with the session's length; and the responses that
wrote their context to the cache again after a pause longer than the lifetime of the cache they write, with what
writing the earlier request's context again cost beyond reading it (``pricing.cache_write_premium``). A response whose
session's previous response lies before the range is not judged a rewrite, since the range's ledger rows alone are
read.

What a full window holds (``plan_capacity``) gives, per plan over the range and per plan week by week from Monday, the
API-equivalent dollars one full 5-hour and one full weekly window held (``capacity``) and their quotient, how many full
5-hour windows a full weekly window held — which of the two limits binds — under the caveat that marks the
figure a lower bound wherever an account is also used otherwise; a week whose figure differs from the plan's last
stated one by more than the readings' rounding allows says whether it is higher or lower. Every plan WindowTally knows has
its row, a plan with no figure saying so.

Colour follows the entity, as a palette token (``palette``): accounts take the series slots 1-3 in the order they were
first seen, so an account keeps its colour when another is added, then ``muted``; model families take slots 4-8; use
with no known account is ``muted``. Words are plain text, no markup, and every day and month name is English
(``timeutil``).
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from fractions import Fraction
from typing import Iterable, Mapping

from . import palette
from .accounts import Account
from .billing import (BillingReport, CostTable, PeriodUse, Subscription, cents, day_start, describe_start,
                      profile_words, refund_words, usd_text)
from .bills import PLANS, Bill
from .capacity import KINDS, Held, differs, held, plan_spans, steps
from .ledger import Ledger
from .limits import FIVE_HOURS, WEEK, all_blocked_spans, coverage_start, renewal_near
from .plan_use import KINDS as RESET_KINDS, PlanUse, Use, plan_use
from .pricing import PLAN_PRICES, cache_write_premium, model_family
from .products import last_of_windows
from .timeutil import DAYS, MONTHS, local_datetime

FAMILIES = ("Fable", "Opus", "Sonnet", "Haiku", "Other")
LINE_BREAK = 12 * 3600.0  # a gap in observations longer than this is shown as a gap, not a held value
TABLE_ROWS = 12           # rows a table shows, its totals among them, before it scrolls: on the page and in the window
WHEEL_PAUSE = 1.5         # seconds without a turn of the wheel that end its gesture: on the page and in the window

# What a section's figures mean. A surface carries none of it at rest: the window shows each behind its section's
# heading as a hint, the page and the export as the heading's tooltip. The capacity caveat alone stands on the
# surface, every surface showing the measure being bound to say it is a lower bound.
EXTRA_RESET_WORDS = "extra reset"
IN_ITS_COLOUR = ", in its account's colour"   # the legend's marks are neutral; the chart's marks wear the colour
EXTRA_RESET_NOTE = EXTRA_RESET_WORDS + IN_ITS_COLOUR
MODEL_RESET_NOTE = "{model}'s allowance reset"
UNKNOWN_RESET_NOTE = "reset of a kind not known"
RESET_MARKS = {"extra": "disc", "model": "diamond", "unknown": "square"}   # a reset's mark on the weekly chart, by kind
RESETS_HEADING = "Resets outside the schedule"
RESETS_NOTE = ("A fall of an account's weekly window inside its week: a reset Anthropic hands out at random, free and "
               "not for sale, which the user takes when they choose — extra, the week given back; a model's allowance "
               "reset, Fable's, giving back about the model's part of the week; or of a kind not known, where the "
               "model was used and its allowance not read. The week's own reset comes at its fixed time and is no "
               "fall inside it. Points given back: the fall as read. Beyond one window: the use the plans covered "
               "after the week had used one full window, counted from the readings' rises, a fall's own use not "
               "counted until the reading after it — the room the resets made. Without resets ÷ plans sets the use "
               "within one window a week against the plans' cost, shown where the resets moved the multiple; outside "
               "the plans is use at extra usage, while a window stood exhausted or past a model's own allowance, which "
               "neither multiple counts.")
RESETS_NONE = "None."
PERIODS_NOTE = ("A period is in effect from its start until its end, a change of plan or its refund; the end shown is "
                "the day the next would start. At list price: the plan's US list price spread over the period's days and "
                "counted on its days in effect. API-equivalent: list price for the tokens of the account's responses "
                "while it was in effect — a yardstick, not a bill; — where the ledger has none. Its multiples of the "
                "list price count the use the plans covered, with resets and, where the two differ, without; the use "
                "at extra usage is said beside it and counted in neither.")
BY_WEEK_NOTE = "Each column is a week from Monday; the first and the last hold only the span's days."
# The window's words, which its export takes too (``dashboard.render_history``); the page keeps its own ranges' words.
SUMMARY_HEADING = "Summary"
WEEKLY_HEADING = "Weekly use"
EXHAUSTED_HEADING = "All accounts exhausted"
SPAN_NO_WEEKLY = "No weekly readings."
SPAN_NO_COST = "No priced responses."
SPAN_NO_CAPACITY_WEEKS = "No readings measure a window."
NO_BILLS_NOTE = "No bills recorded; Bills and sources records them."
UNREAD_NOTE = ("Some bills could not be read — see the source problems under Coverage. The accounts they may concern "
               "stand in none of the figures below, and what the figures leave out is said of the accounts read alone.")
EXHAUSTED_NOTE = ("Exhausted: the weekly or 5-hour window at 99% or more, from the reading that showed it until it "
                  "reset. An account counts as unavailable before it was first seen; use on other devices shows only in "
                  "a later reading.")
EXHAUSTED_COLUMN = "Hours"
PLAN_COST_HEADING = "Plans at list price, by month"
GAPS_HEADING = "Gaps between periods"
GAPS_NONE = {False: "None.", True: "None among the accounts read."}   # by whether some bill may not have been read
CAPACITY_HEADING = "Full window, by plan"        # where no plan is known, and so no switch stands beside it
CAPACITY_BY = "Full window, by"                  # the heading the switch's word completes: by plan, or by week
CAPACITY_COLUMNS = ("5-hour", "Weekly")          # what a full window of each held, in either view
CAPACITY_WINDOWS = "5-hour windows per week"
CAPACITY_CAVEAT = "A lower bound where an account is also used outside Claude Code on this computer."
CAPACITY_NOTE = ("What one full window held, in API-equivalent dollars — list price for the tokens, a yardstick, not a "
                 "bill. Counted as though all of an account's use were Claude Code here: the readings rise with every "
                 "use — the Chat tab, claude.ai, other devices — while the dollars count only the responses recorded "
                 "here, and of them only the plans' own: use at extra usage, while a window stood exhausted or past a "
                 "model's own allowance, raised no window and is left out. A step is two readings of one window at "
                 "most three hours apart, below 99%, under one recorded plan, with responses between them: its dollars "
                 "over the points it rose, times 100. The day a plan begins or changes is left out. A plan's accounts "
                 "count together; weeks run from Monday. —: a rise too small to state to a tenth. higher or lower: "
                 "differs from the plan's previous figure by more than rounding allows. 5-hour windows per week: the "
                 f"weekly figure over the 5-hour one; a week holds {WEEK / FIVE_HOURS:.1f} back to back, so below that "
                 "the weekly limit decides.")
CAPACITY_NO_BILLS = "No bills recorded, so no plan is known."
COVERAGE_NOTE = ("Chat-tab conversations leave no local token record; they show only in the percentages. "
                 "API-equivalent cost is list price for the tokens used — a yardstick, not a bill.")


def reminder_text(days: int | None, off: str = "off") -> str:
    """The renewal reminder's setting, under the subscriptions; ``off`` says it is off, in the surface's words."""
    return f"Renewal tag: {plural(days, 'day')} before a period ends." if days else f"Renewal tag: {off}."


# --- accounts and their colours -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Entity:
    """An account, or the use with no known account (``uuid`` None), with the palette token it wears."""
    uuid: str | None
    label: str
    token: str


UNATTRIBUTED = Entity(None, "no known account", "muted")


def account_slots(ledger: Ledger, accounts: dict[str, Account]) -> list[tuple[Account, str]]:
    """Accounts in the order they were first seen, each with the palette token it wears: the series slots in turn,
    then ``muted`` once they are used up. The window colours its accounts from this list too. Accounts first seen at
    one moment, or never, stand by the name their e-mail gives them, never by the user's name for them, so renaming an
    account never moves its colour."""
    first_seen: dict[str, float] = {}
    for table in ("responses", "observations"):  # each read from its account index, not by scanning both tables
        for account, first in ledger.db.execute(
                f"SELECT account_uuid, MIN(t) FROM {table} WHERE account_uuid IS NOT NULL GROUP BY account_uuid"):
            first_seen[account] = min(first, first_seen.get(account, first))
    ordered = sorted(accounts.values(), key=lambda a: (first_seen.get(a.uuid, float("inf")), a.default_label))
    return [(a, palette.ACCOUNT_SLOTS[i] if i < len(palette.ACCOUNT_SLOTS) else "muted") for i, a in enumerate(ordered)]


def entities(ledger: Ledger, accounts: dict[str, Account]) -> list[Entity]:
    """The accounts in the order they were first seen, each with its colour."""
    return [Entity(a.uuid, a.label, token) for a, token in account_slots(ledger, accounts)]


# --- words ------------------------------------------------------------------------------------------------------------

def _clock(moment: datetime) -> str:
    return f"{moment.hour:02d}:{moment.minute:02d}"


def weekday_clock(epoch: float) -> str:
    """``Wed 19:34``."""
    moment = local_datetime(epoch)
    return f"{DAYS[moment.weekday()]} {_clock(moment)}"


def moment_text(epoch: float) -> str:
    """``Wed Oct 21 19:34``."""
    moment = local_datetime(epoch)
    return f"{DAYS[moment.weekday()]} {MONTHS[moment.month - 1]} {moment.day:02d} {_clock(moment)}"


def stamp(epoch: float) -> str:
    """``Wed 2026-10-21 19:34``."""
    moment = local_datetime(epoch)
    return f"{DAYS[moment.weekday()]} {moment.year:04d}-{moment.month:02d}-{moment.day:02d} {_clock(moment)}"


def when(epoch: float | None, now: float) -> str:
    """A moment as the page writes it: with how long ago or until it within six days, else its date."""
    if epoch is None:
        return "—"
    moment = local_datetime(epoch)
    delta = epoch - now
    if abs(delta) < 60:
        return f"{weekday_clock(epoch)} (just now)"
    if abs(delta) < 86400 * 6:
        hours = abs(delta) / 3600
        span = f"{int(hours // 24)}d {int(hours % 24)}h" if hours >= 24 else f"{int(hours)}h {int(abs(delta) % 3600 // 60)}m"
        relative = f"in {span}" if delta > 0 else f"{span} ago"
        return f"{weekday_clock(epoch)} ({relative})"
    return f"{MONTHS[moment.month - 1]} {moment.day:02d} {_clock(moment)}"


def day_text(day: date) -> str:
    """``Sat 07 Nov 2026``."""
    return f"{DAYS[day.weekday()]} {day.day:02d} {MONTHS[day.month - 1]} {day.year:04d}"


def day_month(day: date) -> str:
    """``07 Nov``."""
    return f"{day.day:02d} {MONTHS[day.month - 1]}"


def month_day(day: date) -> str:
    """``Nov 07``."""
    return f"{MONTHS[day.month - 1]} {day.day:02d}"


def month_label(month: str) -> str:
    """A month written YYYY-MM, as ``Nov 26``."""
    year, number = month.split("-")
    return f"{MONTHS[int(number) - 1]} {year[-2:]}"


def plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def usd(value: float) -> str:
    return f"${value:,.2f}" if value < 1000 else f"${value:,.0f}"


def count(value: float) -> str:
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= limit:
            return f"{value / limit:.1f}{suffix}"
    return f"{value:.0f}"


def money_cell(value: Fraction | None) -> str:
    """A table's sum at list price, or — where there is none."""
    return "—" if value is None else usd_text(value)


def money_tick(value: float) -> str:
    return f"${value:,.0f}"


def plan_words(s: Subscription, near_only: bool = False) -> tuple[str, str]:
    """The plan in effect today and how far it is paid up: the plan, which a surface may set off, and the rest.
    ``near_only`` says the days left only while the renewal is near (``limits.renewal_near``), as an account's card
    does; the subscriptions' table always says them."""
    if s.state == "active":
        plan = PLANS[s.plan] if s.plan else "a recorded plan"
        said = s.days_left is not None and (not near_only or renewal_near(s.days_left))
        left = f" ({plural(s.days_left, 'day')} left)" if said else ""
        return plan, f" · paid until {day_text(s.paid_until)}{left}"
    if s.state == "ended":
        return "no plan today", f" · ended {day_text(s.paid_until)}"
    if s.state == "upcoming":
        return "not begun", f" · first period starts {day_text(s.paid_until)}"
    if s.state == "unread":
        return "bills not all read", " · see the source problems"
    return "no bills recorded", ""


def profile_text(s: Subscription, now: float) -> str:
    """The profile check in words, with when the profile was fetched where that bears on it."""
    text = profile_words(s.profile_check, s.profile_plan)
    if s.profile_fetched_at and s.profile_check in ("matches", "differs", "no-bill-today"):
        text += f" (fetched {when(s.profile_fetched_at, now)})"
    return text


def bill_line(bill: Bill, refund: Bill | None = None) -> str:
    """A bill by its date and what it was for, and its refund where one credits it; its amount is the bill's own
    record, shown only where bills are listed, as the sum a refund returned is."""
    what = PLANS[bill.plan] if bill.plan else {"topup": "top-up", "usage": "usage settled"}.get(bill.kind, bill.kind)
    return f"{bill.date.isoformat()} · {what}" + (f" · {refund_words(refund)}" if refund else "")


# --- days and weeks ---------------------------------------------------------------------------------------------------

def local_midnight(day: date) -> datetime:
    """Local midnight of ``day`` at that day's own UTC offset, so a week boundary stays at midnight across a DST change."""
    return datetime.combine(day, dtime()).astimezone()


def monday_of(epoch: float) -> date:
    day = local_datetime(epoch).date()
    return day - timedelta(days=day.weekday())


def mondays(start: float, end: float) -> list[datetime]:
    """Every local Monday midnight from ``start`` to ``end``."""
    day = local_datetime(start).date()
    monday = day + timedelta(days=(7 - day.weekday()) % 7)
    found = []
    while local_midnight(monday).timestamp() <= end:
        found.append(local_midnight(monday))
        monday += timedelta(days=7)
    return found


def time_ticks(start: float, end: float) -> tuple[tuple[float, str], ...]:
    """A time axis's ticks from ``start`` to ``end``: days within ten days, Mondays within ten weeks, else the first of
    each month."""
    days = (end - start) / 86400
    first, last = local_datetime(start).date(), local_datetime(end).date()
    ticks = []
    if days <= 10:
        day = first
        while day <= last:
            moment = local_midnight(day).timestamp()
            if start <= moment <= end:
                ticks.append((moment, f"{DAYS[day.weekday()]} {day.day}"))
            day += timedelta(days=1)
    elif days <= 70:
        ticks = [(m.timestamp(), month_day(m.date())) for m in mondays(start, end)]
    else:
        year, month = first.year, first.month
        while (year, month) <= (last.year, last.month):
            moment = local_midnight(first.replace(year=year, month=month, day=1)).timestamp()
            if start <= moment <= end:
                ticks.append((moment, month_label(f"{year:04d}-{month:02d}")))
            year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    return tuple(ticks)


def _day(epoch: float) -> str:
    """The local day of ``epoch``, as ``local_datetime`` gives it, in ISO form. Read from the naive local time, which
    has the same wall clock without the cost of attaching the offset: this runs once per priced response, and once per
    account and quarter hour of tokens (``_daily_tokens``)."""
    return datetime.fromtimestamp(epoch).date().isoformat()


# --- weekly usage -----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class UsageLine:
    entity: Entity
    points: tuple[tuple[float, float], ...]      # (epoch, percent), by time


@dataclass(frozen=True)
class Reset:
    """A reset outside an account's weekly schedule (``plan_use``), as the weekly chart marks it."""
    entity: Entity
    before: float                                # the last reading before it
    after: float                                 # the first reading after it
    value: float                                 # that reading's figure
    kind: str = "extra"                          # extra | model | unknown (``plan_use.Reset``)
    model: str | None = None                     # the model whose allowance it reset, for kind model
    given: float = 0.0                           # the points of the week it gave back, as read


@dataclass(frozen=True)
class WeeklyUsage:
    start: float
    end: float
    lines: tuple[UsageLine, ...]                 # accounts with readings in the range, in the accounts' order
    resets: tuple[Reset, ...]


def reset_note(kind: str, model: str | None = None) -> str:
    """What a reset of ``kind`` is, as a legend names its mark."""
    if kind == "model":
        return MODEL_RESET_NOTE.format(model=model or "a model")
    return UNKNOWN_RESET_NOTE if kind == "unknown" else EXTRA_RESET_WORDS


def reset_words(r: Reset) -> str:
    """What a reset's mark says: ``alpha: Fable's allowance reset between …, 50 points given back``."""
    return (f"{r.entity.label}: {reset_note(r.kind, r.model)} between {moment_text(r.before)} and "
            f"{moment_text(r.after)}, {plural(round(r.given), 'point')} given back")


def reset_legend(usage: WeeklyUsage) -> tuple[tuple[str, str], ...]:
    """Each kind of reset the chart marks, once, in ``plan_use.KINDS`` order and each model's by name: (its legend's
    words, its mark, ``RESET_MARKS``). The first says the chart's marks wear the account's colour."""
    found = []
    for kind in RESET_KINDS:
        for model in sorted({r.model or "" for r in usage.resets if r.kind == kind}):
            words = reset_note(kind, model or None) + ("" if found else IN_ITS_COLOUR)
            found.append((words, RESET_MARKS[kind]))
    return tuple(found)


def weekly_usage(ledger: Ledger, accounts: list[Entity], since: float, now: float,
                 uses: PlanUse | None = None) -> WeeklyUsage:
    """Each account's weekly readings from ``since`` — never from more than half a day before the ledger's first
    reading — to ``now``, with the resets outside the account's weekly schedule read after ``since``
    (``plan_use``), from ``uses`` where it covers ``since`` on."""
    covered = coverage_start(ledger)
    start = max(since, (covered or now) - 43200)
    uses = plan_use(ledger, start, now) if uses is None else uses
    lines, resets = [], []
    for entity in accounts:
        observations = ledger.observations(entity.uuid, "seven_day", since=start)
        if not observations:
            continue
        lines.append(UsageLine(entity, tuple((o.t, o.percent) for o in observations)))
        resets += [Reset(entity, r.before, r.after, r.low, r.kind, r.model, r.given)
                   for week in uses.weeks(entity.uuid) for r in week.resets if start <= r.after <= now]
    return WeeklyUsage(start, now, tuple(lines), tuple(resets))


# --- resets outside the schedule ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ResetTable:
    """Every account's weeks with a reset outside the schedule read in the range, oldest first per account."""
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def reset_table(accounts: list[Entity], uses: PlanUse, since: float, now: float) -> ResetTable:
    """A row per account and week with a reset outside the schedule read from ``since`` to ``now``: how many of each
    kind — a column per model whose allowance a reset gave back, and one for the kind not known only where one stands —
    the points they gave back, and the use the plans covered beyond one window in the week, the whole week's."""
    weeks = [(entity, week, [r for r in week.resets if since <= r.after <= now])
             for entity in accounts for week in uses.weeks(entity.uuid)]
    weeks = [(entity, week, shown) for entity, week, shown in weeks if shown]
    models = sorted({r.model for _e, _w, shown in weeks for r in shown if r.kind == "model" and r.model})
    unknown = any(r.kind == "unknown" for _e, _w, shown in weeks for r in shown)
    columns = (("Account", "Week from", "Extra") + tuple(f"{m}'s allowance" for m in models)
               + (("Kind not known",) if unknown else ()) + ("Points given back", "Beyond one window"))

    def counted(shown: list, kind: str, model: str | None = None) -> str:
        return str(sum(1 for r in shown if r.kind == kind and (model is None or r.model == model)))

    rows = [(entity.label, moment_text(week.start), counted(shown, "extra"))
            + tuple(counted(shown, "model", m) for m in models) + ((counted(shown, "unknown"),) if unknown else ())
            + (plural(round(sum(r.given for r in shown)), "point"), usd(week.beyond) if week.beyond else "—")
            for entity, week, shown in weeks]
    return ResetTable(columns, tuple(rows))


# --- weekly use by product --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ProductRow:
    entity: Entity
    window_start: float
    as_of: float                                 # when claude.ai computed the window's last report
    weekly: float | None                         # the weekly figure that report came with
    shares: dict[str, float]                     # product key → percent of the window's use up to the report


@dataclass(frozen=True)
class ProductTable:
    products: tuple[tuple[str, str], ...]        # (key, name): the latest report's, in its order, then older ones'
    rows: tuple[ProductRow, ...]                 # per account in the accounts' order, its windows oldest first


PRODUCTS_NOTE = ("By product: claude.ai's own split of each weekly window, the last its usage page reported in that "
                 "window, in whole percents beside the weekly figure it came with; beside each share, the points of the "
                 "weekly limit it stands for. A window whose page was not opened in Chrome has no row.")
PRODUCT_FIRST_COLUMNS = ("Account", "Window from", "Weekly")


def product_table(ledger: Ledger, accounts: list[Entity], since: float, now: float) -> ProductTable:
    """Each account's weekly windows with a report of their use by product computed from ``since`` to ``now``, by the
    last report of each (``products.last_of_windows``); empty where there is none, and the sections show nothing. The
    columns are the latest report's products under its names, in claude.ai's order, then any product only an older
    report named, in the order first met."""
    older: dict[str, str] = {}
    latest = None
    rows = []
    for entity in accounts:
        if entity.uuid is None:
            continue
        for report in last_of_windows(ledger, entity.uuid, since, now):
            if latest is None or report.as_of > latest.as_of:
                latest = report
            for share in report.shares:
                older.setdefault(share.key, share.name)
            rows.append(ProductRow(entity, report.window_start, report.as_of, report.weekly,
                                   {share.key: share.percent for share in report.shares}))
    names = {share.key: share.name for share in latest.shares} if latest else {}
    names.update((key, name) for key, name in older.items() if key not in names)
    return ProductTable(tuple(names.items()), tuple(rows))


def product_columns(table: ProductTable) -> tuple[str, ...]:
    return (*PRODUCT_FIRST_COLUMNS, *(name for _, name in table.products), "Reported")


def product_cells(table: ProductTable, row: ProductRow) -> tuple[str, ...]:
    """A row's cells: the account, when its window began, the weekly figure, each product's share with the points it
    stands for (— where the report named no such product) and when claude.ai computed the report."""
    return (row.entity.label, moment_text(row.window_start), "—" if row.weekly is None else f"{row.weekly:.0f}%",
            *(share_text(row.shares[key], row.weekly) if key in row.shares else "—" for key, _ in table.products),
            moment_text(row.as_of))


def share_text(share: float, weekly: float | None) -> str:
    """``15% · 8 pts``: a product's share and the points of the weekly limit it stands for, ``weekly`` × share, to the
    whole point — a share in whole percents is half a percent either way, so no finer — and ``<1 pt`` below half a
    point; the share alone where it is none or the weekly figure is not known."""
    if share <= 0 or weekly is None:
        return f"{share:.0f}%"
    points = round(share * weekly / 100)
    return f"{share:.0f}% · " + ("<1 pt" if points < 1 else "1 pt" if points == 1 else f"{points} pts")


# --- API-equivalent cost ----------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Column:
    first: date
    last: date                                   # inclusive: a day's column has last == first


def column_title(column: Column) -> str:
    """A cost column's dates: its day, or its first and last day where it sums a week."""
    if column.first == column.last:
        return column.first.isoformat()
    return f"{column.first.isoformat()} to {column.last.isoformat()}"


def column_label(column: Column) -> str:
    """A cost column's label under the chart: its first day, as MM-DD."""
    return column.first.isoformat()[5:]


def cost_heading(unit: str) -> str:
    """The cost chart's heading, ``unit`` day or week."""
    return f"API-equivalent cost per {unit}"


def family_heading(label: str) -> str:
    """The heading of an account's cost chart by model family, on the cost chart's columns."""
    return f"{label} cost by model family"


@dataclass(frozen=True)
class Stack:
    label: str
    token: str
    values: tuple[float, ...]                    # one per column


@dataclass(frozen=True)
class EntityCosts:
    entity: Entity
    families: tuple[Stack, ...]                  # the families with any priced use, in ``FAMILIES`` order


@dataclass(frozen=True)
class Costs:
    columns: tuple[Column, ...]
    accounts: tuple[Stack, ...]                  # per entity with any priced use, in the accounts' order
    families: tuple[EntityCosts, ...]


def _daily_cost_rows(ledger: Ledger, since: float) -> list[tuple[str | None, str, str, float]]:
    rows = defaultdict(float)
    families: dict[str | None, str] = {}  # a model's family, found once per model rather than once per response
    for account, t, model, cost in ledger.db.execute(
            "SELECT account_uuid, t, model, cost_usd FROM responses WHERE t>=? AND cost_usd IS NOT NULL", (since,)):
        family = families.get(model)
        if family is None:
            family = families[model] = model_family(model)
        rows[(account, _day(t), family)] += cost
    return [(account, day, family, cost) for (account, day, family), cost in rows.items()]


def _dates(first: date, last: date) -> list[date]:
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def daily_costs(ledger: Ledger, accounts: list[Entity], first: date, last: date) -> Costs:
    """The API-equivalent cost of each local day from ``first`` to ``last``, by account and by model family. Use no
    account of ``accounts`` owns is summed under ``UNATTRIBUTED``, last."""
    days = [day.isoformat() for day in _dates(first, last)]
    since = local_midnight(first).timestamp()
    rows = _daily_cost_rows(ledger, since)
    index = {day: i for i, day in enumerate(days)}
    by_account: dict[str | None, list[float]] = defaultdict(lambda: [0.0] * len(days))
    by_family: dict[tuple[str | None, str], list[float]] = defaultdict(lambda: [0.0] * len(days))
    for account, day, family, cost in rows:
        if day in index:
            by_account[account][index[day]] += cost
            by_family[(account, family)][index[day]] += cost
    known = {e.uuid for e in accounts}
    order = list(accounts) + ([UNATTRIBUTED] if any(a not in known for a in by_account) else [])

    def belongs(account: str | None, entity: Entity) -> bool:
        return account == entity.uuid or (entity.uuid is None and account not in known)

    def summed(series_list: list[list[float]]) -> list[float]:
        return [sum(column) for column in zip(*series_list)] if series_list else [0.0] * len(days)

    stacks = []
    for entity in order:
        values = summed([series for account, series in by_account.items() if belongs(account, entity)])
        if any(values):
            stacks.append(Stack(entity.label, entity.token, tuple(values)))
    families = []
    for entity in order:
        family_stacks = []
        for slot, family in zip(palette.FAMILY_SLOTS, FAMILIES):
            values = summed([series for (account, of_family), series in by_family.items()
                             if of_family == family and belongs(account, entity)])
            if any(values):
                family_stacks.append(Stack(family, slot, tuple(values)))
        if family_stacks:
            families.append(EntityCosts(entity, tuple(family_stacks)))
    columns = tuple(Column(date.fromisoformat(d), date.fromisoformat(d)) for d in days)
    return Costs(columns, tuple(stacks), tuple(families))


def _into_weeks(columns: tuple[Column, ...], *groups: tuple[Stack, ...]
               ) -> tuple[tuple[Column, ...], tuple[tuple[Stack, ...], ...]]:
    """Day columns, and each group of stacks over them, summed into weeks from Monday; the first and last week hold
    only the days the range has. Whatever the stacks count — dollars or tokens — is summed."""
    weeks: list[list[int]] = []
    for index, column in enumerate(columns):
        if not weeks or column.first.weekday() == 0:
            weeks.append([])
        weeks[-1].append(index)

    def summed(stack: Stack) -> Stack:
        return Stack(stack.label, stack.token, tuple(sum(stack.values[i] for i in w) for w in weeks))

    return (tuple(Column(columns[w[0]].first, columns[w[-1]].last) for w in weeks),
            tuple(tuple(summed(s) for s in group) for group in groups))


def by_week(costs: Costs) -> Costs:
    """The same costs summed into weeks from Monday (``_into_weeks``)."""
    columns, (accounts, *families) = _into_weeks(costs.columns, costs.accounts, *(e.families for e in costs.families))
    return Costs(columns, accounts, tuple(EntityCosts(e.entity, f) for e, f in zip(costs.families, families)))


# --- tokens -----------------------------------------------------------------------------------------------------------

QUARTER_HOUR = 900   # every UTC offset in use is a whole number of quarter hours, so each lies inside one local day


@dataclass(frozen=True)
class Tokens:
    """Token counts by kind, as Claude Code reports them for a response. ``thinking`` is part of ``output``."""
    input: int = 0                               # sent uncached
    output: int = 0
    thinking: int = 0
    cache_write: int = 0                         # written to the prompt cache, at either lifetime
    cache_read: int = 0

    @property
    def total(self) -> int:
        """Every token once: thinking is counted inside output."""
        return self.input + self.output + self.cache_write + self.cache_read

    def __add__(self, other: Tokens) -> Tokens:
        return Tokens(self.input + other.input, self.output + other.output, self.thinking + other.thinking,
                      self.cache_write + other.cache_write, self.cache_read + other.cache_read)


NO_TOKENS = (Tokens(), 0.0)


@dataclass(frozen=True)
class TokenRow:
    period: str                                  # "week of 2026-10-19", "2026-10", or "In all"
    accounts: tuple[int, ...]                    # each account's tokens, in the table's order
    tokens: Tokens                               # every account's, by kind
    cost: float                                  # the same responses' API-equivalent cost


@dataclass(frozen=True)
class TokenTable:
    labels: tuple[str, ...]                      # the accounts with tokens in the table's range, in the accounts' order
    rows: tuple[TokenRow, ...]                   # each period oldest first, then the range in all; none without tokens


@dataclass(frozen=True)
class TokenUse:
    columns: tuple[Column, ...]                  # the cost chart's: per day, or per week from Monday
    accounts: tuple[Stack, ...]                  # each entity's tokens per column, as the cost chart's accounts
    total: int                                   # every token on the chart's days
    weeks: TokenTable
    months: TokenTable


def tokens_heading(unit: str) -> str:
    """The token chart's heading, ``unit`` day or week."""
    return f"Tokens per {unit}"


TOKENS_BY = "Tokens by"                          # the token tables' heading, the switch's word completing it
TOKEN_COLUMNS = ("Input", "Output", "of it thinking", "Cache write", "Cache read", "All tokens", "API-equivalent")
SPAN_NO_TOKENS = "No responses."
NO_TOKENS_NOTE = "No responses."
# What each kind of token counts: the note the maintainer decided the tokens carry, behind the tokens' heading.
TOKENS_NOTE = ("As Claude Code reports each response: input is what was sent uncached, cache write what was written to "
               "the prompt cache at either lifetime, cache read what was read from it, output what was generated, "
               "thinking included. All tokens adds them. Weeks run from Monday and months by the calendar, in local "
               "time; the first and the last hold only the range's days. API-equivalent is the same responses' list "
               "price, so a change in the work done can be told from a change in what it cost.")


def _daily_tokens(ledger: Ledger, since: float) -> dict[tuple[str | None, str], tuple[Tokens, float]]:
    """Tokens and API-equivalent cost per account and local day, unpriced responses' tokens included. Summed by quarter
    hour in the ledger, so a long range is not read response by response, then each quarter hour put on its local
    day."""
    rows: dict[tuple[str | None, str], tuple[Tokens, float]] = {}
    for account, quarter, *counts, cost in ledger.db.execute(
            f"SELECT account_uuid, CAST(t / {QUARTER_HOUR} AS INTEGER) AS quarter, SUM(input_tokens), "
            "SUM(output_tokens), SUM(thinking_tokens), SUM(cache_write_5m_tokens + cache_write_1h_tokens), "
            "SUM(cache_read_tokens), TOTAL(cost_usd) FROM responses WHERE t>=? GROUP BY account_uuid, quarter",
            (since,)):
        key = (account, _day(quarter * QUARTER_HOUR))
        tokens, spent = rows.get(key, NO_TOKENS)
        rows[key] = (tokens + Tokens(*counts), spent + cost)
    return rows


def _token_table(by_day: dict[tuple[Entity, date], tuple[Tokens, float]], order: list[Entity], first: date,
                 last: date, period) -> TokenTable:
    """``by_day`` from ``first`` to ``last``, summed into the periods ``period`` names each day by."""
    days = _dates(first, last)
    shown = [e for e in order if any(by_day.get((e, day), NO_TOKENS)[0].total for day in days)]
    if not shown:
        return TokenTable((), ())
    periods: dict[str, list[date]] = {}
    for day in days:
        periods.setdefault(period(day), []).append(day)

    def row(name: str, of_days: list[date]) -> TokenRow:
        sums = {e: [by_day.get((e, day), NO_TOKENS) for day in of_days] for e in order}
        return TokenRow(name, tuple(sum((t for t, _c in sums[e]), Tokens()).total for e in shown),
                        sum((t for entries in sums.values() for t, _c in entries), Tokens()),
                        sum(c for entries in sums.values() for _t, c in entries))

    return TokenTable(tuple(e.label for e in shown),
                      tuple(row(name, of_days) for name, of_days in periods.items()) + (row("In all", days),))


def token_cells(row: TokenRow) -> tuple[str, ...]:
    """A table row's figures after its period: each account's tokens, then ``TOKEN_COLUMNS``."""
    t = row.tokens
    return (tuple(count(v) for v in row.accounts)
            + tuple(count(v) for v in (t.input, t.output, t.thinking, t.cache_write, t.cache_read, t.total))
            + (usd(row.cost),))


def token_use(ledger: Ledger, accounts: list[Entity], days: tuple[date, date], weeks: tuple[date, date],
              months: tuple[date, date], weekly: bool) -> TokenUse:
    """Tokens per account over the local days ``days`` — per day, or per week from Monday where ``weekly``, the cost
    chart's columns — and in tables by week over ``weeks`` and by calendar month over ``months``. Use no account of
    ``accounts`` owns is counted under ``UNATTRIBUTED``, last."""
    first = min(days[0], weeks[0], months[0])
    entity_of = {e.uuid: e for e in accounts}
    by_day: dict[tuple[Entity, date], tuple[Tokens, float]] = {}
    for (account, day), (tokens, cost) in _daily_tokens(ledger, local_midnight(first).timestamp()).items():
        key = (entity_of.get(account, UNATTRIBUTED), date.fromisoformat(day))
        before, spent = by_day.get(key, NO_TOKENS)
        by_day[key] = (before + tokens, spent + cost)
    order = list(accounts) + [UNATTRIBUTED]
    chart_days = _dates(*days)
    stacks = []
    for entity in order:
        values = tuple(float(by_day.get((entity, day), NO_TOKENS)[0].total) for day in chart_days)
        if any(values):
            stacks.append(Stack(entity.label, entity.token, values))
    columns, accounts_stacks = tuple(Column(day, day) for day in chart_days), tuple(stacks)
    if weekly:
        columns, (accounts_stacks,) = _into_weeks(columns, accounts_stacks)
    total = sum(tokens.total for (_entity, day), (tokens, _cost) in by_day.items() if days[0] <= day <= days[1])
    return TokenUse(columns, accounts_stacks, total,
                    _token_table(by_day, order, *weeks,
                                 lambda day: f"week of {(day - timedelta(days=day.weekday())).isoformat()}"),
                    _token_table(by_day, order, *months, lambda day: f"{day.year:04d}-{day.month:02d}"))


# --- time with every account exhausted --------------------------------------------------------------------------------

@dataclass(frozen=True)
class ExhaustedWeek:
    monday: date
    hours: float
    known: bool                                  # False: the ledger knows nothing of the week
    covered_from: float | None                   # set when the range or the ledger's record begins inside the week


def exhausted_text(week: ExhaustedWeek) -> str:
    if not week.known:
        return "no data"
    if week.covered_from is not None:
        return f"{week.hours:.1f} h (from {weekday_clock(week.covered_from)})"
    return f"{week.hours:.1f} h"


def exhausted_weeks(ledger: Ledger, accounts: Iterable[Account], since: float, now: float) -> tuple[ExhaustedWeek, ...]:
    """Hours in each local week from the week holding ``since`` to the week holding ``now`` when no account could be
    used (``limits.all_blocked_spans``). A week the counting begins inside — the range's first, or the one the
    ledger's record begins in — says from when it counts."""
    covered = coverage_start(ledger)
    spans = all_blocked_spans(ledger, accounts, since, now)
    hours: dict[str, float] = defaultdict(float)
    for a, b in spans:
        cursor = a
        while cursor < b:
            monday = monday_of(cursor)
            boundary = min(b, local_midnight(monday + timedelta(days=7)).timestamp())
            hours[monday.isoformat()] += (boundary - cursor) / 3600
            cursor = boundary
    monday = monday_of(since)
    weeks = []
    while local_midnight(monday).timestamp() <= now:
        week_end = local_midnight(monday + timedelta(days=7)).timestamp()
        if covered is None or covered >= week_end:
            weeks.append(ExhaustedWeek(monday, 0.0, False, None))
        else:
            begins = max(since, covered)
            within = begins if begins > local_midnight(monday).timestamp() else None
            weeks.append(ExhaustedWeek(monday, hours.get(monday.isoformat(), 0.0), True, within))
        monday += timedelta(days=7)
    return tuple(weeks)


# --- sessions, models, effort and context -----------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionRow:
    label: str
    sessions: int
    cli: int                                     # of them CLI sessions
    prompts: int
    agents: int
    agent_share: float                           # percent of the cost spent by subagents


@dataclass(frozen=True)
class ModelRow:
    label: str
    model: str
    responses: int
    sessions: int
    input: float
    output: float
    thinking: float
    cache_read: float
    cache_write: float
    cost: float | None                           # None: no response of the row is priced


@dataclass(frozen=True)
class EffortRow:
    label: str
    effort: str
    responses: int
    output: float
    cost: float | None


@dataclass(frozen=True)
class ContextRow:
    label: str                                   # the range of a request's context, or "In all"
    responses: int
    sessions: int                                # those with a response in the range
    context: float                               # every token the range's requests sent
    cost: float | None                           # None: no response of the row is priced
    share: float                                 # percent of the span's priced cost
    per_response: float | None                   # the row's cost over its priced responses


@dataclass(frozen=True)
class Rewrites:
    """The responses that wrote their context to the cache again after a pause (``CONTEXT_NOTE``)."""
    responses: int
    premium: float                               # what writing the earlier context again cost beyond reading it
    share: float                                 # percent of the span's priced cost


@dataclass(frozen=True)
class UsageTables:
    sessions: tuple[SessionRow, ...]
    models: tuple[ModelRow, ...]
    efforts: tuple[EffortRow, ...]
    context: tuple[ContextRow, ...]              # by range of context, then "In all"; empty without a response
    rewrites: Rewrites


CONTEXT_EDGES = (100_000, 200_000, 500_000)      # a request's context, in tokens, where one range ends, the next begins
PAUSE_5M, PAUSE_1H = 300.0, 3600.0              # seconds: the cache's two lifetimes; a shorter pause expires nothing
CONTEXT_HEADING = "Context"
CONTEXT_NOTE = ("A request's context is every token it sent — input uncached, cache reads and cache writes. Each turn "
                "sends the whole conversation again, so a long session pays for its length on every response. Rows by "
                "the request's context; sessions: those with a response in the row; per response: the row's "
                "API-equivalent cost over its priced responses. Rewritten after a pause: priced responses that came "
                "longer after the previous response of their session or subagent within the span than the cache they "
                "write lives — an hour, or five minutes — and wrote more to the cache than they read from it, most "
                "often a cache that had expired; with what writing the earlier request's context again cost beyond "
                "reading it.")
CONTEXT_COLUMNS = ("Context", "Responses", "Sessions", "Tokens sent", "API-equivalent", "Share", "Per response")


def context_label(index: int) -> str:
    """The words of the ``index``-th range of ``CONTEXT_EDGES``: "under 100K", "100K–200K", …, "500K and over"."""
    def k(edge: int) -> str:
        return f"{edge // 1000}K"
    if index == 0:
        return f"under {k(CONTEXT_EDGES[0])}"
    if index == len(CONTEXT_EDGES):
        return f"{k(CONTEXT_EDGES[-1])} and over"
    return f"{k(CONTEXT_EDGES[index - 1])}–{k(CONTEXT_EDGES[index])}"


def context_cells(row: ContextRow) -> tuple[str, ...]:
    """A context row's cells under ``CONTEXT_COLUMNS``, as the page and the window show them; — where none is priced."""
    return (row.label, f"{row.responses:,}", f"{row.sessions:,}", count(row.context),
            "—" if row.cost is None else usd(row.cost), f"{row.share:.0f}%",
            "—" if row.per_response is None else usd(row.per_response))


def rewrite_text(r: Rewrites) -> str:
    if not r.responses:
        return "Rewritten after a pause: none."
    return (f"Rewritten after a pause: {plural(r.responses, 'response')}, {usd(r.premium)} beyond reading the "
            f"context again ({r.share:.1f}% of the cost).")


_CONTEXT_SQL = "input_tokens + cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens"


def _context(ledger: Ledger, since: float) -> tuple[tuple[ContextRow, ...], Rewrites]:
    """The responses since ``since`` by the range of their request's context, and those rewritten after a pause."""
    ranges = " ".join(f"WHEN {_CONTEXT_SQL} < {edge} THEN {i}" for i, edge in enumerate(CONTEXT_EDGES))
    grouped = ledger.db.execute(
        f"SELECT CASE {ranges} ELSE {len(CONTEXT_EDGES)} END AS bucket, COUNT(*), COUNT(DISTINCT session_id), "
        f"SUM({_CONTEXT_SQL}), SUM(cost_usd), COUNT(cost_usd) FROM responses WHERE t>=? "
        "GROUP BY bucket ORDER BY bucket", (since,)).fetchall()
    total = sum(c or 0.0 for _r, _n, _s, _x, c, _k in grouped)

    def row(label: str, n: int, sessions: int, context: float, cost: float | None, priced: int) -> ContextRow:
        return ContextRow(label, n, sessions, context or 0, cost if priced else None,
                          (cost or 0.0) / total * 100 if total else 0.0, cost / priced if priced else None)

    rows = [row(context_label(r), n, s, x, c, k) for r, n, s, x, c, k in grouped]
    if rows:
        sessions = ledger.db.execute("SELECT COUNT(DISTINCT session_id) FROM responses WHERE t>=?",
                                     (since,)).fetchone()[0]
        priced = sum(k for *_rest, k in grouped)
        rows.append(row("In all", sum(r.responses for r in rows), sessions, sum(r.context for r in rows),
                        total, priced))
    # A rewrite writes again what a live cache would have served: the earlier request's context less what was read,
    # at most what was written; the turn's own new tokens would have been written either way.
    after_pause = ledger.db.execute(
        "SELECT model, speed, context, write_5m, write_1h, MIN(write_5m + write_1h, before_context - read) FROM ("
        f"SELECT t, model, speed, {_CONTEXT_SQL} AS context, cache_read_tokens AS read, "
        "cache_write_5m_tokens AS write_5m, cache_write_1h_tokens AS write_1h, LAG(t) OVER stream AS before, "
        f"LAG({_CONTEXT_SQL}) OVER stream AS before_context FROM responses WHERE t>=? "
        "WINDOW stream AS (PARTITION BY session_id, agent_id ORDER BY t)) "
        "WHERE before IS NOT NULL AND t - before > CASE WHEN write_1h > 0 THEN ? ELSE ? END "
        "AND write_5m + write_1h > read AND before_context > read", (since, PAUSE_1H, PAUSE_5M)).fetchall()
    premiums = [cache_write_premium(m, prompt_tokens=x, cache_write_5m_tokens=round(w5 * again / (w5 + w1)),
                                    cache_write_1h_tokens=round(w1 * again / (w5 + w1)), speed=sp)
                for m, sp, x, w5, w1, again in after_pause]
    priced = [p for p in premiums if p is not None]
    premium = sum(priced)
    return tuple(rows), Rewrites(len(priced), premium, premium / total * 100 if total else 0.0)


def usage_tables(ledger: Ledger, accounts: list[Entity], since: float) -> UsageTables:
    """Sessions, models and effort of the responses since ``since``, per account, and their context across every
    account."""
    label_of = {e.uuid: e.label for e in accounts}
    models = ledger.db.execute(
        "SELECT account_uuid, model, COUNT(*), COUNT(DISTINCT session_id), SUM(input_tokens), SUM(output_tokens), "
        "SUM(thinking_tokens), SUM(cache_read_tokens), SUM(cache_write_5m_tokens + cache_write_1h_tokens), "
        "SUM(cost_usd) FROM responses WHERE t>=? GROUP BY account_uuid, model ORDER BY account_uuid, SUM(cost_usd) DESC",
        (since,)).fetchall()
    model_rows = tuple(ModelRow(label_of.get(a, UNATTRIBUTED.label), m or "?", n, s, i, o, th, cr, cw, c)
                       for a, m, n, s, i, o, th, cr, cw, c in models)
    efforts = ledger.db.execute(
        "SELECT account_uuid, COALESCE(effort, '—'), COUNT(*), SUM(output_tokens), SUM(cost_usd) FROM responses "
        "WHERE t>=? GROUP BY account_uuid, effort ORDER BY account_uuid, COUNT(*) DESC", (since,)).fetchall()
    effort_rows = tuple(EffortRow(label_of.get(a, UNATTRIBUTED.label), e, n, o, c) for a, e, n, o, c in efforts)
    sessions = ledger.db.execute(
        "SELECT r.account_uuid, COUNT(DISTINCT r.session_id), "
        "COUNT(DISTINCT CASE WHEN r.agent_id IS NOT NULL THEN r.agent_id END), "
        "SUM(CASE WHEN r.agent_id IS NOT NULL THEN r.cost_usd ELSE 0 END), SUM(r.cost_usd), "
        "COUNT(DISTINCT CASE WHEN r.entrypoint IN ('cli','sdk-cli','sdk-ts','sdk-py') THEN r.session_id END) "
        "FROM responses r WHERE r.t>=? GROUP BY r.account_uuid", (since,)).fetchall()
    prompts = dict(ledger.db.execute(
        "SELECT owner.account_uuid, COUNT(*) FROM prompts p JOIN (SELECT session_id, MIN(account_uuid) AS account_uuid "
        "FROM responses WHERE agent_id IS NULL GROUP BY session_id) owner ON owner.session_id = p.session_id "
        "WHERE p.t>=? GROUP BY owner.account_uuid", (since,)).fetchall())
    session_rows = tuple(
        SessionRow(label_of.get(a, UNATTRIBUTED.label), s, cli, prompts.get(a, 0), agents,
                   (agent_cost or 0) / total * 100 if total else 0)
        for a, s, agents, agent_cost, total, cli in sessions)
    return UsageTables(session_rows, model_rows, effort_rows, *_context(ledger, since))


# --- subscriptions ----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SummaryRow:
    subscription: Subscription
    token: str
    plan: tuple[str, str]                        # ``plan_words``
    profile: str
    bills: int
    last_bill: str


@dataclass(frozen=True)
class CostCell:
    cost: Fraction | None                        # None: no plan of the account was in effect in the month
    per_day: Fraction | None                     # per day with a plan; None without one


@dataclass(frozen=True)
class CostMonth:
    month: str
    cells: tuple[CostCell, ...]                  # in the table's account order
    total: Fraction | None                       # None when no account had a plan in effect in the month
    days: int                                    # days on which some account of the table had a plan
    per_day: Fraction | None


@dataclass(frozen=True)
class CostFigures:
    """The plans' cost at list price, month by month, in US dollars."""
    labels: tuple[str, ...]                      # the table's accounts
    stacks: tuple[Stack, ...]                    # each account's cost per month
    months: tuple[str, ...]
    cost_months: tuple[CostMonth, ...]
    totals: tuple[CostCell, ...]                 # each account's over every month
    all_cost: Fraction
    all_days: int
    all_per_day: Fraction | None


@dataclass(frozen=True)
class PeriodRow:
    label: str
    bill: str
    plan: str
    began: str
    in_effect: str
    list_price: str                              # its cost at list price, counted on its days in effect
    api: str                                     # empty: the period never ran; — : the ledger has no use from then


@dataclass(frozen=True)
class GapRow:
    label: str
    start: date
    until: date
    days: int
    covered: str


@dataclass(frozen=True)
class Subscriptions:
    """What the bills say. ``configured`` false: no bill source exists, and nothing else is set."""
    configured: bool
    reminder_days: int | None
    summary: tuple[SummaryRow, ...] = ()
    costs: CostFigures | None = None             # None while no plan was in effect on any day
    periods: tuple[PeriodRow, ...] = ()
    gaps: tuple[GapRow, ...] = ()
    coverage: str | None = None                  # the days some account had a recorded plan
    unread: bool = False                         # some bill may not have been read: ``UNREAD_NOTE`` heads the figures


def _summary(billing: BillingReport, token_of: dict[str | None, str], now: float) -> tuple[SummaryRow, ...]:
    rows = []
    for s in billing.subscriptions:
        bills = [b for b in s.bills if b.kind != "refund"]   # a refund is listed beside the bill it credits
        last = max(bills, key=lambda b: (b.date, b.order), default=None)
        rows.append(SummaryRow(s, token_of.get(s.uuid, UNATTRIBUTED.token), plan_words(s), profile_text(s, now),
                               len(bills),
                               "—" if last is None else bill_line(last, billing.bill_set.refund_of(last))))
    return tuple(rows)


def cost_figures(table: CostTable, billing: BillingReport, token_of: dict[str | None, str]) -> CostFigures:
    """The plans' cost at list price per month, with every total taken from the exact values."""
    by_email = {s.email: s for s in billing.subscriptions}
    labels = tuple(by_email[e].label for e in table.emails)
    stacks = tuple(s for s in (Stack(by_email[e].label, token_of.get(by_email[e].uuid, UNATTRIBUTED.token),
                                     tuple(float(cents(row.cost.get(e, Fraction(0)))) for row in table.months))
                               for e in table.emails) if any(s.values))
    cost_months = []
    for row in table.months:
        cells = []
        for e in table.emails:
            cost, days = row.cost.get(e), row.service_days.get(e, 0)
            cells.append(CostCell(cost, cost / days if cost is not None and days else None))
        total = sum(row.cost.values(), Fraction(0))
        cost_months.append(CostMonth(row.month, tuple(cells), total if row.cost else None, row.any_service_days,
                                     total / row.any_service_days if row.cost and row.any_service_days else None))
    totals = {e: sum((row.cost.get(e, Fraction(0)) for row in table.months), Fraction(0)) for e in table.emails}
    days = {e: sum(row.service_days.get(e, 0) for row in table.months) for e in table.emails}
    all_cost, all_days = sum(totals.values(), Fraction(0)), sum(row.any_service_days for row in table.months)
    return CostFigures(
        labels=labels, stacks=stacks, months=tuple(row.month for row in table.months), cost_months=tuple(cost_months),
        totals=tuple(CostCell(totals[e], totals[e] / days[e] if days[e] else None) for e in table.emails),
        all_cost=all_cost, all_days=all_days, all_per_day=all_cost / all_days if all_days else None)


def _price_words() -> str:
    """The plans' list prices in words: ``Pro $20 a month or $200 a year, Max 5x $100 a month, …``."""
    words = []
    for key, name in PLANS.items():
        price = PLAN_PRICES[key]
        yearly = f" or ${price.yearly:,.0f} a year" if price.yearly is not None else ""
        words.append(f"{name} ${price.monthly:,.0f} a month{yearly}")
    return ", ".join(words)


COST_NOTE = (f"Each plan's US list price — {_price_words()} — spread evenly over its period's days, in UTC, and "
             "counted on the days the plan was in effect; a change of plan starts the new plan's own period. What the "
             "plan time is worth at list price, not what was paid; top-ups and extra usage count in no figure. Totals "
             "come from exact values; days with a plan count each day once.")


def _period_use(use: PeriodUse, uuids: tuple[str, ...], uses: PlanUse | None, now: float) -> str:
    """A period's API-equivalent use, as the period table writes it: the sum, from when the ledger's record begins
    where that is inside the period, what of it was paid outside the plans, and the use the plans covered as a
    multiple of the period's list price, with resets, and without them where the two read differently (``plan_use``)."""
    period = use.period
    if use.api_usd is None:
        return "—"
    text = f"${use.api_usd:,.0f}"
    if use.known_from is not None:
        text += f" (from {day_month(local_datetime(use.known_from).date())})"
    split = None
    if uses is not None:
        split = uses.between(day_start(period.bill.start), min(day_start(period.until), now), uuids)
        if split.outside >= 0.5:
            text += f", ${split.outside:,.0f} of it outside the plans"
    if period.cost > 0:
        in_plans = use.api_usd - (split.outside if split else 0.0)
        multiple = f"{in_plans / float(period.cost):,.0f}"
        text += f" · {multiple}× its list price"
        without = f"{(in_plans - split.beyond) / float(period.cost):,.0f}" if split is not None else multiple
        if without != multiple:
            text += f", {without}× without resets"
    return text


def _periods(billing: BillingReport, uses: PlanUse | None = None, now: float = 0.0) -> tuple[PeriodRow, ...]:
    entries = []
    for s in billing.subscriptions:
        of_period = {id(u.period): u for u in s.uses}
        for period in s.periods:
            entries.append((s, period, of_period.get(id(period))))
    entries.sort(key=lambda e: (e[1].bill.start, e[1].bill.order), reverse=True)
    rows = []
    for s, period, use in entries:
        bill = period.bill
        if period.until <= bill.start:
            effect = "refunded before it began" if period.held <= bill.start else "replaced the same day"
        else:
            effect = f"{bill.start.isoformat()} → {period.until.isoformat()}"
            if bill.start <= billing.today < period.until:
                effect += " (running)"
        api = "" if use is None else _period_use(use, s.uuids, uses, now)
        rows.append(PeriodRow(s.label, bill.date.isoformat() + (f" · {bill.reference}" if bill.reference else "")
                              + (f" · {refund_words(period.refund)}" if period.refund else ""),
                              PLANS[bill.plan], describe_start(period), effect, usd_text(period.cost), api))
    return tuple(rows)


def _gaps(billing: BillingReport) -> tuple[GapRow, ...]:
    """Each gap and how far another account covered it; where some bill may not have been read, a cover short of the
    whole gap is said of the accounts read, since an account not wholly read may have covered the rest."""
    read = " by the bills read" if billing.unread else ""
    rows = []
    for s in billing.subscriptions:
        for gap in s.gaps:
            if gap.covered_days == gap.days:
                covered = f"all, by {', '.join(gap.covered_by)}"
            elif gap.covered_days:
                covered = f"{plural(gap.covered_days, 'day')}, by {', '.join(gap.covered_by)}{read}"
            else:
                covered = f"none{read}" if read else "no"
            rows.append(GapRow(s.label, gap.start, gap.until, gap.days, covered))
    return tuple(rows)


def subscriptions(billing: BillingReport | None, accounts: list[Entity], now: float,
                  uses: PlanUse | None = None) -> Subscriptions | None:
    """Every recorded bill's figures; None without a billing report. ``uses``, covering every period, splits each
    period's use by what the plans covered (``plan_use``); without it a period's multiple counts all of its use."""
    if billing is None:
        return None
    if not billing.configured:
        return Subscriptions(False, billing.reminder_days)
    token_of: dict[str | None, str] = {e.uuid: e.token for e in accounts}
    coverage = billing.coverage
    note = None
    if coverage is not None:
        note = (f"{coverage.start.isoformat()} to {coverage.until.isoformat()}: a plan on {coverage.covered} of "
                f"{plural(coverage.days, 'day')}")
        without = coverage.days - coverage.covered
        # A day without a plan by the bills read may be one an account not wholly read held.
        note += (f" by the bills read; the bills not read may hold the other {without}." if billing.unread and without
                 else f", none on {without}.")
    return Subscriptions(True, billing.reminder_days, _summary(billing, token_of, now),
                         None if billing.table is None else cost_figures(billing.table, billing, token_of),
                         _periods(billing, uses, now), _gaps(billing), note, billing.unread)


# --- what a full window holds -----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class CapacityPlan:
    plan: str                                    # the plan's name
    five_hour: str                               # what a full 5-hour window held, or —
    weekly: str                                  # what a full weekly window held, or —
    windows: str                                 # how many full 5-hour windows the full weekly window held, or —
    held_by: str                                 # the accounts the bills put on the plan in the range, or none here


@dataclass(frozen=True)
class CapacityWeek:
    monday: date
    plan: str
    five_hour: str                               # "(higher)" or "(lower)" after it where it differs from the plan's
    weekly: str                                  # last stated figure
    windows: str                                 # how many full 5-hour windows the week's full weekly window held


@dataclass(frozen=True)
class Capacity:
    """What a full window held. ``known`` false: no bill source exists, so no account's plan is known."""
    known: bool
    plans: tuple[CapacityPlan, ...] = ()         # every plan WindowTally knows, in its order
    weeks: tuple[CapacityWeek, ...] = ()         # each week from Monday with a step of the plan, oldest first


def _held_text(figure: Held) -> str:
    """Whole dollars from $10, cents below, so the sum shown is never coarser than the tenth it is good to."""
    if figure.full is None:
        return "—"
    return money_tick(figure.full) if figure.full >= 10 else f"${figure.full:,.2f}"


def _week_cell(figure: Held, before: Held | None) -> str:
    """A week's figure, marked higher or lower where it reads differently from the plan's last stated one and differs
    from it by more than the two figures' rounding allows."""
    text = _held_text(figure)
    if figure.full is None or before is None or text == _held_text(before) or not differs(figure, before):
        return text
    return text + (" (higher)" if figure.full > before.full else " (lower)")


def _windows_text(five_hour: Held, weekly: Held) -> str:
    """How many full 5-hour windows a full weekly window held, the weekly figure over the 5-hour one, with the range
    the two figures' rounding leaves it in: their shares of themselves add."""
    if not five_hour.full or not weekly.full:     # unstated, or no dollars recorded between the readings
        return "—"
    ratio = weekly.full / five_hour.full
    bound = ratio * (weekly.spread / weekly.full + five_hour.spread / five_hour.full)
    return f"{ratio:.1f} ({max(0.0, ratio - bound):.1f}–{ratio + bound:.1f})"


def plan_capacity(ledger: Ledger, accounts: list[Entity], billing: BillingReport | None, since: float,
                  now: float, uses: PlanUse | None = None) -> Capacity:
    """What a full window held per plan, over the readings from ``since`` to ``now`` and week by week from the Monday
    of ``since``'s week (``capacity``), the dollars the plans' own, from ``uses`` where it covers ``since`` on."""
    if billing is None or not billing.configured:
        return Capacity(False)
    taken = steps(ledger, plan_spans(billing), since, now, uses)
    place = {e.uuid: index for index, e in enumerate(accounts)}
    label = {e.uuid: e.label for e in accounts}
    # An account not wholly read holds no plan by its bills, so a plan none of the others held is said of those read.
    nobody = "none by the bills read" if billing.unread else "none here"
    plans = []
    for key, name in PLANS.items():
        holders = sorted({uuid for s in billing.subscriptions for p in s.periods
                          if p.bill.plan == key and day_start(p.bill.start) < now and day_start(p.until) > since
                          and p.until > p.bill.start for uuid in s.uuids},
                         key=lambda uuid: (place.get(uuid, len(place)), uuid))
        five_hour, weekly = (held(s for s in taken if s.plan == key and s.kind == kind) for kind in KINDS)
        plans.append(CapacityPlan(name, _held_text(five_hour), _held_text(weekly), _windows_text(five_hour, weekly),
                                  ", ".join(label.get(u, u) for u in holders) or nobody))
    starts = mondays(local_midnight(monday_of(since)).timestamp(), now)
    boundaries = [m.timestamp() for m in starts] + [local_midnight(starts[-1].date() + timedelta(days=7)).timestamp()]
    by_week: dict[tuple[int, str], list] = defaultdict(list)
    for step in taken:
        by_week[(bisect_right(boundaries, step.t) - 1, step.plan)].append(step)
    weeks, last = [], {}
    for week, monday in enumerate(starts):
        for key, name in PLANS.items():
            in_week = by_week.get((week, key))
            if not in_week:
                continue
            cells, figures = [], []
            for kind in KINDS:
                figure = held(s for s in in_week if s.kind == kind)
                cells.append(_week_cell(figure, last.get((key, kind))))
                figures.append(figure)
                if figure.full is not None:
                    last[(key, kind)] = figure
            weeks.append(CapacityWeek(monday.date(), name, *cells, _windows_text(*figures)))
    return Capacity(True, tuple(plans), tuple(weeks))


# --- the summary ------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Share:
    entity: Entity
    cost: float                                  # its API-equivalent cost over the span


@dataclass(frozen=True)
class Summary:
    """The figures most looked at, over the span shown. Shares and the costliest family are of the API-equivalent cost."""
    api: float                                   # API-equivalent cost of the span's local days
    days: float                                  # the span's days elapsed, today counted by the part of it gone
    plans: Fraction | None                       # the plans' cost at list price on the span's dates; None: no bill
                                                 # source, or not known (``plans_unread``)
    shares: tuple[Share, ...]                    # every account in the accounts' order, then the use with no known
                                                 # account where it has any
    family: tuple[str, float] | None             # the costliest model family and its cost; None without priced use
    exhausted: float | None                      # hours with every account exhausted; None: the ledger knows nothing
                                                 # of the windows
    tokens: int | None = None                    # every token on the span's days; None: not counted, and no tile
    plans_unread: bool = False                   # plans is None because some bill may not have been read
    outside: float | None = None                 # of api, paid outside the plans (``plan_use``); None: not computed
    beyond: float | None = None                  # of what the plans covered, beyond one window a week; None: not
                                                 # computed

    @property
    def per_day(self) -> float:
        return self.api / self.days if self.days > 0 else 0.0

    @property
    def multiple(self) -> float | None:
        """The use the plans covered — the API-equivalent cost less what was paid outside them — as a multiple of the
        plans' cost, where that is above nothing: the multiple with resets."""
        return (self.api - (self.outside or 0.0)) / float(self.plans) if self.plans else None

    @property
    def multiple_one_window(self) -> float | None:
        """The part of that use within one window a week as a multiple of the plans' cost: the multiple without
        resets; None where it was not computed."""
        if self.multiple is None or self.beyond is None:
            return None
        return self.multiple - self.beyond / float(self.plans)


@dataclass(frozen=True)
class Tile:
    caption: str
    figure: str
    share: float | None = None                   # an account's share of the cost, 0 to 1, where the tile is one
    token: str = ""                              # that account's palette token, its share drawn in its colour


def days_elapsed(first: date, now: float) -> float:
    """The days from ``first`` to ``now``: each local day before today whole, today by the part of it gone — its own
    length, so a day of a clock change counts as one — so a rate over them does not fall at each midnight."""
    today = local_datetime(now).date()
    start = local_midnight(today).timestamp()
    length = local_midnight(today + timedelta(days=1)).timestamp() - start
    return (today - first).days + (now - start) / length


def plans_cost(billing: BillingReport | None, first: date, last: date) -> Fraction | None:
    """The plans' cost at list price on the bills' UTC days dated ``first`` to ``last``, each period's list price per
    printed day (``billing.Period.daily``) on its days in effect, every subscription once; None without a bill
    source, and while some bill may not have been read, when it is not known."""
    if billing is None or not billing.configured or billing.unread:
        return None
    after = last + timedelta(days=1)
    total = Fraction(0)
    for s in billing.subscriptions:
        for period in s.periods:
            days = (min(period.until, after) - max(period.bill.start, first)).days
            if days > 0:
                total += period.daily * days
    return total


def summary(ledger: Ledger, accounts: dict[str, Account], shown: list[Entity], costs: Costs,
            billing: BillingReport | None, first: date, now: float,
            weeks: tuple[ExhaustedWeek, ...] | None = None, tokens: int | None = None,
            use: Use | None = None) -> Summary:
    """The summary over the local days ``first`` to today, from their API-equivalent costs per day (``daily_costs``
    over those days, never summed into weeks), so its total is what the cost charts and the usage tables over them add
    up to. ``weeks`` are the exhausted weeks from ``first``'s midnight, where the caller has them; else they are
    computed. ``tokens`` are the same days' tokens (``TokenUse.total``), which the token chart adds up to. ``use`` is
    the same span's use split by what the plans covered (``plan_use``); without it the multiple counts all of it and
    the multiple without resets is not given."""
    if weeks is None:
        weeks = exhausted_weeks(ledger, accounts.values(), local_midnight(first).timestamp(), now)
    known = [week.hours for week in weeks if week.known]
    by_entity = {entry.entity: sum(sum(s.values) for s in entry.families) for entry in costs.families}
    by_family: dict[str, float] = defaultdict(float)
    for entry in costs.families:
        for stack in entry.families:
            by_family[stack.label] += sum(stack.values)
    shares = [Share(entity, by_entity.get(entity, 0.0)) for entity in shown]
    if UNATTRIBUTED in by_entity:
        shares.append(Share(UNATTRIBUTED, by_entity[UNATTRIBUTED]))
    costliest = max(by_family.items(), key=lambda item: item[1], default=None)
    return Summary(api=sum(by_entity.values()), days=days_elapsed(first, now),
                   plans=plans_cost(billing, first, local_datetime(now).date()), shares=tuple(shares),
                   family=costliest if costliest and costliest[1] > 0 else None,
                   exhausted=sum(known) if known else None, tokens=tokens,
                   plans_unread=bool(billing is not None and billing.configured and billing.unread),
                   outside=None if use is None else use.outside, beyond=None if use is None else use.beyond)


MULTIPLE_CAPTION = "API-equivalent ÷ plans"
ONE_WINDOW_CAPTION = "Without resets ÷ plans"
OUTSIDE_CAPTION = "Outside the plans"


def summary_tiles(s: Summary) -> tuple[Tile, ...]:
    """The summary in words, caption over figure, in the order both surfaces show it. Without a bill source there is
    no plans' cost and no multiple; with some bill not read the plans' cost is said not to be known, and there is no
    multiple; a share needs some priced use to be one of. Where the use was split by what the plans covered, the use
    paid outside them stands after the cost where there is any — the multiples leave it out — and the multiple without
    resets after the one with them where the two read differently, as the month's line and a plan period say it
    (``billing.month_totals_text``, ``_period_use``). An account's share tile also carries the share itself and the
    account's token, so a surface can draw it as a bar in the account's colour beside the figure."""

    def share(cost: float) -> str:
        return f"{cost / s.api * 100:.0f}%" if s.api > 0 else "—"

    tiles = [Tile("API-equivalent cost", usd(s.api)), Tile("API-equivalent per day", usd(s.per_day))]
    if s.outside is not None and s.outside >= 0.005:
        tiles.append(Tile(OUTSIDE_CAPTION, usd(s.outside)))
    if s.plans_unread:
        tiles.append(Tile("Plans at list price", "not known"))
    elif s.plans is not None:
        tiles.append(Tile("Plans at list price", usd(float(cents(s.plans)))))
        if s.multiple is not None:
            tiles.append(Tile(MULTIPLE_CAPTION, f"{s.multiple:.1f}×"))
            if s.multiple_one_window is not None and f"{s.multiple_one_window:.1f}" != f"{s.multiple:.1f}":
                tiles.append(Tile(ONE_WINDOW_CAPTION, f"{s.multiple_one_window:.1f}×"))
    if s.tokens is not None:
        tiles.append(Tile("Tokens", count(s.tokens)))
    tiles += [Tile(f"{item.entity.label}'s share", share(item.cost), item.cost / s.api if s.api > 0 else None,
                   item.entity.token) for item in s.shares]
    tiles.append(Tile("Top model family", "—" if s.family is None else f"{s.family[0]} · {share(s.family[1])}"))
    tiles.append(Tile("Hours all exhausted", "no data" if s.exhausted is None else f"{s.exhausted:.1f} h"))
    return tuple(tiles)


# --- coverage ---------------------------------------------------------------------------------------------------------

def _bill_sources(billing: BillingReport | None) -> list[str]:
    if billing is None or not billing.configured:
        return ["No bills recorded."]
    items = []
    for source in billing.bill_set.sources:
        if source.bills is not None:
            items.append(f"Bills: {source.bills:,} read from {source.path} ({source.format})"
                         + (f", {len(source.left_out):,} left out." if source.left_out else "."))
        elif source.problems:
            items.append(f"Bills: {source.path} was not read.")
    for duplicate in billing.bill_set.duplicates:
        items.append(f"The bill {duplicate.reference} of {duplicate.account} is in "
                     f"{', '.join(duplicate.origins)}: " + ("counted once." if duplicate.counted else
                                                           "left out, its copies differing."))
    return items


def coverage(ledger: Ledger, accounts: Iterable[str], now: float, errors: list[str],
             billing: BillingReport | None = None) -> tuple[str, ...]:
    """What the ledger and the bills cover, and the problems met reading the sources. A response has no known account
    when it has none at all or one not among ``accounts`` (WindowTally's, by UUID) — the use the charts and tables put
    under ``UNATTRIBUTED``, such as an account the desktop app signed in to before the sync stored its profile."""
    first_response = ledger.db.execute("SELECT MIN(t) FROM responses").fetchone()[0]
    first_app = ledger.db.execute("SELECT MIN(t) FROM observations WHERE source='app'").fetchone()[0]
    first_plugin = ledger.db.execute("SELECT MIN(t) FROM observations WHERE source='plugin'").fetchone()[0]
    first_browser = ledger.db.execute("SELECT MIN(t) FROM observations WHERE source='browser'").fetchone()[0]
    known = set(accounts)
    unattributed = sum(n for account, n in ledger.db.execute(
        "SELECT account_uuid, COUNT(*) FROM responses GROUP BY account_uuid") if account not in known)
    items = [
        f"Responses recorded since {when(first_response, now)}." if first_response else "No responses recorded yet.",
        f"Desktop app samples since {when(first_app, now)}." if first_app else "No desktop app samples yet.",
        f"Plugin readings since {when(first_plugin, now)}." if first_plugin else
        "No plugin readings yet." if first_browser else
        "No plugin readings yet: reset times are inferred (≈).",
    ] + ([f"Browser readings since {when(first_browser, now)}."] if first_browser else []) + [
        f"{unattributed:,} responses have no known account." if unattributed else "Every response has an account.",
    ] + _bill_sources(billing) + [f"Source problem: {e}" for e in errors]
    return tuple(items)


# --- the sections shown in one of two views ---------------------------------------------------------------------------

# Three sections hold two views of one kind each, and every surface shows one view at a time, a switch beside the
# section's heading choosing it: the cost chart and the token chart, on the same columns; the token tables by week and
# by month, of the same columns; and what a full window held by plan and by week. A switch's views, by its key, in the
# switch's order and words.
COLUMNS_SWITCH = "columns"
TOKEN_TABLES_SWITCH = "token-tables"
CAPACITY_SWITCH = "capacity"
SWITCH_VIEWS = {COLUMNS_SWITCH: ("Cost", "Tokens"), TOKEN_TABLES_SWITCH: ("week", "month"),
                CAPACITY_SWITCH: ("plan", "week")}


def shown_view(key: str, chosen: Mapping[str, str], by_week: bool = False) -> str:
    """The view switch ``key`` shows: the one ``chosen`` names, else its first — the token tables by month where the
    charts' columns are weeks (``by_week``), a span long enough that its weeks outnumber what a table shows at once."""
    views = SWITCH_VIEWS[key]
    if chosen.get(key) in views:
        return chosen[key]
    return views[1] if key == TOKEN_TABLES_SWITCH and by_week else views[0]


# --- the window's spans -----------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Span:
    key: str
    label: str                                   # on the span's button
    words: str                                   # in a sentence: "Computing 6 months…"


SPANS = (Span("7d", "7 days", "7 days"), Span("30d", "30 days", "30 days"), Span("6mo", "6 months", "6 months"),
         Span("all", "All", "the whole history"))
SPAN_OF = {span.key: span for span in SPANS}
WEEKLY_COLUMNS = ("6mo", "all")                  # spans whose cost is shown per week


def first_record(ledger: Ledger) -> float | None:
    """The ledger's first response or reading."""
    return ledger.db.execute("SELECT MIN(t) FROM (SELECT MIN(t) AS t FROM responses UNION ALL "
                             "SELECT MIN(t) FROM observations)").fetchone()[0]


def first_day(key: str, ledger: Ledger, today: date) -> date:
    """The span's first local day: 7 and 30 days count today; 6 months start on the same day six calendar months
    back, or on that month's last day; all starts on the day of the ledger's first record."""
    if key == "7d":
        return today - timedelta(days=6)
    if key == "30d":
        return today - timedelta(days=29)
    if key == "6mo":
        year, month = (today.year, today.month - 6) if today.month > 6 else (today.year - 1, today.month + 6)
        last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
        return date(year, month, min(today.day, last))
    if key == "all":
        first = first_record(ledger)
        return min(today, local_datetime(first).date()) if first is not None else today
    raise ValueError(f"no span {key!r}")


@dataclass(frozen=True)
class History:
    """Every section of the history page over one span, as the window's History view shows it."""
    span: Span
    now: float
    first: date
    accounts: tuple[Entity, ...]
    summary: Summary
    weekly: WeeklyUsage
    products: ProductTable                       # the weekly windows' use by product, under the weekly chart
    resets: ResetTable                           # the weeks with a reset outside the schedule, under the weekly chart
    costs: Costs                                 # per day, or per week from Monday where ``by_week``
    by_week: bool
    tokens: TokenUse                             # charted as the costs are; its tables by week and by month
    subscriptions: Subscriptions | None          # every recorded bill, whatever the span
    capacity: Capacity                           # what a full window held over the span
    exhausted: tuple[ExhaustedWeek, ...]
    usage: UsageTables
    coverage: tuple[str, ...]


def history(ledger: Ledger, accounts: dict[str, Account], span: Span, now: float, *,
            billing: BillingReport | None, errors: list[str]) -> History:
    """The history over ``span``; the ledger is only read."""
    shown = entities(ledger, accounts)
    today = local_datetime(now).date()
    first = first_day(span.key, ledger, today)
    since = local_midnight(first).timestamp()
    costs = daily_costs(ledger, shown, first, today)
    weekly = span.key in WEEKLY_COLUMNS
    exhausted = exhausted_weeks(ledger, accounts.values(), since, now)
    tokens = token_use(ledger, shown, (first, today), (first, today), (first, today), weekly)
    uses = plan_use(ledger, uses_start(billing, since), now)
    figures = summary(ledger, accounts, shown, costs, billing, first, now, exhausted, tokens.total,
                      uses.between(since, now))
    return History(span, now, first, tuple(shown), figures, weekly_usage(ledger, shown, since, now, uses),
                   product_table(ledger, shown, since, now), reset_table(shown, uses, since, now),
                   by_week(costs) if weekly else costs, weekly, tokens, subscriptions(billing, shown, now, uses),
                   plan_capacity(ledger, shown, billing, since, now, uses), exhausted,
                   usage_tables(ledger, shown, since), coverage(ledger, accounts, now, errors, billing))


def uses_start(billing: BillingReport | None, since: float) -> float:
    """Where the use must be split from (``plan_use``) to answer for ``since`` on and for every recorded plan
    period."""
    if billing is None or not billing.configured:
        return since
    return min([since, *(day_start(p.bill.start) for s in billing.subscriptions for p in s.periods
                         if p.until > p.bill.start)])
