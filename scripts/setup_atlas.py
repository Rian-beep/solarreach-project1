#!/usr/bin/env python3
"""Standalone Atlas setup: collections + validators + indexes via pymongo.

Replaces the four mongosh init scripts (02-collections.js, 03-validators.js,
04-indexes.js, 05-agent-databases.js) with a single Python script that
needs only pymongo. Useful when:
  - You don't want to install mongosh
  - You want to run setup from Colab / notebook / CI
  - You're using Atlas (no docker-entrypoint-initdb.d)

Skips 01-users.js because Atlas already manages users via the UI.

Usage:
  export MONGO_URI='mongodb+srv://user:pwd@cluster.../solarreach?authSource=admin'
  python scripts/setup_atlas.py

Idempotent — safe to re-run.
"""

from __future__ import annotations

import os
import sys

try:
    from pymongo import ASCENDING, DESCENDING, GEOSPHERE, MongoClient
    from pymongo.errors import CollectionInvalid, OperationFailure
except ImportError:
    print("ERROR: pip install pymongo", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Step 1: Standard + time-series collections in solarreach DB
# ---------------------------------------------------------------------------
STANDARD_COLLECTIONS = [
    "leads", "companies", "directors", "inspire_polygons", "land_registry",
    "clients", "audit_log", "outreach_variants", "inbound_leads",
    "suppression_list", "webhooks_inbox",
]

TIME_SERIES_COLLECTIONS = [
    {"name": "energy_yield_ts", "timeField": "ts", "metaField": "meta", "granularity": "hours"},
    {"name": "weather_ts",      "timeField": "ts", "metaField": "meta", "granularity": "hours"},
    {"name": "calls_ts",        "timeField": "ts", "metaField": "meta", "granularity": "seconds"},
]


def step_1_collections(db) -> None:
    print(f"\n[1/4] creating collections in {db.name}")
    existing = set(db.list_collection_names())

    for name in STANDARD_COLLECTIONS:
        if name in existing:
            print(f"  - {name} (exists, skipped)")
            continue
        db.create_collection(name)
        print(f"  + {name}")

    for spec in TIME_SERIES_COLLECTIONS:
        if spec["name"] in existing:
            print(f"  - {spec['name']} (exists, skipped)")
            continue
        try:
            db.create_collection(
                spec["name"],
                timeseries={
                    "timeField": spec["timeField"],
                    "metaField": spec["metaField"],
                    "granularity": spec["granularity"],
                },
            )
            print(f"  + {spec['name']} (time-series, granularity={spec['granularity']})")
        except (CollectionInvalid, OperationFailure) as e:
            print(f"  ! {spec['name']} time-series creation failed: {e}")


# ---------------------------------------------------------------------------
# Step 2: $jsonSchema validators
# ---------------------------------------------------------------------------
LEAD_SCHEMA = {
    "bsonType": "object",
    "required": ["_id", "client_slug", "name", "premises_type", "address", "postcode",
                 "geo", "composite_score", "score_breakdown", "created_at", "updated_at"],
    "properties": {
        "_id":           {"bsonType": "string"},
        "client_slug":   {"bsonType": "string"},
        "name":          {"bsonType": "string"},
        "premises_type": {"bsonType": "string"},
        "address":       {"bsonType": "string"},
        "postcode":      {"bsonType": "string"},
        "geo": {
            "bsonType": "object",
            "required": ["point"],
            "properties": {
                "point": {
                    "bsonType": "object",
                    "required": ["type", "coordinates"],
                    "properties": {
                        "type":        {"enum": ["Point"]},
                        "coordinates": {"bsonType": "array", "minItems": 2, "maxItems": 2},
                    },
                },
            },
        },
        "rooftop_polygon": {"bsonType": ["object", "null"]},
        "rooftop_polygon_source": {"enum": ["inspire_index_polygon", "solar_api_bbox", "synthesized"]},
        "inspire_id":      {"bsonType": ["string", "null"]},
        "company_id":      {"bsonType": ["string", "null"]},
        "composite_score": {"bsonType": "double", "minimum": 0, "maximum": 100},
        "score_breakdown": {
            "bsonType": "object",
            "required": ["solar_roi", "financial_health", "social_impact"],
            "properties": {
                "solar_roi":        {"bsonType": "double"},
                "financial_health": {"bsonType": "double"},
                "social_impact":    {"bsonType": "double"},
            },
        },
        "panel_layout":    {"bsonType": "array"},
        "financial":       {"bsonType": ["object", "null"]},
        "annual_kwh":      {"bsonType": ["double", "null", "int"]},
        "panels_count":    {"bsonType": "int", "minimum": 0},
        "enriched_at":     {"bsonType": ["date", "null"]},
        "created_at":      {"bsonType": "date"},
        "updated_at":      {"bsonType": "date"},
    },
}

# Smaller validators for the other collections — kept terse here.
COMPANY_SCHEMA = {
    "bsonType": "object",
    "required": ["_id", "proprietor_name", "source", "created_at", "updated_at"],
    "properties": {
        "_id":             {"bsonType": "string"},
        "proprietor_name": {"bsonType": "string"},
        "source":          {"enum": ["ccod", "ocod", "companies_house", "synthesized"]},
        "created_at":      {"bsonType": "date"},
        "updated_at":      {"bsonType": "date"},
    },
}

CLIENT_SCHEMA = {
    "bsonType": "object",
    "required": ["_id", "display_name", "primary_color", "accent_color", "created_at"],
    "properties": {
        "_id":           {"bsonType": "string"},
        "display_name":  {"bsonType": "string"},
        "primary_color": {"bsonType": "string"},
        "accent_color":  {"bsonType": "string"},
        "created_at":    {"bsonType": "date"},
    },
}

AUDIT_SCHEMA = {
    "bsonType": "object",
    "required": ["_id", "ts", "actor", "action", "cost_cents"],
    "properties": {
        "_id":            {"bsonType": "string"},
        "ts":             {"bsonType": "date"},
        "actor":          {"bsonType": "string"},
        "action":         {"bsonType": "string"},
        "cost_cents":     {"bsonType": "int", "minimum": 0},
        "recipient_hash": {"bsonType": ["string", "null"]},
    },
}

VALIDATORS = {
    "leads":     LEAD_SCHEMA,
    "companies": COMPANY_SCHEMA,
    "clients":   CLIENT_SCHEMA,
    "audit_log": AUDIT_SCHEMA,
}


def step_2_validators(db) -> None:
    print(f"\n[2/4] applying validators")
    for coll, schema in VALIDATORS.items():
        try:
            db.command({
                "collMod": coll,
                "validator": {"$jsonSchema": schema},
                "validationLevel": "moderate",
                "validationAction": "warn",
            })
            print(f"  ✓ {coll}")
        except OperationFailure as e:
            print(f"  ✗ {coll}: {e}")


# ---------------------------------------------------------------------------
# Step 3: Indexes
# ---------------------------------------------------------------------------
def step_3_indexes(db) -> None:
    print(f"\n[3/4] creating indexes")

    def ensure(coll: str, keys, **opts):
        name = opts.get("name", "_".join(f"{k}_{v}" for k, v in keys))
        existing = {ix["name"] for ix in db[coll].list_indexes()}
        if name in existing:
            print(f"  - {coll}.{name} (exists)")
            return
        db[coll].create_index(keys, **opts)
        print(f"  + {coll}.{name}")

    # leads
    ensure("leads", [("geo.point", GEOSPHERE)],                    name="leads_geo_point_2dsphere")
    ensure("leads", [("client_slug", 1), ("composite_score", -1)], name="leads_client_score")
    ensure("leads", [("postcode", 1)],                              name="leads_postcode")
    ensure("leads", [("client_slug", 1), ("premises_type", 1), ("composite_score", -1)],
                                                                    name="leads_filter_compound")
    ensure("leads", [("inspire_id", 1)],                            name="leads_inspire_id_sparse", sparse=True)
    ensure("leads", [("company_id", 1)],                            name="leads_company_id_sparse", sparse=True)

    # companies
    ensure("companies", [("proprietor_name", 1)],   name="companies_proprietor_name")
    ensure("companies", [("company_number", 1)],    name="companies_number_unique", unique=True, sparse=True)

    # directors
    ensure("directors", [("company_id", 1)], name="directors_company_id")
    ensure("directors", [("full_name", 1)],  name="directors_full_name")

    # inspire
    ensure("inspire_polygons", [("centroid", GEOSPHERE)], name="inspire_centroid_2dsphere")
    ensure("inspire_polygons", [("geometry", GEOSPHERE)], name="inspire_geometry_2dsphere")
    ensure("inspire_polygons", [("area_m2_approx", 1)],   name="inspire_area")

    # land_registry
    ensure("land_registry", [("postcode", 1)],          name="lr_postcode")
    ensure("land_registry", [("proprietor_name", 1)],   name="lr_proprietor_name")
    ensure("land_registry", [("source", 1), ("postcode", 1)], name="lr_source_postcode")

    # audit_log
    ensure("audit_log", [("ts", -1)],                     name="audit_ts")
    ensure("audit_log", [("client_slug", 1), ("ts", -1)], name="audit_client_ts")
    ensure("audit_log", [("actor", 1), ("ts", -1)],       name="audit_actor_ts")

    # suppression_list
    ensure("suppression_list", [("hash", 1)], name="suppression_hash_unique", unique=True)


# ---------------------------------------------------------------------------
# Step 4: Agent backend databases (separate from solarreach)
# ---------------------------------------------------------------------------
def step_4_agent_dbs(client) -> None:
    print(f"\n[4/4] bootstrapping agent backend DBs")

    cp_db = client["solarreach_agent_checkpoints"]
    if "checkpoints" not in cp_db.list_collection_names():
        cp_db.create_collection("checkpoints")
    if "checkpoint_writes" not in cp_db.list_collection_names():
        cp_db.create_collection("checkpoint_writes")
    cp_db["checkpoints"].create_index(
        [("thread_id", 1), ("checkpoint_ns", 1), ("checkpoint_id", -1)],
        name="checkpoints_thread_ns_id", unique=True,
    )
    cp_db["checkpoint_writes"].create_index(
        [("thread_id", 1), ("checkpoint_ns", 1), ("checkpoint_id", -1)],
        name="checkpoint_writes_thread_ns_id", unique=True,
    )
    print(f"  ✓ solarreach_agent_checkpoints (checkpoints, checkpoint_writes)")

    st_db = client["solarreach_agent_store"]
    if "store" not in st_db.list_collection_names():
        st_db.create_collection("store")
    st_db["store"].create_index([("namespace", 1), ("key", 1)],
                                 name="store_namespace_key", unique=True)
    st_db["store"].create_index([("updated_at", -1)], name="store_recency")
    print(f"  ✓ solarreach_agent_store (store)")


# ---------------------------------------------------------------------------
def main() -> int:
    uri = os.environ.get("MONGO_URI")
    if not uri:
        print("ERROR: MONGO_URI env var not set", file=sys.stderr)
        return 2

    print(f"connecting to Atlas...")
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    # ping
    client.admin.command("ping")
    print(f"connected.")

    db = client.get_default_database()
    if db is None:
        db = client["solarreach"]

    step_1_collections(db)
    step_2_validators(db)
    step_3_indexes(db)
    step_4_agent_dbs(client)

    print(f"\n✓ Atlas setup complete.")
    print(f"  Default DB: {db.name}")
    print(f"  Agent DBs : solarreach_agent_checkpoints, solarreach_agent_store")
    print(f"\nNext: python scripts/seed_atlas_standalone.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
