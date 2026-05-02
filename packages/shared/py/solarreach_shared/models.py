"""Pydantic v2 domain models — single source of truth for in-memory shapes.

JSON Schema validators in packages/shared/schemas/ are derived from these
where possible (see scripts/export_schemas.py). At-rest validation in MongoDB
uses the JSON-Schema versions; in-process validation uses these.

Hard-won lessons baked in:
- `geo` is `{point: GeoJSONPoint}` (NOT a raw GeoJSONPoint) — matches
  the schema. Mismatch caused entire-API crashes.
- All datetimes are timezone-aware UTC.
- All money in pence (int) where stored, pounds (float) only at display edge.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Geo primitives
# ---------------------------------------------------------------------------
Longitude = Annotated[float, Field(ge=-180, le=180)]
Latitude = Annotated[float, Field(ge=-90, le=90)]


class GeoJSONPoint(BaseModel):
    """RFC 7946 Point. Coordinates are [lng, lat] (NOT lat, lng)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["Point"] = "Point"
    coordinates: tuple[Longitude, Latitude]


class GeoJSONPolygon(BaseModel):
    """RFC 7946 Polygon. coordinates is list of linear rings; first is outer."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[tuple[Longitude, Latitude]]]

    @field_validator("coordinates")
    @classmethod
    def _ring_must_close(cls, v: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
        if not v or not v[0]:
            raise ValueError("polygon must have at least one ring with points")
        for ring in v:
            if len(ring) < 4:
                raise ValueError("each ring must have >=4 points (closed)")
            if ring[0] != ring[-1]:
                raise ValueError("each ring's first and last point must be identical")
        return v


class LeadGeo(BaseModel):
    """Wrapper enforced by Mongo validator: leads.geo is {point: ...}."""

    model_config = ConfigDict(extra="forbid")

    point: GeoJSONPoint


# ---------------------------------------------------------------------------
# Lead — the central object
# ---------------------------------------------------------------------------
class FinancialBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capex_gbp: float
    annual_saving_gbp: float
    payback_years: float
    npv_25yr_gbp: float
    irr_pct: float | None = None


class PanelLayoutEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    center: tuple[Longitude, Latitude]
    azimuth_deg: float            # compass bearing (0=N, 90=E, 180=S, 270=W)
    width_m: float
    height_m: float
    yearly_kwh: float


class Lead(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(alias="_id")
    client_slug: str
    name: str
    premises_type: str
    address: str
    postcode: str
    geo: LeadGeo
    rooftop_polygon: GeoJSONPolygon | None = None
    rooftop_polygon_source: Literal[
        "inspire_index_polygon",
        "solar_api_bbox",
        "synthesized",
    ] = "synthesized"
    inspire_id: str | None = None
    company_id: str | None = None
    composite_score: float = Field(ge=0, le=100)
    score_breakdown: dict[str, float]
    panel_layout: list[PanelLayoutEntry] = Field(default_factory=list)
    financial: FinancialBreakdown | None = None
    annual_kwh: float | None = None
    panels_count: int = 0
    enriched_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Company / Director (HMLR + Companies House)
# ---------------------------------------------------------------------------
class Company(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(alias="_id")
    proprietor_name: str            # exact CCOD/OCOD field
    company_number: str | None = None  # Companies House number (8 char)
    incorporation_country: str | None = None
    registered_address: str | None = None
    sic_codes: list[str] = Field(default_factory=list)
    accounts_summary: dict[str, Any] | None = None  # turnover, profit, latest filed
    health_score: float | None = Field(default=None, ge=0, le=100)
    embedding: list[float] | None = None  # 1024-dim Voyage 'voyage-3'
    source: Literal["ccod", "ocod", "companies_house", "synthesized"] = "ccod"
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class Director(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(alias="_id")
    company_id: str
    full_name: str                  # already reformatted as "Firstname LASTNAME"
    role: str                       # CFO, MD, Sustainability, etc.
    appointed_on: datetime | None = None
    resigned_on: datetime | None = None
    email: str | None = None        # populated by Hunter.io
    linkedin_url: str | None = None
    inferred_decision_maker: bool = False
    decision_maker_confidence: float | None = Field(default=None, ge=0, le=1)
    source: Literal["companies_house", "hunter", "manual", "synthesized"] = "companies_house"
    created_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# INSPIRE Index Polygon
# ---------------------------------------------------------------------------
class InspirePolygon(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(alias="_id")           # INSPIRE_ID, eg "21487532"
    inspire_id: str                        # duplicated for clarity in queries
    title_no: str | None = None
    geometry: GeoJSONPolygon               # in EPSG:4326 (converted from BNG)
    centroid: GeoJSONPoint
    area_m2_approx: float                  # computed in BNG before conversion
    local_authority: str | None = None
    ingested_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Land Registry CCOD/OCOD record
# ---------------------------------------------------------------------------
class LandRegistryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(alias="_id")
    title_number: str
    tenure: Literal["Freehold", "Leasehold"] | None = None
    proprietor_name: str
    proprietor_address: str | None = None
    company_registration_no: str | None = None
    country_incorporated: str | None = None  # OCOD only
    property_address: str
    postcode: str | None = None
    price_paid_gbp: int | None = None        # in pounds (file is in pounds)
    date_proprietor_added: datetime | None = None
    multiple_address_indicator: bool = False
    source: Literal["ccod", "ocod"]
    ingested_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Client (admin centre)
# ---------------------------------------------------------------------------
class Client(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(alias="_id")           # slug, eg "client-greensolar-uk"
    display_name: str
    primary_color: str = "#FF6B6B"          # hex, used in deck theming
    accent_color: str = "#FFD93D"
    logo_url: str | None = None
    pricing_overrides: dict[str, float] = Field(default_factory=dict)
    voice_agent_id: str | None = None       # ElevenLabs agent id override
    created_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Audit log (immutable, sha256 recipient hashes — see compliance.py)
# ---------------------------------------------------------------------------
class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(alias="_id")
    ts: datetime = Field(default_factory=_utc_now)
    actor: str                              # service name, eg "codex.deck"
    action: str                             # eg "anthropic.sonnet.invoke"
    lead_id: str | None = None
    client_slug: str | None = None
    cost_cents: int = 0                     # integer cents (sub-£0.01 = round up)
    recipient_hash: str | None = None       # sha256 of email/phone if relevant
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Time-series schemas — meta + measurement separation
# ---------------------------------------------------------------------------
class EnergyYieldSample(BaseModel):
    """One row in energy_yield_ts (granularity hours)."""

    model_config = ConfigDict(extra="forbid")

    ts: datetime
    meta: dict[str, str]                   # {"building_id": "..."}
    kwh: float
    weather_cell_id: str | None = None


class WeatherSample(BaseModel):
    """One row in weather_ts (granularity hours)."""

    model_config = ConfigDict(extra="forbid")

    ts: datetime
    meta: dict[str, str]                   # {"cell_id": "..."}
    irradiance_w_m2: float
    cloud_cover_pct: float
    temp_c: float


class CallTranscriptChunk(BaseModel):
    """One row in calls_ts (granularity seconds)."""

    model_config = ConfigDict(extra="forbid")

    ts: datetime
    meta: dict[str, str]                   # {"lead_id": "...", "role": "agent|user"}
    text: str
    embedding: list[float] | None = None    # 1024-dim Voyage; populated async
