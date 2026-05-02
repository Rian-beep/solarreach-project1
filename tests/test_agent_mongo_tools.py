"""Tests for the Mongo tool wrappers.

We patch the lazy `_client()` accessor with `mongomock.MongoClient` so tests
run with no live Mongo. mongomock supports the operations we use here
(find/insert_one/update_one/count_documents) but NOT: aggregation pipelines
with $geoNear, GridFS, transactions, or $jsonSchema validation. Tests that
need any of those should be flagged as integration tests instead.
"""

from __future__ import annotations

import json

import mongomock
import pytest


@pytest.fixture(autouse=True)
def _patch_mongo_client(monkeypatch: pytest.MonkeyPatch):
    """Replace the lazy MongoClient accessor with a mongomock instance.

    We blow away the module-level client cache so each test starts clean."""

    import lead_agent.tools.mongo_tools as mt

    fake = mongomock.MongoClient()
    monkeypatch.setattr(mt, "_CLIENT", fake)
    monkeypatch.setattr(mt, "_client", lambda: fake)
    yield fake


def _seed_lead(client, *, lead_id="lead_test_0001", **overrides):
    from datetime import datetime, timezone
    base = {
        "_id": lead_id,
        "client_slug": "client-greensolar-uk",
        "name": "Test Office Ltd",
        "premises_type": "Office",
        "address": "1 Demo Street",
        "postcode": "EC1Y 8AF",
        "geo": {"point": {"type": "Point", "coordinates": [-0.0879, 51.5232]}},
        "composite_score": None,
        "score_breakdown": {},
        "panel_layout": [],
        "panels_count": 0,
        "rooftop_polygon": None,
        "rooftop_polygon_source": "synthesized",
        "inspire_id": None,
        "company_id": "co_demo",
        "annual_kwh": None,
        "financial": None,
        "enriched_at": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    client["solarreach"]["leads"].insert_one(base)
    return base


# ---------------------------------------------------------------------------
def test_count_leads_total_and_unscored(_patch_mongo_client):
    from lead_agent.tools.mongo_tools import count_leads

    _seed_lead(_patch_mongo_client, lead_id="a")
    _seed_lead(_patch_mongo_client, lead_id="b", composite_score=75.0,
               enriched_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))

    res = json.loads(count_leads.invoke({"client_slug": "client-greensolar-uk", "only_unscored": False}))
    assert res["total"] == 2

    res = json.loads(count_leads.invoke({"client_slug": "client-greensolar-uk", "only_unscored": True}))
    assert res["unscored"] == 1


def test_fetch_unscored_leads_returns_only_unscored(_patch_mongo_client):
    from lead_agent.tools.mongo_tools import fetch_unscored_leads
    from datetime import datetime, timezone

    _seed_lead(_patch_mongo_client, lead_id="unscored_1")
    _seed_lead(_patch_mongo_client, lead_id="scored_1",
               composite_score=80.0, enriched_at=datetime.now(timezone.utc))

    out = json.loads(fetch_unscored_leads.invoke({"client_slug": "client-greensolar-uk", "limit": 10}))
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["_id"] == "unscored_1"


def test_fetch_unscored_leads_caps_limit_at_50(_patch_mongo_client):
    """Even if the LLM passes 9999, we cap at 50 to keep context small."""
    from lead_agent.tools.mongo_tools import fetch_unscored_leads

    for i in range(60):
        _seed_lead(_patch_mongo_client, lead_id=f"u_{i:03d}")

    out = json.loads(fetch_unscored_leads.invoke({"client_slug": "client-greensolar-uk", "limit": 9999}))
    assert len(out) == 50


def test_get_lead_returns_doc_or_error(_patch_mongo_client):
    from lead_agent.tools.mongo_tools import get_lead

    _seed_lead(_patch_mongo_client, lead_id="present")
    out = json.loads(get_lead.invoke({"lead_id": "present"}))
    assert out["_id"] == "present"
    assert out["name"] == "Test Office Ltd"
    # Polygon stripped to save context.
    assert "rooftop_polygon" not in out

    out = json.loads(get_lead.invoke({"lead_id": "absent"}))
    assert out["error"] == "not_found"


