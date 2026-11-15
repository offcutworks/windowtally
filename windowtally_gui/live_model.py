"""What the window and the tray icon show, from one status snapshot at one moment: every surface's words, marks and
levels computed in one place, so the window, the tray's tooltip and its icon never disagree. The cards and the
tooltip's lines keep status.json's order, the one order every surface of WindowTally shows the accounts in, and leave
out the accounts it marks hidden (``Status.listed``), which the header's in-use line counts.

Marks follow WindowTally's rules: ≈ marks a figure inferred rather than read, and a reset time only where it was inferred
(``anchorExact`` false), since status.json's ``estimated`` covers the figure and the reset time together; the moment
the first account opens again, with every account at its limit, or room returns, with every account at or near it,
likewise only where it was inferred (``reliefExact`` false). A window's countdown written the band's way is marked only where no figure stands before it. A level is a
window's warning level (``windowtally.limits.warning_level``): 0, 1 for a warning, 2 for an error — the figures the
plugin warns at.

An account with no 5-hour limit (the window's state ``no_limit``) leads with its weekly window everywhere — the card's
first window, the tooltip's first figure, the tray icon's one ring — and says it has no 5-hour limit after it; its
level is its weekly window's alone.

A weekly reset is written by its weekday and time (``Sat 04:00``), the window being at most a week long, with its date
where it is more than six days away, so a reset a week off never reads as today's (``week_moment``); a 5-hour one by
the time left. The age of the reading a card's figures rest on is said only once the reading is old enough that its
figures may be out of date (``reading_dated``); it is then said once, after the last response, where both windows rest
on one reading — always for an account with no 5-hour limit, whose 5-hour window says only ``no limit`` — and on each
window's line otherwise. A plan's days left are said only while its renewal is near (``renewal_near``); its date always.

The header names which account each client uses only where the cards' chips cannot say it (``chips_say_clients``): the
desktop app not running or at its sign-in page, or an account in use that no card names. The sync's mode and the
hidden accounts' count are always said.

The weekly window's line ends, where status.json gives it, with the week's use by product as claude.ai last reported
it — ``by product 3h ago: Claude Code 89%, Chats 11%`` — the products with a share above zero, in claude.ai's order,
and the report's age, since a report is only as fresh as claude.ai's page last open in Chrome; a week of one product
alone says nothing the figure does not. It changes no figure, level or mark: a card without it reads as it always did.

Under the two windows a card shows each per-model window status.json gives the account — a model's own allowance
inside the week, Fable's, which the service gives only for an account that has used the model — by the model's name,
its gauge a thin bar rather than a ring (``scoped_row``). The tooltip and the tray icon leave it out: the tooltip's room is the
accounts', and the icon's two rings are the two windows that stop an account.

An account whose bills record a plan that has ended and none since (``plan_ended``), and that neither client uses
(``windows_left_out``), has no card: it stands on a line under the cards (``EndedRow``) saying when its plan ended and
when its week resets, the moment a renewal is planned around, and is left off the tooltip. It takes no readings, so its
figures are its last ones rolled forward through their resets to nothing, which would read as room left. One a client
uses keeps its card, its readings keeping its windows live. The service lists such accounts after the others. An
account whose bills could not all be read (the subscription's state ``unread``) keeps its card, whose plan line says so
and points to the source problems, never that it has no bills; and while any bill is unread the header says the
month's plans at list price are not known.

The tooltip names the accounts in use, then the recommendation, then the others: Windows shows 127 characters of it,
and a tooltip that runs over loses the other accounts' lines from its end, whole; what still runs over then is cut at
the limit, so the recommendation is never lost to the accounts after it.

The tray icon's rings each take their own window's level; while every account is at its limit, both take an error's.

A desktop app the status reports not running is said in the header (``Desktop app: <account> (not running)``), on a
line of its own with the button that starts it, and on the tooltip's first line, and the tray's menu offers the start;
the icon is unchanged and no notification is raised. Once the window has started the app it shows the app as starting
(``still_starting``) — none of those, and the progress row's word instead — until a status says the app runs, or one
written ``START_GRACE`` seconds or more after the start still says it does not: the watcher looks every 15 seconds and
the service writes the status each minute, so the status that follows a start says it only that late.
"""

