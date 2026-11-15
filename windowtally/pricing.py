"""Anthropic's list prices: the API's, for the API-equivalent cost of each response, and the plans', for what a
subscription's plan time is worth.

The cost is a yardstick for comparing models, sessions and accounts — subscription use is not billed per token.
Prices are USD per million tokens at Claude API first-party rates, as published in November 2026. Cache writes
cost 1.25x the input price with the 5-minute TTL and 2x with the 1-hour TTL; cache reads have a price of their
own per model. Measured against Claude Code's own cost record (a transcript's ``cost-state`` line) for
claude-opus-5-5 with 1-hour cache writes, the formula below reproduces it to the cent.

Fast mode publishes input and output at exactly twice the standard rate for every model that has it; its cache
rates are not published separately and are taken at the same factor.

The plans' prices are Anthropic's US web prices in US dollars, as checked on 2026-10-23: Pro $20 a month or $200 a
year billed annually; Max 5x $100 and Ultra $200 a month, monthly only — Ultra at the price Max 20x had, which
Anthropic's notice of 2026-10-31 renaming the plan kept. Every subscription cost WindowTally shows is
at these prices, whatever a bill was charged in, so it stands beside the API-equivalent figures in one currency with
nothing converted (``billing``). Nothing is fetched: the table changes when the prices do.

What a context written to the cache again cost beyond reading it from there (``cache_write_premium``) is priced by the
same rates, at the tier the request's whole context puts it in.

A response of a model the table does not name has no cost (``response_cost`` None), never a cost of nought: the
ledger keeps its tokens, so once the table names the model every such response is priced where it stands
(``ingest_transcripts.reprice``), and until then the pass names the model among its source problems.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

CACHE_WRITE_5M_FACTOR = 1.25
CACHE_WRITE_1H_FACTOR = 2.0
FAST_MODE_FACTOR = 2.0


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens. A model with a long-context tier switches every rate above the prompt threshold."""

    input: float
    output: float
    cache_read: float
    long_context_threshold: int | None = None
    long_context: ModelPrice | None = None


PRICES: dict[str, ModelPrice] = {
    "claude-fable-5-2": ModelPrice(8.0, 40.0, 0.20),
    "claude-mythos-5-2": ModelPrice(8.0, 40.0, 0.20),
    "claude-fable-5-1": ModelPrice(10.0, 50.0, 0.25),
    "claude-mythos-5-1": ModelPrice(10.0, 50.0, 0.25),
    "claude-fable-5": ModelPrice(10.0, 50.0, 1.00),
    "claude-mythos-5": ModelPrice(10.0, 50.0, 1.00),
    "claude-opus-5-5": ModelPrice(4.0, 20.0, 0.20),
    "claude-opus-5": ModelPrice(5.0, 25.0, 0.50),
    "claude-opus-4-8": ModelPrice(5.0, 25.0, 0.50),
    "claude-opus-4-7": ModelPrice(5.0, 25.0, 0.50),
    "claude-opus-4-6": ModelPrice(5.0, 25.0, 0.50),
    "claude-sonnet-5-5": ModelPrice(2.0, 10.0, 0.20),
    "claude-sonnet-5": ModelPrice(2.0, 10.0, 0.20),
    "claude-sonnet-4-6": ModelPrice(3.0, 15.0, 0.30),
    "claude-haiku-5-5": ModelPrice(0.10, 0.50, 0.01, long_context_threshold=100_000,
                                   long_context=ModelPrice(0.50, 2.50, 0.05)),
    "claude-haiku-4-5": ModelPrice(1.0, 5.0, 0.10),
}

@dataclass(frozen=True)
class PlanPrice:
    """A plan's US list price in US dollars: a month's, and a year's where the plan is sold by the year."""

    monthly: Decimal
    yearly: Decimal | None = None


PLAN_PRICES: dict[str, PlanPrice] = {
    "pro": PlanPrice(Decimal(20), Decimal(200)),
    "max5x": PlanPrice(Decimal(100)),
    "ultra": PlanPrice(Decimal(200)),
}

_SUFFIXES = re.compile(r"(\[[^\]]*\])+$|-\d{8}$")


def canonical_model(model: str | None) -> str | None:
    """The model ID without a context-size tag ("[1m]") or a date snapshot suffix ("-20250929")."""
    if not model:
        return None
    previous = None
    name = model.strip()
    while previous != name:
        previous = name
        name = _SUFFIXES.sub("", name)
    return name


FAMILY_KEYS = (("Fable", ("fable", "mythos")), ("Opus", ("opus",)), ("Sonnet", ("sonnet",)), ("Haiku", ("haiku",)))
"""Each model family and the words its model IDs hold. Mythos is Fable's counterpart for verified organizations, the
same model under another name, so it is counted with Fable."""


def model_family(model: str | None) -> str:
    """The family a model belongs to — ``Fable``, ``Opus``, ``Sonnet``, ``Haiku`` — or ``Other``."""
    name = canonical_model(model) or ""
    for family, keys in FAMILY_KEYS:
        if any(key in name for key in keys):
            return family
    return "Other"


def family_named(display_name: str) -> str | None:
    """The family a model's name as a page shows it names — ``Fable`` for "Fable", "Fable 5.2" or "Claude Fable" — or
    None where it names none of them."""
    name = display_name.lower()
    return next((family for family, keys in FAMILY_KEYS if any(key in name for key in keys)), None)


def price_for(model: str | None) -> ModelPrice | None:
    name = canonical_model(model)
    return PRICES.get(name) if name else None


def _tier(price: ModelPrice, prompt_tokens: int) -> ModelPrice:
    """The rates a request of ``prompt_tokens`` pays: the long-context tier's above its threshold."""
    if price.long_context is not None and price.long_context_threshold is not None \
            and prompt_tokens > price.long_context_threshold:
        return price.long_context
    return price


def response_cost(model: str | None, *, input_tokens: int, output_tokens: int, cache_read_tokens: int,
                  cache_write_5m_tokens: int, cache_write_1h_tokens: int, speed: str | None = None) -> float | None:
    """API-equivalent USD of one response, or None for a model with no list price.

    Thinking tokens are part of ``output_tokens`` in the API's usage, so they are not added again.
    """
    price = price_for(model)
    if price is None:
        return None
    price = _tier(price, input_tokens + cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens)
    usd = (input_tokens * price.input
           + output_tokens * price.output
           + cache_read_tokens * price.cache_read
           + cache_write_5m_tokens * price.input * CACHE_WRITE_5M_FACTOR
           + cache_write_1h_tokens * price.input * CACHE_WRITE_1H_FACTOR) / 1_000_000
    if speed == "fast":
        usd *= FAST_MODE_FACTOR
    return usd


def cache_write_premium(model: str | None, *, prompt_tokens: int, cache_write_5m_tokens: int,
                        cache_write_1h_tokens: int, speed: str | None = None) -> float | None:
    """What a response's cache writes cost beyond reading the same tokens from the cache, in API-equivalent USD, or
    None for a model with no list price: what writing a context again cost over having it still cached. The rates are
    the tier ``prompt_tokens``, the request's whole context, puts it in."""
    price = price_for(model)
    if price is None:
        return None
    price = _tier(price, prompt_tokens)
    usd = (cache_write_5m_tokens * (price.input * CACHE_WRITE_5M_FACTOR - price.cache_read)
           + cache_write_1h_tokens * (price.input * CACHE_WRITE_1H_FACTOR - price.cache_read)) / 1_000_000
    if speed == "fast":
        usd *= FAST_MODE_FACTOR
    return usd
