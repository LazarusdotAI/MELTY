# Cold War (T9) compatibility-first Phase 1: API regression tests using an isolated TEST_CW fixture device.
# Never touches ATLAS or any other real device. No AI calls (only requests that are blocked before budget/generation).
import os
import time
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
ATLAS = "761878c002d84bdba20614a4e5890604"
REASON = "Not supported by MELTY — host compatibility unverified"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

CW_STEAM = "/tmp/TEST_CW/steam/BOCW"
CW_REG = "/tmp/TEST_CW/reg/ColdWar"
CW_ALIAS = "/tmp/TEST_CW/folder/Generic"
SKY = "/tmp/TEST_CW/folder/Skyhaven"
KF2 = "/tmp/TEST_CW/steam/KF2"
MW = "/tmp/TEST_CW/steam/MW"
APPONLY = "/tmp/TEST_CW/steam/AppOnly"


def games_payload(steam_version="build ?"):
    return [
        {"name": "Call of Duty®: Black Ops Cold War", "source": "steam", "steam_appid": "1985810", "install_dir": CW_STEAM,
         "exe": "BlackOpsColdWar.exe", "engine": "unknown", "game_version": steam_version},
        {"name": "Black Ops Cold War™", "source": "registry", "install_dir": CW_REG, "exe": None, "engine": "t9",
         "game_version": "1.34.0", "installation_exists": True, "executable_exists": False},
        {"name": "TEST_CW Generic", "source": "folder", "install_dir": CW_ALIAS, "exe": "BlackOpsColdWar.exe",
         "engine": "unity-mono", "managed_dir": CW_ALIAS + "/X_Data/Managed"},
        {"name": "TEST_CW Skyhaven", "source": "folder", "install_dir": SKY, "exe": "Skyhaven.exe", "engine": "unity-mono",
         "managed_dir": SKY + "/Skyhaven_Data/Managed", "unity_version": "2021.3.1f1"},
        {"name": "Killing Floor 2", "source": "steam", "steam_appid": "232090", "install_dir": KF2, "exe": "Binaries/Win64/KFGame.exe",
         "engine": "unreal3", "sdk_installed": True, "game_version": "build 1"},
        {"name": "Call of Duty: Modern Warfare", "source": "steam", "steam_appid": "2000950", "install_dir": MW, "exe": "cod.exe",
         "engine": "unknown"},
        {"name": "TEST_CW AppOnly", "source": "steam", "steam_appid": "1985810", "install_dir": APPONLY,
         "exe": "Game-Win64-Shipping.exe", "engine": "unreal"},
    ]


@pytest.fixture(scope="module")
def dev():
    s = requests.Session()
    code = s.post(f"{API}/devices/pairing-code").json()["code"]
    r = s.post(f"{API}/companion/pair", json={"code": code, "hostname": "TEST_CW-host", "os": "Windows-10-TEST",
                                              "companion_version": "0.3.0"})
    assert r.status_code == 200
    d = r.json()
    assert d["device_id"] != ATLAS
    h = {"X-Device-Token": d["token"]}
    s.post(f"{API}/companion/heartbeat", json={"status": {"version": "0.3.0"}}, headers=h)
    assert s.post(f"{API}/companion/games", json={"games": games_payload()}, headers=h).status_code == 200
    info = {"id": d["device_id"], "h": h, "s": s, "mods": [], "releases": [], "code": code}
    yield info
    did = d["device_id"]
    for c in ("games", "jobs", "installs", "pitches"):
        mdb[c].delete_many({"device_id": did})
    mdb.mods.delete_many({"$or": [{"device_id": did}, {"id": {"$in": info["mods"]}}]})
    mdb.releases.delete_many({"id": {"$in": info["releases"]}})
    mdb.versions.delete_many({"project_id": {"$in": info["mods"]}})
    mdb.messages.delete_many({"project_id": {"$in": info["mods"]}})
    mdb.devices.delete_one({"id": did})
    mdb.pairing.delete_one({"code": info["code"]})


def beat(dev, version="0.3.0"):
    dev["s"].post(f"{API}/companion/heartbeat", json={"status": {"version": version}}, headers=dev["h"])


def gmap(dev):
    return {g["install_dir"]: g for g in requests.get(f"{API}/devices/{dev['id']}/games").json()}


