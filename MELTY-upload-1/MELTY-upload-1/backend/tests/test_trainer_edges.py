"""Edge cases for Trainer API, manual engine and tools endpoints (fake TEST_TE device only; never ATLAS)."""
import os
from pathlib import Path
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parents[1] / "frontend" / ".env")
load_dotenv(HERE.parent / ".env")
API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
CP = "C:/TEST_TE/Cyberpunk 2077"
CP_NOCET = "C:/TEST_TE/nocet/Cyberpunk 2077"
UE = "C:/TEST_TE/Stalker2"
UNK = "C:/TEST_TE/Mystery"


@pytest.fixture(scope="module")
def dev():
    code = requests.post(f"{API}/devices/pairing-code").json()["code"]
    h = {"User-Agent": "MeltyCompanion"}
    d = requests.post(f"{API}/companion/pair", json={"code": code, "hostname": "TEST_TE_PC", "os": "t", "companion_version": "0.5.0"}, headers=h).json()
    h["X-Device-Token"] = d["token"]
    games = [
        {"name": "Cyberpunk 2077", "source": "gog", "install_dir": CP, "engine": "redengine4", "exe": "bin/x64/Cyberpunk2077.exe", "frameworks": ["cet"]},
        {"name": "Cyberpunk 2077", "source": "steam", "install_dir": CP_NOCET, "engine": "redengine4", "exe": "bin/x64/Cyberpunk2077.exe", "frameworks": []},
        {"name": "S.T.A.L.K.E.R. 2- Heart of Chornobyl", "source": "folder", "install_dir": UE, "engine": "unreal"},
        {"name": "TEST Mystery Game", "source": "folder", "install_dir": UNK, "engine": "unknown"},
    ]
    requests.post(f"{API}/companion/games", json={"games": games}, headers=h).raise_for_status()
    yield {"id": d["device_id"], "h": h, "games": games}
    mdb.devices.delete_one({"id": d["device_id"]})
    for c in ("games", "jobs", "trainer_settings", "asset_grants"):
        mdb[c].delete_many({"device_id": d["device_id"]})
    mdb.trainer_presets.delete_many({"install_dir": {"$regex": "^C:/TEST_TE"}})


def ref(dev, d=CP):
    return {"device_id": dev["id"], "install_dir": d}


def test_statuses_stored(dev):
    recs = {g["install_dir"]: g for g in requests.get(f"{API}/devices/{dev['id']}/games").json()}
    assert recs[CP]["mod_status"] == "READY TO MOD" and recs[CP]["hostable"]
    assert recs[CP_NOCET]["mod_status"] == "SETUP REQUIRED" and recs[CP_NOCET]["hostable"]
    assert recs[UNK]["mod_status"] == "SETUP REQUIRED" and not recs[UNK]["hostable"]
    assert recs[UE]["mod_status"] == "READY TO MOD"


def test_unreal_trainer_requires_build(dev):
    t = requests.get(f"{API}/trainer/game", params=ref(dev, UE)).json()
    assert t["supported"] and all(f["status"] == "Requires Build" and f["why"] for f in t["features"])
    assert requests.post(f"{API}/trainer/install", json=ref(dev, UE)).status_code == 400
    assert requests.post(f"{API}/trainer/apply", json={**ref(dev, UE), "features": {}}).status_code == 400


def test_install_without_cet_rejected(dev):
    r = requests.post(f"{API}/trainer/install", json=ref(dev, CP_NOCET))
    assert r.status_code == 400 and "Cyber Engine Tweaks" in r.json()["detail"]


def test_trainer_unknown_game_404(dev):
    assert requests.get(f"{API}/trainer/game", params=ref(dev, "C:/nope")).status_code == 404


def test_apply_build_only_feature_off_is_not_500(dev):
    r = requests.post(f"{API}/trainer/apply", json={**ref(dev), "features": {"no_recoil": {"on": False}}})
    assert r.status_code != 500, r.text


def test_apply_unknown_feature_is_not_500(dev):
    r = requests.post(f"{API}/trainer/apply", json={**ref(dev), "features": {"bogus": {"on": False}}})
    assert r.status_code in (200, 400), r.status_code


def test_apply_non_numeric_slider_is_not_500(dev):
    r = requests.post(f"{API}/trainer/apply", json={**ref(dev), "features": {"super_speed": {"on": True, "value": "fast"}}})
    assert r.status_code in (200, 400, 422), r.status_code


def test_apply_clamps_and_emergency_clears(dev):
    r = requests.post(f"{API}/trainer/apply", json={**ref(dev), "features": {"bullet_time": {"on": True, "value": -5}}})
    assert r.status_code == 200
    s = mdb.trainer_settings.find_one({"device_id": dev["id"], "install_dir": CP})
    assert s["features"]["bullet_time"]["value"] == 0.1
    e = requests.post(f"{API}/trainer/apply", json={**ref(dev), "features": {"bullet_time": {"on": True}}, "emergency": True})
    assert e.status_code == 200
    s = mdb.trainer_settings.find_one({"device_id": dev["id"], "install_dir": CP})
    assert set(s["features"]) == {"__rev"}
    job = mdb.jobs.find_one({"device_id": dev["id"], "op": "trainer_apply"}, sort=[("created_at", -1)])
    assert job["status"] == "queued" and job["params"]["settings"]["emergency"] is True


def test_preset_crud_and_rename_empty(dev):
    p = requests.post(f"{API}/trainer/presets", json={**ref(dev), "name": "TEST TE one", "features": {"god_mode": {"on": True}}}).json()
    assert requests.patch(f"{API}/trainer/presets/{p['id']}", json={"name": "TEST TE renamed"}).json()["ok"]
    names = [x["name"] for x in requests.get(f"{API}/trainer/game", params=ref(dev)).json()["presets"]]
    assert "TEST TE renamed" in names
    r = requests.patch(f"{API}/trainer/presets/{p['id']}", json={"name": "   "})
    stored = mdb.trainer_presets.find_one({"id": p["id"]})
    assert r.status_code == 400 or stored["name"], "empty rename accepted -> blank preset name"


def test_manual_engine_validation_and_persistence(dev):
    assert requests.post(f"{API}/games/manual", json={**ref(dev, UNK), "engine": "frostbite"}).status_code == 400
    assert requests.post(f"{API}/games/manual", json={**ref(dev, "C:/TEST_TE/new"), "engine": "unreal"}).status_code == 400
    m = requests.post(f"{API}/games/manual", json={**ref(dev, UNK), "engine": "redengine4"}).json()
    assert m["hostable"] and m["mod_status"] == "SETUP REQUIRED" and "_id" not in m
    # rescan reporting engine unknown keeps the manual engine
    requests.post(f"{API}/companion/games", json={"games": dev["games"]}, headers=dev["h"]).raise_for_status()
    g = requests.get(f"{API}/games/details", params=ref(dev, UNK)).json()["game"]
    assert g["engine"] == "redengine4" and g["manual_engine"] == "redengine4"


def test_tools_validation(dev):
    assert requests.post(f"{API}/games/tools", json={**ref(dev), "tools": ["wolvenkit"]}).status_code == 400
    assert requests.post(f"{API}/games/tools", json={**ref(dev, "C:/nope"), "tools": []}).status_code == 404
    s = requests.post(f"{API}/games/tools", json={**ref(dev, CP_NOCET), "tools": ["cet"]}).json()
    assert s["op"] == "setup_tools" and s["status"] == "needs_approval"
    assert s["params"]["tools"][0]["repo"] == "maximegmd/CyberEngineTweaks"
