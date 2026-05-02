# Atlas Search + Vector Search index definitions

These two indexes can NOT be created by `mongosh` init scripts. They live on
the Atlas control plane and require either the Atlas UI, the `atlas` CLI, or
a POST to the Atlas Admin API.

For local Docker mongo (no Atlas), the **legacy text index**
`companies_text_fallback` (created in `04-indexes.js`) covers basic
full-text. Vector search has no local equivalent — adapter falls back to
brute-force cosine in the scoring pipeline.

---

## 1. Atlas Search — `companies_text` (Lucene full-text)

Target collection: `solarreach.companies`.
Index name: **`companies_text`**.

```json
{
  "name": "companies_text",
  "definition": {
    "mappings": {
      "dynamic": false,
      "fields": {
        "proprietor_name": [
          { "type": "string", "analyzer": "lucene.standard" },
          { "type": "autocomplete", "tokenization": "edgeGram", "minGrams": 2, "maxGrams": 15 }
        ],
        "registered_address": { "type": "string", "analyzer": "lucene.standard" },
        "sic_codes": { "type": "string", "analyzer": "lucene.keyword" },
        "incorporation_country": { "type": "string", "analyzer": "lucene.keyword" }
      }
    }
  }
}
```

Create via `atlas` CLI:

```bash
atlas clusters search indexes create \
  --clusterName solarreach-prod \
  --db solarreach --collection companies \
  --file infra/mongodb/atlas-search-companies_text.json
```

---

## 2. Atlas Vector Search — `companies_vector` (Voyage AI 1024-dim)

Target collection: `solarreach.companies`, field `embedding`.
Index name: **`companies_vector`**.

```json
{
  "name": "companies_vector",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      {
        "type": "vector",
        "path": "embedding",
        "numDimensions": 1024,
        "similarity": "cosine"
      },
      { "type": "filter", "path": "incorporation_country" },
      { "type": "filter", "path": "source" }
    ]
  }
}
```

---

## 3. Atlas Vector Search — `calls_vector` (transcript chunks)

Target: `solarreach.calls_ts`, field `embedding`.

```json
{
  "name": "calls_vector",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      {
        "type": "vector",
        "path": "embedding",
        "numDimensions": 1024,
        "similarity": "cosine"
      },
      { "type": "filter", "path": "meta.lead_id" },
      { "type": "filter", "path": "meta.role" }
    ]
  }
}
```

> Time-series collections in Mongo 7 support vector search but the create
> command must include `"sourceCollection"` set to the system bucket name —
> see Atlas docs current as of 2026-05.  Project 5 (voice) owns this index.

---

## 4. Verification

After creating, confirm with:

```bash
atlas clusters search indexes list \
  --clusterName solarreach-prod --db solarreach --collection companies
```

Indexes go to `STEADY` after a few minutes for thousands of docs. For
hackathon demo loads (~hundreds of companies), expect <30s.
