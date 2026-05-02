"""MongoDB backends for the lead agent.

We use ONE Mongo cluster for THREE purposes (the "3-in-one" pattern from
LangChain's MongoDB partnership announcement):

  1. Application data       -> solarreach DB (leads, companies, etc.)
  2. Short-term agent state -> solarreach_agent_checkpoints DB
                               (managed by langgraph-checkpoint-mongodb)
  3. Long-term agent memory -> solarreach_agent_store DB
                               (managed by langgraph-store-mongodb)

Separating into three logical DBs (not collections) means we can easily set
different TTLs / backup policies / read concerns per workload, and we never
risk the agent's checkpoint writes silently colliding with application
writes via shared collection names.

DEFERRED IMPORTS: langgraph-checkpoint-mongodb and langgraph-store-mongodb
are heavy installs and only needed when the agent runs. We import inside
the functions so unit tests of unrelated modules don't pull them in.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from pymongo import MongoClient


def get_mongo_client(uri: str | None = None) -> MongoClient:
    """Build a MongoClient. Honours MONGO_URI env if not passed.

    The application user lives in `admin` (per 01-users.js) so the URI must
    end with ?authSource=admin — see .env.example.
    """

    final_uri = uri or os.environ.get("MONGO_URI")
    if not final_uri:
        raise RuntimeError("MONGO_URI not set and no uri passed to get_mongo_client()")
    # serverSelectionTimeoutMS keeps tests + dev fast on a wrong URI.
    return MongoClient(final_uri, serverSelectionTimeoutMS=3000)


# ---------------------------------------------------------------------------
# Names — kept here so they are easy to grep across services.
# ---------------------------------------------------------------------------
APP_DB_NAME = "solarreach"
CHECKPOINT_DB_NAME = "solarreach_agent_checkpoints"
STORE_DB_NAME = "solarreach_agent_store"

CHECKPOINT_COLL = "checkpoints"          # langgraph default; explicit for clarity
CHECKPOINT_WRITES_COLL = "checkpoint_writes"
STORE_COLL = "store"                     # singular; multi-namespace within


# ---------------------------------------------------------------------------
# Checkpointer (short-term memory; per-thread agent state)
# ---------------------------------------------------------------------------
@contextmanager
def open_checkpointer(client: MongoClient | None = None):
    """Context-managed MongoDBSaver. Indexes auto-created on first call.

    Usage:
        with open_checkpointer(client) as cp:
            agent = build_lead_agent(checkpointer=cp, ...)
            agent.invoke({"messages": [...]}, config={"configurable": {"thread_id": "..."}})
    """

    # langgraph-checkpoint-mongodb is an optional/heavy dep; import lazily.
    from langgraph.checkpoint.mongodb import MongoDBSaver

    owned_client = False
    if client is None:
        client = get_mongo_client()
        owned_client = True
    try:
        # Direct constructor takes a live MongoClient + db_name; the
        # `from_conn_string` classmethod accepts a string and is a context
        # manager. We use the constructor so callers can share a client.
        saver = MongoDBSaver(
            client,
            db_name=CHECKPOINT_DB_NAME,
            checkpoint_collection_name=CHECKPOINT_COLL,
            writes_collection_name=CHECKPOINT_WRITES_COLL,
        )
        yield saver
    finally:
        if owned_client:
            client.close()


# ---------------------------------------------------------------------------
# Long-term store (cross-thread, namespaced facts the agent learns)
# ---------------------------------------------------------------------------
@contextmanager
def open_store(client: MongoClient | None = None):
    """Context-managed MongoDBStore. Use for facts that should survive across
    sessions / threads (e.g. 'this postcode is consistently low IMD',
    'this proprietor is a holding company, look at subsidiaries').
    """

    from langgraph.store.mongodb import MongoDBStore

    owned_client = False
    if client is None:
        client = get_mongo_client()
        owned_client = True
    try:
        store = MongoDBStore(
            client,
            db_name=STORE_DB_NAME,
            collection_name=STORE_COLL,
        )
        yield store
    finally:
        if owned_client:
            client.close()
