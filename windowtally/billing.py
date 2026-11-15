"""What the bills say about each subscription: its plan over time, the gaps between recorded periods, the plans' cost
at their US list price per month, the days with a plan, how far it is paid up, whether the profile agrees, and the
API-equivalent use of each period.

Vocabulary
    period      a subscription bill's service period, [start, end) in UTC days
    held        a period's plan is held from its start to its printed end, or to its refund's date: a refund ends the
                plan on the day it is dated, half-open, so one dated on or before the period's start leaves it no day
    in effect   a period's plan holds from its start until the end of its holding, or until a later bill's period
                starts inside it: a mid-period change of plan takes effect at once and restarts the period. A change
                billed the same day as the order it replaces leaves that order no day in effect. The days with a plan,
                how far an account is paid up and whether its plan has ended are read from the days in effect, so a
                plan a change replaced does not come back when the plan that replaced it is refunded.
    new order   a period starting on or after the end of every period before it: a renewal, or an order after a gap,
                at any plan. Ordering a lower plan once a period has ended is a new order, never a downgrade.
    gap         days between an account's recorded periods; another account's periods may cover them
    list price  a period's price at its plan's US list price (``pricing.PLAN_PRICES``): the monthly price for a period
                of one calendar month (``spans_months``), the yearly price for a Pro period of one calendar year,
                every plan of ``bills.PLANS`` having its price. A period of any other length is priced by the day at
                the monthly price, twelve months to 365 days, and named as a problem of the bills.
    cost        a period's list price spread evenly over its printed days and counted on the days it was in effect,
                each day in its own month: a period cut short by a change of plan counts only its days in effect, and
                the new plan its own period from the change.

So the cost says what the plan time held is worth at the US list price, never what anyone paid: an upgrade from Max 5x
to Ultra on the tenth day of a 30-day period counts $100 × 10/30 + $200 = $233.33, what a US customer at list price
is charged in all, and a 30-day Pro period refunded on its seventh day $20 × 6/30. A top-up or a settlement of extra
usage has no list price and counts in no figure. A bill's amount and currency are the bill's own record (``bills``),
written with its currency's code wherever bills are listed, and so is the sum a refund returned: no figure reads them,
nothing is converted, and no currency is favoured.

An account whose bills may not all have been read (``bills.Unread``) has no figure at all: its state is ``unread``,
with no plan, no end, no reminder, no profile check and no cost, and this month's cost across the accounts is not known
while any account is so — what was not read is never stated as a plan that ended, a gap or a sum of nothing.

Days are UTC calendar days, as bills print them, and a month is a calendar month of them. Sums are exact fractions;
each figure shown is rounded to the cent on its own, half up, and every total comes from the exact values, never from
the shown ones.

A bill's account is the known account with that e-mail — every one of them, should several share it, the one whose
profile is on this machine standing for them; the bills of an e-mail no account here has are still counted, under
that e-mail. The profile check sets the plan the account's profile names (``accounts``) against the period in effect
today; the profile is as fresh as Claude Code last fetched it.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Collection, Iterator

from .accounts import Account
from .bills import PLAN_RANK, PLANS, Bill, BillSet
from .ledger import Ledger
from .pricing import PLAN_PRICES

ONE_DAY = timedelta(days=1)
CENT = Decimal("0.01")
# Ultra's tier keeps the spelling of the plan's earlier name, Max 20x, as Claude Code 2.1.310's bundle spells it
# (measured on the development machine, 2026-10-31).
_MAX_TIERS = {"default_claude_max_5x": "max5x", "default_claude_max_20x": "ultra"}


# --- days, months, money ------------------------------------------------------------------------------------------

def utc_day(epoch: float) -> date:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).date()


def day_start(day: date) -> float:
    """The epoch second at which a UTC day begins."""
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()


def month_of(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _month_first(month: str) -> date:
    return date(int(month[:4]), int(month[5:7]), 1)


def _next_month(day: date) -> date:
    return date(day.year + day.month // 12, day.month % 12 + 1, 1)


def months_between(first: str, last: str) -> Iterator[str]:
    """Every month from ``first`` to ``last``, both included."""
    day = _month_first(first)
    while month_of(day) <= last:
        yield month_of(day)
        day = _next_month(day)


def month_start(day: date) -> float:
    """The epoch second at which the UTC month holding ``day`` begins."""
    return day_start(day.replace(day=1))


def spans_months(start: date, end: date, months: int) -> bool:
    """Whether [start, end) is ``months`` calendar months as a subscription renewing on its day prints them: to the
    same day, or to the month's last day where it has no such day — and from a month's last day, on to the later day
    the subscription renews on, which that month could not hold. So a month from 31 January ends on 28 February, and
    the next, of a subscription renewing on the 31st, on 31 March."""
    if (end.year * 12 + end.month) - (start.year * 12 + start.month) != months:
        return False
    if end.day == start.day:
        return True
    end_last = calendar.monthrange(end.year, end.month)[1]
    start_last = calendar.monthrange(start.year, start.month)[1]
    return (end.day < start.day and end.day == end_last) or (start.day == start_last and end.day > start.day)


def _month_days(start: date, end: date) -> Iterator[tuple[str, int]]:
    """(month, days) for each month the span [start, end) reaches."""
    cursor = start
    while cursor < end:
        boundary = min(end, _next_month(cursor))
        yield month_of(cursor), (boundary - cursor).days
        cursor = boundary


def cents(value: Fraction | Decimal | float) -> Decimal:
    """``value`` rounded to the cent, half up."""
    exact = Fraction(value)
    return (Decimal(exact.numerator) / Decimal(exact.denominator)).quantize(CENT, rounding=ROUND_HALF_UP)


def money_text(value: Fraction | Decimal | float, currency: str) -> str:
    """A bill's sum in its own currency, rounded to the cent half up, after the currency's code: EUR 1,408.63,
    USD 200.00. Every currency is written alike, so none is favoured."""
    return f"{currency} {cents(value):,.2f}"


def usd_text(value: Fraction | Decimal | float) -> str:
    """A list-price figure in US dollars, rounded to the cent half up: $1,408.63."""
    return f"${cents(value):,.2f}"


def month_totals_text(api: float | None, plans: float | None, unread: bool = False, in_plans: float | None = None,
                      one_window: float | None = None) -> str | None:
    """This UTC month across the accounts, in whole dollars, the use the plans covered as a multiple of the plans'
    cost: ``This month: $1,284 API-equivalent · $300 plans at list price · 4.3×``. ``in_plans`` and ``one_window`` are
    status.json's ``inPlans`` and ``withinOneWindow``: where the plans covered less than the whole — some use was at
    extra usage — the part outside them is said after the sum, and where resets outside the schedule made room for some,
    the multiple without resets follows the one with them where the two read differently: ``$1,284 API-equivalent,
    $84 outside the plans · $300 plans at list price · 4.0× · 3.6× without resets``. The window's header and the
    ``status`` command both say it so. Without bills the plans' cost is not known, nor the multiple; with ``unread``,
    some bills were not read, and the plans' cost is said not to be known; None where nothing is."""
    if api is None and plans is None and not unread:
        return None
    covered = api if in_plans is None else in_plans
    within = covered if one_window is None else one_window
    parts = [] if api is None else [f"${api:,.0f} API-equivalent"
                                    + (f", ${api - covered:,.0f} outside the plans" if api - covered >= 0.5 else "")]
    if unread:
        parts.append("plans at list price not known: some bills could not be read")
    elif plans is not None:
        parts.append(f"${plans:,.0f} plans at list price")
        if api is not None and plans > 0:
            parts.append(f"{covered / plans:.1f}×")
            if f"{within / plans:.1f}" != f"{covered / plans:.1f}":
                parts.append(f"{within / plans:.1f}× without resets")
    return "This month: " + " · ".join(parts)


