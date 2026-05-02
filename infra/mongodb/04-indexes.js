// 04-indexes.js — every index needed for the demo path.
// Atlas Search + Atlas Vector Search indexes are NOT created here (they
// require a control-plane API call or the Atlas UI) — see 05-search-indexes.md.

db = db.getSiblingDB("solarreach");

const ensure = (coll, spec, opts) => {
  const name = opts && opts.name ? opts.name : Object.keys(spec).map(k => `${k}_${spec[k]}`).join("_");
  const existing = db[coll].getIndexes().map(i => i.name);
  if (existing.includes(name)) {
    print(`[04-indexes] ${coll}.${name} already exists, skipping`);
    return;
  }
  db[coll].createIndex(spec, opts || {});
  print(`[04-indexes] created ${coll}.${name}`);
};

// ---- leads ---------------------------------------------------------------
ensure("leads", { "geo.point": "2dsphere" }, { name: "leads_geo_point_2dsphere" });
ensure("leads", { client_slug: 1, composite_score: -1 }, { name: "leads_client_score" });
ensure("leads", { postcode: 1 }, { name: "leads_postcode" });
ensure("leads", { client_slug: 1, premises_type: 1, composite_score: -1 }, { name: "leads_filter_compound" });
ensure("leads", { inspire_id: 1 }, { name: "leads_inspire_id_sparse", sparse: true });
ensure("leads", { company_id: 1 }, { name: "leads_company_id_sparse", sparse: true });

// ---- companies -----------------------------------------------------------
ensure("companies", { proprietor_name: 1 }, { name: "companies_proprietor_name" });
ensure("companies", { company_number: 1 }, { name: "companies_number_unique", unique: true, sparse: true });
// Legacy text index — kept as Atlas Search fallback for Compass/dev users
// without an Atlas Search node. Will conflict with the Atlas index if both
// active in production; safe in dev.
ensure("companies",
  { proprietor_name: "text", registered_address: "text" },
  { name: "companies_text_fallback", default_language: "english" });

// ---- directors -----------------------------------------------------------
ensure("directors", { company_id: 1 }, { name: "directors_company_id" });
ensure("directors", { full_name: 1 }, { name: "directors_full_name" });
ensure("directors",
  { company_id: 1, inferred_decision_maker: 1, decision_maker_confidence: -1 },
  { name: "directors_dm_lookup" });

// ---- inspire_polygons ----------------------------------------------------
ensure("inspire_polygons", { centroid: "2dsphere" }, { name: "inspire_centroid_2dsphere" });
ensure("inspire_polygons", { geometry: "2dsphere" }, { name: "inspire_geometry_2dsphere" });
ensure("inspire_polygons", { area_m2_approx: 1 }, { name: "inspire_area" });
ensure("inspire_polygons", { local_authority: 1 }, { name: "inspire_local_authority", sparse: true });

// ---- land_registry -------------------------------------------------------
ensure("land_registry", { postcode: 1 }, { name: "lr_postcode" });
ensure("land_registry", { proprietor_name: 1 }, { name: "lr_proprietor_name" });
ensure("land_registry", { source: 1, postcode: 1 }, { name: "lr_source_postcode" });
ensure("land_registry", { company_registration_no: 1 }, { name: "lr_ch_number_sparse", sparse: true });

// ---- audit_log -----------------------------------------------------------
ensure("audit_log", { ts: -1 }, { name: "audit_ts" });
ensure("audit_log", { client_slug: 1, ts: -1 }, { name: "audit_client_ts" });
ensure("audit_log", { actor: 1, ts: -1 }, { name: "audit_actor_ts" });

// ---- suppression_list ----------------------------------------------------
ensure("suppression_list", { hash: 1 }, { name: "suppression_hash_unique", unique: true });

// ---- inbound_leads -------------------------------------------------------
ensure("inbound_leads", { ts: -1 }, { name: "inbound_ts" });
ensure("inbound_leads", { postcode: 1 }, { name: "inbound_postcode" });

// ---- outreach_variants ---------------------------------------------------
ensure("outreach_variants", { theme: 1, performance_score: -1 }, { name: "variants_theme_perf" });

// ---- webhooks_inbox ------------------------------------------------------
ensure("webhooks_inbox", { ts: -1 }, { name: "webhooks_ts" });
ensure("webhooks_inbox", { provider: 1, processed: 1 }, { name: "webhooks_provider_proc" });

db._init_marker.insertOne({ at: new Date(), step: "04-indexes" });
