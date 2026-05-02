"""End-to-end discovery test using the mock adapters."""

from __future__ import annotations

import asyncio

import pytest

from scoring_worker.adapters import factory
from scoring_worker.adapters.mocks import (
    MockCompaniesHouseAdapter,
    MockGeocodingAdapter,
    MockIMDAdapter,
    MockPvgisAdapter,
    MockSolarApiAdapter,
)
from scoring_worker.pipeline.discovery import discover


@pytest.fixture(autouse=True)
def _reset_adapter_singletons(monkeypatch: pytest.MonkeyPatch):
    # Force mock mode regardless of env state
    monkeypatch.setenv("SOLARREACH_ADAPTER_MODE", "mock")
    # Wipe cached singletons so per-test env changes take effect
    import scoring_worker.adapters.factory as f
    f._MOCK_INSTANCES = None
    f._REAL_INSTANCES = None


def test_factory_returns_mock_by_default() -> None:
    g = factory.get_adapter("geocoding")
    assert isinstance(g, MockGeocodingAdapter)
    assert isinstance(factory.get_adapter("pvgis"), MockPvgisAdapter)
    assert isinstance(factory.get_adapter("imd"), MockIMDAdapter)
    assert isinstance(factory.get_adapter("solar"), MockSolarApiAdapter)
    assert isinstance(factory.get_adapter("ch"), MockCompaniesHouseAdapter)


def test_factory_unknown_adapter_raises() -> None:
    with pytest.raises(KeyError):
        factory.get_adapter("nonexistent")


def test_factory_invalid_mode_raises() -> None:
    with pytest.raises(ValueError):
        factory.get_adapter("geocoding", mode="banana")


def test_discover_known_postcode_returns_plausible_signals() -> None:
    sig = asyncio.run(discover("EC1Y 8AF", company_name="Demo Office Ltd"))
    # Known table entry — Old Street area
    assert -0.10 < sig.lng < -0.05
    assert 51.50 < sig.lat < 51.55
    assert sig.formatted_address.startswith("EC1Y 8AF")
    # PVGIS yield in plausible UK band
    assert 800 <= sig.annual_kwh_per_kwp <= 1100
    # IMD decile is the fixed mock value (4)
    assert sig.imd_decile == 4
    # Mock returns a non-null company health when name is given
    assert sig.company_health_score is not None
    assert 50 <= sig.company_health_score <= 100
    # Cost is zero in mock mode
    assert sig.cost_cents == 0


def test_discover_unknown_postcode_falls_back_safely() -> None:
    sig = asyncio.run(discover("ZZ9 9ZZ"))
    # Mock geocoder uses a London fallback for unknown postcodes
    assert -1.0 < sig.lng < 1.0
    assert 50.0 < sig.lat < 53.0
    # IMD still returns SOMETHING in [1, 10]
    assert 1 <= sig.imd_decile <= 10
    # No company name -> no company health
    assert sig.company_health_score is None


def test_discover_is_deterministic() -> None:
    a = asyncio.run(discover("BS1 4DJ", company_name="Bristol Office Ltd"))
    b = asyncio.run(discover("BS1 4DJ", company_name="Bristol Office Ltd"))
    assert a.lng == b.lng
    assert a.lat == b.lat
    assert a.imd_decile == b.imd_decile
    assert a.annual_kwh_per_kwp == b.annual_kwh_per_kwp


def test_mock_solar_api_panel_layout_is_centered() -> None:
    solar = factory.get_adapter("solar")
    out = asyncio.run(solar.building_insights(-0.0879, 51.5232))
    assert len(out.panel_layout) >= 20
    assert out.distance_to_request_m < 10
    assert out.annual_kwh_estimate > 0
    # Every panel should have all required fields
    for panel in out.panel_layout:
        assert "center" in panel
        assert "azimuth_deg" in panel
        assert "yearly_kwh" in panel


def test_mock_companies_house_returns_plausible_officers() -> None:
    ch = factory.get_adapter("ch")
    hits = asyncio.run(ch.search_company("Some Demo Office Ltd"))
    assert len(hits) >= 1
    officers = asyncio.run(ch.list_officers(hits[0].company_number))
    assert 2 <= len(officers) <= 5
    # Mock format: "LASTNAME, Firstname"
    for o in officers:
        assert "," in o.name
        assert o.role in {"director","secretary","cfo","ceo","sustainability-officer"}
