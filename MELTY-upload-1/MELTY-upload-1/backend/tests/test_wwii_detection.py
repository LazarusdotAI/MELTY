# Call of Duty: WWII (S2) detection + campaign status + unverified-host guard regressions.
# Companion tests use temp dirs only (no binaries executed, no network). API tests use an isolated TEST_WWII device.
import os
import sys
import importlib
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
WWII_REASON = "Not supported by MELTY — WWII campaign loader compatibility unverified"
CW_REASON = "Not supported by MELTY — host compatibility unverified"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------- shared alias parity (backend adapters vs companion) ----------------
@pytest.fixture()
def comp(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
    sys.modules.pop("melty_companion", None)
    mc = importlib.import_module("melty_companion")
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"forbidden call {a[:1]}"))
    for name in ("download_url", "upload", "http", "bepinex_zip", "install_zip", "dotnet_version", "executable_version"):
        monkeypatch.setattr(mc, name, boom)
    monkeypatch.setattr(mc.subprocess, "Popen", boom)
    monkeypatch.setattr(mc.subprocess, "run", boom)
    yield mc
    sys.modules.pop("melty_companion", None)


YES = [{"name": "Call of Duty®: WWII"}, {"name": "Call of Duty: WWII"}, {"name": "COD WWII"}, {"name": "Call of Duty: WWII - Multiplayer"},
       {"name": "Call of Duty: WWII – Campaign"}, {"name": "Call of Duty WWII Single Player"}, {"name": "x", "steam_appid": 476600},
       {"name": "x", "steam_appid": "476600"}, {"name": "x", "exe": "C:\\G\\S2_SP64_SHIP.EXE"}, {"name": "x", "exe": "s2_mp64_ship.exe"},
       {"name": "x", "adapter_id": "cod-wwii-s2"}]
NO = [{"name": "Brothers in Arms WWII"}, {"name": "WWII Tanks"}, {"name": "Medal of Honor: WWII Heroes"}, {"name": "x", "exe": "DLogUploader.exe"},
      {"name": "Call of Duty: Black Ops Cold War"}, {"name": "Call of Duty: Modern Warfare"}, {"name": "Call of Duty: WWII Fan Remake 2"}]


def test_alias_parity(comp):
    import adapters
    for g in YES:
        assert adapters.is_wwii(g) and comp.is_wwii(g), g
    for g in NO:
        assert not adapters.is_wwii(g) and not comp.is_wwii(g), g
    assert comp.VERSION == "0.5.0"
    assert adapters.is_cold_war({"name": "Call of Duty®: Black Ops Cold War"}) and not adapters.is_cold_war({"name": "Call of Duty: WWII"})


def snapshot(d):
    return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in Path(d).rglob("*"))


def mk(d, *files, dirs=()):
    d.mkdir(parents=True, exist_ok=True)
    for f in files:
        (d / f).write_bytes(b"MZ-fixture")
    for x in dirs:
        (d / x).mkdir()
    return d


def steam_lib(tmp_path, monkeypatch, comp, name, files, appid="476600", dirs=()):
    root = tmp_path / "steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps" / f"appmanifest_{appid}.acf").write_text(
        f'"AppState"\n{{\n "appid" "{appid}"\n "name" "{name}"\n "installdir" "WWII"\n "buildid" "22081346"\n}}\n')
    d = mk(root / "steamapps" / "common" / "WWII", *files, dirs=dirs)
    monkeypatch.setattr(comp, "steam_roots", lambda: [str(root)])
    monkeypatch.setattr(comp, "registry_games", lambda: [])
    monkeypatch.setattr(comp, "launcher_folder_games", lambda: [])
    return d


# ---------------- companion detect_games ----------------
def test_detect_selects_campaign_not_helper(comp, tmp_path, monkeypatch):
    d = steam_lib(tmp_path, monkeypatch, comp, "Call of Duty: WWII", ["DLogUploader.exe", "s2_mp64_ship.exe", "s2_sp64_ship.exe"])
    before = snapshot(d)
    g = comp.detect_games({}, {})[0]["games"][0]
    assert g["exe"] == "s2_sp64_ship.exe" and g["campaign_exe"] == "s2_sp64_ship.exe" and g["multiplayer_exe"] == "s2_mp64_ship.exe"
    assert g["campaign_executable_found"] is True and g["wwii_mode"] == "campaign" and g["engine"] == "s2"
    assert g["adapter_id"] == "cod-wwii-s2" and g["loader_installed"] is False and g["game_version"] == "build 22081346"
    assert snapshot(d) == before