def refund_words(refund: Bill) -> str:
    """A refund beside the bill it credits, its sum in its own currency: ``refunded USD 58.06 on 2027-05-19``."""
    return f"refunded {money_text(refund.amount, refund.currency)} on {refund.date.isoformat()}"


def _a_plan(plan: str) -> str:
    """A plan's name after the article its first letter takes: a Pro, a Max 5x, an Ultra. Every name of
    ``bills.PLANS`` is spoken as it is spelt; a name whose first letter is not would need its article written out."""
    name = PLANS[plan]
    return f"{'an' if name[0] in 'AEIOU' else 'a'} {name}"


def profile_words(check: str, plan: str | None) -> str:
    """What the profile check found, in words."""
    named = PLANS.get(plan or "", "")
    return {
        "matches": "the profile names the same plan",
        "differs": f"the profile names {named}",
        "profile-older": f"the profile, fetched before this period began, names {named}",
        "no-bill-today": f"the profile names {named}, but no recorded bill covers today",
        "unknown-plan": "the profile names no plan WindowTally compares",
        "no-profile": "no profile of this account on this machine",
        "unread": "not compared with the profile: the account's bills could not all be read",
    }.get(check, check)


def profile_plan(account: Account) -> str | None:
    """The plan an account's profile names, as a key of ``bills.PLANS``; None for any other organization or tier."""
    if account.organization_type == "claude_pro":
        return "pro"
    if account.organization_type == "claude_max":
        return _MAX_TIERS.get(account.rate_limit_tier or "")
    return None


