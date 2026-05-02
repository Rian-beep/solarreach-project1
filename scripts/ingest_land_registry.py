#!/usr/bin/env python3
"""Ingest HM Land Registry CCOD + OCOD into solarreach.land_registry.

Inputs (download from https://use-land-property-data.service.gov.uk/):
- CCOD: CCOD_FULL_YYYY_MM.csv (~1.5GB, ~4.4M rows)
- OCOD: OCOD_FULL_YYYY_MM.csv (~35MB, ~91k rows)

Filters:
- Only rows whose `Property Address` contains a postcode in our target set
  (LONDON_BBOX/BRISTOL_BBOX areas — we filter by postcode prefix here, the
  geo-bbox check happens at lead-creation time once we geocode).

Hard-won lessons baked in:
- Stream with csv.DictReader, NEVER pandas (pandas loads all 1.5GB).
- Use bulk_write with ordered=False and 1k-doc batches.
- _id = sha1(source + title_number) to make re-ingest idempotent.
- Dates parse leniently — LR uses DD/MM/YYYY.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pymongo import MongoClient, UpdateOne
from pymongo.collection import Collection

# These are the postcode prefixes we keep. Generous: we don't want to drop
# valid LR records due to address parsing. Geocoding+bbox at lead-time
# decides what makes it onto the map.
TARGET_POSTCODE_PREFIXES = {
    # London
    "EC1","EC2","EC3","EC4","WC1","WC2","W1","SW1","NW1","N1","E1","SE1",
    "EC1Y","EC1V","EC1A","EC1M","EC1N","EC1R",
    "SW2","SW3","SW4","SW5","SW6","SW7","SW8","SW9","SW10","SW11","SW12",
    "E2","E3","E8","E14","SE10","SE11","SE15","SE17","SE22","N4","N7","N16",
    # Bristol
    "BS1","BS2","BS3","BS4","BS5","BS6","BS7","BS8","BS16",
}

# UK postcode regex — tolerant of missing space.
POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.IGNORECASE)

# CCOD/OCOD column names (CCOD has 17 cols; OCOD adds country fields).
CCOD_COLS = {
    "title_number":            "Title Number",
    "tenure":                  "Tenure",
    "proprietor_name":         "Proprietor Name (1)",
    "company_registration_no": "Company Registration No. (1)",
    "proprietor_address":      "Proprietor (1) Address (1)",
    "property_address":        "Property Address",
    "price_paid":              "Price Paid",
    "date_proprietor_added":   "Date Proprietor Added",
    "multiple_address":        "Multiple Address Indicator",
}
OCOD_COLS = {**CCOD_COLS, "country_incorporated": "Country Incorporated (1)"}


log = logging.getLogger("ingest_lr")


def _stable_id(source: str, title: str) -> str:
    return f"lr_{source}_" + hashlib.sha1(f"{source}|{title}".encode()).hexdigest()[:16]


def _extract_postcode(addr: str) -> str | None:
    if not addr:
        return None
    m = POSTCODE_RE.search(addr)
    if not m:
        return None
    return f"{m.group(1).upper()} {m.group(2).upper()}"


def _matches_target(postcode: str | None) -> bool:
    if not postcode:
        return False
    prefix = postcode.split()[0]
    if prefix in TARGET_POSTCODE_PREFIXES:
        return True
    # Try the area-only prefix (e.g. EC1Y -> EC1).
    short = re.match(r"^([A-Z]{1,2}\d)", prefix)
    return short is not None and short.group(1) in TARGET_POSTCODE_PREFIXES


def _parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_price(raw: str) -> int | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d]", "", raw)
    return int(cleaned) if cleaned else None


def _row_to_doc(row: dict[str, str], *, source: str, columns: dict[str, str]) -> dict[str, Any] | None:
    title = (row.get(columns["title_number"]) or "").strip()
    if not title:
        return None
    addr = (row.get(columns["property_address"]) or "").strip()
    pc = _extract_postcode(addr)
    if not _matches_target(pc):
        return None

    proprietor = (row.get(columns["proprietor_name"]) or "").strip()
    if not proprietor:
        return None

    doc: dict[str, Any] = {
        "_id": _stable_id(source, title),
        "title_number": title,
        "tenure": (row.get(columns["tenure"]) or "").strip() or None,
        "proprietor_name": proprietor,
        "proprietor_address": (row.get(columns["proprietor_address"]) or "").strip() or None,
        "company_registration_no": (row.get(columns["company_registration_no"]) or "").strip() or None,
        "property_address": addr,
        "postcode": pc,
        "price_paid_gbp": _parse_price(row.get(columns["price_paid"]) or ""),
        "date_proprietor_added": _parse_date(row.get(columns["date_proprietor_added"]) or ""),
        "multiple_address_indicator": (row.get(columns["multiple_address"]) or "").strip().upper() == "Y",
        "source": source,
        "ingested_at": datetime.now(timezone.utc),
    }
    if source == "ocod":
        doc["country_incorporated"] = (row.get(OCOD_COLS["country_incorporated"]) or "").strip() or None
    return doc


def _bulk_iter(coll: Collection, docs: Iterable[dict[str, Any]], *, batch: int = 1000) -> tuple[int, int]:
    """Upsert in batches. Returns (n_processed, n_upserted)."""

    ops: list[UpdateOne] = []
    n_processed = 0
    n_upserted = 0
    for doc in docs:
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": doc}, upsert=True))
        if len(ops) >= batch:
            res = coll.bulk_write(ops, ordered=False)
            n_processed += len(ops)
            n_upserted += res.upserted_count
            ops.clear()
            log.info(f"  upserted batch -> {n_processed} processed total")
    if ops:
        res = coll.bulk_write(ops, ordered=False)
        n_processed += len(ops)
        n_upserted += res.upserted_count
    return n_processed, n_upserted


def ingest_csv(path: Path, *, source: str, coll: Collection) -> tuple[int, int]:
    columns = OCOD_COLS if source == "ocod" else CCOD_COLS
    log.info(f"ingesting {source}: {path}")
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        docs = (
            doc
            for row in reader
            if (doc := _row_to_doc(row, source=source, columns=columns)) is not None
        )
        return _bulk_iter(coll, docs)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mongo-uri", default="mongodb://solarreach_app:change-me-in-prod@localhost:27017/solarreach?authSource=admin")
    p.add_argument("--ccod", type=Path, help="CCOD_FULL_YYYY_MM.csv")
    p.add_argument("--ocod", type=Path, help="OCOD_FULL_YYYY_MM.csv")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not args.ccod and not args.ocod:
        log.error("Provide at least one of --ccod / --ocod")
        return 2

    client = MongoClient(args.mongo_uri)
    coll = client.get_default_database()["land_registry"]

    if args.ccod:
        if not args.ccod.exists():
            log.error(f"CCOD file not found: {args.ccod}")
            return 2
        n, up = ingest_csv(args.ccod, source="ccod", coll=coll)
        log.info(f"CCOD done: {n:,} processed, {up:,} upserted")
    if args.ocod:
        if not args.ocod.exists():
            log.error(f"OCOD file not found: {args.ocod}")
            return 2
        n, up = ingest_csv(args.ocod, source="ocod", coll=coll)
        log.info(f"OCOD done: {n:,} processed, {up:,} upserted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
