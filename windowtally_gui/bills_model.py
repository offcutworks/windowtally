"""The Bills and sources window's content: the bills as each source gives them, the sources, the renewal reminder, and
the form a bill is recorded or changed through.

Every rule a bill obeys is WindowTally's own (``windowtally.bills``): the form only parses what the user typed and hands
it to ``make_bill``, so the window accepts exactly what the command line accepts and refuses it in the same words.
The rows of WindowTally's own bills file are that file as read, every entry in it that reads as a bill — a copy that
disagrees with another source, and a bill another entry of its reference left out, are left out of the figures, and
listed here so that they can be put right — and only they can be changed or removed, while the file reads whole; a
further source's bills are the user's archive, read-only here, and appear as the figures count them. A refund stands
directly under the bill it credits.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from windowtally.billing import money_text
from windowtally.bills import KINDS, PLANS, Bill, BillsError, load_bills, make_bill, parse_day, read_bills_entries
from windowtally.paths import MachinePaths

KIND_NAMES = {"subscription": "subscription", "topup": "top-up", "usage": "usage settled", "refund": "refund"}
PLAN_KEYS = {name: key for key, name in PLANS.items()}
_GROUPED = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")   # an amount with thousands separators: 1,408.63


@dataclass(frozen=True)
class BillRow:
    bill: Bill
    date: str
    account: str
    what: str
    amount: str
    period: str
    reference: str
    source: str
    editable: bool          # a bill of WindowTally's own file, which the window may change or remove


@dataclass(frozen=True)
class SourceRow:
    path: Path
    format: str
    bills: int | None       # None when absent or refused
    problems: tuple[str, ...]
    own: bool               # WindowTally's own bills file, read whenever it exists and never removed from the list
    left_out: tuple[str, ...] = ()   # each bill it holds that was not read, why

    @property
    def count(self) -> str:
        """How much of it was read, in words."""
        if self.bills is None:
            return "not read" if self.problems else "absent"
        return f"{self.bills} bill{'' if self.bills == 1 else 's'}" + (
            f", {len(self.left_out)} left out" if self.left_out else "")

    @property
    def name(self) -> str:
        return f"{self.path}" + (" (own)" if self.own else "")


@dataclass(frozen=True)
class BillsList:
    rows: tuple[BillRow, ...]
    sources: tuple[SourceRow, ...]
    problems: tuple[str, ...]
    reminder_days: int | None
    accounts: tuple[str, ...]      # e-mails a new bill can be addressed to
    currencies: tuple[str, ...]    # the currencies the bills listed were charged in, alphabetical: the form's
                                   # suggestions, so WindowTally suggests no currency of its own


def _what(bill: Bill) -> str:
    return PLANS[bill.plan] if bill.plan else KIND_NAMES.get(bill.kind, bill.kind)


def _row(bill: Bill, source: str, editable: bool) -> BillRow:
    period = f"{bill.start.isoformat()} → {bill.end.isoformat()}" if bill.start and bill.end else ""
    return BillRow(bill=bill, date=bill.date.isoformat(), account=bill.account, what=_what(bill),
                   amount=money_text(bill.amount, bill.currency), period=period, reference=bill.reference or "",
                   source=source, editable=editable)


def _placed(rows: list[BillRow]) -> list[BillRow]:
    """Newest first, each refund directly under the bill it credits where that bill is listed, paired by the key that
    pairs them in the figures (``windowtally.bills.Bill.key``); a row left out of the figures still has its place."""
    credited = {r.bill.key[:2]: r.bill for r in rows if r.bill.kind != "refund" and r.bill.reference}

    def place(row: BillRow) -> tuple:
        bill = credited.get(row.bill.key[:2]) if row.bill.kind == "refund" else None
        return (bill.date, bill.order, 0, row.bill.order) if bill else (row.bill.date, row.bill.order, 1, row.bill.order)

    return sorted(rows, key=place, reverse=True)


def read_list(paths: MachinePaths, known_accounts: tuple[str, ...] = ()) -> BillsList:
    """Every source as it reads now. ``known_accounts`` are the e-mails of the accounts status.json names."""
    bill_set = load_bills(paths)
    own_rows: list[BillRow] = []
    if paths.bills_file.is_file():
        try:
            entries, broken = read_bills_entries(paths.bills_file)
        except (BillsError, OSError):
            entries, broken = [], ()   # its problems are the source's, listed with it
        # The window writes only a file that reads whole, so a file with a broken entry lists its bills read-only.
        own_rows = [_row(b, paths.bills_file.name, not broken) for b in entries]
    others = [b for b in bill_set.bills if b.order[0] != 0]
    source_names = {index: s.path.name for index, s in enumerate(bill_set.sources)}
    rows = _placed(own_rows + [_row(b, source_names.get(b.order[0], "?"), False) for b in others])
    sources = tuple(SourceRow(path=s.path, format=s.format, bills=s.bills, problems=s.problems,
                              own=index == 0, left_out=s.left_out) for index, s in enumerate(bill_set.sources))
    accounts = tuple(sorted(set(a.lower() for a in known_accounts if a) | {r.account for r in rows}))
    return BillsList(rows=tuple(rows), sources=sources, problems=bill_set.errors,
                     reminder_days=bill_set.settings.renewal_reminder_days, accounts=accounts,
                     currencies=tuple(sorted({r.bill.currency for r in rows})))


@dataclass(frozen=True)
class BillForm:
    """What the form's fields hold, as typed."""

    account: str = ""
    date: str = ""
    kind: str = "subscription"
    plan: str = ""          # a plan's name, as PLANS spells it
    amount: str = ""
    currency: str = ""
    start: str = ""
    end: str = ""
    reference: str = ""
    note: str = ""


