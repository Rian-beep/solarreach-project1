"""Financial maths for solar ROI.

Single source of truth. TS mirror at packages/shared/ts/src/financial.ts
must produce identical outputs (±£1) — verified by tests/test_financial.py.

Conventions:
- All money in pounds (float) at this layer; storage layer converts to pence.
- All energy in kWh.
- Year 0 = year of install (capex outflow). Years 1..N = operation.
- Degradation compounded annually.
"""

from __future__ import annotations

from dataclasses import dataclass

from solarreach_shared.constants import (
    DISCOUNT_RATE,
    GBP_PER_KWH_GRID,
    GBP_PER_KWH_SEG_EXPORT,
    GBP_PER_KWP_INSTALLED,
    PANEL_KWP,
    SYSTEM_DEGRADATION_PCT_PER_YEAR,
    SYSTEM_LIFETIME_YEARS,
)


@dataclass(frozen=True)
class FinancialInputs:
    panels_count: int
    annual_kwh_year1: float                  # generation in year 1, BEFORE degradation
    self_consumption_pct: float = 0.70       # % of generation used on-site
    grid_tariff_gbp_per_kwh: float = GBP_PER_KWH_GRID
    seg_tariff_gbp_per_kwh: float = GBP_PER_KWH_SEG_EXPORT
    capex_gbp_per_kwp: float = GBP_PER_KWP_INSTALLED
    panel_kwp: float = PANEL_KWP
    discount_rate: float = DISCOUNT_RATE
    lifetime_years: int = SYSTEM_LIFETIME_YEARS
    degradation_per_year: float = SYSTEM_DEGRADATION_PCT_PER_YEAR


@dataclass(frozen=True)
class FinancialOutputs:
    capex_gbp: float
    annual_saving_year1_gbp: float
    payback_years: float                    # fractional
    npv_25yr_gbp: float
    irr_pct: float | None                   # None if NPV never crosses zero
    system_kwp: float

    def as_breakdown_dict(self) -> dict[str, float]:
        out: dict[str, float] = {
            "capex_gbp": round(self.capex_gbp, 2),
            "annual_saving_gbp": round(self.annual_saving_year1_gbp, 2),
            "payback_years": round(self.payback_years, 2),
            "npv_25yr_gbp": round(self.npv_25yr_gbp, 2),
        }
        if self.irr_pct is not None:
            out["irr_pct"] = round(self.irr_pct, 2)
        return out


def system_kwp(panels_count: int, panel_kwp: float = PANEL_KWP) -> float:
    return panels_count * panel_kwp


def capex(panels_count: int, *, panel_kwp: float = PANEL_KWP, gbp_per_kwp: float = GBP_PER_KWP_INSTALLED) -> float:
    return system_kwp(panels_count, panel_kwp) * gbp_per_kwp


def annual_saving(
    annual_kwh: float,
    *,
    self_consumption_pct: float = 0.70,
    grid_tariff: float = GBP_PER_KWH_GRID,
    seg_tariff: float = GBP_PER_KWH_SEG_EXPORT,
) -> float:
    """Year-1 saving in GBP. Self-consumed kWh saves grid tariff;
    exported kWh earns SEG tariff."""

    if annual_kwh < 0:
        raise ValueError("annual_kwh must be >= 0")
    self_consumed = annual_kwh * self_consumption_pct
    exported = annual_kwh - self_consumed
    return self_consumed * grid_tariff + exported * seg_tariff


def payback_years(capex_gbp: float, annual_saving_gbp: float) -> float:
    """Simple payback ignoring degradation/discount.
    Returns float infinity if annual_saving_gbp <= 0."""

    if annual_saving_gbp <= 0:
        return float("inf")
    return capex_gbp / annual_saving_gbp


def yearly_cashflows(inputs: FinancialInputs) -> list[float]:
    """Year 0 = -capex; years 1..N = saving with degradation applied."""

    cashflows: list[float] = [-capex(
        inputs.panels_count,
        panel_kwp=inputs.panel_kwp,
        gbp_per_kwp=inputs.capex_gbp_per_kwp,
    )]
    kwh = inputs.annual_kwh_year1
    for year in range(1, inputs.lifetime_years + 1):
        # Degradation applied at start of each year EXCEPT year 1.
        # Year 1 = nameplate; year 2 = nameplate * (1 - d); etc.
        if year > 1:
            kwh *= (1.0 - inputs.degradation_per_year)
        cashflows.append(annual_saving(
            kwh,
            self_consumption_pct=inputs.self_consumption_pct,
            grid_tariff=inputs.grid_tariff_gbp_per_kwh,
            seg_tariff=inputs.seg_tariff_gbp_per_kwh,
        ))
    return cashflows


def npv(cashflows: list[float], rate: float) -> float:
    """Standard NPV: sum of cashflow_t / (1+r)^t for t=0..N."""

    return sum(cf / ((1.0 + rate) ** t) for t, cf in enumerate(cashflows))


def irr(cashflows: list[float], *, guess: float = 0.10, max_iter: int = 200, tol: float = 1e-7) -> float | None:
    """Newton-Raphson IRR. Returns None if it doesn't converge or no sign change."""

    # Sign-change check — IRR undefined if cashflows are all same sign.
    has_pos = any(cf > 0 for cf in cashflows)
    has_neg = any(cf < 0 for cf in cashflows)
    if not (has_pos and has_neg):
        return None

    rate = guess
    for _ in range(max_iter):
        # NPV and its derivative w.r.t. rate.
        f = 0.0
        df = 0.0
        for t, cf in enumerate(cashflows):
            denom = (1.0 + rate) ** t
            f += cf / denom
            if t > 0:
                df += -t * cf / ((1.0 + rate) ** (t + 1))
        if abs(df) < 1e-12:
            return None
        new_rate = rate - f / df
        if abs(new_rate - rate) < tol:
            return new_rate
        rate = new_rate
        # Bound to keep us in plausible territory.
        if rate <= -0.999 or rate > 10.0:
            return None
    return None


def fractional_payback(cashflows: list[float]) -> float:
    """Payback in fractional years from cumulative cashflow series.
    Year 0 is the capex outflow. Linear interpolate within the crossing year."""

    cumulative = 0.0
    for t, cf in enumerate(cashflows):
        new_cum = cumulative + cf
        if cumulative < 0 <= new_cum:
            # Crossing happens in year `t`. Fraction = -cumulative / cf.
            if cf == 0:
                return float(t)
            return (t - 1) + (-cumulative / cf)
        cumulative = new_cum
    return float("inf")


def compute(inputs: FinancialInputs) -> FinancialOutputs:
    """Full financial summary."""

    cfs = yearly_cashflows(inputs)
    capex_gbp = -cfs[0]
    annual_saving_y1 = cfs[1] if len(cfs) > 1 else 0.0
    return FinancialOutputs(
        capex_gbp=capex_gbp,
        annual_saving_year1_gbp=annual_saving_y1,
        payback_years=fractional_payback(cfs),
        npv_25yr_gbp=npv(cfs, inputs.discount_rate),
        irr_pct=(irr(cfs) or 0.0) * 100 if irr(cfs) is not None else None,
        system_kwp=system_kwp(inputs.panels_count, inputs.panel_kwp),
    )