from __future__ import annotations

from dataclasses import dataclass

from windowtally.accounts import default_label
from windowtally.billing import month_totals_text, profile_words
from windowtally import limits
from windowtally.limits import renewal_near, warning_level

from .formatting import ago, day_text, percent_text, plural, span, when
from .status_model import Account, ByProduct, Scoped, Snapshot, Status, Subscription, Window
from .switch_model import SwitchButton, Switches, mode_words, switch_buttons, switches_of

STALE_AFTER = 300.0   # a status this old means the service stopped writing (WindowTally's `status` command warns at it)
TOOLTIP_LIMIT = 127   # characters Windows shows of a tray icon's tooltip
PROFILE_NOTES = ("differs", "profile-older", "no-bill-today")
START_GRACE = 20.0    # seconds after a start by which the sync's watcher, looking every 15 s, has seen the app run
NOT_RUNNING = "The desktop app is not running."
FIVE_HOUR_NAME, WEEKLY_NAME = "5-hour", "Weekly"   # a window's name on a card


@dataclass(frozen=True)
class WindowRow:
    name: str            # 5-hour | Weekly
    figure: str          # 82%, ≈82%, not started, running, unknown, no limit
    level: int           # 0, 1, 2
    fraction: float      # how far its gauge — a ring, or a per-model window's bar — is filled, 0 to 1
    detail: str          # when it resets; empty for a 5-hour window with no limit
    note: str            # the pace, and the reading the figure rests on where the card does not say it once
    products: str = ""   # the weekly window's use by product and its age; empty where there is none
    metered: bool = True  # it has a ring; not a 5-hour window with no limit, where an empty one would read as 0 %


@dataclass(frozen=True)
class PlanRow:
    text: str
    tone: str            # normal | warning | muted
    note: str


@dataclass(frozen=True)
class Card:
    uuid: str
    label: str
    heading: str
    tags: tuple[str, ...]
    renew_tag: str | None
    five_hour: WindowRow
    weekly: WindowRow
    plan: PlanRow | None
    switches: tuple[SwitchButton, ...] = ()   # the buttons that switch the desktop app or the CLI to this account
    weekly_first: bool = False                # the account has no 5-hour limit, so its weekly window leads
    in_use: bool = False                      # the desktop app or the CLI uses the account
    scoped: tuple[WindowRow, ...] = ()        # the per-model windows (Fable's) under the two, each a bar, not a ring

    @property
    def windows(self) -> tuple[WindowRow, WindowRow]:
        """The two windows in the order the card shows them."""
        return (self.weekly, self.five_hour) if self.weekly_first else (self.five_hour, self.weekly)


@dataclass(frozen=True)
class EndedRow:
    """An account whose plan has ended and that neither client uses, on a line of its own under the cards."""

    uuid: str
    label: str
    text: str                                 # when the plan ended and when the week resets
    email: str = ""                           # the e-mail where the account's name is not taken from it
    switches: tuple[SwitchButton, ...] = ()


@dataclass(frozen=True)
class Header:
    status_line: str
    stale: bool
    in_use_line: str
    totals_line: str | None      # this month's totals across the accounts; None where status.json gives none
    cli_condition: str | None
    next_line: str
    all_blocked: bool
    not_running: bool = False    # the desktop app is not running: the line and the button that starts it are shown


@dataclass(frozen=True)
class LiveView:
    problem: str | None          # why there are no standings to show, in place of them
    header: Header | None
    cards: tuple[Card, ...]
    problems: tuple[str, ...]    # the sources the service could not read
    ended: tuple[EndedRow, ...] = ()   # the accounts whose plan has ended that no client uses, under the cards


