"""The subscription bills: what each one says, WindowTally's own bills file, and reading every source into one list.

Nothing on the machine records what a subscription cost — an account's profile names only the plan it is on now — so
the bills come from the user: WindowTally's own bills file, and any further source ``settings.json`` lists, such as a bill
archive's manifest (``bills_manifest``). Every source is read in full on every pass; the files are small and the
user's own, so WindowTally keeps no copy of them.

WindowTally's own bills file — contract (version 1), ``bills.json`` in WindowTally's data folder, written by
``python -m windowtally bills add``, by the window (``windowtally_gui``), which also replaces and removes a bill, or
by hand:

    {"v": 1, "bills": [
      {"account": "alpha@example.com", "date": "2027-05-07", "kind": "subscription", "plan": "max5x",
       "amount": 100.00, "currency": "USD", "start": "2027-05-07", "end": "2027-06-07",
       "reference": "INV-0012", "note": "renewed at the same plan"},
      {"account": "alpha@example.com", "date": "2027-05-19", "kind": "refund", "amount": 58.06, "currency": "USD",
       "reference": "INV-0012", "note": "cancelled"}]}

    account     the e-mail the bill is addressed to: the account's sign-in e-mail
    date        the charge date as the bill prints it, YYYY-MM-DD; on a refund, the day it was issued
    kind        subscription (a plan's service period) | topup (prepaid extra usage: paid, not yet consumed) |
                usage (extra usage settled for a period; often netted to zero) | refund (a sum returned on the bill
                its reference names, such as a cancellation's prorated refund)
    plan        pro | max5x | ultra, on a subscription only
    amount      what was charged, tax included, a number in the currency's units; on a refund the sum returned,
                unsigned
    currency    an ISO 4217 code; on a refund, the credited bill's
    start, end  the service period of a subscription or a usage settlement, in UTC days: start is the first day
                covered and end the day the next period would start, so a month from 7 May ends on 7 June
    reference   the invoice number; optional, like note, which is text the user keeps beside the bill, save on a
                refund, which names the bill it credits by that bill's reference

A mid-period change of plan is entered as its bill prints it: the amount charged — the new plan's price less the
unused part of the old one — and the new period, which starts at the change. A refund ends the plan of the
subscription it credits on its date (``billing``); its sum is the bill's own record, like any amount, and enters no
figure.

Every bill is checked against the contract. A source whose document breaks it — not JSON, another version, an unknown
key at its top, no list of bills; a manifest without a column it reads — is refused whole. Within a source, an entry
that breaks it is left out together with the bill it belongs to — every entry of its account and reference — and an
entry naming no reference it can be read by belongs to no bill and is left out alone; each is named, and the source's
other bills count. The same bill — one account, one reference — read twice, in two sources or in one, counts once when both copies
agree and not at all when they differ, and is named either way; a refund is a document of its own, never a copy of the
bill it credits, and two refunds of one bill are two copies of one refund. Each refund is matched, across every
source, to the bill of its account and reference, and is left out where it matches none, and with that bill where it
contradicts it: another currency, more than the bill charged, a date before the bill's or, on a bill with a period, on
or after its end.

What was not read is never shown as what does not exist: every source refused, and every bill left out, marks the
accounts it may concern as not wholly read (``Unread``) — the bill's own account where a row of it names one, every
account otherwise — and ``billing`` then states no plan, end or sum for them.

Writing is strict: a bill is added, replaced or removed only in a file that reads whole, and a further source is
listed only once it reads whole, the one moment the user is there to put it right. A bill is replaced or removed by its
place in WindowTally's own file, and only while that place still holds the bill as it was read: a list read before
another writer changed the file never replaces or removes the wrong bill. Further sources are listed in the settings by
``add_source`` and ``remove_source``, which the command line and the window share.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from functools import cached_property
from pathlib import Path
from typing import Callable

from .files import editing, write_text_atomically
from .paths import MachinePaths
from .settings import SOURCE_FORMATS, BillSource, Settings, SettingsError, load_settings, same_file, save_settings

BILLS_VERSION = 1
KINDS = ("subscription", "topup", "usage", "refund")
PLANS = {"pro": "Pro", "max5x": "Max 5x", "ultra": "Ultra"}
PLAN_RANK = {"pro": 1, "max5x": 5, "ultra": 20}
PROBLEMS_PER_LINE = 3            # problems of one source spelt out in its sourceErrors line; the rest are counted
_FIELDS = ("account", "date", "kind", "plan", "amount", "currency", "start", "end", "reference", "note")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class BillsError(ValueError):
    """A bill source that breaks its contract; ``problems`` names every problem found."""

    def __init__(self, source: str, problems: list[str]):
        super().__init__(f"{source}: " + "; ".join(problems))
        self.source = source
        self.problems = problems


@dataclass(frozen=True)
class Bill:
    account: str              # the e-mail the bill is addressed to, lower-cased
    date: date                # the charge date as the bill prints it
    kind: str                 # one of KINDS
    plan: str | None          # a key of PLANS, on a subscription
    amount: Decimal           # as charged, tax included; on a refund the sum returned, unsigned
    currency: str
    start: date | None        # the service period [start, end) in UTC days; None on a top-up and a refund
    end: date | None
    reference: str | None     # the invoice number, when known; on a refund, the credited bill's
    origin: str               # where it was read, for messages: "bills.json bill 3", "_manifest.csv row 12"
    order: tuple[int, int]    # (source, position): bills of one day keep the order their source gives them
    note: str | None = None   # the user's own text beside the bill; no figure depends on it

    def agrees_with(self, other: Bill) -> bool:
        """Whether two copies of one bill say the same thing."""
        fields = ("account", "date", "kind", "plan", "amount", "currency", "start", "end")
        return all(getattr(self, name) == getattr(other, name) for name in fields)

    @property
    def key(self) -> tuple[str, str | None, bool]:
        """What one bill is known by in every source: its account and reference, and whether it is a refund, which
        shares its reference with the bill it credits."""
        return self.account, self.reference, self.kind == "refund"


def parse_day(value: object, what: str) -> date:
    """A YYYY-MM-DD day; ValueError naming ``what`` otherwise."""
    if not isinstance(value, str) or not _DAY.match(value.strip()):
        raise ValueError(f"{what} {value!r} is not YYYY-MM-DD")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"{what} {value!r} is not a calendar day") from None


def make_bill(*, account: object, day: date, kind: str, plan: str | None, amount: Decimal, currency: object,
              start: date | None, end: date | None, reference: str | None, origin: str, position: int,
              note: str | None = None) -> Bill:
    """A bill from parsed values, after the rules every source format shares; ValueError names each broken rule."""
    problems = []
    email = account.strip().lower() if isinstance(account, str) else ""
    if "@" not in email:
        problems.append(f"the account {account!r} is not an e-mail address")
    if not isinstance(kind, str) or kind not in KINDS:
        problems.append(f"the kind {kind!r} is not one of {', '.join(KINDS)}")
    elif kind == "subscription" and not (isinstance(plan, str) and plan in PLANS):
        problems.append(f"the plan {plan!r} is not one of {', '.join(PLANS)}")
    elif kind != "subscription" and plan is not None:
        problems.append(f"a {kind} has no plan")
    if not amount.is_finite() or amount < 0:
        problems.append(f"the amount {amount} is not a sum charged")
    code = currency.strip() if isinstance(currency, str) else ""
    if not _CURRENCY.match(code):
        problems.append(f"the currency {currency!r} is not an ISO 4217 code")
    if kind == "topup" and (start is not None or end is not None):
        problems.append("a top-up has no service period")
    elif kind == "refund" and (start is not None or end is not None):
        problems.append("a refund has no service period: it ends the period of the bill it credits")
    elif kind in ("subscription", "usage") and (start is None or end is None):
        problems.append(f"a {kind} needs its service period")
    elif start is not None and end is not None and end <= start:
        problems.append(f"the service period {start}..{end} ends before it starts")
    if kind == "refund" and not reference:
        problems.append("a refund names the bill it credits by that bill's reference")
    if problems:
        raise ValueError("; ".join(problems))
    return Bill(account=email, date=day, kind=kind, plan=plan, amount=amount, currency=code, start=start, end=end,
                reference=reference or None, origin=origin, order=(0, position), note=note or None)


# --- WindowTally's own bills file ----------------------------------------------------------------------------------

def _amount(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError(f"the amount {value!r} is not a number")
    return Decimal(value)


def _optional_text(entry: dict, name: str) -> str | None:
    value = entry.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"the {name} {value!r} is not text")
    return value.strip() if value else None


def _bill_from_entry(entry: object, origin: str, position: int) -> Bill:
    if not isinstance(entry, dict):
        raise ValueError("it is not an object")
    unknown = [key for key in entry if key not in _FIELDS]
    if unknown:
        raise ValueError(f"unknown field {', '.join(map(repr, unknown))}")
    missing = [name for name in ("account", "date", "kind", "amount", "currency") if name not in entry]
    if missing:
        raise ValueError(f"no {', '.join(missing)}")
    start = parse_day(entry["start"], "the start") if entry.get("start") is not None else None
    end = parse_day(entry["end"], "the end") if entry.get("end") is not None else None
    return make_bill(account=entry["account"], day=parse_day(entry["date"], "the date"), kind=entry["kind"],
                     plan=entry.get("plan"), amount=_amount(entry["amount"]), currency=entry["currency"],
                     start=start, end=end, reference=_optional_text(entry, "reference"), origin=origin,
                     position=position, note=_optional_text(entry, "note"))


def _document(path: Path) -> dict:
    """The bills file's JSON, checked for its version and shape; BillsError otherwise."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"), parse_float=Decimal)
    except ValueError as exc:
        raise BillsError(str(path), [f"it is not JSON ({exc})"]) from None
    if not isinstance(data, dict) or data.get("v") != BILLS_VERSION:
        version = data.get("v") if isinstance(data, dict) else None
        raise BillsError(str(path), [f"it is version {version!r}; this version of WindowTally reads version {BILLS_VERSION}"])
    problems = [f"unknown key {key!r}" for key in data if key not in ("v", "bills")]
    if not isinstance(data.get("bills"), list):
        problems.append("it has no list of bills")
    if problems:
        raise BillsError(str(path), problems)
    return data


