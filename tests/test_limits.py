"""Launch limits are plain code: verdict and violations never come from a model.

Limits: wind_knots <= 25, temp_c >= 4, 98 <= fuel_pct <= 100.
Each limit is tested exactly on the boundary (go) and just past it (no_go).
"""

import pytest

from app.domain.limits import LimitCheck, Violation, check_limits

NOMINAL = {"wind_knots": 10.0, "temp_c": 15.0, "fuel_pct": 99.0}


def readings(**overrides):
    return {**NOMINAL, **overrides}


def test_all_nominal_is_go_with_no_violations():
    result = check_limits(**NOMINAL)
    assert result == LimitCheck(verdict="go", violations=[])


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"wind_knots": 25.0}, id="wind exactly 25"),
        pytest.param({"temp_c": 4.0}, id="temp exactly 4"),
        pytest.param({"fuel_pct": 98.0}, id="fuel exactly 98"),
        pytest.param({"fuel_pct": 100.0}, id="fuel exactly 100"),
    ],
)
def test_exactly_on_limit_is_go(overrides):
    result = check_limits(**readings(**overrides))
    assert result.verdict == "go"
    assert result.violations == []


@pytest.mark.parametrize(
    "overrides, expected",
    [
        pytest.param({"wind_knots": 25.1}, Violation("wind_knots", 25.1, "<= 25"), id="wind 25.1"),
        pytest.param({"temp_c": 3.9}, Violation("temp_c", 3.9, ">= 4"), id="temp 3.9"),
        pytest.param({"fuel_pct": 97.9}, Violation("fuel_pct", 97.9, "98-100"), id="fuel 97.9"),
        pytest.param({"fuel_pct": 100.1}, Violation("fuel_pct", 100.1, "98-100"), id="fuel 100.1"),
    ],
)
def test_just_past_limit_is_no_go_with_one_violation(overrides, expected):
    result = check_limits(**readings(**overrides))
    assert result.verdict == "no_go"
    assert result.violations == [expected]


def test_multiple_violations_are_all_reported_in_fixed_order():
    result = check_limits(wind_knots=40.0, temp_c=-2.0, fuel_pct=90.0)
    assert result.verdict == "no_go"
    assert [v.reading for v in result.violations] == ["wind_knots", "temp_c", "fuel_pct"]