# --- the report ---------------------------------------------------------------------------------------------------

def held_until(bill: Bill, refund: Bill | None) -> date:
    """The day a subscription's plan stopped being held: its printed end, or the day its refund is dated, which ends
    the plan that day, half-open — never before the period's start."""
    if refund is None:
        return bill.end
    return min(bill.end, max(bill.start, refund.date))


@dataclass(frozen=True)
class Period:
    bill: Bill
    until: date                   # the end of the days its plan was in effect; its start when it had none
    how: str                      # new | change (a mid-period change of plan) | overlap (inside one, no higher plan)
    previous_plan: str | None     # for a change or an overlap the plan it started inside, else the last one before
    gap_before: int | None        # for a new order after a gap: the gap's days
    price: Fraction               # its list price, for its printed days
    refund: Bill | None = None    # the refund that ended its plan, where one did

    @property
    def held(self) -> date:
        """The end of the days its plan was held: its printed end, or its refund's date."""
        return held_until(self.bill, self.refund)

    @property
    def daily(self) -> Fraction:
        """Its list price per printed day: what each of its days in effect counts, the month table's and its own."""
        return self.price / (self.bill.end - self.bill.start).days

    @property
    def cost(self) -> Fraction:
        """Its list price counted on its days in effect."""
        return self.daily * max(0, (self.until - self.bill.start).days)


def describe_start(period: Period) -> str:
    """How a period began, in words."""
    previous = PLANS.get(period.previous_plan or "")
    if period.how == "change":
        return f"change of plan from {previous}"
    if period.how == "overlap":
        return f"starts inside {_a_plan(period.previous_plan)} period without raising the plan"
    if period.previous_plan is None:
        return "first order"
    days = period.gap_before
    text = f"new order after {days} day{'' if days == 1 else 's'} without a plan" if days else "renewal"
    if PLAN_RANK[period.bill.plan] < PLAN_RANK[period.previous_plan]:
        text += f", lower than the {previous} before"
    return text


@dataclass(frozen=True)
class Gap:
    start: date                   # the day the account's previous periods ended
    until: date                   # the day its next period began
    covered_days: int             # days another account's period covered
    covered_by: tuple[str, ...]   # those accounts' labels

    @property
    def days(self) -> int:
        return (self.until - self.start).days


@dataclass(frozen=True)
class PeriodUse:
    period: Period
    api_usd: float | None         # API-equivalent cost of the account's responses while the period was in effect
    known_from: float | None      # set when the ledger's record of the account begins inside the period


@dataclass(frozen=True)
class Subscription:
    email: str
    label: str
    uuid: str | None              # the known account standing for this e-mail, if any
    uuids: tuple[str, ...]        # every known account with this e-mail
    bills: tuple[Bill, ...]       # oldest first, refunds among them
    periods: tuple[Period, ...]
    gaps: tuple[Gap, ...]
    uses: tuple[PeriodUse, ...]
    state: str                    # active | ended | upcoming | none (no subscription bill) | unread (its bills may
                                  # not all have been read: no period, gap, use, plan, end or cost is stated)
    plan: str | None              # the plan in effect today
    paid_until: date | None       # active: the end of the periods that run on from today; ended: the last end;
                                  # upcoming: the next start
    days_left: int | None         # active: whole days from today to paid_until
    renew_soon: bool              # active and within the renewal reminder's days
    profile_plan: str | None
    profile_check: str            # matches | differs | profile-older | no-bill-today | unknown-plan | no-profile |
                                  # unread (not compared)
    profile_fetched_at: float | None
    this_month: Fraction | None   # the plans' cost at list price on the days of today's UTC month, the whole month;
                                  # None while unread


@dataclass(frozen=True)
class MonthFigures:
    month: str
    cost: dict[str, Fraction]           # e-mail -> the plans' cost at list price on that month's days
    service_days: dict[str, int]        # e-mail -> days with a recorded plan
    any_service_days: int               # days on which at least one of the table's accounts had one


