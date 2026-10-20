# MELTY modding platform backend regression tests (no AI-spending calls)
import io
import os
import zipfile
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
MOD_ID = "b174817333f2448d8dbca73a73d856b5"
REL_ID = "c5e456f2038c432f82dc575bfa3a3831"
ATLAS = "761878c002d84bdba20614a4e5890604"
# Seeded fixtures from the early simulated run; skip their tests when the data has since been cleared.
needs_mod = pytest.mark.skipif(requests.get(f"{BASE_URL}/api/mods/{MOD_ID}").status_code != 200,
                               reason="fixture mod MOD_ID absent")
needs_release = pytest.mark.skipif(requests.get(f"{BASE_URL}/api/releases/{REL_ID}").status_code != 200,
                                   reason="fixture release REL_ID absent")


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture
def temporary_devices():
    from pathlib import Path
    from dotenv import load_dotenv
    from pymongo import MongoClient
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    entries = []
    yield entries
    with MongoClient(os.environ["MONGO_URL"]) as client:
        db = client[os.environ["DB_NAME"]]
        for did, code in entries:
            assert did != ATLAS
            db.jobs.delete_many({"device_id": did})
            db.devices.delete_one({"id": did})
            db.pairing.delete_one({"code": code})


@pytest.fixture(scope="module")
def device(s):
    # Only the simulated companion (with its FakeQuest game) qualifies; never the user's real PC.
    ds = s.get(f"{BASE_URL}/api/devices").json()
    for d in ds:
        if d.get("online") and d["id"] != ATLAS and any(
                g["name"] == "FakeQuest" for g in s.get(f"{BASE_URL}/api/devices/{d['id']}/games").json()):
            return d
    pytest.skip("No online simulated companion with FakeQuest")


