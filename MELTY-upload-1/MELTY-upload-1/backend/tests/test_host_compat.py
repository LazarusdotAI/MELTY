"""Host-compatibility regression tests: Cyberpunk 2077 (REDengine 4) and other engines must be judged by adapters, not name lists."""
import io
import os
import sys
import zipfile
import importlib
from pathlib import Path
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parents[1] / "frontend" / ".env")
load_dotenv(HERE.parent / ".env")
sys.path.insert(0, str(HERE.parent))
API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
import adapters  # noqa: E402

ROOT = Path("/tmp/TEST_HC")
SEED = {a["id"]: a for a in adapters.SEED}


def cyberpunk(base, tools=()):
    d = Path(base)
    (d / "bin" / "x64").mkdir(parents=True, exist_ok=True)
    (d / "archive" / "pc" / "content").mkdir(parents=True, exist_ok=True)
    (d / "bin" / "x64" / "Cyberpunk2077.exe").write_bytes(b"MZ")
    (d / "bin" / "x64" / "REDprelauncher.exe").write_bytes(b"MZ")
    markers = {"cet": "bin/x64/plugins/cyber_engine_tweaks.asi", "redmod": "tools/redmod/bin/redMod.exe", "red4ext": "red4ext/RED4ext.dll"}
    for t in tools:
        p = d / markers[t]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return str(d)


@pytest.fixture(scope="module")
def mc():
    os.environ["APPDATA"] = str(ROOT / "appdata")
    sys.path.insert(0, str(HERE.parent / "companion"))
    sys.modules.pop("melty_companion", None)
    return importlib.import_module("melty_companion")


@pytest.mark.parametrize("store", ["Steam/steamapps/common/Cyberpunk 2077", "GOG Games/Cyberpunk 2077", "Epic Games/Cyberpunk2077"])
def test_cyberpunk_identified_from_every_store(mc, store):
    d = cyberpunk(ROOT / store)
    info = mc.identify(d)
    assert info["engine"] == "redengine4"
    assert info["exe"].replace("\\", "/") == "bin/x64/Cyberpunk2077.exe"
    assert info["frameworks"] == []


def test_tool_detection(mc):
    d = cyberpunk(ROOT / "tools/Cyberpunk 2077", tools=("cet", "red4ext"))
    assert mc.identify(d)["frameworks"] == ["cet", "red4ext"]


def red(**g):
    return {"name": "Cyberpunk 2077", "engine": "redengine4", **g}


def test_cyberpunk_host_statuses():
    a = SEED["redengine4"]
    ready = adapters.host_info(red(frameworks=["cet"]), a)
    assert ready["hostable"] and ready["mod_status"] == "READY TO MOD" and ready["toolchain"] == "cet-lua"
    setup = adapters.host_info(red(frameworks=[]), a)
    assert setup["hostable"] and setup["mod_status"] == "SETUP REQUIRED"
    assert "can host mods" in setup["host_reason"] and "Cyber Engine Tweaks" in setup["host_reason"]
    assert "cannot be a host" not in setup["host_reason"].lower()


def test_one_unready_feature_does_not_block_host():
    hi = adapters.host_info(red(frameworks=["cet"]), SEED["redengine4"])
    caps = {c["feature"]: c["ready"] for c in hi["capabilities"]}
    assert caps["Gameplay scripts (Lua)"] and not caps["New items, meshes & textures"]
    assert hi["mod_status"] == "READY TO MOD"


def test_missing_engine_metadata_is_not_unsupported():
    fallback = {"id": None, "status": "unidentified", "hostable": False}
    hi = adapters.host_info({"name": "Mystery Game", "engine": "unknown"}, fallback)
    assert hi["mod_status"] == "SETUP REQUIRED"


@pytest.mark.parametrize("aid,game,status", [
    ("unreal", {"name": "S.T.A.L.K.E.R. 2- Heart of Chornobyl", "engine": "unreal"}, "READY TO MOD"),
    ("unreal", {"name": "Ready or Not", "engine": "unreal"}, "READY TO MOD"),
    ("game-kf2", {"name": "Killing Floor 2", "engine": "unreal3", "sdk_installed": False}, "SETUP REQUIRED"),
    ("unity-il2cpp", {"name": "Some IL2CPP game", "engine": "unity-il2cpp"}, "LIMITED SUPPORT"),
    ("blocked-anticheat", {"name": "Valorant", "engine": "iw"}, "UNSUPPORTED"),
])
def test_other_engines(aid, game, status):
    assert adapters.host_info(game, SEED[aid])["mod_status"] == status


