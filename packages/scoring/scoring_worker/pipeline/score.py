"""Composite scoring engine.

  composite_score = 0.40 * solar_roi
                  + 0.35 * financial_health
                  + 0.25 * social_impact

All three components are normalised to [0, 100]. Weights live in
solarreach_shared.constants.SCORE_WEIGHTS — single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass

from solarreach_shared.constants import SCORE_WEIGHTS

# ---------------------------------------------------------------------------
# Component scoring functions — pure, easy to unit-test
# ---------------------------------------------------------------------------
def solar_roi_score(annual_kwh_per_kwp: float, *, premises_floor_area_m2: float | None = None) -> float:
    """0..100 from PVGIS yield.

    UK realistic range: 750 (north Scotland) to 1100 (south coast).
    750 = 0; 1100 = 100; linear in between."""

    if annual_kwh_per_kwp <= 0:
        return 0.0
    raw = (annual_kwh_per_kwp - 750.0) / (1100.0 - 750.0) * 100.0
    return max(0.0, min(100.0, raw))


def financial_health_score(company_health: float | None, *, has_company: bool) -> float:
    """0..100 from a company-health signal. Falls back to neutral 50 if unknown."""

    if not has_company:
        return 50.0
    if company_health is None:
        return 50.0
    return max(0.0, min(100.0, company_health))


def social_impact_score(imd_decile: int) -> float:
    """0..100 from IMD decile.

    More-deprived areas score HIGHER for social impact (1 = most deprived,
    10 = least). decile 1 -> 100; decile 10 -> 10. Linear."""

    if imd_decile < 1 or imd_decile > 10:
        return 50.0
    # decile 1 -> 100, decile 10 -> 10. slope = -10 per decile, intercept 110.
    return float(110 - imd_decile * 10)


@dataclass(frozen=True)
class CompositeScoreResult:
    composite_score: float
    breakdown: dict[str, float]


def compute_composite(
    *,
    annual_kwh_per_kwp: float,
    company_health: float | None,
    imd_decile: int,
    has_company: bool,
) -> CompositeScoreResult:
    s_roi = solar_roi_score(annual_kwh_per_kwp)
    s_fin = financial_health_score(company_health, has_company=has_company)
    s_soc = social_impact_score(imd_decile)
    composite = (
        SCORE_WEIGHTS["solar_roi"] * s_roi
        + SCORE_WEIGHTS["financial_health"] * s_fin
        + SCORE_WEIGHTS["social_impact"] * s_soc
    )
    return CompositeScoreResult(
        composite_score=round(composite, 2),
        breakdown={
            "solar_roi": round(s_roi, 2),
            "financial_health": round(s_fin, 2),
            "social_impact": round(s_soc, 2),
        },
    )
