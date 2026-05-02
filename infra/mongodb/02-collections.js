// 02-collections.js — create the 12 standard collections + 3 time-series.
// Validators come in 03-validators.js, indexes in 04-indexes.js.

db = db.getSiblingDB("solarreach");

// --- Standard collections (12) -------------------------------------------
const standard = [
  "leads",
  "companies",
  "directors",
  "inspire_polygons",
  "land_registry",
  "clients",
  "audit_log",
  "outreach_variants",
  "inbound_leads",
  "suppression_list",
  "webhooks_inbox"
];

for (const name of standard) {
  if (!db.getCollectionNames().includes(name)) {
    db.createCollection(name);
    print(`[02-collections] created ${name}`);
  } else {
    print(`[02-collections] ${name} already exists, skipping`);
  }
}

// --- Time-series collections (3) -----------------------------------------
// Mongo 7+ time-series. Granularity matters: hours = ~30s scan vs days = 1ms.
const ts = [
  {
    name: "energy_yield_ts",
    timeField: "ts",
    metaField: "meta",        // {building_id: "..."}
    granularity: "hours"
  },
  {
    name: "weather_ts",
    timeField: "ts",
    metaField: "meta",        // {cell_id: "..."}
    granularity: "hours"
  },
  {
    name: "calls_ts",
    timeField: "ts",
    metaField: "meta",        // {lead_id: "...", role: "agent"|"user"}
    granularity: "seconds"    // sub-minute chunks during voice rehearsal
  }
];

for (const spec of ts) {
  if (!db.getCollectionNames().includes(spec.name)) {
    db.createCollection(spec.name, {
      timeseries: {
        timeField: spec.timeField,
        metaField: spec.metaField,
        granularity: spec.granularity
      }
    });
    print(`[02-collections] created time-series ${spec.name} (${spec.granularity})`);
  } else {
    print(`[02-collections] ${spec.name} already exists, skipping`);
  }
}

db._init_marker.insertOne({ at: new Date(), step: "02-collections" });
