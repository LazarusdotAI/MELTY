"""End-to-end Asset Workshop test: live backend + a simulated paired PC running the real companion handlers
on a synthetic (freely licensed) Unreal install. Never touches ATLAS or real games."""
import os
import sys
import time
import threading
import importlib
from pathlib import Path
import pytest
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

ROOT = Path("/tmp/TEST_WS")
CFG_TXT = fx.STALKER_CFG.encode()


@pytest.fixture(scope="module")
def pc():
    import shutil
    shutil.rmtree(ROOT, ignore_errors=True)
    inst, paks = fx.unreal_game(str(ROOT / "XboxGames" / "S.T.A.L.K.E.R. 2- Heart of Chornobyl" / "Content"), "Stalker2", "WinGDK",
                                "Stalker2-WinGDK-Shipping.exe", "++UE5+Release-5.1", utf16=True, xbox_manifest=("GSC.STALKER2", "1.5.2.0"))
    fx.pak_v11(os.path.join(paks, "pakchunk0-WinGDK.pak"), {"Stalker2/Content/GameLite/Weapons/GunAKM.cfg": CFG_TXT,
                                                           "Stalker2/Content/Textures/T_Red.dds": fx.dds_bc1(16, 16)},
               compress={"Stalker2/Content/GameLite/Weapons/GunAKM.cfg"})
    fx.pak_v11(os.path.join(paks, "pakchunk9-WinGDK.pak"), {"Stalker2/Content/secret.bin": b"x"}, encrypted_index=True)
    code = requests.post(f"{API}/devices/pairing-code").json()["code"]
    r = requests.post(f"{API}/companion/pair", json={"code": code, "hostname": "TEST_WS_PC", "os": "test", "companion_version": "0.4.0"},
                      headers={"User-Agent": "MeltyCompanion"}).json()
    os.environ["APPDATA"] = str(ROOT / "appdata")
    sys.path.insert(0, str(HERE.parent / "companion"))
    sys.modules.pop("melty_companion", None)
    mc = importlib.import_module("melty_companion")
    mc.CFG.update(server=BASE, token=r["token"], device_id=r["device_id"])
    mc.http("POST", "/api/companion/games", {"games": [{"name": "S.T.A.L.K.E.R. 2- Heart of Chornobyl", "source": "folder", "install_dir": inst,
                                                         "engine": "unreal", "exe": "Stalker2/Binaries/WinGDK/Stalker2-WinGDK-Shipping.exe"}]})
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                job = mc.http("GET", "/api/companion/jobs/next").get("job")
            except Exception:
                job = None
            if not job:
                time.sleep(0.5)
                continue
            try:
                res, logtxt = mc.HANDLERS[job["op"]](job.get("params") or {}, job)
                st = "done"
            except Exception as e:
                res, logtxt, st = {"error": str(e), "state": getattr(e, "state", None)}, str(e), "failed"
            mc.http("POST", f"/api/companion/jobs/{job['id']}/result", {"status": st, "result": res, "log": logtxt})
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    yield {"did": r["device_id"], "inst": inst, "paks": paks, "mc": mc}
    stop.set()
    requests.delete(f"{API}/devices/{r['device_id']}")
    mdb.devices.delete_one({'id': r['device_id']})
    for c in ("games", "jobs", "asset_grants", "installs"):
        mdb[c].delete_many({"device_id": r["device_id"]})


def wait(jid, t=60):
    end = time.time() + t
    while time.time() < end:
        j = next((x for x in requests.get(f"{API}/workshop/ops", params={"limit": 200}).json() if x["id"] == jid), None)
        if j and j["state"] not in ("Pending", "Running"):
            return j
        time.sleep(0.5)
    raise AssertionError("job did not finish")


