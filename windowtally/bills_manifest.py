"""A bill archive's manifest read as bills: a CSV index with one row per filed document, a paid bill filed as its
invoice and its receipt, and a refund of it as its credit note and the refund's own document, both under the bill's
invoice number.

The columns read, by their header names; any others are ignored:
    vendor          only "Anthropic Claude" rows are read
    account         the e-mail the bill is addressed to
    date            the charge date, YYYY-MM-DD; on a refund's rows, the day it was issued
    status          paid | voided; a voided document was never charged and is skipped. A refund's rows are paid: the
                    refund was issued
    doc_type        Invoice | Receipt | CreditNote | Refund; a paid bill counts once, from its invoice's row, and its
                    refund once, from its credit note's row, which repeats the bill's line item and printed period;
                    a receipt and a refund's own document are not read
    amount          what was charged, tax included, in currency; on a refund's rows the sum returned, unsigned
    currency        an ISO 4217 code
    line_item       the bill's line: "Claude Pro", "Max plan - 5x", "Max plan - 20x" or "Claude Ultra" (a plan's
                    period; the last two both read as Ultra whatever the bill's date, the invoices measured from
                    before the plan's renaming on 2026-10-31 printing its earlier name and those since its own),
                    "Prepaid extra usage" (a top-up) or
                    "Extra usage units" (a usage settlement)
    service_period  YYYY-MM-DD..YYYY-MM-DD, half-open like WindowTally's own periods; empty on a top-up
    invoice_no      the invoice number, which ties a receipt, a credit note and a refund to their invoice

A manifest that is not CSV, or lacks a column read, is refused whole (``bills.BillsError``). Within one, a row that
cannot be read — an unknown status or document type, a value that does not parse — leaves out the bill of its invoice
number, as does a paid bill with no invoice row or with two, two credit notes, a refund's own document without its
credit note, or a credit note that names another account, line item or period than its invoice; a paid row naming no
invoice belongs to no bill and is left out alone. Each is named (``bills.LeftOut``), and the manifest's other bills
count. Which refund credits which bill, and whether it contradicts it, is the matching every source shares
(``bills.load_bills``).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .bills import Bill, BillsError, LeftOut, SourceRead, make_bill, parse_day

VENDOR = "Anthropic Claude"
COLUMNS = ("vendor", "account", "date", "status", "doc_type", "amount", "currency", "line_item", "service_period",
           "invoice_no")
LINE_ITEMS = {
    "Claude Pro": ("subscription", "pro"),
    "Max plan - 5x": ("subscription", "max5x"),
    "Max plan - 20x": ("subscription", "ultra"),
    "Claude Ultra": ("subscription", "ultra"),
    "Prepaid extra usage": ("topup", None),
    "Extra usage units": ("usage", None),
}
STATUSES = ("paid", "voided")
DOC_TYPES = ("Invoice", "Receipt", "CreditNote", "Refund")


def _amount(row: dict[str, str]) -> Decimal:
    try:
        return Decimal(row["amount"])
    except InvalidOperation:
        raise ValueError(f"the amount {row['amount']!r} is not a number") from None


def _bill(row: dict[str, str], origin: str, position: int) -> Bill:
    line = row["line_item"]
    if line not in LINE_ITEMS:
        raise ValueError(f"unknown line item {line!r}")
    kind, plan = LINE_ITEMS[line]
    amount = _amount(row)
    start = end = None
    if row["service_period"]:
        first, separator, last = row["service_period"].partition("..")
        if not separator:
            raise ValueError(f"the service period {row['service_period']!r} is not START..END")
        start, end = parse_day(first, "the period's start"), parse_day(last, "the period's end")
    return make_bill(account=row["account"], day=parse_day(row["date"], "the date"), kind=kind, plan=plan,
                     amount=amount, currency=row["currency"], start=start, end=end, reference=row["invoice_no"],
                     origin=origin, position=position)


def _refund(row: dict[str, str], invoice: dict[str, str], origin: str, position: int) -> Bill:
    """A credit note's row as the refund of the bill its invoice row gives; ValueError where it names another account,
    line item or period than that invoice, or a value of it does not parse."""
    if row["account"].lower() != invoice["account"].lower():
        raise ValueError(f"the credit note is addressed to {row['account']!r}, its invoice to {invoice['account']!r}")
    for column, what in (("line_item", "line item"), ("service_period", "period")):
        if row[column] != invoice[column]:
            raise ValueError(f"the credit note's {what} {row[column]!r} is not its invoice's {invoice[column]!r}")
    return make_bill(account=row["account"], day=parse_day(row["date"], "the date"), kind="refund", plan=None,
                     amount=_amount(row), currency=row["currency"], start=None, end=None,
                     reference=row["invoice_no"], origin=origin, position=position)


def _email(rows: list[dict[str, str]]) -> str | None:
    """The account a bill's rows name: the first that is an e-mail address, lower-cased."""
    return next((row["account"].lower() for row in rows if "@" in row["account"]), None)


