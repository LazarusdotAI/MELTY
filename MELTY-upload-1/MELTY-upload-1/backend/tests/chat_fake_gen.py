"""Chat line-up helper: insert/finish a FAKE running generation (no AI spend). Usage: python chat_fake_gen.py start|stop <pid>"""
import os
import sys
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
STATE = Path("/tmp/TEST_fake_gen.json")
cmd, pid = sys.argv[1], sys.argv[2]
if cmd == "start":
    gid = "TEST_" + uuid.uuid4().hex
    db.generations.insert_one({"id": gid, "project_id": pid, "kind": "edit", "status": "running", "events": [], "cost": 0, "calls": 0,
                               "created_at": datetime.now(timezone.utc).isoformat()})
    STATE.write_text(json.dumps({"gid": gid, "pid": pid}))
    print("FAKE GEN", gid)
else:
    s = json.loads(STATE.read_text())
    n = db.messages.delete_many({"project_id": pid, "queued": True}).deleted_count
    db.generations.update_one({"id": s["gid"]}, {"$set": {"status": "failed", "error": "TEST fake generation"}})
    print("stopped", s["gid"], "deleted queued", n, "inbox", db.generations.find_one({"id": s["gid"]}, {"_id": 0, "inbox": 1}))
