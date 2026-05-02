"""Abstract base interfaces for every external-API adapter.

Conventions:
- All adapters expose async methods (the worker uses asyncio).
- Every method that costs money returns a `cost_cents` field in metadata.
- Adapters NEVER write to MongoDB; they return plain dicts. Persistence is
  the pipeline's job.
- Errors raise AdapterError with a discriminated `code` for the cost gate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AdapterCost:
    cents: int = 0
    free_quota_remaining: int | None = None


class AdapterError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class GeocodeResult:
    lng: float
    lat: float
    formatted_address: str
    confidence: float
    cost: AdapterCost


@dataclass(frozen=True)
class WeatherForecast:
    cell_id: str
    days: list[dict[str, Any]]   # {date, irradiance_kwh_m2, cloud_cover_pct, temp_c}
    cost: AdapterCost


@dataclass(frozen=True)
class PvgisYearly:
    annual_kwh_per_kwp: float
    optimum_tilt: float
    optimum_azimuth: float
    cost: AdapterCost = AdapterCost()


@dataclass(frozen=True)
class SolarBuildingInsights:
    """Raw-ish wrapper around Google Solar API findClosest."""

    distance_to_request_m: float
    roof_segments: list[dict[str, Any]]
    panel_layout: list[dict[str, Any]]
    annual_kwh_estimate: float
    cost: AdapterCost


@dataclass(frozen=True)
class SolarFluxLayer:
    """Raw GeoTIFF URLs from Solar API dataLayers:get."""

    annual_flux_url: str
    monthly_flux_url: str | None
    rgb_url: str | None
    mask_url: str | None
    bbox_4326: tuple[float, float, float, float]   # (min_lng, min_lat, max_lng, max_lat)
    cost: AdapterCost


@dataclass(frozen=True)
class IMDLookup:
    postcode: str
    decile: int            # 1 = most deprived; 10 = least
    rank: int
    cost: AdapterCost = AdapterCost()


@dataclass(frozen=True)
class CompaniesHouseSearchHit:
    company_number: str
    title: str
    address_snippet: str | None
    company_status: str | None
    cost: AdapterCost = AdapterCost()


@dataclass(frozen=True)
class CompaniesHouseOfficer:
    name: str               # raw "LASTNAME, Firstname"
    role: str
    appointed_on: str | None
    resigned_on: str | None
    cost: AdapterCost = AdapterCost()


# ---------------------------------------------------------------------------
# Abstract bases
# ---------------------------------------------------------------------------
class GeocodingAdapter(ABC):
    @abstractmethod
    async def geocode_postcode(self, postcode: str) -> GeocodeResult: ...


class WeatherAdapter(ABC):
    @abstractmethod
    async def forecast(self, lng: float, lat: float, *, days: int = 5) -> WeatherForecast: ...


class PvgisAdapter(ABC):
    @abstractmethod
    async def yearly_yield(self, lng: float, lat: float, *, kwp: float = 1.0) -> PvgisYearly: ...


class SolarApiAdapter(ABC):
    @abstractmethod
    async def building_insights(self, lng: float, lat: float) -> SolarBuildingInsights: ...

    @abstractmethod
    async def data_layers(self, lng: float, lat: float, *, radius_m: float = 50) -> SolarFluxLayer: ...


class IMDAdapter(ABC):
    @abstractmethod
    async def lookup_postcode(self, postcode: str) -> IMDLookup: ...


class CompaniesHouseAdapter(ABC):
    @abstractmethod
    async def search_company(self, name: str) -> list[CompaniesHouseSearchHit]: ...

    @abstractmethod
    async def list_officers(self, company_number: str) -> list[CompaniesHouseOfficer]: ...
