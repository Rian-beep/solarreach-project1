"""Tests for the scoring-pipeline tool wrappers.

These tests cover the @tool wrappers themselves: input validation, output
shape, and round-trip correctness against the underlying pipeline. They do
NOT exercise the LLM — agent end-to-end tests are deferred to manual demo.
"""

from __future__ import annotations

import json

import pytest

from lead_agent.tools.scoring_tools import (
    check_roi_gate,
    compute_financials,
    compute_score,
    discover_signals,
)


def test_discover_signals_returns_expected_keys() -> None:
    out = discover_signals.invoke({"postcode": "EC1Y 8AF", "company_name": "Test Office Ltd"})
    assert isinstance(out, dict)
    expected = {
        "lng", "lat", "formatted_address", "annual_kwh_per_kwp",
        "optimum_tilt", "optimum_azimuth", "imd_decile",
        "company_health_score", "cost_cents",
    }
    assert expected.issubset(out.keys())
    # IMD decile must be a 1-10 int, not a numpy / float.
    assert isinstance(out["imd_decile"], int)
    assert 1 <= out["imd_decile"] <= 10


def test_discover_signals_no_company_returns_null_health() -> None:
    out = discover_signals.invoke({"postcode": "EC1Y 8AF"})
    assert out["company_health_score"] is None


def test_discover_signals_is_deterministic_in_mock_mode() -> None:
    a = discover_signals.invoke({"postcode": "BS1 4DJ", "company_name": "Demo Ltd"})
    b = discover_signals.invoke({"postcode": "BS1 4DJ", "company_name": "Demo Ltd"})
    assert a == b


def test_compute_score_round_trip() -> None:
    out = compute_score.invoke({
        "annual_kwh_per_kwp": 1000.0,
        "imd_decile": 3,
        "company_health": 75.0,
        "has_company": True,
    })
    assert "composite_score" in out
    assert 0 <= out["composite_score"] <= 100
    assert set(out["breakdown"].keys()) == {"solar_roi", "financial_health", "social_impact"}


def test_compute_score_no_company_uses_neutral_financial() -> None:
    out = compute_score.invoke({
        "annual_kwh_per_kwp": 950.0,
        "imd_decile": 5,
        "company_health": None,
        "has_company": False,
    })
    assert out["breakdown"]["financial_health"] == 50.0


def test_check_roi_gate_default_threshold() -> None:
    above = check_roi_gate.invoke({"composite_score": 75.0})
    assert above["eligible"] is True
    assert above["threshold"] == 70.0

    below = check_roi_gate.invoke({"composite_score": 65.0})
    assert below["eligible"] is False


def test_check_roi_gate_override_threshold() -> None:
    out = check_roi_gate.invoke({"composite_score": 65.0, "threshold": 60.0})
    assert out["eligible"] is True
    assert out["threshold"] == 60.0


def test_compute_financials_returns_breakdown() -> None:
    out = compute_financials.invoke({
        "panels_count": 100,
        "annual_kwh_year1": 40000.0,
    })
    expected = {"capex_gbp", "annual_saving_gbp", "payback_years", "npv_25yr_gbp", "system_kwp"}
    assert expected.issubset(out.keys())
    # 100 panels @ 0.42 kWp = 42 kWp
    assert out["system_kwp"] == pytest.approx(42.0)
    # capex = 42 * 850 = 35700
    assert out["capex_gbp"] == pytest.approx(35700.0)


def test_compute_financials_zero_panels_zero_capex() -> None:
    out = compute_financials.invoke({
        "panels_count": 0,
        "annual_kwh_year1": 0.0,
    })
    assert out["capex_gbp"] == 0.0
    assert out["system_kwp"] == 0.0
