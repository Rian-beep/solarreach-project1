# SolarReach — Project 1: Data Foundation

This is the **data foundation** workstream of the SolarReach hackathon: MongoDB
schemas, JSON-Schema validators, indexes (2dsphere + Atlas Search/Vector
specs), HM Land Registry CCOD/OCOD ingest, INSPIRE polygon ingest, a
deterministic 250-lead seed for the `client-greensolar-uk` demo client, and
a **deepagents-based Lead Researcher agent** that runs on LangChain and
persists its state in the same MongoDB cluster.

Downstream projects (API/codex, voice, UI, telemetry) consume the collections
and shared package this project ships.

---

## Quick start

```bash
# 1. install
make install                 # editable install with dev extras

# 2. start mongo (init scripts auto-run on first boot)
cp .env.example .env
make up

# 3. seed deterministic 250 leads (mock adapters — no network needed)
make seed

# 4. run tests
make test
```

That's the minimum to have a populated mongo with a working domain model.
For the full pipeline — including real Land Registry data and INSPIRE
polygon snapping — read on. To run the **Lead Researcher agent** (LangChain
DeepAgents on MongoDB), see the agent section below.

---

## The Lead Researcher agent (LangChain DeepAgents on MongoDB)

After leads are seeded, the **Lead Researcher** agent picks up unscored
ones, runs the deterministic discovery + composite scoring pipeline, and
writes results back to Mongo. The agent loop runs on **LangChain**
(via the `deepagents` package on top of LangGraph), and its short-term
state + long-term memory live in the **same MongoDB cluster** as the
application data.

### Architecture: one Mongo cluster, three roles

```
solarreach                       (application data — leads, companies, ...)
solarreach_agent_checkpoints     (langgraph-checkpoint-mongodb · MongoDBSaver)
solarreach_agent_store           (langgraph-store-mongodb     · MongoDBStore)
```

This is the "3-in-one" pattern from LangChain's MongoDB partnership: data,
agent state, and long-term memory share one cluster, so backups and access
control are one job, not three. The agent user (`solarreach_app`) is
granted `readWrite` on all three DBs in `01-users.js`.

### Run the agent

```bash
make install-agent            # one-time: deepagents + langchain-mongodb stack
export ANTHROPIC_API_KEY=...  # or set in .env
make agent                    # score 5 unscored leads
make agent BATCH=20           # bigger batch
```

The output ends with a `thread_id`. Pass it to resume after a crash:

```bash
make agent-resume THREAD=lead-research-abc123def456
```

This works because every step writes a checkpoint via `MongoDBSaver`. Drop
the process mid-run, start it again with the same thread, and the agent
picks up from the last checkpoint instead of re-scoring leads it already
finished.

### What the agent does (workflow enforced by `prompts.py`)

1. `count_leads(client_slug, only_unscored=true)` to gauge work.
2. `fetch_unscored_leads(client_slug, limit=N)` for a batch.
3. For each lead: `discover_signals` → `compute_score` →
   `update_lead_score` → `check_roi_gate` → optionally
   `compute_financials` + `update_lead_financial` → `record_audit_event`.
4. One-line summary at the end.

The agent has six MongoDB tools and four scoring tools (defined in
`packages/agents/lead_agent/tools/`). All Mongo writes go through tool
wrappers — the agent **cannot** issue raw queries — and the wrappers
enforce the polygon-preservation rule (`update_lead_score` never touches
`rooftop_polygon` or `inspire_id`).

### LangSmith tracing (optional but recommended for the demo)

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY=...` in `.env` and
every agent invocation shows up as a replayable trace at
<https://smith.langchain.com>. You can scrub through the agent's tool
calls live — invaluable when the demo goes sideways.

---

## Full data pipeline

```
docker compose up mongo                      # init users + collections + validators + indexes
        │
        ▼
make ingest-lr  CCOD=… OCOD=…                # Land Registry CCOD + OCOD CSVs
        │
        ▼
make ingest-inspire GML_DIR=… BBOX=london    # INSPIRE polygons -> EPSG:4326
        │
        ▼
make seed                                    # 250 deterministic leads
        │
        ▼