def test_detect_mp_only_no_fallback(comp, tmp_path, monkeypatch):
    steam_lib(tmp_path, monkeypatch, comp, "Call of Duty: WWII", ["DLogUploader.exe", "s2_mp64_ship.exe"])
    g = comp.detect_games({}, {})[0]["games"][0]
    assert g["exe"] is None and g["campaign_exe"] is None and g["multiplayer_exe"] == "s2_mp64_ship.exe"
    assert g["campaign_executable_found"] is False


def test_detect_named_multiplayer(comp, tmp_path, monkeypatch):
    steam_lib(tmp_path, monkeypatch, comp, "Call of Duty: WWII - Multiplayer", ["s2_mp64_ship.exe", "DLogUploader.exe"])
    g = comp.detect_games({}, {})[0]["games"][0]
    assert g["exe"] == "s2_mp64_ship.exe" and g["wwii_mode"] == "multiplayer" and g["campaign_executable_found"] is False


def test_detect_helper_only_named(comp, tmp_path, monkeypatch):
    steam_lib(tmp_path, monkeypatch, comp, "Call of Duty: WWII", ["DLogUploader.exe"])
    g = comp.detect_games({}, {})[0]["games"][0]
    assert g["exe"] is None and g["campaign_executable_found"] is False and g["multiplayer_exe"] is None


def test_detect_generic_helper_only(comp, tmp_path, monkeypatch):
    steam_lib(tmp_path, monkeypatch, comp, "TEST Some Game", ["DLogUploader.exe"], appid="999")
    g = comp.detect_games({}, {})[0]["games"][0]
    assert g["exe"] is None and g.get("adapter_id") != "cod-wwii-s2" and not comp.is_wwii(g)


def test_metadata_missing_unreadable_case_dirs(comp, tmp_path, monkeypatch):
    assert comp.wwii_metadata({"install_dir": str(tmp_path / "nope")})["campaign_executable_found"] is False
    d = mk(tmp_path / "case", "S2_SP64_SHIP.EXE")
    m = comp.wwii_metadata({"install_dir": str(d)})
    assert m["campaign_exe"] == "S2_SP64_SHIP.EXE" and m["campaign_executable_found"] is True
    d2 = mk(tmp_path / "dirs", dirs=("s2_sp64_ship.exe", "s2_mp64_ship.exe"))
    m = comp.wwii_metadata({"install_dir": str(d2)})
    assert m["campaign_exe"] is None and m["multiplayer_exe"] is None and m["campaign_executable_found"] is False
    assert comp.identify(str(d2))["exe"] is None or comp.identify(str(d2)).get("adapter_id") != "cod-wwii-s2"
    real = os.listdir
    monkeypatch.setattr(comp.os, "listdir", lambda p: (_ for _ in ()).throw(PermissionError("denied")) if "locked" in str(p) else real(p))
    m = comp.wwii_metadata({"install_dir": str(tmp_path / "locked")})
    assert m["campaign_executable_found"] is None and m["exe"] is None


def test_identify_unknown_folder_with_s2(comp, tmp_path):
    d = mk(tmp_path / "Random Folder", "DLogUploader.exe", "s2_sp64_ship.exe")
    i = comp.identify(str(d))
    assert i["adapter_id"] == "cod-wwii-s2" and i["engine"] == "s2" and i["exe"] == "s2_sp64_ship.exe"


def test_require_supported_host_before_side_effects(comp, tmp_path):
    d = mk(tmp_path / "WWII", "s2_sp64_ship.exe")
    g = {"name": "Call of Duty: WWII", "install_dir": str(d), "exe": "s2_sp64_ship.exe", "engine": "s2", "source": "steam"}
    comp.CFG["games"] = [g]
    before = snapshot(d)
    calls = [(comp.build_mod, {"host_name": g["name"], "slug": "x", "files": []}),
             (comp.test_mod, {"host_name": g["name"], "slug": "x", "files": []}),
             (comp.install_package, {"manifest": {"host": {"game": g["name"]}, "files": []}})]
    for fn, p in calls:
        with pytest.raises(RuntimeError, match="WWII campaign loader compatibility unverified"):
            fn(p, {"id": "TEST_WWII"})
    with pytest.raises(RuntimeError, match="WWII"):
        comp.launch(g, {})
    assert snapshot(d) == before and not comp.PROCS


# ---------------- API (isolated TEST_WWII device) ----------------
P = "/tmp/TEST_WWII"
SP, MP, STALE, UNK, HELPER, BIA, SKY, CW = (f"{P}/steam/WWII", f"{P}/reg/WWII-MP", f"{P}/stale/WWII", f"{P}/folder/Unknown",
                                            f"{P}/folder/Helper", f"{P}/folder/BIA", f"{P}/folder/Skyhaven", f"{P}/steam/BOCW")


