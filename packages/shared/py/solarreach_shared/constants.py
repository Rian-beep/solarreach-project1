"""Constants shared across scoring, API, codex, voice, and web services.

Hard rule: if a constant appears in more than one service, it lives here.
TS mirror: packages/shared/ts/src/constants.ts (must stay in sync).
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Composite score weights — see Section 1 of the system prompt
# ---------------------------------------------------------------------------
# composite_score = 0.40 * solar_roi + 0.35 * financial_health + 0.25 * social_impact
# All three components are 0-100. Weights MUST sum to 1.0.
SCORE_WEIGHTS: Final[dict[str, float]] = {
    "solar_roi": 0.40,
    "financial_health": 0.35,
    "social_impact": 0.25,
}

# Composite score below this threshold = no expensive enrichment
# (no Hunter.io, no Companies House director lookup, no Solar API).
ROI_GATE_THRESHOLD: Final[float] = 70.0

# ---------------------------------------------------------------------------
# Target geographic bounding boxes — used to filter LR + INSPIRE ingest
# ---------------------------------------------------------------------------
# Format: (min_lng, min_lat, max_lng, max_lat) in EPSG:4326.
# Generous bounds — narrow at query time, never at ingest time.
LONDON_BBOX: Final[tuple[float, float, float, float]] = (-0.51, 51.28, 0.33, 51.69)
BRISTOL_BBOX: Final[tuple[float, float, float, float]] = (-2.72, 51.39, -2.45, 51.55)

TARGET_BBOXES: Final[dict[str, tuple[float, float, float, float]]] = {
    "london": LONDON_BBOX,
    "bristol": BRISTOL_BBOX,
}

# ---------------------------------------------------------------------------
# INSPIRE polygon plausibility filter
# ---------------------------------------------------------------------------
# INSPIRE includes parcels that are gardens, parking lots, and fields.
# Filter to plausible building footprints by area.
INSPIRE_MIN_AREA_M2: Final[float] = 80.0
INSPIRE_MAX_AREA_M2: Final[float] = 5000.0
# Search radius (metres) when snapping a lead to its nearest INSPIRE polygon.
INSPIRE_SNAP_RADIUS_M: Final[float] = 200.0

# ---------------------------------------------------------------------------
# Solar API hardening
# ---------------------------------------------------------------------------
# Reject Google Solar API findClosest responses returning a building further
# than this from the requested coordinates — likely a different building.
SOLAR_API_MAX_DISTANCE_M: Final[float] = 80.0

# ---------------------------------------------------------------------------
# Premises taxonomy — bound to name pattern in seed.py to avoid the
# "random misclassification" bug noted in Project 1.
# ---------------------------------------------------------------------------
PREMISES_TYPES: Final[tuple[str, ...]] = (
    "Warehouse",
    "Office",
    "Retail Park",
    "Leisure Centre",
    "Manufacturing",
    "Cold Storage",
    "Hospital",
    "School",
    "Hotel",
    "Logistics Hub",
)

# ---------------------------------------------------------------------------
# UK financial constants — mirrored in financial.py
# ---------------------------------------------------------------------------
GBP_PER_KWH_GRID: Final[float] = 0.27       # 2026 typical UK commercial tariff
GBP_PER_KWH_SEG_EXPORT: Final[float] = 0.05  # Smart Export Guarantee floor
GBP_PER_KWP_INSTALLED: Final[float] = 850.0  # turnkey commercial install
PANEL_KWP: Final[float] = 0.42               # 420W panel default
SYSTEM_DEGRADATION_PCT_PER_YEAR: Final[float] = 0.005  # 0.5%/yr
SYSTEM_LIFETIME_YEARS: Final[int] = 25
DISCOUNT_RATE: Final[float] = 0.06           # 6% real discount rate

# ---------------------------------------------------------------------------
# Sanity check — runs on import
# ---------------------------------------------------------------------------
_total = sum(SCORE_WEIGHTS.values())
if not (0.999 <= _total <= 1.001):
    raise ValueError(f"SCORE_WEIGHTS must sum to 1.0 (got {_total})")
