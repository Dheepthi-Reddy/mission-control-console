"""Brief-by time in plain code: how soon the Flight Director must be briefed.

Severity comes from the model; a launch-limit violation (from check_limits)
always overrides it to high, so a mis-rated report can't get a slow deadline.
"""

from typing import Literal

Severity = Literal["high", "medium", "low"]

BRIEF_BY_MINUTES: dict[str, int] = {"high": 5, "medium": 15, "low": 30}


def effective_severity(severity: Severity, has_violation: bool) -> Severity:
    """The severity actually used: any limit violation counts as high."""
    if severity not in BRIEF_BY_MINUTES:
        raise ValueError(f"unknown severity: {severity!r}")
    return "high" if has_violation else severity


def brief_by_minutes(severity: Severity, has_violation: bool) -> int:
    return BRIEF_BY_MINUTES[effective_severity(severity, has_violation)]