# ---- identification & stale override ----
def test_adapter_identification(dev):
    g = gmap(dev)
    for p in (CW_STEAM, CW_REG, CW_ALIAS, APPONLY):
        assert g[p]["adapter_id"] == "cold-war-t9", p
        assert g[p]["hostable"] is False and g[p]["host_reason"] == REASON and g[p]["toolchain"] is None
    assert g[SKY]["hostable"] is True and g[SKY]["toolchain"] == "bepinex5-csharp"
    assert g[KF2]["hostable"] is True and g[KF2]["toolchain"] == "ue3-unrealscript"
    assert g[MW]["adapter_id"] == "blocked-anticheat" and g[MW]["hostable"] is False


def test_stale_hostable_overridden(dev):
    mdb.games.update_one({"device_id": dev["id"], "install_dir": CW_STEAM},
                         {"$set": {"hostable": True, "toolchain": "bepinex5-csharp", "adapter_id": "unity-mono-bepinex5",
                                   "adapter_status": "documented", "host_reason": None}})
    try:
        assert gmap(dev)[CW_STEAM]["hostable"] is False
        d = requests.get(f"{API}/games/details", params={"device_id": dev["id"], "install_dir": CW_STEAM}).json()
        assert d["buildable_host"] is False and d["game"]["host_reason"] == REASON and d["adapter"]["id"] == "cold-war-t9"
        sug = requests.get(f"{API}/suggestions", params={"device_id": dev["id"]}).json()
        assert all("Cold War" not in p["host"]["name"] for p in sug["pairs"])
        assert any(b["name"] == "Call of Duty®: Black Ops Cold War" and b["reason"] == REASON for b in sug["blocked"])
        ck = requests.get(f"{API}/checklist", params={"device_id": dev["id"]}).json()
        host = next(s for s in ck["steps"] if s["key"] == "host")
        assert host["label"] == "Buildable host available (2)", host
    finally:
        mdb.games.update_one({"device_id": dev["id"], "install_dir": CW_STEAM},
                             {"$set": {"hostable": False, "adapter_id": "cold-war-t9"}})


def test_supported_details_unchanged(dev):
    d = requests.get(f"{API}/games/details", params={"device_id": dev["id"], "install_dir": SKY}).json()
    assert d["buildable_host"] is True and d["adapter"]["id"] == "unity-mono-bepinex5"
    d = requests.get(f"{API}/games/details", params={"device_id": dev["id"], "install_dir": KF2}).json()
    assert d["buildable_host"] is True and d["adapter"]["id"] == "game-kf2"


# ---- compatibility report ----
def test_report_steam(dev):
    r = requests.get(f"{API}/games/cold-war/compatibility", params={"device_id": dev["id"], "install_dir": CW_STEAM})
    assert r.status_code == 200
    d = r.json()
    assert d["status_label"] == REASON and d["intended_host"] == "Call of Duty®: Black Ops Cold War"
    assert d["detected"] is True and d["community_tools_documented"] is True and d["melty_loader_supported"] is False
    i = d["installation"]
    assert i["store"] == "Steam" and i["reported_version"] is None and i["executable_version"] is None
    assert {s["id"] for s in d["sources"]} == {"atian-tools", "activision-policy"}
    txt = " ".join(d["limits"] + d["missing_prerequisites"])
    assert "37 and 38" in txt and "private-match" in txt


def test_report_registry_store_unknown(dev):
    d = requests.get(f"{API}/games/cold-war/compatibility", params={"device_id": dev["id"], "install_dir": CW_REG}).json()
    assert d["installation"]["store"] is None and d["installation"]["detection_source"] == "registry"
    assert d["installation"]["executable_exists"] is False


def test_report_steam_build_is_library_not_exe(dev):
    dev["s"].post(f"{API}/companion/games", json={"games": games_payload("build 13579")}, headers=dev["h"])
    i = requests.get(f"{API}/games/cold-war/compatibility", params={"device_id": dev["id"], "install_dir": CW_STEAM}).json()["installation"]
    assert i["reported_version"] == "build 13579" and i["executable_version"] is None