def read_manifest_source(path: Path) -> SourceRead:
    """The paid Claude bills a manifest lists and their refunds, in its row order, and each bill or row it holds and
    did not give; BillsError when the manifest is not CSV or lacks a column read."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            header = list(reader.fieldnames or [])
            rows = [{column: (row.get(column) or "").strip() for column in COLUMNS} for row in reader]
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise BillsError(str(path), [f"it cannot be read as CSV ({exc})"]) from None
    missing = [column for column in COLUMNS if column not in header]
    if missing:
        raise BillsError(str(path), [f"it has no column {', '.join(missing)}"])
    left_out: list[LeftOut] = []
    # Each invoice's paid rows, a row that cannot be read among them with its problem.
    by_invoice: dict[str, list[tuple[int, dict[str, str], str | None]]] = defaultdict(list)
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        if row["vendor"] != VENDOR:
            continue
        problem = None
        if row["status"] not in STATUSES:
            problem = f"row {number}: unknown status {row['status']!r}"
        elif row["status"] == "voided":
            continue
        elif row["doc_type"] not in DOC_TYPES:
            problem = f"row {number}: unknown document type {row['doc_type']!r}"
        if not row["invoice_no"]:
            reason = problem or f"row {number}: a paid bill without an invoice number"
            left_out.append(LeftOut(_email([row]), reason, "it belongs to no bill, so it is left out alone"))
            continue
        by_invoice[row["invoice_no"]].append((number, row, problem))
    bills = []
    for invoice, documents in by_invoice.items():
        problems = [problem for _, _, problem in documents if problem]
        # A row that cannot be read still stands for its document, so it is not also said to be missing.
        kinds = defaultdict(list)
        for number, row, _ in documents:
            kinds[row["doc_type"]].append((number, row))
        invoices, credits = kinds["Invoice"], kinds["CreditNote"]
        if len(invoices) != 1:
            problems.append(f"invoice {invoice}: {len(invoices)} invoice rows where a paid bill has one")
        if len(credits) > 1:
            problems.append(f"invoice {invoice}: {len(credits)} credit notes where a refund has one")
        if kinds["Refund"] and not credits:
            problems.append(f"invoice {invoice}: a refund's own document without its credit note")
        found: list[Bill] = []
        if not problems:
            number, row = invoices[0]
            try:
                found.append(_bill(row, f"{path.name} row {number}", number))
            except ValueError as exc:
                problems.append(f"row {number}: {exc}")
        if not problems and credits:
            number, credit = credits[0]
            try:
                found.append(_refund(credit, invoices[0][1], f"{path.name} row {number}", number))
            except ValueError as exc:
                problems.append(f"row {number}: {exc}")
        if problems:
            account = _email([row for _, row, _ in documents])
            left_out.append(LeftOut(account, "; ".join(problems), f"the bill {invoice} is left out"))
            continue
        bills.extend(found)
    return SourceRead(tuple(sorted(bills, key=lambda bill: bill.order)), tuple(left_out))


def read_manifest(path: Path) -> list[Bill]:
    """The paid Claude bills a manifest lists and their refunds, in its row order, read whole; BillsError when it breaks
    its shape, every problem named."""
    read = read_manifest_source(path)
    if read.left_out:
        raise BillsError(str(path), [item.problem for item in read.left_out])
    return list(read.bills)