@dataclass(frozen=True)
class LeftOut:
    """A bill, or a row of one, that a source holds and WindowTally did not read."""
    account: str | None       # its e-mail, lower-cased, where a row of it names one; None: it may be any account's
    problem: str              # why, and where, as a reader that reads the source whole names it
    outcome: str              # what was left out for it

    @property
    def text(self) -> str:
        return f"{self.problem}; {self.outcome}"


def _email_in(value: object) -> str | None:
    email = value.strip().lower() if isinstance(value, str) else ""
    return email if "@" in email else None


def _entries_of(data: dict, path: Path) -> tuple[list[Bill], list[tuple[int, str | None, str | None, str]]]:
    """Every entry that reads as a bill, and every one that does not: (position, reference, account, problem)."""
    bills, broken = [], []
    for index, entry in enumerate(data["bills"], start=1):
        try:
            bills.append(_bill_from_entry(entry, f"{path.name} bill {index}", index))
        except ValueError as exc:
            reference = entry.get("reference") if isinstance(entry, dict) else None
            reference = (reference.strip() or None) if isinstance(reference, str) else None
            account = _email_in(entry.get("account")) if isinstance(entry, dict) else None
            broken.append((index, reference, account, f"bill {index}: {exc}"))
    return bills, broken


def _bills_of(data: dict, path: Path) -> list[Bill]:
    bills, broken = _entries_of(data, path)
    if broken:
        raise BillsError(str(path), [problem for _, _, _, problem in broken])
    return bills


