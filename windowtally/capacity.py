"""What a plan's windows hold: the API-equivalent dollars one full 5-hour window and one full weekly window held, per
plan, from the readings of the accounts the bills put on it, taken on this machine.

A reading says how much of a window the account has used; the ledger says what the account's Claude Code responses here
cost at list price. Between two readings of one window, the dollars spent here and the points the figure rose give a
rate, and a full window — 100 points — held 100 × dollars ÷ points. The figure is counted as though all of the account's
use were Claude Code here: the readings also rise with the account's other use — the desktop app's Chat tab, claude.ai
in a browser, other devices — which costs nothing here, so wherever the account is also used otherwise a full window
holds more than the figure says, which is then a lower bound. It is stated per plan in absolute terms, never derived
from the multiples marketed between plans, and a plan none of whose accounts was measured here has no figure. The
dollars are those of the use the plans covered (``plan_use``): what extra usage paid for — use while a window stood
exhausted, or a model's use past its own allowance — raised no window of the plan, and counted would make a window
seem to hold more than it did.

Vocabulary
    plan span   a stretch of time one recorded plan held an account (``plan_spans``): its periods in effect, joined where
                one runs on into the next at the same plan, less the UTC day the plan began or changed — a bill gives
                that day, not the hour.
    step        one rise of the estimates (``limits.rises``): two consecutive readings of one account's window from one
                instrument — its plugin readings from the first of them on, its desktop app samples before that —
                inside one run, the points the figure moved between them and the dollars of the account's responses
                after the first and up to the second: the rule the ≈ estimates' rate is built from, so the two rest on
                the same evidence. Here one plan span must also hold both readings, and the dollars are the plans'.
    chain       one run of steps, each beginning at the reading the one before ended at: its rise is its highest reading
                less its first, so a reading of another session trailing by a few points inside it adds nothing.
    held        100 × dollars ÷ points over a set of steps: what one full window held (``Held``).

Rounding. Readings are whole points, so a chain's rise is off by less than one point, and the chains' errors are
independent: over n chains the rise is off by √n points or less but rarely (√n is about 2.4 standard deviations of a sum
of n differences of two readings, each rounded within one point). A figure is stated only where that moves it by at most
``TOLERANCE`` of itself — a rise of at least √n ÷ ``TOLERANCE`` points, ten for a single chain — and two figures differ
only by more than the sum of their two such bounds (``differs``). A chain's first reading can also be one that trails
another session's by a few points; few readings do, so the bound is left to rounding alone.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from typing import Iterable

from .billing import ONE_DAY, BillingReport, day_start
from .ledger import Ledger
from .limits import CALIBRATION_MAX_GAP, rises
from .plan_use import PlanUse, plan_use

KINDS = ("five_hour", "seven_day")
FULL = 100.0           # a full window, in points
RESOLUTION = 1.0       # a reading's resolution in points: Claude Code and the desktop app report whole percentages
TOLERANCE = 0.1        # the largest share of a figure the readings' rounding may move it by


@dataclass(frozen=True)
class PlanSpan:
    start: float
    end: float
    plan: str          # a key of ``bills.PLANS``


@dataclass(frozen=True)
class Step:
    account: str
    plan: str
    kind: str
    t: float           # the later reading's time
    points: float      # how far the later reading took the chain's highest reading so far: never negative
    dollars: float     # API-equivalent USD of the account's responses in (earlier reading, later reading], maybe 0
    chain: tuple       # the chain it belongs to: one per account, window, instrument and run of steps


@dataclass(frozen=True)
class Held:
    points: float
    dollars: float
    chains: int

    @property
    def stated(self) -> bool:
        return self.points > 0 and self.points * TOLERANCE >= RESOLUTION * math.sqrt(self.chains)

    @property
    def full(self) -> float | None:
        """What one full window held, in API-equivalent dollars; None where the rise is too small to say."""
        return FULL * self.dollars / self.points if self.stated else None

    @property
    def spread(self) -> float | None:
        """How far the readings' rounding may move ``full``, in dollars."""
        full = self.full
        return None if full is None else full * RESOLUTION * math.sqrt(self.chains) / self.points


def held(steps: Iterable[Step]) -> Held:
    taken = list(steps)
    return Held(sum(s.points for s in taken), sum(s.dollars for s in taken), len({s.chain for s in taken}))


def differs(a: Held, b: Held) -> bool:
    """Whether two stated figures differ by more than the readings' rounding can move them apart."""
    return abs(a.full - b.full) > a.spread + b.spread


# --- plans over time --------------------------------------------------------------------------------------------------

def plan_spans(billing: BillingReport) -> dict[str, list[PlanSpan]]:
    """Each account's plan spans, oldest first, by UUID: every account a subscription's e-mail names. A span ends where
    its plans stopped being in effect, a refund's date among those ends; an account whose bills may not all have been
    read has no period (``billing``), so no span, and is not measured."""
    spans: dict[str, list[PlanSpan]] = {}
    for s in billing.subscriptions:
        joined: list[list] = []   # [first day, day it stopped, plan]
        for period in sorted((p for p in s.periods if p.until > p.bill.start), key=lambda p: p.bill.start):
            if joined and joined[-1][2] == period.bill.plan and joined[-1][1] >= period.bill.start:
                joined[-1][1] = max(joined[-1][1], period.until)
            else:
                joined.append([period.bill.start, period.until, period.bill.plan])
        found = [PlanSpan(day_start(first + ONE_DAY), day_start(stopped), plan)
                 for first, stopped, plan in joined if first + ONE_DAY < stopped]
        for uuid in s.uuids:
            spans[uuid] = found
    return spans


def _plan_at(spans: list[PlanSpan], starts: list[float], moment: float) -> str | None:
    at = bisect_right(starts, moment) - 1
    return spans[at].plan if at >= 0 and moment < spans[at].end else None


# --- steps ------------------------------------------------------------------------------------------------------------

def steps(ledger: Ledger, spans: dict[str, list[PlanSpan]], since: float, until: float,
          uses: PlanUse | None = None) -> list[Step]:
    """Every step whose later reading is from ``since`` to ``until``, of every account a plan span names. A step's
    dollars are the use the plans covered (``plan_use``), read from ``uses`` where it covers ``since`` on, else
    computed: what extra usage paid for raised no window of the plan."""
    if uses is None:
        uses = plan_use(ledger, since, until)
    found: list[Step] = []
    for account, held_spans in spans.items():
        if not (held_spans and held_spans[0].start <= until and held_spans[-1].end > since - CALIBRATION_MAX_GAP):
            continue
        starts = [s.start for s in held_spans]

        def plan_of(a: float, b: float, held_spans=held_spans, starts=starts) -> str | None:
            plan = _plan_at(held_spans, starts, a)
            return plan if plan is not None and _plan_at(held_spans, starts, b) == plan else None

        spending = uses.spending(account)
        for kind in KINDS:
            found += [Step(account, r.group, kind, r.t, r.points, r.dollars, (account, kind, r.source, r.run))
                      for r in rises(ledger, account, kind, since, until, plan_of, spending)]
    return found
