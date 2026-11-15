"""``status.json`` — every account's live standing, the contract the desktop plugin and the window read.

Contract (version 3). Times are UTC ISO 8601 strings or null; percentages are numbers or null; days are UTC days,
YYYY-MM-DD; sums of money are numbers of US dollars rounded to the cent.

    {"v": 3, "generatedAt": "...",
     "desktopAccount": "<uuid>|null", "desktopSignedIn": false, "desktopRunning": false,
     "cliAccount": "<uuid>|null", "cliCondition": "<text>|null",
     "sourceErrors": ["<source>: <problem>", ...],
     "recommended": {"account": "<uuid>|null", "reason": "<text>", "reliefAt": "...|null", "reliefExact": false},
     "renewalReminderDays": 3|null, "notificationsSilenced": false,
     "syncFollows": false, "oneClickDesktop": true, "workingSessions": 2, "billsUnread": true,
     "thisMonth": {"apiEquivalent": 1283.56|null, "plansAtListPrice": 300.0|null, "inPlans": 1199.10,
                   "withinOneWindow": 1080.42},
     "accounts": [
       {"uuid": "...", "email": "...", "label": "...", "isDesktop": true, "isCli": true,
        "lastActivity": "...|null", "desktopArchived": true, "hidden": true,
        "fiveHour": {"state": "running|not_started|no_limit|unknown", "percent": 26, "resetsAt": "...",
                     "asOf": "...", "estimated": false, "exhaustsAt": "...|null", "anchorExact": true},
        "weekly":   {"state": "current|unknown", "percent": 60, "resetsAt": "...", "asOf": "...",
                     "estimated": false, "exhaustsAt": "...|null", "anchorExact": true,
                     "byProduct": {"asOf": "...", "rows": [{"key": "claude_code", "name": "Claude Code", "percent": 99},
                                                           {"key": "chat", "name": "Chats", "percent": 1}]},
                     "scoped": [{"name": "Fable", "state": "current|unknown", "percent": 21, "resetsAt": "...",
                                 "asOf": "...", "estimated": true, "allowanceOfWeekly": 50}]},
        "subscription": null | {
            "state": "active|ended|upcoming|none|unread", "plan": "pro|max5x|ultra|null", "planName": "Max 5x|null",
            "paidUntil": "2027-06-07|null", "daysLeft": 9|null, "renewSoon": false,
            "thisMonthListPrice": 80.65|null,
            "profilePlan": "ultra|null",
            "profileCheck": "matches|differs|profile-older|no-bill-today|unknown-plan|no-profile|unread"}}]}

``byProduct``, on the weekly window alone, is the week's use split by product as claude.ai last reported it through the
browser extension (``products``): ``asOf`` when claude.ai computed it, and its ``rows`` in claude.ai's order, each
product's key, the name its page shows and its whole-percent share of the window's use up to then. It is an optional
key added with no version bump, written only while the account's current report is of the weekly window in effect
(``products.current``), so absent means no report of this window; a reader that does not know it shows the window as
before, and no figure of the document rests on it.

``scoped``, on the weekly window alone, is the account's per-model weekly windows (``limits.scoped_standings``): a
model's own allowance inside the weekly window, as Fable's is, which only claude.ai reports, through the browser
extension. ``name`` is the model's name as claude.ai shows it; ``percent`` is of the model's own allowance, null while
``state`` is ``unknown`` — a reset since its reading whose effect on it is not known; ``resetsAt`` its reset, the weekly
window's; ``asOf`` the reading it rests on, from claude.ai's page, so possibly hours old; ``estimated`` that a rise from
the model's use since that reading was added — its part of the weekly window's rise, or its spend at its rate — or a
reset of its allowance inferred from the weekly window; and
``allowanceOfWeekly`` the allowance as a percentage of the weekly window, null where claude.ai did not say. It is an
optional key added with no version bump, written only for an account that has used the model, so absent means none to
show; the weekly window's ``exhaustsAt`` already allows for it, and no other figure rests on it.

``accounts`` stand in the order every surface lists them in (``shown_order``): the account the desktop app uses, then
the CLI's where it is another, then the rest in the user's order (``settings``, ``accountOrder``), those it does not
list after the listed ones by name, and the accounts whose ``subscription`` is ``ended`` after all the others, in that
same order among themselves; a reader keeps that order. ``label`` is the account's name as shown: the user's own
(``accountNames``), else the e-mail's local part; ``email`` is the e-mail whatever the name, and ``uuid`` names the
account in every action.

``fiveHour``'s state ``no_limit`` says the account has no 5-hour limit (``limits.five_hour_removed``): its percent,
resetsAt and exhaustsAt are null, its asOf the reading that says so, and the account is recommended and warned of by
its weekly window alone. The ``fiveHour`` object stays, so a reader that requires it keeps reading the whole document;
one that does not know the state shows the window as unknown.

``estimated`` marks a figure inferred rather than read (an inferred reset time, or a rise estimated from usage
since the last reading); it covers the figure and the reset time together. ``anchorExact`` says which of the two it
was for the reset time: true when ``resetsAt`` came from a plugin or browser reading, false when it was inferred or
there is none, so a reader marks a reset time approximate only where ``anchorExact`` is false. ``reliefAt``, set only while no
account is under the recommendation's ceilings, is the first reset that frees one — one of the accounts' reset times — and
``reliefExact`` says of it what ``anchorExact`` says of that reset time. With ``account`` null every account is blocked and
``reliefAt`` is when the first opens; with an account named, every account is at or near its limit, that one has the most
left, and ``reliefAt`` is when room returns. ``notificationsSilenced`` is the user's setting
(``settings``): while true no plugin raises a limit toast. ``cliCondition`` is what keeps
the CLI from following the desktop account, as the account sync reports it. ``sourceErrors`` names each source the
pass could not read, so a reader can tell a stale figure from a fresh one. The file is replaced atomically, so a
reader never sees a partial write.

``subscription`` is what the user's bills say (``billing``), null while no bill source exists. ``plan`` is the plan
in effect today. ``paidUntil`` is, while a recorded period covers today (``active``), the end of the periods running
on from today — the day the next would start — and ``daysLeft`` the whole days to it; once none covers today
(``ended``) it is the day the last one ended, and before the first begins (``upcoming``) the day it starts.
``renewSoon`` is set within ``renewalReminderDays`` of that end, the reminder the user turns on, null while off.
``thisMonthListPrice`` is the account's plans' cost at their US list price on the days of today's UTC month, the
whole month — what the plan time is worth, never what was paid (``billing``). ``profileCheck`` sets
``profilePlan``, the plan the account's profile names, against ``plan``: ``profile-older`` is a difference from a
profile fetched before today's period began, ``no-bill-today`` a profile naming a plan while no recorded period covers
today. A refund ends the plan of the bill it credits on its date, so an account whose last plan was refunded is
``ended`` from that day.

``unread`` says the account's bills may not all have been read — a bill source was refused, or a bill of the account
was left out, as ``sourceErrors`` names — so nothing is stated of its plan: ``plan``, ``planName``, ``paidUntil``,
``daysLeft`` and ``thisMonthListPrice`` are null, ``renewSoon`` false, and ``profileCheck`` is ``unread``, the profile
not compared; a reader says the account's bills could not all be read, never that it has none. The state and the
null sum were added with no version bump: a reader that requires a number there refuses the document whole rather
than state an absence.

``desktopSignedIn``, ``desktopRunning``, ``syncFollows``, ``oneClickDesktop``, ``workingSessions``, ``billsUnread``
and an account's ``desktopArchived`` and ``hidden`` are optional keys added with no version bump; a writer omits the
value a reader takes for a key it does not find. ``billsUnread`` is written only as true: some bill a source holds may
not have been read, so ``thisMonth.plansAtListPrice`` is null and not known, and absent means every bill was read.
``desktopSignedIn`` is written only as false: the desktop app is at its sign-in page, so
it is no account's — ``desktopAccount`` is null and no account ``isDesktop`` — and absent means the app is signed in,
to ``desktopAccount``, or its account is not known (``desktopAccount`` null). ``desktopRunning`` is written only as
false: none of the desktop app's processes runs, as the account sync's watcher saw it within the last two minutes, and
nothing the sync did since has started it; ``desktopAccount``, and the account ``isDesktop``, still name the account the app starts on, and
``desktopSignedIn`` whether it starts at its sign-in page. Absent means the app runs or whether it runs is not known.
``syncFollows`` is written only as false: the user turned off "CLI follows the app" in the account sync, and absent
means the CLI follows. ``oneClickDesktop`` is written only as true, the user's switch for one-click desktop switching
being on (it is on until turned off), and absent means unavailable. ``workingSessions`` is how many desktop-hosted
Claude Code sessions have a turn in progress, as Claude Code's own session registry says (``registry``), written only
above zero, and absent means none.
``desktopArchived`` is written only as true, on an account whose desktop login the account sync has stored, and
absent means no archive. ``hidden`` is written only as true, on an account the user hid (``settings``,
``hiddenAccounts``) that neither the desktop app nor the CLI uses: no surface lists it, while a reader still finds it
by its UUID, where the window's *Arrange accounts…* lists every account to show it again. Absent means the account is
listed — one the user hid included while a client uses it, so the account in use is never left out. A hidden account
is not recommended either way (``limits.recommend``).

``thisMonth`` is today's UTC month across the accounts, the month the bills' days are counted in: ``apiEquivalent`` the
API-equivalent cost of every response since the month began, the use with no known account included, null where the
writer read no ledger; ``plansAtListPrice`` every subscription's ``thisMonthListPrice`` summed with each bill counted
once — an e-mail two accounts share once, an e-mail no account here has included — null while no bill source exists,
and while ``billsUnread`` is set. ``inPlans`` is the part of ``apiEquivalent`` the plans covered: less the use paid at
extra usage, while a window stood exhausted or past a model's own allowance (``plan_use``); ``withinOneWindow`` the part
of ``inPlans`` within one full weekly window a week: less the use a reset outside the schedule made room for. Each is an
optional key added with no version bump, written only where it is less than the one before it, so absent means the
same sum; a reader sets the plans' cost against ``inPlans`` for the multiple with resets and against
``withinOneWindow`` for the one without.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Collection, Mapping, Sequence

from .accounts import arranged
from .billing import BillingReport, Subscription, cents
from .bills import PLANS
from .files import write_text_atomically
from .limits import AccountStanding, Recommendation, ScopedStanding, WindowStanding
from .products import Report
from .timeutil import to_iso

STATUS_VERSION = 3


def _percent(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _window(w: WindowStanding, by_product: Report | None = None, scoped: Sequence[ScopedStanding] = ()) -> dict:
    entry = {"state": w.state, "percent": _percent(w.percent), "resetsAt": to_iso(w.resets_at),
             "asOf": to_iso(w.as_of), "estimated": w.estimated, "exhaustsAt": to_iso(w.exhausts_at),
             "anchorExact": w.reset_exact}
    if by_product is not None:
        entry["byProduct"] = {"asOf": to_iso(by_product.as_of),
                              "rows": [{"key": s.key, "name": s.name, "percent": s.percent} for s in by_product.shares]}
    if scoped:
        entry["scoped"] = [{"name": s.name, "state": s.state, "percent": _percent(s.percent),
                            "resetsAt": to_iso(s.resets_at), "asOf": to_iso(s.as_of), "estimated": s.estimated,
                            "allowanceOfWeekly": s.allowance} for s in scoped]
    return entry


def subscription_entry(s: Subscription | None) -> dict | None:
    """An account's ``subscription`` object of the contract."""
    if s is None:
        return None
    return {
        "state": s.state, "plan": s.plan, "planName": PLANS.get(s.plan) if s.plan else None,
        "paidUntil": s.paid_until.isoformat() if s.paid_until else None, "daysLeft": s.days_left,
        "renewSoon": s.renew_soon,
        "thisMonthListPrice": None if s.this_month is None else float(cents(s.this_month)),
        "profilePlan": s.profile_plan, "profileCheck": s.profile_check,
    }


