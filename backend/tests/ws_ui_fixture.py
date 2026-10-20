"""Long-running fake companion (TEST_WS_PC) for driving the Asset Workshop UI. Never touches ATLAS.
Usage: python ws_ui_fixture.py [seconds]  -> writes /tmp/TEST_WS_dev.json; touch /tmp/TEST_WS_stop to stop + cleanup."""
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
sys.path.insert(0, str(HERE))
import unreal_fixtures as fx  # noqa: E402

ROOT = Path("/tmp/TEST_WS_UI")
STOP = Path("/tmp/TEST_WS_stop")


def main(secs):
    STOP.unlink(missing_ok=True)
    shutil.rmtree(ROOT, ignore_errors=True)
    inst, paks = fx.unreal_game(str(ROOT / "XboxGames" / "S.T.A.L.K.E.R. 2- Heart of Chornobyl" / "Content"), "Stalker2", "WinGDK",
                                "Stalker2-WinGDK-Shipping.exe", "++UE5+Release-5.1", utf16=True, xbox_manifest=("GSC.STALKER2", "1.5.2.0"))
    fx.pak_v11(os.path.join(paks, "pakchunk0-WinGDK.pak"), {"Stalker2/Content/GameLite/Weapons/GunAKM.cfg": fx.STALKER_CFG.encode(),
                                                           "Stalker2/Content/Textures/T_Red.dds": fx.dds_bc1(16, 16)},
               compress={"Stalker2/Content/GameLite/Weapons/GunAKM.cfg"})
    fx.pak_v11(os.path.join(paks, "pakchunk9-WinGDK.pak"), {"Stalker2/Content/secret.bin": b"x"}, encrypted_index=True)
    code = requests.post(f"{API}/devices/pairing-code").json()["code"]
    r = requests.post(f"{API}/companion/pair", json={"code": code, "hostname": "TEST_WS_PC", "os": "test", "companion_version": "0.4.0"},
                      headers={"User-Agent": "MeltyCompanion"}).json()
    did = r["device_id"]
    os.environ["APPDATA"] = str(ROOT / "appdata")
    sys.path.insert(0, str(HERE.parent / "companion"))
    mc = importlib.import_module("melty_companion")
    mc.CFG.update(server=BASE, token=r["token"], device_id=did)
    mc.http("POST", "/api/companion/games", {"games": [{"name": "S.T.A.L.K.E.R. 2- Heart of Chornobyl", "source": "folder", "install_dir": inst,
                                                         "engine": "unreal", "exe": "Stalker2/Binaries/WinGDK/Stalker2-WinGDK-Shipping.exe"}]})
    Path("/tmp/TEST_WS_dev.json").write_text(json.dumps({"did": did, "inst": inst}))
    print("READY", did, inst, flush=True)
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
            try:
                res, logtxt = mc.HANDLERS[job["op"]](job.get("params") or {}, job)
                st = "done"
            except Exception as e:
                res, logtxt, st = {"error": str(e), "state": getattr(e, "state", None)}, str(e), "failed"
            mc.http("POST", f"/api/companion/jobs/{job['id']}/result", {"status": st, "result": res, "log": logtxt})
    finally:
        requests.delete(f"{API}/devices/{did}")
        for c in ("games", "jobs", "asset_grants", "installs"):
            mdb[c].delete_many({"device_id": did})
        mdb.devices.delete_many({"id": did})
        print("CLEANED", did, flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1200)