def test_update_lead_score_writes_fields_and_skips_polygon(_patch_mongo_client):
    from lead_agent.tools.mongo_tools import update_lead_score

    _seed_lead(_patch_mongo_client, lead_id="s1",
               rooftop_polygon={"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]},
               inspire_id="inspire-keepme")

    res = json.loads(update_lead_score.invoke({
        "lead_id": "s1",
        "composite_score": 84.5,
        "score_breakdown_json": json.dumps({"solar_roi": 90, "financial_health": 80, "social_impact": 75}),
        "mark_enriched": True,
    }))
    assert res["ok"] is True

    doc = _patch_mongo_client["solarreach"]["leads"].find_one({"_id": "s1"})
    assert doc["composite_score"] == 84.5
    assert doc["score_breakdown"]["solar_roi"] == 90
    assert doc["enriched_at"] is not None
    # CRITICAL: polygon and inspire_id MUST be untouched.
    assert doc["inspire_id"] == "inspire-keepme"
    assert doc["rooftop_polygon"]["coordinates"] == [[[0,0],[1,0],[1,1],[0,1],[0,0]]]


def test_update_lead_score_rejects_out_of_range(_patch_mongo_client):
    from lead_agent.tools.mongo_tools import update_lead_score
    _seed_lead(_patch_mongo_client, lead_id="s2")

    res = json.loads(update_lead_score.invoke({
        "lead_id": "s2",
        "composite_score": 150.0,
        "score_breakdown_json": json.dumps({"solar_roi": 1, "financial_health": 1, "social_impact": 1}),
    }))
    assert res["ok"] is False


def test_update_lead_score_rejects_missing_breakdown_keys(_patch_mongo_client):
    from lead_agent.tools.mongo_tools import update_lead_score
    _seed_lead(_patch_mongo_client, lead_id="s3")

    res = json.loads(update_lead_score.invoke({
        "lead_id": "s3",
        "composite_score": 80.0,
        "score_breakdown_json": json.dumps({"solar_roi": 80}),  # missing keys
    }))
    assert res["ok"] is False
    assert "missing keys" in res["error"]


def test_update_lead_score_rejects_invalid_json(_patch_mongo_client):
    from lead_agent.tools.mongo_tools import update_lead_score
    _seed_lead(_patch_mongo_client, lead_id="s4")

    res = json.loads(update_lead_score.invoke({
        "lead_id": "s4",
        "composite_score": 80.0,
        "score_breakdown_json": "not-json",
    }))
    assert res["ok"] is False


def test_update_lead_financial_writes_full_breakdown(_patch_mongo_client):
    from lead_agent.tools.mongo_tools import update_lead_financial
    _seed_lead(_patch_mongo_client, lead_id="f1")

    fin = {
        "capex_gbp": 35700.0,
        "annual_saving_gbp": 8160.0,
        "payback_years": 4.4,
        "npv_25yr_gbp": 64000.0,
        "irr_pct": 22.2,
    }
    res = json.loads(update_lead_financial.invoke({
        "lead_id": "f1",
        "financial_json": json.dumps(fin),
        "panels_count": 100,
        "annual_kwh": 40000.0,
    }))
    assert res["ok"] is True

    doc = _patch_mongo_client["solarreach"]["leads"].find_one({"_id": "f1"})
    assert doc["panels_count"] == 100
    assert doc["annual_kwh"] == 40000.0
    assert doc["financial"]["capex_gbp"] == 35700.0
    assert doc["enriched_at"] is not None


def test_record_audit_event_hashes_recipient(_patch_mongo_client):
    from lead_agent.tools.mongo_tools import record_audit_event
    from solarreach_shared.compliance import hash_recipient

    res = json.loads(record_audit_event.invoke({
        "actor": "agent.lead_researcher",
        "action": "score.compute",
        "cost_cents": 5,
        "lead_id": "lead_x",
        "recipient_email": "John.Doe@Example.COM",
        "metadata_json": json.dumps({"thread_id": "test-1"}),
    }))
    assert res["ok"] is True

    audit = _patch_mongo_client["solarreach"]["audit_log"].find_one({"_id": res["_id"]})
    assert audit is not None
    # CRITICAL: raw email NEVER stored.
    assert audit["recipient_hash"] == hash_recipient("John.Doe@Example.COM")
    serialized = json.dumps(audit, default=str)
    assert "John.Doe" not in serialized.lower() or "john.doe" not in serialized.lower()


def test_record_audit_event_invalid_metadata_returns_error(_patch_mongo_client):
    from lead_agent.tools.mongo_tools import record_audit_event

    res = json.loads(record_audit_event.invoke({
        "actor": "agent.lead_researcher",
        "action": "score.compute",
        "metadata_json": "not-json",
    }))
    assert res["ok"] is False
