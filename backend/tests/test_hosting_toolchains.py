"""Regression: per-toolchain hostability, non-game filter, suggestions, create_mod host guard, companion setup/version.
Uses only the simulated device. Never creates a mod with a hostable host (that spends AI money)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
SIM = "78b5c7a2123341b7a3408d215a081cf6"
COD = "Call of Duty®: Black Ops Cold War"
# Legacy suite bound to a removed SIM device and pre-Phase-1 Cold War expectations (anti-cheat reason, 0.2.0).
# Cold War behaviour is now covered by test_cold_war_compat.py / test_cold_war_companion.py with isolated fixtures.
pytestmark = pytest.mark.skipif(
    not any(d["id"] == SIM for d in requests.get(f"{BASE_URL}/api/devices").json()),
    reason="SIM fixture device absent; superseded by test_cold_war_compat.py")


@pytest.fixture(scope="module")
def games():
    r = requests.get(f"{BASE_URL}/api/devices/{SIM}/games")
    assert r.status_code == 200
    return {g["name"]: g for g in r.json()}


# Hostability per adapter toolchain
def test_kf2_hostable(games):
    g = games["Killing Floor 2"]
    assert g["hostable"] is True and g["toolchain"] == "ue3-unrealscript" and g["adapter_id"] == "game-kf2"


def test_skyreach_hostable(games):
    g = games["Skyreach"]
    assert g["hostable"] is True and g["toolchain"] == "ue4ss-lua"


def test_cod_blocked(games):
    g = games[COD]
    assert g["hostable"] is False and g["adapter_id"] == "cold-war-t9" and "unverified" in g["host_reason"]


def test_re_village_not_hostable(games):
    g = games["ResidentEvilVillage"]
    assert g["hostable"] is False and "RE Engine" in g["host_reason"]


# Non-game filter
def test_no_launchers(games):
    assert not any("launcher" in n.lower() or "social club" in n.lower() for n in games)


# Suggestions
def test_suggestions():
    d = requests.get(f"{BASE_URL}/api/suggestions", params={"device_id": SIM}).json()
    assert d["host_count"] == 2 and len(d["pairs"]) > 0
    assert {p["host"]["name"] for p in d["pairs"]} == {"Killing Floor 2", "Skyreach"}
    assert {b["name"] for b in d["blocked"]} == {COD, "ResidentEvilVillage"}
    assert all(b["reason"] for b in d["blocked"])


# Game details
def test_game_details_kf2(games):
    r = requests.get(f"{BASE_URL}/api/games/details", params={"device_id": SIM, "install_dir": games["Killing Floor 2"]["install_dir"]})
    assert r.status_code == 200
    d = r.json()
    assert d["game"]["toolchain"] == "ue3-unrealscript" and d["adapter"]["id"] == "game-kf2"


def test_game_details_buildable_host_matches_hostable(games):
    r = requests.get(f"{BASE_URL}/api/games/details", params={"device_id": SIM, "install_dir": games["Killing Floor 2"]["install_dir"]})
    assert r.json()["buildable_host"] is True, "buildable_host still computed as engine == unity-mono"


# create_mod host guard (only non-hostable hosts -> 400, no AI spend)
@pytest.mark.parametrize("host", [COD, "ResidentEvilVillage"])
def test_create_mod_rejects_unhostable(host):
    r = requests.post(f"{BASE_URL}/api/mods", json={"host": {"name": host, "role": "host"}, "description": "TEST_x",
                                                    "device_id": SIM, "secondary": [], "aspects": []})
    assert r.status_code == 400 and ("unverified" if host == COD else "can't be a host") in r.json()["detail"]


# Companion app version + setup.bat
def test_version():
    assert requests.get(f"{BASE_URL}/api/companion-app/version").json()["version"] == "0.3.1"


def test_setup_bat_ok():
    r = requests.get(f"{BASE_URL}/api/companion-app/setup.bat", params={"code": "ABCDEFGH", "server": "https://example.com"})
    assert r.status_code == 200 and "MELTY-Setup.bat" in r.headers["content-disposition"]
    assert "https://example.com" in r.text and "ABCDEFGH" in r.text


@pytest.mark.parametrize("code,server", [("bad", "https://example.com"), ("ABCDEFGH", "http://example.com"), ("ABCDEFGH", "https://x.com&calc")])
def test_setup_bat_invalid(code, server):
    assert requests.get(f"{BASE_URL}/api/companion-app/setup.bat", params={"code": code, "server": server}).status_code == 400


# Checklist host step should count hostable games
def test_checklist_host_counts_hostable():
    c = requests.get(f"{BASE_URL}/api/checklist").json()
    steps = {s["key"]: s for s in c["steps"]}
    assert steps["host"]["done"] is True, steps["host"]["label"]
    n = sum(1 for g in requests.get(f"{BASE_URL}/api/devices/{c['device_id']}/games").json() if g.get("hostable"))
    assert f"({n})" in steps["host"]["label"]
    # no BepInEx hosts on either device -> .NET not needed
    assert steps["dotnet"]["label"] == ".NET SDK (not needed for your hosts)" and steps["dotnet"]["done"] is True


# Details drawer data for Skyreach also hostable
def test_game_details_skyreach_buildable(games):
    r = requests.get(f"{BASE_URL}/api/games/details", params={"device_id": SIM, "install_dir": games["Skyreach"]["install_dir"]})
    assert r.status_code == 200 and r.json()["buildable_host"] is True


def test_game_details_cod_not_buildable(games):
    r = requests.get(f"{BASE_URL}/api/games/details", params={"device_id": SIM, "install_dir": games[COD]["install_dir"]})
    assert r.status_code == 200 and r.json()["buildable_host"] is False


# secondary_fit reasons
def test_secondary_reasons_not_unknown_for_known_engines(games):
    d = requests.get(f"{BASE_URL}/api/suggestions", params={"device_id": SIM}).json()
    for p in d["pairs"]:
        eng = games[p["secondary"]["name"]].get("engine")
        if eng in ("unreal", "unreal3", "re-engine"):
            assert not any("Unknown engine" in r for r in p["reasons"]), (p["key"], p["reasons"])
    sec = {p["secondary"]["name"]: p["reasons"][-1] for p in d["pairs"]}
    if "ResidentEvilVillage" in sec:
        assert "RE Engine" in sec["ResidentEvilVillage"]
    if "Killing Floor 2" in sec:
        assert "Unreal" in sec["Killing Floor 2"]


# Blocked check happens before budget
def test_create_mod_cod_400_before_budget():
    r = requests.post(f"{BASE_URL}/api/mods", json={"host": {"name": COD}, "description": "TEST_x", "device_id": SIM})
    assert r.status_code == 400 and "unverified" in r.json()["detail"]
