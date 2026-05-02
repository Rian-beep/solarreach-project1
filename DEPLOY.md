# Deploy Project 1 to MongoDB Atlas + LangGraph Platform

The "no laptop after setup" deployment path. Once you've done these steps,
your team can run the agent from the LangGraph Studio browser UI; data
lives in your Atlas cluster; traces appear in LangSmith.

## What you'll have at the end

- 250 demo leads in your Atlas cluster, with all collections / validators / indexes
- The Lead Researcher agent deployed to LangGraph Platform as a hosted endpoint
- A LangGraph Studio URL your team can open in any browser to chat with the agent
- LangSmith traces of every run, automatically

## You need

- A MongoDB Atlas cluster (you have this)
- A LangGraph Platform / LangSmith Deployment account (you have this)
- A GitHub account
- An Anthropic API key (console.anthropic.com → API Keys)
- Python 3.12 installed locally (only to run the one-time setup scripts)

## Time required

About 25 minutes total. The longest wait is LangGraph Platform building the
container (~5 min on first deploy).

---

# Phase A: Get data into Atlas (10 min, one-time)

## A1. Get your Atlas connection string

In Atlas → your cluster → **Connect** → **Drivers** → Python 3.12+. Copy the
URI. Edit it so it has your password, the database name, and authSource:

```
mongodb+srv://USER:PASSWORD@cluster-xxx.mongodb.net/solarreach?retryWrites=true&w=majority&authSource=admin
```

The user needs **Read and write to any database** privileges (Atlas → Database Access).
Network Access must include your IP (or `0.0.0.0/0` for the hackathon).

## A2. Set up Atlas (collections, validators, indexes, agent DBs)

Locally — only needs pymongo:

```bash
pip install pymongo
export MONGO_URI='mongodb+srv://USER:PASSWORD@cluster-xxx.mongodb.net/solarreach?retryWrites=true&w=majority&authSource=admin'
python scripts/setup_atlas.py
```

You'll see four sections of output:
- `[1/4]` creates 11 standard + 3 time-series collections
- `[2/4]` applies JSON Schema validators
- `[3/4]` creates 20+ indexes including the 2dsphere geo index
- `[4/4]` creates `solarreach_agent_checkpoints` + `solarreach_agent_store` databases

Idempotent — safe to re-run if it errors halfway through.

## A3. Seed 250 demo leads

```bash
python scripts/seed_atlas_standalone.py
```

Takes about 5 seconds. Verify in the Atlas UI → Browse Collections →
`solarreach.leads` → you should see 250 documents.

That's Phase A. Your data foundation is live and your team can start
building Projects 2-6 against it RIGHT NOW even if you skip Phase B.

---

# Phase B: Deploy the agent to LangGraph Platform (15 min)

## B1. Push Project 1 to a private GitHub repo

