#!/usr/bin/env python3
"""Deterministic seed: 250 leads + matching companies + officers.

Hard-won lessons baked in:
- random.seed(42) for reproducibility.
- Premises type is BOUND to the name pattern (no random misclassification —
  a "Logistics Hub" never becomes a "Hospital").
- Lead _id is a uuid suffix on top of the deterministic seed key, so that
  re-seeding never collides on _id (audit_log stays append-only).
- geo is ALWAYS {point: GeoJSONPoint} — never the raw point. This matches
  the validator and is the field name 2dsphere is on.

Acceptance criteria (Project 1):
- 250 leads seeded with score_breakdown populated.
- All linked to a company doc.
- Composite score in [0, 100].
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import random
import sys
import uuid
from datetime import datetime, timezone

from pymongo import MongoClient

from scoring_worker.pipeline.discovery import discover
from scoring_worker.pipeline.score import compute_composite
from solarreach_shared.constants import LONDON_BBOX, BRISTOL_BBOX

log = logging.getLogger("seed")

# Name patterns -> premises_type. Each pattern picks its own name set.
NAME_PATTERNS: list[tuple[str, list[str]]] = [
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

# Demo postcodes — generous spread across the two target cities.
DEMO_POSTCODES = [
    # London
    "EC1Y 8AF","EC1V 9NR","EC1A 4HD","SE1 9TG","SW1A 1AA","E1 6AN","E2 8DD",
    "N1 9GU","NW1 2BU","SE10 0ER","SE15 4PT","W1D 3DA","WC2N 5DU","E14 5AB",
    # Bristol
    "BS1 4DJ","BS2 0JP","BS3 4DT","BS4 3EH","BS5 0AX","BS6 5JY","BS7 8NN",
    "BS8 1TH","BS16 1QU",
]

CLIENT_SLUG = "client-greensolar-uk"


def _hash_to_unit(seed: str) -> float:
    h = hashlib.sha256(seed.encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def _name_for(rng: random.Random, premises_type: str, idx: int) -> str:
    table = dict(NAME_PATTERNS)
    prefix = rng.choice(table[premises_type])
    suffix = "Ltd" if premises_type in {"Warehouse","Office","Manufacturing","Cold Storage","Logistics Hub"} else ""
    return f"{prefix} {premises_type} {idx:03d}{(' ' + suffix) if suffix else ''}".strip()


def _stable_lead_id(name: str, postcode: str, run_uuid: str) -> str:
    """Deterministic-ish but UUID-suffixed to avoid collisions on re-seed."""

    seed = hashlib.sha1(f"{name}|{postcode}".encode()).hexdigest()[:12]
    return f"lead_{seed}_{run_uuid[:8]}"


async def _build_one_lead(
    rng: random.Random,
    *,
    premises_type: str,
    idx: int,
    run_uuid: str,
    cx_lng: float,
    cx_lat: float,
) -> dict:
    name = _name_for(rng, premises_type, idx)
    postcode = rng.choice(DEMO_POSTCODES)

    # Run discovery (mock by default — fast, deterministic via hash).
    sig = await discover(postcode, company_name=name)

    # Slight scatter around the discovery centroid so pins don't overlap.
    jitter_lng = (rng.random() - 0.5) * 0.004
    jitter_lat = (rng.random() - 0.5) * 0.003
    lng = sig.lng + jitter_lng
    lat = sig.lat + jitter_lat

    # Composite score from cheap signals.
    score = compute_composite(
        annual_kwh_per_kwp=sig.annual_kwh_per_kwp,
        company_health=sig.company_health_score,
        imd_decile=sig.imd_decile,
        has_company=True,
    )

    return {
        "_id": _stable_lead_id(name, postcode, run_uuid),
        "client_slug": CLIENT_SLUG,
        "name": name,
        "premises_type": premises_type,
        "address": f"{idx} Demo Street, {postcode}",
        "postcode": postcode,
        "geo": {"point": {"type": "Point", "coordinates": [lng, lat]}},
        "rooftop_polygon": None,
        "rooftop_polygon_source": "synthesized",
        "inspire_id": None,
        "company_id": None,         # filled in below
        "composite_score": score.composite_score,
        "score_breakdown": score.breakdown,
        "panel_layout": [],
        "financial": None,
        "annual_kwh": None,
        "panels_count": 0,
        "enriched_at": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def _company_for_lead(lead: dict, run_uuid: str) -> dict:
    seed = hashlib.sha1((lead["name"] + run_uuid[:4]).encode()).hexdigest()[:12]
    return {
        "_id": f"co_{seed}",
        "proprietor_name": lead["name"],
        "company_number": None,           # populated by Project 3 enrichment
        "incorporation_country": "United Kingdom",
        "registered_address": lead["address"],
        "sic_codes": [],
        "accounts_summary": None,
        "health_score": None,
        "embedding": None,
        "source": "synthesized",
        "created_at": lead["created_at"],
        "updated_at": lead["updated_at"],
    }


def _client_doc() -> dict:
    return {
        "_id": CLIENT_SLUG,
        "display_name": "GreenSolar UK",
        "primary_color": "#0E9F6E",
        "accent_color":  "#FFD93D",
        "logo_url": None,
        "pricing_overrides": {},
        "voice_agent_id": None,
        "created_at": datetime.now(timezone.utc),
    }


async def _seed_async(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    run_uuid = uuid.uuid4().hex
    log.info(f"deterministic seed={args.seed}, run_uuid={run_uuid}")

    client = MongoClient(args.mongo_uri)
    db = client.get_default_database()
    leads = db["leads"]
    companies = db["companies"]
    clients = db["clients"]

    # Wipe deterministic re-seeds if requested.
    if args.fresh:
        log.info("--fresh: wiping leads + companies for client")
        leads.delete_many({"client_slug": CLIENT_SLUG})
        companies.delete_many({"source": "synthesized"})

    # Upsert client doc.
    cdoc = _client_doc()
    clients.update_one({"_id": cdoc["_id"]}, {"$set": cdoc}, upsert=True)

    # Pick city centroids for jitter.
    cx_london = ((LONDON_BBOX[0] + LONDON_BBOX[2]) / 2, (LONDON_BBOX[1] + LONDON_BBOX[3]) / 2)
    cx_bristol = ((BRISTOL_BBOX[0] + BRISTOL_BBOX[2]) / 2, (BRISTOL_BBOX[1] + BRISTOL_BBOX[3]) / 2)

    n_made = 0
    types_count = {t: 0 for t, _ in NAME_PATTERNS}
    for i in range(args.count):
        ptype = rng.choice([t for t, _ in NAME_PATTERNS])
        types_count[ptype] += 1
        # Alternate cities for spread (40/60).
        cx = cx_london if rng.random() < 0.6 else cx_bristol
        lead = await _build_one_lead(
            rng,
            premises_type=ptype,
            idx=i + 1,
            run_uuid=run_uuid,
            cx_lng=cx[0], cx_lat=cx[1],
        )
        co = _company_for_lead(lead, run_uuid)
        lead["company_id"] = co["_id"]

        # Upsert (idempotent against same _id; new run_uuid prevents collisions
        # if the user reseeds without --fresh).
        leads.update_one({"_id": lead["_id"]}, {"$set": lead}, upsert=True)
        companies.update_one({"_id": co["_id"]}, {"$set": co}, upsert=True)
        n_made += 1
        if n_made % 50 == 0:
            log.info(f"  seeded {n_made}/{args.count}")

    log.info(f"seeded {n_made} leads. distribution: {types_count}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mongo-uri", default="mongodb://solarreach_app:change-me-in-prod@localhost:27017/solarreach?authSource=admin")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--count", type=int, default=250)
    p.add_argument("--fresh", action="store_true", help="Wipe demo client leads + synthesised companies first")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(_seed_async(args))


if __name__ == "__main__":
    sys.exit(main())
