"""Lead Researcher agent.

A deepagents-based agent that:
1. Reads unscored / re-score-eligible leads from MongoDB.
2. Runs the deterministic discovery + composite scoring pipeline as tools.
3. Optionally enriches post-gate (Companies House officers, Solar API).
4. Writes back the score, breakdown, and enrichment to MongoDB.
5. Persists its own short-term memory + long-term notes in MongoDB
   (via langgraph-checkpoint-mongodb + langgraph-store-mongodb).

Public entry points:
- build_lead_agent(): construct the deep agent (no I/O).
- run_lead_agent_session(): one full agent run on a slice of leads.
"""

from lead_agent.agent import build_lead_agent, run_lead_agent_session

__all__ = ["build_lead_agent", "run_lead_agent_session"]