@pytest.mark.parametrize("did,path,code", [("nope", CW_STEAM, 404), (None, "/tmp/TEST_CW/missing", 404), (None, SKY, 400)])
def test_report_invalid(dev, did, path, code):
    r = requests.get(f"{API}/games/cold-war/compatibility", params={"device_id": did or dev["id"], "install_dir": path})
    assert r.status_code == code


# ---- manual version ----
def test_manual_version_persist_and_rescan(dev):
    r = requests.patch(f"{API}/games/cold-war/version", json={"device_id": dev["id"], "install_dir": CW_STEAM, "version": " 1.34.1.15931218 "})
    assert r.status_code == 200 and r.json()["installation"]["manual_version"] == "1.34.1.15931218"
    assert r.json()["status_label"] == REASON
    dev["s"].post(f"{API}/companion/games", json={"games": games_payload("build 2468")}, headers=dev["h"])
    d = requests.get(f"{API}/games/cold-war/compatibility", params={"device_id": dev["id"], "install_dir": CW_STEAM}).json()
    assert d["installation"]["manual_version"] == "1.34.1.15931218"
    assert d["installation"]["reported_version"] == "build 2468" and d["melty_loader_supported"] is False
    assert gmap(dev)[CW_STEAM]["hostable"] is False
    # other installation not affected
    other = requests.get(f"{API}/games/cold-war/compatibility", params={"device_id": dev["id"], "install_dir": CW_REG}).json()
    assert other["installation"]["manual_version"] is None


@pytest.mark.parametrize("payload,code", [
    ({"install_dir": CW_STEAM, "version": "x" * 81}, 422),
    ({"install_dir": CW_STEAM, "version": "1.0\n2"}, 422),
    ({"install_dir": CW_STEAM, "version": "1.0\x7f"}, 422),
    ({"install_dir": SKY, "version": "1.0"}, 400),
    ({"install_dir": "/tmp/TEST_CW/missing", "version": "1.0"}, 404),
])
def test_manual_version_invalid(dev, payload, code):
    assert requests.patch(f"{API}/games/cold-war/version", json={"device_id": dev["id"], **payload}).status_code == code


def test_manual_version_80_ok(dev):
    r = requests.patch(f"{API}/games/cold-war/version", json={"device_id": dev["id"], "install_dir": CW_REG, "version": "v" * 80})
    assert r.status_code == 200
    requests.patch(f"{API}/games/cold-war/version", json={"device_id": dev["id"], "install_dir": CW_REG, "version": ""})


# ---- read-only check ----
def test_check_old_companion(dev):
    beat(dev, "0.2.0")
    r = requests.post(f"{API}/games/cold-war/check", json={"device_id": dev["id"], "install_dir": CW_STEAM})
    assert r.status_code == 409 and "0.3.0" in r.json()["detail"]
    beat(dev)


def test_check_offline(dev):
    mdb.devices.update_one({"id": dev["id"]}, {"$set": {"last_seen": "2020-01-01T00:00:00+00:00"}})
    r = requests.post(f"{API}/games/cold-war/check", json={"device_id": dev["id"], "install_dir": CW_STEAM})
    assert r.status_code == 409 and "offline" in r.json()["detail"].lower()
    beat(dev)


def test_check_non_cold_war_rejected(dev):
    assert requests.post(f"{API}/games/cold-war/check", json={"device_id": dev["id"], "install_dir": SKY}).status_code == 400
    assert requests.post(f"{API}/games/cold-war/check", json={"device_id": dev["id"], "install_dir": "/nope"}).status_code == 404