def read_bills_file(path: Path) -> list[Bill]:
    """The bills of a file in WindowTally's own format, read whole as a writer reads it; BillsError when any of them
    breaks the contract."""
    return _bills_of(_document(path), path)


def read_bills_entries(path: Path) -> tuple[list[Bill], tuple[str, ...]]:
    """Every entry of a file in WindowTally's own format that reads as a bill, a bill left out by another entry of its
    reference included, and the problem of each entry that does not, for a list that shows the file as it stands;
    BillsError when the file's document breaks the contract."""
    bills, broken = _entries_of(_document(path), path)
    return bills, tuple(problem for _, _, _, problem in broken)


def read_bills_source(path: Path) -> SourceRead:
    """A file in WindowTally's own format read as a source: its bills, less each bill an entry that breaks the contract
    belongs to — every entry of that entry's account and reference, or of its reference alone where its account cannot
    be read — and that entry alone where it names no reference; BillsError when the file's document breaks the
    contract. Every account a bill left out belongs to is named, so none of them is shown as having fewer bills."""
    bills, broken = _entries_of(_document(path), path)
    dropped: set[int] = set()
    left_out = []
    for _, reference, account, problem in broken:
        if not reference:
            left_out.append(LeftOut(account, problem, "it names no reference, so it is left out alone"))
            continue
        belonging = [b for b in bills if b.reference == reference and (account is None or b.account == account)]
        dropped.update(id(b) for b in belonging)
        owners = {account} if account else {b.account for b in belonging}
        # An entry whose account cannot be read may be any account's, unless the bills it leaves out name one alone.
        left_out.append(LeftOut(owners.pop() if len(owners) == 1 else None, problem,
                                f"the bill {reference} is left out"))
    return SourceRead(tuple(b for b in bills if id(b) not in dropped), tuple(left_out))


