# WWII UI fixture helper: `setup` pairs isolated TEST_WWII device + mocked library, `beat N` keeps it online,
# `teardown` removes device/games/jobs/mods/releases/pairing code. Token only in /app/test_reports/.wwii_fixture.json.
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
F = "/app/test_reports/.wwii_fixture.json"
P = "/tmp/TEST_WWII"
GAMES = [
    {"name": "Call of Duty®: WWII", "source": "steam", "steam_appid": "476600", "install_dir": f"{P}/steam/WWII", "exe": "s2_sp64_ship.exe",
     "engine": "s2", "game_version": "build 22081346", "campaign_exe": "s2_sp64_ship.exe", "multiplayer_exe": "s2_mp64_ship.exe",
     "campaign_executable_found": True, "wwii_mode": "campaign"},
    {"name": "COD WWII", "source": "folder", "install_dir": f"{P}/folder/MPonly", "exe": None, "engine": "s2",
     "multiplayer_exe": "s2_mp64_ship.exe", "campaign_exe": None, "campaign_executable_found": False, "wwii_mode": "campaign"},
    {"name": "Call of Duty: WWII", "source": "steam", "install_dir": f"{P}/stale/WWII", "exe": "DLogUploader.exe", "engine": "unity-mono",
     "game_version": "build 1"},
    {"name": "TEST_WWII Skyhaven", "source": "folder", "install_dir": f"{P}/folder/Skyhaven", "exe": "Skyhaven.exe", "engine": "unity-mono"},
    {"name": "Call of Duty®: Black Ops Cold War", "source": "steam", "steam_appid": "1985810", "install_dir": f"{P}/steam/BOCW",
     "exe": "BlackOpsColdWar.exe", "engine": "unknown", "game_version": "build 13579"},
]


def setup():
    code = requests.post(f"{API}/devices/pairing-code").json()["code"]
    d = requests.post(f"{API}/companion/pair", json={"code": code, "hostname": "TEST_WWII-host", "os": "Windows-10-TEST",
                                                    "companion_version": "0.3.0"}).json()
    h = {"X-Device-Token": d["token"]}
    requests.post(f"{API}/companion/heartbeat", json={"status": {"version": "0.3.0"}}, headers=h)
    requests.post(f"{API}/companion/games", json={"games": GAMES}, headers=h)
    # stale bogus record (pre-fix scanner): Unity hostable + helper exe
    mdb.games.update_one({"device_id": d["device_id"], "install_dir": f"{P}/stale/WWII"},
                         {"$set": {"hostable": True, "toolchain": "bepinex5-csharp", "adapter_id": "unity-mono-bepinex5"}})
    json.dump({"device_id": d["device_id"], "token": d["token"], "pairing_code": code}, open(F, "w"))
    print("device", d["device_id"])


def beat(seconds):
    f = json.load(open(F))
    end = time.time() + seconds
    while time.time() < end and os.path.exists(F):
        requests.post(f"{API}/companion/heartbeat", json={"status": {"version": os.environ.get("WWII_VER", "0.3.0")}},
                      headers={"X-Device-Token": f["token"]})
        time.sleep(10)


def teardown():
    f = json.load(open(F))
    did = f["device_id"]
    for c in ("games", "jobs", "installs", "pitches"):
        mdb[c].delete_many({"device_id": did})
    pids = [m["id"] for m in mdb.mods.find({"device_id": did}, {"id": 1})]
    mdb.mods.delete_many({"device_id": did})
    for c in ("releases", "versions", "messages", "generations"):
        mdb[c].delete_many({"project_id": {"$in": pids}})
    mdb.devices.delete_one({"id": did})
    mdb.pairing.delete_one({"code": f["pairing_code"]})
    os.remove(F)
    print("cleaned", did, "mods", len(pids))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"setup": setup, "teardown": teardown, "beat": lambda: beat(int(a[1]))}[a[0]]()
