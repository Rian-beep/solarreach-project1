"""ROI gate. Returns True iff a lead is eligible for paid enrichment.

A 'paid enrichment' is anything that costs real money: Solar API findClosest,
Solar API dataLayers, Hunter.io email lookup, real Companies House director
lookups (free but rate-limited so we still gate them).

Threshold lives in solarreach_shared.constants.ROI_GATE_THRESHOLD (default 70).
"""

from __future__ import annotations

from solarreach_shared.constants import ROI_GATE_THRESHOLD


def is_eligible(composite_score: float, *, threshold: float | None = None) -> bool:
    """True if the lead clears the ROI gate."""

    return composite_score >= (threshold if threshold is not None else ROI_GATE_THRESHOLD)