def test_check_enqueue_claim_result(dev):
    beat(dev)
    r = requests.post(f"{API}/games/cold-war/check", json={"device_id": dev["id"], "install_dir": CW_STEAM})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["op"] == "inspect_game" and j["status"] == "queued"
    assert j["params"] == {"name": "Call of Duty®: Black Ops Cold War", "install_dir": CW_STEAM, "metadata_only": True}
    nxt = requests.get(f"{API}/companion/jobs/next", headers=dev["h"]).json()["job"]
    assert nxt["id"] == j["id"]
    res = {"install_dir": CW_STEAM, "exe": "BlackOpsColdWar.exe", "installation_exists": True, "executable_exists": True,
           "executable_version": "1.34.1.15931218", "inspection_note": None, "managed": ["evil.dll"], "hostable": True,
           "game_version": "HACK", "loader_installed": True}
    assert requests.post(f"{API}/companion/jobs/{j['id']}/result", json={"status": "done", "result": res}, headers=dev["h"]).status_code == 200
    g = mdb.games.find_one({"device_id": dev["id"], "install_dir": CW_STEAM})
    assert g["executable_version"] == "1.34.1.15931218" and g.get("managed") in (None, [])
    assert g["game_version"] != "HACK" and g["hostable"] is False and g.get("compatibility_checked_at")
    other = mdb.games.find_one({"device_id": dev["id"], "install_dir": CW_REG})
    assert other.get("executable_version") is None
    d = requests.get(f"{API}/games/cold-war/compatibility", params={"device_id": dev["id"], "install_dir": CW_STEAM}).json()
    assert d["installation"]["executable_version"] == "1.34.1.15931218" and d["melty_loader_supported"] is False
    # no artifacts / other jobs
    assert mdb.jobs.count_documents({"device_id": dev["id"], "op": {"$ne": "inspect_game"}}) == 0


def test_check_needs_approval_and_cancel(dev):
    ops = [o for o in requests.get(f"{API}/companion/ops").json() if o != "inspect_game"]
    mdb.devices.update_one({"id": dev["id"]}, {"$set": {"approved_ops": ops}})
    try:
        j = requests.post(f"{API}/games/cold-war/check", json={"device_id": dev["id"], "install_dir": CW_REG}).json()
        assert j["status"] == "needs_approval"
        requests.post(f"{API}/jobs/{j['id']}/cancel")
        assert requests.get(f"{API}/jobs/{j['id']}").json()["status"] == "cancelled"
    finally:
        mdb.devices.update_one({"id": dev["id"]}, {"$set": {"approved_ops": ops + ["inspect_game"]}})


def test_metadata_only_name_mismatch(dev):
    r = requests.post(f"{API}/devices/{dev['id']}/jobs", json={"op": "inspect_game", "params": {
        "name": "TEST_CW Skyhaven", "install_dir": CW_STEAM, "metadata_only": True}})
    assert r.status_code == 400


# ---- direct job blocking ----
CW_JOBS = [
    ("build_mod", {"host_name": "Call of Duty®: Black Ops Cold War", "toolchain": "ue4ss-lua"}),
    ("test_mod", {"host_name": "Black Ops Cold War", "toolchain": "bepinex5-csharp"}),
    ("build_mod", {"host_name": "TEST_CW Generic"}),
    ("install_package", {"manifest": {"host": {"game": "Some Name", "exe": "C:\\G\\BlackOpsColdWar.exe"}}}),
    ("launch_game", {"manifest": {"host": {"game": "x", "steam_appid": 1985810}}}),
    ("launch_game", {"manifest": {"host": {"game": "TEST_CW AppOnly"}}}),
    ("install_package", {"manifest": {"host": {"name": "COD Cold War"}}}),
]


@pytest.mark.parametrize("op,params", CW_JOBS)
def test_direct_jobs_blocked(dev, op, params):
    r = requests.post(f"{API}/devices/{dev['id']}/jobs", json={"op": op, "params": params})
    assert r.status_code == 400 and r.json()["detail"] == REASON


def test_restore_and_supported_jobs_allowed(dev):
    r = requests.post(f"{API}/devices/{dev['id']}/jobs", json={"op": "uninstall_package", "params": {"install_id": "TEST_CW"}})
    assert r.status_code == 200
    requests.post(f"{API}/jobs/{r.json()['id']}/cancel")
    r = requests.post(f"{API}/devices/{dev['id']}/jobs", json={"op": "launch_game", "params": {"manifest": {"host": {"game": "TEST_CW Skyhaven"}}}})
    assert r.status_code == 200
    requests.post(f"{API}/jobs/{r.json()['id']}/cancel")


def test_stale_queued_job_blocked_at_claim(dev):
    jid = "TEST_CW_stale_job"
    mdb.jobs.insert_one({"id": jid, "device_id": dev["id"], "op": "build_mod", "params": {"host_name": "Black Ops Cold War™"},
                         "status": "queued", "created_at": "2000-01-01T00:00:00+00:00", "artifacts": []})
    nxt = requests.get(f"{API}/companion/jobs/next", headers=dev["h"]).json()
    assert nxt["job"] is None
    j = mdb.jobs.find_one({"id": jid})
    assert j["status"] == "failed" and j["result"]["error"] == REASON


