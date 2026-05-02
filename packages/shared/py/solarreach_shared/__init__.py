"""Shared SolarReach domain types, financial maths, compliance helpers.

Single source of truth for cross-service constants. Mirrored partially in TS
under packages/shared/ts/src/. Schemas live in packages/shared/schemas/.
"""

from solarreach_shared.constants import (
    BRISTOL_BBOX,
    LONDON_BBOX,
    ROI_GATE_THRESHOLD,
    SCORE_WEIGHTS,
)

__all__ = [
    "BRISTOL_BBOX",
    "LONDON_BBOX",
    "ROI_GATE_THRESHOLD",
    "SCORE_WEIGHTS",
]