def entry_of(bill: Bill, note: str | None = None) -> dict:
    """The bills-file entry that reads back as ``bill``; ``note``, when given, in place of the bill's own."""
    entry: dict = {"account": bill.account, "date": bill.date.isoformat(), "kind": bill.kind}
    if bill.plan is not None:
        entry["plan"] = bill.plan
    entry["amount"] = bill.amount
    entry["currency"] = bill.currency
    if bill.start is not None and bill.end is not None:
        entry["start"], entry["end"] = bill.start.isoformat(), bill.end.isoformat()
    if bill.reference:
        entry["reference"] = bill.reference
    note = note if note is not None else bill.note
    if note:
        entry["note"] = note
    return entry


def _number(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)  # a two-place amount's shortest float spelling reads back as the same decimal
    raise TypeError(f"{value!r} is not JSON")


def _write_document(path: Path, data: dict) -> None:
    write_text_atomically(path, json.dumps(data, ensure_ascii=False, indent=1, default=_number) + "\n")


def _repeats_reference(bill: Bill, others: list[Bill]) -> bool:
    return bool(bill.reference) and any(b.key == bill.key for b in others)


def _repeated(bill: Bill) -> str:
    return (f"it already holds a refund of the bill {bill.reference} of {bill.account}" if bill.kind == "refund"
            else f"it already holds the bill {bill.reference} of {bill.account}")


def add_bill(path: Path, bill: Bill, note: str | None = None) -> None:
    """Appends ``bill`` to a bills file in WindowTally's own format, creating the file; the file is replaced atomically.

    Refused (BillsError) when the file breaks the contract, or already holds a bill of the account with the same
    reference — for a refund, a refund of the same bill.
    """
    with editing(path):
        data = _document(path) if path.exists() else {"v": BILLS_VERSION, "bills": []}
        existing = _bills_of(data, path)
        if _repeats_reference(bill, existing):
            raise BillsError(str(path), [_repeated(bill)])
        data["bills"].append(entry_of(bill, note))
        _write_document(path, data)


def replace_bill(path: Path, bill: Bill, replacement: Bill | None) -> None:
    """Puts ``replacement`` in the place of ``bill``, as read from WindowTally's own bills file at ``path``, or removes
    ``bill`` when it is None; the file is replaced atomically.

    Refused (BillsError) when the file breaks the contract, when the place ``bill`` was read from no longer holds it as
    it was read — another writer changed the file since — or when the replacement repeats the reference of another
    bill of its account; OSError when the file cannot be read.
    """
    with editing(path):
        data = _document(path)
        existing = _bills_of(data, path)
        index = bill.order[1] - 1
        held = existing[index] if 0 <= index < len(existing) else None
        if held is None or not (held.agrees_with(bill) and held.reference == bill.reference
                                and held.note == bill.note):
            raise BillsError(str(path), [f"{bill.origin} is no longer the bill that was read; read the bills again"])
        if replacement is None:
            del data["bills"][index]
        else:
            if _repeats_reference(replacement, existing[:index] + existing[index + 1:]):
                raise BillsError(str(path), [_repeated(replacement)])
            data["bills"][index] = entry_of(replacement)
        _write_document(path, data)


def remove_bill(path: Path, bill: Bill) -> None:
    """Removes ``bill``, as read from WindowTally's own bills file at ``path``, under ``replace_bill``'s refusals."""
    replace_bill(path, bill, None)


