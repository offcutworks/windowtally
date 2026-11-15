"""Each account's standing in its two plan windows and its per-model weekly windows, and the views built on it.

Vocabulary
    five_hour     the 5-hour window. It starts with the first message after the previous window ended and lasts
                  five hours; once past its end it is *not started* until the next message.
    seven_day     the weekly window. It resets at a fixed instant every week — the account's weekly *anchor*.
    observation   a window's percentage at a moment: an app sample (no reset time), a plugin reading (with the
                  exact reset time Claude Code received) or a browser reading (with the exact reset time claude.ai's
                  page received).
    reset outside the schedule
                  a fall in the weekly percentage at a moment the schedule does not explain: a reset Anthropic hands
                  out at random, free and not for sale, which the user takes when they choose, of the week or of a
                  model's own allowance. It leaves the week's reset time as it was; ``plan_use`` tells its kinds
                  apart — extra, the week given back, a model's allowance's, or not known.
    blocked       a window at or above ``CAPPED`` percent: the account cannot be used until that window resets.
    no limit      the 5-hour window of an account whose plan has none: Anthropic removes the 5-hour limit account by
                  account, and from then on no source reads that window (``five_hour_removed``). Such an account is
                  judged by its weekly window alone.
    scoped window a model's own allowance inside the weekly window, as Fable's is (``scoped_standings``).

Usage only raises a percentage; only a reset lowers it. A reading can still stand a little below the one before it:
Claude Code sessions running at once each hand on the figure their own latest response carried, so one session's
reading can trail another's taken seconds earlier — by a point in the weekly window, by up to about five in the 5-hour
window, as measured on the development machine. The desktop app rounds its figure differently too: read in the same
minute, it stands a point above Claude Code's a third of the time in the 5-hour window and half the time in the weekly
one. So a window's figure is the highest any observation of it has read (``_peak``), never merely the latest: a
lower figure read after it says less. A fall of ``DROP_POINTS`` or more is taken for a reset, an idle account's
figures stand until its next reset, and between two observations the rise can be estimated from the API-equivalent
cost of the responses in between (``percent_per_dollar``). Every estimated figure is flagged.

A scoped window, as claude.ai reports it (measured in Chrome on the development machine, 2026-11-10): its usage
response lists, beside the weekly window, a window of kind ``weekly_scoped`` for each model that has one — Fable's —
with its own percentage and the weekly window's reset, and the model's allowance as a share of the weekly window, half
of it on the plan it was read on. The model's use counts in both: its share of the weekly window is its own percentage
times that allowance. Past its allowance the model goes on at usage credits, outside the plan, so its use raises the
weekly window no further; and a reset of the model's allowance, which the user can take, gives its share of the weekly
window back, the weekly reset time unchanged — both measured in the ledger the same day, the weekly window standing
still once Fable's allowance filled, and falling by the allowance's share when a reset of it gave that back.

Only the browser extension reads a scoped window — Claude Code hands its plugins the 5-hour and weekly windows alone
(its build 2.1.321) — so its latest reading may be hours old, and its standing at ``now`` is that reading carried
forward, flagged. The weekly window's own readings go on meanwhile, so the model's part of the week's rise since is
read from them: the rise between the first weekly reading since and the latest is split between the model and every
other model in proportion to what each spent between those two readings at its own points per dollar
(``family_rates``), or by the dollars alone where either rate is not measured, and the model's part, over the
allowance, is added, the allowance capping it. Only the model's spend outside those two readings is added at its
points per dollar alone, or at the account's single rate where its own is not measured. One rate for every model will
not do: the plan meters models unevenly against their list prices — measured on the development machine, 2026-11-10
and -11, a dollar of Fable 5.2 took several times the weekly points a dollar of the other families took, so the
account's single rate carried a reading far below claude.ai's. The model's own rate is read off claude.ai's readings
of its window wherever they measure it — what the window rose between two of them, or since the start of a week it was
watched from, over what the model spent — and only without them taken as what the weekly window's rises leave once
every other model's rate is taken out (``read_rate_of``), a remainder measured on the development machine, 2026-11-14,
to stand at times well short of the read rate and at times level with it. The two readings' figures are each the
highest any instrument read by then, as the weekly window's own is
(``_peak``), so their instruments' rounding moves the rise by a point at most. A scheduled weekly reset since empties
the window; and a fall of the weekly window since, read by the rule a reset is read by, that gives back about what the
model held of the week is a reset of the model's allowance, which then starts again from nothing, while any other
fall large enough to have touched it leaves it unknown until claude.ai is read again. The weekly window's projection
stops the model's part of its pace where the model's allowance fills (``projection_plateaus``). The rule is one object,
``ScopedCarry``, which the history also carries a model's window by over past weeks (``plan_use``).
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import accumulate
from typing import Callable, Collection, Iterable

from .accounts import Account, arranged
from .ledger import Ledger, Observation, ScopedObservation
from .pricing import family_named, model_family
from .timeutil import local_datetime

WEEK = 7 * 24 * 3600.0
FIVE_HOURS = 5 * 3600.0
DROP_POINTS = 3.0                 # a fall of at least this many points is a reset, not rounding
CAPPED = 99.0                     # a window at or above this percentage is exhausted
PHASE_STEP = 900.0                # resolution of the weekly-anchor search: 15 minutes
STEADY_EVIDENCE_SPAN = 2 * 3600.0 # a rise over at most this span, from a non-trivial level, rules a reset out
STEADY_EVIDENCE_FLOOR = 10.0
CALIBRATION_DAYS = 14
CALIBRATION_MAX_GAP = 3 * 3600.0  # observation pairs further apart could hide use on another device
CALIBRATION_MIN_COST = 5.0        # USD of priced use needed before a percent-per-dollar rate is trusted
SAME_WINDOW_END = 2.0             # s: readings whose window ends differ by less name one window; within one window
                                  # Claude Code's reset time holds to the millisecond, measured on the development machine
WINDOW_START_MARGIN = 60.0        # s: an observation this soon after a window's start may still read the one before it
PROJECTION_LOOKBACK = 2 * 3600.0
PROJECTION_MIN_SPAN = 20 * 60.0
PROJECTION_FRESHNESS = 30 * 60.0  # the latest observation must be this recent for a projection
RECOMMEND_WEEKLY_CEILING = 95.0
RECOMMEND_FIVE_HOUR_CEILING = 90.0
HISTORY_WEEKS = 6
NO_LIMIT_SPAN = 15 * 60.0         # s: readings with no 5-hour window span this before the limit counts as removed
SHARE_TOLERANCE = 0.25            # a weekly fall within this part of a model's share of the week gave that share back
FAMILY_FREE_SHARE = 0.01          # a run of rises at most this part of whose dollars are one family's measures the rest

WARNING_THRESHOLDS = {"five_hour": (80.0, 95.0), "seven_day": (70.0, 90.0), "weekly_scoped": (80.0, 95.0)}
"""Each window's two warning figures: from the first its use is a warning, from the second an error. The desktop
plugin warns at them (``plugin/hooks/alerts.ts``, THRESHOLDS — the two change together), and the history page and the
window colour a figure by them, so every surface marks the same figure the same way. A per-model window
(``weekly_scoped``) fills within hours where the model is used, and past it the model runs at usage credits, so it
warns late and close to full, as the 5-hour window does."""


def warning_level(kind: str, percent: float | None) -> int:
    """0 below the window's first warning figure, or with no figure; 1 from the first; 2 from the second."""
    first, second = WARNING_THRESHOLDS.get(kind, (math.inf, math.inf))
    if percent is None or percent < first:
        return 0
    return 2 if percent >= second else 1


def reading_dated(as_of: float | None, last_activity: float | None, now: float) -> bool:
    """Whether a window's reading, taken at ``as_of``, is old enough that its figure may be out of date, so that a
    surface says its age: there is no reading; or a response has come since it was taken, use the reading does not
    hold; or it is a 5-hour window old or older, the shortest span over which an account's standing renews, so a whole
    window's use, on this machine or elsewhere, may lie after it. A reading taken since the account's last response and
    younger than that is the standing as it is. The window's cards and the history page's say a reading's age by it."""
    if as_of is None:
        return True
    return (last_activity is not None and last_activity > as_of) or now - as_of >= FIVE_HOURS