def next_month(day: date) -> date:
    """The same day a month on, or the month's last day where it has no such day: a month from 31 Jan is 28 Feb."""
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def blank_form(bills: BillsList, account: str, today: date) -> BillForm:
    """A new bill for ``account``, charged today: plan, amount and currency as its latest subscription bill had
    them, its period a month from today."""
    latest = next((r.bill for r in bills.rows if r.bill.account == account.lower() and r.bill.kind == "subscription"),
                  None)
    return BillForm(account=account, date=today.isoformat(), kind="subscription",
                    plan=PLANS[latest.plan] if latest and latest.plan else "",
                    amount=f"{latest.amount:.2f}" if latest else "", currency=latest.currency if latest else "",
                    start=today.isoformat(), end=next_month(today).isoformat())


def form_of(bill: Bill) -> BillForm:
    """The form holding ``bill``, to change it."""
    return BillForm(account=bill.account, date=bill.date.isoformat(), kind=bill.kind,
                    plan=PLANS[bill.plan] if bill.plan else "", amount=f"{bill.amount:.2f}", currency=bill.currency,
                    start=bill.start.isoformat() if bill.start else "", end=bill.end.isoformat() if bill.end else "",
                    reference=bill.reference or "", note=bill.note or "")


def takes_plan(kind: str) -> bool:
    return kind == "subscription"


def takes_period(kind: str) -> bool:
    return kind in ("subscription", "usage")


def check(form: BillForm) -> Bill:
    """The bill the form describes; ValueError naming every problem, in WindowTally's words. A plan or a period the kind
    does not take is ignored, since the form leaves those fields closed for it."""
    problems = []
    if form.kind not in KINDS:
        problems.append(f"the kind {form.kind!r} is not one of {', '.join(KINDS)}")

    def day(text: str, what: str) -> date | None:
        try:
            return parse_day(text, what)
        except ValueError as exc:
            problems.append(str(exc))
            return None

    charged = day(form.date, "the date")
    amount = None
    figures = form.amount.strip()
    if "," in figures and not _GROUPED.match(figures):
        # Not a thousands separator: a decimal comma ("12,50") would otherwise read as 1250.
        problems.append(f"the amount {form.amount!r} is not a number: write its decimals after a point")
    else:
        try:
            amount = Decimal(figures.replace(",", ""))
        except InvalidOperation:
            problems.append(f"the amount {form.amount!r} is not a number")
    start = end = None
    if takes_period(form.kind):
        start, end = day(form.start, "the period's start"), day(form.end, "the period's end")
    plan = None
    if takes_plan(form.kind):
        plan = PLAN_KEYS.get(form.plan.strip(), form.plan.strip() or None)
    if problems:
        raise ValueError("; ".join(problems))
    return make_bill(account=form.account, day=charged, kind=form.kind, plan=plan, amount=amount,
                     currency=form.currency.strip().upper(), start=start, end=end,
                     reference=form.reference.strip() or None, origin="the window", position=0,
                     note=form.note.strip() or None)


def with_kind(form: BillForm, kind: str, today: date) -> BillForm:
    """The form after its kind changed: a period opened for a kind that takes one starts at the charge date."""
    if takes_period(kind) and not form.start:
        try:
            first = date.fromisoformat(form.date)
        except ValueError:
            first = today
        return replace(form, kind=kind, start=first.isoformat(), end=next_month(first).isoformat())
    return replace(form, kind=kind)
