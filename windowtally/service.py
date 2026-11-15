"""One pass over every source, and the background loop that repeats it.

A pass refreshes the account registry; ingests the sync's events and log, the app's history, the plugin's readings,
the browser extension's readings and the transcripts; prices the responses a model new to the price table left
unpriced, naming each model still without a price among the source problems; re-attributes; reads the user's bills and
settings, and gives each account the name the user gave it there, so every figure and word that follows names it so;
computes every account's standing; works out what the
bills say; recommends an account, weighing none the user hid or whose plan has ended; writes ``status.json``, its
accounts in the order every surface lists them and those the user hid marked; and regenerates the history
page when it is older than ``DASHBOARD_INTERVAL`` (or when asked). A source that fails is logged and named in the
status file's ``sourceErrors``, and the pass goes on with the others, so a stale figure is never presented as a fresh
one.

The service is not the only process that runs passes: the command line's ``once`` and ``dashboard`` and the window's
Refresh run one beside it. Each pass therefore holds the data folder's pass lock (``PassLock``) from
start to end, waiting for one already running, so two passes never write status.json or the history page at once.

Only the service keeps the computer awake while a Claude Code session works, on a thread of its own beside the passes
(``keep_awake``); a pass run by the command line or the window holds nothing. A pass counts the desktop app's sessions
at work off Claude Code's session registry for status.json, naming a registry file it cannot read among the source
problems.

A pass times each of its phases (``PassReport.phases``). The service logs one line for every pass — its counts, its
time, the history page's share of it and any wait for the pass lock — and, for a pass of ``SLOW_PASS`` seconds or
more, a second line with the time of every phase, so a slow pass names where its time went.
"""

from __future__ import annotations

import logging
import logging.handlers
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, TypeVar

from .accounts import Account, by_email, by_org, load_registry, named
from .attribution import Timeline, attribute, cli_timeline, desktop_timeline
from .billing import BillingReport, billing_report, month_start, utc_day
from .bills import BillSet, load_bills
from .dashboard import render_dashboard, write_dashboard
from .files import FileLock, try_lock
from .ingest_app_history import ingest_app_history
from .ingest_browser import ingest_browser
from .ingest_readings import ingest_readings
from .ingest_sync import WatchView, ingest_sync_events, ingest_sync_log, read_watch_view
from .ingest_transcripts import Repricing, TranscriptStats, ingest_transcripts, reprice
from .ledger import Ledger
from .limits import recommend, standings
from .keep_awake import start_keep_awake
from .paths import MachinePaths
from .plan_use import plan_use
from .products import current_reports
from .registry import read_registry
from .settings import Settings
from .status_file import status_document, write_status
from .sync_store import desktop_archived_accounts, read_sync_settings

log = logging.getLogger(__name__)

PASS_INTERVAL = 60.0
DASHBOARD_INTERVAL = 600.0
PASS_LOCK_PATIENCE = 300.0  # seconds a pass waits for another to end; a first import of a long history takes minutes
SLOW_PASS = 10.0  # seconds from which the service logs a pass's phases; one writing the history page can take that long
LOCK_WAIT_LOGGED = 1.0  # seconds of waiting for the pass lock from which the service's line names the wait
# Seconds a watcher's view that the desktop app is not running is taken at its word: the watcher writes it again at
# every look, every 15 s, so one this old says the watcher has stopped looking.
NOT_RUNNING_FRESH = 120.0

HISTORY_PAGE = "history page"


@dataclass
class PassReport:
    started: float
    duration: float = 0.0  # the pass's own time, under the lock
    lock_wait: float = 0.0  # the time spent waiting for another pass to end, before ``started``
    phases: list[tuple[str, float]] = field(default_factory=list)  # (phase, seconds), in the order they ran
    errors: list[str] = field(default_factory=list)
    transcripts: TranscriptStats = field(default_factory=TranscriptStats)
    new_observations: int = 0
    new_events: int = 0
    attributed: int = 0
    dashboard_written: bool = False
    status: dict | None = None
    billing: BillingReport | None = None


T = TypeVar("T")


def _timed(report: PassReport, name: str, action: Callable[[], T]) -> T:
    """``action``'s result, its time recorded as the phase ``name`` whether it returns or raises."""
    start = time.perf_counter()
    try:
        return action()
    finally:
        report.phases.append((name, time.perf_counter() - start))


def _step(report: PassReport, name: str, action: Callable[[], object]) -> object | None:
    try:
        return _timed(report, name, action)
    except Exception as exc:  # one source's failure must not stop the others; it is logged and reported
        log.exception("%s failed", name)
        report.errors.append(f"{name}: {exc}")
        return None


