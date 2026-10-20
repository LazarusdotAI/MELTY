"""Asset Workshop edge cases: validation errors, offline device, deny flow, device scoping, traversal guards.
Reuses the simulated companion fixture from test_workshop_e2e (never touches ATLAS)."""
import os
import time

import requests
from test_workshop_e2e import API, post, wait
from test_workshop_e2e import pc as pc

FAKE_DEV = "TEST_no_such_device"


# Validation errors
def test_extract_requires_paths(pc):
    r = requests.post(f"{API}/workshop/extract", json={"install_dir": pc["inst"], "device_id": pc["did"], "container": "x", "paths": []})
    assert r.status_code == 400 and "Pick" in r.json()["detail"]


def test_package_requires_files(pc):
    r = requests.post(f"{API}/workshop/package", json={"install_dir": pc["inst"], "device_id": pc["did"], "package_name": "x", "files": []})
    assert r.status_code == 400


def test_unknown_install_dir_404_on_many_routes(pc):
    for path, extra in [("extract", {"container": "c", "paths": ["a"]}), ("convert", {"files": ["a"]}), ("install", {"package": "p"}),
                        ("cleanup", {}), ("validate", {"files": ["a"]})]:
        r = requests.post(f"{API}/workshop/{path}", json={"install_dir": "C:/Nope", "device_id": pc["did"], **extra})
        assert r.status_code == 404, (path, r.status_code)


# Offline / unknown device -> 409
def test_offline_device_409(pc):
    for path in ("scan", "cleanup"):
        r = requests.post(f"{API}/workshop/{path}", json={"install_dir": pc["inst"], "device_id": FAKE_DEV})
        assert r.status_code == 409 and "offline" in r.json()["detail"].lower()
    assert requests.post(f"{API}/workshop/detect", params={"device_id": FAKE_DEV}).status_code == 409
    assert requests.post(f"{API}/workshop/rollback", json={"install_id": "x", "device_id": FAKE_DEV}).status_code == 409


# games endpoint must honour device_id
def test_games_with_device_id_returns_that_device(pc):
    d = requests.get(f"{API}/workshop/games", params={"device_id": pc["did"]}).json()
    assert d["device"]["id"] == pc["did"] and d["device"]["asset_tools"] is True
    assert any(g["install_dir"] == pc["inst"] for g in d["games"])


def test_games_unknown_device_id_does_not_fall_back_to_other_pc(pc):
    d = requests.get(f"{API}/workshop/games", params={"device_id": FAKE_DEV}).json()
    assert d["device"] is None or d["device"]["id"] == FAKE_DEV, f"fell back to {d['device']['hostname']}"


# ops filter by device
def test_ops_scoped_to_device(pc):
    wait(post("scan", pc)["id"])
    ops = requests.get(f"{API}/workshop/ops", params={"device_id": pc["did"], "limit": 200}).json()
    assert ops and all(o["install_dir"] in (pc["inst"], None) for o in ops)


# Deny permission -> Failed and never runs; no grant created
def test_deny_extract_permission(pc):
    requests.post(f"{API}/workshop/grants/revoke", json={"install_dir": pc["inst"], "device_id": pc["did"]})
    pak = os.path.join(pc["paks"], "pakchunk0-WinGDK.pak")
    j = post("extract", pc, container=pak, paths=["Stalker2/Content/Textures/T_Red.dds"])
    assert j["state"] == "Permission Required"
    assert requests.post(f"{API}/jobs/{j['id']}/cancel").status_code == 200
    r = wait(j["id"], 10)
    assert r["state"] == "Failed" and "Cancel" in (r["why"] or "")
    g = requests.get(f"{API}/workshop/games", params={"device_id": pc["did"]}).json()["games"]
    assert not next(x for x in g if x["install_dir"] == pc["inst"])["extract_granted"]


# Install always asks, even after an extract grant exists
def test_install_always_asks_even_with_grant(pc):
    pak = os.path.join(pc["paks"], "pakchunk0-WinGDK.pak")
    j = post("extract", pc, container=pak, paths=["Stalker2/Content/Textures/T_Red.dds"])
    requests.post(f"{API}/jobs/{j['id']}/approve")
    wait(j["id"])
    ins = post("install", pc, package="/tmp/does-not-exist.pak")
    assert ins["state"] == "Permission Required"
    requests.post(f"{API}/jobs/{ins['id']}/cancel")


# Package destination traversal must not escape
def test_package_dest_traversal_rejected(pc):
    pak = os.path.join(pc["paks"], "pakchunk0-WinGDK.pak")
    e = wait(post("extract", pc, container=pak, paths=["Stalker2/Content/GameLite/Weapons/GunAKM.cfg"])["id"])
    src = e["result"]["extracted"][0]["out"]
    pk = wait(post("package", pc, package_name="../../TEST_evil", files=[{"src": src, "dest": "../../../../evil.cfg"}])["id"])
    if pk["state"] == "Completed":
        assert "/tmp/TEST_WS/XboxGames" not in pk["result"]["package"] or "packages" in pk["result"]["package"]
        assert ".." not in pk["result"]["package"]


def test_rollback_unknown_install_fails(pc):
    r = requests.post(f"{API}/workshop/rollback", json={"install_id": "TEST_nope", "device_id": pc["did"]}).json()
    assert wait(r["id"])["state"] == "Failed"


def test_list_encrypted_container_400(pc):
    pak9 = os.path.join(pc["paks"], "pakchunk9-WinGDK.pak")
    t = time.time()
    r = requests.post(f"{API}/workshop/list", json={"install_dir": pc["inst"], "device_id": pc["did"], "container": pak9})
    assert time.time() - t < 30
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        assert r.json()["total"] == 0 or r.json().get("issues")