# ---- mods / releases ----
def counts():
    return mdb.ai_calls.count_documents({}), mdb.generations.count_documents({}), list(mdb.budget_days.find({}, {"_id": 0, "reserved": 1, "spent": 1}).sort("day", -1).limit(1))


@pytest.mark.parametrize("host,with_dev", [("Call of Duty®: Black Ops Cold War", True), ("Black Ops Cold War", False),
                                           ("TEST_CW Generic", True), ("TEST_CW AppOnly", True)])
def test_create_mod_blocked_no_spend(dev, host, with_dev):
    before = counts()
    r = requests.post(f"{API}/mods", json={"host": {"name": host}, "description": "TEST_CW should be blocked",
                                          "device_id": dev["id"] if with_dev else None})
    assert r.status_code == 400 and REASON in r.json()["detail"]
    assert counts() == before
    assert mdb.mods.count_documents({"description": "TEST_CW should be blocked"}) == 0


@pytest.fixture(scope="module")
def legacy(dev):
    pid, rid = "TEST_CW_mod", "TEST_CW_rel"
    mdb.mods.insert_one({"id": pid, "title": "TEST_CW Legacy", "slug": "test-cw-legacy", "host": {"name": "Call of Duty®: Black Ops Cold War", "role": "host"},
                         "secondary": [], "aspects": [], "description": "legacy", "device_id": dev["id"], "adapter_id": "unity-mono-bepinex5",
                         "toolchain": "bepinex5-csharp", "files": [{"path": "Plugin.cs", "content": "//"}], "spec_md": "",
                         "build_status": "built", "last_build_job_id": "TEST_CW_build", "dirty": False,
                         "created_at": "2001-01-01T00:00:00+00:00", "updated_at": "2001-01-01T00:00:00+00:00"})
    mdb.releases.insert_one({"id": rid, "project_id": pid, "version": "1.0.0", "published": False, "title": "TEST_CW Legacy",
                             "host": "Call of Duty®: Black Ops Cold War", "secondary": [], "compat": {}, "spec_md": "",
                             "manifest": {"name": "test-cw-legacy", "host": {"game": "Call of Duty®: Black Ops Cold War", "supported_versions": []},
                                          "files": [], "secondary": []}, "created_at": "2001-01-01T00:00:00+00:00"})
    dev["mods"].append(pid)
    dev["releases"].append(rid)
    return pid, rid


def test_legacy_mod_detail_reason(legacy):
    d = requests.get(f"{API}/mods/{legacy[0]}").json()
    assert d["hosting_blocked_reason"] == REASON


@pytest.mark.parametrize("method,path,body", [
    ("post", "/mods/{pid}/chat", {"message": "TEST_CW hi"}),
    ("post", "/mods/{pid}/build", None),
    ("get", "/mods/{pid}/export", None),
    ("post", "/mods/{pid}/releases", {"version": "1.0.1"}),
    ("post", "/releases/{rid}/publish", {"publish": True}),
    ("post", "/releases/{rid}/install", {"device_id": "DEV"}),
])
def test_legacy_actions_blocked(dev, legacy, method, path, body):
    before = counts()
    url = API + path.format(pid=legacy[0], rid=legacy[1])
    if body and body.get("device_id") == "DEV":
        body = {"device_id": dev["id"]}
    r = getattr(requests, method)(url, json=body)
    assert r.status_code == 400 and r.json()["detail"] == REASON, (path, r.status_code, r.text[:200])
    assert counts() == before
    assert mdb.jobs.count_documents({"device_id": dev["id"], "status": {"$in": ["queued", "needs_approval"]}}) == 0


def test_legacy_release_reason_and_unpublish(legacy):
    d = requests.get(f"{API}/releases/{legacy[1]}").json()
    assert d["hosting_blocked_reason"] == REASON
    assert requests.post(f"{API}/releases/{legacy[1]}/publish", json={"publish": False}).status_code == 200


def test_supported_create_mod_validation_still_works():
    r = requests.post(f"{API}/mods", json={"host": {"name": "TEST_CW Skyhaven"}, "description": "  "})
    assert r.status_code == 400 and "required" in r.json()["detail"]
