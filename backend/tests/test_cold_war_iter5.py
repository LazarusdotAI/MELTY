# Cold War Phase 1 iteration-5 regression: fixes for secondary exclusion, legacy inspect retention, Unicode version
# validation, bare "Cold War" alias, SFX guard, alias parity (backend/companion/frontend), UE4SS/RE host unchanged.
# Uses its own isolated TEST_CW5 device; never touches ATLAS; no AI/ElevenLabs calls (all requests rejected pre-spend).
import os
import sys
import json
import importlib
import subprocess
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
API = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/") + "/api"
ATLAS = "761878c002d84bdba20614a4e5890604"
REASON = "Not supported by MELTY — host compatibility unverified"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CW = "/tmp/TEST_CW5/steam/BOCW"
ALIAS_UNITY = "/tmp/TEST_CW5/folder/AliasUnity"
APP_UNREAL = "/tmp/TEST_CW5/steam/AppUnreal"
MINDWARE = "/tmp/TEST_CW5/folder/ColdWar2005"
SKY = "/tmp/TEST_CW5/folder/Sky"
UE5 = "/tmp/TEST_CW5/steam/UE5"
RE = "/tmp/TEST_CW5/steam/RE"
KF2 = "/tmp/TEST_CW5/steam/KF2"
CW_NAMES = {"Call of Duty®: Black Ops Cold War", "TEST_CW5 AliasUnity", "TEST_CW5 AppUnreal"}

GAMES = [
    {"name": "Call of Duty®: Black Ops Cold War", "source": "steam", "steam_appid": "1985810", "install_dir": CW,
     "exe": "BlackOpsColdWar.exe", "engine": "unknown", "game_version": "build 1"},
    {"name": "TEST_CW5 AliasUnity", "source": "folder", "install_dir": ALIAS_UNITY, "exe": "BlackOpsColdWar.exe",
     "engine": "unity-mono", "managed_dir": ALIAS_UNITY + "/X_Data/Managed"},
    {"name": "TEST_CW5 AppUnreal", "source": "steam", "steam_appid": "1985810", "install_dir": APP_UNREAL,
     "exe": "Game-Win64-Shipping.exe", "engine": "unreal"},
    {"name": "Cold War", "source": "folder", "install_dir": MINDWARE, "exe": "ColdWar.exe", "engine": "unknown"},
    {"name": "TEST_CW5 Sky", "source": "folder", "install_dir": SKY, "exe": "Sky.exe", "engine": "unity-mono",
     "managed_dir": SKY + "/Sky_Data/Managed", "unity_version": "2021.3.1f1"},
    {"name": "TEST_CW5 UE5", "source": "steam", "steam_appid": "999001", "install_dir": UE5,
     "exe": "UE5-Win64-Shipping.exe", "engine": "unreal"},
    {"name": "TEST_CW5 RE", "source": "steam", "steam_appid": "999002", "install_dir": RE, "exe": "re.exe", "engine": "re-engine"},
    {"name": "Killing Floor 2", "source": "steam", "steam_appid": "232090", "install_dir": KF2,
     "exe": "Binaries/Win64/KFGame.exe", "engine": "unreal3", "sdk_installed": True},
]


@pytest.fixture(scope="module")
def dev():
    s = requests.Session()
    code = s.post(f"{API}/devices/pairing-code").json()["code"]
    d = s.post(f"{API}/companion/pair", json={"code": code, "hostname": "TEST_CW5-host", "os": "Windows-10-TEST",
                                              "companion_version": "0.3.0"}).json()
    assert d["device_id"] != ATLAS
    h = {"X-Device-Token": d["token"]}
    s.post(f"{API}/companion/heartbeat", json={"status": {"version": "0.3.0"}}, headers=h)
    assert s.post(f"{API}/companion/games", json={"games": GAMES}, headers=h).status_code == 200
    info = {"id": d["device_id"], "h": h, "mods": []}
    yield info
    did = d["device_id"]
    for c in ("games", "jobs", "installs", "pitches"):
        mdb[c].delete_many({"device_id": did})
    mdb.mods.delete_many({"$or": [{"device_id": did}, {"id": {"$in": info["mods"]}}]})
    for c in ("versions", "messages", "generations", "releases"):
        mdb[c].delete_many({"project_id": {"$in": info["mods"]}})
    mdb.devices.delete_one({"id": did})
    mdb.pairing.delete_one({"code": code})