In GitHub:
1. Click **New repository**
2. Name: `solarreach-project1` (or whatever — it's private)
3. **Private** visibility
4. Don't initialize with README/license/gitignore
5. **Create repository**

Then locally, in the project1 directory:

```bash
git init
git add .
git commit -m "Initial Project 1"
git branch -M main
git remote add origin git@github.com:YOUR-USERNAME/solarreach-project1.git
git push -u origin main
```

(Use HTTPS instead of SSH if that's how your GitHub auth is set up — GitHub
shows both forms when you create a new repo.)

## B2. Deploy from LangGraph Platform UI

In smith.langchain.com:

1. Left sidebar → **Deployments** (or "LangSmith Deployment")
2. Click **+ New Deployment**
3. **Connect GitHub** if you haven't already — authorize the LangChain app
4. Select your repo `solarreach-project1`, branch `main`
5. **LangGraph config file**: `langgraph.json` (default — already at the repo root)
6. **Deployment name**: `solarreach-lead-researcher`
7. **Deployment type**: Development (for the hackathon — cheaper, may sleep when idle)

## B3. Set environment variables

Before clicking Deploy, set these env vars in the LangGraph Platform UI:

| Key | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your `sk-ant-...` key |
| `MONGO_URI` | your Atlas URI from A1 (the same one) |
| `SOLARREACH_AGENT_MODEL` | `anthropic:claude-sonnet-4-6` (default; can omit) |
| `SOLARREACH_ADAPTER_MODE` | `mock` (keep mocks for the hackathon — no Google API charges) |

Click **Submit** / **Deploy**.

## B4. Wait for the build

LangGraph Platform builds a container with your dependencies. First build
takes about 5 minutes — you can watch the logs in the UI.

Status goes: `Building` → `Deploying` → `Active`.

When it's `Active` you'll see:
- An **API URL** (like `https://solarreach-...langgraph.app`)
- A **LangGraph Studio URL** — click this

## B5. Talk to the agent in LangGraph Studio

LangGraph Studio opens in a new tab. You'll see the graph visualised on the
left and a chat panel on the right.

In the chat, type:

```
Score 5 unscored leads for client_slug='client-greensolar-uk'
```

Watch the agent loop:
- Calls `count_leads` → finds 0 unscored (the seed populated everything)

Wait — we need unscored leads first. Open Atlas Data Explorer → `solarreach.leads`
collection → run this in the **mongosh shell** at the top:

```javascript
db.leads.updateMany({}, { $unset: { composite_score: "", enriched_at: "" } })
```

Now back in Studio, type the same prompt. The agent will:
- Count: 250 unscored
- Fetch a batch of 5
- For each: discover → score → write to Mongo → check gate → maybe enrich → audit
- Return a one-line summary

Every step shows up in LangSmith traces (smith.langchain.com → Tracing).

---

# Phase C: Share with your team (1 min)

Send teammates:

1. **The Studio URL** from B4 — they can open it in any browser to chat with the agent
2. **The Atlas URI** (or have admin add them as users) — for projects that need direct DB access
3. **A link to this repo** so they can read the architecture

---

# Day-to-day operation

The agent runs entirely in LangGraph Platform after deploy. You don't need
your laptop. Anyone with Studio access can:

- Trigger runs from the chat UI
- Resume crashed runs by selecting the same thread
- See full history per thread

When you push code changes to GitHub `main`, LangGraph Platform auto-redeploys.

---

# Architecture recap

```
GitHub repo                      MongoDB Atlas
   │                                  │
   │ (autodeploy on push)             │  (data + agent state + memory)
   ▼                                  │
LangGraph Platform                    │
   │                                  │
   │ (hosts the graph)                │
   ├─── tools call ─────────────────► │  solarreach            (app data)
   ├─── checkpointer (built in) ────► │  Platform's Postgres
   │                                  │
   ▼                                  │
LangGraph Studio (browser UI)         │
   │                                  │
   │ (every run streams to)           │
   ▼                                  │
LangSmith Traces                      │
```

Two notes:

1. **The agent's checkpoint storage on Platform is Platform's built-in
   Postgres**, not your `solarreach_agent_checkpoints` Mongo database. We
   created the Mongo database too because it's useful for self-hosted
   deployments later (Project 4 telemetry can run its own agent against it
   without paying for Platform).

2. **`SOLARREACH_ADAPTER_MODE=mock`** keeps the agent off paid Google APIs.
   Flip to `real` only after adding `GOOGLE_API_KEY` and
   `COMPANIES_HOUSE_API_KEY` env vars in the Platform UI.

---

# Troubleshooting

**Setup script `auth failed`** — your URI is missing `authSource=admin` at the end, or the password contains a special character. Regenerate the password without `@`, `/`, `:`, `?`, `#`, `&`.

**Setup script `connection timeout`** — Atlas Network Access doesn't include your IP. Add `0.0.0.0/0` for the hackathon.

**LangGraph build fails on `lxml`** — the Platform build container should have wheels for it, but if it doesn't, edit `pyproject.toml` and remove `lxml`, `pyproj`, `shapely` from the `dependencies` list. Those are only needed for the INSPIRE/CCOD ingest scripts, not for the agent.

**Studio shows "Graph not found"** — `langgraph.json` is missing from the repo root, or its path to `platform_graph.py:graph` is wrong. Check `git ls-files langgraph.json` returns the file.

**Agent says "no work"** — you forgot to unset scores in B5. Re-run the `db.leads.updateMany` command.

**Anthropic rate limit errors** — drop batch size to 3. Each lead is 5-7 LLM calls.
