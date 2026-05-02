"""Pydantic model validation tests.

These guard the hard-won lessons:
- `geo` MUST be {point: GeoJSONPoint} — not a raw point.
- Polygons must close (last == first).
- Coordinates have correct lng,lat ordering with valid bounds.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from solarreach_shared.models import (
    GeoJSONPoint,
    GeoJSONPolygon,
    Lead,
    LeadGeo,
)


def _basic_lead_dict(**overrides):
    base = {
        "_id": "lead_test_0001",
        "client_slug": "client-test",
        "name": "Test Office Ltd",
        "premises_type": "Office",
        "address": "1 Demo Street, EC1Y 8AF",
        "postcode": "EC1Y 8AF",
        "geo": {"point": {"type": "Point", "coordinates": [-0.0879, 51.5232]}},
        "composite_score": 75.0,
        "score_breakdown": {"solar_roi": 80, "financial_health": 70, "social_impact": 60},
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return base


def test_geojson_point_valid() -> None:
    p = GeoJSONPoint(coordinates=(-0.0879, 51.5232))
    assert p.type == "Point"
    assert p.coordinates == (-0.0879, 51.5232)


def test_geojson_point_lng_out_of_bounds_rejected() -> None:
    with pytest.raises(ValidationError):
        GeoJSONPoint(coordinates=(200.0, 51.5232))


def test_geojson_point_lat_out_of_bounds_rejected() -> None:
    with pytest.raises(ValidationError):
        GeoJSONPoint(coordinates=(-0.0879, 95.0))


def test_polygon_must_close() -> None:
    # First and last point not identical
    with pytest.raises(ValidationError):
        GeoJSONPolygon(coordinates=[[
            (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0),  # not closed
        ]])


def test_polygon_too_few_points_rejected() -> None:
    with pytest.raises(ValidationError):
        GeoJSONPolygon(coordinates=[[(0.0, 0.0), (1.0, 0.0), (0.0, 0.0)]])


def test_polygon_closed_accepted() -> None:
    poly = GeoJSONPolygon(coordinates=[[
        (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)
    ]])
    assert poly.type == "Polygon"


def test_lead_geo_wrapper_required() -> None:
    """The CRITICAL test: a raw GeoJSONPoint at lead.geo must FAIL validation.

    This is the bug that took down the API in the prior session — geo must
    always be {point: ...}, never a bare point dict.
    """
    bad = _basic_lead_dict(geo={"type": "Point", "coordinates": [-0.0879, 51.5232]})
    with pytest.raises(ValidationError):
        Lead.model_validate(bad)


def test_lead_geo_wrapper_correct_shape_accepted() -> None:
    lead = Lead.model_validate(_basic_lead_dict())
    assert lead.geo.point.coordinates == (-0.0879, 51.5232)


def test_lead_composite_score_range_enforced() -> None:
    with pytest.raises(ValidationError):
        Lead.model_validate(_basic_lead_dict(composite_score=150.0))
    with pytest.raises(ValidationError):
        Lead.model_validate(_basic_lead_dict(composite_score=-1.0))


def test_lead_extra_fields_rejected() -> None:
    bad = _basic_lead_dict(invented_field="oops")
    with pytest.raises(ValidationError):
        Lead.model_validate(bad)


def test_lead_default_polygon_source_is_synthesized() -> None:
    lead = Lead.model_validate(_basic_lead_dict())
    assert lead.rooftop_polygon_source == "synthesized"
    assert lead.rooftop_polygon is None


def test_lead_geo_construct_directly() -> None:
    g = LeadGeo(point=GeoJSONPoint(coordinates=(-2.59, 51.45)))
    assert g.point.coordinates == (-2.59, 51.45)
