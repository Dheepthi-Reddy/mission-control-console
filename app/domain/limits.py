"""Launch limits in plain code. No model is involved in the verdict.

A report's note can contain anything (including instructions aimed at a model),
so the go/no_go decision depends only on the three numeric readings.
"""

from dataclasses import dataclass, field
from typing import Literal

WIND_MAX_KNOTS = 25.0
TEMP_MIN_C = 4.0
FUEL_MIN_PCT = 98.0
FUEL_MAX_PCT = 100.0

Verdict = Literal["go", "no_go"]


@dataclass(frozen=True)
class Violation:
    reading: str
    value: float
    limit: str


@dataclass(frozen=True)
class LimitCheck:
    verdict: Verdict
    violations: list[Violation] = field(default_factory=list)


def check_limits(wind_knots: float, temp_c: float, fuel_pct: float) -> LimitCheck:
    """Return the verdict and every violated limit, in order: wind, temp, fuel."""
    violations: list[Violation] = []

    if wind_knots > WIND_MAX_KNOTS:
        violations.append(Violation("wind_knots", wind_knots, f"<= {WIND_MAX_KNOTS:g}"))
    if temp_c < TEMP_MIN_C:
        violations.append(Violation("temp_c", temp_c, f">= {TEMP_MIN_C:g}"))
    if not FUEL_MIN_PCT <= fuel_pct <= FUEL_MAX_PCT:
        violations.append(Violation("fuel_pct", fuel_pct, f"{FUEL_MIN_PCT:g}-{FUEL_MAX_PCT:g}"))

    return LimitCheck(verdict="no_go" if violations else "go", violations=violations)
