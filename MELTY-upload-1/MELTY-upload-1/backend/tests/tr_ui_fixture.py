"""Fake companion (TEST_TR_UI) with synthetic Cyberpunk folders for driving GamePicker/Trainer UI. Never touches ATLAS.
Usage: python tr_ui_fixture.py [seconds] -> /tmp/TEST_TR_dev.json; touch /tmp/TEST_TR_stop to stop + clean up. setup_tools jobs are never run."""
import os
import sys
import json
import time
import shutil
import importlib
from pathlib import Path
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parents[1] / "frontend" / ".env")
load_dotenv(HERE.parent / ".env")
BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
ROOT = Path("/tmp/TEST_TR_UI")
STOP = Path("/tmp/TEST_TR_stop")
sys.path.insert(0, str(HERE))


def main(secs):
    STOP.unlink(missing_ok=True)
    shutil.rmtree(ROOT, ignore_errors=True)
    os.environ["APPDATA"] = str(ROOT / "appdata")
    sys.path.insert(0, str(HERE.parent / "companion"))
    from test_host_compat import cyberpunk  # noqa: E402
    mc = importlib.import_module("melty_companion")
    cp = cyberpunk(ROOT / "GOG Games" / "Cyberpunk 2077", tools=("cet",))
    cp2 = cyberpunk(ROOT / "Steam" / "Cyberpunk 2077")
    odd = ROOT / "Odd"
    odd.mkdir(parents=True, exist_ok=True)
    code = requests.post(f"{API}/devices/pairing-code").json()["code"]
    r = requests.post(f"{API}/companion/pair", json={"code": code, "hostname": "TEST_TR_UI_PC", "os": "test", "companion_version": "0.5.0"},
                      headers={"User-Agent": "MeltyCompanion"}).json()
    did = r["device_id"]
    mc.CFG.update(server=BASE, token=r["token"], device_id=did)
    games = [{"name": "Cyberpunk 2077", "source": "gog", "install_dir": cp, **mc.identify(cp)},
             {"name": "TEST Cyberpunk NoCET", "source": "steam", "install_dir": cp2, **mc.identify(cp2)},
             {"name": "TEST Odd Game", "source": "folder", "install_dir": str(odd), "engine": "unknown"},
             {"name": "TEST Unreal Game", "source": "folder", "install_dir": str(ROOT / "UE"), "engine": "unreal"}]
    mc.http("POST", "/api/companion/games", {"games": games})
    Path("/tmp/TEST_TR_dev.json").write_text(json.dumps({"did": did, "cp": cp, "cp2": cp2, "odd": str(odd), "token": r["token"]}))
    print("READY", did, cp, flush=True)
    end = time.time() + secs
    try:
        while time.time() < end and not STOP.exists():
            try:
                job = mc.http("GET", "/api/companion/jobs/next").get("job")
            except Exception:
                job = None
            if not job:
                time.sleep(0.3)
                continue
            print("JOB", job["op"], flush=True)
            if job["op"] == "setup_tools":
                res, logtxt, st = {"error": "TEST fixture never downloads"}, "skipped", "failed"
            else:
                try:
                    res, logtxt = mc.HANDLERS[job["op"]](job.get("params") or {}, job)
                    st = "done"
                except Exception as e:
                    res, logtxt, st = {"error": str(e)}, str(e), "failed"
            mc.http("POST", f"/api/companion/jobs/{job['id']}/result", {"status": st, "result": res, "log": logtxt})
    finally:
        for c in ("games", "jobs", "asset_grants", "installs", "trainer_settings"):
            mdb[c].delete_many({"device_id": did})
        mdb.devices.delete_many({"id": did})
        mdb.trainer_presets.delete_many({"install_dir": {"$regex": "^/tmp/TEST_TR_UI"}})
        print("CLEANED", did, flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1500)
