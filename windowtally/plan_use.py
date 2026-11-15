"""What the plans covered of the API-equivalent use, and the weekly window's resets outside its schedule.

The history sets the API-equivalent use beside the plans' cost at list price, as a multiple of it (``history``,
``billing.month_totals_text``). Two parts of the use would make that multiple say more than the plans gave, and this
module finds both, response by response, from the readings alone:

    outside the plans   use paid at extra usage. A response made while the account's weekly or 5-hour window stood
                        exhausted (``limits.blocked_spans_of``), when the plan refuses and only extra usage answers;
                        and a response of a model that has an allowance of its own inside the weekly window, as Fable
                        has from claude.ai's first reading of it (below), made while that allowance stood full, past
                        which the model goes on at usage credits. The allowance's level is a claude.ai reading of it,
                        or nothing at its week's start, carried forward to the moment just before the response by the
                        rule the live figure is carried by
                        (``limits.ScopedCarry``), through every reset read by then — the weekly reading the response
                        itself brought among them, since a fall it shows came before the response.
    beyond one window   use the plans covered after the account's week had used more than one full weekly window: the
                        room a reset outside the schedule made. A week's use is counted in points of its window, every
                        reading's rise above the highest read since the week began or since its last fall of
                        ``limits.DROP_POINTS`` or more, the count going on from the first reading after such a fall: the
                        use between a reset and that reading is not counted, so what a reset made room for is never
                        overstated. The dollars between the two readings across which the count passes 100 are split by
                        the points on either side, and every response after them in the week is beyond. A week without
                        such a fall never counts past 100.

The multiple with resets sets the use the plans covered (``Use.in_plans``) against the plans' cost, the multiple without
resets the part of it within one window a week (``Use.one_window``).

A week is one of an account's scheduled weekly windows, ending where its readings' own reset time says, or where the
account's weekly anchor says for a reading without one (``limits.weekly_anchor``). A reading taken within
``limits.WINDOW_START_MARGIN`` of its week's start, or naming a window already over, may read the week before and is
left out, as the live figure leaves it out (``limits.weekly_standing``); one naming a window half a week or more before
the latest one read is a reading handed on late.

A fall inside a week is a reset outside the schedule, of one of three kinds (``Reset.kind``):
    model     it gave back about what a model with an allowance of its own held of the week (``limits.gives_back``): a
              reset of that allowance;
    extra     the model's allowance cannot explain it — the model held under ``limits.DROP_POINTS`` of the week, or the
              fall gave back more than it held: the week given back;
    unknown   the model was used while its allowance was not known, or the fall gave back less than the model held.
Either reset is one Anthropic hands out at random, free and not for sale, which the user takes when they choose (the
maintainer's answer of 2026-11-11): the room it makes is no paid use, but a chance gift, which is why the multiple
without resets leaves it out. The week's own reset comes at its fixed time and ends the week rather than falling inside
it.
A model has an allowance from the moment claude.ai first read its window, on any account, and in every week after it,
whether claude.ai was read that week or not (the maintainer's decision of 2026-11-11): before it, the model's use is the
plans' and no fall is its reset, as no figure then showed an allowance. From then on, an account with no reading of the
window takes its allowance as unknown, and an account's allowance for a week is the last one claude.ai gave it by the
week's end, else the first it gave after: the allowance is the plan's, and changes only with it.

The model's points per dollar, and the weekly window's, are the live figure's rates as they stood at the week's end, or
at the end of the span asked for where that comes first (``limits.percent_per_dollar``, ``limits.family_rates``), cut
from one reading of every rise the span's weeks need.

Facts are read, never stored: every figure here is computed from the ledger when it is asked for, so a reading that
arrives late changes it.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import accumulate
from typing import Iterable

from .ledger import Ledger, Observation, ScopedObservation
from .limits import (CALIBRATION_DAYS, DROP_POINTS, FIVE_HOURS, WEEK, WINDOW_START_MARGIN, Rise, ScopedCarry, Spending,
                     WeeklyAnchor, blocked_spans_of, family_rates_of, merge_spans, rate_of, rises, share_tolerance,
                     weekly_anchor)
from .pricing import family_named, model_family

FULL = 100.0                # a full window, in points
JUST_BEFORE = 1e-3          # s: a response's model allowance is read this long before it, its own spend left out
LOOKBACK = WEEK + FIVE_HOURS    # read before a span's start: the week it begins inside, and a run of 5-hour readings
KINDS = ("extra", "model", "unknown")


@dataclass(frozen=True)
class Use:
    """API-equivalent dollars over a span (``PlanUse.between``)."""

    api: float = 0.0            # every response's
    outside: float = 0.0        # of it, paid at extra usage
    beyond: float = 0.0         # of what the plans covered, the use beyond one window a week

    @property
    def in_plans(self) -> float:
        return self.api - self.outside

    @property
    def one_window(self) -> float:
        return self.api - self.outside - self.beyond

    def __add__(self, other: Use) -> Use:
        return Use(self.api + other.api, self.outside + other.outside, self.beyond + other.beyond)


@dataclass(frozen=True)
class Reset:
    """A fall of the weekly window inside one scheduled week: a reset outside the schedule."""

    before: float               # the last reading before it
    after: float                # the first reading after it
    high: float                 # the highest figure read in the week since its start or its last fall
    low: float                  # the figure after it
    kind: str                   # model | extra | unknown
    model: str | None = None    # the model's window's name, for kind model

    @property
    def given(self) -> float:
        """The points of the week it gave back, as read."""
        return self.high - self.low


@dataclass(frozen=True)
class Week:
    """One scheduled weekly window of an account."""

    start: float
    end: float
    used: float                 # points of the window used in it, as counted above
    resets: tuple[Reset, ...]   # oldest first
    beyond: float               # API-equivalent dollars the plans covered in it beyond one window


class AccountUse:
    """One account's responses, oldest first, each with its API-equivalent dollars, the part of them paid outside the
    plans and the part beyond one window a week, and the account's scheduled weeks."""

    def __init__(self, times: list[float], costs: list[float | None], outside: list[bool], beyond: list[float],
                 weeks: tuple[Week, ...] = ()):
        self.times, self.weeks = times, weeks
        priced = [cost or 0.0 for cost in costs]
        self._rows = [(t, None if cost is None else 0.0 if out else cost)
                      for t, cost, out in zip(times, costs, outside)]
        self._api = [0.0, *accumulate(priced)]
        self._outside = [0.0, *accumulate(cost if out else 0.0 for cost, out in zip(priced, outside))]
        self._beyond = [0.0, *accumulate(beyond)]

    def between(self, start: float, end: float) -> Use:
        """The dollars of the responses in [start, end)."""
        low, high = bisect_left(self.times, start), bisect_left(self.times, end)
        return Use(self._api[high] - self._api[low], self._outside[high] - self._outside[low],
                   self._beyond[high] - self._beyond[low])

    def spending(self) -> Spending:
        """The use the plans covered, as ``limits.rises`` prices responses: an unpriced response stays unpriced, one
        paid outside the plans costs nothing."""
        return Spending(self._rows)