@dataclass(frozen=True)
class CostTable:
    emails: tuple[str, ...]             # the accounts whose plans cost anything, in the report's order
    months: tuple[MonthFigures, ...]    # every month from the first day a plan was in effect to the last


@dataclass(frozen=True)
class Coverage:
    start: date
    until: date
    covered: int                        # days on which some account had a recorded plan

    @property
    def days(self) -> int:
        return (self.until - self.start).days


@dataclass(frozen=True)
class BillingReport:
    today: date
    bill_set: BillSet
    subscriptions: tuple[Subscription, ...]
    table: CostTable | None             # None while no plan was in effect on any day; the accounts read alone
    this_month: Fraction | None         # every subscription's cost at list price this UTC month, each e-mail once;
                                        # None while any bill may not have been read
    coverage: Coverage | None           # the accounts read alone
    reminder_days: int | None
    problems: tuple[str, ...]           # what the bills contradict, for the status file's sourceErrors

    @property
    def configured(self) -> bool:
        return self.bill_set.configured

    @property
    def unread(self) -> bool:
        """Whether any bill a source holds may not have been read: then figures across the accounts are not known, and
        an absence across them is not stated."""
        return bool(self.bill_set.unread)

    def for_account(self, uuid: str) -> Subscription | None:
        return next((s for s in self.subscriptions if uuid in s.uuids), None)


# --- periods ------------------------------------------------------------------------------------------------------

def list_price(bill: Bill) -> tuple[Fraction, str | None]:
    """A subscription bill's period at its plan's US list price, and, for a period neither a month nor a year the
    plan is sold by, the problem naming it."""
    price = PLAN_PRICES[bill.plan]
    if spans_months(bill.start, bill.end, 1):
        return Fraction(price.monthly), None
    if price.yearly is not None and spans_months(bill.start, bill.end, 12):
        return Fraction(price.yearly), None
    days = (bill.end - bill.start).days
    sold = "a month or a year" if price.yearly is not None else "a month"
    return (Fraction(price.monthly) * 12 * days / 365,
            f"{bill.origin} is {_a_plan(bill.plan)} period of {days} days, not {sold}: it is counted at the monthly "
            f"list price by the day")


def _periods(subscriptions: list[tuple[Bill, Bill | None]]) -> tuple[list[Period], list[tuple[date, date]], list[str]]:
    """Each subscription bill's period — how it began, the days its plan was in effect and its cost at list price — the
    gaps between the account's periods, and what contradicts the plan rules. ``subscriptions`` are each bill with its
    refund, or None, in (start, date, order) order."""
    periods: list[Period] = []
    gaps: list[tuple[date, date]] = []
    problems: list[str] = []
    covered_until: date | None = None
    for bill, refund in subscriptions:
        price, problem = list_price(bill)
        if problem:
            problems.append(problem)
        held = held_until(bill, refund)
        # A period refunded before a later one starts has ended by then: what starts after its refund is a new order.
        containing = [p for p in periods if p.bill.start <= bill.start < p.held]
        if containing:
            current = containing[-1]  # the latest to start is the one in effect
            raised = PLAN_RANK[bill.plan] > PLAN_RANK[current.bill.plan]
            if not raised:
                problems.append(f"{bill.origin} starts inside the period of {current.bill.origin} without raising "
                                f"the plan; a mid-period change raises it")
            periods.append(Period(bill, held, "change" if raised else "overlap", current.bill.plan, None,
                                  price, refund))
        else:
            gap = None
            if covered_until is not None and bill.start > covered_until:
                gap = (bill.start - covered_until).days
                gaps.append((covered_until, bill.start))
            periods.append(Period(bill, held, "new", periods[-1].bill.plan if periods else None, gap, price, refund))
        covered_until = held if covered_until is None else max(covered_until, held)
    cut = []
    for index, period in enumerate(periods):
        later = next((p.bill.start for p in periods[index + 1:] if p.bill.start < period.held), None)
        cut.append(replace(period, until=later) if later is not None else period)
    return cut, gaps, problems


def _cost_by_month(periods: list[Period]) -> dict[str, Fraction]:
    """Each month's share of the periods' cost: a period's list price per printed day, on each of its days in
    effect."""
    cost: dict[str, Fraction] = defaultdict(Fraction)
    for period in periods:
        for month, days in _month_days(period.bill.start, period.until):
            cost[month] += period.daily * days
    return dict(cost)


