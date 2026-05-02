"""Discovery: gather the CHEAP signals that feed the composite score.

Order of operations (all on free / mock adapters):
1. Geocode postcode -> lng/lat (Google free tier or postcodes.io)
2. PVGIS yearly yield at lng/lat -> annual_kwh_per_kwp
3. IMD decile from postcodes.io -> social_impact input
4. (optional) mock Companies House -> approximated financial health

NO Solar API call here. NO paid Hunter call here. Those happen post-gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..adapters import factory


@dataclass(frozen=True)
class DiscoverySignals:
    lng: float
    lat: float
    formatted_address: str
    annual_kwh_per_kwp: float
    optimum_tilt: float
    optimum_azimuth: float
    imd_decile: int                 # 1 = most deprived, 10 = least
    company_health_score: float | None  # 0..100, mock for unknown companies
    cost_cents: int


async def discover(postcode: str, *, company_name: str | None = None) -> DiscoverySignals:
    geocoder = factory.get_adapter("geocoding")
    pvgis = factory.get_adapter("pvgis")
    imd = factory.get_adapter("imd")

    geo = await geocoder.geocode_postcode(postcode)
    pv = await pvgis.yearly_yield(geo.lng, geo.lat, kwp=1.0)
    try:
        imd_res = await imd.lookup_postcode(postcode)
        imd_decile = imd_res.decile
        imd_cost = imd_res.cost.cents
    except Exception:
        imd_decile = 5   # neutral fallback
        imd_cost = 0

    # Optional company health — mock for now; real CH comes post-gate.
    company_health: float | None = None
    if company_name:
        # cheap mock: name-hash based health (real signal comes later)
        ch = factory.get_adapter("ch", mode="mock")  # always mock at discovery
        hits = await ch.search_company(company_name)
        if hits:
            # naive: longer companies tend to be older = healthier (mock heuristic)
            company_health = 50 + min(40, len(company_name)) / 2

    total_cost = geo.cost.cents + getattr(pv.cost, "cents", 0) + imd_cost
    return DiscoverySignals(
        lng=geo.lng, lat=geo.lat,
        formatted_address=geo.formatted_address,
        annual_kwh_per_kwp=pv.annual_kwh_per_kwp,
        optimum_tilt=pv.optimum_tilt,
        optimum_azimuth=pv.optimum_azimuth,
        imd_decile=imd_decile,
        company_health_score=company_health,
        cost_cents=total_cost,
    )
