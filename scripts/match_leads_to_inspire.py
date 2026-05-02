#!/usr/bin/env python3
"""Snap each lead to its nearest plausible INSPIRE polygon.

For every lead in solarreach.leads:
1. Run a $geoNear on inspire_polygons.centroid with radius INSPIRE_SNAP_RADIUS_M.
2. Pick the closest polygon whose area is in [MIN, MAX] (already filtered at
   ingest time, but defence-in-depth here).
3. Update the lead with rooftop_polygon, rooftop_polygon_source = "inspire_index_polygon",
   inspire_id.

Hard rule (CARDINAL RULE #6): NEVER overwrite an INSPIRE polygon with the
Solar API axis-aligned 5-corner bbox. Therefore this script ONLY writes when
either:
- existing polygon is None
- existing polygon is from "synthesized" or "solar_api_bbox"

Acceptance criterion (Project 1): >=80% of seeded leads snapped.
"""

from __future__ import annotations

import argparse
import logging
import sys

from pymongo import MongoClient

from solarreach_shared.constants import (
    INSPIRE_MAX_AREA_M2,
    INSPIRE_MIN_AREA_M2,
    INSPIRE_SNAP_RADIUS_M,
)

log = logging.getLogger("match_inspire")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mongo-uri", default="mongodb://solarreach_app:change-me-in-prod@localhost:27017/solarreach?authSource=admin")
    p.add_argument("--client-slug", default=None, help="Restrict to one client")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    client = MongoClient(args.mongo_uri)
    db = client.get_default_database()
    leads = db["leads"]
    inspire = db["inspire_polygons"]

    query: dict = {}
    if args.client_slug:
        query["client_slug"] = args.client_slug
    n_total = leads.count_documents(query)
    log.info(f"matching {n_total:,} leads against inspire_polygons")

    n_snapped = 0
    n_skipped_better = 0
    n_no_match = 0

    for lead in leads.find(query, no_cursor_timeout=True):
        existing_source = lead.get("rooftop_polygon_source", "synthesized")
        existing_polygon = lead.get("rooftop_polygon")
        existing_inspire = lead.get("inspire_id")

        # Preservation rule: keep INSPIRE if we already have one.
        if existing_source == "inspire_index_polygon" and existing_inspire:
            n_skipped_better += 1
            continue

        point = lead.get("geo", {}).get("point")
        if not point or "coordinates" not in point:
            log.warning(f"lead {lead['_id']} has no geo.point — skipping")
            continue

        # geoNear by centroid; we filter area in $match for safety.
        pipeline = [
            {
                "$geoNear": {
                    "near": point,
                    "distanceField": "dist_m",
                    "maxDistance": INSPIRE_SNAP_RADIUS_M,
                    "spherical": True,
                    "key": "centroid",
                    "query": {
                        "area_m2_approx": {"$gte": INSPIRE_MIN_AREA_M2, "$lte": INSPIRE_MAX_AREA_M2},
                    },
                }
            },
            {"$limit": 1},
        ]
        match = next(inspire.aggregate(pipeline), None)
        if not match:
            n_no_match += 1
            log.debug(f"no inspire match for lead {lead['_id']}")
            continue

        update = {
            "rooftop_polygon": match["geometry"],
            "rooftop_polygon_source": "inspire_index_polygon",
            "inspire_id": match["inspire_id"],
        }
        if args.dry_run:
            log.info(f"DRY-RUN would update {lead['_id']} -> inspire {match['inspire_id']} (dist={match['dist_m']:.1f}m)")
        else:
            leads.update_one({"_id": lead["_id"]}, {"$set": update})
        n_snapped += 1

    log.info(f"done. snapped={n_snapped:,} preserved={n_skipped_better:,} no_match={n_no_match:,}")
    pct = (n_snapped + n_skipped_better) / max(n_total, 1) * 100
    log.info(f"coverage: {pct:.1f}% ({n_snapped + n_skipped_better:,} / {n_total:,})")
    if pct < 80 and n_total >= 100:
        log.warning("coverage below 80% acceptance threshold — check INSPIRE ingest bbox")
    return 0


if __name__ == "__main__":
    sys.exit(main())
