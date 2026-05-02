// 05-agent-databases.js — bootstrap separate DBs for the agent's
// short-term checkpoints and long-term store.
//
// We keep these in their OWN databases (not collections inside `solarreach`)
// so backups, TTLs, and access controls can be set independently per
// workload. Important: langgraph-checkpoint-mongodb auto-creates a
// {thread_id, checkpoint_ns, checkpoint_id} compound index on first use,
// but doing it here too is idempotent and removes a "first call is slow"
// gotcha during the live demo.

print("[05-agent-databases] bootstrapping agent backend DBs");

// ---- Checkpoints (short-term agent state) ---------------------------
const cpDb = db.getSiblingDB("solarreach_agent_checkpoints");

if (!cpDb.getCollectionNames().includes("checkpoints")) {
  cpDb.createCollection("checkpoints");
  print("[05-agent-databases] created checkpoints");
}
if (!cpDb.getCollectionNames().includes("checkpoint_writes")) {
  cpDb.createCollection("checkpoint_writes");
  print("[05-agent-databases] created checkpoint_writes");
}

// Same compound index langgraph-checkpoint-mongodb expects.
cpDb.checkpoints.createIndex(
  { thread_id: 1, checkpoint_ns: 1, checkpoint_id: -1 },
  { name: "checkpoints_thread_ns_id", unique: true }
);
cpDb.checkpoint_writes.createIndex(
  { thread_id: 1, checkpoint_ns: 1, checkpoint_id: -1 },
  { name: "checkpoint_writes_thread_ns_id", unique: true }
);
// TTL safety hatch — delete checkpoints older than 30 days. Set TTL to 0
// to keep forever; we set 30d here as a demo-friendly default.
cpDb.checkpoints.createIndex({ ts: 1 }, { name: "checkpoints_ttl_30d", expireAfterSeconds: 60 * 60 * 24 * 30 });

print("[05-agent-databases] checkpoint indexes ready");

// ---- Long-term store (cross-thread memory) --------------------------
const stDb = db.getSiblingDB("solarreach_agent_store");

if (!stDb.getCollectionNames().includes("store")) {
  stDb.createCollection("store");
  print("[05-agent-databases] created store");
}
// Standard namespace + key lookup. langgraph-store-mongodb uses these.
stDb.store.createIndex({ namespace: 1, key: 1 }, { name: "store_namespace_key", unique: true });
stDb.store.createIndex({ updated_at: -1 }, { name: "store_recency" });

print("[05-agent-databases] store indexes ready");

// Marker so we can introspect init ordering later.
const appDb = db.getSiblingDB("solarreach");
appDb._init_marker.insertOne({ at: new Date(), step: "05-agent-databases" });
