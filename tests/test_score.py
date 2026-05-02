"""Composite scoring + gate tests."""

from __future__ import annotations

import pytest

from scoring_worker.pipeline.gate import is_eligible
from scoring_worker.pipeline.score import (
    compute_composite,
    financial_health_score,
    social_impact_score,
    solar_roi_score,
)
from solarreach_shared.constants import ROI_GATE_THRESHOLD, SCORE_WEIGHTS


# ----- component scoring ---------------------------------------------------
def test_solar_roi_score_below_floor_clamps_to_zero() -> None:
    assert solar_roi_score(700.0) == 0.0


def test_solar_roi_score_zero_yield_is_zero() -> None:
    assert solar_roi_score(0.0) == 0.0


def test_solar_roi_score_above_ceiling_clamps_to_100() -> None:
    assert solar_roi_score(1500.0) == 100.0


def test_solar_roi_score_midpoint_is_around_50() -> None:
    # midpoint of 750..1100 is 925
    s = solar_roi_score(925.0)
    assert 49.0 <= s <= 51.0


def test_financial_health_no_company_returns_neutral() -> None:
    assert financial_health_score(80.0, has_company=False) == 50.0


def test_financial_health_unknown_returns_neutral() -> None:
    assert financial_health_score(None, has_company=True) == 50.0


def test_financial_health_clamps_above_100() -> None:
    assert financial_health_score(150.0, has_company=True) == 100.0


def test_financial_health_clamps_below_zero() -> None:
    assert financial_health_score(-10.0, has_company=True) == 0.0


def test_social_impact_decile_1_is_high_impact() -> None:
    # Most-deprived area gets the highest social impact score.
    assert social_impact_score(1) == 100.0


def test_social_impact_decile_10_is_low_impact() -> None:
    assert social_impact_score(10) == 10.0


def test_social_impact_invalid_decile_returns_neutral() -> None:
    assert social_impact_score(0) == 50.0
    assert social_impact_score(11) == 50.0
    assert social_impact_score(-3) == 50.0


# ----- composite -----------------------------------------------------------
def test_compute_composite_weighted_sum_correct() -> None:
    res = compute_composite(
        annual_kwh_per_kwp=1100.0,   # solar_roi=100
        company_health=80.0,          # financial_health=80
        imd_decile=1,                 # social_impact=100
        has_company=True,
    )
    expected = (
        SCORE_WEIGHTS["solar_roi"] * 100.0
        + SCORE_WEIGHTS["financial_health"] * 80.0
        + SCORE_WEIGHTS["social_impact"] * 100.0
    )
    assert res.composite_score == pytest.approx(expected, abs=0.01)


def test_compute_composite_breakdown_keys() -> None:
    res = compute_composite(
        annual_kwh_per_kwp=900.0,
        company_health=60.0,
        imd_decile=5,
        has_company=True,
    )
    assert set(res.breakdown.keys()) == {"solar_roi", "financial_health", "social_impact"}


def test_compute_composite_in_zero_to_hundred() -> None:
    # Worst possible numbers
    worst = compute_composite(annual_kwh_per_kwp=0, company_health=0, imd_decile=10, has_company=True)
    # Best possible numbers
    best = compute_composite(annual_kwh_per_kwp=1500, company_health=100, imd_decile=1, has_company=True)
    assert 0 <= worst.composite_score <= 100
    assert 0 <= best.composite_score <= 100
    assert best.composite_score > worst.composite_score


def test_compute_composite_no_company_uses_neutral_financial() -> None:
    res = compute_composite(
        annual_kwh_per_kwp=950.0,
        company_health=None,
        imd_decile=5,
        has_company=False,
    )
    # financial_health should be neutral (50)
    assert res.breakdown["financial_health"] == 50.0


# ----- gate ---------------------------------------------------------------
def test_gate_at_threshold_passes() -> None:
    assert is_eligible(ROI_GATE_THRESHOLD) is True


def test_gate_below_threshold_fails() -> None:
    assert is_eligible(ROI_GATE_THRESHOLD - 0.01) is False


def test_gate_well_above_passes() -> None:
    assert is_eligible(95.0) is True


def test_gate_custom_threshold() -> None:
    # caller can override
    assert is_eligible(50.0, threshold=40.0) is True
    assert is_eligible(50.0, threshold=60.0) is False