def shared_reading(five_hour_state: str, five_hour_as_of: float | None, weekly_as_of: float | None) -> bool:
    """Whether an account's card says its reading's age once rather than on each window's line: both windows rest on
    one reading, or the 5-hour window, having no limit, shows no figure that rests on one."""
    return five_hour_state == "no_limit" or five_hour_as_of == weekly_as_of


def renewal_near(days_left: int) -> bool:
    """Whether a plan's renewal is near enough that an account's card says its days left: within one weekly window, the
    longest span an account's limits renew over, so the renewal falls in the week the user plans their use in."""
    return days_left * 86400 <= WEEK


@dataclass(frozen=True)
class WeeklyAnchor:
    """One weekly reset instant; the resets recur every ``WEEK`` from it."""

    at: float
    exact: bool  # from a plugin or browser reading; else inferred from the app's samples

    def next_after(self, moment: float) -> float:
        return self.at + (math.floor((moment - self.at) / WEEK) + 1) * WEEK

    def last_at_or_before(self, moment: float) -> float:
        return self.at + math.floor((moment - self.at) / WEEK) * WEEK


@dataclass(frozen=True)
class WindowStanding:
    kind: str
    state: str                  # running | not_started | no_limit (five_hour) · current (seven_day) · unknown
    percent: float | None
    resets_at: float | None
    as_of: float | None         # the latest observation the figures rest on
    estimated: bool             # the percent or the reset time is inferred rather than read
    exhausts_at: float | None = None
    reset_exact: bool = False   # the reset time came from a plugin or browser reading; false with no reset time


@dataclass(frozen=True)
class ScopedStanding:
    """A per-model weekly window at ``now`` (``scoped_standings``)."""

    name: str                   # the model's name as claude.ai shows it: Fable
    state: str                  # current | unknown (a reset whose effect on it is not known came since its reading)
    percent: float | None       # of the model's own allowance; None while unknown
    resets_at: float | None
    as_of: float                # the reading the figure rests on
    estimated: bool             # a rise estimated from the model's use since, or a reset read from the weekly window
    allowance: float | None     # the allowance as a percentage of the weekly window; None where claude.ai did not say
    rate: float | None = None   # weekly points per dollar of the model's use as measured (``family_rates``), or None
    rest_rate: float | None = None  # the same of every other model's use, which the weekly window's rise is shared with


@dataclass(frozen=True)
class AccountStanding:
    account: Account
    five_hour: WindowStanding
    weekly: WindowStanding
    anchor: WeeklyAnchor | None
    last_activity: float | None
    is_desktop: bool
    is_cli: bool
    scoped: tuple[ScopedStanding, ...] = ()   # the per-model weekly windows of an account that has used the model


@dataclass(frozen=True)
class Recommendation:
    account_uuid: str | None
    reason: str
    relief_at: float | None     # with no account under the ceilings: the first reset that frees one
    relief_exact: bool = False  # relief_at came from a plugin or browser reading; False where inferred or there is none


# --- the weekly anchor ----------------------------------------------------------------------------------------

def _drops(observations: list[Observation]) -> list[tuple[float, float]]:
    """(before, after) of each consecutive pair whose percentage fell: a reset happened in (before, after]."""
    return [(a.t, b.t) for a, b in zip(observations, observations[1:]) if a.percent - b.percent >= DROP_POINTS]


def _steady(observations: list[Observation]) -> list[tuple[float, float]]:
    """Short spans across which the percentage rose from a non-trivial level: no reset happened inside them."""
    return [(a.t, b.t) for a, b in zip(observations, observations[1:])
            if b.percent >= a.percent >= STEADY_EVIDENCE_FLOOR and b.t - a.t <= STEADY_EVIDENCE_SPAN]


def _phase_counts(spans: list[tuple[float, float]], steps: int) -> list[int]:
    """For each phase step of the week, how many spans (start, end] contain an instant of that phase.

    A step is the instant ``i·PHASE_STEP`` (mod WEEK); WEEK is a whole number of steps, so the steps inside a
    span are the integers in (start/PHASE_STEP, end/PHASE_STEP], taken modulo the week.
    """
    difference = [0] * (steps + 1)
    for start, end in spans:
        low, high = math.floor(start / PHASE_STEP) + 1, math.floor(end / PHASE_STEP)
        if high < low:
            continue
        if high - low + 1 >= steps:
            difference[0] += 1
            difference[steps] -= 1
            continue
        first, last = low % steps, high % steps
        if first <= last:
            difference[first] += 1
            difference[last + 1] -= 1
        else:
            difference[first] += 1
            difference[steps] -= 1
            difference[0] += 1
            difference[last + 1] -= 1
    counts, running = [], 0
    for step in range(steps):
        running += difference[step]
        counts.append(running)
    return counts


def weekly_anchor(observations: list[Observation]) -> WeeklyAnchor | None:
    """The account's weekly reset instant: read from the latest plugin or browser reading that carries one, else
    inferred.

    Inference scores every phase of the week (in ``PHASE_STEP`` steps) by how many falls it explains, minus twice
    the steady spans it would contradict, and takes the middle of the best-scoring run. Falls spanning a week or
    more explain nothing and are ignored. A fall the winning phase does not explain is a reset outside the schedule,
    which ``plan_use`` reads week by week.
    """
    exact = [o for o in observations if o.resets_at is not None]
    if exact:
        latest = max(exact, key=lambda o: o.t)
        return WeeklyAnchor(at=latest.resets_at, exact=True)
    samples = sorted(observations, key=lambda o: o.t)
    drops = [d for d in _drops(samples) if d[1] - d[0] < WEEK]
    if not drops:
        return None
    steps = int(round(WEEK / PHASE_STEP))
    hit_counts = _phase_counts(drops, steps)
    miss_counts = _phase_counts(_steady(samples), steps)
    scores = [(hits - 2 * misses, hits) for hits, misses in zip(hit_counts, miss_counts)]
    best = max(score for score, _ in scores)
    if best <= 0:
        return None
    winners = [step for step, (score, hits) in enumerate(scores) if score == best and hits > 0]
    if not winners:
        return None
    middle = _middle_of_longest_run(winners, steps)
    phase = middle * PHASE_STEP
    reference = samples[-1].t
    return WeeklyAnchor(at=phase + math.floor((reference - phase) / WEEK) * WEEK, exact=False)


def _middle_of_longest_run(steps_in_run: list[int], modulus: int) -> float:
    """The middle step of the longest run of consecutive steps, the week being circular."""
    members = set(steps_in_run)
    best_start, best_length = steps_in_run[0], 0
    for step in steps_in_run:
        if (step - 1) % modulus in members and len(members) < modulus:
            continue
        length = 1
        while (step + length) % modulus in members and length < modulus:
            length += 1
        if length > best_length:
            best_start, best_length = step, length
    return (best_start + (best_length - 1) / 2) % modulus


# --- calibration and projection -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Rise:
    """How far one window's figure moved between two consecutive readings of one instrument inside one run, and the
    API-equivalent dollars of the account's responses after the first reading and up to the second (``rises``)."""

    source: str        # the instrument: "plugin" or "app"
    t: float           # the later reading's time
    points: float      # how far the later reading took the run's highest reading so far: never negative
    dollars: float     # zero where no response came between them
    run: int           # the run it belongs to, counted from 1 per instrument
    group: str         # what ``group`` named for both readings; empty where no ``group`` was given
    start: float       # the earlier reading's time: the dollars are the responses' in (start, t]


class Spending:
    """An account's responses as running sums, so the dollars and the unpriced responses between two moments are two
    lookups each."""

    def __init__(self, rows: list[tuple[float, float | None]]):
        self.times = [t for t, _ in rows]
        self.dollars, self.unpriced = [0.0], [0]
        for _, cost in rows:
            self.dollars.append(self.dollars[-1] + (cost or 0.0))
            self.unpriced.append(self.unpriced[-1] + (cost is None))

    def between(self, start: float, end: float) -> float | None:
        """The dollars of the responses in (start, end], zero where there is none; None where one has no list price."""
        low, high = bisect_right(self.times, start), bisect_right(self.times, end)
        if self.unpriced[high] - self.unpriced[low]:
            return None
        return self.dollars[high] - self.dollars[low]


