"""status.json as the window reads it: version 3 of the contract whose canonical statement is
``windowtally/status_file.py`` — the file, and the version, the desktop plugin reads (``plugin/hooks/status.ts``).

The file is read again only when its modification time changes, whatever it held: on Windows the service's atomic
replace of the file waits while a reader holds it (``windowtally.files`` retries the replace), so the window holds
it once after each change and no more (the plugin reads the same way). Only a read that failed — the file held or
vanishing as it was opened — is tried again at the next look. A file of another version is reported as such and
never guessed at; one that is not the version-3 shape is reported with what is wrong, so a stale figure is never
shown as a fresh one. Every sum of money in it is in US dollars. The contract's optional keys (``desktopSignedIn``,
``desktopRunning``, ``syncFollows``, ``oneClickDesktop``, ``workingSessions`` and an account's ``desktopArchived`` and
``hidden``) are read as it says of a key that is absent: the desktop app is not at its sign-in page, it runs or whether
it runs is not known, the CLI follows, one-click switching is unavailable, no session works, no desktop login is
stored, the account is listed. The weekly window's ``byProduct`` and ``scoped`` are read the same way, and more
leniently than the rest: each is an addition no other figure rests on, so one that is not in its shape is read as
absent, never as a fault of the document, and the window shows the account as it would without it.

``Status.accounts`` holds every account the file names, so that one named by its UUID — the desktop app's, the CLI's,
the recommended one — is always found; ``Status.listed`` leaves out those the file marks hidden, and is what every
list of the window shows, but for *Arrange accounts…*, where a hidden account is shown again.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from windowtally.status_file import STATUS_VERSION
from windowtally.timeutil import parse_iso


@dataclass(frozen=True)
class Window:
    """One plan window as status.json gives it; times are epoch seconds."""

    kind: str                       # five_hour | seven_day
    state: str                      # running | not_started | no_limit | current | unknown
    percent: float | None
    resets_at: float | None
    as_of: float | None
    estimated: bool                 # the figure, or the reset time with it, was inferred rather than read
    exhausts_at: float | None
    anchor_exact: bool | None       # the reset time was read rather than inferred; None where the file does not say
    by_product: ByProduct | None = None   # the weekly window's use by product, where the file gives it
    scoped: tuple[Scoped, ...] = ()       # the weekly window's per-model windows, where the file gives them


@dataclass(frozen=True)
class Scoped:
    """A per-model window as status.json gives it on the weekly window: a model's own allowance inside the week, as
    Fable's is, read from claude.ai; times are epoch seconds."""

    name: str
    state: str                      # current | unknown
    percent: float | None           # of the model's own allowance; None while unknown
    resets_at: float | None
    as_of: float | None             # the claude.ai reading it rests on
    estimated: bool
    allowance: float | None         # the allowance as a percentage of the weekly window; None where unsaid


@dataclass(frozen=True)
class ByProduct:
    """The weekly window's use by product as status.json gives it: when claude.ai computed it, and each product's
    name and whole-percent share of the window's use, in claude.ai's order."""

    as_of: float
    shares: tuple[tuple[str, float], ...]   # (name, percent)


@dataclass(frozen=True)
class Subscription:
    state: str                      # active | ended | upcoming | none | unread (its bills not all read: nothing stated)
    plan: str | None
    plan_name: str | None
    paid_until: str | None          # YYYY-MM-DD
    days_left: int | None
    renew_soon: bool
    this_month: float | None        # the plans' cost at list price in today's UTC month; None while unread
    profile_plan: str | None
    profile_check: str


@dataclass(frozen=True)
class Account:
    uuid: str
    email: str | None
    label: str
    is_desktop: bool
    is_cli: bool
    last_activity: float | None
    five_hour: Window
    weekly: Window
    subscription: Subscription | None
    desktop_archived: bool = False  # the account sync has stored this account's desktop login
    hidden: bool = False            # the user hid it and neither client uses it: no list of the window shows it