@dataclass(frozen=True)
class TrayView:
    tooltip: str
    level: int                   # -1 while no fresh status gives the account in use; else its rings' higher level
    five_hour: float | None      # the account in use's rings, 0 to 1, None without a figure
    weekly: float | None
    account: str | None          # the account in use's UUID
    can_start: bool = False      # the desktop app is reported not running, so the tray's menu offers to start it
    weekly_only: bool = False    # the account in use has no 5-hour limit: the icon draws its weekly ring alone
    five_hour_level: int = 0     # each ring's level, 0 to 2; 2 for both while every account is at its limit
    weekly_level: int = 0


def is_stale(status: Status, now: float) -> bool:
    return status.generated_at is None or now - status.generated_at > STALE_AFTER


def still_starting(status: Status | None, started_at: float | None, now: float) -> bool:
    """Whether the desktop app the window started at ``started_at`` is still shown as starting: until a status says it
    runs, or a status written ``START_GRACE`` seconds or more after the start says it does not, the start having come
    to nothing; and, with no such status, for ``STALE_AFTER`` seconds at most."""
    if started_at is None or now - started_at > STALE_AFTER:
        return False
    if status is None:
        return True
    if status.desktop_running:
        return False
    return status.generated_at is None or status.generated_at < started_at + START_GRACE


def _not_running(status: Status, starting: bool) -> bool:
    return not status.desktop_running and not starting


def snapshot_problem(snapshot: Snapshot | None) -> str | None:
    """Why the snapshot gives no standings, in words; None when it does."""
    if snapshot is None:
        return "Reading WindowTally's status…"
    if snapshot.kind == "missing":
        return f"No status file yet at {snapshot.path}. Is the WindowTally service running?"
    if snapshot.kind == "unreadable":
        return f"The status file cannot be read: {snapshot.problem}."
    if snapshot.kind == "unknown-version":
        return (f"The status file is version {snapshot.problem}, which this window does not read: the service that "
                f"wrote it runs another version of WindowTally.")
    if not snapshot.status.accounts:
        return "No account is known yet."
    return None


def _label(status: Status, uuid: str | None) -> str:
    if uuid is None:
        return "unknown"
    account = status.account(uuid)
    return account.label if account else uuid[:8]


def _reset_mark(window: Window) -> str:
    if window.anchor_exact is not None:
        return "" if window.anchor_exact else "≈"
    return "≈" if window.estimated else ""


WEEK_DATED_AFTER = 6 * 86400   # a weekly reset further off than this carries its date: its weekday is today's


def week_moment(resets_at: float, now: float) -> str:
    """When a weekly window resets: ``Sat 04:00``, or ``Sat 14 Nov 04:00`` more than six days away."""
    return when(resets_at, resets_at - now > WEEK_DATED_AFTER)


def reading_text(window: Window, now: float) -> str:
    """The age of the reading a window's figure rests on: ``read 30m ago``."""
    return "no reading yet" if window.as_of is None else f"read {ago(now - window.as_of)}"


def reading_dated(window: Window, last_activity: float | None, now: float) -> bool:
    """Whether a window's reading is old enough that its figure may be out of date, so that its age is said: the
    bound the history page's cards keep too (``windowtally.limits.reading_dated``)."""
    return limits.reading_dated(window.as_of, last_activity, now)


def shared_reading(account: Account) -> bool:
    """Whether a card says its reading's age once: the rule the history page's cards keep too
    (``windowtally.limits.shared_reading``)."""
    return limits.shared_reading(account.five_hour.state, account.five_hour.as_of, account.weekly.as_of)