def rises(ledger: Ledger, account: str, kind: str, since: float, until: float,
          group: Callable[[float, float], str | None] | None = None, spending: Spending | None = None,
          observations: list[Observation] | None = None) -> list[Rise]:
    """Every rise of one account's window whose later reading is from ``since`` to ``until``, oldest first per
    instrument, the app's before the plugin's. ``spending``, where given, prices the responses in its stead — such as
    the account's use the plans covered (``plan_use``) — from a week and five hours before ``since`` on, rather than
    every response the ledger holds; ``observations``, where given, are the account's readings of the window, as
    ``Ledger.observations`` gives them, from a week before ``since`` on, read once by a caller that asks often.

    One instrument at a time: the plugin's readings and the app's samples read the figure at different moments and
    round it differently — the app's stands a point higher about half the time — so a pair of the two would count that
    difference as use. An account's plugin readings of a window are its instrument from the first of them on, its app
    samples before that. The browser extension's readings are never one, though they read the same figure, the
    account's whole use: those two instruments already divide an account's time between them, so a run of browser
    readings would measure spending one of them measures already and count it twice. Where the rule would leave a
    span unmeasured — a browser reading before the account's first plugin reading — PROJECT.md (*Decisions*) records
    what was measured and when to revisit it.

    A run is consecutive readings of one instrument inside one window; it ends where a pair fails any of:
      - the readings are at most ``CALIBRATION_MAX_GAP`` apart: further apart, use elsewhere could hide between them;
      - neither is at ``CAPPED``, where the figure stops rising with use;
      - the figure fell by less than ``DROP_POINTS`` — save in the 5-hour window between two readings naming one window
        end, which only that end resets, so there a fall of any size is a reading trailing another session's — and no
        reset lies between them by the readings' own reset times, else by the 5-hour window rule (``five_hour_end``)
        or the account's weekly anchor. A weekly fall keeps the test even where the reset time holds, since a reset
        outside the schedule leaves it as it was;
      - ``group``, where given, names something both readings share (``capacity``: the plan the bills put the account
        on), never None;
      - every response between them has a list price, since an unpriced one leaves the dollars unknown.
    Inside a run every pair counts its rise of the run's highest reading so far, a pair with no response between
    with no dollars: the run's rises sum to its highest reading less its first and its dollars to everything spent
    across it, and a reading another session took a moment earlier, a few points lower, adds nothing — nor does the
    recovery after it, which a sum of rises from one reading to the next would count once more. Each rise stands
    where it happened, so a cut through a run — a week's edge, the start of the rate's range — counts none twice. A
    run across which nothing was spent here measures nothing WindowTally can price — an idle stretch, or use elsewhere —
    and is left out whole, so it adds no chain to the measure's rounding bound either.
    """
    origin = since - WEEK   # far enough back for a 5-hour window's run of readings and for the weekly anchor
    if spending is None:
        spending = Spending(ledger.db.execute(
            "SELECT t, cost_usd FROM responses WHERE account_uuid=? AND t>=? AND t<=? ORDER BY t",
            (account, origin - FIVE_HOURS, until)).fetchall())
    every = (ledger.observations(account, kind, since=origin) if observations is None
             else [o for o in observations if o.t >= origin])
    observed = [o for o in every if o.t <= until]
    anchor = weekly_anchor(every) if kind == "seven_day" else None   # the account's schedule, from all it says
    switch = ledger.db.execute("SELECT MIN(t) FROM observations WHERE account_uuid=? AND kind=? AND source='plugin'",
                               (account, kind)).fetchone()[0]
    found: list[Rise] = []
    for source in ("app", "plugin"):
        series = [o for o in observed if o.source == source and (source == "plugin" or switch is None or o.t < switch)]
        run, highest = 0, None   # the run's highest reading so far; None between runs
        for index in range(1, len(series)):
            taken = _rise(series, index, kind, spending, anchor, group)
            if taken is None:
                highest = None
                continue
            if highest is None:
                run += 1
                highest = series[index - 1].percent
            shared, dollars = taken
            later = series[index].percent
            points, highest = max(0.0, later - highest), max(highest, later)
            if series[index].t >= since:
                found.append(Rise(source, series[index].t, points, dollars, run, shared, series[index - 1].t))
    spent: dict[tuple[str, int], float] = {}
    for r in found:
        spent[(r.source, r.run)] = spent.get((r.source, r.run), 0.0) + r.dollars
    return [r for r in found if spent[(r.source, r.run)] > 0]


def _rise(series: list[Observation], index: int, kind: str, spending: Spending, anchor: WeeklyAnchor | None,
          group: Callable[[float, float], str | None] | None) -> tuple[str, float] | None:
    """What both readings share and the dollars between them, for the pair from reading ``index - 1`` to reading
    ``index``, or None where the run ends there. The cheap tests come first: the window's end is looked up last."""
    a, b = series[index - 1], series[index]
    if not 0 < b.t - a.t <= CALIBRATION_MAX_GAP:
        return None
    if a.percent >= CAPPED or b.percent >= CAPPED:
        return None
    one_end = (kind == "five_hour" and a.resets_at is not None and b.resets_at is not None
               and abs(a.resets_at - b.resets_at) < SAME_WINDOW_END)
    if a.percent - b.percent >= DROP_POINTS and not one_end:
        return None
    shared = "" if group is None else group(a.t, b.t)
    if shared is None:
        return None
    dollars = spending.between(a.t, b.t)
    if dollars is None:
        return None
    if not _one_window(series, index, kind, spending.times, anchor):
        return None
    return shared, dollars


def _one_window(series: list[Observation], index: int, kind: str, activity: list[float],
                anchor: WeeklyAnchor | None) -> bool:
    """Whether no reset lies between readings ``index - 1`` and ``index``."""
    a, b = series[index - 1], series[index]
    length = FIVE_HOURS if kind == "five_hour" else WEEK
    if b.resets_at is not None and a.percent > 0 and b.resets_at - length > a.t:
        return False   # the later reading's window began after the earlier reading, which had use in its own
    if kind == "five_hour":
        end, _ = five_hour_end(series, activity, index - 1)
        return end is None or b.t < end
    if a.resets_at is not None:
        return b.t < a.resets_at
    return anchor is None or anchor.next_after(a.t) > b.t


def percent_per_dollar(ledger: Ledger, account: str, kind: str, now: float) -> float | None:
    """How many points of this window one API-equivalent dollar has cost lately; None without enough evidence.

    The rises of the last ``CALIBRATION_DAYS`` (``rises``), points over dollars, once their dollars reach
    ``CALIBRATION_MIN_COST``.
    """
    return rate_of(rises(ledger, account, kind, now - CALIBRATION_DAYS * 86400, now))


def rate_of(found: list[Rise]) -> float | None:
    """Points over dollars of the rises ``found``, once the dollars reach ``CALIBRATION_MIN_COST``."""
    points = sum(r.points for r in found)
    cost = sum(r.dollars for r in found)
    if cost < CALIBRATION_MIN_COST or points <= 0:
        return None
    return points / cost