@dataclass(frozen=True)
class Status:
    generated_at: float | None
    desktop_account: str | None
    cli_account: str | None
    cli_condition: str | None
    source_errors: tuple[str, ...]
    recommended_account: str | None
    recommended_reason: str
    relief_at: float | None
    relief_exact: bool              # relief_at was read rather than inferred; False where the file does not say
    renewal_reminder_days: int | None
    month_api: float | None         # this UTC month's API-equivalent use across the accounts
    month_plans: float | None       # this UTC month's plans' cost at list price across the accounts; None without bills
                                    # or while some bill may not have been read
    accounts: tuple[Account, ...]
    # The optional keys of the contract, each read as the contract says of a key that is absent.
    bills_unread: bool = False      # some bill may not have been read, so month_plans is not known
    desktop_signed_in: bool = True  # False: the desktop app is at its sign-in page, and so no account's
    desktop_running: bool = True    # False: the desktop app is not running; True: it runs, or that is not known
    sync_follows: bool = True       # the CLI follows the desktop app's account
    one_click_desktop: bool = False  # one-click switching of the desktop app is on
    working_sessions: int = 0       # desktop-hosted Code sessions with a turn in progress
    month_in_plans: float | None = None    # of month_api, what the plans covered; None: all of it, or not known
    month_one_window: float | None = None  # of that, the use within one window a week; None: all of it, or not known

    def account(self, uuid: str | None) -> Account | None:
        return next((a for a in self.accounts if a.uuid == uuid), None)

    @property
    def listed(self) -> tuple[Account, ...]:
        """The accounts the window's lists show, in the file's order: every one the file does not mark hidden."""
        return tuple(a for a in self.accounts if not a.hidden)


@dataclass(frozen=True)
class Snapshot:
    """What reading status.json found: ``ok`` with the status, or why there is none."""

    kind: str                       # ok | missing | unreadable | unknown-version
    path: Path
    status: Status | None = None
    problem: str | None = None      # unreadable: what is wrong; unknown-version: the version found, as JSON


class StatusShapeError(ValueError):
    """status.json is version 3 by its number but not by its shape."""


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _window(kind: str, value: object) -> Window:
    if not isinstance(value, dict) or not isinstance(value.get("state"), str):
        raise StatusShapeError(f"an account's {kind} window is not in the version-3 shape")
    exact = value.get("anchorExact")
    return Window(kind=kind, state=value["state"], percent=_number(value.get("percent")),
                  resets_at=parse_iso(value.get("resetsAt")), as_of=parse_iso(value.get("asOf")),
                  estimated=value.get("estimated") is True, exhausts_at=parse_iso(value.get("exhaustsAt")),
                  anchor_exact=exact if isinstance(exact, bool) else None,
                  by_product=_by_product(value.get("byProduct")), scoped=_scoped(value.get("scoped")))


def _scoped(value: object) -> tuple[Scoped, ...]:
    """The per-model windows, or none where they are absent or not in their shape: read as the plugin reads them
    (``plugin/hooks/status.ts``, scopedOf), so the window and the band never disagree on one."""
    if not isinstance(value, list):
        return ()
    rows = []
    for row in value:
        if not isinstance(row, dict) or _text(row.get("name")) is None or _text(row.get("state")) is None:
            return ()
        rows.append(Scoped(name=row["name"], state=row["state"], percent=_number(row.get("percent")),
                           resets_at=parse_iso(row.get("resetsAt")), as_of=parse_iso(row.get("asOf")),
                           estimated=row.get("estimated") is True, allowance=_number(row.get("allowanceOfWeekly"))))
    return tuple(rows)


def _by_product(value: object) -> ByProduct | None:
    """The use by product, or None where it is absent or not in its shape."""
    as_of = parse_iso(value.get("asOf")) if isinstance(value, dict) else None
    rows = value.get("rows") if isinstance(value, dict) else None
    if as_of is None or not isinstance(rows, list):
        return None
    shares = []
    for row in rows:
        # A row is read as the plugin reads it (plugin/hooks/status.ts, byProductOf): its key, name and share, or
        # the whole report is absent, so the window and the panel never disagree on one.
        if not isinstance(row, dict) or _text(row.get("key")) is None:
            return None
        name, percent = _text(row.get("name")), _number(row.get("percent"))
        if name is None or percent is None:
            return None
        shares.append((name, percent))
    return ByProduct(as_of, tuple(shares))


def _subscription(value: object) -> Subscription | None:
    if value is None:
        return None
    this_month = _number(value.get("thisMonthListPrice")) if isinstance(value, dict) else None
    # The month's sum is null only on an account whose bills were not all read.
    if not isinstance(value, dict) or not isinstance(value.get("state"), str) or (
            this_month is None and not (value["state"] == "unread" and value.get("thisMonthListPrice") is None)):
        raise StatusShapeError("an account's subscription is not in the version-3 shape")
    days_left = _number(value.get("daysLeft"))
    return Subscription(state=value["state"], plan=_text(value.get("plan")), plan_name=_text(value.get("planName")),
                        paid_until=_text(value.get("paidUntil")),
                        days_left=int(days_left) if days_left is not None else None,
                        renew_soon=value.get("renewSoon") is True, this_month=this_month,
                        profile_plan=_text(value.get("profilePlan")),
                        profile_check=_text(value.get("profileCheck")) or "")


