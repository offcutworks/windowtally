"""The command line: ``python -m windowtally <command>``, run from the folder that holds the package.

    run         the background service (what the logon task runs): a pass every minute, logging to the data folder
    once        one pass over every source, then each account's standing
    status      each account's standing as the service last wrote it, without reading any source
    dashboard   regenerate the history page now; --open shows it in the default browser
    bills       what the bills say about each subscription, read from every bill source now; with --list, every bill
    bills add       record a bill in WindowTally's own bills file
    bills source    read a further bill file as well (--manifest, --bills), or stop reading one (--remove)
    bills remind    tag an account on the band when its recorded period ends within --days days, or --off
    browser register    register the browser extension's host with Chrome, run by --python on this package's folder
    browser unregister  remove that registration

The three roots can be relocated (--claude-home, --desktop-data, --data-dir), which is how the tests run the
whole pass against a synthetic machine. ``bills source`` and ``bills remind`` write the settings file themselves, in
UTF-8, so a path in any script survives a console whose code page cannot spell it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import webbrowser
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .accounts import load_registry, named
from .billing import (BillingReport, Period, billing_report, describe_start, money_text, month_totals_text,
                      profile_words, usd_text)
from .bills import (KINDS, PLANS, Bill, BillsError, add_bill, add_source, check_refund_pairing, load_bills, make_bill,
                    parse_day, remove_source)
from .browser_host import register, unregister
from .paths import MachinePaths, default_paths
from .service import configure_logging, run_forever, run_pass
from .settings import REMINDER_DAYS_LIMITS, set_renewal_reminder
from .status_file import STATUS_VERSION, subscription_entry
from .timeutil import local_datetime, parse_iso


def _paths(args: argparse.Namespace) -> MachinePaths:
    defaults = default_paths()
    return MachinePaths(
        claude_home=Path(args.claude_home) if args.claude_home else defaults.claude_home,
        desktop_data=Path(args.desktop_data) if args.desktop_data else defaults.desktop_data,
        data_dir=Path(args.data_dir) if args.data_dir else defaults.data_dir,
    )


def _when(text: str | None) -> str:
    epoch = parse_iso(text)
    return local_datetime(epoch).strftime("%a %m-%d %H:%M") if epoch is not None else "—"


def _window_text(window: dict) -> str:
    """A window's figure and reset time. ``estimated`` marks the figure; the reset time is approximate only when it
    was inferred (``anchorExact`` false), or, in a file that does not say, whenever ``estimated`` is set."""
    mark = "≈" if window.get("estimated") else ""
    reset_mark = mark if "anchorExact" not in window else ("" if window["anchorExact"] else "≈")
    if window["state"] == "not_started":
        return "not started"
    if window["state"] == "no_limit":
        return "no limit on this account"
    if window["percent"] is None:
        return f"{window['state']}" + (f", resets {reset_mark}{_when(window['resetsAt'])}"
                                       if window.get("resetsAt") else "")
    text = f"{mark}{window['percent']:.0f}%"
    if window.get("resetsAt"):
        text += f", resets {reset_mark}{_when(window['resetsAt'])}"
    return text


def _plan_line(subscription: dict, month: bool = True) -> str:
    """The status file's subscription of one account, in one line; ``month`` closes it with this month's cost at list
    price, which ``status`` leaves to its totals line, as the window does."""
    state, until = subscription["state"], subscription.get("paidUntil")
    if state == "active":
        left = subscription.get("daysLeft")
        text = (f"{subscription.get('planName') or 'a recorded plan'}, paid until {until}"
                + (f" ({left} day{'' if left == 1 else 's'} left)" if left is not None else ""))
        if subscription.get("renewSoon"):
            text += ", renew soon"
    elif state == "ended":
        text = f"no recorded plan today; the last period ended {until}"
    elif state == "upcoming":
        text = f"the first recorded period starts {until}"
    elif state == "unread":
        # Its bills may not all have been read: nothing is said of a plan, an end or a cost.
        return "its bills could not all be read; see the source problems"
    else:
        text = "no bills recorded"
    return text + (f"; this month {usd_text(subscription['thisMonthListPrice'])} at list price" if month else "")


def _totals_line(document: dict) -> str | None:
    """This UTC month across the accounts, as the window's header says it; None where status.json knows neither
    figure."""
    month = document.get("thisMonth") or {}
    return month_totals_text(month.get("apiEquivalent"), month.get("plansAtListPrice"),
                             document.get("billsUnread") is True, month.get("inPlans"), month.get("withinOneWindow"))


def format_status(document: dict) -> str:
    lines = []
    # desktopRunning is written only as false: the desktop app is not running, and its account is the one it starts on.
    desktop = "desktop, not running" if document.get("desktopRunning") is False else "desktop"
    # Every account, a hidden one marked: the command line reads the whole status, where the other surfaces list none.
    for account in document["accounts"]:
        roles = [role for role, flag in ((desktop, account["isDesktop"]), ("CLI", account["isCli"]),
                                         ("hidden", account.get("hidden") is True)) if flag]
        lines.append(f"{account['label']}" + (f"  [{', '.join(roles)}]" if roles else ""))
        windows = [f"    5-hour : {_window_text(account['fiveHour'])}", f"    weekly : {_window_text(account['weekly'])}"]
        # An account with no 5-hour limit leads with its weekly window, the one limit it has.
        lines.extend(reversed(windows) if account["fiveHour"]["state"] == "no_limit" else windows)
        if account.get("subscription"):
            lines.append(f"    plan   : {_plan_line(account['subscription'], month=False)}")
        as_of = account["weekly"].get("asOf")
        if as_of:
            lines.append(f"    reading: {_when(as_of)}")
    if document.get("desktopRunning") is False and not any(a["isDesktop"] for a in document["accounts"]):
        lines.append("Desktop app: not running")
    totals = _totals_line(document)
    if totals:
        lines.append(totals)
    lines.append(f"Next: {document['recommended']['reason']}")
    if document.get("cliCondition"):
        lines.append(f"CLI: {document['cliCondition']}")
    for problem in document.get("sourceErrors", []):
        lines.append(f"Source problem: {problem}")
    lines.append(f"(as of {_when(document['generatedAt'])})")
    return "\n".join(lines)


# --- bills ----------------------------------------------------------------------------------------------------

def _bill_line(bill: Bill, period: Period | None) -> str:
    """One bill of the listing, its sum in its own currency; a refund, under the bill it credits, the sum it
    returned."""
    if bill.kind == "refund":
        return f"    {bill.date}  {'refund':<8} {money_text(bill.amount, bill.currency):>14} returned on the bill [{bill.reference}]"
    what = PLANS[bill.plan] if bill.plan else bill.kind
    span = f" {bill.start}..{bill.end}" if bill.start else ""
    how = f" — {describe_start(period)}" if period is not None else ""
    reference = f" [{bill.reference}]" if bill.reference else ""
    return f"    {bill.date}  {what:<8} {money_text(bill.amount, bill.currency):>14}{span}{how}{reference}"


def format_bills(report: BillingReport, listing: bool = False) -> str:
    """What every bill source says now, per account; with ``listing``, each account's bills too."""
    lines = []
    if not report.configured:
        lines.append("No bills are recorded. Record one with 'bills add', or read a bill archive's manifest with "
                     "'bills source --manifest PATH'.")
    for s in report.subscriptions:
        lines.append(f"{s.label}  ({s.email})")
        lines.append(f"    plan   : {_plan_line(subscription_entry(s))}")
        if s.profile_check not in ("matches", "unread"):   # an account not wholly read says so on its plan line
            lines.append(f"    profile: {profile_words(s.profile_check, s.profile_plan)}")
        if listing:
            starts = {id(p.bill): p for p in s.periods}
            # A refund stands under the bill it credits, which every refund read has (``bills.load_bills``).
            for bill in (b for b in s.bills if b.kind != "refund"):
                lines.append(_bill_line(bill, starts.get(id(bill))))
                refund = report.bill_set.refund_of(bill)
                if refund is not None:
                    lines.append(_bill_line(refund, None))
    for source in report.bill_set.sources:
        if source.bills is not None:
            lines.append(f"Source: {source.path} ({source.format}): {source.bills} bill"
                         + ("" if source.bills == 1 else "s")
                         + (f", {len(source.left_out)} left out" if source.left_out else ""))
            lines.extend(f"    {problem}" for problem in source.left_out)
        elif source.problems:
            lines.append(f"Source: {source.path} ({source.format}): not read")
            lines.extend(f"    {problem}" for problem in source.problems)
    days = report.reminder_days
    lines.append(f"Renewal reminder: within {days} day{'' if days == 1 else 's'} of a period's end" if days else
                 "Renewal reminder: off")
    lines.extend(f"Problem: {problem}" for problem in report.bill_set.errors + report.problems)
    return "\n".join(lines)