def family_rates(ledger: Ledger, account: str, family: str, now: float,
                 readings: Iterable[ScopedObservation] = (), weekly: Iterable[Observation] = ()
                 ) -> tuple[float | None, float | None]:
    """How many points of the weekly window one API-equivalent dollar of one model family's use has cost lately, and one
    dollar of every other family's: each None without enough evidence. ``readings`` are claude.ai's readings of the
    family's own window, one model's, oldest first, and ``weekly`` the account's weekly observations, oldest first.

    The plan meters families unevenly against their list prices, so the weekly window's single rate
    (``percent_per_dollar``) misjudges a family whose share of the use departs from its usual one. The family's rate is
    read off its own window where claude.ai's readings measure it (``read_rate_of``): what the window rose between two
    readings is the family's part of the week exactly. Otherwise, and for every other family, the evidence is the
    weekly window's rises, a run at a time. A run whose dollars are at most ``FAMILY_FREE_SHARE`` the family's measures
    the other families: their points over their dollars, once those reach ``CALIBRATION_MIN_COST``. Every other run's
    points, less what the other families' dollars in it cost at that rate, measure the family, once its dollars reach
    the same: a remainder, which carries the other families' rate's error whole, and in which a run across which the
    family's allowance stood full, where its use no longer raised the week, counts its dollars without its points, so
    it leans low.
    """
    since = now - CALIBRATION_DAYS * 86400
    readings, weekly = list(readings), list(weekly)
    found = rises(ledger, account, "seven_day", since, now)
    if not found and not readings:
        return None, None
    # From a week before the rate's days: a reading inside them is measured from its week's start (``read_rate_of``).
    own_spending = Spending([(t, cost if model_family(model) == family else 0.0) for t, cost, model in
                             ledger.db.execute("SELECT t, cost_usd, model FROM responses WHERE account_uuid=? AND t>? "
                                               "AND t<=? ORDER BY t",
                                               (account, since - WEEK - CALIBRATION_MAX_GAP, now))])
    return family_rates_of(found, own_spending, readings, weekly, since, now)


def family_rates_of(found: list[Rise], own_spending: Spending, readings: list[ScopedObservation],
                    weekly: list[Observation], since: float, until: float) -> tuple[float | None, float | None]:
    """``family_rates`` from the weekly window's rises ``found``, the family's dollars as running sums, an unpriced
    response's None, from a week before ``since``, and claude.ai's readings of the family's window up to ``until``: the
    family's rate as read (``read_rate_of``), else as the rises leave it, and every other family's."""
    own, rest = _rates_by_rises(found, own_spending)
    read = read_rate_of(readings, own_spending, weekly, since, until)
    return (own if read is None else read), rest


def fall_spans(observations: list[Observation]) -> list[tuple[float, float]]:
    """(the observation before it, the observation that showed it) of each fall of the weekly window of ``DROP_POINTS``
    or more, by the rule ``falls_after`` reads one: the reset came after the first and by the second."""
    spans, highest, before = [], -math.inf, -math.inf
    for o in observations:
        if highest - o.percent >= DROP_POINTS:
            spans.append((before, o.t))
            highest = o.percent
        else:
            highest = max(highest, o.percent)
        before = o.t
    return spans


def read_rate_of(readings: list[ScopedObservation], own_spending: Spending, weekly: list[Observation], since: float,
                 until: float) -> float | None:
    """How many points of the weekly window one API-equivalent dollar of a model family's use cost, read off claude.ai's
    readings of the family's own window: None without enough evidence.

    ``readings`` are one model's, oldest first; ``own_spending`` the family's dollars as running sums, an unpriced
    response's None, from a week before ``since``; ``weekly`` the account's weekly observations, oldest first. Each
    reading from ``since`` to ``until`` is measured from the reading before it in the same week: the points its window
    rose, over its allowance, are the family's part of the week, and the dollars the family's responses between the
    two. A week's first reading is measured from the week's start, where the window stood empty, once the window was
    read in a week before and the weekly window observed by the week's start: both then show the account's use was
    recorded from that start on. Otherwise it only sets the level the next is measured from. A reading names its week
    by its reset time; one without, or within ``WINDOW_START_MARGIN`` of its week's start, where it may still show the
    week before, is passed over. A pair measures nothing, and the next is measured from its later reading, where:
      - no reading has yet said the allowance;
      - either level is at ``CAPPED``, where the window stops rising with use;
      - the window fell by ``DROP_POINTS`` or more, or the weekly window did while the pair ran (``fall_spans``): a
        reset of the allowance, or one that may have touched it, so the rise is not the whole of the use;
      - a response of the family between them has no list price, or the family spent nothing here between them: an
        idle stretch, or its use elsewhere — in chat, on another machine — which WindowTally cannot price.
    Short of a fall the next is measured from the higher of the two, so a lower reading adds nothing. The rate is the
    points over the dollars once the dollars reach ``CALIBRATION_MIN_COST``. Readings come only while claude.ai is
    open, so no bound is set on the time between two: the family's use elsewhere beside its use here raises the rate,
    as it raises the weekly window's.
    """
    points = dollars = 0.0
    allowance = None
    start: tuple[float, float, float] | None = None   # (when, level, the week's end) the next reading is measured from
    falls: list[tuple[float, float]] = []             # the weekly window's falls in that week (``fall_spans``)
    for r in readings:
        if r.t > until:
            break
        if r.allowance is not None:
            allowance = r.allowance
        if r.resets_at is None:
            start = None
            continue
        week_start = r.resets_at - WEEK
        if r.t < week_start + WINDOW_START_MARGIN:
            continue
        if start is None or abs(start[2] - r.resets_at) >= WEEK / 2:
            # The week's own observations, as ``_window_members`` takes them: one handed on late from the week before
            # would read as a fall at the week's start.
            falls = fall_spans([o for o in weekly if week_start + WINDOW_START_MARGIN <= o.t < r.resets_at
                                and (o.resets_at is None or abs(o.resets_at - r.resets_at) < WEEK / 2)])
            if start is None or not weekly or weekly[0].t > week_start:
                start = (r.t, r.percent, r.resets_at)
                continue
            start = (week_start, 0.0, r.resets_at)
        opened, level, _ = start
        fell = level - r.percent >= DROP_POINTS or any(before < r.t and shown > opened for before, shown in falls)
        start = (r.t, r.percent if fell else max(level, r.percent), r.resets_at)
        spent = own_spending.between(opened, r.t)
        if fell or not allowance or not spent or level >= CAPPED or r.percent >= CAPPED:
            continue
        if r.t >= since:
            points += max(0.0, r.percent - level) * allowance / 100.0
            dollars += spent
    if dollars < CALIBRATION_MIN_COST or points <= 0:
        return None
    return points / dollars


def _rates_by_rises(found: list[Rise], own_spending: Spending) -> tuple[float | None, float | None]:
    """A family's rate and every other family's by the weekly window's rises ``found`` alone (``family_rates``), the
    family's dollars as running sums from the first rise's start on: the family's is what its runs leave."""
    if not found:
        return None, None
    runs: dict[tuple[str, int], list[float]] = {}
    for r in found:
        run = runs.setdefault((r.source, r.run), [0.0, 0.0, 0.0])   # points, dollars, the family's dollars
        run[0] += r.points
        run[1] += r.dollars
        run[2] += own_spending.between(r.start, r.t) or 0.0
    rest_points = rest_dollars = mixed_points = mixed_rest = mixed_own = 0.0
    for points, dollars, own in runs.values():
        if own <= FAMILY_FREE_SHARE * dollars:
            rest_points, rest_dollars = rest_points + points, rest_dollars + dollars - own
        else:
            mixed_points, mixed_rest, mixed_own = mixed_points + points, mixed_rest + dollars - own, mixed_own + own
    if rest_dollars < CALIBRATION_MIN_COST or rest_points <= 0:
        return None, None
    rest = rest_points / rest_dollars
    left = mixed_points - rest * mixed_rest
    return (left / mixed_own if mixed_own >= CALIBRATION_MIN_COST and left > 0 else None), rest


@dataclass(frozen=True)
class Plateau:
    """A part of a window's pace that stops once ``headroom`` points of the window have been used: a model's use, whose
    allowance inside the weekly window fills before the window does (``projection_plateaus``)."""

    share: float      # the part of the pace, 0 to 1
    headroom: float   # points of the window the part may still add


def exhausts_at(observations: list[Observation], now: float, plateaus: Iterable[Plateau] = ()) -> float | None:
    """When the window reaches 100 % at its recent pace, if it is being used right now. ``observations`` are the
    window's own; each counts at the highest figure read up to it, so a trailing reading neither slows the pace nor
    hastens it. Each of ``plateaus`` stops its share of the pace once its headroom is used, so a window rising on one
    model's use alone is not projected past where that model's allowance stops it."""
    if not observations:
        return None
    levels = list(accumulate((o.percent for o in observations), max))
    latest_t, level = observations[-1].t, levels[-1]
    if now - latest_t > PROJECTION_FRESHNESS or level >= 100:
        return None
    first = next(i for i, o in enumerate(observations) if o.t >= latest_t - PROJECTION_LOOKBACK)
    span = latest_t - observations[first].t
    if span < PROJECTION_MIN_SPAN or level <= levels[first]:
        return None
    pace = (level - levels[first]) / span
    after = _seconds_to_fill(100.0 - level, pace, plateaus)
    return None if after is None else latest_t + after