# --- every source ------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceRead:
    """What one source gave: the bills it read, and each bill it holds and did not."""
    bills: tuple[Bill, ...]
    left_out: tuple[LeftOut, ...] = ()


@dataclass(frozen=True)
class SourceReport:
    path: Path
    format: str
    bills: int | None                     # how many bills it gave; None when it is absent or was refused
    problems: tuple[str, ...] = ()        # why it was refused
    left_out: tuple[str, ...] = ()        # each bill it holds and that was not read, why


@dataclass(frozen=True)
class Duplicate:
    account: str
    reference: str
    origins: tuple[str, ...]
    counted: bool                         # the copies agree, so the bill counts once; otherwise not at all


@dataclass(frozen=True)
class Unread:
    """The accounts whose bills may not all have been read, so that no figure states an absence for them: every
    account where a source was refused, or a bill left out names no account; else the e-mails of the bills left out."""
    everyone: bool = False
    emails: frozenset[str] = frozenset()

    def __bool__(self) -> bool:
        return self.everyone or bool(self.emails)

    def concerns(self, email: str) -> bool:
        return self.everyone or email in self.emails


@dataclass(frozen=True)
class BillSet:
    bills: tuple[Bill, ...]               # every bill read and counted, each refund among them matched to its bill
    sources: tuple[SourceReport, ...]
    duplicates: tuple[Duplicate, ...]
    settings: Settings
    errors: tuple[str, ...]               # one line per problem, for the status file's sourceErrors
    unread: Unread = field(default_factory=Unread)
    set_aside: tuple[Bill, ...] = ()      # what refund matching left out — a bill and the refund contradicting it, a
                                          # refund of no bill counted — which a writer putting either right is set against

    @property
    def configured(self) -> bool:
        """Whether there is any bill source at all; without one WindowTally shows no subscription figures. A source
        refused, or a settings file that cannot say which sources there are, counts as one: its bills were not read."""
        return self.unread.everyone or any(s.bills is not None or s.problems for s in self.sources)

    @cached_property
    def _refunds(self) -> dict[tuple[str, str | None], Bill]:
        return {b.key[:2]: b for b in self.bills if b.kind == "refund"}

    def refund_of(self, bill: Bill) -> Bill | None:
        """The refund of ``bill``, where one credits it."""
        if bill.kind == "refund" or not bill.reference:
            return None
        return self._refunds.get(bill.key[:2])


def _reader(format: str) -> Callable[[Path], SourceRead]:
    if format == "manifest":
        # Imported only when a source names the format: WindowTally runs without the module.
        from .bills_manifest import read_manifest_source
        return read_manifest_source
    return read_bills_source


def read_source_in_part(source: BillSource) -> SourceRead:
    """The bills of one source, and each it holds and did not give; BillsError when its document breaks its contract,
    OSError when it cannot be read."""
    return _reader(source.format)(source.path)


def read_source(source: BillSource) -> list[Bill]:
    """The bills of one source read whole; BillsError when any part of it breaks its contract, every problem named,
    OSError when it cannot be read."""
    read = read_source_in_part(source)
    if read.left_out:
        raise BillsError(str(source.path), [item.problem for item in read.left_out])
    return list(read.bills)


def add_source(paths: MachinePaths, format: str, path: Path) -> tuple[Settings, int]:
    """Lists the bill file at ``path``, in ``format`` (one of ``settings.SOURCE_FORMATS``), as a further source once
    it reads whole — the one moment the user is there to put it right; the settings written and how many bills the
    file holds. A source already listed under another spelling of the path is listed once. Once listed, a source is
    read bill by bill (``load_bills``).

    SettingsError when the settings cannot be read; ValueError for another format, or for WindowTally's own bills file,
    which is read whenever it exists; BillsError when the file breaks its contract and OSError when it cannot be read —
    the settings then left as they were.
    """
    if format not in SOURCE_FORMATS:
        raise ValueError(f"the format {format!r} is not one of {', '.join(SOURCE_FORMATS)}")
    source = BillSource(format, Path(os.path.abspath(path.expanduser())))
    if same_file(source.path, paths.bills_file):
        raise ValueError(f"{source.path} is read whenever it exists.")
    count = len(read_source(source))
    with editing(paths.settings_file):
        settings = load_settings(paths.settings_file)
        others = tuple(s for s in settings.bill_sources if not same_file(s.path, source.path))
        settings = replace(settings, bill_sources=others + (source,))
        save_settings(paths.settings_file, settings)
    return settings, count