def window_row(window: Window, now: float, say_reading: bool = True) -> WindowRow:
    """A window's two lines; ``say_reading`` false where the card says the reading's age once for both."""
    weekly = window.kind == "seven_day"
    name = WEEKLY_NAME if weekly else FIVE_HOUR_NAME
    notes: list[str] = []
    if window.state == "no_limit":
        return WindowRow(name, "no limit", 0, 0.0, "", "", metered=False)
    if window.state == "not_started":
        figure, level, fraction, detail = "not started", 0, 0.0, ""
    else:
        if window.percent is None:
            figure, level, fraction = ("running" if window.state == "running" else "unknown"), 0, 0.0
        else:
            figure = ("≈" if window.estimated else "") + percent_text(window.percent)
            level = warning_level(window.kind, window.percent)
            fraction = max(0.0, min(1.0, window.percent / 100.0))
        if window.resets_at is None:
            detail = "reset time unknown"
        else:
            mark = _reset_mark(window)
            left = span(window.resets_at - now)
            detail = (f"resets {mark}{week_moment(window.resets_at, now)} (in {left})" if weekly
                      else f"resets in {left} ({mark}{when(window.resets_at)})")
        if window.exhausts_at is not None:
            notes.append(f"full at this pace ≈{when(window.exhausts_at)}")
    if say_reading:
        notes.append(reading_text(window, now))
    return WindowRow(name, figure, level, fraction, detail, " · ".join(notes), products_text(window.by_product, now))


SAME_RESET = 60.0   # s: a per-model window resetting this close to the weekly window resets with it


def scoped_row(scoped: Scoped, weekly: Window, now: float) -> WindowRow:
    """A per-model window's two lines, by the model's name: its figure, ≈ where the service estimated it, coloured by
    the per-model window's warning figures; then its reset where it is not the week's, its allowance's share of the week
    and the age of the claude.ai reading it rests on, said always since it is read apart from the other windows."""
    if scoped.percent is None:
        figure, level, fraction = "unknown", 0, 0.0
    else:
        figure = ("≈" if scoped.estimated else "") + percent_text(scoped.percent)
        level = warning_level("weekly_scoped", scoped.percent)
        fraction = max(0.0, min(1.0, scoped.percent / 100.0))
    shared = (scoped.resets_at is not None and weekly.resets_at is not None
              and abs(scoped.resets_at - weekly.resets_at) < SAME_RESET)
    detail = ("" if scoped.resets_at is None or shared
              else f"resets {week_moment(scoped.resets_at, now)} (in {span(scoped.resets_at - now)})")
    notes = []
    if scoped.allowance is not None:
        notes.append(f"{percent_text(scoped.allowance)} of the weekly limit")
    if scoped.state == "unknown":
        notes.append("a reset came since claude.ai was read")
    notes.append("no reading yet" if scoped.as_of is None else f"read on claude.ai {ago(now - scoped.as_of)}")
    return WindowRow(scoped.name, figure, level, fraction, detail, " · ".join(notes), metered=False)


def products_text(by_product: ByProduct | None, now: float) -> str:
    """``by product 3h ago: Claude Code 89%, Chats 11%``: the shares above zero; empty where fewer than two are."""
    used = [(name, percent) for name, percent in (by_product.shares if by_product else ()) if percent > 0]
    if len(used) < 2:
        return ""
    return f"by product {ago(now - by_product.as_of)}: " + ", ".join(f"{name} {percent_text(p)}" for name, p in used)


def plan_row(subscription: Subscription) -> PlanRow:
    until = day_text(subscription.paid_until)
    if subscription.state == "active":
        text = f"{subscription.plan_name or 'a recorded plan'} · paid until {until}"
        if subscription.days_left is not None and renewal_near(subscription.days_left):
            text += f" ({plural(subscription.days_left, 'day')} left)"
        tone = "warning" if subscription.renew_soon else "normal"
    elif subscription.state == "ended":
        text, tone = f"ended {until}", "warning"
    elif subscription.state == "upcoming":
        text, tone = f"first period starts {until}", "normal"
    elif subscription.state == "unread":
        # Its bills may not all have been read: no plan, end or absence is said, only where to look.
        text, tone = "bills not all read · see the source problems", "warning"
    else:
        text, tone = "no bills recorded", "muted"
    note = (profile_words(subscription.profile_check, subscription.profile_plan)
            if subscription.profile_check in PROFILE_NOTES else "")
    return PlanRow(text, tone, note)


