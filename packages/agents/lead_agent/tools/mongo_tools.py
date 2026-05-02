"""MongoDB I/O exposed as LangChain tools.

Hard rules baked in:
- Tools NEVER overwrite an existing INSPIRE rooftop polygon (CARDINAL RULE
  from the spec). update_lead_score only writes scoring fields.
- Audit log entries always go through record_audit_event so the recipient
  hashing / cost accounting is consistent.
- The Mongo client is created LAZILY on first tool call so that simply
  importing this module does not require a live database (matters for tests).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from langchain_core.tools import tool
from pymongo import MongoClient

from solarreach_shared.compliance import hash_recipient
from lead_agent.backends.mongo import APP_DB_NAME, get_mongo_client


# ---------------------------------------------------------------------------
# Lazy client cache — one per process; threadsafe (pymongo's MongoClient is).
# ---------------------------------------------------------------------------
_CLIENT: MongoClient | None = None


def _client() -> MongoClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = get_mongo_client()
    return _CLIENT


def _db():
    return _client()[APP_DB_NAME]


# ---------------------------------------------------------------------------
# fetch_unscored_leads
# ---------------------------------------------------------------------------
@tool
def fetch_unscored_leads(
    client_slug: Annotated[str, "Client slug, eg 'client-greensolar-uk'."],
    limit: Annotated[int, "Max leads to return. Cap 50 for hackathon safety."] = 10,
) -> str:
    """Find leads that need (re-)scoring. A lead 'needs scoring' if its
    composite_score is missing OR its enriched_at is null OR its updated_at
    is older than 30 days.

    Returns JSON string of a list of leads with {_id, name, postcode,
    premises_type, composite_score, enriched_at}. Limited to keep agent
    context small."""

    safe_limit = max(1, min(int(limit), 50))
    cursor = _db().leads.find(
        {
            "client_slug": client_slug,
            "$or": [
                {"composite_score": {"$exists": False}},
                {"composite_score": None},
                {"enriched_at": None},
            ],
        },
        projection={
            "_id": 1, "name": 1, "postcode": 1,
            "premises_type": 1, "composite_score": 1, "enriched_at": 1,
        },
    ).limit(safe_limit)

    out = []
    for doc in cursor:
        out.append({
            "_id": doc["_id"],
            "name": doc.get("name"),
            "postcode": doc.get("postcode"),
            "premises_type": doc.get("premises_type"),
            "composite_score": doc.get("composite_score"),
            "enriched_at": doc.get("enriched_at").isoformat() if doc.get("enriched_at") else None,
        })
    return json.dumps(out)


# ---------------------------------------------------------------------------
# get_lead
# ---------------------------------------------------------------------------
@tool
def get_lead(
    lead_id: Annotated[str, "Lead _id, eg 'lead_<sha1>_<run_uuid>'."],
) -> str:
    """Fetch one lead's full document. Returns a JSON string. Returns
    {\"error\": \"not_found\"} if missing.

    Strips the rooftop_polygon (it can be 1KB+ and waste agent context); the
    agent should not need it for scoring decisions. Use the dedicated
    get_lead_polygon tool if you really need it."""

    doc = _db().leads.find_one({"_id": lead_id})
    if not doc:
        return json.dumps({"error": "not_found", "lead_id": lead_id})
    doc.pop("rooftop_polygon", None)
    # Stringify datetimes for JSON.
    for k in ("created_at", "updated_at", "enriched_at"):
        if isinstance(doc.get(k), datetime):
            doc[k] = doc[k].isoformat()
    return json.dumps(doc, default=str)


# ---------------------------------------------------------------------------
# update_lead_score
# ---------------------------------------------------------------------------
@tool
def update_lead_score(
    lead_id: Annotated[str, "Lead _id."],
    composite_score: Annotated[float, "0-100 composite score."],
    score_breakdown_json: Annotated[str, "JSON of {solar_roi, financial_health, social_impact} keys, all 0-100."],
    mark_enriched: Annotated[bool, "Set enriched_at = now (used post-gate)."] = False,
) -> str:
    """Write the composite score + breakdown back to the lead.

    DOES NOT touch rooftop_polygon, inspire_id, panel_layout, or financial
    — those are owned by other workflows. CARDINAL RULE: never overwrite an
    INSPIRE polygon from a scoring agent.

    Returns JSON {ok: bool, modified: int}."""

    try:
        breakdown = json.loads(score_breakdown_json)
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"invalid breakdown JSON: {e}"})
    required = {"solar_roi", "financial_health", "social_impact"}
    if not required.issubset(breakdown.keys()):
        return json.dumps({"ok": False, "error": f"breakdown missing keys: {required - breakdown.keys()}"})
    if not (0 <= composite_score <= 100):
        return json.dumps({"ok": False, "error": "composite_score out of [0,100]"})

    update: dict[str, Any] = {
        "composite_score": float(composite_score),
        "score_breakdown": {k: float(v) for k, v in breakdown.items()},
        "updated_at": datetime.now(timezone.utc),
    }
    if mark_enriched:
        update["enriched_at"] = datetime.now(timezone.utc)

    res = _db().leads.update_one({"_id": lead_id}, {"$set": update})
    if res.matched_count == 0:
        return json.dumps({"ok": False, "error": "lead not found", "lead_id": lead_id})
    return json.dumps({"ok": True, "modified": res.modified_count})


# ---------------------------------------------------------------------------
# update_lead_financial
# ---------------------------------------------------------------------------
@tool
def update_lead_financial(
    lead_id: Annotated[str, "Lead _id."],
    financial_json: Annotated[str, "JSON of {capex_gbp, annual_saving_gbp, payback_years, npv_25yr_gbp, irr_pct}."],
    panels_count: Annotated[int, "Total panels installed."],
    annual_kwh: Annotated[float, "Year-1 generation kWh."],
) -> str:
    """Write the financial breakdown + panels_count + annual_kwh into the
    lead. Used post-gate after compute_financials.

    Returns JSON {ok: bool, modified: int}."""

    try:
        fin = json.loads(financial_json)
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"invalid financial JSON: {e}"})
    required = {"capex_gbp", "annual_saving_gbp", "payback_years", "npv_25yr_gbp"}
    if not required.issubset(fin.keys()):
        return json.dumps({"ok": False, "error": f"financial missing keys: {required - fin.keys()}"})

    res = _db().leads.update_one(
        {"_id": lead_id},
        {"$set": {
            "financial": fin,
            "panels_count": int(panels_count),
            "annual_kwh": float(annual_kwh),
            "enriched_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    if res.matched_count == 0:
        return json.dumps({"ok": False, "error": "lead not found"})
    return json.dumps({"ok": True, "modified": res.modified_count})


# ---------------------------------------------------------------------------
# record_audit_event
# ---------------------------------------------------------------------------
@tool
def record_audit_event(
    actor: Annotated[str, "Service that did the thing, eg 'agent.lead_researcher'."],
    action: Annotated[str, "Verb-object, eg 'score.compute' or 'enrichment.solar_api'."],
    cost_cents: Annotated[int, "Integer cents. 0 if free."] = 0,
    lead_id: Annotated[str | None, "Optional lead _id."] = None,
    client_slug: Annotated[str | None, "Optional client slug."] = None,
    recipient_email: Annotated[str | None, "Email if relevant. Will be sha256-hashed before write."] = None,
    metadata_json: Annotated[str, "JSON object, eg '{\"thread_id\": \"abc\"}'. Default empty."] = "{}",
) -> str:
    """Append an immutable audit event. Recipients are sha256-hashed —
    raw email/phone are NEVER stored.

    Returns JSON {ok: bool, _id: str}."""

    try:
        metadata = json.loads(metadata_json) if metadata_json else {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata_json must decode to an object")
    except (json.JSONDecodeError, ValueError) as e:
        return json.dumps({"ok": False, "error": f"invalid metadata: {e}"})

    event_id = f"audit_{uuid.uuid4().hex[:16]}"
    doc: dict[str, Any] = {
        "_id": event_id,
        "ts": datetime.now(timezone.utc),
        "actor": actor,
        "action": action,
        "cost_cents": max(0, int(cost_cents)),
        "lead_id": lead_id,
        "client_slug": client_slug,
        "recipient_hash": hash_recipient(recipient_email) if recipient_email else None,
        "metadata": metadata,
    }
    _db().audit_log.insert_one(doc)
    return json.dumps({"ok": True, "_id": event_id})


# ---------------------------------------------------------------------------
# count_leads
# ---------------------------------------------------------------------------
@tool
def count_leads(
    client_slug: Annotated[str, "Client slug."],
    only_unscored: Annotated[bool, "If true, only count leads missing composite_score."] = False,
) -> str:
    """Quick count for the agent to gauge work remaining.
    Returns JSON {total: int, unscored: int}."""

    base = {"client_slug": client_slug}
    total = _db().leads.count_documents(base)
    if only_unscored:
        unscored = _db().leads.count_documents({
            **base,
            "$or": [
                {"composite_score": {"$exists": False}},
                {"composite_score": None},
                {"enriched_at": None},
            ],
        })
    else:
        unscored = total
    return json.dumps({"total": total, "unscored": unscored})


def all_mongo_tools() -> list:
    return [
        fetch_unscored_leads,
        get_lead,
        update_lead_score,
        update_lead_financial,
        record_audit_event,
        count_leads,
    ]