def _bills_now(paths: MachinePaths) -> BillingReport:
    registry, _ = load_registry(paths.accounts_dir)
    bill_set = load_bills(paths)
    return billing_report(bill_set, named(registry, bill_set.settings.names), registry, None, time.time())


def _amount_argument(text: str) -> Decimal:
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValueError(f"the amount {text!r} is not a number") from None


def _period_argument(text: str | None) -> tuple[date | None, date | None]:
    if not text:
        return None, None
    first, separator, last = text.partition("..")
    if not separator:
        raise ValueError(f"the period {text!r} is not START..END")
    return parse_day(first, "the period's start"), parse_day(last, "the period's end")


def _bills_add(args: argparse.Namespace, paths: MachinePaths) -> int:
    try:
        start, end = _period_argument(args.period)
        bill = make_bill(account=args.account, day=parse_day(args.date, "the date"), kind=args.kind,
                         plan=args.plan, amount=_amount_argument(args.amount), currency=args.currency,
                         start=start, end=end, reference=args.reference, origin="the command line", position=0)
        check_refund_pairing(paths, bill)
        add_bill(paths.bills_file, bill, note=args.note)
    except (ValueError, OSError) as exc:  # BillsError is a ValueError
        print(f"Not recorded: {exc}", file=sys.stderr)
        return 2
    what = PLANS[bill.plan] if bill.plan else bill.kind
    period = f", {bill.start}..{bill.end}" if bill.start else ""
    credits = f" of the bill {bill.reference}" if bill.kind == "refund" else ""
    print(f"Recorded {bill.account}: {bill.date} {what}{credits} {money_text(bill.amount, bill.currency)}{period} "
          f"in {paths.bills_file}")
    return 0