make match-inspire                           # snap leads to nearest INSPIRE polygon
        │
        ▼
make test                                    # all green
```

### 1. CCOD/OCOD download

Get the latest two CSVs from
<https://use-land-property-data.service.gov.uk/datasets/ccod> and
<https://use-land-property-data.service.gov.uk/datasets/ocod>.

The CCOD file is ~1.5 GB. The ingest script streams it row by row — never
loads it into memory.

### 2. INSPIRE download

Each English LA publishes its INSPIRE Index Polygons as a GML zip from
<https://use-land-property-data.service.gov.uk/datasets/inspire>. Extract
all of them into one directory and pass it as `GML_DIR=`.

### 3. Adapter mode

By default, every external API uses a deterministic **mock adapter** (no
network, no quota). Flip `SOLARREACH_ADAPTER_MODE=real` (or per-adapter
e.g. `SOLARREACH_SOLAR_MODE=real`) to use Google Solar/Geocoding/Weather,
PVGIS, postcodes.io, Companies House.

---

## What lives where

```
packages/shared/py/solarreach_shared/   # constants, models, financial, compliance, themes
packages/shared/schemas/                # canonical JSON-Schemas (Mongo validator source)
packages/scoring/scoring_worker/        # adapters + composite scoring pipeline
packages/agents/lead_agent/             # deepagents + langchain-mongodb agent
  ├── agent.py                          # build_lead_agent / run_lead_agent_session
  ├── prompts.py                        # system prompt with the workflow
  ├── tools/                            # @tool wrappers: scoring + Mongo I/O
  └── backends/mongo.py                 # MongoDBSaver + MongoDBStore wiring
infra/mongodb/                          # init scripts (01..05) + Atlas Search docs
scripts/                                # ingest_lr, ingest_inspire, match-inspire, seed,
                                        # run_lead_agent
tests/                                  # ≥80 tests across financial, scoring, models,
                                        # compliance, discovery, agent tools, agent mongo