def email_note(account: Account) -> str:
    """The account's e-mail where its name is the user's own, so the e-mail says what the name does not; else empty."""
    if not account.email or account.label in (account.email, default_label(account.uuid, account.email)):
        return ""
    return account.email


def ended_row(status: Status, account: Account, now: float, switches: Switches | None = None) -> EndedRow:
    """``plan ended Sun 1 Nov · week resets Sun 21:59``: the week's reset is the moment a renewal is planned around."""
    paid_until = account.subscription.paid_until if account.subscription else None
    parts = [f"plan ended {day_text(paid_until)}" if paid_until else "plan ended"]
    week = account.weekly
    if week.resets_at is not None:
        parts.append(f"week resets {_reset_mark(week)}{week_moment(week.resets_at, now)}")
    return EndedRow(uuid=account.uuid, label=account.label, text=" · ".join(parts), email=email_note(account),
                    switches=switch_buttons(status, account, switches or switches_of(status)))


def renew_tag(subscription: Subscription | None) -> str | None:
    if subscription is None or not subscription.renew_soon or subscription.days_left is None:
        return None
    days = subscription.days_left
    return "renew today" if days <= 0 else f"renew in {plural(days, 'day')}"


def card(status: Status, account: Account, now: float, switches: Switches | None = None) -> Card:
    tags = tuple(tag for tag, held in (("desktop app", account.is_desktop), ("CLI", account.is_cli),
                                       ("use next", status.recommended_account == account.uuid)) if held)
    shared = shared_reading(account)

    def dated(window: Window) -> bool:
        return reading_dated(window, account.last_activity, now)

    heading = " · ".join(part for part in (
        email_note(account),
        None if account.last_activity is None else f"last response {ago(now - account.last_activity)}",
        reading_text(account.weekly, now) if shared and dated(account.weekly) else None) if part)
    return Card(uuid=account.uuid, label=account.label, heading=heading, tags=tags,
                renew_tag=renew_tag(account.subscription),
                five_hour=window_row(account.five_hour, now, not shared and dated(account.five_hour)),
                weekly=window_row(account.weekly, now, not shared and dated(account.weekly)),
                plan=plan_row(account.subscription) if account.subscription else None,
                switches=switch_buttons(status, account, switches or switches_of(status)),
                weekly_first=weekly_leads(account), in_use=account.is_desktop or account.is_cli,
                scoped=tuple(scoped_row(s, account.weekly, now) for s in account.weekly.scoped))


def totals_line(status: Status) -> str | None:
    """This UTC month across the accounts (``windowtally.billing.month_totals_text``, which the ``status`` command says
    too), the plans' cost said not to be known while some bill may not have been read, the use outside the plans and the
    multiple without resets where status.json gives them; None where it gives neither sum."""
    return month_totals_text(status.month_api, status.month_plans, status.bills_unread, status.month_in_plans,
                             status.month_one_window)


def next_text(status: Status, now: float) -> str:
    """The recommendation's reason, with the time left until room returns or the first account opens where it names
    that moment, ≈ where the moment was inferred: ``… Room returns ≈Thu 14:00 (in ≈1h 05m).``"""
    reason = status.recommended_reason
    if status.relief_at is None:
        return reason
    approx = "" if status.relief_exact else "≈"
    return f"{reason[:-1] if reason.endswith('.') else reason} (in {approx}{span(status.relief_at - now)})."


def chips_say_clients(status: Status, not_running: bool) -> bool:
    """Whether the cards' chips say which account each client uses, so the header need not: the desktop app runs, or
    is being started, signed in, and both clients use an account the status knows, which then has a card, since an
    account in use is never hidden nor set aside."""
    return (status.desktop_signed_in and not not_running and status.account(status.desktop_account) is not None
            and status.account(status.cli_account) is not None)


