"""Cost per model call and per report, calculated in code from token counts.

Decimal, not float, so money adds up exactly (0.1 + 0.2 == 0.3).
"""

from collections.abc import Iterable
from decimal import Decimal

from app.llm.client import LLMResponse

PER_MILLION = Decimal(1_000_000)

# USD per 1M tokens: (input, output). Anthropic first-party rates.
# Haiku 5.5 charges more above 100K-token prompts; reports here are far smaller.
PRICES_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00")),
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "fake": (Decimal("0"), Decimal("0")),
}


def step_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """USD cost of one model call. Unknown models fail loudly rather than cost $0."""
    if model not in PRICES_PER_MTOK:
        raise ValueError(f"no price for model {model!r}")
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts must be non-negative")

    input_price, output_price = PRICES_PER_MTOK[model]
    return (input_tokens * input_price + output_tokens * output_price) / PER_MILLION


def report_cost(steps: Iterable[LLMResponse]) -> Decimal:
    """Total USD cost of every model call made for one report."""
    return sum(
        (step_cost(s.model, s.input_tokens, s.output_tokens) for s in steps),
        start=Decimal("0"),
    )
