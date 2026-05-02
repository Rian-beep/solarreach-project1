#!/usr/bin/env python3
"""Ingest HM Land Registry INSPIRE Index Polygons into solarreach.inspire_polygons.

Inputs:
- A directory containing per-local-authority GML files (download zips from
  https://use-land-property-data.service.gov.uk/datasets/inspire and extract).

Hard-won lessons baked in:
- INSPIRE GML uses EPSG:27700 (British National Grid). MUST be converted to
  EPSG:4326 BEFORE inserting; 2dsphere indexes do not accept BNG.
- INSPIRE polygons can be land parcels (gardens, parking) — not just buildings.
  We filter by area_m2_approx in [INSPIRE_MIN_AREA_M2, INSPIRE_MAX_AREA_M2].
  Compute area in BNG (metres) where it is meaningful, BEFORE projection.
- Stream-parse with lxml.etree.iterparse; clear elements + delete parent links
  to keep memory bounded. Naive parsing of the full file blows out memory.
- Bbox filter: only insert polygons whose centroid is in our target bboxes.

Usage:
  python scripts/ingest_inspire.py --gml-dir /data/inspire/extracted/ \\
      --bbox london \\
      --mongo-uri mongodb://...
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from lxml import etree
from pymongo import MongoClient, UpdateOne
from pymongo.collection import Collection
from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import transform as shp_transform

from solarreach_shared.constants import (
    BRISTOL_BBOX,
    INSPIRE_MAX_AREA_M2,
    INSPIRE_MIN_AREA_M2,
    LONDON_BBOX,
)

# Namespaces used in INSPIRE GML feeds.
NS = {
    "gml":  "http://www.opengis.net/gml/3.2",
    "lr":   "http://landregistry.data.gov.uk/def/inspire/1/0/",
}

# Module-level transformer (pyproj re-creation is expensive).
TRANSFORMER_BNG_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)

log = logging.getLogger("ingest_inspire")


def _stable_id(inspire_id: str) -> str:
    return f"insp_{inspire_id}" if inspire_id else f"insp_anon_{hashlib.sha1(str(id(object())).encode()).hexdigest()[:10]}"


def _parse_gml_polygon(elem: etree._Element) -> Polygon | None:
    """Parse a gml:Polygon element to a shapely Polygon in EPSG:27700.
    Returns None if no usable coordinates."""

    pos_list = elem.find(".//gml:posList", NS)
    if pos_list is None or pos_list.text is None:
        return None
    coords_raw = pos_list.text.split()
    if len(coords_raw) < 8 or len(coords_raw) % 2:
        return None   # need ≥4 points (8 floats), and even count
    try:
        flat = list(map(float, coords_raw))
    except ValueError:
        return None
    pairs = list(zip(flat[0::2], flat[1::2]))
    if pairs[0] != pairs[-1]:
        pairs.append(pairs[0])   # close ring if open
    if len(pairs) < 4:
        return None
    try:
        return Polygon(pairs)
    except Exception:
        return None


def _project_to_4326(poly_bng: Polygon) -> Polygon:
    return shp_transform(lambda x, y, z=None: TRANSFORMER_BNG_TO_WGS84.transform(x, y), poly_bng)


def _in_bbox(lng: float, lat: float, bbox: tuple[float, float, float, float]) -> bool:
    return bbox[0] <= lng <= bbox[2] and bbox[1] <= lat <= bbox[3]


def iter_features(path: Path, *, target_bbox: tuple[float, float, float, float]) -> Iterator[dict[str, Any]]:
    """Yield validated docs ready to upsert. Streaming, low memory."""

    # Use iterparse to avoid loading the whole tree.
    context = etree.iterparse(str(path), events=("end",), tag=f"{{{NS['lr']}}}LandRegistryPolygon")
    for _evt, elem in context:
        try:
            inspire_id = (elem.findtext("lr:INSPIREID", namespaces=NS) or "").strip()
            title_no = (elem.findtext("lr:TITLENO", namespaces=NS) or "").strip() or None
            poly_bng = _parse_gml_polygon(elem)
            if poly_bng is None or poly_bng.is_empty:
                continue
            area = poly_bng.area
            if area < INSPIRE_MIN_AREA_M2 or area > INSPIRE_MAX_AREA_M2:
                continue
            poly_4326 = _project_to_4326(poly_bng)
            cx, cy = poly_4326.centroid.x, poly_4326.centroid.y
            if not _in_bbox(cx, cy, target_bbox):
                continue
            ring = list(poly_4326.exterior.coords)
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            doc = {
                "_id": _stable_id(inspire_id),
                "inspire_id": inspire_id,
                "title_no": title_no,
                "geometry": {"type": "Polygon", "coordinates": [[(float(x), float(y)) for x, y in ring]]},
                "centroid": {"type": "Point", "coordinates": [float(cx), float(cy)]},
                "area_m2_approx": float(area),
                "local_authority": path.stem,
                "ingested_at": datetime.now(timezone.utc),
            }
            yield doc
        finally:
            # CRITICAL for memory: clear the element + drop all preceding siblings.
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]


def _flush(coll: Collection, ops: list[UpdateOne]) -> int:
    if not ops:
        return 0
    res = coll.bulk_write(ops, ordered=False)
    return res.upserted_count + res.modified_count


def ingest_directory(gml_dir: Path, *, target_bbox: tuple[float, float, float, float], coll: Collection, batch: int = 1000) -> int:
    n = 0
    for gml in sorted(gml_dir.rglob("*.gml")):
        log.info(f"parsing {gml.name}")
        ops: list[UpdateOne] = []
        for doc in iter_features(gml, target_bbox=target_bbox):
            ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": doc}, upsert=True))
            if len(ops) >= batch:
                _flush(coll, ops)
                n += len(ops)
                log.info(f"  ...{n:,} upserted so far")
                ops.clear()
        n += _flush(coll, ops)
        log.info(f"finished {gml.name}: total {n:,}")
    return n


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mongo-uri", default="mongodb://solarreach_app:change-me-in-prod@localhost:27017/solarreach?authSource=admin")
    p.add_argument("--gml-dir", required=True, type=Path)
    p.add_argument("--bbox", choices=["london", "bristol", "all"], default="london")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not args.gml_dir.exists():
        log.error(f"GML dir not found: {args.gml_dir}")
        return 2

    bboxes = {"london": LONDON_BBOX, "bristol": BRISTOL_BBOX}
    if args.bbox == "all":
        # union — generous min/max
        bbox = (
            min(LONDON_BBOX[0], BRISTOL_BBOX[0]),
            min(LONDON_BBOX[1], BRISTOL_BBOX[1]),
            max(LONDON_BBOX[2], BRISTOL_BBOX[2]),
            max(LONDON_BBOX[3], BRISTOL_BBOX[3]),
        )
    else:
        bbox = bboxes[args.bbox]

    client = MongoClient(args.mongo_uri)
    coll = client.get_default_database()["inspire_polygons"]

    n = ingest_directory(args.gml_dir, target_bbox=bbox, coll=coll)
    log.info(f"INSPIRE ingest complete: {n:,} polygons in target bbox")
    return 0


if __name__ == "__main__":
    sys.exit(main())