def payload():
    return [
        {"name": "Call of Duty®: WWII", "source": "steam", "steam_appid": "476600", "install_dir": SP, "exe": "s2_sp64_ship.exe",
         "engine": "s2", "game_version": "build 22081346", "campaign_exe": "s2_sp64_ship.exe", "multiplayer_exe": "s2_mp64_ship.exe",
         "campaign_executable_found": True, "wwii_mode": "campaign", "evil_field": "x"},
        {"name": "Call of Duty: WWII - Multiplayer", "source": "steam", "install_dir": MP, "exe": "s2_mp64_ship.exe", "engine": "s2",
         "multiplayer_exe": "s2_mp64_ship.exe", "campaign_exe": None, "campaign_executable_found": False, "wwii_mode": "multiplayer"},
        {"name": "Call of Duty: WWII", "source": "steam", "install_dir": STALE, "exe": "DLogUploader.exe", "engine": "unity-mono"},
        {"name": "TEST_WWII Unknown", "source": "folder", "install_dir": UNK, "exe": "s2_sp64_ship.exe", "engine": "s2"},
        {"name": "TEST_WWII Dlog Game", "source": "folder", "install_dir": HELPER, "exe": "DLogUploader.exe", "engine": "unity-mono",
         "managed_dir": HELPER + "/x"},
        {"name": "TEST_WWII Brothers WWII", "source": "folder", "install_dir": BIA, "exe": "BIA.exe", "engine": "unity-mono"},
        {"name": "TEST_WWII Skyhaven", "source": "folder", "install_dir": SKY, "exe": "Skyhaven.exe", "engine": "unity-mono"},
        {"name": "Call of Duty®: Black Ops Cold War", "source": "steam", "steam_appid": "1985810", "install_dir": CW,
         "exe": "BlackOpsColdWar.exe", "engine": "unknown"},
    ]


@pytest.fixture(scope="module")
def dev():
    s = requests.Session()
    code = s.post(f"{API}/devices/pairing-code").json()["code"]
    d = s.post(f"{API}/companion/pair", json={"code": code, "hostname": "TEST_WWII-host", "os": "Windows-10-TEST",
                                              "companion_version": "0.3.1"}).json()
    assert d["device_id"] != ATLAS
    h = {"X-Device-Token": d["token"]}
    s.post(f"{API}/companion/heartbeat", json={"status": {"version": "0.3.1"}}, headers=h)
    assert s.post(f"{API}/companion/games", json={"games": payload()}, headers=h).status_code == 200
    info = {"id": d["device_id"], "h": h, "code": code, "mods": ["TEST_WWII_mod"], "rel": "TEST_WWII_rel"}
    yield info
    did = d["device_id"]
    for c in ("games", "jobs", "installs", "pitches"):
        mdb[c].delete_many({"device_id": did})
    mdb.mods.delete_many({"$or": [{"device_id": did}, {"id": {"$in": info["mods"]}}, {"description": {"$regex": "^TEST_WWII"}}]})
    mdb.releases.delete_many({"project_id": {"$in": info["mods"]}})
    for c in ("versions", "messages", "generations"):
        mdb[c].delete_many({"project_id": {"$in": info["mods"]}})
    mdb.devices.delete_one({"id": did})
    mdb.pairing.delete_one({"code": info["code"]})


def gmap(dev):
    return {g["install_dir"]: g for g in requests.get(f"{API}/devices/{dev['id']}/games").json()}


def test_store_identity_and_metadata_whitelist(dev):
    g = gmap(dev)
    for p in (SP, MP, STALE, UNK):
        assert g[p]["adapter_id"] == "cod-wwii-s2" and g[p]["engine"] == "s2" and g[p]["hostable"] is False, p
        assert g[p]["host_reason"] == WWII_REASON and g[p]["toolchain"] is None and g[p]["adapter_status"] == "unverified"
    assert g[SP]["campaign_exe"] == "s2_sp64_ship.exe" and g[SP]["multiplayer_exe"] == "s2_mp64_ship.exe"
    assert g[SP]["campaign_executable_found"] is True and g[SP]["wwii_mode"] == "campaign" and "evil_field" not in g[SP]
    assert g[MP]["exe"] == "s2_mp64_ship.exe" and g[MP]["campaign_executable_found"] is False
    assert g[STALE]["exe"] is None and g[STALE].get("campaign_executable_found") is None and g[STALE].get("campaign_exe") is None
    for p in (HELPER, BIA, SKY):
        assert g[p]["adapter_id"] != "cod-wwii-s2" and g[p]["hostable"] is True, p
    assert g[CW]["adapter_id"] == "cold-war-t9" and g[CW]["host_reason"] == CW_REASON