class PlanUse:
    """Every account's use over a span, and the use with no known account, which nothing here classifies."""

    def __init__(self, accounts: dict[str, AccountUse], loose: AccountUse):
        self.accounts, self.loose = accounts, loose

    def between(self, start: float, end: float, uuids: Iterable[str] | None = None) -> Use:
        """The dollars of the responses in [start, end): every response's, the use with no account among them, or only
        the responses of the accounts ``uuids`` names."""
        if uuids is None:
            found = [*self.accounts.values(), self.loose]
        else:
            found = [self.accounts[uuid] for uuid in set(uuids) if uuid in self.accounts]
        return sum((use.between(start, end) for use in found), Use())

    def weeks(self, uuid: str | None) -> tuple[Week, ...]:
        use = self.accounts.get(uuid) if uuid is not None else None
        return use.weeks if use is not None else ()

    def spending(self, uuid: str) -> Spending | None:
        use = self.accounts.get(uuid)
        return use.spending() if use is not None else None


def plan_use(ledger: Ledger, start: float, end: float) -> PlanUse:
    """Every response's use from ``start`` to ``end``, classified, and every account's weeks with a reading in that
    span, the readings and the responses being read from ``LOOKBACK`` before ``start``. ``between`` answers for spans
    within it, and the accounts' ``spending`` from a week and five hours before ``start``."""
    origin = start - LOOKBACK
    rows: dict[str | None, list[tuple[float, float | None, str | None]]] = defaultdict(list)
    for account, t, cost, model in ledger.db.execute(
            "SELECT account_uuid, t, cost_usd, model FROM responses WHERE t>=? AND t<=? ORDER BY t", (origin, end)):
        rows[account].append((t, cost, model))
    read = {account for (account,) in ledger.db.execute(
        "SELECT DISTINCT account_uuid FROM observations WHERE kind='seven_day' AND account_uuid IS NOT NULL "
        "AND t>=? AND t<=?", (origin, end))}
    models = _models(ledger)
    families: dict[str | None, str] = {}
    accounts = {account: _Account(ledger, account, rows.get(account, []), origin, end, models, families).use()
                for account in sorted({a for a in rows if a is not None} | read)}
    loose = rows.get(None, [])
    return PlanUse(accounts, AccountUse([t for t, _, _ in loose], [cost for _, cost, _ in loose], [False] * len(loose),
                                        [0.0] * len(loose)))


