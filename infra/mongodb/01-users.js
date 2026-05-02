// 01-users.js — runs once on fresh mongo data dir.
// Creates the application user. Never edit; bind variables via env.
//
// IMPORTANT: this script reads MONGO_INITDB_ROOT_USERNAME / PASSWORD set in
// docker-compose.yml.  The application user MUST authenticate against the
// admin database (?authSource=admin in URI) — easy to forget, breaks silently.

const dbName = "solarreach";
const checkpointDb = "solarreach_agent_checkpoints";
const storeDb = "solarreach_agent_store";
const appUser = process.env.SOLARREACH_DB_USER || "solarreach_app";
const appPwd = process.env.SOLARREACH_DB_PASSWORD || "change-me-in-prod";

db = db.getSiblingDB("admin");

if (!db.getUser(appUser)) {
  db.createUser({
    user: appUser,
    pwd: appPwd,
    roles: [
      { role: "readWrite", db: dbName },
      { role: "dbAdmin", db: dbName },
      // Agent backends live in their own DBs; same user reads/writes both.
      { role: "readWrite", db: checkpointDb },
      { role: "readWrite", db: storeDb }
    ]
  });
  print(`[01-users] created user ${appUser}`);
} else {
  print(`[01-users] user ${appUser} already exists, skipping`);
}

// Create empty database (collections come in step 2).
db = db.getSiblingDB(dbName);
db.createCollection("_init_marker");
db._init_marker.insertOne({ at: new Date(), step: "01-users" });
