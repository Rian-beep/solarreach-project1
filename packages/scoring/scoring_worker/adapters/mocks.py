"""Deterministic mock adapters. Default in dev + CI to avoid burning quota.

Every value is derived from a hash of the input — same input gives same output
across runs. This matters for snapshot tests and for the seed script.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from ._base import (
    AdapterCost,
    CompaniesHouseAdapter,
    CompaniesHouseOfficer,
    CompaniesHouseSearchHit,
    GeocodeResult,
    GeocodingAdapter,
    IMDAdapter,
    IMDLookup,
    PvgisAdapter,
    PvgisYearly,
    SolarApiAdapter,
    SolarBuildingInsights,
    SolarFluxLayer,
    WeatherAdapter,
    WeatherForecast,
)


def _hash_to_unit(*parts: str | float) -> float:
    """Stable [0,1) float from arbitrary inputs."""

    s = "|".join(str(p) for p in parts)
    h = hashlib.sha256(s.encode("utf-8")).digest()
    # First 8 bytes -> uint64 -> /2^64.
    n = int.from_bytes(h[:8], "big", signed=False)
    return n / 2**64


def _postcode_centroid(pc: str) -> tuple[float, float]:
    """Approximate London/Bristol centroid from postcode prefix.

    Real impl uses postcodes.io. Mock just maps prefix to a fixed centroid
    plus deterministic jitter — enough to render distinct pins."""

    prefix = pc.strip().upper().split()[0]
    # Hand-set centroids for common demo postcodes.
    table = {
        "EC1Y": (-0.0879, 51.5232),   # Old Street area
        "EC1V": (-0.0954, 51.5273),
        "SE1":  (-0.0950, 51.5050),
        "BS1":  (-2.5945, 51.4545),   # central Bristol
        "BS2":  (-2.5727, 51.4624),
    }
    center = table.get(prefix)
    if center is None:
        # Fall back to London centre + jitter from full postcode hash.
        center = (-0.118, 51.509)
    jitter_lng = (_hash_to_unit("lng", pc) - 0.5) * 0.012
    jitter_lat = (_hash_to_unit("lat", pc) - 0.5) * 0.008
    return (center[0] + jitter_lng, center[1] + jitter_lat)


# ---------------------------------------------------------------------------
class MockGeocodingAdapter(GeocodingAdapter):
    async def geocode_postcode(self, postcode: str) -> GeocodeResult:
        lng, lat = _postcode_centroid(postcode)
        return GeocodeResult(
            lng=lng, lat=lat,
            formatted_address=f"{postcode.strip().upper()}, UK",
            confidence=0.85,
            cost=AdapterCost(cents=0),
        )


# ---------------------------------------------------------------------------
class MockWeatherAdapter(WeatherAdapter):
    async def forecast(self, lng: float, lat: float, *, days: int = 5) -> WeatherForecast:
        cell_id = f"mock-{round(lng,2)}_{round(lat,2)}"
        out = []
        for d in range(days):
            seed = _hash_to_unit(cell_id, d)
            out.append({
                "date": f"day+{d}",
                "irradiance_kwh_m2": 2.5 + 2.0 * seed,    # 2.5..4.5
                "cloud_cover_pct": 30 + 50 * seed,         # 30..80
                "temp_c": 8 + 12 * seed,                   # 8..20
            })
        return WeatherForecast(cell_id=cell_id, days=out, cost=AdapterCost(0))


# ---------------------------------------------------------------------------
class MockPvgisAdapter(PvgisAdapter):
    async def yearly_yield(self, lng: float, lat: float, *, kwp: float = 1.0) -> PvgisYearly:
        # Latitude-aware: lower yield at higher latitudes.
        # Northern UK (~55N) ~= 850 kWh/kWp; southern UK (~50N) ~= 1050.
        lat_factor = max(0.0, min(1.0, (56.0 - lat) / 6.0))
        annual = (850 + 200 * lat_factor) * kwp
        return PvgisYearly(
            annual_kwh_per_kwp=annual / kwp if kwp > 0 else annual,
            optimum_tilt=35.0,
            optimum_azimuth=180.0,
        )


# ---------------------------------------------------------------------------
class MockSolarApiAdapter(SolarApiAdapter):
    """Returns synthesised insights — does NOT need network."""

    async def building_insights(self, lng: float, lat: float) -> SolarBuildingInsights:
        seed = _hash_to_unit("solar", lng, lat)
        # 20..120 panels, deterministic.
        n = int(20 + seed * 100)
        # Build a fake panel layout: NxM grid centered on the lat/lng.
        cols = max(4, int(math.sqrt(n)))
        rows = (n + cols - 1) // cols
        panels = []
        deg_per_m_lat = 1 / 111_320.0
        deg_per_m_lng = 1 / (111_320.0 * math.cos(math.radians(lat)))
        for i in range(n):
            r = i // cols
            c = i % cols
            offset_x = (c - cols / 2) * 1.6   # 1.6 m panel width
            offset_y = (r - rows / 2) * 1.0   # 1.0 m panel height
            panels.append({
                "center": [lng + offset_x * deg_per_m_lng, lat + offset_y * deg_per_m_lat],
                "azimuth_deg": 180.0,
                "width_m": 1.6,
                "height_m": 1.0,
                "yearly_kwh": 380 + 80 * _hash_to_unit("p", lng, lat, i),
            })
        annual = sum(p["yearly_kwh"] for p in panels)
        return SolarBuildingInsights(
            distance_to_request_m=2.5 + 5 * seed,
            roof_segments=[{
                "area_m2": n * 1.6,
                "azimuth_deg": 180.0,
                "pitch_deg": 25.0,
                "sunshine_kwh_per_m2_per_year": 950.0,
            }],
            panel_layout=panels,
            annual_kwh_estimate=annual,
            cost=AdapterCost(cents=0),    # mock: free
        )

    async def data_layers(self, lng: float, lat: float, *, radius_m: float = 50) -> SolarFluxLayer:
        # Return non-network URLs that the mock flux endpoint can shortcut on.
        return SolarFluxLayer(
            annual_flux_url="mock://annual",
            monthly_flux_url="mock://monthly",
            rgb_url=None, mask_url=None,
            bbox_4326=(
                lng - 0.0005, lat - 0.0003,
                lng + 0.0005, lat + 0.0003,
            ),
            cost=AdapterCost(cents=0),
        )


# ---------------------------------------------------------------------------
class MockIMDAdapter(IMDAdapter):
    async def lookup_postcode(self, postcode: str) -> IMDLookup:
        # Fixed deciles for known demo postcodes; hash for the rest.
        table = {
            "EC1Y 8AF": 4,   # Old Street: mid-deprivation
            "BS1 4DJ": 6,
        }
        pc_norm = postcode.strip().upper()
        if pc_norm in table:
            decile = table[pc_norm]
        else:
            decile = 1 + int(_hash_to_unit("imd", pc_norm) * 10)
            if decile > 10:
                decile = 10
        return IMDLookup(
            postcode=pc_norm,
            decile=decile,
            rank=decile * 3000,
        )


# ---------------------------------------------------------------------------
class MockCompaniesHouseAdapter(CompaniesHouseAdapter):
    """Generates plausible-looking officers from name hash."""

    _FIRST_NAMES = ["Sarah","James","Priya","Mohammed","Olivia","David","Aisha","Chen","Tom","Emma","Hassan","Sophie"]
    _LAST_NAMES  = ["PATEL","WILLIAMS","NGUYEN","SMITH","JOHNSON","KAUR","BROWN","LI","WILSON","TAYLOR","AHMED","CHEN"]
    _ROLES       = ["director","secretary","cfo","ceo","sustainability-officer"]

    async def search_company(self, name: str) -> list[CompaniesHouseSearchHit]:
        # Mock: pretend any name resolves to one company.
        seed = _hash_to_unit("ch_search", name)
        number = f"{int(seed * 99_999_999):08d}"
        return [CompaniesHouseSearchHit(
            company_number=number,
            title=name,
            address_snippet="London, United Kingdom",
            company_status="active",
        )]

    async def list_officers(self, company_number: str) -> list[CompaniesHouseOfficer]:
        n = 2 + int(_hash_to_unit("ch_n", company_number) * 4)   # 2..5
        out: list[CompaniesHouseOfficer] = []
        for i in range(n):
            f = self._FIRST_NAMES[int(_hash_to_unit("ch_f", company_number, i) * len(self._FIRST_NAMES)) % len(self._FIRST_NAMES)]
            l = self._LAST_NAMES[int(_hash_to_unit("ch_l", company_number, i) * len(self._LAST_NAMES)) % len(self._LAST_NAMES)]
            r = self._ROLES[int(_hash_to_unit("ch_r", company_number, i) * len(self._ROLES)) % len(self._ROLES)]
            out.append(CompaniesHouseOfficer(
                name=f"{l}, {f}",
                role=r,
                appointed_on="2018-01-01",
                resigned_on=None,
            ))
        return out


# ---------------------------------------------------------------------------
def all_mocks() -> dict[str, Any]:
    """Convenience for the factory."""
    return {
        "geocoding": MockGeocodingAdapter(),
        "weather":   MockWeatherAdapter(),
        "pvgis":     MockPvgisAdapter(),
        "solar":     MockSolarApiAdapter(),
        "imd":       MockIMDAdapter(),
        "ch":        MockCompaniesHouseAdapter(),
    }