```

---

## Hard-won lessons baked in

These cost real time in earlier iterations. They are now enforced in code
or comments:

1. **`leads.geo` is `{point: GeoJSONPoint}`, NEVER a raw point.** A
   validator + a Pydantic model both enforce this. There's a dedicated test
   in `test_models.py` (`test_lead_geo_wrapper_required`).

2. **INSPIRE GML is in EPSG:27700 (BNG).** Convert to EPSG:4326 BEFORE
   inserting; 2dsphere does not accept BNG. We compute area in BNG (where
   it's meaningful in metres), then reproject. See `scripts/ingest_inspire.py`.

3. **INSPIRE polygons can be gardens, parking, fields.** Filter by area
   `[INSPIRE_MIN_AREA_M2, INSPIRE_MAX_AREA_M2]` (defaults 80–5000 m²).

4. **Polygon preservation rule.** Once a lead has an
   `inspire_index_polygon`, the Solar API axis-aligned 5-corner bbox MUST
   NOT overwrite it. `match_leads_to_inspire.py` enforces this.

5. **Solar API findClosest can return a building 100–300 m away.** Reject
   if `distance > SOLAR_API_MAX_DISTANCE_M` (80 m). Real adapter does this
   inline. The "panels in the wrong courtyard" demo bug.

6. **Solar API GeoTIFF URLs need `?key=` re-appended.** The dataLayers
   response strips your key from the embedded URLs. Real adapter handles it.

7. **Companies House uses HTTP Basic with the API key as username, NO
   password.** And the rate limit is 600 req / 5 min — real adapter sleeps
   0.6 s between calls.

8. **Mongo URI MUST include `?authSource=admin`** because the application
   user lives in the admin DB even though it operates on `solarreach`.
   Forgetting this gives a confusing "auth failed" with the right user.

9. **Time-series collections do not support `$jsonSchema`.** Validate at
   the application layer (Pydantic models). Init script comments this.

10. **Tailwind name collisions.** Custom theme tokens are namespaced
    `app-*` / `gotham-*`. Naming a custom color `base`/`sm`/`lg` silently
    blanks out text — see `themes.py`.

11. **Audit log NEVER stores raw email/phone**, only `sha256` hex hash.
    `compliance.hash_recipient` is the only writer.

12. **AI disclosure check.** Voice agent system prompt MUST include both an
    "AI" token AND a "disclos*" / "automated" token. `check_ai_disclosure`
    enforces; voice service hard-fails boot on a bad prompt.

13. **Re-seed safety.** Lead `_id` is `lead_<sha1>_<run_uuid_8>`, so
    re-seeding without `--fresh` never collides.

14. **Premises type is bound to the name pattern in the seed.** A "Logistics
    Hub" never gets named "St Mary's School". Random premises type +
    random name = ridiculous demo.

15. **CCOD ingest streams `csv.DictReader`, NEVER pandas.** The 1.5 GB CCOD
    file would OOM a 4 GB worker.

16. **Three Mongo DBs, one cluster.** App data, agent checkpoints, and the
    long-term store live in **separate databases** (not collections) so
    backups, TTLs, and access scopes can be set per workload. The agent
    checkpointer auto-creates a `(thread_id, checkpoint_ns, checkpoint_id)`
    unique index on first call — `05-agent-databases.js` creates it
    eagerly so the demo's first scoring call isn't slow.

17. **The agent NEVER touches Mongo directly — only through tool wrappers.**
    Wrappers enforce: composite_score in [0,100], breakdown keys present,
    polygon preservation rule, recipient hashing in audit_log. Even if the
    LLM hallucinates a payload, the wrapper rejects it with `{ok: false}`.

18. **Tools cap their own response sizes.** `fetch_unscored_leads` caps at
    50 even if asked for 9999. `get_lead` strips the rooftop polygon. This
    matters because LLM context is the constraint that breaks first under
    real load.

---

## Acceptance criteria

| # | Check | How to verify |
|---|-------|--------------|
| 1 | `make seed` produces 250 leads with `composite_score` in [0, 100] and `score_breakdown` populated | `db.leads.countDocuments({client_slug: 'client-greensolar-uk'})` |
| 2 | All seeded leads have a `company_id` linked to a `companies` doc | `db.leads.aggregate([{$lookup:{from:'companies', localField:'company_id', foreignField:'_id', as:'co'}}, {$match:{co:{$size:0}}}, {$count:'orphans'}])` returns 0 |
| 3 | `geo.point` 2dsphere index exists | `db.leads.getIndexes()` includes `leads_geo_point_2dsphere` |
| 4 | After `match-inspire`, ≥80% of leads have `rooftop_polygon_source = "inspire_index_polygon"` (assuming INSPIRE data was ingested) | Pipeline reports coverage % at end |
| 5 | All tests pass | `make test` |
| 6 | Score weights sum to 1.0 | Module import would raise — `python -c 'import solarreach_shared'` exits 0 |
| 7 | After `make agent`, agent-processed leads have `composite_score` set and an `audit_log` entry with `actor='agent.lead_researcher'` | `db.audit_log.countDocuments({actor: 'agent.lead_researcher'})` > 0 |
| 8 | Agent state is durable: kill mid-run, `make agent-resume THREAD=...` continues without re-scoring earlier leads | check the `solarreach_agent_checkpoints.checkpoints` collection has rows for the thread_id |

---

## Notes for downstream projects

- **Project 2 (3D viewer):** `leads.geo.point` is the pin location; if
  `rooftop_polygon` is non-null, render it as the building footprint
  (preferred). Otherwise fall back to the synthetic axis-aligned bbox.
- **Project 3 (codex/outreach):** Read `companies.embedding` (1024-dim
  Voyage 'voyage-3') for similarity-based variant selection. The
  `companies_vector` Atlas Search index covers it.
- **Project 4 (telemetry):** Time-series collections are
  `energy_yield_ts` / `weather_ts` / `calls_ts` — granularity hours / hours
  / seconds respectively.
- **Project 5 (voice):** `check_ai_disclosure(system_prompt)` must be
  called at boot. Reject startup on failure.
- **Project 6 (UI):** Theme tokens are in `themes.py`; do NOT introduce
  Tailwind utility-shadowing names.