def post(path, pc, **body):
    r = requests.post(f"{API}/workshop/{path}", json={"install_dir": pc["inst"], "device_id": pc["did"], **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_full_asset_pipeline(pc):
    s = wait(post("scan", pc)["id"])
    assert s["state"] == "Completed"
    scan = s["result"]
    assert scan["engine_version"] == "5.1" and scan["store_version"] == "1.5.2.0"
    pak = next(c["path"] for c in scan["containers"] if c["path"].endswith("pakchunk0-WinGDK.pak"))
    enc = next(c for c in scan["containers"] if c["path"].endswith("pakchunk9-WinGDK.pak"))
    assert enc["state"] == "blocked_by_protection"

    lst = post("list", pc, container=pak)
    assert lst["total"] == 2

    # first extraction from this game asks permission
    j = post("extract", pc, container=pak, paths=["Stalker2/Content/GameLite/Weapons/GunAKM.cfg"])
    assert j["state"] == "Permission Required"
    time.sleep(2)
    assert wait(j["id"], 3)["state"] == "Permission Required"  # never runs without approval
    requests.post(f"{API}/jobs/{j['id']}/approve")
    e1 = wait(j["id"])
    assert e1["state"] == "Completed" and e1["result"]["source_untouched"]
    # once per game: the second one runs straight away
    j2 = post("extract", pc, container=pak, paths=["Stalker2/Content/Textures/T_Red.dds"])
    assert j2["state"] == "Pending"
    e2 = wait(j2["id"])
    assert e2["state"] == "Completed"
    outs = [x["out"] for x in e1["result"]["extracted"] + e2["result"]["extracted"]]
    assert open(outs[0], "rb").read() == CFG_TXT

    c = wait(post("convert", pc, files=outs)["id"])
    assert c["state"] == "Completed"
    reps = {Path(r["source"]).suffix: r for r in c["result"]["reports"]}
    assert reps[".dds"]["converted"] and reps[".dds"]["validation"][0]["ok"] and reps[".dds"].get("preview") == "preview_1.png"
    assert requests.get(f"{API}/jobs/{c['id']}/artifact/preview_1.png").content[:4] == b"\x89PNG"
    assert reps[".cfg"]["converted"]

    pk = wait(post("package", pc, package_name="AKM Tweak", files=[{"src": outs[0], "dest": "Stalker2/Content/GameLite/Weapons/GunAKM.cfg"}])["id"])
    assert pk["state"] == "Completed" and pk["result"]["verify"]["ok"] and pk["result"]["personal_use_only"]
    pkg = pk["result"]["package"]

    ins = post("install", pc, package=pkg)
    assert ins["state"] == "Permission Required"
    requests.post(f"{API}/jobs/{ins['id']}/approve")
    ins = wait(ins["id"])
    assert ins["state"] == "Completed"
    target = Path(pc["inst"]) / ins["result"]["installed_to"]
    assert target.exists() and "~mods" in str(target)

    t = wait(post("test-package", pc, package=pkg)["id"])
    assert t["result"]["package_ok"] and t["result"]["installed"]

    rb = requests.post(f"{API}/workshop/rollback", json={"install_id": ins["result"]["install_id"], "device_id": pc["did"]}).json()
    assert wait(rb["id"])["state"] == "Completed" and not target.exists()

    cl = wait(post("cleanup", pc)["id"])
    assert cl["state"] == "Completed" and cl["result"]["freed_bytes"] > 0


def test_encrypted_container_reports_unsupported_and_bad_paths_fail(pc):
    pak9 = os.path.join(pc["paks"], "pakchunk9-WinGDK.pak")
    requests.post(f"{API}/workshop/grants/revoke", json={"install_dir": pc["inst"], "device_id": pc["did"]})
    j = post("extract", pc, container=pak9, paths=["Stalker2/Content/secret.bin"])
    requests.post(f"{API}/jobs/{j['id']}/approve")
    r = wait(j["id"])
    assert r["state"] == "Unsupported" and "encrypt" in (r["why"] or "").lower()
    bad = wait(post("extract", pc, container="/etc/passwd", paths=["x"])["id"])
    assert bad["state"] == "Failed" and "not inside" in bad["why"]
    v = wait(post("validate", pc, files=["/etc/hosts"])["id"])
    assert v["state"] == "Failed"


def test_unknown_game_rejected(pc):
    r = requests.post(f"{API}/workshop/scan", json={"install_dir": "C:/NotAGame", "device_id": pc["did"]})
    assert r.status_code == 404