def _clients(status: Status, not_running: bool) -> str:
    """Which account each client uses: ``Desktop app and CLI: alpha``, ``Desktop app: alpha (not running) · CLI: beta``."""
    if status.desktop_signed_in and not not_running and status.desktop_account is not None \
            and status.desktop_account == status.cli_account:
        return f"Desktop app and CLI: {_label(status, status.cli_account)}"
    desktop = _label(status, status.desktop_account) if status.desktop_signed_in else "at its sign-in page"
    if not_running:
        desktop += " (not running)"
    return f"Desktop app: {desktop} · CLI: {_label(status, status.cli_account)}"


def header(status: Status, now: float, switches: Switches | None = None, starting: bool = False) -> Header:
    """``starting``: the window has started the desktop app and no status says yet whether it runs
    (``still_starting``)."""
    stale = is_stale(status, now)
    if status.generated_at is None:
        status_line = "Status time unknown"
    else:
        status_line = f"Updated {ago(now - status.generated_at)}"
    if stale:
        status_line += " — the service may not be running"
    all_blocked = status.recommended_account is None and status.relief_at is not None
    next_line = f"Next: {next_text(status, now)}"
    not_running = _not_running(status, starting)
    parts = [] if chips_say_clients(status, not_running) else [_clients(status, not_running)]
    parts.append(mode_words(switches or switches_of(status)))
    hidden = len(status.accounts) - len(status.listed)
    if hidden:
        parts.append(f"{plural(hidden, 'account')} hidden")
    return Header(status_line=status_line, stale=stale, in_use_line=" · ".join(parts),
                  totals_line=totals_line(status), cli_condition=status.cli_condition, next_line=next_line,
                  all_blocked=all_blocked, not_running=not_running)


def live_view(snapshot: Snapshot | None, now: float, switches: Switches | None = None,
              starting: bool = False) -> LiveView:
    """The window's view of ``snapshot`` at ``now``; ``switches`` are the sync's two switches as the window shows them
    (``switch_model.switches_to_show``), the status's own where not given; ``starting`` as ``header`` takes it."""
    problem = snapshot_problem(snapshot)
    status = snapshot.status if snapshot is not None else None
    if status is None:
        return LiveView(problem, None, (), ())
    return LiveView(problem, header(status, now, switches, starting),
                    tuple(card(status, a, now, switches) for a in status.listed if not windows_left_out(a)),
                    status.source_errors,
                    tuple(ended_row(status, a, now, switches) for a in status.listed if windows_left_out(a)))


def weekly_leads(account: Account) -> bool:
    """Whether the account has no 5-hour limit, so that its weekly window leads on every surface."""
    return account.five_hour.state == "no_limit"


def plan_ended(account: Account) -> bool:
    """Whether the account's bills record a plan that has ended and none since, one of the accounts the recommendation
    does not weigh. A plan upcoming or no bill recorded is not one."""
    return account.subscription is not None and account.subscription.state == "ended"


def windows_left_out(account: Account) -> bool:
    """Whether the window and the tooltip leave the account's windows out, as the plugin's band does: its plan has ended
    and neither client uses it, so it takes no readings and its figures stand at nothing."""
    return plan_ended(account) and not (account.is_desktop or account.is_cli)


def in_use(status: Status) -> Account | None:
    """The account the desktop app uses, else the CLI's: an app at its sign-in page uses none."""
    return status.account(status.desktop_account) or status.account(status.cli_account)


def _brief(name: str, window: Window, now: float) -> str:
    """A window as the band writes it: ``5h ≈82% ↻1h 19m``, ``5h running ↻≈1h 19m``, ``week 60% ↻Sat 04:00``,
    ``5h not started``, ``5h no limit``."""
    if window.state == "not_started":
        return f"{name} not started"
    if window.state == "no_limit":
        return f"{name} no limit"
    if window.percent is None:
        figure, mark = ("running" if window.state == "running" else "unknown"), _reset_mark(window)
    else:
        figure, mark = ("≈" if window.estimated else "") + percent_text(window.percent), ""
    if window.resets_at is None:
        return f"{name} {figure}"
    moment = week_moment(window.resets_at, now) if window.kind == "seven_day" else span(window.resets_at - now)
    return f"{name} {figure} ↻{mark}{moment}"