def test_stale_bogus_unity_overridden(dev):
    mdb.games.update_one({"device_id": dev["id"], "install_dir": STALE},
                         {"$set": {"hostable": True, "toolchain": "bepinex5-csharp", "adapter_id": "unity-mono-bepinex5",
                                   "engine": "unity-mono", "exe": "DLogUploader.exe", "host_reason": None, "loader_installed": True}})
    g = gmap(dev)[STALE]
    assert (g["engine"], g["adapter_id"], g["adapter_status"], g["hostable"], g["toolchain"], g["exe"]) == \
        ("s2", "cod-wwii-s2", "unverified", False, None, None)
    assert g["loader_installed"] is False and g.get("campaign_executable_found") is None
    d = requests.get(f"{API}/games/details", params={"device_id": dev["id"], "install_dir": STALE}).json()
    assert d["buildable_host"] is False and d["adapter"]["id"] == "cod-wwii-s2" and d["game"]["host_reason"] == WWII_REASON
    assert "online game" not in d["game"]["host_reason"].lower()


def test_suggestions_and_checklist(dev):
    sug = requests.get(f"{API}/suggestions", params={"device_id": dev["id"]}).json()
    for p in sug["pairs"]:
        for side in ("host", "secondary"):
            assert p[side]["name"] not in ("Call of Duty®: WWII", "Call of Duty: WWII", "Call of Duty: WWII - Multiplayer",
                                           "TEST_WWII Unknown", "Call of Duty®: Black Ops Cold War"), p
    bl = {b["name"]: b["reason"] for b in sug["blocked"]}
    assert bl["Call of Duty®: WWII"] == WWII_REASON and bl["Call of Duty: WWII - Multiplayer"] == WWII_REASON
    ck = requests.get(f"{API}/checklist", params={"device_id": dev["id"]}).json()
    host = next(s for s in ck["steps"] if s["key"] == "host")
    assert host["label"] == "Buildable host available (3)", host


def counts():
    return mdb.ai_calls.count_documents({}), mdb.generations.count_documents({})


@pytest.mark.parametrize("host,with_dev", [("Call of Duty®: WWII", True), ("COD WWII", False), ("Call of Duty: WWII - Multiplayer", True),
                                           ("TEST_WWII Unknown", True), ("Call of Duty WWII Campaign", False)])
def test_create_blocked_no_spend(dev, host, with_dev):
    before = counts()
    r = requests.post(f"{API}/mods", json={"host": {"name": host}, "description": "TEST_WWII blocked",
                                          "device_id": dev["id"] if with_dev else None})
    assert r.status_code == 400 and r.json()["detail"] == WWII_REASON
    assert counts() == before and mdb.mods.count_documents({"description": "TEST_WWII blocked"}) == 0


@pytest.mark.parametrize("op,params", [
    ("build_mod", {"host_name": "Call of Duty®: WWII", "toolchain": "bepinex5-csharp"}),
    ("test_mod", {"host_name": "TEST_WWII Unknown"}),
    ("install_package", {"manifest": {"host": {"game": "y", "exe": "C:\\G\\s2_sp64_ship.exe"}}}),
    ("launch_game", {"manifest": {"host": {"game": "y", "steam_appid": 476600}}}),
    ("launch_game", {"manifest": {"host": {"game": "Call of Duty: WWII - Multiplayer"}}}),
])
def test_direct_jobs_blocked(dev, op, params):
    r = requests.post(f"{API}/devices/{dev['id']}/jobs", json={"op": op, "params": params})
    assert r.status_code == 400 and r.json()["detail"] == WWII_REASON


def test_supported_and_restore_jobs_allowed(dev):
    for op, params in (("uninstall_package", {"install_id": "TEST_WWII"}), ("launch_game", {"manifest": {"host": {"game": "TEST_WWII Skyhaven"}}})):
        r = requests.post(f"{API}/devices/{dev['id']}/jobs", json={"op": op, "params": params})
        assert r.status_code == 200
        requests.post(f"{API}/jobs/{r.json()['id']}/cancel")