def _models(ledger: Ledger) -> dict[str, tuple[str, float]]:
    """Each per-model window claude.ai has read, on any account, by name, with the model family it names and the moment
    claude.ai first read it, from which the model's allowance stands."""
    if not ledger.has_table("scoped_windows"):
        return {}
    found = {}
    for name, first in ledger.db.execute("SELECT name, MIN(t) FROM scoped_windows GROUP BY name ORDER BY name"):
        family = family_named(name)
        if family is not None:
            found[name] = (family, first)
    return found


# --- the weeks --------------------------------------------------------------------------------------------------------

@dataclass
class _Walk:
    """One week's readings walked, oldest first."""

    start: float
    end: float
    levels: list[tuple[float, float]] = field(default_factory=list)   # (when, the highest since the start or last fall)
    # Each fall: (the last reading before it, the first after it, the highest before it, the figure after it).
    falls: list[tuple[float, float, float, float]] = field(default_factory=list)
    used: float = 0.0
    level: float = 0.0
    full: tuple[float, float, float] | None = None   # (from, to, the part of the dollars between them still within)


def _walks(observations: list[Observation], anchor: WeeklyAnchor | None) -> list[_Walk]:
    """The account's weeks, each its readings walked: its levels, its falls and the points it used."""
    walks: list[_Walk] = []
    for o in observations:
        end = o.resets_at if o.resets_at is not None else anchor.next_after(o.t) if anchor is not None else None
        if end is None or end <= o.t or o.t < end - WEEK + WINDOW_START_MARGIN:
            continue
        walk = walks[-1] if walks else None
        if walk is not None and end <= walk.end - WEEK / 2:
            continue
        if walk is None or end >= walk.end + WEEK / 2:
            walk = _Walk(end - WEEK, end)
            walks.append(walk)
        else:
            walk.end = end   # the end the week's latest reading names
        before = walk.levels[-1][0] if walk.levels else walk.start
        if walk.level - o.percent >= DROP_POINTS:
            walk.falls.append((before, o.t, walk.level, o.percent))
            walk.level = o.percent
        else:
            rise = max(0.0, o.percent - walk.level)
            if walk.full is None and walk.used + rise > FULL:
                walk.full = (before, o.t, (FULL - walk.used) / rise)
            walk.used += rise
            walk.level = max(walk.level, o.percent)
        walk.levels.append((o.t, walk.level))
    return walks


