// 03-validators.js — attach $jsonSchema validators to non-time-series
// collections.  We use validationLevel: "moderate" so historical seed data
// survives schema evolution; new inserts must pass.
//
// IMPORTANT: time-series collections do NOT support $jsonSchema validators
// in Mongo 7. Validate at the application layer (Pydantic models).

db = db.getSiblingDB("solarreach");

const collMod = (name, schema) => {
  db.runCommand({
    collMod: name,
    validator: { $jsonSchema: schema },
    validationLevel: "moderate",
    validationAction: "warn"   // demo-friendly: log but don't reject.
                               // Flip to "error" in prod via collMod.
  });
  print(`[03-validators] applied schema to ${name}`);
};

// ---- leads ---------------------------------------------------------------
collMod("leads", {
  bsonType: "object",
  required: [
    "_id","client_slug","name","premises_type","address","postcode",
    "geo","composite_score","score_breakdown","created_at","updated_at"
  ],
  properties: {
    _id:           { bsonType: "string" },
    client_slug:   { bsonType: "string" },
    name:          { bsonType: "string" },
    premises_type: { bsonType: "string" },
    address:       { bsonType: "string" },
    postcode:      { bsonType: "string" },
    geo: {
      bsonType: "object",
      required: ["point"],
      properties: {
        point: {
          bsonType: "object",
          required: ["type","coordinates"],
          properties: {
            type:        { enum: ["Point"] },
            coordinates: { bsonType: "array", minItems: 2, maxItems: 2 }
          }
        }
      }
    },
    rooftop_polygon: { bsonType: ["object","null"] },
    rooftop_polygon_source: {
      enum: ["inspire_index_polygon","solar_api_bbox","synthesized"]
    },
    inspire_id:      { bsonType: ["string","null"] },
    company_id:      { bsonType: ["string","null"] },
    composite_score: { bsonType: "double", minimum: 0, maximum: 100 },
    score_breakdown: {
      bsonType: "object",
      required: ["solar_roi","financial_health","social_impact"],
      properties: {
        solar_roi:        { bsonType: "double" },
        financial_health: { bsonType: "double" },
        social_impact:    { bsonType: "double" }
      }
    },
    panel_layout:    { bsonType: "array" },
    financial:       { bsonType: ["object","null"] },
    annual_kwh:      { bsonType: ["double","null","int"] },
    panels_count:    { bsonType: "int", minimum: 0 },
    enriched_at:     { bsonType: ["date","null"] },
    created_at:      { bsonType: "date" },
    updated_at:      { bsonType: "date" }
  }
});

// ---- companies -----------------------------------------------------------
collMod("companies", {
  bsonType: "object",
  required: ["_id","proprietor_name","source","created_at","updated_at"],
  properties: {
    _id:                   { bsonType: "string" },
    proprietor_name:       { bsonType: "string" },
    company_number:        { bsonType: ["string","null"] },
    incorporation_country: { bsonType: ["string","null"] },
    registered_address:    { bsonType: ["string","null"] },
    sic_codes:             { bsonType: "array" },
    accounts_summary:      { bsonType: ["object","null"] },
    health_score:          { bsonType: ["double","null"], minimum: 0, maximum: 100 },
    embedding:             { bsonType: ["array","null"] },
    source:                { enum: ["ccod","ocod","companies_house","synthesized"] },
    created_at:            { bsonType: "date" },
    updated_at:            { bsonType: "date" }
  }
});

// ---- directors -----------------------------------------------------------
collMod("directors", {
  bsonType: "object",
  required: ["_id","company_id","full_name","role","source","created_at"],
  properties: {
    _id:                       { bsonType: "string" },
    company_id:                { bsonType: "string" },
    full_name:                 { bsonType: "string" },
    role:                      { bsonType: "string" },
    appointed_on:              { bsonType: ["date","null"] },
    resigned_on:               { bsonType: ["date","null"] },
    email:                     { bsonType: ["string","null"] },
    linkedin_url:              { bsonType: ["string","null"] },
    inferred_decision_maker:   { bsonType: "bool" },
    decision_maker_confidence: { bsonType: ["double","null"], minimum: 0, maximum: 1 },
    source:                    { enum: ["companies_house","hunter","manual","synthesized"] },
    created_at:                { bsonType: "date" }
  }
});

// ---- inspire_polygons ----------------------------------------------------
collMod("inspire_polygons", {
  bsonType: "object",
  required: ["_id","inspire_id","geometry","centroid","area_m2_approx","ingested_at"],
  properties: {
    _id:             { bsonType: "string" },
    inspire_id:      { bsonType: "string" },
    title_no:        { bsonType: ["string","null"] },
    geometry:        { bsonType: "object" },
    centroid:        { bsonType: "object" },
    area_m2_approx:  { bsonType: "double", minimum: 0 },
    local_authority: { bsonType: ["string","null"] },
    ingested_at:     { bsonType: "date" }
  }
});

// ---- land_registry -------------------------------------------------------
collMod("land_registry", {
  bsonType: "object",
  required: ["_id","title_number","proprietor_name","property_address","source","ingested_at"],
  properties: {
    _id:                       { bsonType: "string" },
    title_number:              { bsonType: "string" },
    tenure:                    { bsonType: ["string","null"] },
    proprietor_name:           { bsonType: "string" },
    proprietor_address:        { bsonType: ["string","null"] },
    company_registration_no:   { bsonType: ["string","null"] },
    country_incorporated:      { bsonType: ["string","null"] },
    property_address:          { bsonType: "string" },
    postcode:                  { bsonType: ["string","null"] },
    price_paid_gbp:            { bsonType: ["int","long","null"] },
    date_proprietor_added:     { bsonType: ["date","null"] },
    multiple_address_indicator:{ bsonType: "bool" },
    source:                    { enum: ["ccod","ocod"] },
    ingested_at:               { bsonType: "date" }
  }
});

// ---- clients -------------------------------------------------------------
collMod("clients", {
  bsonType: "object",
  required: ["_id","display_name","primary_color","accent_color","created_at"],
  properties: {
    _id:               { bsonType: "string" },
    display_name:      { bsonType: "string" },
    primary_color:     { bsonType: "string" },
    accent_color:      { bsonType: "string" },
    logo_url:          { bsonType: ["string","null"] },
    pricing_overrides: { bsonType: "object" },
    voice_agent_id:    { bsonType: ["string","null"] },
    created_at:        { bsonType: "date" }
  }
});

// ---- audit_log -----------------------------------------------------------
collMod("audit_log", {
  bsonType: "object",
  required: ["_id","ts","actor","action","cost_cents"],
  properties: {
    _id:            { bsonType: "string" },
    ts:             { bsonType: "date" },
    actor:          { bsonType: "string" },
    action:         { bsonType: "string" },
    lead_id:        { bsonType: ["string","null"] },
    client_slug:    { bsonType: ["string","null"] },
    cost_cents:     { bsonType: "int", minimum: 0 },
    recipient_hash: { bsonType: ["string","null"] },
    metadata:       { bsonType: "object" }
  }
});

db._init_marker.insertOne({ at: new Date(), step: "03-validators" });
