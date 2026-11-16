"""Cost per report is calculated in code from token counts and a price table."""

from decimal import Decimal

import pytest

from app.domain.cost import report_cost, step_cost
from app.llm.client import LLMResponse

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"


def call(model: str, input_tokens: int, output_tokens: int) -> LLMResponse:
    return LLMResponse(text="", input_tokens=input_tokens, output_tokens=output_tokens, model=model)


@pytest.mark.parametrize(
    "model, input_price, output_price",
    [
        pytest.param(OPUS, "4.00", "20.00", id="opus 5.5"),
        pytest.param(SONNET, "2.00", "10.00", id="sonnet 5.5"),
        pytest.param(HAIKU, "0.10", "0.50", id="haiku 5.5"),
    ],
)
def test_one_million_tokens_costs_the_listed_price(model, input_price, output_price):
    assert step_cost(model, 1_000_000, 0) == Decimal(input_price)
    assert step_cost(model, 0, 1_000_000) == Decimal(output_price)


def test_small_call_is_exact():
    # 1,000 in at $4/M = 0.004; 1,000 out at $20/M = 0.02
    assert step_cost(OPUS, 1_000, 1_000) == Decimal("0.024")


def test_zero_tokens_cost_nothing():
    assert step_cost(OPUS, 0, 0) == Decimal("0")


def test_fake_model_costs_nothing():
    assert step_cost("fake", 500, 500) == Decimal("0")


def test_report_cost_sums_every_step_across_models():
    steps = [
        call(OPUS, 1_000, 1_000),  # 0.024
        call(HAIKU, 2_000, 1_000),  # 0.0002 + 0.0005 = 0.0007
        call(SONNET, 1_000, 500),  # 0.002 + 0.005 = 0.007
    ]
    assert report_cost(steps) == Decimal("0.0317")


def test_report_with_no_steps_costs_nothing():
    assert report_cost([]) == Decimal("0")


def test_unknown_model_is_rejected():
    with pytest.raises(ValueError, match="no price"):
        step_cost("gpt-unknown", 10, 10)


@pytest.mark.parametrize("tokens", [(-1, 0), (0, -1)], ids=["negative input", "negative output"])
def test_negative_tokens_are_rejected(tokens):
    with pytest.raises(ValueError):
        step_cost(OPUS, *tokens)