def gmap(dev):
    return {g["install_dir"]: g for g in requests.get(f"{API}/devices/{dev['id']}/games").json()}


def spend():
    return mdb.ai_calls.count_documents({}), mdb.generations.count_documents({}), mdb.sfx.count_documents({}) if "sfx" in mdb.list_collection_names() else 0


# ---- engine labels for stale aliases ----
def test_alias_engine_is_t9(dev):
    g = gmap(dev)
    for p in (CW, ALIAS_UNITY, APP_UNREAL):
        assert g[p]["engine"] == "t9" and g[p]["adapter_id"] == "cold-war-t9" and g[p]["hostable"] is False, g[p]


# ---- bare Cold War (Mindware 2005) is not T9 ----
def test_bare_cold_war_not_t9(dev):
    g = gmap(dev)[MINDWARE]
    assert g["adapter_id"] != "cold-war-t9" and g["engine"] != "t9" and g.get("host_reason") != REASON
    r = requests.get(f"{API}/games/cold-war/compatibility", params={"device_id": dev["id"], "install_dir": MINDWARE})
    assert r.status_code == 400
    r = requests.post(f"{API}/games/cold-war/check", json={"device_id": dev["id"], "install_dir": MINDWARE})
    assert r.status_code == 400


# ---- alias parity backend / companion / frontend ----
CASES = [
    {"name": "Cold War"}, {"name": "Cold War", "exe": "ColdWar.exe"}, {"name": "cold-war"},
    {"name": "COD Cold War"}, {"name": "Call of Duty Cold War"}, {"name": "Black Ops: Cold War"},
    {"name": "Call of Duty®: Black Ops Cold War"}, {"name": "Black Ops Cold War™"},
    {"name": "Cold War", "steam_appid": 1985810}, {"name": "x", "exe": "C:\\G\\BlackOpsColdWar.exe"},
    {"name": "x", "exe": "D:/g/blackopscoldwar.EXE"}, {"name": "x", "adapter_id": "cold-war-t9"},
    {"name": "Call of Duty: Modern Warfare"}, {"name": "Black Ops III"}, {"game": "Black Ops Cold War"}, {},
]
EXPECT = [False, False, False, True, True, True, True, True, True, True, True, True, False, False, True, False]


def test_alias_parity():
    import adapters
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
    mc = importlib.import_module("melty_companion")
    back = [adapters.is_cold_war(c) for c in CASES]
    comp = [mc.is_cold_war(c) for c in CASES]
    src = Path("/app/frontend/src/components/ColdWarCompatibility.jsx").read_text()
    start = src.index("export function isColdWar")
    fn = src[start:src.index("\n}\n", start) + 2].replace("export ", "")
    js = fn + f"\nconsole.log(JSON.stringify({json.dumps(CASES)}.map(isColdWar)));"
    front = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert back == EXPECT, back
    assert comp == EXPECT, comp
    assert front == EXPECT, front


