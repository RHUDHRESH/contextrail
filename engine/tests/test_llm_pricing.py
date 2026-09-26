"""Cost per call (T115): Claude Haiku 4.5 list prices, cache multipliers, rounding that never under-counts."""

from decimal import Decimal

import pytest

from contextrail.llm.pricing import PRICES, UnknownPrice, cost_usd
from contextrail.llm.router import HAIKU_BEDROCK_ID, HAIKU_DIRECT_ID

HAIKU = HAIKU_DIRECT_ID


def test_only_claude_haiku_4_5_is_priced():
    assert set(PRICES) == {HAIKU}  # D-013: no Sonnet or other model entries
    p = PRICES[HAIKU]
    assert (p.input, p.output, p.cache_write, p.cache_read) == (
        Decimal("1.00"), Decimal("5.00"), Decimal("1.25"), Decimal("0.10"))  # USD per million tokens


def test_input_and_output_tokens():
    assert cost_usd(HAIKU, input_tokens=1_000, output_tokens=200) == Decimal("0.002000")   # 0.001 + 0.001
    assert cost_usd(HAIKU, input_tokens=1_000_000, output_tokens=0) == Decimal("1.000000")


def test_cache_writes_and_reads_are_priced_separately():
    assert cost_usd(HAIKU, input_tokens=0, output_tokens=0, cache_write_tokens=4_000) == Decimal("0.005000")
    assert cost_usd(HAIKU, input_tokens=0, output_tokens=0, cache_read_tokens=4_000) == Decimal("0.000400")


def test_rounds_up_to_the_microdollar_so_spend_is_never_under_counted():
    assert cost_usd(HAIKU, input_tokens=1, output_tokens=0) == Decimal("0.000001")   # $0.000001 exactly
    assert cost_usd(HAIKU, input_tokens=0, output_tokens=1) == Decimal("0.000005")
    assert cost_usd(HAIKU, input_tokens=0, output_tokens=0, cache_read_tokens=1) == Decimal("0.000001")  # 1e-7 -> up


def test_zero_tokens_cost_nothing():
    assert cost_usd(HAIKU, input_tokens=0, output_tokens=0) == Decimal("0.000000")


@pytest.mark.parametrize("model", ["claude-sonnet-5", "claude-opus-5", HAIKU_BEDROCK_ID])
def test_an_unpriced_model_is_an_error_not_free(model):
    # Bedrock calls are priced by the logical Haiku ID (the router does that), never by the profile ID.
    with pytest.raises(UnknownPrice):
        cost_usd(model, input_tokens=1, output_tokens=1)
