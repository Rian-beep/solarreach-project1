#!/usr/bin/env python3
"""Standalone seed: 250 leads + 250 companies + 1 client into Atlas.

This file is INTENTIONALLY DEPENDENCY-FREE beyond pymongo. You can:
  1. Run it locally:  python scripts/seed_atlas_standalone.py
  2. Paste it into a Google Colab cell.
  3. Paste it into a Jupyter notebook in LangGraph Studio.

It does NOT import from packages/ — every constant is inlined so you can
copy-paste a single file. If you want the modular version that shares
constants with the rest of the project, use scripts/seed.py.

Reads:
  MONGO_URI env var (e.g. mongodb+srv://user:pwd@cluster.../solarreach?...).
"""

from __future__ import annotations

import hashlib
import os
import random
import sys
import uuid
from datetime import datetime, timezone

try:
    from pymongo import MongoClient
except ImportError:
    print("ERROR: pip install pymongo", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# CONSTANTS — copied from solarreach_shared.constants so this file stands alone
# ---------------------------------------------------------------------------
SCORE_WEIGHTS = {"solar_roi": 0.40, "financial_health": 0.35, "social_impact": 0.25}
CLIENT_SLUG = "client-greensolar-uk"

NAME_PATTERNS = [
    ("Warehouse",       ["Bunhill", "Riverside", "Hartford", "Aldgate", "Pickering", "Southwark"]),
    ("Office",          ["Northgate", "Crescent", "Westbrook", "Beaufort", "Quarry"]),
    ("Retail Park",     ["Vauxhall", "Greenford", "Beckton", "Lawrence Hill", "Brislington"]),
    ("Leisure Centre",  ["Albany", "Mile End", "Oasis", "Westminster", "Henleaze"]),
    ("Manufacturing",   ["Park Royal", "Trafford", "Avonmouth", "Filton", "Dagenham"]),
    ("Cold Storage",    ["Felixstowe", "Tilbury", "Avon", "Royal Wharf"]),
    ("Hospital",        ["St Bartholomew's", "Royal London", "Bristol Royal", "St Mary's", "Whitechapel"]),
    ("School",          ["Camden", "Stoke Newington", "Bedminster", "Henleaze", "Clifton"]),
    ("Hotel",           ["Travelmark", "Premier", "Ibis", "Aldgate Tower", "Avonmouth Lodge"]),
    ("Logistics Hub",   ["Heathrow West", "Avonmouth West", "Park Royal West", "Filton North"]),
]

# Postcode → (lng, lat) — hand-set centroids for the demo postcodes.
POSTCODE_TABLE = {
    "EC1Y 8AF": (-0.0879, 51.5232),  "EC1V 9NR": (-0.0954, 51.5273),
    "EC1A 4HD": (-0.0985, 51.5158),  "SE1 9TG":  (-0.0950, 51.5050),
    "SW1A 1AA": (-0.1419, 51.5014),  "E1 6AN":   (-0.0717, 51.5177),
    "E2 8DD":   (-0.0612, 51.5305),  "N1 9GU":   (-0.1062, 51.5341),
    "NW1 2BU":  (-0.1376, 51.5294),  "SE10 0ER": (-0.0098, 51.4793),
    "SE15 4PT": (-0.0681, 51.4738),  "W1D 3DA":  (-0.1339, 51.5142),
    "WC2N 5DU": (-0.1276, 51.5074),  "E14 5AB":  (-0.0235, 51.5054),
    "BS1 4DJ":  (-2.5945, 51.4545),  "BS2 0JP":  (-2.5727, 51.4624),
    "BS3 4DT":  (-2.6010, 51.4400),  "BS4 3EH":  (-2.5688, 51.4377),
    "BS5 0AX":  (-2.5546, 51.4659),  "BS6 5JY":  (-2.6010, 51.4716),
    "BS7 8NN":  (-2.5856, 51.4833),  "BS8 1TH":  (-2.6097, 51.4585),
    "BS16 1QU": (-2.5174, 51.4844),
}

DEMO_POSTCODES = list(POSTCODE_TABLE.keys())

# Postcode → fixed IMD decile (1=most deprived, 10=least)
POSTCODE_IMD = {
    "EC1Y 8AF": 4, "BS1 4DJ": 6, "E1 6AN": 2, "E2 8DD": 3, "BS5 0AX": 3,
    "SW1A 1AA": 10, "BS8 1TH": 9, "NW1 2BU": 5,
}


def _hash_unit(*parts) -> float:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def _name_for(rng: random.Random, premises_type: str, idx: int) -> str:
    table = dict(NAME_PATTERNS)
    prefix = rng.choice(table[premises_type])
    suffix = "Ltd" if premises_type in {"Warehouse", "Office", "Manufacturing", "Cold Storage", "Logistics Hub"} else ""
    return f"{prefix} {premises_type} {idx:03d}{(' ' + suffix) if suffix else ''}".strip()


# ---------------------------------------------------------------------------
# Scoring functions — copied from scoring_worker.pipeline.score
# ---------------------------------------------------------------------------
def solar_roi_score(annual_kwh_per_kwp: float) -> float:
    if annual_kwh_per_kwp <= 0:
        return 0.0
    return max(0.0, min(100.0, (annual_kwh_per_kwp - 750.0) / (1100.0 - 750.0) * 100.0))


def financial_health_score(company_health: float | None, has_company: bool) -> float:
    if not has_company or company_health is None:
        return 50.0
    return max(0.0, min(100.0, company_health))


def social_impact_score(imd_decile: int) -> float:
    if imd_decile < 1 or imd_decile > 10:
        return 50.0
    return float(110 - imd_decile * 10)


def compute_composite(annual_kwh_per_kwp: float, company_health: float | None,
                      imd_decile: int, has_company: bool) -> dict:
    s_roi = solar_roi_score(annual_kwh_per_kwp)
    s_fin = financial_health_score(company_health, has_company)
    s_soc = social_impact_score(imd_decile)
    composite = (
        SCORE_WEIGHTS["solar_roi"] * s_roi
        + SCORE_WEIGHTS["financial_health"] * s_fin
        + SCORE_WEIGHTS["social_impact"] * s_soc
    )
    return {
        "composite_score": round(composite, 2),
        "breakdown": {
            "solar_roi": round(s_roi, 2),
            "financial_health": round(s_fin, 2),
            "social_impact": round(s_soc, 2),
        },
    }


# ---------------------------------------------------------------------------
# Mock discovery — derives signals deterministically from postcode hash
# ---------------------------------------------------------------------------
def discover_mock(postcode: str, company_name: str | None = None) -> dict:
    centroid = POSTCODE_TABLE.get(postcode, (-0.118, 51.509))
    jitter_lng = (_hash_unit("lng", postcode) - 0.5) * 0.012
    jitter_lat = (_hash_unit("lat", postcode) - 0.5) * 0.008
    lng = centroid[0] + jitter_lng
    lat = centroid[1] + jitter_lat
    # PVGIS-like yield, latitude-aware
    lat_factor = max(0.0, min(1.0, (56.0 - lat) / 6.0))
    annual = 850 + 200 * lat_factor
    imd_decile = POSTCODE_IMD.get(postcode, 1 + int(_hash_unit("imd", postcode) * 10))
    if imd_decile > 10:
        imd_decile = 10
    company_health = None
    if company_name:
        company_health = 50 + min(40, len(company_name)) / 2
    return {
        "lng": lng, "lat": lat,
        "annual_kwh_per_kwp": annual,
        "imd_decile": imd_decile,
        "company_health": company_health,
    }


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------
def seed(mongo_uri: str, *, count: int = 250, seed_value: int = 42, fresh: bool = False) -> None:
    rng = random.Random(seed_value)
    run_uuid = uuid.uuid4().hex
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=10000)

    # Atlas URI typically includes /solarreach as the default DB.
    db = client.get_default_database()
    if db is None:
        db = client["solarreach"]

    print(f"target db: {db.name}")
    print(f"deterministic seed={seed_value}, run_uuid={run_uuid[:8]}")

    if fresh:
        d1 = db["leads"].delete_many({"client_slug": CLIENT_SLUG}).deleted_count
        d2 = db["companies"].delete_many({"source": "synthesized"}).deleted_count
        print(f"  --fresh: deleted {d1} leads, {d2} companies")

    # Upsert client doc
    db["clients"].update_one(
        {"_id": CLIENT_SLUG},
        {"$set": {
            "_id": CLIENT_SLUG,
            "display_name": "GreenSolar UK",
            "primary_color": "#0E9F6E",
            "accent_color":  "#FFD93D",
            "logo_url": None,
            "pricing_overrides": {},
            "voice_agent_id": None,
            "created_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )

    n_made = 0
    types_count: dict[str, int] = {t: 0 for t, _ in NAME_PATTERNS}

    for i in range(count):
        ptype = rng.choice([t for t, _ in NAME_PATTERNS])
        types_count[ptype] += 1
        name = _name_for(rng, ptype, i + 1)
        postcode = rng.choice(DEMO_POSTCODES)
        sig = discover_mock(postcode, company_name=name)
        score = compute_composite(
            sig["annual_kwh_per_kwp"], sig["company_health"],
            sig["imd_decile"], has_company=True,
        )

        seed_id = hashlib.sha1(f"{name}|{postcode}".encode()).hexdigest()[:12]
        lead_id = f"lead_{seed_id}_{run_uuid[:8]}"
        co_id = f"co_{hashlib.sha1((name + run_uuid[:4]).encode()).hexdigest()[:12]}"
        now = datetime.now(timezone.utc)

        lead_doc = {
            "_id": lead_id,
            "client_slug": CLIENT_SLUG,
            "name": name,
            "premises_type": ptype,
            "address": f"{i+1} Demo Street, {postcode}",
            "postcode": postcode,
            "geo": {"point": {"type": "Point", "coordinates": [sig["lng"], sig["lat"]]}},
            "rooftop_polygon": None,
            "rooftop_polygon_source": "synthesized",
            "inspire_id": None,
            "company_id": co_id,
            "composite_score": score["composite_score"],
            "score_breakdown": score["breakdown"],
            "panel_layout": [],
            "financial": None,
            "annual_kwh": None,
            "panels_count": 0,
            "enriched_at": None,
            "created_at": now,
            "updated_at": now,
        }
        co_doc = {
            "_id": co_id,
            "proprietor_name": name,
            "company_number": None,
            "incorporation_country": "United Kingdom",
            "registered_address": lead_doc["address"],
            "sic_codes": [],
            "accounts_summary": None,
            "health_score": None,
            "embedding": None,
            "source": "synthesized",
            "created_at": now,
            "updated_at": now,
        }

        db["leads"].update_one({"_id": lead_id}, {"$set": lead_doc}, upsert=True)
        db["companies"].update_one({"_id": co_id}, {"$set": co_doc}, upsert=True)

        n_made += 1
        if n_made % 50 == 0:
            print(f"  seeded {n_made}/{count}")

    print(f"\nseeded {n_made} leads.")
    print(f"distribution: {types_count}")
    print(f"\nverify in Atlas:")
    print(f"  db.leads.countDocuments({{client_slug: '{CLIENT_SLUG}'}})  →  {n_made}")


if __name__ == "__main__":
    uri = os.environ.get("MONGO_URI")
    if not uri:
        print("ERROR: MONGO_URI env var not set", file=sys.stderr)
        print("Example: export MONGO_URI='mongodb+srv://user:pwd@cluster.../solarreach?authSource=admin'", file=sys.stderr)
        sys.exit(2)
    fresh = "--fresh" in sys.argv
    seed(uri, fresh=fresh)