def test_cet_package_layout_and_missing_cet_error(mc, monkeypatch):
    got = {}
    monkeypatch.setattr(mc, "upload", lambda jid, name, data: got.update(name=name, data=data))
    r, _ = mc.build_cet({"slug": "TacticalGun", "files": [{"path": "init.lua", "content": "-- x"}, {"path": "lib/aim.lua", "content": "-- y"}]}, {"id": "j"}, {})
    assert r["ok"] and sorted(zipfile.ZipFile(io.BytesIO(got["data"])).namelist()) == ["TacticalGun/init.lua", "TacticalGun/lib/aim.lua"]
    bad, _ = mc.build_cet({"slug": "X", "files": [{"path": "main.lua", "content": ""}]}, {"id": "j"}, {})
    assert not bad["ok"]
    with pytest.raises(RuntimeError, match="Cyber Engine Tweaks"):
        mc.test_cet({"slug": "X"}, {"id": "j"}, {"install_dir": cyberpunk(ROOT / "nocet")})


def test_setup_tools_installs_verifies_and_rolls_back(mc, monkeypatch):
    d = cyberpunk(ROOT / "setup/Cyberpunk 2077")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("bin/x64/plugins/cyber_engine_tweaks.asi", b"cet")
        z.writestr("bin/x64/version.dll", b"v")
    monkeypatch.setattr(mc, "github_zip", lambda repo: ("v9.9", "cet.zip", buf.getvalue()))
    tool = {"key": "cet", "name": "Cyber Engine Tweaks", "repo": "maximegmd/CyberEngineTweaks", "marker": "bin/x64/plugins/cyber_engine_tweaks.asi"}
    r, _ = mc.setup_tools({"install_dir": d, "tools": [tool]}, None)
    assert r["frameworks"] == ["cet"] and r["installed"][0]["version"] == "v9.9"
    mc.restore_journal(r["installed"][0]["install_id"])
    assert not os.path.exists(os.path.join(d, "bin/x64/version.dll")) and mc.frameworks_in(d, mc.RED_MARKERS) == []
    monkeypatch.setattr(mc, "github_zip", lambda repo: ("v1", "bad.zip", b"PK\x05\x06" + b"\0" * 18))
    with pytest.raises(RuntimeError, match="main file"):
        mc.setup_tools({"install_dir": d, "tools": [tool]}, None)


def test_api_store_games_rescan_and_tool_update(mc):
    import shutil
    shutil.rmtree(ROOT / "api", ignore_errors=True)
    code = requests.post(f"{API}/devices/pairing-code").json()["code"]
    h = {"User-Agent": "MeltyCompanion"}
    dev = requests.post(f"{API}/companion/pair", json={"code": code, "hostname": "TEST_HC_PC", "os": "t", "companion_version": "0.5.0"}, headers=h).json()
    h["X-Device-Token"] = dev["token"]
    try:
        games = []
        for src, sub in (("steam", "s"), ("gog", "g"), ("epic", "e")):
            d = cyberpunk(ROOT / "api" / sub / "Cyberpunk 2077")
            games.append({"name": "Cyberpunk 2077", "source": src, "install_dir": d, **mc.identify(d)})
        stalker = {"name": "S.T.A.L.K.E.R. 2- Heart of Chornobyl", "source": "folder", "install_dir": str(ROOT / "api/stalker"), "engine": "unreal"}
        requests.post(f"{API}/companion/games", json={"games": games + [stalker]}, headers=h).raise_for_status()
        recs = {g["install_dir"]: g for g in requests.get(f"{API}/devices/{dev['device_id']}/games").json()}
        for g in games:
            r = recs[g["install_dir"]]
            assert r["hostable"] and r["mod_status"] == "SETUP REQUIRED" and r["toolchain"] == "cet-lua", r
        assert recs[stalker["install_dir"]]["hostable"]
        # tools installed later -> recheck flips to READY TO MOD without a full rescan
        d0 = games[0]["install_dir"]
        cyberpunk(d0, tools=("cet",))
        j = requests.post(f"{API}/games/tools", json={"device_id": dev["device_id"], "install_dir": d0, "tools": []}).json()
        assert j["op"] == "detect_tools" and j["status"] == "queued"
        job = requests.get(f"{API}/companion/jobs/next", headers=h).json()["job"]
        res, _ = mc.detect_tools(job["params"], job)
        requests.post(f"{API}/companion/jobs/{job['id']}/result", json={"status": "done", "result": res}, headers=h)
        g = requests.get(f"{API}/games/details", params={"device_id": dev["device_id"], "install_dir": d0}).json()["game"]
        assert g["mod_status"] == "READY TO MOD"
        # setup always asks permission
        s = requests.post(f"{API}/games/tools", json={"device_id": dev["device_id"], "install_dir": d0, "tools": ["archivexl"]}).json()
        assert s["status"] == "needs_approval" and [t["key"] for t in s["params"]["tools"]] == ["red4ext", "archivexl"]
        assert requests.post(f"{API}/games/tools", json={"device_id": dev["device_id"], "install_dir": d0, "tools": ["redmod"]}).status_code == 400
        # rescan keeps working after detection refresh; manual engine for an unknown game
        m = requests.post(f"{API}/games/manual", json={"device_id": dev["device_id"], "install_dir": str(ROOT / "api/odd"), "engine": "redengine4", "name": "Odd Game"}).json()
        assert m["hostable"] and m["manual_engine"] == "redengine4"
    finally:
        mdb.devices.delete_one({"id": dev["device_id"]})
        for c in ("games", "jobs"):
            mdb[c].delete_many({"device_id": dev["device_id"]})