def run_pass(paths: MachinePaths, now: float | None = None, *, dashboard: bool | None = None) -> PassReport:
    """One pass, under the pass lock. ``dashboard`` True forces the page, False skips it, None regenerates it when it
    is due. TimeoutError when another pass holds the lock longer than ``PASS_LOCK_PATIENCE``."""
    asked = time.perf_counter()
    with PassLock(paths.pass_lock):
        lock_wait = time.perf_counter() - asked
        report = _pass(paths, now, dashboard)
    report.lock_wait = lock_wait
    return report


def _registry(ledger: Ledger, paths: MachinePaths) -> tuple[dict[str, Account], list[str], dict[str, Account]]:
    """The profiles on this machine and their warnings, recorded in the ledger; then every account the ledger knows."""
    registry, warnings = load_registry(paths.accounts_dir)
    with ledger.transaction():
        ledger.upsert_accounts(registry)
        ledger.set_profiles_on_machine(registry)
    return registry, warnings, ledger.known_accounts()


def _plans_ended(billing: BillingReport | None, accounts: Mapping[str, Account]) -> frozenset[str]:
    """The accounts whose bills record a plan that has ended and none since: a recorded period, none covering today
    and none to come. An account no bill names, or every account while no bill source exists, is not among them: the
    bills say nothing of it."""
    if billing is None or not billing.configured:
        return frozenset()
    ended = set()
    for uuid in accounts:
        subscription = billing.for_account(uuid)
        if subscription is not None and subscription.state == "ended":
            ended.add(uuid)
    return frozenset(ended)


def _pass(paths: MachinePaths, now: float | None, dashboard: bool | None) -> PassReport:
    started = time.time()
    clock = time.perf_counter()
    now = started if now is None else now
    report = PassReport(started=started)
    ledger = _timed(report, "ledger open", lambda: Ledger.open(paths.ledger_db))
    try:
        registry, warnings, accounts = _timed(report, "registry", lambda: _registry(ledger, paths))
        report.errors.extend(warnings)

        report.new_events += _step(report, "sync events", lambda: ingest_sync_events(ledger, paths.sync_events)) or 0
        report.new_events += _step(report, "sync log",
                                   lambda: ingest_sync_log(ledger, paths.sync_log, by_email(accounts))) or 0
        report.new_observations += _step(report, "desktop app history", lambda: ingest_app_history(
            ledger, paths.plan_usage_history, by_org(accounts))) or 0
        report.new_observations += _step(report, "plugin readings",
                                         lambda: ingest_readings(ledger, paths.readings_dir, now)) or 0
        report.new_observations += _step(report, "browser readings", lambda: ingest_browser(
            ledger, paths.browser_dir, by_org(accounts), now)) or 0
        stats = _step(report, "transcripts", lambda: ingest_transcripts(ledger, paths.projects_dir))
        if isinstance(stats, TranscriptStats):
            report.transcripts = stats
        repricing = _step(report, "prices", lambda: reprice(ledger))
        if isinstance(repricing, Repricing):
            report.errors.extend(unpriced_problems(repricing))
        report.attributed = _step(report, "attribution", lambda: attribute(ledger)) or 0

        # The bills come before the standings for the settings they carry: the user's names for the accounts are in
        # every standing, the recommendation's reason and the history page. Settings that cannot be read name nothing,
        # order nothing and hide nothing, the problem among the source problems. The billing comes before the
        # recommendation, which does not weigh an account whose plan has ended.
        bill_set = _step(report, "bills", lambda: load_bills(paths))
        settings = bill_set.settings if isinstance(bill_set, BillSet) else Settings()
        accounts = named(accounts, settings.names)
        in_use = _timed(report, "accounts in use", lambda: _accounts_in_use(ledger, paths, now))
        current = _timed(report, "standings", lambda: standings(ledger, accounts.values(), now,
                                                                  desktop_uuid=in_use.desktop, cli_uuid=in_use.cli))
        silenced = settings.silence_notifications
        if isinstance(bill_set, BillSet):
            report.errors.extend(bill_set.errors)
            billing = _step(report, "billing", lambda: billing_report(bill_set, accounts, registry, ledger, now))
            if isinstance(billing, BillingReport):
                report.billing = billing
                report.errors.extend(billing.problems)
        excluded = settings.hidden | _plans_ended(report.billing, accounts)
        recommendation = _timed(report, "recommendation", lambda: recommend(current, excluded))
        # The use by product is an addition no figure rests on: a failure to read it is a source problem, and the
        # status is written without it.
        reports = _step(report, "use by product", lambda: current_reports(ledger, current, now))
        by_product = reports if isinstance(reports, dict) else None

        def status() -> dict:
            first = month_start(utc_day(now))
            api_this_month = ledger.total_cost_in(first, now)
            # What the plans covered of it is an addition the month's totals carry: a failure to split it is a source
            # problem, and the status is written without it.
            try:
                month = plan_use(ledger, first, now).between(first, now)
                in_plans, one_window = api_this_month - month.outside, api_this_month - month.outside - month.beyond
            except Exception as exc:  # logged and reported as a failing source is
                log.exception("plan use failed")
                report.errors.append(f"plan use: {exc}")
                in_plans = one_window = None
            follows, one_click = read_sync_settings(paths.sync_settings)
            registry = read_registry(paths.registry_dir)
            report.errors.extend(registry.problems)
            ws = len(registry.desktop_working_ids())
            archived = desktop_archived_accounts(paths.accounts_dir)
            document = status_document(current, recommendation, now=now, desktop_account=in_use.desktop,
                                       desktop_signed_out=in_use.desktop_signed_out,
                                       desktop_not_running=in_use.desktop_not_running, cli_account=in_use.cli,
                                       cli_condition=in_use.view.condition if in_use.view else None,
                                       source_errors=report.errors,
                                       billing=report.billing, notifications_silenced=silenced,
                                       api_this_month=api_this_month, sync_follows=follows,
                                       one_click_desktop=one_click, working_sessions=ws,
                                       desktop_archived=archived, account_order=settings.account_order,
                                       hidden=settings.hidden, by_product=by_product,
                                       in_plans_this_month=in_plans, one_window_this_month=one_window)
            write_status(paths.status_file, document)
            return document

        report.status = _timed(report, "status.json", status)

        due = dashboard if dashboard is not None else _dashboard_due(paths, now)
        if due:
            _timed(report, HISTORY_PAGE, lambda: write_dashboard(paths.dashboard_file, render_dashboard(
                ledger, accounts, current, recommendation, now, report.errors, report.billing, by_product)))
            report.dashboard_written = True
    except Exception:  # the caller reports the failure; the time spent before it is said here, or it is lost
        log.warning("A pass failed after %.1f s, by phase: %s", time.perf_counter() - clock, _phase_words(report))
        raise
    finally:
        _timed(report, "ledger close", ledger.close)
    report.duration = time.perf_counter() - clock
    return report