class _Spend:
    """Dollars by response time as running sums, so a span's dollars are two lookups."""

    def __init__(self, times: list[float], costs: Iterable[float]):
        self.times, self.sums = times, [0.0, *accumulate(costs)]

    def between(self, start: float, end: float) -> float:
        """The dollars of the responses in (start, end]."""
        return self.sums[bisect_right(self.times, end)] - self.sums[bisect_right(self.times, start)]


class _Account:
    """One account's responses classified (``plan_use``)."""

    def __init__(self, ledger: Ledger, account: str, rows: list[tuple[float, float | None, str | None]],
                 origin: float, end: float, models: dict[str, tuple[str, float]], families: dict[str | None, str]):
        """``rows`` are the account's responses from ``origin`` to ``end``; the readings are read from a week before
        ``origin``, so the week ``origin`` falls in is walked whole."""
        self.ledger, self.account, self.end = ledger, account, end
        # Read once: the weeks walked from a week before ``origin``, and before them what the rates' rises need — the
        # rate's days before the earliest week's end, and a week before those (``_rises``).
        self.read_from = origin - 2 * WEEK - CALIBRATION_DAYS * 86400
        self.every_weekly = [o for o in ledger.observations(account, "seven_day", since=self.read_from) if o.t <= end]
        self.weekly = [o for o in self.every_weekly if o.t >= origin - WEEK]
        five = [o for o in ledger.observations(account, "five_hour", since=origin - FIVE_HOURS) if o.t <= end]
        self.anchor = weekly_anchor(self.weekly)
        self.times = [t for t, _, _ in rows]
        self.costs = [cost for _, cost, _ in rows]
        self.family_of = families
        self.families = [self._family(model) for _, _, model in rows]
        self.priced = priced = [cost or 0.0 for cost in self.costs]
        self.rates: dict[tuple[str, float], tuple[float | None, float | None, float | None]] = {}
        self.own: dict[str, Spending] = {}
        self._wide_rows: tuple[float, list] | None = None
        self._all_rises: tuple[list[Rise], list[float]] | None = None
        self.total = _Spend(self.times, priced)
        self.outside = [False] * len(rows)
        for a, b in merge_spans(blocked_spans_of(self.weekly, "seven_day", self.anchor, end)
                                + blocked_spans_of(five, "five_hour", self.anchor, end)):
            for index in range(bisect_right(self.times, a), bisect_right(self.times, b)):
                self.outside[index] = True
        self.walks = _walks(self.weekly, self.anchor)
        self.verdicts: dict[tuple[int, int], list[tuple[str, str | None]]] = defaultdict(list)
        readings: dict[str, list[ScopedObservation]] = defaultdict(list)
        for r in ledger.scoped_observations(account):
            readings[r.name].append(r)
        for name, (family, first_read) in models.items():
            self._model(name, family, first_read, readings.get(name, []))

    # --- a model's allowance ------------------------------------------------------------------------------------------

    def _model(self, name: str, family: str, first_read: float, readings: list[ScopedObservation]) -> None:
        """Each fall's verdict for the model, and its responses made while its allowance stood full, outside the
        plans, from ``first_read``, when claude.ai first read the model's window: before it the model has no allowance,
        so its use is the plans' and no fall is its reset."""
        spend = _Spend(self.times, (cost if f == family else 0.0 for cost, f in zip(self.priced, self.families)))
        for number, walk in enumerate(self.walks):
            if walk.end <= first_read:
                continue
            first = bisect_right(self.times, max(walk.start, first_read))
            last = bisect_right(self.times, min(walk.end, self.end))
            responses = [i for i in range(first, last) if self.families[i] == family]
            if not any(after > first_read for _before, after, _high, _low in walk.falls) and not responses:
                continue
            allowance = _allowance(readings, walk.end)
            week = [r for r in readings if walk.start + WINDOW_START_MARGIN <= r.t <= walk.end
                    and (r.resets_at is None or abs(r.resets_at - walk.end) < WEEK / 2)]
            anchors = [(walk.start, 0.0)] + [(r.t, r.percent) for r in week]
            anchor_times = [t for t, _ in anchors]
            rate, own, rest = (self._rates(name, family, walk, readings) if allowance and responses
                               else (None, None, None))
            carry = ScopedCarry([(walk.start, 0.0)] + walk.levels, spend.between, self.total.between, allowance,
                                own, rest, rate if own is None else own)
            falls = [(after, high, low) for _before, after, high, low in walk.falls]
            fall_times = [after for after, _, _ in falls]

            def carried(moment: float, read: float | None = None) -> tuple[float, float, float | None, float, tuple]:
                """The last anchor before ``moment`` — the week's start or a claude.ai reading — with its level, and the
                model's level carried from it through the falls read up to ``read`` (``moment`` where not given): where
                the carry stands from, and each fall's verdict, None for each after the first whose effect on the model
                is not known."""
                at, level = anchors[max(0, bisect_left(anchor_times, moment) - 1)]
                passed = falls[bisect_right(fall_times, at):bisect_right(fall_times, moment if read is None else read)]
                carried_level, since, _inferred, verdicts = carry.through(level, at, passed)
                return at, level, carried_level, since, verdicts + (None,) * (len(passed) - len(verdicts))

            for index, (after, high, low) in enumerate(falls):
                if after <= first_read:
                    continue   # before the model had an allowance: its verdict is none of this model's
                at, anchor_level, _level, _since, verdicts = carried(after)
                verdict = verdicts[-1]
                if allowance is None:
                    used = spend.between(max(at, first_read), after) > 0 or anchor_level > 0
                    kind = "unknown" if used else "extra"
                elif verdict is None:
                    kind = "unknown"
                elif verdict.kind == "model":
                    kind = "model"
                elif verdict.kind == "other":
                    kind = "extra"
                elif verdict.share is not None and high - low > verdict.share + share_tolerance(verdict.share):
                    kind = "extra"
                else:
                    kind = "unknown"
                self.verdicts[(number, index)].append((kind, name if kind == "model" else None))
            level_times = [t for t, _ in walk.levels]
            for index in responses:
                if self.outside[index]:
                    continue
                moment = self.times[index] - JUST_BEFORE
                # A fall the response's own reading shows came before it: that reading is the first after it.
                brought = bisect_left(level_times, self.times[index])
                read = level_times[brought] if brought < len(level_times) else moment
                _at, _anchor_level, level, carried_from, _verdicts = carried(moment, read)
                if level is not None and level + carry.took(carried_from, moment, bisect_right) >= FULL:
                    self.outside[index] = True

    def _rates(self, name: str, family: str, walk: _Walk,
               readings: list[ScopedObservation]) -> tuple[float | None, float | None, float | None]:
        """The weekly window's points per dollar, the family's and every other family's, as the live figure would have
        measured them at the week's end (``limits.percent_per_dollar``, ``limits.family_rates``): the rises of the
        ``limits.CALIBRATION_DAYS`` before it, cut from one reading of every rise the span needs, a run counting only
        where something was spent across it within those days, and the family's read off ``readings``, claude.ai's of
        the model ``name``'s window, where they measure it (``limits.family_rates_of``)."""
        moment = min(walk.end, self.end)
        key = (name, moment)
        if key not in self.rates:
            since = moment - CALIBRATION_DAYS * 86400
            found, times = self._rises()
            found = found[bisect_left(times, since):bisect_right(times, moment)]
            spent: dict[tuple[str, int], float] = defaultdict(float)
            for r in found:
                spent[(r.source, r.run)] += r.dollars
            found = [r for r in found if spent[(r.source, r.run)] > 0]
            self.rates[key] = (rate_of(found), *family_rates_of(found, self._family_spending(family), readings,
                                                                self.every_weekly, since, moment))
        return self.rates[key]

    def _wide(self) -> tuple[float, list[tuple[float, float | None, str | None]]]:
        """Where the rates' rises are read from — the rate's days before the earliest week's end — and the account's
        responses (t, dollars, model) from a week and five hours before that, read once."""
        if self._wide_rows is None:
            first = min((walk.end for walk in self.walks), default=self.end)
            since = min(first, self.end) - CALIBRATION_DAYS * 86400
            rows = self.ledger.db.execute("SELECT t, cost_usd, model FROM responses WHERE account_uuid=? AND t>=? "
                                          "AND t<=? ORDER BY t", (self.account, since - WEEK - FIVE_HOURS, self.end))
            self._wide_rows = (since, rows.fetchall())
        return self._wide_rows

    def _rises(self) -> tuple[list[Rise], list[float]]:
        """Every rise of the weekly window the rates need, read once (``limits.rises``), by time, and their times."""
        if self._all_rises is None:
            since, rows = self._wide()
            # Every week walked ends after a week before ``origin``, so its rises' readings are among those read.
            found = sorted(rises(self.ledger, self.account, "seven_day", since, self.end,
                                 spending=Spending([(t, cost) for t, cost, _model in rows]),
                                 observations=self.every_weekly), key=lambda r: r.t)
            self._all_rises = (found, [r.t for r in found])
        return self._all_rises

    def _family_spending(self, family: str) -> Spending:
        """The family's dollars of the account's responses as running sums, an unpriced one of its own left unpriced,
        as ``limits.family_rates`` counts them."""
        if family not in self.own:
            _since, rows = self._wide()
            self.own[family] = Spending([(t, cost if self._family(model) == family else 0.0)
                                         for t, cost, model in rows])
        return self.own[family]

    def _family(self, model: str | None) -> str:
        if model not in self.family_of:
            self.family_of[model] = model_family(model)
        return self.family_of[model]

    # --- the account's use ------------------------------------------------------------------------------------------

    def use(self) -> AccountUse:
        in_plans = [0.0 if out else cost for cost, out in zip(self.priced, self.outside)]
        beyond = [0.0] * len(self.times)
        weeks = []
        for number, walk in enumerate(self.walks):
            first, last = bisect_right(self.times, walk.start), bisect_right(self.times, walk.end)
            if walk.full is not None:
                frm, to, within = walk.full
                cut = bisect_right(self.times, to)
                for index in range(max(first, bisect_right(self.times, frm)), cut):
                    beyond[index] = in_plans[index] * (1.0 - within)
                for index in range(max(first, cut), last):
                    beyond[index] = in_plans[index]
            resets = tuple(Reset(before, after, high, low, *_kind(self.verdicts.get((number, index), [])))
                           for index, (before, after, high, low) in enumerate(walk.falls))
            weeks.append(Week(walk.start, walk.end, walk.used, resets, sum(beyond[first:last])))
        return AccountUse(self.times, self.costs, self.outside, beyond, tuple(weeks))


def _allowance(readings: list[ScopedObservation], end: float) -> float | None:
    """The model's allowance for the week ending at ``end``: the last claude.ai gave by then, else the first after."""
    given = [r for r in readings if r.allowance is not None]
    before = [r for r in given if r.t <= end]
    if before:
        return before[-1].allowance
    return given[0].allowance if given else None


def _kind(verdicts: list[tuple[str, str | None]]) -> tuple[str, str | None]:
    """A fall's kind over every model's verdict: a model's reset where one gave back its share, unknown where any model
    could not say, else extra; a week no model's allowance was read for gives extra."""
    for kind, model in verdicts:
        if kind == "model":
            return kind, model
    return ("unknown", None) if any(kind == "unknown" for kind, _ in verdicts) else ("extra", None)