def _seconds_to_fill(points: float, pace: float, plateaus: Iterable[Plateau]) -> float | None:
    """Seconds until ``points`` more are used at ``pace`` points a second, each plateau's share of the pace stopping
    once its headroom is used; None where the pace stops first."""
    plateaus = list(plateaus)
    parts = [(pace * p.share, p.headroom) for p in plateaus if p.share > 0 and p.headroom > 0]
    rest = max(0.0, pace - sum(pace * p.share for p in plateaus if p.share > 0))
    elapsed = 0.0
    while True:
        speed = rest + sum(part for part, _ in parts)
        if speed <= 0:
            return None
        step = min((headroom / part for part, headroom in parts), default=math.inf)
        if points <= speed * step:
            return elapsed + points / speed
        points -= speed * step
        elapsed += step
        parts = [(part, headroom - part * step) for part, headroom in parts if headroom - part * step > 1e-9]


# --- window standings -----------------------------------------------------------------------------------------

def _estimate(base: float, rate: float | None, ledger: Ledger, account: str, start: float, now: float) -> tuple[float, bool]:
    """``base`` plus the estimated rise since ``start``; flagged when a rise was added."""
    if rate is None:
        return base, False
    spent = ledger.cost_between(account, start, now)
    if spent <= 0:
        return base, False
    return min(100.0, base + rate * spent), True


def _window_members(observations: list[Observation], start: float, end: float, same_end: float) -> list[Observation]:
    """The observations, oldest first, that read the window running from ``start`` to ``end``: each taken after its
    start, by ``WINDOW_START_MARGIN``, whose reset time, where it carries one, is ``end`` within ``same_end`` — so a
    reading of an earlier window handed on late is not taken for this one's. The latest observation is the one the
    window was found from, and always among them."""
    members = [o for o in observations[:-1] if o.t >= start + WINDOW_START_MARGIN
               and (o.resets_at is None or abs(o.resets_at - end) < same_end)]
    return members + [observations[-1]]


def _since_last_fall(members: list[Observation]) -> list[Observation]:
    """The members from the last that stands ``DROP_POINTS`` or more below the highest read since the reset before
    it: such a fall is a reset no schedule showed, and what was read before it belongs to the window it ended."""
    start, highest = 0, -math.inf
    for i, o in enumerate(members):
        if highest - o.percent >= DROP_POINTS:
            start, highest = i, o.percent
        else:
            highest = max(highest, o.percent)
    return members[start:]


def _peak(members: list[Observation]) -> Observation:
    """The member carrying the window's highest figure, the latest of equals. Use only raises a window's figure,
    so a lower one read after it trails another session's reading or rounds the same use down, and says less; the
    highest still holds at the latest observation, from which an estimate adds what was spent since."""
    return max(reversed(members), key=lambda o: o.percent)


def _run_start(observations: list[Observation], index: int) -> int:
    """The first observation of the 5-hour window that observation ``index`` belongs to, as far as the samples tell:
    walking back while the percentage stays non-zero, does not fall, and no gap exceeds five hours."""
    while index > 0:
        before, current = observations[index - 1], observations[index]
        if before.percent <= 0 or before.percent - current.percent >= DROP_POINTS or current.t - before.t > FIVE_HOURS:
            break
        index -= 1
    return index


def _last_window_start(activity: list[float], after: float | None) -> float | None:
    """Where the latest 5-hour window began if every message after ``after`` opened a new window whenever the
    previous one had ended — the window rule applied to the response times alone."""
    opened = None
    for t in activity:
        if after is not None and t <= after:
            continue
        if opened is None or t >= opened + FIVE_HOURS:
            opened = t
    return opened


def five_hour_end(observations: list[Observation], activity: list[float],
                  index: int | None = None) -> tuple[float | None, bool]:
    """The end of the window observation ``index`` belongs to — the latest by default — and whether that end is
    estimated; None where that observation is at zero and no reading names its window's end.

    A reading's own reset time is exact. Without one, the window began at the first activity after the previous
    observation outside the current run of non-falling, non-zero percentages — or at the run's first observation
    when no activity is recorded — and ends five hours later. ``activity`` is oldest first.
    """
    index = len(observations) - 1 if index is None else index
    latest = observations[index]
    if latest.resets_at is not None:
        return latest.resets_at, False
    for back in range(index, -1, -1):
        o = observations[back]
        if o.t < latest.t - FIVE_HOURS:
            break
        if o.resets_at is not None and o.resets_at > latest.t:
            return o.resets_at, False
    if latest.percent <= 0:
        return None, False
    run_start = _run_start(observations, index)
    first = observations[run_start]
    earliest = observations[run_start - 1].t if run_start > 0 else first.t - FIVE_HOURS
    earliest = max(earliest, latest.t - FIVE_HOURS)
    after = bisect_right(activity, earliest)
    started = activity[after] if after < len(activity) and activity[after] <= first.t else first.t
    return started + FIVE_HOURS, True


def five_hour_removed(ledger: Ledger, account: str) -> float | None:
    """The latest reading on which the account's 5-hour limit stands removed, or None while it holds.

    A reading's windows are the observations it wrote at one moment (``source``, ``ref``, ``t``), and Claude Code, the
    browser extension and the desktop app each leave out a window the server did not send. So the limit is removed
    once the readings since the account's last 5-hour figure carry its weekly window alone, at least two of them and
    ``NO_LIMIT_SPAN`` apart, and holds again from the next reading that carries a 5-hour figure. One such reading is
    not enough: Claude Code hands on a reading with the weekly window alone, once and only for a moment, where a
    5-hour window has just ended (measured on the development machine, 2026-10), the next reading carrying the
    5-hour window again within minutes.
    """
    last = ledger.db.execute("SELECT MAX(t) FROM observations WHERE account_uuid=? AND kind='five_hour'",
                             (account,)).fetchone()[0]
    first_after, latest_after, readings = ledger.db.execute(
        "SELECT MIN(t), MAX(t), COUNT(DISTINCT source || '|' || ref || '|' || t) FROM observations "
        "WHERE account_uuid=? AND kind='seven_day' AND t>?", (account, -math.inf if last is None else last)).fetchone()
    if readings < 2 or latest_after - first_after < NO_LIMIT_SPAN:
        return None
    return latest_after


def no_limit_standing(as_of: float) -> WindowStanding:
    """The 5-hour window of an account whose limit was removed: no figure and no reset, as of the reading that says
    so."""
    return WindowStanding("five_hour", "no_limit", None, None, as_of, False)


def five_hour_standing(observations: list[Observation], activity: list[float], now: float,
                       rate: float | None = None, ledger: Ledger | None = None,
                       account: str | None = None) -> WindowStanding:
    """The 5-hour window at ``now``. ``activity`` is the account's response times, oldest first."""
    if not observations:
        opened = _last_window_start(activity, None)
        if opened is not None and now < opened + FIVE_HOURS:
            return WindowStanding("five_hour", "running", None, opened + FIVE_HOURS, None, True)
        return WindowStanding("five_hour", "unknown", None, None, None, False)
    latest = observations[-1]
    end, estimated = five_hour_end(observations, activity)
    if end is not None and now < end:
        # Only the window's end resets it, so no fall among the readings of it is a reset.
        members = _window_members(observations, end - FIVE_HOURS, end, SAME_WINDOW_END)
        peak = _peak(members)
        percent, added = peak.percent, False
        if ledger is not None and account is not None:
            percent, added = _estimate(peak.percent, rate, ledger, account, latest.t, now)
        projected = exhausts_at(members, now)
        return WindowStanding("five_hour", "running", percent, end, latest.t, estimated or added,
                              projected if projected is not None and projected < end else None,
                              reset_exact=not estimated)
    # The observed window is over (or none was running): every later message opened a window of its own.
    opened = _last_window_start(activity, end if end is not None else latest.t)
    if opened is not None and now < opened + FIVE_HOURS:
        percent = None
        if ledger is not None and account is not None and rate is not None:
            percent, _ = _estimate(0.0, rate, ledger, account, opened, now)
        return WindowStanding("five_hour", "running", percent, opened + FIVE_HOURS, latest.t, True)
    return WindowStanding("five_hour", "not_started", 0.0, None, latest.t, False)