def unpriced_problems(repricing: Repricing) -> list[str]:
    """A source problem for each model whose responses have no list price: their cost counts as nothing in every sum
    until the price table names the model, so a figure resting on it would read low without a word."""
    return [f"prices: {model} has no list price, so the cost of its {count} response{'' if count == 1 else 's'} "
            "counts as nothing" for model, count in repricing.unpriced]


def _phase_words(report: PassReport) -> str:
    return ", ".join(f"{name} {seconds:.1f} s" for name, seconds in report.phases)


@dataclass(frozen=True)
class AccountsInUse:
    """The sync watcher's view, and the accounts the desktop app and the CLI use now."""

    view: WatchView | None
    desktop: str | None
    desktop_signed_out: bool    # the desktop app is at its sign-in page, so ``desktop`` is None
    cli: str | None
    desktop_not_running: bool = False   # none of the desktop app's processes runs


def _accounts_in_use(ledger: Ledger, paths: MachinePaths, now: float) -> AccountsInUse:
    view = read_watch_view(paths.sync_watch_state)
    timeline = desktop_timeline(ledger)
    desktop, signed_out = _desktop_account(view, timeline)
    cli = _current_account(view.t if view else None, view.cli_account if view else None, cli_timeline(ledger))
    return AccountsInUse(view, desktop, signed_out, cli, _desktop_not_running(view, timeline, now))


def _desktop_not_running(view: WatchView | None, timeline: Timeline, now: float) -> bool:
    """Whether the desktop app is not running, as the watcher's view says, only while that view is at least as new as
    the desktop timeline's last point — a switch or a start writes its point and starts the app, so a point newer than
    the view says the app was started since the watcher last looked — and no older than ``NOT_RUNNING_FRESH``: the
    watcher writes such a view again at every look, so an older one means the watcher stopped, and the app may have
    been started by hand since."""
    return (view is not None and view.desktop_not_running and _view_is_newer(view.t, timeline)
            and view.t is not None and now - view.t <= NOT_RUNNING_FRESH)


