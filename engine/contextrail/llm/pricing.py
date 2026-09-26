"""What one model call cost (T115, CLAUDE.md §11). Claude Haiku 4.5 is the only model (D-013).

SOURCE of every number below: the `claude-api` skill bundled with Claude Code (retrieved 2026-09-26):
- "Current Models (cached: 2026-06-24)": Claude Haiku 4.5 at $1.00 input / $5.00 output per million tokens
  (Anthropic first-party API rates);
- shared/prompt-caching.md "Economics": cache reads cost ~0.1x base input, 5-minute cache writes 1.25x.
Re-check https://docs.claude.com/en/docs/about-claude/pricing before relying on these for billing.

Bedrock (T3) is partner-operated and billed separately by AWS. Its calls are ESTIMATED here at the first-party rates
(priced by the logical Haiku ID, never by the Bedrock profile ID). The Bedrock cap (T116) therefore enforces an
estimate; the AWS Budgets alerts are the authoritative backstop.

Rounding is up to the microdollar (numeric(10,6) in llm_calls), so recorded spend is never below real spend.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_UP, Decimal

_PER_MILLION = Decimal(1_000_000)
_MICRODOLLAR = Decimal("0.000001")


class UnknownPrice(KeyError):
    """No price for this model. An unpriced call is an error, never silently free (budgets depend on it)."""


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: Decimal
    output: Decimal
    cache_write: Decimal   # 5-minute ephemeral cache write
    cache_read: Decimal


PRICES: dict[str, Price] = {
    "claude-haiku-4-5-20251001": Price(input=Decimal("1.00"), output=Decimal("5.00"),
                                       cache_write=Decimal("1.25"), cache_read=Decimal("0.10")),
}


def price_for(model: str) -> Price:
    try:
        return PRICES[model]
    except KeyError:
        raise UnknownPrice(f"no price for {model!r}; priced models: {sorted(PRICES)}") from None


def cost_usd(model: str, *, input_tokens: int, output_tokens: int, cache_write_tokens: int = 0,
             cache_read_tokens: int = 0) -> Decimal:
    p = price_for(model)
    total = (input_tokens * p.input + output_tokens * p.output + cache_write_tokens * p.cache_write
             + cache_read_tokens * p.cache_read) / _PER_MILLION
    return total.quantize(_MICRODOLLAR, rounding=ROUND_UP)