def weekly_standing(observations: list[Observation], anchor: WeeklyAnchor | None, now: float,
                    rate: float | None = None, ledger: Ledger | None = None,
                    account: str | None = None, plateaus: Iterable[Plateau] = ()) -> WindowStanding:
    """The weekly window at ``now``, rolled forward from the latest observation through the reset schedule;
    ``plateaus`` as ``exhausts_at`` takes them."""
    if not observations:
        resets_at = anchor.next_after(now) if anchor else None
        return WindowStanding("seven_day", "unknown", None, resets_at, None, anchor is not None and not anchor.exact,
                              reset_exact=anchor is not None and anchor.exact)
    latest = observations[-1]
    if latest.resets_at is not None:
        reset_after_latest, schedule_estimated = latest.resets_at, False
    elif anchor is not None:
        reset_after_latest, schedule_estimated = anchor.next_after(latest.t), not anchor.exact
    else:
        reset_after_latest, schedule_estimated = None, False
    if reset_after_latest is None or now < reset_after_latest:
        # With no reset time to bound the week, where it began is unknown: the latest observation stands alone.
        members = ([latest] if reset_after_latest is None else
                   _since_last_fall(_window_members(observations, reset_after_latest - WEEK, reset_after_latest,
                                                    WEEK / 2)))
        peak = _peak(members)
        percent, added = peak.percent, False
        if ledger is not None and account is not None:
            percent, added = _estimate(peak.percent, rate, ledger, account, latest.t, now)
        projected = exhausts_at(members, now, plateaus)
        if projected is not None and reset_after_latest is not None and projected >= reset_after_latest:
            projected = None
        return WindowStanding("seven_day", "current", percent, reset_after_latest, latest.t,
                              schedule_estimated or added, projected,
                              reset_exact=reset_after_latest is not None and not schedule_estimated)
    # One or more resets happened since the latest observation.
    weeks_passed = math.floor((now - reset_after_latest) / WEEK)
    last_reset = reset_after_latest + weeks_passed * WEEK
    percent, added = 0.0, False
    if ledger is not None and account is not None:
        percent, added = _estimate(0.0, rate, ledger, account, last_reset, now)
    return WindowStanding("seven_day", "current", percent, last_reset + WEEK, latest.t, schedule_estimated or added,
                          reset_exact=not schedule_estimated)


# --- per-model weekly windows -------------------------------------------------------------------------------------

def family_cost(ledger: Ledger, account: str, name: str, start: float, end: float) -> float:
    """API-equivalent USD of the account's responses in (start, end] of the model family a per-model window's name
    names (``pricing.family_named``); nothing for a name that names no family, and an unpriced response adds nothing."""
    family = family_named(name)
    if family is None:
        return 0.0
    rows = ledger.db.execute("SELECT model, COALESCE(SUM(cost_usd), 0) FROM responses "
                             "WHERE account_uuid=? AND t>? AND t<=? GROUP BY model", (account, start, end))
    return sum(cost for model, cost in rows if model_family(model) == family)


def falls_after(observations: list[Observation], since: float) -> list[tuple[float, float, float]]:
    """Each fall of the weekly window of ``DROP_POINTS`` or more read after ``since``, as (when it was read, the highest
    read before it, the figure after it): the rule ``_since_last_fall`` reads a reset by."""
    falls, highest = [], -math.inf
    for o in observations:
        if highest - o.percent >= DROP_POINTS:
            if o.t > since:
                falls.append((o.t, highest, o.percent))
            highest = o.percent
        else:
            highest = max(highest, o.percent)
    return falls


def share_tolerance(share: float) -> float:
    """How far a fall of the weekly window may stand from a model's ``share`` of it and still give that share back:
    ``DROP_POINTS``, or ``SHARE_TOLERANCE`` of the share for a large one, the model's figure being estimated."""
    return max(DROP_POINTS, SHARE_TOLERANCE * share)


def gives_back(fall: float, share: float) -> bool:
    """Whether a fall of the weekly window by ``fall`` points gave back a model's ``share`` of it
    (``share_tolerance``)."""
    return abs(fall - share) <= share_tolerance(share)


def weekly_levels(observations: list[Observation]) -> list[tuple[float, float]]:
    """(when, the weekly window's figure) at each observation, oldest first: the highest read since the last fall of
    ``DROP_POINTS`` or more, the rule ``falls_after`` and ``_since_last_fall`` read the window by."""
    levels, highest = [], -math.inf
    for o in observations:
        highest = o.percent if highest - o.percent >= DROP_POINTS else max(highest, o.percent)
        levels.append((o.t, highest))
    return levels


def _share(own: float, rest: float, own_rate: float | None, rest_rate: float | None) -> float:
    """A model's part of what ``own`` dollars of its use and ``rest`` dollars of every other model's took of the weekly
    window together: each at its own points per dollar, or, without both rates, at one rate for all."""
    if own <= 0:
        return 0.0
    if own_rate and rest_rate:
        own, rest = own * own_rate, rest * rest_rate
    return own / (own + max(0.0, rest))


@dataclass(frozen=True)
class FallVerdict:
    """What a fall of the weekly window did to a model's allowance (``ScopedCarry.through``)."""

    kind: str                   # model: it gave back the model's share, a reset of its allowance · other: the model
                                # held too little of the week for the fall to be its own · unknown: its effect on the
                                # model is not known
    share: float | None         # the weekly points the model held just before it; None where its allowance is unsaid


class ScopedCarry:
    """One model's window carried forward between two moments, by the rule its live figure is carried by
    (``scoped_standings``): what its use took of its allowance is its part of the weekly window's rise between the
    weekly readings ``levels`` gives — (when, the figure) as ``weekly_levels`` reads it, oldest first — shared with
    every other model's by what each spent between those two readings at its own points per dollar (``_share``), and
    its spend outside them at ``alone_rate``. ``model`` and ``total`` give the API-equivalent dollars of the model's
    responses and of every response in (start, end]; ``allowance`` is the model's share of the weekly window, in
    percent, None where claude.ai did not say it."""

    def __init__(self, levels: list[tuple[float, float]], model: Callable[[float, float], float],
                 total: Callable[[float, float], float], allowance: float | None, own_rate: float | None,
                 rest_rate: float | None, alone_rate: float | None):
        self.levels, self.times = levels, [t for t, _ in levels]
        self.model, self.total, self.allowance = model, total, allowance
        self.own_rate, self.rest_rate, self.alone_rate = own_rate, rest_rate, alone_rate

    def at_rate(self, start: float, end: float) -> float:
        """Points of the model's allowance its spend in (start, end] took at its own points per dollar."""
        if self.alone_rate is None or end <= start:
            return 0.0
        return self.alone_rate * self.model(start, end) * 100.0 / self.allowance

    def took(self, start: float, stop: float, upto: Callable[[list[float], float], int]) -> float:
        """Points of the model's allowance its use from ``start`` to ``stop`` took: its part of the weekly window's
        rise between the first weekly reading at or after ``start`` and the last that ``upto`` keeps before ``stop``,
        over the dollars spent between those two readings, and its spend outside them at its own rate."""
        if not self.allowance:
            return 0.0
        first, last = bisect_left(self.times, start), upto(self.times, stop) - 1
        if last <= first:
            return self.at_rate(start, stop)
        (opened, base), (closed, top) = self.levels[first], self.levels[last]
        own = self.model(opened, closed)
        rest = self.total(opened, closed) - own
        part = max(0.0, top - base) * _share(own, rest, self.own_rate, self.rest_rate) * 100.0 / self.allowance
        return self.at_rate(start, opened) + part + self.at_rate(closed, stop)

    def through(self, level: float, since: float, falls: Iterable[tuple[float, float, float]]
                ) -> tuple[float | None, float, bool, tuple[FallVerdict, ...]]:
        """The model's level, of its allowance, carried from ``level`` at ``since`` through each of ``falls`` —
        (when it was read, the highest read before it, the figure after it), oldest first, each after ``since`` — and
        what each did to it: the level after the last, None from the first whose effect on it is not known, where the
        walk stops; the moment the level stands from; whether a reset of the allowance was inferred; and each fall's
        verdict. A fall that gives back about the model's share of the week is a reset of its allowance, which starts
        again from nothing; one while the model held under ``DROP_POINTS`` of the week is not its own, the level
        standing at what the model held."""
        verdicts, inferred = [], False
        for when, before, after in falls:
            # The readings before the fall's own: the last of them read the ``before`` the fall is measured from.
            held = min(100.0, level + self.took(since, when, bisect_left))
            share = None if self.allowance is None else held * self.allowance / 100.0
            if held <= 0 or (share is not None and share < DROP_POINTS):
                level, since = held, when
                verdicts.append(FallVerdict("other", share))
                continue
            if share is None or not gives_back(before - after, share):
                verdicts.append(FallVerdict("unknown", share))
                return None, since, inferred, tuple(verdicts)
            level, since, inferred = 0.0, when, True
            verdicts.append(FallVerdict("model", share))
        return level, since, inferred, tuple(verdicts)