def test_trainer_flow_cyberpunk(mc):
    import json as _json
    import shutil
    shutil.rmtree(ROOT / "tr", ignore_errors=True)
    code = requests.post(f"{API}/devices/pairing-code").json()["code"]
    h = {"User-Agent": "MeltyCompanion"}
    dev = requests.post(f"{API}/companion/pair", json={"code": code, "hostname": "TEST_TR_PC", "os": "t", "companion_version": "0.5.0"}, headers=h).json()
    h["X-Device-Token"] = dev["token"]
    did = dev["device_id"]
    mc.CFG.update(server=API[:-4], token=dev["token"])

    def drain():
        job = requests.get(f"{API}/companion/jobs/next", headers=h).json()["job"]
        res, _ = mc.HANDLERS[job["op"]](job["params"], job)
        requests.post(f"{API}/companion/jobs/{job['id']}/result", json={"status": "done", "result": res}, headers=h)
        return job, res
    try:
        d = cyberpunk(ROOT / "tr" / "Cyberpunk 2077", tools=("cet",))
        requests.post(f"{API}/companion/games", json={"games": [{"name": "Cyberpunk 2077", "source": "gog", "install_dir": d, **mc.identify(d)}]}, headers=h).raise_for_status()
        q = {"install_dir": d, "device_id": did}
        t = requests.get(f"{API}/trainer/game", params=q).json()
        st = {f["key"]: f["status"] for f in t["features"]}
        assert st["god_mode"] == "Install First" and st["aim_assist"] == "Requires Build" and not t["installed"]
        assert requests.post(f"{API}/trainer/apply", json={**q, "features": {"no_recoil": {"on": True}}}).status_code == 400
        j = requests.post(f"{API}/trainer/install", json=q).json()
        assert j["status"] == "needs_approval"
        requests.post(f"{API}/jobs/{j['id']}/approve")
        job, res = drain()
        mod = Path(d) / "bin/x64/plugins/cyber_engine_tweaks/mods/MeltyTrainer"
        assert (mod / "init.lua").read_text().startswith("-- MELTY Trainer")
        t = requests.get(f"{API}/trainer/game", params=q).json()
        assert t["installed"] and {f["key"]: f["status"] for f in t["features"]}["god_mode"] == "Available"
        r = requests.post(f"{API}/trainer/apply", json={**q, "features": {"super_speed": {"on": True, "value": 9}, "god_mode": {"on": True}}}).json()
        drain()
        sent = _json.loads((mod / "settings.json").read_text())
        assert sent["features"]["super_speed"]["value"] == 4 and sent["rev"] == r["rev"]  # clamped to the safe range
        assert {f["key"]: f["status"] for f in requests.get(f"{API}/trainer/game", params=q).json()["features"]}["super_speed"] == "Needs Testing"
        # simulate the in-game script's report: speed confirmed, god mode rejected by the game
        (mod / "status.json").write_text(_json.dumps({"loaded": 1, "in_game": True, "rev": r["rev"], "features": {
            "super_speed": {"ok": True, "info": "MaxSpeed=14"}, "god_mode": {"ok": False, "info": "attempt to call nil"}}}))
        requests.post(f"{API}/trainer/refresh", json=q)
        drain()
        sts = {f["key"]: f["status"] for f in requests.get(f"{API}/trainer/game", params=q).json()["features"]}
        assert sts["super_speed"] == "Active" and sts["god_mode"] == "Broken"
        p = requests.post(f"{API}/trainer/presets", json={**q, "name": "TEST Super Soldier", "features": {"super_speed": {"on": True, "value": 2}}}).json()
        assert any(x["id"] == p["id"] for x in requests.get(f"{API}/trainer/game", params=q).json()["presets"])
        requests.delete(f"{API}/trainer/presets/{p['id']}")
        mc.restore_journal(res["install_id"])
        assert not (mod / "init.lua").exists()
    finally:
        mdb.devices.delete_one({"id": did})
        for c in ("games", "jobs", "trainer_settings"):
            mdb[c].delete_many({"device_id": did})
        mdb.trainer_presets.delete_many({"name": {"$regex": "^TEST"}})