def test_stale_queued_claim_blocked(dev):
    mdb.jobs.insert_one({"id": "TEST_WWII_job", "device_id": dev["id"], "op": "build_mod", "params": {"host_name": "TEST_WWII Unknown"},
                         "status": "queued", "created_at": "2000-01-01T00:00:00+00:00", "artifacts": []})
    assert requests.get(f"{API}/companion/jobs/next", headers=dev["h"]).json()["job"] is None
    j = mdb.jobs.find_one({"id": "TEST_WWII_job"})
    assert j["status"] == "failed" and j["result"]["error"] == WWII_REASON


@pytest.fixture(scope="module")
def legacy(dev):
    pid, rid = "TEST_WWII_mod", "TEST_WWII_rel"
    host = "TEST_WWII Unknown"  # identity only via stored record alias (exe), not name
    mdb.mods.insert_one({"id": pid, "title": "TEST_WWII Legacy", "slug": "test-wwii", "host": {"name": host, "role": "host"},
                         "secondary": [], "aspects": [], "description": "legacy", "device_id": dev["id"], "adapter_id": "unity-mono-bepinex5",
                         "toolchain": "bepinex5-csharp", "files": [{"path": "Plugin.cs", "content": "//"}], "spec_md": "",
                         "build_status": "built", "dirty": False, "created_at": "2001-01-01T00:00:00+00:00",
                         "updated_at": "2001-01-01T00:00:00+00:00"})
    mdb.releases.insert_one({"id": rid, "project_id": pid, "version": "1.0.0", "published": False, "title": "TEST_WWII", "host": host,
                             "secondary": [], "compat": {}, "spec_md": "", "created_at": "2001-01-01T00:00:00+00:00",
                             "manifest": {"name": "test-wwii", "host": {"game": "Call of Duty: WWII", "supported_versions": []},
                                          "files": [], "secondary": []}})
    return pid, rid


def test_legacy_detail_reason(legacy):
    assert requests.get(f"{API}/mods/{legacy[0]}").json()["hosting_blocked_reason"] == WWII_REASON
    assert requests.get(f"{API}/releases/{legacy[1]}").json()["hosting_blocked_reason"] == WWII_REASON


@pytest.mark.parametrize("method,path,body", [
    ("post", "/mods/{pid}/chat", {"message": "TEST_WWII hi"}), ("post", "/mods/{pid}/build", None),
    ("get", "/mods/{pid}/export", None), ("post", "/mods/{pid}/releases", {"version": "1.0.1"}),
    ("post", "/releases/{rid}/publish", {"publish": True}), ("post", "/releases/{rid}/install", {"device_id": "DEV"}),
    ("post", "/sfx/generate", {"prompt": "TEST_WWII boom", "duration": 1, "project_id": "PID"}),
])
def test_legacy_actions_blocked(dev, legacy, method, path, body):
    before = counts()
    if body and body.get("device_id") == "DEV":
        body = {"device_id": dev["id"]}
    if body and body.get("project_id") == "PID":
        body = {**body, "project_id": legacy[0]}
    r = getattr(requests, method)(API + path.format(pid=legacy[0], rid=legacy[1]), json=body)
    assert r.status_code == 400 and r.json()["detail"] == WWII_REASON, (path, r.status_code, r.text[:200])
    assert counts() == before
    assert mdb.jobs.count_documents({"device_id": dev["id"], "status": {"$in": ["queued", "needs_approval"]}}) == 0


def test_companion_version_endpoint():
    assert requests.get(f"{API}/companion-app/version").json()["version"] == "0.5.0"


# Secondary guard (iteration8): supported fixture host + unverified secondary must 400 before any side effects
@pytest.mark.parametrize("sec,reason", [("Call of Duty®: WWII", "WWII"), ("Call of Duty: WWII - Multiplayer", "WWII"),
                                        ("Call of Duty®: Black Ops Cold War", "CW"), ("TEST_WWII Unknown", "WWII")])
def test_create_secondary_blocked_no_side_effects(dev, sec, reason):
    before = (counts(), mdb.mods.count_documents({}), mdb.jobs.count_documents({"device_id": dev["id"]}))
    r = requests.post(f"{API}/mods", json={"host": {"name": "TEST_WWII Skyhaven"}, "secondary": [{"name": sec}],
                                          "description": "TEST_WWII secondary blocked", "device_id": dev["id"]})
    assert r.status_code == 400 and r.json()["detail"] == (WWII_REASON if reason == "WWII" else CW_REASON), r.text[:200]
    assert (counts(), mdb.mods.count_documents({}), mdb.jobs.count_documents({"device_id": dev["id"]})) == before
    assert mdb.mods.count_documents({"description": "TEST_WWII secondary blocked"}) == 0
