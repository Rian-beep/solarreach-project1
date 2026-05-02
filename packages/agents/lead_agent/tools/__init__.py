"""LangChain @tool wrappers exposing scoring + Mongo I/O to the agent.

Importing this module triggers tool registration as a side effect of @tool;
prefer `from .tools import all_tools` over wildcard imports.
"""

from lead_agent.tools.scoring_tools import all_scoring_tools
from lead_agent.tools.mongo_tools import all_mongo_tools


def all_tools() -> list:
    """Every tool the lead agent has access to. Order is significant only for
    the agent's prompt — the LLM sees them in declaration order."""

    return all_mongo_tools() + all_scoring_tools()


__all__ = ["all_tools", "all_scoring_tools", "all_mongo_tools"]
