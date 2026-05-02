"""Lead Researcher agent: build + run.

This module is the only place where deepagents and langgraph collide with
our domain code. Keep it boring.

Design choices (and why):
- We use deepagents.create_deep_agent (not langgraph.prebuilt.create_react_agent)
  so we get planning, file system, and subagent slots for free. The
  Lead Researcher does not currently spawn subagents but we leave the door
  open for Project 3 (codex) to add an outreach-writer subagent later.
- The model defaults to Anthropic Claude Sonnet 4.6 because that's what
  the rest of SolarReach uses for codex/voice. Override via env or arg.
- Checkpointer = MongoDBSaver, ALWAYS. Resumability is non-negotiable —
  the demo cannot afford to lose state mid-run.
- Long-term store is OPTIONAL — passed in only if the caller wants the
  agent to persist learned facts across runs. For one-shot scoring runs
  it's noise.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from pymongo import MongoClient

from lead_agent.backends.mongo import (
    get_mongo_client,
    open_checkpointer,
    open_store,
)
from lead_agent.prompts import LEAD_RESEARCHER_SYSTEM_PROMPT
from lead_agent.tools import all_tools

log = logging.getLogger("lead_agent")


DEFAULT_MODEL = os.environ.get("SOLARREACH_AGENT_MODEL", "anthropic:claude-sonnet-4-6")
DEFAULT_RECURSION_LIMIT = int(os.environ.get("SOLARREACH_AGENT_RECURSION_LIMIT", "60"))


def build_lead_agent(
    *,
    model: str | Any = DEFAULT_MODEL,
    extra_tools: list | None = None,
    system_prompt: str = LEAD_RESEARCHER_SYSTEM_PROMPT,
    checkpointer: Any | None = None,
    store: Any | None = None,
):
    """Construct the deep agent. Returns a compiled LangGraph runnable.

    Pass `checkpointer` (a MongoDBSaver instance) to enable durable thread
    state — strongly recommended in production. In tests with a fake
    backend, pass None to use the default in-memory checkpointer.
    """

    # Lazy import — keeps `pip install solarreach-project1` light.
    from deepagents import create_deep_agent

    tools = all_tools()
    if extra_tools:
        tools = tools + list(extra_tools)

    kwargs: dict[str, Any] = {
        "model": model,
        "tools": tools,
        "system_prompt": system_prompt,
    }
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
    if store is not None:
        kwargs["store"] = store

    return create_deep_agent(**kwargs)


def run_lead_agent_session(
    *,
    client_slug: str,
    batch_size: int = 5,
    thread_id: str | None = None,
    mongo_client: MongoClient | None = None,
    use_long_term_store: bool = False,
    model: str | Any = DEFAULT_MODEL,
) -> dict:
    """One full agent invocation that scores up to `batch_size` leads.

    Returns: {thread_id, final_message, message_count}.

    The caller can re-invoke with the SAME `thread_id` and the agent will
    resume from the last checkpoint. This is how we recover from a crash
    halfway through scoring 50 leads."""

    own_client = False
    if mongo_client is None:
        mongo_client = get_mongo_client()
        own_client = True

    thread_id = thread_id or f"lead-research-{uuid.uuid4().hex[:12]}"
    log.info(f"starting lead agent session client={client_slug} thread={thread_id}")

    try:
        # Open checkpointer (always) and optionally the long-term store.
        with open_checkpointer(mongo_client) as cp:
            agent_kwargs: dict[str, Any] = {
                "model": model,
                "checkpointer": cp,
            }
            if use_long_term_store:
                with open_store(mongo_client) as st:
                    agent_kwargs["store"] = st
                    return _invoke(agent_kwargs, client_slug, batch_size, thread_id)
            return _invoke(agent_kwargs, client_slug, batch_size, thread_id)
    finally:
        if own_client:
            mongo_client.close()


def _invoke(agent_kwargs: dict, client_slug: str, batch_size: int, thread_id: str) -> dict:
    agent = build_lead_agent(**agent_kwargs)
    user_message = (
        f"Score up to {batch_size} unscored leads for client_slug='{client_slug}'. "
        f"Follow the workflow exactly. When you are done, give the one-sentence summary."
    )
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": DEFAULT_RECURSION_LIMIT,
    }
    result = agent.invoke({"messages": [{"role": "user", "content": user_message}]}, config=config)
    msgs = result.get("messages", [])
    final = ""
    if msgs:
        last = msgs[-1]
        final = getattr(last, "content", "") or (last.get("content", "") if isinstance(last, dict) else "")
    return {
        "thread_id": thread_id,
        "final_message": final,
        "message_count": len(msgs),
    }