def _account(value: object) -> Account:
    if not isinstance(value, dict) or not isinstance(value.get("uuid"), str) or not value["uuid"]:
        raise StatusShapeError("one of its accounts is not in the version-3 shape")
    uuid = value["uuid"]
    return Account(uuid=uuid, email=_text(value.get("email")),
                   label=_text(value.get("label")) or _text(value.get("email")) or uuid[:8],
                   is_desktop=value.get("isDesktop") is True, is_cli=value.get("isCli") is True,
                   last_activity=parse_iso(value.get("lastActivity")),
                   five_hour=_window("five_hour", value.get("fiveHour")),
                   weekly=_window("seven_day", value.get("weekly")),
                   subscription=_subscription(value.get("subscription")),
                   desktop_archived=value.get("desktopArchived") is True, hidden=value.get("hidden") is True)


def parse_status(data: dict) -> Status:
    """A version-3 document as a Status; StatusShapeError naming what is not the version-3 shape."""
    if not isinstance(data.get("accounts"), list):
        raise StatusShapeError("it has no accounts list")
    month = data.get("thisMonth")
    if not isinstance(month, dict) or any(month.get(key) is not None and _number(month.get(key)) is None
                                          for key in ("apiEquivalent", "plansAtListPrice")):
        raise StatusShapeError("this month's totals are not in the version-3 shape")
    recommended = data.get("recommended") if isinstance(data.get("recommended"), dict) else {}
    days = _number(data.get("renewalReminderDays"))
    errors = data.get("sourceErrors")
    sessions = _number(data.get("workingSessions"))
    return Status(
        generated_at=parse_iso(data.get("generatedAt")),
        desktop_account=_text(data.get("desktopAccount")), cli_account=_text(data.get("cliAccount")),
        cli_condition=_text(data.get("cliCondition")),
        source_errors=tuple(str(e) for e in errors) if isinstance(errors, list) else (),
        recommended_account=_text(recommended.get("account")), recommended_reason=_text(recommended.get("reason")) or "",
        relief_at=parse_iso(recommended.get("reliefAt")),
        relief_exact=recommended.get("reliefExact") is True,
        renewal_reminder_days=int(days) if days is not None else None,
        month_api=_number(month.get("apiEquivalent")), month_plans=_number(month.get("plansAtListPrice")),
        accounts=tuple(_account(a) for a in data["accounts"]),
        bills_unread=data.get("billsUnread") is True,
        desktop_signed_in=data.get("desktopSignedIn") is not False,
        desktop_running=data.get("desktopRunning") is not False,
        sync_follows=data.get("syncFollows") is not False, one_click_desktop=data.get("oneClickDesktop") is True,
        working_sessions=int(sessions) if sessions is not None and sessions > 0 else 0,
        month_in_plans=_number(month.get("inPlans")), month_one_window=_number(month.get("withinOneWindow")))


def snapshot_of(path: Path, text: str) -> Snapshot:
    """The snapshot of a status file at ``path`` holding ``text``."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        return Snapshot("unreadable", path, problem=f"it is not JSON ({exc})")
    if not isinstance(data, dict):
        return Snapshot("unreadable", path, problem="it is not a JSON object")
    if data.get("v") != STATUS_VERSION:
        return Snapshot("unknown-version", path, problem=json.dumps(data.get("v")))
    try:
        return Snapshot("ok", path, status=parse_status(data))
    except StatusShapeError as exc:
        return Snapshot("unreadable", path, problem=str(exc))


class StatusReader:
    """Reads status.json once after each change of its modification time."""

    def __init__(self, path: Path):
        self.path = path
        self.snapshot: Snapshot | None = None
        self._seen: tuple[str, int | None] | None = None

    def poll(self) -> Snapshot | None:
        """The snapshot when the file changed since the last poll — appeared, went, or was replaced — else None."""
        try:
            mtime = os.stat(self.path).st_mtime_ns
        except FileNotFoundError:
            seen, read = ("missing", None), lambda: (Snapshot("missing", self.path), True)
        except OSError as exc:
            seen, read = ("unstatable", None), lambda: (Snapshot("unreadable", self.path, problem=str(exc)), True)
        else:
            seen, read = ("file", mtime), self._read
        if seen == self._seen and self.snapshot is not None:
            return None
        snapshot, settled = read()
        self._seen = seen if settled else None
        self.snapshot = snapshot
        return snapshot

    def _read(self) -> tuple[Snapshot, bool]:
        """The snapshot, and whether the file was read whole: a failed read is not remembered as seen."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return Snapshot("missing", self.path), False
        except UnicodeDecodeError as exc:
            return Snapshot("unreadable", self.path, problem=str(exc)), True
        except OSError as exc:
            return Snapshot("unreadable", self.path, problem=str(exc)), False
        return snapshot_of(self.path, text), True