# ---- suggestions & pitch exclude Cold War as secondary ----
def test_suggestions_no_cold_war_secondary(dev):
    mdb.games.update_many({"device_id": dev["id"], "install_dir": {"$in": [ALIAS_UNITY, APP_UNREAL]}},
                          {"$set": {"hostable": True, "adapter_id": "unity-mono-bepinex5"}})
    try:
        sug = requests.get(f"{API}/suggestions", params={"device_id": dev["id"]}).json()
        assert sug["pairs"], "expected supported pairs"
        for p in sug["pairs"]:
            assert p["secondary"]["name"] not in CW_NAMES and p["host"]["name"] not in CW_NAMES, p
            assert "Cold War" not in p["key"] or p["key"].endswith("|Cold War")  # Mindware allowed
        blocked = {b["name"] for b in sug["blocked"]}
        assert CW_NAMES <= blocked
    finally:
        mdb.games.update_many({"device_id": dev["id"], "install_dir": {"$in": [ALIAS_UNITY, APP_UNREAL]}},
                              {"$set": {"hostable": False, "adapter_id": "cold-war-t9"}})


@pytest.mark.parametrize("key", ["Killing Floor 2|Call of Duty®: Black Ops Cold War", "TEST_CW5 Sky|TEST_CW5 AppUnreal",
                                 "TEST_CW5 Sky|TEST_CW5 AliasUnity"])
def test_pitch_rejects_cold_war_secondary_no_spend(dev, key):
    before = spend()
    r = requests.post(f"{API}/suggestions/pitch", json={"device_id": dev["id"], "keys": [key]})
    assert r.status_code == 400 and "No matching" in r.json()["detail"]
    assert spend() == before


# ---- legacy inspect result keeps good metadata ----
def _claim_and_post(dev, jid, result):
    nxt = requests.get(f"{API}/companion/jobs/next", headers=dev["h"]).json()["job"]
    assert nxt and nxt["id"] == jid
    r = requests.post(f"{API}/companion/jobs/{jid}/result", json={"status": "done", "result": result}, headers=dev["h"])
    assert r.status_code == 200


def test_legacy_inspect_result_retains_metadata(dev):
    j = requests.post(f"{API}/games/cold-war/check", json={"device_id": dev["id"], "install_dir": CW}).json()
    _claim_and_post(dev, j["id"], {"install_dir": CW, "exe": "BlackOpsColdWar.exe", "installation_exists": True,
                                   "executable_exists": True, "executable_version": "1.34.1.1", "inspection_note": None})
    good = mdb.games.find_one({"device_id": dev["id"], "install_dir": CW})
    assert good["executable_version"] == "1.34.1.1" and good["compatibility_checked_at"]
    r = requests.post(f"{API}/devices/{dev['id']}/jobs", json={"op": "inspect_game", "params": {
        "name": "Call of Duty®: Black Ops Cold War", "install_dir": CW}})
    assert r.status_code == 200, r.text
    _claim_and_post(dev, r.json()["id"], {"install_dir": CW, "managed": ["Assembly-CSharp.dll"], "loader_installed": False})
    g = mdb.games.find_one({"device_id": dev["id"], "install_dir": CW})
    for k in ("executable_version", "installation_exists", "executable_exists", "compatibility_checked_at"):
        assert g.get(k) == good.get(k), k
    assert not g.get("managed") and g.get("loader_installed") is None
    rep = requests.get(f"{API}/games/cold-war/compatibility", params={"device_id": dev["id"], "install_dir": CW}).json()
    assert rep["installation"]["executable_version"] == "1.34.1.1"
    # partial result updates only present keys
    r = requests.post(f"{API}/devices/{dev['id']}/jobs", json={"op": "inspect_game", "params": {
        "name": "Call of Duty®: Black Ops Cold War", "install_dir": CW, "metadata_only": True}})
    _claim_and_post(dev, r.json()["id"], {"install_dir": CW, "executable_exists": False})
    g2 = mdb.games.find_one({"device_id": dev["id"], "install_dir": CW})
    assert g2["executable_exists"] is False and g2["executable_version"] == "1.34.1.1" and g2["installation_exists"] is True


# ---- manual version Unicode controls ----
@pytest.mark.parametrize("bad", ["1.0\u0085", "1.\u200b0", "1.0\u2028x", "1.0\u2029", "\u202e1.0", "1.0\ufeff", "1.0\t", "1\x7f"])
def test_manual_version_unicode_rejected(dev, bad):
    r = requests.patch(f"{API}/games/cold-war/version", json={"device_id": dev["id"], "install_dir": CW, "version": bad})
    assert r.status_code == 422, (repr(bad), r.status_code)