def _in_effect(periods: list[Period]) -> list[tuple[date, date]]:
    """Each period's days in effect, [start, until), where it had any."""
    return [(p.bill.start, p.until) for p in periods if p.until > p.bill.start]


def _days_of(spans: list[tuple[date, date]]) -> set[date]:
    days: set[date] = set()
    for start, until in spans:
        day = start
        while day < until:
            days.add(day)
            day += ONE_DAY
    return days


def _paid_until(spans: list[tuple[date, date]], today: date) -> date | None:
    """The end of the days in effect that run on without a break from today, or None when none covers today."""
    ends = [until for start, until in spans if start <= today < until]
    if not ends:
        return None
    paid = max(ends)
    for start, until in sorted(spans):
        if today < start <= paid:
            paid = max(paid, until)
    return paid


def _profile_check(profile: Account | None, state: str, plan: str | None,
                   in_effect: Period | None) -> tuple[str | None, str]:
    if state == "unread":
        return (profile_plan(profile) if profile else None), "unread"
    if profile is None:
        return None, "no-profile"
    named = profile_plan(profile)
    if named is None:
        return None, "unknown-plan"
    if state != "active" or in_effect is None:
        return named, "no-bill-today"
    if named == plan:
        return named, "matches"
    if profile.profile_fetched_at is not None and profile.profile_fetched_at < day_start(in_effect.bill.start):
        return named, "profile-older"
    return named, "differs"


def _uses(periods: list[Period], ledger: Ledger | None, uuids: tuple[str, ...], now: float) -> list[PeriodUse]:
    if ledger is None or not uuids:
        return []
    firsts = [t for t in (ledger.first_response(uuid) for uuid in uuids) if t is not None]
    known_from = min(firsts) if firsts else None
    uses = []
    for period in periods:
        start, end = day_start(period.bill.start), min(day_start(period.until), now)
        if period.until <= period.bill.start or start >= now:
            continue
        if known_from is None or known_from >= end:
            uses.append(PeriodUse(period, None, None))
        else:
            usd = sum(ledger.cost_in(uuid, start, end) for uuid in uuids)
            uses.append(PeriodUse(period, usd, known_from if known_from > start else None))
    return uses


# --- the monthly table --------------------------------------------------------------------------------------------

def _table(cost_of: dict[str, dict[str, Fraction]], order: list[str],
           days_of: dict[str, set[date]]) -> CostTable | None:
    emails = tuple(e for e in order if cost_of[e])
    months = {month for e in emails for month in cost_of[e]}
    if not months:
        return None
    rows = []
    for month in months_between(min(months), max(months)):
        first, after = _month_first(month), _next_month(_month_first(month))
        month_days = [first + ONE_DAY * offset for offset in range((after - first).days)]
        rows.append(MonthFigures(
            month=month,
            cost={e: cost_of[e][month] for e in emails if month in cost_of[e]},
            service_days={e: sum(1 for d in month_days if d in days_of[e]) for e in emails},
            any_service_days=sum(1 for d in month_days if any(d in days_of[e] for e in emails))))
    return CostTable(emails, tuple(rows))


# --- everything ---------------------------------------------------------------------------------------------------