def shown_order(standings: list[AccountStanding], order: Sequence[str] = (),
                ended: Collection[str] = ()) -> list[AccountStanding]:
    """The standings in the order every surface lists the accounts: the desktop app's account, then the CLI's where it
    is another, then the rest in the user's ``order`` (``accounts.arranged``), those in ``ended`` — accounts whose plan
    has ended, by UUID — after the others in that same order. An account in use stands first whatever its plan."""
    desktop = [s for s in standings if s.is_desktop]
    cli = [s for s in standings if s.is_cli and not s.is_desktop]
    rest = [s for s in standings if not (s.is_desktop or s.is_cli)]
    live = [s for s in rest if s.account.uuid not in ended]
    over = [s for s in rest if s.account.uuid in ended]
    return desktop + cli + [s for group in (live, over)
                            for s in arranged(group, order, lambda s: s.account.uuid, lambda s: s.account.label)]


def status_document(standings: list[AccountStanding], recommendation: Recommendation, *, now: float,
                    desktop_account: str | None, cli_account: str | None, cli_condition: str | None,
                    source_errors: list[str] | None = None, billing: BillingReport | None = None,
                    notifications_silenced: bool = False, api_this_month: float | None = None,
                    sync_follows: bool = True, one_click_desktop: bool = False,
                    working_sessions: int = 0, desktop_archived: set[str] | None = None,
                    desktop_signed_out: bool = False, desktop_not_running: bool = False,
                    account_order: Sequence[str] = (), hidden: Collection[str] = (),
                    by_product: Mapping[str, Report] | None = None, in_plans_this_month: float | None = None,
                    one_window_this_month: float | None = None) -> dict:
    """``api_this_month`` is the API-equivalent cost of every response in today's UTC month, which the caller reads
    from the ledger, ``in_plans_this_month`` the part of it the plans covered and ``one_window_this_month`` the part of
    that within one window a week (``plan_use``), None where not computed. ``desktop_signed_out`` says the desktop app
    is at its sign-in page; the caller then gives no
    ``desktop_account`` and no standing marked as the desktop's. ``desktop_not_running`` says none of the desktop app's
    processes runs. ``account_order`` is the user's order of the
    accounts, which the document's accounts follow after the accounts in use, those whose plan has ended last
    (``shown_order``). ``hidden`` are the
    accounts the user hid, by UUID; those neither client uses are marked ``hidden``. ``by_product`` is each account's
    current report of the week's use by product, by UUID (``products.current_reports``)."""
    subscriptions = {s.account.uuid: billing.for_account(s.account.uuid) if billing and billing.configured else None
                     for s in standings}
    # The month's cost across the accounts is not known exactly when some bill may not have been read.
    unread = bool(billing and billing.configured and billing.this_month is None)
    ended = {uuid for uuid, subscription in subscriptions.items()
             if subscription is not None and subscription.state == "ended"}
    accounts = []
    for s in shown_order(standings, account_order, ended):
        subscription = subscriptions[s.account.uuid]
        entry: dict = {
            "uuid": s.account.uuid, "email": s.account.email, "label": s.account.label,
            "isDesktop": s.is_desktop, "isCli": s.is_cli, "lastActivity": to_iso(s.last_activity),
            "fiveHour": _window(s.five_hour),
            "weekly": _window(s.weekly, (by_product or {}).get(s.account.uuid), s.scoped),
            "subscription": subscription_entry(subscription),
        }
        if desktop_archived and s.account.uuid in desktop_archived:
            entry["desktopArchived"] = True
        if s.account.uuid in hidden and not (s.is_desktop or s.is_cli):
            entry["hidden"] = True
        accounts.append(entry)
    document: dict = {
        "v": STATUS_VERSION,
        "generatedAt": to_iso(now),
        "desktopAccount": desktop_account,
        "cliAccount": cli_account,
        "cliCondition": cli_condition,
        "sourceErrors": list(source_errors or []),
        "recommended": {"account": recommendation.account_uuid, "reason": recommendation.reason,
                        "reliefAt": to_iso(recommendation.relief_at), "reliefExact": recommendation.relief_exact},
        "renewalReminderDays": billing.reminder_days if billing else None,
        "notificationsSilenced": notifications_silenced,
        "thisMonth": {
            "apiEquivalent": None if api_this_month is None else float(cents(api_this_month)),
            "plansAtListPrice": float(cents(billing.this_month)) if billing and billing.configured and not unread
                                else None},
        "accounts": accounts,
    }
    month = document["thisMonth"]
    if month["apiEquivalent"] is not None:
        covered = month["apiEquivalent"]
        for key, value in (("inPlans", in_plans_this_month), ("withinOneWindow", one_window_this_month)):
            if value is not None and float(cents(value)) < covered:
                month[key] = covered = float(cents(value))
    if unread:
        document["billsUnread"] = True
    if desktop_signed_out:
        document["desktopSignedIn"] = False
    if desktop_not_running:
        document["desktopRunning"] = False
    if not sync_follows:
        document["syncFollows"] = False
    if one_click_desktop:
        document["oneClickDesktop"] = True
    if working_sessions > 0:
        document["workingSessions"] = working_sessions
    return document


def write_status(path: Path, document: dict) -> None:
    write_text_atomically(path, json.dumps(document, ensure_ascii=False, indent=1))
