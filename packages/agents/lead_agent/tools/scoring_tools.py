"""Scoring pipeline exposed as LangChain tools.

Every tool here is a thin wrapper around the deterministic pipeline already
shipped in scoring_worker. The agent never reaches the API directly — it
goes through a tool, which means: (a) we get LangSmith tracing for free,
(b) we can swap mock/real adapters from the env without changing the agent.

Each tool's docstring is part of its prompt to the LLM. Be precise about
units, ranges, and side effects.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from langchain_core.tools import tool

from scoring_worker.pipeline.discovery import discover
from scoring_worker.pipeline.gate import is_eligible
from scoring_worker.pipeline.score import compute_composite
from solarreach_shared.financial import FinancialInputs, compute as compute_financial


# ---------------------------------------------------------------------------
# discover_signals
# ---------------------------------------------------------------------------
@tool
def discover_signals(
    postcode: Annotated[str, "UK postcode, eg 'EC1Y 8AF' or 'BS1 4DJ'."],
    company_name: Annotated[str | None, "Optional company name for cheap mock health lookup."] = None,
) -> dict:
    """Run cheap discovery for a single lead: geocode the postcode, fetch the
    PVGIS yearly yield (kWh/kWp), look up the IMD decile (1=most deprived,
    10=least), and optionally a mock company-health signal.

    Returns a dict with: lng, lat, formatted_address, annual_kwh_per_kwp,
    optimum_tilt, optimum_azimuth, imd_decile, company_health_score,
    cost_cents.

    Cost: 0 cents in mock mode (default), ~2-3 cents in real mode.
    Side effects: none (read-only). Always safe to retry."""

    sig = asyncio.run(discover(postcode, company_name=company_name))
    return {
        "lng": sig.lng,
        "lat": sig.lat,
        "formatted_address": sig.formatted_address,
        "annual_kwh_per_kwp": sig.annual_kwh_per_kwp,
        "optimum_tilt": sig.optimum_tilt,
        "optimum_azimuth": sig.optimum_azimuth,
        "imd_decile": sig.imd_decile,
        "company_health_score": sig.company_health_score,
        "cost_cents": sig.cost_cents,
    }


# ---------------------------------------------------------------------------
# compute_score
# ---------------------------------------------------------------------------
@tool
def compute_score(
    annual_kwh_per_kwp: Annotated[float, "PVGIS annual yield. Realistic UK band: 750-1100."],
    imd_decile: Annotated[int, "IMD decile, integer 1-10. 1=most deprived."],
    company_health: Annotated[float | None, "Company health 0-100, or null."] = None,
    has_company: Annotated[bool, "True if a company is associated with the lead."] = True,
) -> dict:
    """Compute the composite score from discovery signals.

    composite_score = 0.40 * solar_roi + 0.35 * financial_health + 0.25 * social_impact.
    Returns: {composite_score: 0-100, breakdown: {solar_roi, financial_health, social_impact}}.

    Pure function. No I/O, no side effects."""

    res = compute_composite(
        annual_kwh_per_kwp=annual_kwh_per_kwp,
        company_health=company_health,
        imd_decile=imd_decile,
        has_company=has_company,
    )
    return {"composite_score": res.composite_score, "breakdown": res.breakdown}


# ---------------------------------------------------------------------------
# check_roi_gate
# ---------------------------------------------------------------------------
@tool
def check_roi_gate(
    composite_score: Annotated[float, "Composite score from compute_score, 0-100."],
    threshold: Annotated[float | None, "Optional override. Default 70.0."] = None,
) -> dict:
    """Decide whether a lead is eligible for paid enrichment (Solar API,
    Hunter, real Companies House). Default threshold is 70.

    Returns: {eligible: bool, threshold: float, composite_score: float}.
    Pure. No side effects."""

    eligible = is_eligible(composite_score, threshold=threshold)
    actual_thresh = threshold if threshold is not None else 70.0
    return {
        "eligible": eligible,
        "threshold": actual_thresh,
        "composite_score": composite_score,
    }


# ---------------------------------------------------------------------------
# compute_financials
# ---------------------------------------------------------------------------
@tool
def compute_financials(
    panels_count: Annotated[int, "Number of panels installed."],
    annual_kwh_year1: Annotated[float, "Year-1 generation in kWh BEFORE degradation."],
    self_consumption_pct: Annotated[float, "Fraction self-consumed, 0-1. Default 0.7."] = 0.70,
) -> dict:
    """Compute capex, year-1 saving, fractional payback, 25-year NPV at 6%
    real, and IRR for a solar install.

    Returns the full breakdown dict ready to write into lead.financial.
    Pure function."""

    inputs = FinancialInputs(
        panels_count=panels_count,
        annual_kwh_year1=annual_kwh_year1,
        self_consumption_pct=self_consumption_pct,
    )
    out = compute_financial(inputs)
    d = out.as_breakdown_dict()
    d["system_kwp"] = round(out.system_kwp, 2)
    return d


def all_scoring_tools() -> list:
    return [discover_signals, compute_score, check_roi_gate, compute_financials]
