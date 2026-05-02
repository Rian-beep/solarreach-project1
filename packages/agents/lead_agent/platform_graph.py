"""LangGraph Platform entry point.

This module exposes a module-level `graph` variable that LangGraph Platform
imports at deploy time. The path is referenced in `langgraph.json` as
  "lead_researcher": "./packages/agents/lead_agent/platform_graph.py:graph"

Why this exists separately from agent.py:

- agent.py's `build_lead_agent()` is a FACTORY — it takes a checkpointer
  and store as arguments, so callers can inject test doubles.
- LangGraph Platform expects a COMPILED graph instance at import time.
  Platform supplies its own checkpointer + store automatically; we must
  not pass our own.

So this module imports the factory, calls it with no checkpointer/store
args (Platform injects), and exposes the result as `graph`.

Environment variables expected at deploy time:
- ANTHROPIC_API_KEY            (model)
- MONGO_URI                    (your tools' Mongo client)
- SOLARREACH_AGENT_MODEL       (optional, defaults to anthropic:claude-sonnet-4-6)

The Mongo URI here is for the TOOLS (which read/write app data). The
checkpointer + long-term store on Platform use Platform's built-in
Postgres-backed persistence — a different concern from your app data.
"""

from __future__ import annotations

from lead_agent.agent import build_lead_agent

# Module-level compiled graph. Platform imports this on cold start.
# DO NOT pass checkpointer or store here — Platform injects its own.
graph = build_lead_agent()
