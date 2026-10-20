# Cold War UI fixture helper: `setup` creates isolated TEST_CW device/games/mods/releases, `beat` keeps it online,
# `teardown` removes everything. Token kept only in /app/test_reports/.cw_fixture.json (deleted on teardown).
import os
import sys
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
F = "/app/test_reports/.cw_fixture.json"
sys.path.insert(0, str(Path(__file__).parent))
from test_cold_war_compat import games_payload  # noqa: E402

CW = "Call of Duty®: Black Ops Cold War"


def setup():
    code = requests.post(f"{API}/devices/pairing-code").json()["code"]
    d = requests.post(f"{API}/companion/pair", json={"code": code, "hostname": "TEST_CW-host", "os": "Windows-10-TEST",
                                                    "companion_version": "0.3.0"}).json()
    h = {"X-Device-Token": d["token"]}
    requests.post(f"{API}/companion/heartbeat", json={"status": {"version": "0.3.0"}}, headers=h)
    requests.post(f"{API}/companion/games", json={"games": games_payload("build 13579")}, headers=h)
    mdb.games.update_one({"device_id": d["device_id"], "install_dir": "/tmp/TEST_CW/steam/BOCW"}, {"$set": {"hostable": True}})
    base = {"secondary": [], "aspects": [], "description": "legacy", "device_id": d["device_id"], "spec_md": "",
            "files": [{"path": "Plugin.cs", "content": "// TEST_CW"}], "build_status": "unbuilt", "dirty": True,
            "created_at": "2001-01-01T00:00:00+00:00", "updated_at": "2001-01-01T00:00:00+00:00"}
    mdb.mods.insert_one({**base, "id": "TEST_CW_mod_cw", "title": "TEST_CW Legacy CW", "slug": "test-cw-legacy",
                         "host": {"name": CW, "role": "host"}, "adapter_id": "unity-mono-bepinex5", "toolchain": "bepinex5-csharp"})
    mdb.mods.insert_one({**base, "id": "TEST_CW_mod_sky", "title": "TEST_CW Skyhaven", "slug": "test-cw-sky",
                         "host": {"name": "TEST_CW Skyhaven", "role": "host"}, "adapter_id": "unity-mono-bepinex5", "toolchain": "bepinex5-csharp"})
    for rid, pid, host in (("TEST_CW_rel_cw", "TEST_CW_mod_cw", CW), ("TEST_CW_rel_sky", "TEST_CW_mod_sky", "TEST_CW Skyhaven")):
        mdb.releases.insert_one({"id": rid, "project_id": pid, "version": "1.0.0", "published": False, "title": f"TEST_CW {host}",
                                 "host": host, "secondary": [], "compat": {}, "spec_md": "", "created_at": "2001-01-01T00:00:00+00:00",
                                 "manifest": {"name": rid, "version": "1.0.0", "host": {"game": host, "supported_versions": []},
                                              "files": [], "secondary": []}})
    json.dump({"device_id": d["device_id"], "token": d["token"], "pairing_code": code}, open(F, "w"))
    print("device", d["device_id"])


def beat(seconds):
    f = json.load(open(F))
    end = time.time() + seconds
    while time.time() < end:
        requests.post(f"{API}/companion/heartbeat", json={"status": {"version": os.environ.get("CW_VER", "0.3.0")}},
                      headers={"X-Device-Token": f["token"]})
        time.sleep(10)


def teardown():
    f = json.load(open(F))
    did = f["device_id"]
    for c in ("games", "jobs", "installs", "pitches"):
        mdb[c].delete_many({"device_id": did})
    pids = ["TEST_CW_mod_cw", "TEST_CW_mod_sky"]
    mdb.mods.delete_many({"$or": [{"device_id": did}, {"id": {"$in": pids}}]})
    mdb.releases.delete_many({"project_id": {"$in": pids}})
    for c in ("versions", "messages", "generations"):
        mdb[c].delete_many({"project_id": {"$in": pids}})
    mdb.devices.delete_one({"id": did})
    if f.get("pairing_code"):
        mdb.pairing.delete_one({"code": f["pairing_code"]})
    os.remove(F)
    print("cleaned", did)


def control(action, arg=""):
    """UI-test helpers: cancel pending jobs, toggle inspect_game approval, set reported companion version."""
    did = json.load(open(F))["device_id"]
    if action == "cancel":
        mdb.jobs.update_many({"device_id": did, "status": {"$in": ["queued", "needs_approval"]}}, {"$set": {"status": "cancelled"}})
    elif action == "approve":
        ops = [o for o in requests.get(f"{API}/companion/ops").json() if arg == "on" or o != "inspect_game"]
        mdb.devices.update_one({"id": did}, {"$set": {"approved_ops": ops}})
    elif action == "ver":
        mdb.devices.update_one({"id": did}, {"$set": {"status.version": arg}})
    elif action == "last":
        print([j["status"] for j in mdb.jobs.find({"device_id": did}).sort("created_at", -1).limit(1)])


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] in ("cancel", "approve", "ver", "last"):
        control(a[0], a[1] if len(a) > 1 else "")
    else:
        {"setup": setup, "teardown": teardown, "beat": lambda: beat(int(a[1]))}[a[0]]()
