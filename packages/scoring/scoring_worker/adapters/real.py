"""Real adapters — only used when SOLARREACH_ADAPTER_MODE=real or per-call.

These cost money / have rate limits. Project 1 ships them as scaffolds so
downstream projects can wire them; mocks remain the default in dev/CI.

Hard-won lessons baked in (see CARDINAL RULES section of system prompt):
- Google API key MUST have Application restrictions = None (HTTP referrer
  blocks server-side calls — 403 API_KEY_HTTP_REFERRER_BLOCKED).
- Solar API findClosest can return a building 100-300m away. We reject if
  distance > SOLAR_API_MAX_DISTANCE_M (80m) — the "panels in courtyard" bug.
- Solar API dataLayers GeoTIFF URLs need ?key=KEY appended.
- Companies House uses HTTP Basic with key as username, NO password.
- CH rate limit: 600/5min — we sleep 0.6s between calls.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from solarreach_shared.constants import SOLAR_API_MAX_DISTANCE_M

from ._base import (
    AdapterCost,
    AdapterError,
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

GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_SOLAR_BUILDING_URL = "https://solar.googleapis.com/v1/buildingInsights:findClosest"
GOOGLE_SOLAR_DATALAYERS_URL = "https://solar.googleapis.com/v1/dataLayers:get"
GOOGLE_WEATHER_URL = "https://weather.googleapis.com/v1/forecast:lookup"
PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
POSTCODES_IO_URL = "https://api.postcodes.io/postcodes"
CH_BASE = "https://api.company-information.service.gov.uk"

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise AdapterError("MISSING_ENV", f"env var {name} required for real adapter")
    return val


# ---------------------------------------------------------------------------
class GoogleGeocodingAdapter(GeocodingAdapter):
    async def geocode_postcode(self, postcode: str) -> GeocodeResult:
        key = _require_env("GOOGLE_API_KEY")
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(GOOGLE_GEOCODE_URL, params={
                "address": postcode, "components": "country:GB", "key": key,
            })
        if r.status_code != 200:
            raise AdapterError("HTTP", f"geocode {r.status_code}: {r.text[:200]}", http_status=r.status_code)
        body = r.json()
        if body.get("status") != "OK" or not body.get("results"):
            raise AdapterError("NO_RESULT", f"geocode status={body.get('status')}")
        top = body["results"][0]
        loc = top["geometry"]["location"]
        return GeocodeResult(
            lng=float(loc["lng"]), lat=float(loc["lat"]),
            formatted_address=top.get("formatted_address", postcode),
            confidence=0.95 if top["geometry"].get("location_type") == "ROOFTOP" else 0.7,
            cost=AdapterCost(cents=1),  # Google geocoding ~$0.005, round to 1 cent
        )


# ---------------------------------------------------------------------------
class GoogleWeatherAdapter(WeatherAdapter):
    async def forecast(self, lng: float, lat: float, *, days: int = 5) -> WeatherForecast:
        key = _require_env("GOOGLE_API_KEY")
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(GOOGLE_WEATHER_URL, params={
                "location.latitude": lat, "location.longitude": lng,
                "days": days, "key": key,
            })
        if r.status_code != 200:
            raise AdapterError("HTTP", f"weather {r.status_code}: {r.text[:200]}", http_status=r.status_code)
        # Real API response shape varies — keep it loose.
        body = r.json()
        days_out: list[dict[str, Any]] = []
        for d in body.get("dailyForecasts", [])[:days]:
            days_out.append({
                "date": d.get("date"),
                "irradiance_kwh_m2": d.get("solarIrradianceKwhPerSqm", 3.5),
                "cloud_cover_pct": d.get("cloudCoverPercent", 50),
                "temp_c": d.get("temperatureMaxC", 15),
            })
        return WeatherForecast(
            cell_id=f"goog-{round(lng,2)}_{round(lat,2)}",
            days=days_out,
            cost=AdapterCost(cents=1),
        )


# ---------------------------------------------------------------------------
class PvgisAdapterReal(PvgisAdapter):
    """Free EU Joint Research Centre API. No key. Rate-limited."""

    async def yearly_yield(self, lng: float, lat: float, *, kwp: float = 1.0) -> PvgisYearly:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(PVGIS_URL, params={
                "lat": lat, "lon": lng,
                "peakpower": kwp, "loss": 14, "outputformat": "json",
                "optimalangles": 1, "pvtechchoice": "crystSi",
                "mountingplace": "building",
            })
        if r.status_code != 200:
            raise AdapterError("HTTP", f"pvgis {r.status_code}: {r.text[:200]}", http_status=r.status_code)
        body = r.json()
        totals = body["outputs"]["totals"]["fixed"]
        annual = float(totals["E_y"])
        return PvgisYearly(
            annual_kwh_per_kwp=annual / kwp if kwp > 0 else annual,
            optimum_tilt=float(body["inputs"]["mounting_system"]["fixed"]["slope"]["value"]),
            optimum_azimuth=180.0 + float(body["inputs"]["mounting_system"]["fixed"]["azimuth"]["value"]),
        )


# ---------------------------------------------------------------------------
class GoogleSolarApiAdapter(SolarApiAdapter):
    async def building_insights(self, lng: float, lat: float) -> SolarBuildingInsights:
        key = _require_env("GOOGLE_API_KEY")
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(GOOGLE_SOLAR_BUILDING_URL, params={
                "location.latitude": lat,
                "location.longitude": lng,
                "requiredQuality": "HIGH",
                "key": key,
            })
        if r.status_code == 404:
            raise AdapterError("NO_BUILDING", "Solar API has no insights at this point", http_status=404)
        if r.status_code != 200:
            raise AdapterError("HTTP", f"solar {r.status_code}: {r.text[:200]}", http_status=r.status_code)
        body = r.json()

        # CRITICAL: distance check. Solar API returns nearest known building,
        # which can be 100-300m away. Reject if too far.
        center = body.get("center", {})
        if not center:
            raise AdapterError("NO_CENTER", "Solar API response missing center")
        from math import asin, cos, radians, sin, sqrt
        dlat = radians(center["latitude"] - lat)
        dlng = radians(center["longitude"] - lng)
        a = sin(dlat / 2) ** 2 + cos(radians(lat)) * cos(radians(center["latitude"])) * sin(dlng / 2) ** 2
        distance_m = 2 * 6371000 * asin(sqrt(a))
        if distance_m > SOLAR_API_MAX_DISTANCE_M:
            raise AdapterError(
                "BUILDING_TOO_FAR",
                f"nearest building is {distance_m:.0f}m away (limit {SOLAR_API_MAX_DISTANCE_M}m)",
            )

        sp = body.get("solarPotential", {})
        # The full panel array — server-side roof clip happens in the pipeline
        # against the INSPIRE polygon, NOT here.
        panels = []
        for p in sp.get("solarPanels", []):
            c = p.get("center", {})
            panels.append({
                "center": [float(c["longitude"]), float(c["latitude"])],
                "azimuth_deg": float(p.get("orientation", 180)),
                "width_m": float(sp.get("panelWidthMeters", 1.045)),
                "height_m": float(sp.get("panelHeightMeters", 1.879)),
                "yearly_kwh": float(p.get("yearlyEnergyDcKwh", 380)),
            })
        return SolarBuildingInsights(
            distance_to_request_m=distance_m,
            roof_segments=sp.get("roofSegmentStats", []),
            panel_layout=panels,
            annual_kwh_estimate=float(sp.get("maxArrayAnnualEnergyDcKwh", 0.0)),
            cost=AdapterCost(cents=10),   # ~$0.10/call — a rounding choice
        )

    async def data_layers(self, lng: float, lat: float, *, radius_m: float = 50) -> SolarFluxLayer:
        key = _require_env("GOOGLE_API_KEY")
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(GOOGLE_SOLAR_DATALAYERS_URL, params={
                "location.latitude": lat, "location.longitude": lng,
                "radiusMeters": radius_m, "view": "FULL_LAYERS",
                "requiredQuality": "HIGH", "pixelSizeMeters": 0.5,
                "key": key,
            })
        if r.status_code != 200:
            raise AdapterError("HTTP", f"dataLayers {r.status_code}: {r.text[:200]}", http_status=r.status_code)
        body = r.json()

        def _with_key(url: str | None) -> str | None:
            if not url:
                return None
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}key={key}"

        bbox = body.get("imageryProcessedDate", {})  # placeholder; real bbox usually in `boundingBox`
        bb = body.get("boundingBox", {})
        sw = bb.get("sw", {})
        ne = bb.get("ne", {})
        bbox_4326 = (
            float(sw.get("longitude", lng - 0.0005)),
            float(sw.get("latitude", lat - 0.0003)),
            float(ne.get("longitude", lng + 0.0005)),
            float(ne.get("latitude", lat + 0.0003)),
        )
        return SolarFluxLayer(
            annual_flux_url=_with_key(body.get("annualFluxUrl")) or "",
            monthly_flux_url=_with_key(body.get("monthlyFluxUrl")),
            rgb_url=_with_key(body.get("rgbUrl")),
            mask_url=_with_key(body.get("maskUrl")),
            bbox_4326=bbox_4326,
            cost=AdapterCost(cents=5),
        )


# ---------------------------------------------------------------------------
class PostcodesIoIMDAdapter(IMDAdapter):
    """Free, unauthenticated IMD lookup."""

    async def lookup_postcode(self, postcode: str) -> IMDLookup:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(f"{POSTCODES_IO_URL}/{postcode}")
        if r.status_code == 404:
            raise AdapterError("NOT_FOUND", f"postcode {postcode} not in postcodes.io")
        if r.status_code != 200:
            raise AdapterError("HTTP", f"imd {r.status_code}", http_status=r.status_code)
        body = r.json().get("result", {})
        # postcodes.io returns deprivation rank + deciles for England only.
        codes = body.get("codes", {})
        rank = codes.get("imd", 0) or 0
        # Convert rank → decile (1 = most deprived, 10 = least). Approx.
        # England has ~32,844 LSOAs. Decile = ceil(rank / 3284.4).
        if rank <= 0:
            decile = 5
        else:
            decile = max(1, min(10, ((rank - 1) // 3285) + 1))
        return IMDLookup(postcode=body.get("postcode", postcode), decile=decile, rank=rank)


# ---------------------------------------------------------------------------
class CompaniesHouseAdapterReal(CompaniesHouseAdapter):
    """HTTP Basic auth: username = API key, no password."""

    _LAST_CALL: float = 0.0   # crude rate limiter — instance state

    async def _wait(self) -> None:
        # 600 req / 5 min = 0.5s/req; 0.6 to be safe.
        loop = asyncio.get_running_loop()
        now = loop.time()
        if now - self._LAST_CALL < 0.6:
            await asyncio.sleep(0.6 - (now - self._LAST_CALL))
        self._LAST_CALL = loop.time()

    async def search_company(self, name: str) -> list[CompaniesHouseSearchHit]:
        key = _require_env("COMPANIES_HOUSE_API_KEY")
        await self._wait()
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, auth=(key, "")) as client:
            r = await client.get(f"{CH_BASE}/search/companies", params={"q": name, "items_per_page": 5})
        if r.status_code == 401:
            raise AdapterError("AUTH", "Companies House key invalid (regenerate at developer.company-information.service.gov.uk)", http_status=401)
        if r.status_code != 200:
            raise AdapterError("HTTP", f"ch search {r.status_code}: {r.text[:200]}", http_status=r.status_code)
        out = []
        for hit in r.json().get("items", []):
            out.append(CompaniesHouseSearchHit(
                company_number=hit.get("company_number", ""),
                title=hit.get("title", ""),
                address_snippet=hit.get("address_snippet"),
                company_status=hit.get("company_status"),
            ))
        return out

    async def list_officers(self, company_number: str) -> list[CompaniesHouseOfficer]:
        key = _require_env("COMPANIES_HOUSE_API_KEY")
        await self._wait()
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, auth=(key, "")) as client:
            r = await client.get(f"{CH_BASE}/company/{company_number}/officers", params={"items_per_page": 35})
        if r.status_code == 401:
            raise AdapterError("AUTH", "Companies House key invalid", http_status=401)
        if r.status_code == 404:
            return []
        if r.status_code != 200:
            raise AdapterError("HTTP", f"ch officers {r.status_code}: {r.text[:200]}", http_status=r.status_code)
        out = []
        for o in r.json().get("items", []):
            if o.get("resigned_on"):
                continue   # active only
            out.append(CompaniesHouseOfficer(
                name=o.get("name", ""),                    # "LASTNAME, Firstname" raw
                role=o.get("officer_role", "director"),
                appointed_on=o.get("appointed_on"),
                resigned_on=o.get("resigned_on"),
            ))
        return out


# ---------------------------------------------------------------------------
def all_real() -> dict[str, Any]:
    return {
        "geocoding": GoogleGeocodingAdapter(),
        "weather":   GoogleWeatherAdapter(),
        "pvgis":     PvgisAdapterReal(),
        "solar":     GoogleSolarApiAdapter(),
        "imd":       PostcodesIoIMDAdapter(),
        "ch":        CompaniesHouseAdapterReal(),
    }