def _view_is_newer(view_time: float | None, timeline: Timeline) -> bool:
    """Whether the sync watcher's view, written at ``view_time``, is at least as new as the timeline's last point.

    The watcher rewrites its view on every change it sees, and at every look while the desktop app is not running, so
    a timeline point newer than the view means the watcher was not running when that change happened, or a mode of
    the sync recorded it before the watcher's next look, and the point is the better evidence.
    """
    return not timeline.times or (view_time is not None and view_time >= timeline.times[-1])


def _current_account(view_time: float | None, view_account: str | None, timeline: Timeline) -> str | None:
    """The account the newer of two sources names: the sync watcher's view, or the timeline's last point."""
    if view_account and _view_is_newer(view_time, timeline):
        return view_account
    return timeline.accounts[-1] if timeline.accounts else view_account


def _desktop_account(view: WatchView | None, timeline: Timeline) -> tuple[str | None, bool]:
    """The desktop app's account now, and whether it is at its sign-in page, from the newer of the watcher's view and
    the desktop timeline's last point, as ``_current_account`` takes them: a view, or a point, that says the app is at
    its sign-in page answers no account, where a view that names none at all leaves the answer to the timeline."""
    if view is not None and (view.desktop_account or view.desktop_signed_out) and _view_is_newer(view.t, timeline):
        return (None, True) if view.desktop_signed_out else (view.desktop_account, False)
    if timeline.accounts:
        return timeline.accounts[-1], timeline.accounts[-1] is None
    return None, False


def _dashboard_due(paths: MachinePaths, now: float) -> bool:
    try:
        return now - paths.dashboard_file.stat().st_mtime >= DASHBOARD_INTERVAL
    except FileNotFoundError:
        return True


class SingleInstance:
    """An exclusive lock on a lock file in the data folder, held for the life of the process: the service's, and the
    window's (one window per user)."""

    def __init__(self, path):
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "a+")
        if not try_lock(self.handle):
            self.handle.close()
            self.handle = None
            return False
        return True


class PassLock(FileLock):
    """The data folder's pass lock, held for one pass, waiting up to ``patience`` seconds (``PASS_LOCK_PATIENCE`` when
    not given) for another pass to end."""

    def __init__(self, path, patience: float | None = None):
        super().__init__(path, PASS_LOCK_PATIENCE if patience is None else patience, "another pass")


def configure_logging(paths: MachinePaths, *, to_file: bool) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    if to_file:
        paths.data_dir.mkdir(parents=True, exist_ok=True)
        # A line for every pass, a pass a minute, is about 200 KB a day: three files of 2 MB keep about a month.
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            paths.log_file, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.handlers[:] = [handler]


def run_forever(paths: MachinePaths, interval: float = PASS_INTERVAL) -> int:
    """The background service: a pass every ``interval`` seconds, and beside the passes the keep-awake, which holds the
    computer awake while a Claude Code session works (``keep_awake``). A second instance exits at once."""
    lock = SingleInstance(paths.lock_file)
    if not lock.acquire():
        log.info("Another ledger service holds %s; exiting.", paths.lock_file)
        return 0
    log.info("Ledger service started; a pass every %.0f s.", interval)
    start_keep_awake(paths.registry_dir, paths.settings_file)
    while True:
        try:
            for level, message in pass_log_lines(run_pass(paths)):
                log.log(level, "%s", message)
        except Exception:  # the loop must outlive a failed pass; the next pass retries
            log.exception("Pass failed")
        time.sleep(interval)


def pass_log_lines(report: PassReport) -> list[tuple[int, str]]:
    """What the service logs of one pass, as (level, message): the pass's line, every pass; its source problems, where
    it met any; its phases, where it took ``SLOW_PASS`` seconds or more."""
    line = (f"Pass: {report.transcripts.responses} responses, {report.new_observations} observations, "
            f"{report.new_events} events, {report.attributed} attributed in {report.duration:.1f} s")
    page = sum(seconds for name, seconds in report.phases if name == HISTORY_PAGE)
    if report.dashboard_written:
        line += f"; the history page took {page:.1f} s of it"
    if report.lock_wait >= LOCK_WAIT_LOGGED:
        line += f"; it waited {report.lock_wait:.1f} s for another pass first"
    lines = [(logging.INFO, line)]
    if report.errors:
        lines.append((logging.WARNING, "Pass finished with source problems: " + "; ".join(report.errors)))
    if report.duration >= SLOW_PASS:
        lines.append((logging.INFO, f"Slow pass, {report.duration:.1f} s by phase: {_phase_words(report)}"))
    return lines
