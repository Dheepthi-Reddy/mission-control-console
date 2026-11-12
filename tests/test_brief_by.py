"""Brief-by time follows severity (high 5, medium 15, low 30 minutes).

Any launch-limit violation counts as high, whatever severity the model gave.
"""

import pytest

from app.domain.brief_by import brief_by_minutes, effective_severity


@pytest.mark.parametrize(
    "severity, minutes",
    [
        pytest.param("high", 5, id="high -> 5"),
        pytest.param("medium", 15, id="medium -> 15"),
        pytest.param("low", 30, id="low -> 30"),
    ],
)
def test_minutes_follow_severity_when_no_violation(severity, minutes):
    assert effective_severity(severity, has_violation=False) == severity
    assert brief_by_minutes(severity, has_violation=False) == minutes


@pytest.mark.parametrize("severity", ["high", "medium", "low"])
def test_any_violation_counts_as_high(severity):
    assert effective_severity(severity, has_violation=True) == "high"
    assert brief_by_minutes(severity, has_violation=True) == 5


@pytest.mark.parametrize("bad", ["critical", "", "HIGH", None])
def test_unknown_severity_is_rejected(bad):
    with pytest.raises(ValueError):
        brief_by_minutes(bad, has_violation=False)