def _scoped_window(ledger: Ledger, account: str, readings: list[ScopedObservation], weekly: list[Observation],
                   rate: float | None, now: float) -> ScopedStanding:
    """One model's window at ``now``, carried forward from its latest reading (``scoped_standings``)."""
    latest = readings[-1]
    allowance = next((r.allowance for r in reversed(readings) if r.allowance is not None), None)
    # A reading without a reset time resets with the week: the weekly window's next reset as a reading names it.
    resets_at = latest.resets_at if latest.resets_at is not None else next(
        (o.resets_at for o in weekly if o.resets_at is not None and o.resets_at > latest.t), None)
    level, since, inferred = latest.percent, latest.t, False
    # The week the window is in, up to ``now``; with no reset time known at all, the week since its reading.
    levels: list[tuple[float, float]] = []
    if resets_at is not None and now >= resets_at:
        # Its scheduled reset passed: the window starts again from nothing, as the weekly window does from nought.
        since = resets_at + math.floor((now - resets_at) / WEEK) * WEEK
        level, resets_at, levels = 0.0, since + WEEK, [(since, 0.0)]
    week = [o for o in weekly if o.t <= now and
            (latest.t - WEEK < o.t if resets_at is None else resets_at - WEEK < o.t < resets_at)]
    levels += weekly_levels(week)
    family = family_named(latest.name)
    own_rate, rest_rate = family_rates(ledger, account, family, now, readings, weekly) if family else (None, None)
    carry = ScopedCarry(levels, lambda start, end: family_cost(ledger, account, latest.name, start, end),
                        lambda start, end: ledger.cost_between(account, start, end), allowance, own_rate, rest_rate,
                        rate if own_rate is None else own_rate)
    level, since, inferred, _verdicts = carry.through(level, since, falls_after(week, since))
    if level is None:
        # A reset whose effect on the model's allowance is not known: unknown until claude.ai is read again.
        return ScopedStanding(latest.name, "unknown", None, resets_at, latest.t, False, allowance, own_rate, rest_rate)
    added = carry.took(since, now, bisect_right)
    return ScopedStanding(latest.name, "current", min(100.0, level + added), resets_at, latest.t,
                          inferred or added > 0, allowance, own_rate, rest_rate)


def scoped_standings(ledger: Ledger, account: str, weekly: list[Observation], rate: float | None,
                     now: float) -> tuple[ScopedStanding, ...]:
    """The account's per-model weekly windows at ``now``, by name, each read in the last ``HISTORY_WEEKS`` weeks and
    shown only where some reading of it stood above nothing: an account that has not used the model has none to show.
    ``weekly`` is the account's weekly observations, oldest first, and ``rate`` its weekly window's points a dollar."""
    readings: dict[str, list[ScopedObservation]] = {}
    for r in ledger.scoped_observations(account, since=now - HISTORY_WEEKS * WEEK):
        if r.t <= now:
            readings.setdefault(r.name, []).append(r)
    return tuple(_scoped_window(ledger, account, rows, weekly, rate, now)
                 for name, rows in sorted(readings.items()) if any(r.percent > 0 for r in rows))


def projection_plateaus(ledger: Ledger, account: str, weekly: list[Observation], scoped: Iterable[ScopedStanding],
                        rate: float | None, now: float) -> list[Plateau]:
    """What stops part of the weekly window's recent pace: each model whose window is current and names its
    allowance, with the model's part of what the use over the projection's span took of the week — its cost and every
    other model's, each at the points per dollar its window carries as measured (``_share``) — and the weekly points
    its allowance had left at the latest weekly observation, where the projection starts: its room at ``now`` and the
    weekly points its use since then took at its rate, or at ``rate`` where none was measured. Past its allowance the
    model goes on at usage credits, outside the plan, so its use stops raising the weekly window."""
    if not weekly:
        return []
    end = weekly[-1].t
    start = end - PROJECTION_LOOKBACK
    total = ledger.cost_between(account, start, end)
    if total <= 0:
        return []
    plateaus = []
    for s in scoped:
        if s.state != "current" or s.percent is None or not s.allowance:
            continue
        alone_rate = rate if s.rate is None else s.rate
        since = (0.0 if alone_rate is None or now <= end else
                 alone_rate * family_cost(ledger, account, s.name, end, now))
        headroom = min(s.allowance, (100.0 - s.percent) * s.allowance / 100.0 + since)
        own = family_cost(ledger, account, s.name, start, end)
        plateaus.append(Plateau(_share(own, total - own, s.rate, s.rest_rate), headroom))
    return plateaus


def account_standing(ledger: Ledger, account: Account, now: float, *, desktop_uuid: str | None = None,
                     cli_uuid: str | None = None) -> AccountStanding:
    weekly_observations = ledger.observations(account.uuid, "seven_day", since=now - HISTORY_WEEKS * WEEK)
    five_hour_observations = ledger.observations(account.uuid, "five_hour", since=now - 2 * WEEK)
    anchor = weekly_anchor(weekly_observations)
    # Activity from five hours before the latest observation — the start of the window it is in — or, with no
    # observation, from a day back, enough to chain the windows of continuous use.
    reference = five_hour_observations[-1].t if five_hour_observations else now - 86400
    since = min(reference, now) - FIVE_HOURS - 1
    activity = ledger.response_times(account.uuid, since=since)
    last = ledger.db.execute("SELECT MAX(t) FROM responses WHERE account_uuid=?", (account.uuid,)).fetchone()[0]
    # Without a 5-hour limit nothing is inferred for the window: the window rule applied to the response times would
    # open windows the account no longer has and estimate a rise of each.
    removed = five_hour_removed(ledger, account.uuid)
    weekly_rate = percent_per_dollar(ledger, account.uuid, "seven_day", now)
    scoped = scoped_standings(ledger, account.uuid, weekly_observations, weekly_rate, now)
    return AccountStanding(
        account=account,
        five_hour=(no_limit_standing(removed) if removed is not None else
                   five_hour_standing(five_hour_observations, activity, now,
                                      percent_per_dollar(ledger, account.uuid, "five_hour", now), ledger,
                                      account.uuid)),
        weekly=weekly_standing(weekly_observations, anchor, now, weekly_rate, ledger, account.uuid,
                               projection_plateaus(ledger, account.uuid, weekly_observations, scoped, weekly_rate,
                                                   now)),
        anchor=anchor,
        scoped=scoped,
        last_activity=last,
        is_desktop=account.uuid == desktop_uuid,
        is_cli=account.uuid == cli_uuid,
    )


def standings(ledger: Ledger, accounts: Iterable[Account], now: float, *, desktop_uuid: str | None = None,
              cli_uuid: str | None = None) -> list[AccountStanding]:
    """Each account's standing, by name as WindowTally orders names (``accounts.arranged`` with no order given)."""
    return [account_standing(ledger, a, now, desktop_uuid=desktop_uuid, cli_uuid=cli_uuid)
            for a in arranged(accounts, (), lambda a: a.uuid, lambda a: a.label)]