def billing_report(bill_set: BillSet, accounts: dict[str, Account], profiles: dict[str, Account],
                   ledger: Ledger | None, now: float, on_machine: Collection[str] | None = None) -> BillingReport:
    """``accounts`` are the known accounts, by UUID, for labels; ``profiles`` the profiles read this pass, by UUID, for
    the profile check; ``on_machine`` the accounts whose profile is on this machine, the profiles' own when not given
    — a reader that reads no profile passes the ones the last pass recorded (``Ledger.profiles_on_machine``)."""
    today = utc_day(now)
    present = profiles.keys() if on_machine is None else on_machine
    group_of: dict[str, list[Account]] = defaultdict(list)
    for a in sorted(accounts.values(), key=lambda a: a.uuid):
        if a.email:
            group_of[a.email.lower()].append(a)
    # The account standing for an e-mail: one whose profile is on this machine, else the first.
    known = {e: next((a for a in group if a.uuid in present), group[0]) for e, group in group_of.items()}
    bills_of: dict[str, list[Bill]] = defaultdict(list)
    for bill in bill_set.bills:
        bills_of[bill.account].append(bill)
    if bill_set.configured:
        for email in known:
            bills_of.setdefault(email, [])
    for email in bill_set.unread.emails:
        bills_of.setdefault(email, [])
    label_of = {e: known[e].label if e in known else e.split("@", 1)[0] for e in bills_of}
    order = sorted(bills_of, key=lambda e: (label_of[e], e))
    for email in order:
        bills_of[email].sort(key=lambda b: (b.start or b.date, b.date, b.order))
    unread = {e for e in order if bill_set.unread.concerns(e)}
    periods_of: dict[str, tuple[list[Period], list[tuple[date, date]], list[str]]] = {
        e: _periods([(b, bill_set.refund_of(b)) for b in bills_of[e] if b.kind == "subscription"])
        for e in order if e not in unread}
    spans_of = {e: _in_effect(periods_of[e][0]) if e in periods_of else [] for e in order}
    days_of = {e: _days_of(spans_of[e]) for e in order}
    month = month_of(today)
    problems: list[str] = []
    cost_of: dict[str, dict[str, Fraction]] = {}
    subscriptions = []
    for email in order:
        account = known.get(email)
        profile = profiles.get(account.uuid) if account else None
        uuids = tuple(a.uuid for a in group_of.get(email, []))
        if email in unread:
            named, check = _profile_check(profile, "unread", None, None)
            cost_of[email] = {}
            subscriptions.append(Subscription(
                email=email, label=label_of[email], uuid=account.uuid if account else None, uuids=uuids,
                bills=tuple(bills_of[email]), periods=(), gaps=(), uses=(), state="unread", plan=None,
                paid_until=None, days_left=None, renew_soon=False, profile_plan=named, profile_check=check,
                profile_fetched_at=profile.profile_fetched_at if profile else None, this_month=None))
            continue
        periods, raw_gaps, contradictions = periods_of[email]
        spans = spans_of[email]
        problems.extend(contradictions)
        cost_of[email] = _cost_by_month(periods)
        gaps = []
        for start, until in raw_gaps:
            covered, others = 0, set()
            day = start
            while day < until:
                covering = [e for e in order if e != email and day in days_of[e]]
                if covering:
                    covered += 1
                    others.update(label_of[e] for e in covering)
                day += ONE_DAY
            gaps.append(Gap(start, until, covered, tuple(sorted(others))))
        in_effect = next((p for p in reversed(periods) if p.bill.start <= today < p.until), None)
        paid_until = _paid_until(spans, today)
        if not periods:
            state = "none"
        elif paid_until is not None:
            state = "active"
        elif any(start > today for start, _ in spans):
            state, paid_until = "upcoming", min(start for start, _ in spans if start > today)
        else:
            # Every plan has ended: on the last day one was in effect, or, where no period held a day — each refunded
            # on or before its start, or replaced the same day by one that was — on the day of the last refund, which
            # never lies after today the way a refunded period's start can.
            refunded = [p.refund.date for p in periods if p.refund is not None]
            state, paid_until = "ended", max((until for _, until in spans),
                                             default=max(refunded, default=max(p.held for p in periods)))
        plan = in_effect.bill.plan if state == "active" and in_effect else None
        days_left = (paid_until - today).days if state == "active" and paid_until else None
        reminder = bill_set.settings.renewal_reminder_days
        named, check = _profile_check(profile, state, plan, in_effect)
        subscriptions.append(Subscription(
            email=email, label=label_of[email], uuid=account.uuid if account else None, uuids=uuids,
            bills=tuple(bills_of[email]), periods=tuple(periods), gaps=tuple(gaps),
            uses=tuple(_uses(periods, ledger, uuids, now)),
            state=state, plan=plan, paid_until=paid_until, days_left=days_left,
            renew_soon=reminder is not None and days_left is not None and days_left <= reminder,
            profile_plan=named, profile_check=check, profile_fetched_at=profile.profile_fetched_at if profile else None,
            this_month=cost_of[email].get(month, Fraction(0))))
    every_day = set().union(*days_of.values()) if days_of else set()
    coverage = None
    if every_day:
        every_span = [span for spans in spans_of.values() for span in spans]
        coverage = Coverage(min(s for s, _ in every_span), max(u for _, u in every_span), len(every_day))
    return BillingReport(today=today, bill_set=bill_set, subscriptions=tuple(subscriptions),
                         table=_table(cost_of, order, days_of),
                         this_month=None if bill_set.unread else sum((s.this_month for s in subscriptions), Fraction(0)),
                         coverage=coverage, reminder_days=bill_set.settings.renewal_reminder_days,
                         problems=tuple(f"bills: {p}" for p in problems))