def check_refund_pairing(paths: MachinePaths, bill: Bill, replacing: Bill | None = None) -> None:
    """Refuses (BillsError) a bill a writer is about to record where it and its refund would contradict each other, as
    every source gives them now: a refund must credit a bill read, and agree with it; a bill must agree with the refund
    that credits it. A bill and a refund left out for contradicting each other count here, so that either can be put
    right; ``replacing``, the entry being replaced, is not set against its replacement."""
    if not bill.reference:
        return
    bill_set = load_bills(paths)
    others = [b for b in bill_set.bills + bill_set.set_aside if replacing is None or b.origin != replacing.origin]
    if bill.kind == "refund":
        credited = next((b for b in others if b.key == (bill.account, bill.reference, False)), None)
        if credited is None:
            raise BillsError(str(paths.bills_file), [f"no bill of {bill.account} read now has the reference "
                                                     f"{bill.reference}, which a refund credits"])
        problem = _contradiction(credited, bill)
    else:
        refund = next((b for b in others if b.key == (bill.account, bill.reference, True)), None)
        problem = _contradiction(bill, refund) if refund is not None else None
    if problem:
        raise BillsError(str(paths.bills_file), [problem])


def remove_source(paths: MachinePaths, path: Path) -> Settings:
    """Stops reading the listed bill source at ``path``, however it is spelt — relative to the data folder, as the
    settings allow, or not; the settings written. SettingsError when the settings cannot be read; ValueError when no
    listed source is that file."""
    target = path.expanduser()
    with editing(paths.settings_file):
        settings = load_settings(paths.settings_file)
        kept = tuple(s for s in settings.bill_sources
                     if not (same_file(s.path, target) or same_file(s.path, paths.data_dir / target)))
        if len(kept) == len(settings.bill_sources):
            raise ValueError(f"{target} is not a listed bill source.")
        settings = replace(settings, bill_sources=kept)
        save_settings(paths.settings_file, settings)
    return settings


def _summary(problems: list[str]) -> str:
    shown = "; ".join(problems[:PROBLEMS_PER_LINE])
    more = len(problems) - PROBLEMS_PER_LINE
    return shown + (f"; and {more} more" if more > 0 else "")


def _without_duplicates(bills: list[Bill]) -> tuple[list[Bill], list[Duplicate]]:
    groups: dict[tuple[str, str | None, bool], list[Bill]] = defaultdict(list)
    for bill in bills:
        if bill.reference:
            groups[bill.key].append(bill)
    dropped: set[int] = set()
    duplicates = []
    for (account, reference, _), copies in groups.items():
        if len(copies) < 2:
            continue
        counted = all(copy.agrees_with(copies[0]) for copy in copies[1:])
        first = min(copies, key=lambda b: b.order)
        dropped.update(id(copy) for copy in copies if not counted or copy is not first)
        duplicates.append(Duplicate(account, reference, tuple(copy.origin for copy in copies), counted))
    return [b for b in bills if id(b) not in dropped], duplicates


def _contradiction(bill: Bill, refund: Bill) -> str | None:
    """Why ``refund`` cannot be a refund of ``bill``, or None."""
    if refund.currency != bill.currency:
        return f"{refund.origin} returns {refund.currency} on {bill.origin}, which was charged in {bill.currency}"
    if refund.amount > bill.amount:
        return f"{refund.origin} returns more than {bill.origin} charged"
    if refund.date < bill.date:
        return f"{refund.origin} is dated before {bill.origin}"
    if bill.end is not None and refund.date >= bill.end:
        return f"{refund.origin} is dated on or after the end of {bill.origin}'s period, which it cannot then end"
    return None