def test_manual_version_unicode_letters_ok(dev):
    r = requests.patch(f"{API}/games/cold-war/version", json={"device_id": dev["id"], "install_dir": CW, "version": "1.34 Ü-版本 (Steam)"})
    assert r.status_code == 200 and r.json()["installation"]["manual_version"] == "1.34 Ü-版本 (Steam)"
    requests.patch(f"{API}/games/cold-war/version", json={"device_id": dev["id"], "install_dir": CW, "version": ""})


# ---- SFX guard before key check/spend ----
def test_sfx_legacy_cold_war_guard(dev):
    pid = "TEST_CW5_sfx_mod"
    dev["mods"].append(pid)
    mdb.mods.insert_one({"id": pid, "title": "TEST_CW5 sfx", "host": {"name": "Call of Duty®: Black Ops Cold War"},
                         "device_id": dev["id"], "files": [], "secondary": []})
    before = spend()
    r = requests.post(f"{API}/sfx/generate", json={"prompt": "TEST_CW5 boom", "project_id": pid})
    assert r.status_code == 400 and r.json()["detail"] == REASON
    # alias resolved via stored install identity (host name only, stored game is exe alias)
    mdb.mods.update_one({"id": pid}, {"$set": {"host": {"name": "TEST_CW5 AliasUnity"}}})
    r = requests.post(f"{API}/sfx/generate", json={"prompt": "TEST_CW5 boom", "project_id": pid})
    assert r.status_code == 400 and r.json()["detail"] == REASON
    assert spend() == before


def test_sfx_mod_without_host_no_500(dev):
    pid = "TEST_CW5_sfx_nohost"
    dev["mods"].append(pid)
    mdb.mods.insert_one({"id": pid, "title": "TEST_CW5 nohost", "device_id": dev["id"]})
    r = requests.post(f"{API}/sfx/generate", json={"prompt": "TEST_CW5 boom", "project_id": pid})
    assert r.status_code != 500, r.text


# ---- old companion check message references My PC update ----
def test_old_companion_message(dev):
    requests.post(f"{API}/companion/heartbeat", json={"status": {"version": "0.2.0"}}, headers=dev["h"])
    try:
        r = requests.post(f"{API}/games/cold-war/check", json={"device_id": dev["id"], "install_dir": CW})
        assert r.status_code == 409 and "My PC" in r.json()["detail"] and "0.3.0" in r.json()["detail"]
    finally:
        requests.post(f"{API}/companion/heartbeat", json={"status": {"version": "0.3.0"}}, headers=dev["h"])


# ---- supported hosts unchanged (UE4SS / RE / KF2 / Unity) ----
def test_supported_hosts_unchanged(dev):
    g = gmap(dev)
    assert g[UE5]["hostable"] is True and g[UE5]["toolchain"] == "ue4ss-lua" and g[UE5]["adapter_id"] == "unreal"
    assert g[RE]["hostable"] is False and g[RE]["adapter_id"] == "re-engine" and "REFramework" in g[RE]["host_reason"]
    assert g[KF2]["toolchain"] == "ue3-unrealscript" and g[SKY]["toolchain"] == "bepinex5-csharp"
    assert g[MINDWARE].get("host_reason") != REASON
    for name in ("TEST_CW5 UE5", "TEST_CW5 Sky"):
        r = requests.post(f"{API}/devices/{dev['id']}/jobs", json={"op": "launch_game", "params": {"manifest": {"host": {"game": name}}}})
        assert r.status_code == 200, r.text
        requests.post(f"{API}/jobs/{r.json()['id']}/cancel")
    d = requests.get(f"{API}/games/details", params={"device_id": dev["id"], "install_dir": UE5}).json()
    assert d["buildable_host"] is True