# Health & providers
def test_health(s):
    r = s.get(f"{BASE_URL}/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_providers_status_and_switch(s):
    r = s.get(f"{BASE_URL}/api/providers/status")
    assert r.status_code == 200
    data = r.json()
    txt = str(data)
    for k in ("kimi", "claude", "openai", "gemini"):
        assert k in txt
    orig = data.get("preferred") or data.get("preferred_model") or "kimi"
    r2 = s.put(f"{BASE_URL}/api/providers/preferred", json={"preferred_model": "claude"})
    assert r2.status_code == 200
    assert "claude" in str(r2.json())
    bad = s.put(f"{BASE_URL}/api/providers/preferred", json={"preferred_model": "nope"})
    assert bad.status_code == 400
    s.put(f"{BASE_URL}/api/providers/preferred", json={"preferred_model": orig if orig in ("kimi", "claude", "openai", "gemini") else "kimi"})


# Budget
def test_budget_view(s):
    r = s.get(f"{BASE_URL}/api/budget")
    assert r.status_code == 200
    d = r.json()
    for k in ("spent", "reserved", "remaining", "ceiling", "per_project", "generations", "calls", "outside_limit"):
        assert k in d, k
    assert d["remaining"] <= d["ceiling"]


def test_budget_settings_validation_and_persist(s):
    for bad in ({"daily_ceiling": 0, "generation_ceiling": 2.5}, {"daily_ceiling": 101, "generation_ceiling": 2.5},
                {"daily_ceiling": 9, "generation_ceiling": -1}):
        assert s.put(f"{BASE_URL}/api/budget/settings", json=bad).status_code == 422
    r = s.put(f"{BASE_URL}/api/budget/settings", json={"daily_ceiling": 12.5, "generation_ceiling": 3})
    assert r.status_code == 200 and r.json()["daily_ceiling"] == 12.5
    assert s.get(f"{BASE_URL}/api/budget").json()["ceiling"] == 12.5
    r = s.put(f"{BASE_URL}/api/budget/settings", json={"daily_ceiling": 9, "generation_ceiling": 2.5})
    assert r.json()["daily_ceiling"] == 9 and r.json()["generation_ceiling"] == 2.5


# Pairing & companion auth
def test_pairing_flow(s, temporary_devices):
    r = s.post(f"{BASE_URL}/api/devices/pairing-code")
    assert r.status_code == 200
    code = r.json()["code"]
    assert len(code) == 8
    body = {"code": code, "hostname": "TEST_host", "os": "TestOS", "companion_version": "0.0.1"}
    p = s.post(f"{BASE_URL}/api/companion/pair", json=body)
    assert p.status_code == 200
    tok, did = p.json()["token"], p.json()["device_id"]
    temporary_devices.append((did, code))
    assert tok
    assert s.post(f"{BASE_URL}/api/companion/pair", json=body).status_code == 400
    hb = s.post(f"{BASE_URL}/api/companion/heartbeat", json={"status": {}}, headers={"X-Device-Token": tok})
    assert hb.status_code == 200
    # cleanup TEST device
    s.delete(f"{BASE_URL}/api/devices/{did}")
    # revoked token now 401
    assert s.post(f"{BASE_URL}/api/companion/heartbeat", json={"status": {}}, headers={"X-Device-Token": tok}).status_code == 401


def test_companion_rejects_bad_tokens(s):
    assert s.get(f"{BASE_URL}/api/companion/jobs/next").status_code == 401
    assert s.get(f"{BASE_URL}/api/companion/jobs/next", headers={"X-Device-Token": "bogus"}).status_code == 401
    assert s.post(f"{BASE_URL}/api/companion/heartbeat", json={}, headers={"X-Device-Token": "bogus"}).status_code == 401
    assert s.get(f"{BASE_URL}/api/companion/download", params={"path": "x"}).status_code == 401


# Jobs & approvals (uses a temp TEST device so the real device's ops are untouched)
def test_jobs_approval_flow(s, temporary_devices):
    code = s.post(f"{BASE_URL}/api/devices/pairing-code").json()["code"]
    p = s.post(f"{BASE_URL}/api/companion/pair", json={"code": code, "hostname": "TEST_jobs", "os": "x", "companion_version": "1"}).json()
    did = p["device_id"]
    temporary_devices.append((did, code))
    try:
        assert s.post(f"{BASE_URL}/api/devices/{did}/jobs", json={"op": "rm_rf", "params": {}}).status_code == 400
        assert s.patch(f"{BASE_URL}/api/devices/{did}", json={"approved_ops": ["doctor", "evil"]}).json()["approved_ops"] == ["doctor"]
        j = s.post(f"{BASE_URL}/api/devices/{did}/jobs", json={"op": "screenshot", "params": {}}).json()
        assert j["status"] == "needs_approval"
        assert s.post(f"{BASE_URL}/api/jobs/{j['id']}/approve").status_code == 200
        g = s.get(f"{BASE_URL}/api/jobs/{j['id']}")
        assert g.status_code == 200 and g.json()["status"] == "queued"
        j2 = s.post(f"{BASE_URL}/api/devices/{did}/jobs", json={"op": "doctor", "params": {}}).json()
        assert j2["status"] == "queued"
        assert s.get(f"{BASE_URL}/api/jobs/doesnotexist").status_code == 404
    finally:
        s.delete(f"{BASE_URL}/api/devices/{did}")
    assert s.get(f"{BASE_URL}/api/jobs/{j['id']}").json()["status"] == "cancelled"


# Adapters & knowledge
def test_adapters_and_knowledge(s):
    ads = s.get(f"{BASE_URL}/api/adapters").json()
    ids = {a["id"] for a in ads}
    for a in ("unity-mono-bepinex5", "unity-il2cpp", "unreal", "game-repo", "game-ultrakill"):
        assert a in ids, a
    target = ads[0]["name"]
    r = s.post(f"{BASE_URL}/api/knowledge", json={"game": target, "note": "TEST_note pytest"})
    assert r.status_code == 200
    ads2 = s.get(f"{BASE_URL}/api/adapters").json()
    notes = next(a for a in ads2 if a["name"] == target)["notes"]
    assert any("TEST_note pytest" in n.get("note", "") for n in notes)


# Mods, versions, files, export
@needs_mod
def test_mods_list_and_detail(s):
    ms = s.get(f"{BASE_URL}/api/mods").json()
    assert any(m["id"] == MOD_ID for m in ms)
    d = s.get(f"{BASE_URL}/api/mods/{MOD_ID}")
    assert d.status_code == 200 and d.json()["id"] == MOD_ID and "files" in d.json()
    assert s.get(f"{BASE_URL}/api/mods/nonexistent").status_code == 404


@needs_mod
def test_file_save_locked_and_cs(s):
    m = s.get(f"{BASE_URL}/api/mods/{MOD_ID}").json()
    csproj = next(f for f in m["files"] if f["path"].endswith(".csproj"))
    r = s.put(f"{BASE_URL}/api/mods/{MOD_ID}/files", json={"path": csproj["path"], "content": "x"})
    assert r.status_code == 400
    # NOTE: "../x.cs" is silently sanitized to "x.cs" by lstrip("./"); only embedded ".." is rejected
    assert s.put(f"{BASE_URL}/api/mods/{MOD_ID}/files", json={"path": "src/../evil.cs", "content": "x"}).status_code == 400
    assert s.put(f"{BASE_URL}/api/mods/{MOD_ID}/files", json={"path": "evil.exe", "content": "x"}).status_code == 400


@needs_mod
def test_checkpoint_restore_and_cs_save(s):
    if s.get(f"{BASE_URL}/api/mods/{MOD_ID}").json().get("active_generation_id"):
        pytest.skip("AI busy")
    before = s.get(f"{BASE_URL}/api/mods/{MOD_ID}").json()
    cp = s.post(f"{BASE_URL}/api/mods/{MOD_ID}/versions", json={"name": "TEST_checkpoint"})
    assert cp.status_code == 200
    vid = cp.json()["version_id"]
    vs = s.get(f"{BASE_URL}/api/mods/{MOD_ID}/versions").json()
    v = next(x for x in vs if x["id"] == vid)
    # save a scratch .cs file
    r = s.put(f"{BASE_URL}/api/mods/{MOD_ID}/files", json={"path": "TEST_Scratch.cs", "content": "// test"})
    assert r.status_code == 200
    m = s.get(f"{BASE_URL}/api/mods/{MOD_ID}").json()
    assert any(f["path"] == "TEST_Scratch.cs" for f in m["files"]) and m["dirty"] is True
    # restore checkpoint -> scratch file gone
    rr = s.post(f"{BASE_URL}/api/mods/{MOD_ID}/versions/{vid}/restore")
    assert rr.status_code == 200
    m2 = s.get(f"{BASE_URL}/api/mods/{MOD_ID}").json()
    assert not any(f["path"] == "TEST_Scratch.cs" for f in m2["files"])
    assert sorted(f["path"] for f in m2["files"]) == sorted(f["path"] for f in before["files"])
    vs2 = s.get(f"{BASE_URL}/api/mods/{MOD_ID}/versions").json()
    assert vs2[0]["name"].startswith(f"Restored v{v['number']}")
    assert s.post(f"{BASE_URL}/api/mods/{MOD_ID}/versions/bad/restore").status_code == 404


@needs_mod
def test_export_zip(s):
    r = s.get(f"{BASE_URL}/api/mods/{MOD_ID}/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/zip")
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert any(n.endswith("DESIGN.md") for n in names) and any(n.endswith("README.md") for n in names)


# Releases, compat, catalog
@needs_release
def test_release_compat_publish(s):
    r = s.get(f"{BASE_URL}/api/releases/{REL_ID}")
    assert r.status_code == 200
    rel = r.json()
    orig_pub = rel["published"]
    gv = next(iter(rel["compat"]))
    orig = rel["compat"][gv]["save_load"]["status"]
    p = s.patch(f"{BASE_URL}/api/releases/{REL_ID}/compat", json={"key": "save_load", "status": "partial", "note": "TEST"})
    assert p.status_code == 200 and p.json()["compat"][gv]["save_load"]["status"] == "partial"
    assert s.patch(f"{BASE_URL}/api/releases/{REL_ID}/compat", json={"key": "bad", "status": "partial"}).status_code == 400
    assert s.patch(f"{BASE_URL}/api/releases/{REL_ID}/compat", json={"key": "save_load", "status": "bad"}).status_code == 400
    s.patch(f"{BASE_URL}/api/releases/{REL_ID}/compat", json={"key": "save_load", "status": orig})
    s.post(f"{BASE_URL}/api/releases/{REL_ID}/publish", json={"publish": True})
    assert any(x["id"] == REL_ID for x in s.get(f"{BASE_URL}/api/catalog").json())
    s.post(f"{BASE_URL}/api/releases/{REL_ID}/publish", json={"publish": False})
    assert not any(x["id"] == REL_ID for x in s.get(f"{BASE_URL}/api/catalog").json())
    s.post(f"{BASE_URL}/api/releases/{REL_ID}/publish", json={"publish": orig_pub})
    assert s.get(f"{BASE_URL}/api/releases/nope").status_code == 404


def test_catalog_hides_storage_path(s):
    for x in s.get(f"{BASE_URL}/api/catalog").json():
        for f in x["manifest"]["files"]:
            assert "storage_path" not in f


# Assets & SFX
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def test_asset_upload_png(s):
    r = s.post(f"{BASE_URL}/api/assets/upload", files={"file": ("TEST_px.png", PNG, "image/png")}, data={"license": "CC0"})
    assert r.status_code == 200
    aid = r.json()["id"]
    assert any(a["id"] == aid for a in s.get(f"{BASE_URL}/api/assets").json())
    f = s.get(f"{BASE_URL}/api/assets/file/{aid}")
    assert f.status_code == 200 and f.content == PNG
    bad = s.post(f"{BASE_URL}/api/assets/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 400
    s.delete(f"{BASE_URL}/api/assets/{aid}")
    assert s.get(f"{BASE_URL}/api/assets/file/{aid}").status_code == 404


def test_sfx_disabled(s):
    st = s.get(f"{BASE_URL}/api/sfx/status").json()
    assert st["enabled"] is False
    r = s.post(f"{BASE_URL}/api/sfx/generate", json={"prompt": "laser zap", "duration": 2})
    assert r.status_code == 400


# Companion device state
def test_device_games_and_installs(s, device):
    games = s.get(f"{BASE_URL}/api/devices/{device['id']}/games").json()
    assert any(g["name"] == "FakeQuest" for g in games)
    ins = s.get(f"{BASE_URL}/api/installs").json()
    assert isinstance(ins, list)
    assert "token_hash" not in device