# --- the recommendation ---------------------------------------------------------------------------------------

def _under(s: AccountStanding, weekly_ceiling: float, five_hour_ceiling: float) -> bool:
    """Whether the account stands below both ceilings. An account with no 5-hour limit is judged by its week alone:
    its 5-hour window is never running (``no_limit_standing``)."""
    weekly_ok = s.weekly.percent is None or s.weekly.percent < weekly_ceiling
    five_hour_ok = not (s.five_hour.state == "running" and (s.five_hour.percent or 0.0) >= five_hour_ceiling)
    return weekly_ok and five_hour_ok


def _when(epoch: float) -> str:
    return local_datetime(epoch).strftime("%a %H:%M")


def _first_relief(all_standings: list[AccountStanding], weekly_ceiling: float) -> tuple[float, bool] | None:
    """The earliest reset that frees an account, with whether that reset time is exact, marked ≈ as the windows are:
    its weekly window's where that stands at ``weekly_ceiling`` or more, otherwise its 5-hour window's — which an
    account with no 5-hour limit does not have, its window carrying no reset time (``no_limit_standing``)."""
    moments: list[tuple[float, bool]] = []
    for s in all_standings:
        weekly_held = s.weekly.percent is not None and s.weekly.percent >= weekly_ceiling
        if weekly_held and s.weekly.resets_at is not None:
            moments.append((s.weekly.resets_at, bool(s.anchor and s.anchor.exact)))
        elif not weekly_held and s.five_hour.resets_at is not None:
            moments.append((s.five_hour.resets_at, s.five_hour.reset_exact))
    return min(moments, key=lambda moment: moment[0], default=None)


def _awaiting_relief(all_standings: list[AccountStanding], account_uuid: str | None, sentence: str, moment: str,
                     weekly_ceiling: float) -> Recommendation:
    """``sentence``, and ``moment`` with the time of ``_first_relief`` at ``weekly_ceiling`` where there is one."""
    relief = _first_relief(all_standings, weekly_ceiling)
    if relief is None:
        return Recommendation(account_uuid, sentence, None)
    relief_at, exact = relief
    reason = f"{sentence} {moment} {'' if exact else '≈'}{_when(relief_at)}."
    return Recommendation(account_uuid, reason, relief_at, exact)


def recommend(all_standings: list[AccountStanding], excluded: Collection[str] = frozenset()) -> Recommendation:
    """Of the accounts with room left, the one whose weekly window resets first: its remaining allowance is the
    first to expire, so spending it first wastes least. With none under the ceilings, the account not blocked with
    the most of its week left, an account with no weekly figure last, and when room returns. Only with every account
    blocked is none recommended, and then the moment is when the first opens.

    An account in ``excluded`` (by UUID) is not weighed at all, neither recommended nor waited on: one the user hid,
    or one whose bills record a plan that has ended, whose weekly figure, rolled forward through its resets with no
    reading since, would stand at nothing and read as room left. With every account excluded none is recommended and
    nothing is waited on."""
    if not all_standings:
        return Recommendation(None, "No account is known yet.", None)
    weighed = [s for s in all_standings if s.account.uuid not in excluded]
    if not weighed:
        return Recommendation(None, "No account is left to recommend: every account is hidden or its plan has ended.",
                              None)
    return _recommend(weighed)


def _recommend(all_standings: list[AccountStanding]) -> Recommendation:
    """``recommend`` over the accounts it weighs, at least one."""
    usable = [s for s in all_standings if _under(s, RECOMMEND_WEEKLY_CEILING, RECOMMEND_FIVE_HOUR_CEILING)]
    if usable:
        choice = min(usable, key=lambda s: (s.weekly.resets_at if s.weekly.resets_at is not None else math.inf,
                                            s.weekly.percent if s.weekly.percent is not None else 0.0))
        if choice.weekly.resets_at is not None:
            # The reset time is approximate only when the weekly schedule was inferred; an estimated rise of the
            # figure leaves a reading's exact reset time exact.
            approx = "" if choice.anchor and choice.anchor.exact else "≈"
            reason = f"{choice.account.label} — room left, week resets first ({approx}{_when(choice.weekly.resets_at)})."
        else:
            reason = f"{choice.account.label} — room left."
        return Recommendation(choice.account.uuid, reason, None)
    unblocked = [s for s in all_standings if _under(s, CAPPED, CAPPED)]
    if unblocked:
        choice = min(unblocked, key=lambda s: (s.weekly.percent is None, s.weekly.percent or 0.0,
                                               s.weekly.resets_at if s.weekly.resets_at is not None else math.inf))
        return _awaiting_relief(all_standings, choice.account.uuid,
                                f"Every account is at or near its limit. {choice.account.label} has the most left.",
                                "Room returns", RECOMMEND_WEEKLY_CEILING)
    return _awaiting_relief(all_standings, None, "Every account is at its limit.", "The first opens", CAPPED)


# --- blocked time ---------------------------------------------------------------------------------------------

def merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The spans joined where they meet or overlap, oldest first; an empty one left out."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(s for s in spans if s[1] > s[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _intersect(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        start, end = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if start < end:
            result.append((start, end))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return result


def blocked_spans_of(observations: list[Observation], kind: str, anchor: WeeklyAnchor | None,
                     until: float) -> list[tuple[float, float]]:
    """When this window was exhausted: from each observation at or above ``CAPPED`` until the window reset —
    its reading's reset time, the weekly schedule, or the next observation below the cap, whichever comes first."""
    spans = []
    ordered = sorted(observations, key=lambda o: o.t)
    below: list[float | None] = [None] * len(ordered)   # when the first observation after each stood below the cap
    upcoming = None
    for index in range(len(ordered) - 1, -1, -1):
        below[index] = upcoming
        if ordered[index].percent < CAPPED:
            upcoming = ordered[index].t
    for index, o in enumerate(ordered):
        if o.percent < CAPPED:
            continue
        ends = [until]
        if o.resets_at is not None:
            ends.append(o.resets_at)
        elif kind == "seven_day" and anchor is not None:
            ends.append(anchor.next_after(o.t))
        elif kind == "five_hour":
            # The window began no later than the first sample of its run, so it ended within five hours of that.
            ends.append(ordered[_run_start(ordered, index)].t + FIVE_HOURS)
        if below[index] is not None:
            ends.append(below[index])
        spans.append((o.t, min(ends)))
    return merge_spans(spans)


def coverage_start(ledger: Ledger) -> float | None:
    """The first observation of any account: before it the ledger knows nothing about the windows."""
    return ledger.db.execute("SELECT MIN(t) FROM observations WHERE account_uuid IS NOT NULL").fetchone()[0]


def all_blocked_spans(ledger: Ledger, accounts: Iterable[Account], start: float, end: float) -> list[tuple[float, float]]:
    """Spans in [start, end) when no account could be used: each was blocked, or did not exist yet.

    Only the covered period counts: before the first observation of any account nothing is known, and that time
    is left out rather than counted either way. Within it, an account exists from its own first observation;
    before that it offered no capacity, which counts as blocked, so adding an account never rewrites the history
    before it.
    """
    covered = coverage_start(ledger)
    if covered is None:
        return []
    start = max(start, covered)
    if start >= end:
        return []
    per_account = []
    for account in accounts:
        first_seen = ledger.db.execute("SELECT MIN(t) FROM observations WHERE account_uuid=?",
                                       (account.uuid,)).fetchone()[0]
        if first_seen is None or first_seen >= end:
            continue
        weekly = ledger.observations(account.uuid, "seven_day", since=start - WEEK)
        five_hour = ledger.observations(account.uuid, "five_hour", since=start - FIVE_HOURS)
        anchor = weekly_anchor(weekly)
        spans = merge_spans(blocked_spans_of(weekly, "seven_day", anchor, end)
                            + blocked_spans_of(five_hour, "five_hour", anchor, end)
                            + [(start, first_seen)])
        per_account.append([(max(a, start), min(b, end)) for a, b in spans if b > start and a < end])
    if not per_account:
        return []
    result = per_account[0]
    for spans in per_account[1:]:
        result = _intersect(result, spans)
    return result