def _bills_source(args: argparse.Namespace, paths: MachinePaths) -> int:
    try:
        if args.remove:
            settings = remove_source(paths, Path(args.remove))
        else:
            settings, count = add_source(paths, "manifest" if args.manifest else "bills",
                                         Path(args.manifest or args.bills))
            print(f"{settings.bill_sources[-1].path} holds {count} bill{'' if count == 1 else 's'}.")
    except BillsError as exc:
        print(f"Not added: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:  # SettingsError is a ValueError
        print(f"Not changed: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Not {'changed' if args.remove else 'added'}: {exc}", file=sys.stderr)
        return 2
    for listed in settings.bill_sources:
        print(f"Bill source: {listed.path} ({listed.format})")
    if not settings.bill_sources:
        print("No bill source is listed; WindowTally's own bills file is read whenever it exists.")
    return 0


def _bills_remind(args: argparse.Namespace, paths: MachinePaths) -> int:
    low, high = REMINDER_DAYS_LIMITS
    if not args.off and not low <= args.days <= high:
        print(f"Not changed: --days takes a whole number of days from {low} to {high}.", file=sys.stderr)
        return 2
    try:
        set_renewal_reminder(paths.settings_file, None if args.off else args.days)
    except (ValueError, OSError) as exc:  # SettingsError is a ValueError
        print(f"Not changed: {exc}", file=sys.stderr)
        return 2
    print("The renewal reminder is off." if args.off else
          f"The band tags an account whose recorded period ends within {args.days} day{'' if args.days == 1 else 's'}.")
    return 0


def _bills(args: argparse.Namespace, paths: MachinePaths) -> int:
    if args.action == "add":
        return _bills_add(args, paths)
    if args.action == "source":
        return _bills_source(args, paths)
    if args.action == "remind":
        return _bills_remind(args, paths)
    report = _bills_now(paths)
    print(format_bills(report, listing=args.list))
    return 1 if report.bill_set.errors or report.problems else 0


def _bills_parser(commands: argparse._SubParsersAction) -> None:
    bills = commands.add_parser("bills", help="what the bills say about each subscription")
    bills.add_argument("--list", action="store_true", help="list every bill too")
    actions = bills.add_subparsers(dest="action")
    add = actions.add_parser("add", help="record a bill in WindowTally's own bills file")
    add.add_argument("--account", required=True, help="the e-mail the bill is addressed to")
    add.add_argument("--date", required=True, help="the charge date, YYYY-MM-DD")
    add.add_argument("--kind", choices=KINDS, default="subscription")
    add.add_argument("--plan", choices=list(PLANS), help="a subscription's plan")
    add.add_argument("--amount", required=True, help="what was charged, tax included; for a refund, the sum returned")
    add.add_argument("--currency", required=True, help="the ISO 4217 code of the currency the bill was charged in")
    add.add_argument("--period", help="the service period START..END, END being the day the next would start")
    add.add_argument("--reference", help="the invoice number; for a refund, that of the bill it credits")
    add.add_argument("--note")
    source = actions.add_parser("source", help="read a further bill file, or stop reading one")
    which = source.add_mutually_exclusive_group(required=True)
    which.add_argument("--manifest", metavar="PATH", help="a bill archive's manifest")
    which.add_argument("--bills", metavar="PATH", help="a file in WindowTally's own bills format")
    which.add_argument("--remove", metavar="PATH", help="stop reading this source")
    remind = actions.add_parser("remind", help="tag an account on the band when its recorded period ends soon")
    when = remind.add_mutually_exclusive_group(required=True)
    when.add_argument("--days", type=int, help="how many days before the end")
    when.add_argument("--off", action="store_true")


def _browser(args: argparse.Namespace, paths: MachinePaths) -> int:
    if args.action == "register":
        python = Path(args.python)
        if not python.is_file():
            print(f"No interpreter at {python}.", file=sys.stderr)
            return 1
        manifest = register(paths, python, Path(__file__).resolve().parent.parent)
        print(f"Registered the browser extension's host with Chrome: {manifest}")
        return 0
    unregister(paths)
    print("Removed the browser extension's host from Chrome's registry and the data folder.")
    return 0


def _browser_parser(commands: argparse._SubParsersAction) -> None:
    browser = commands.add_parser("browser", help="the browser extension's host, as Chrome finds it")
    actions = browser.add_subparsers(dest="action", required=True)
    add = actions.add_parser("register", help="register the host with Chrome")
    add.add_argument("--python", required=True, help="the console interpreter (python.exe) the host runs under")
    actions.add_parser("unregister", help="remove the host's registration")


def _tolerant_streams() -> None:
    """A redirected stream takes the console's code page, which may not spell every character a command prints — ≈,
    a bill's note, an account's name in another script: such a character is printed as '?' rather than ending the
    command with an encoding error."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    _tolerant_streams()
    parser = argparse.ArgumentParser(prog="windowtally", description="Ledger and live standing of Claude accounts.")
    parser.add_argument("--claude-home", help="Claude Code's folder (default ~/.claude)")
    parser.add_argument("--desktop-data", help="the desktop app's data folder (default %%APPDATA%%/Claude)")
    parser.add_argument("--data-dir", help="WindowTally's data folder (default ~/.claude/windowtally)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="run the background service")
    commands.add_parser("once", help="one pass over every source, then the standings")
    commands.add_parser("status", help="the standings the service last wrote")
    page = commands.add_parser("dashboard", help="regenerate the history page")
    page.add_argument("--open", action="store_true", help="open the page in the default browser")
    _bills_parser(commands)
    _browser_parser(commands)
    args = parser.parse_args(argv)
    paths = _paths(args)

    if args.command == "run":
        configure_logging(paths, to_file=True)
        return run_forever(paths)
    configure_logging(paths, to_file=False)
    if args.command == "bills":
        return _bills(args, paths)
    if args.command == "browser":
        return _browser(args, paths)
    if args.command == "status":
        try:
            document = json.loads(paths.status_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"No status yet at {paths.status_file}; run 'once' or start the service.", file=sys.stderr)
            return 1
        if not isinstance(document, dict) or document.get("v") != STATUS_VERSION:
            version = document.get("v") if isinstance(document, dict) else None
            print(f"The status at {paths.status_file} is version {version!r}; this version of WindowTally reads version "
                  f"{STATUS_VERSION}, so the service that wrote it runs another version of WindowTally.", file=sys.stderr)
            return 1
        age = time.time() - (parse_iso(document.get("generatedAt")) or 0)
        print(format_status(document))
        if age > 300:
            print(f"Warning: this status is {age / 60:.0f} minutes old; the service may not be running.",
                  file=sys.stderr)
        return 0
    report = run_pass(paths, dashboard=True if args.command == "dashboard" else None)
    if args.command == "once":
        print(format_status(report.status))
        print(f"({report.transcripts.responses} responses, {report.new_observations} observations and "
              f"{report.new_events} account events read in {report.duration:.1f} s)")
    else:
        print(paths.dashboard_file)
        if args.open:
            webbrowser.open(paths.dashboard_file.as_uri())
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
