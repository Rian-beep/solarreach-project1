"""Financial maths tests. Acceptance: ≥13 tests, all passing."""

from __future__ import annotations

import math

import pytest

from solarreach_shared.financial import (
    FinancialInputs,
    annual_saving,
    capex,
    compute,
    fractional_payback,
    irr,
    npv,
    payback_years,
    system_kwp,
    yearly_cashflows,
)


def test_system_kwp_default_panel() -> None:
    assert system_kwp(100) == pytest.approx(42.0)


def test_capex_uses_default_per_kwp() -> None:
    # 100 panels * 0.42 kWp * 850 £/kWp = 35_700 £
    assert capex(100) == pytest.approx(35700.0)


def test_annual_saving_self_consumption_split() -> None:
    # 10000 kWh * 0.7 * 0.27 + 10000 * 0.3 * 0.05 = 1890 + 150 = 2040
    s = annual_saving(10000.0)
    assert s == pytest.approx(2040.0)


def test_annual_saving_negative_input_raises() -> None:
    with pytest.raises(ValueError):
        annual_saving(-1.0)


def test_payback_years_simple() -> None:
    assert payback_years(20000.0, 4000.0) == pytest.approx(5.0)


def test_payback_years_zero_saving_is_inf() -> None:
    assert payback_years(20000.0, 0.0) == math.inf


def test_yearly_cashflows_year0_is_negative_capex() -> None:
    inputs = FinancialInputs(panels_count=100, annual_kwh_year1=40000.0)
    cfs = yearly_cashflows(inputs)
    assert cfs[0] == pytest.approx(-capex(100))


def test_yearly_cashflows_degradation_compounds() -> None:
    inputs = FinancialInputs(panels_count=100, annual_kwh_year1=40000.0,
                              degradation_per_year=0.005, lifetime_years=5)
    cfs = yearly_cashflows(inputs)
    # Year 1 = full nameplate; year 2 = 0.995x; year 3 = 0.995^2 x
    s1 = annual_saving(40000.0)
    s2 = annual_saving(40000.0 * 0.995)
    s3 = annual_saving(40000.0 * 0.995 * 0.995)
    assert cfs[1] == pytest.approx(s1)
    assert cfs[2] == pytest.approx(s2)
    assert cfs[3] == pytest.approx(s3)


def test_npv_simple_constant_cashflows() -> None:
    cfs = [-1000.0, 100.0, 100.0, 100.0]
    # NPV at 10% = -1000 + 100/1.1 + 100/1.21 + 100/1.331
    expected = -1000.0 + 100.0 / 1.1 + 100.0 / 1.21 + 100.0 / 1.331
    assert npv(cfs, 0.10) == pytest.approx(expected, abs=1e-6)


def test_irr_returns_none_when_all_same_sign() -> None:
    assert irr([100.0, 100.0, 100.0]) is None


def test_irr_recovers_known_rate() -> None:
    # An investment of 1000 returning 110/year for 25 yrs → IRR ~9.4%
    cfs = [-1000.0] + [110.0] * 25
    r = irr(cfs)
    assert r is not None
    assert 0.05 < r < 0.15


def test_fractional_payback_within_year() -> None:
    # -1000, then 400/yr → payback at year 2.5
    cfs = [-1000.0, 400.0, 400.0, 400.0]
    fp = fractional_payback(cfs)
    assert fp == pytest.approx(2.5, abs=0.01)


def test_fractional_payback_never_recovers() -> None:
    cfs = [-1000.0, 100.0, 100.0]
    assert fractional_payback(cfs) == math.inf


def test_compute_full_breakdown_is_consistent() -> None:
    inputs = FinancialInputs(panels_count=100, annual_kwh_year1=40000.0)
    out = compute(inputs)
    # capex check
    assert out.capex_gbp == pytest.approx(capex(100))
    # year-1 saving check
    assert out.annual_saving_year1_gbp == pytest.approx(annual_saving(40000.0))
    # payback should be in plausible commercial range (3-15 years for healthy install)
    assert 3.0 < out.payback_years < 15.0
    # NPV at default 6% over 25 years should be positive for plausible inputs
    assert out.npv_25yr_gbp > 0
    # Breakdown dict serialises cleanly
    d = out.as_breakdown_dict()
    assert set(d.keys()) >= {"capex_gbp", "annual_saving_gbp", "payback_years", "npv_25yr_gbp"}


def test_compute_zero_panels_is_zero_capex() -> None:
    inputs = FinancialInputs(panels_count=0, annual_kwh_year1=0.0)
    out = compute(inputs)
    assert out.capex_gbp == 0.0
    assert out.annual_saving_year1_gbp == 0.0