def _with_refunds_matched(bills: list[Bill]) -> tuple[list[Bill], list[LeftOut], list[Bill]]:
    """The bills with each refund matched to the bill it credits, why each refund was left out — one that matches no
    bill, and one that contradicts its bill, with the bill — and the bills so left out. ``bills`` hold at most one
    refund of a bill: two are copies of one document by its key, counted once or left out (``_without_duplicates``)."""
    credited = {b.key[:2]: b for b in bills if b.kind != "refund" and b.reference}
    dropped: set[int] = set()
    left_out = []
    for refund in (b for b in bills if b.kind == "refund"):
        account, reference = refund.key[:2]
        bill = credited.get((account, reference))
        if bill is None:
            problem = f"{refund.origin} credits the bill {reference} of {account}, which is not among the bills counted"
        else:
            problem = _contradiction(bill, refund)
        if problem is None:
            continue
        dropped.add(id(refund))
        if bill is not None:
            dropped.add(id(bill))
        left_out.append(LeftOut(account, problem, "it is left out" if bill is None
                                else "the bill is left out with its refund"))
    return [b for b in bills if id(b) not in dropped], left_out, [b for b in bills if id(b) in dropped]


def load_bills(paths: MachinePaths) -> BillSet:
    """Every bill of every source: WindowTally's own bills file when it exists, then each source the settings list.

    A source's problems never raise; they are in the result, so one broken source leaves the others' figures. What was
    not read marks the accounts it may concern (``Unread``): every account for a source refused, a listed source that
    does not exist, or settings that cannot say which sources there are; the account of each bill left out — every
    account where none of its rows names one — whether a source left it out, its copies differ, or its refund
    could not be matched to it.
    """
    errors: list[str] = []
    everyone = False
    emails: set[str] = set()
    try:
        settings = load_settings(paths.settings_file)
    except SettingsError as exc:
        errors.append(f"settings: {exc}")
        settings = Settings()
        everyone = True
    listed = [s for s in settings.bill_sources if not same_file(s.path, paths.bills_file)]
    if len(listed) < len(settings.bill_sources):
        errors.append(f"settings: {paths.bills_file} is read whenever it exists; it needs no entry in billSources")
    sources = [BillSource("bills", paths.bills_file)] + listed
    reports: list[SourceReport] = []
    collected: list[Bill] = []
    for index, source in enumerate(sources):
        if not source.path.is_file():
            if index:
                problem = f"{source.path} does not exist"
                errors.append(f"bills: {problem}")
                reports.append(SourceReport(source.path, source.format, None, (problem,)))
                everyone = True
            else:
                reports.append(SourceReport(source.path, source.format, None))
            continue
        try:
            read = read_source_in_part(source)
        except BillsError as exc:
            errors.append(f"bills: {source.path} was not read: {_summary(exc.problems)}")
            reports.append(SourceReport(source.path, source.format, None, tuple(exc.problems)))
            everyone = True
            continue
        except OSError as exc:
            errors.append(f"bills: {source.path} cannot be read: {exc}")
            reports.append(SourceReport(source.path, source.format, None, (str(exc),)))
            everyone = True
            continue
        collected.extend(replace(bill, order=(index, bill.order[1])) for bill in read.bills)
        problems = [item.text for item in read.left_out]
        if problems:
            errors.append(f"bills: {source.path} was read in part, {len(problems)} left out: {_summary(problems)}")
        for item in read.left_out:
            if item.account is None:
                everyone = True
            else:
                emails.add(item.account)
        reports.append(SourceReport(source.path, source.format, len(read.bills), left_out=tuple(problems)))
    bills, duplicates = _without_duplicates(collected)
    if duplicates:
        counted = sum(1 for d in duplicates if d.counted)
        parts = [f"{counted} counted once" if counted else "",
                 f"{len(duplicates) - counted} left out, their copies differing" if counted < len(duplicates) else ""]
        many = len(duplicates) != 1
        errors.append(f"bills: {len(duplicates)} bill{'s are' if many else ' is'} read more than once: "
                      + ", ".join(p for p in parts if p))
        emails.update(d.account for d in duplicates if not d.counted)
    bills, unmatched, set_aside = _with_refunds_matched(bills)
    for item in unmatched:
        errors.append(f"bills: {item.text}")
        emails.add(item.account)
    return BillSet(bills=tuple(bills), sources=tuple(reports), duplicates=tuple(duplicates), settings=settings,
                   errors=tuple(errors), unread=Unread(everyone, frozenset(emails)), set_aside=tuple(set_aside))