def _fit(lines: list[str], protected: int = 0) -> str:
    """The lines within Windows' limit: the lines after line ``protected`` left off the end whole, an ellipsis line
    saying so; where the lines up to it still run over, they are cut at the limit."""
    text = "\n".join(lines)
    if len(text) <= TOOLTIP_LIMIT:
        return text
    kept = list(lines)
    while len(kept) > protected + 1:
        kept.pop()
        shortened = "\n".join(kept + ["…"])
        if len(shortened) <= TOOLTIP_LIMIT:
            return shortened
    text = "\n".join(kept)
    return text if len(text) <= TOOLTIP_LIMIT else text[:TOOLTIP_LIMIT - 1] + "…"


def tray_view(snapshot: Snapshot | None, now: float, starting: bool = False) -> TrayView:
    """The tray's tooltip and picture; ``starting`` as ``header`` takes it."""
    problem = snapshot_problem(snapshot)
    status = snapshot.status if snapshot is not None else None
    if status is None or not status.accounts:
        return TrayView(_fit([f"WindowTally: {problem}"]), -1, None, None, None)
    account = in_use(status)
    can_start = _not_running(status, starting)
    lines = ["Desktop app not running"] if can_start else []
    if is_stale(status, now):
        age = "unknown" if status.generated_at is None else span(now - status.generated_at)
        lines.append(f"Status {age} old: is the service running?")
    # status.json lists the accounts in the order every surface shows them, the accounts in use first; an account whose
    # plan has ended and that no client uses is the window's to show, not the tooltip's.
    in_use_lines, other_lines = [], []
    for a in status.listed:
        if windows_left_out(a):
            continue
        roles = [r for r, held in (("app", a.is_desktop), ("CLI", a.is_cli)) if held]
        briefs = [_brief("5h", a.five_hour, now), _brief("week", a.weekly, now)]
        if weekly_leads(a):
            briefs.reverse()
        (in_use_lines if roles else other_lines).append(
            f"{a.label}{' (' + ', '.join(roles) + ')' if roles else ''}  {' · '.join(briefs)}")
    next_account = status.account(status.recommended_account)
    if next_account is None:
        # With a moment the first opens, every account is at its limit; without one the reason is a single sentence
        # of its own, every account at its limit or none left to weigh.
        reason = status.recommended_reason.rstrip(".")
        next_line = "Every account is at its limit" if status.relief_at is not None or not reason else reason
    elif status.relief_at is None:
        next_line = f"Next: {next_account.label}"
    else:
        next_line = f"Next: {next_account.label}, all at or near the limit"
    lines += in_use_lines + [next_line]
    protected = len(lines) - 1
    lines += other_lines
    if account is None or is_stale(status, now):
        return TrayView(_fit(lines, protected), -1, None, None, account.uuid if account else None, can_start,
                        weekly_only=account is not None and weekly_leads(account))
    five_hour_level = warning_level(account.five_hour.kind, account.five_hour.percent)
    weekly_level = warning_level(account.weekly.kind, account.weekly.percent)
    if status.recommended_account is None and status.relief_at is not None:
        five_hour_level = weekly_level = 2

    def fill(window: Window) -> float | None:
        if window.state == "not_started":
            return 0.0
        return None if window.percent is None else max(0.0, min(1.0, window.percent / 100.0))

    return TrayView(_fit(lines, protected), max(five_hour_level, weekly_level), fill(account.five_hour),
                    fill(account.weekly), account.uuid, can_start, weekly_only=weekly_leads(account),
                    five_hour_level=five_hour_level, weekly_level=weekly_level)
