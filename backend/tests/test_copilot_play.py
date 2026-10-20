"""Copilot play actions (install/confirm/remove), feature-proof gate, queue, games filter. FAKE device only (never ATLAS), no AI spend."""
import os
import sys
import time
import asyncio
import uuid
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
REAL_MOD = "a1138530221d4c139df85f40c6ffdf60"
GAME = "TEST_PLAY Game"


@pytest.fixture(scope="module")
def dev():
    code = requests.post(f"{API}/devices/pairing-code").json()["code"]
    r = requests.post(f"{API}/companion/pair", json={"code": code, "hostname": "TEST_PLAY_PC", "os": "test", "companion_version": "0.5.1"},
                      headers={"User-Agent": "MeltyCompanion"}).json()
    h = {"X-Device-Token": r["token"]}
    games = [{"name": GAME, "source": "steam", "install_dir": "/tmp/TEST_PLAY/game", "engine": "redengine4", "frameworks": ["cet"]},
             {"name": "Epic Games Launcher", "source": "folder", "install_dir": "/tmp/TEST_PLAY/egl", "engine": "unknown"},
             {"name": "Unreal Engine", "source": "folder", "install_dir": "/tmp/TEST_PLAY/ue", "engine": "unreal"},
             {"name": "Epic Games Launcher", "source": "epic", "install_dir": "/tmp/TEST_PLAY/egl2", "engine": "unknown"},
             {"name": "Unreal Engine", "source": "epic", "install_dir": "/tmp/TEST_PLAY/ue2", "engine": "unreal"}]
    requests.post(f"{API}/companion/games", json={"games": games}, headers=h)
    yield {"did": r["device_id"], "h": h}
    did = r["device_id"]
    pids = [m["id"] for m in mdb.mods.find({"device_id": did}, {"id": 1})]
    for c in ("games", "jobs", "installs"):
        mdb[c].delete_many({"device_id": did})
    for p in pids:
        mdb.releases.delete_many({"project_id": p})
        mdb.messages.delete_many({"project_id": p})
        mdb.versions.delete_many({"project_id": p})
        mdb.generations.delete_many({"project_id": p})
    mdb.mods.delete_many({"device_id": did})
    mdb.devices.delete_many({"id": did})


def make_mod(did, built=True, checks=("aim_assist", "aim_assist_visuals")):
    pid = "TEST_" + uuid.uuid4().hex
    bj = None
    if built:
        bj = "TEST_" + uuid.uuid4().hex
        mdb.jobs.insert_one({"id": bj, "device_id": did, "op": "build_mod", "status": "done", "project_id": pid, "result": {"ok": True},
                             "artifacts": [{"name": "TEST_mod.zip", "storage_path": "/tmp/TEST_mod.zip", "sha256": "0" * 64, "size": 1}],
                             "created_at": "2026-01-01T00:00:00+00:00"})
    mdb.mods.insert_one({"id": pid, "title": "TEST Play Mod", "slug": "TESTPlayMod", "host": {"name": GAME, "role": "host"}, "secondary": [],
                         "description": "TEST aim assist", "device_id": did, "toolchain": "cet-lua", "build_status": "built" if built else "unbuilt",
                         "current_version_id": "TEST_v_" + pid, "dirty": False, "last_build_job_id": bj, "feature_checks": list(checks),
                         "files": [], "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"})
    return pid


def run_job(dev, op, result, status="done"):
    for _ in range(20):
        j = requests.get(f"{API}/companion/jobs/next", headers=dev["h"]).json().get("job")
        if j:
            assert j["op"] == op, j["op"]
            r = requests.post(f"{API}/companion/jobs/{j['id']}/result", json={"status": status, "result": result, "log": "TEST"}, headers=dev["h"])
            assert r.status_code == 200
            return j
        time.sleep(0.3)
    raise AssertionError(f"no {op} job")


def wait_msg(pid, needle, secs=12):
    for _ in range(secs * 2):
        ms = requests.get(f"{API}/mods/{pid}/messages").json()
        hit = [m for m in ms if needle in (m.get("content") or "")]
        if hit:
            return hit[-1]
        time.sleep(0.5)
    raise AssertionError(f"no message containing {needle!r}: {[m.get('content') for m in ms]}")


# Play state / install / confirm / remove full flow
class TestPlayFlow:
    def test_play_state_built(self, dev):
        pid = make_mod(dev["did"])
        r = requests.get(f"{API}/mods/{pid}/play").json()
        assert r["built"] is True and r["installed"] is False and r["status"] == "built"
        assert r["feature_checks"] == ["aim_assist", "aim_assist_visuals"] and r["checking"] is False
        assert [f["name"] for f in r["features"]] == ["aim_assist", "aim_assist_visuals"] and not any(f["pass"] for f in r["features"])

    def test_full_flow(self, dev):
        pid = make_mod(dev["did"])
        r = requests.post(f"{API}/mods/{pid}/play")
        assert r.status_code == 200, r.text
        out = r.json()
        assert out.get("install_job") and out.get("launch_job")
        assert mdb.releases.count_documents({"project_id": pid}) == 1
        run_job(dev, "install_package", {"install_id": "TEST_inst_" + pid, "host_dir": "/tmp/TEST_PLAY/game", "created": 1})
        run_job(dev, "launch_game", {"ok": True})
        st = requests.get(f"{API}/mods/{pid}/play").json()
        assert st["installed"] is True and st["install_id"] == "TEST_inst_" + pid
        wait_msg(pid, "Installing it in your game")
        # second play reuses release
        assert requests.post(f"{API}/mods/{pid}/play").status_code == 200
        assert mdb.releases.count_documents({"project_id": pid}) == 1
        run_job(dev, "install_package", {"install_id": "TEST_inst_" + pid, "host_dir": "/tmp/TEST_PLAY/game"})
        run_job(dev, "launch_game", {"ok": True})

        # confirm: one missing, one failed -> Not confirmed
        c = requests.post(f"{API}/mods/{pid}/confirm").json()
        assert c["job_id"] and c["needs_approval"] is False
        assert requests.get(f"{API}/mods/{pid}/play").json()["checking"] is True
        run_job(dev, "collect_logs", {"checks": [{"name": "aim_assist", "pass": False, "detail": "no target"}], "log_tail": "x"})
        m = wait_msg(pid, "Not confirmed yet")
        assert "aim assist visuals" in m["content"] and "Not working: aim assist" in m["content"]
        assert {f["name"]: (f["seen"], f["pass"]) for f in m["features"]} == {"aim_assist": (True, False), "aim_assist_visuals": (False, False)}
        assert mdb.mods.find_one({"id": pid})["build_status"] == "built"
        st = requests.get(f"{API}/mods/{pid}/play").json()
        assert st["checking"] is False

        # confirm: old companion -> update message
        requests.post(f"{API}/mods/{pid}/confirm")
        run_job(dev, "collect_logs", {"log_tail": "old"})
        wait_msg(pid, "too old to read")
        assert mdb.mods.find_one({"id": pid})["build_status"] == "built"

        # confirm: empty checks
        requests.post(f"{API}/mods/{pid}/confirm")
        run_job(dev, "collect_logs", {"checks": [], "log_tail": ""})
        wait_msg(pid, "didn't find any sign")

        # confirm: failed job
        requests.post(f"{API}/mods/{pid}/confirm")
        run_job(dev, "collect_logs", {"error": "x"}, status="failed")
        wait_msg(pid, "couldn't read the game's log")

        # confirm: all PASS -> verified
        requests.post(f"{API}/mods/{pid}/confirm")
        run_job(dev, "collect_logs", {"checks": [{"name": "aim_assist", "pass": True, "detail": "rot moved"},
                                                  {"name": "aim_assist_visuals", "pass": True, "detail": "12 draws"}]})
        m = wait_msg(pid, "Confirmed in your game")
        assert all(f["pass"] for f in m["features"])
        assert mdb.mods.find_one({"id": pid})["build_status"] == "verified"
        assert requests.get(f"{API}/mods/{pid}/play").json()["status"] == "verified"

        # remove
        r = requests.post(f"{API}/mods/{pid}/remove")
        assert r.status_code == 200 and r.json()["job_id"]
        run_job(dev, "uninstall_package", {"restored": 1})
        assert requests.get(f"{API}/mods/{pid}/play").json()["installed"] is False
        assert requests.post(f"{API}/mods/{pid}/remove").status_code == 404
        wait_msg(pid, "Removing the mod")

    def test_verified_then_failed_check_status(self, dev):
        """After a mod is verified, a later failing check should not still claim 'Working in your game'."""
        pid = make_mod(dev["did"], checks=("speed_boost",))
        mdb.mods.update_one({"id": pid}, {"$set": {"build_status": "verified"}})
        requests.post(f"{API}/mods/{pid}/confirm")
        run_job(dev, "collect_logs", {"checks": [{"name": "speed_boost", "pass": False, "detail": "readback 600"}]})
        wait_msg(pid, "Not confirmed yet")
        assert mdb.mods.find_one({"id": pid})["build_status"] != "verified"


# Error paths
class TestPlayErrors:
    def test_unbuilt_play_400(self, dev):
        pid = make_mod(dev["did"], built=False)
        r = requests.post(f"{API}/mods/{pid}/play")
        assert r.status_code == 400
        assert requests.get(f"{API}/mods/{pid}/play").json()["built"] is False

    def test_missing_mod_404(self):
        for m, p in (("get", "play"), ("post", "play"), ("post", "confirm"), ("post", "remove")):
            assert getattr(requests, m)(f"{API}/mods/TEST_nope/{p}").status_code == 404

    def test_remove_not_installed_404(self, dev):
        pid = make_mod(dev["did"])
        assert requests.post(f"{API}/mods/{pid}/remove").status_code == 404

    def test_offline_409(self, dev):
        pid = make_mod(dev["did"])
        mdb.devices.update_one({"id": dev["did"]}, {"$set": {"last_seen": "2020-01-01T00:00:00+00:00"}})
        try:
            assert requests.post(f"{API}/mods/{pid}/play").status_code == 409
            assert requests.post(f"{API}/mods/{pid}/confirm").status_code == 409
        finally:
            requests.get(f"{API}/companion/jobs/next", headers=dev["h"])

    def test_real_mod_view_only(self):
        r = requests.get(f"{API}/mods/{REAL_MOD}/play")
        assert r.status_code == 200 and "feature_checks" in r.json()


# Queue while busy (fake running generation, no AI spend)
class TestQueue:
    def test_queue_and_remove(self, dev):
        pid = make_mod(dev["did"])
        gid = "TEST_" + uuid.uuid4().hex
        mdb.generations.insert_one({"id": gid, "project_id": pid, "kind": "edit", "status": "running", "events": [], "cost": 0, "calls": 0,
                                    "created_at": "2026-01-01T00:00:00+00:00"})
        assert requests.get(f"{API}/mods/{pid}").json()["active_generation_id"] == gid
        r = requests.post(f"{API}/mods/{pid}/chat", json={"message": "TEST also make it blue"}).json()
        assert r["queued"] is True
        ms = requests.get(f"{API}/mods/{pid}/messages").json()
        assert any(m["id"] == r["message_id"] and m.get("queued") for m in ms)
        assert mdb.generations.find_one({"id": gid})["inbox"][0]["id"] == r["message_id"]
        assert requests.post(f"{API}/mods/{pid}/queue/start").status_code == 409
        assert requests.delete(f"{API}/mods/{pid}/queue/{r['message_id']}").status_code == 200
        assert requests.delete(f"{API}/mods/{pid}/queue/{r['message_id']}").status_code == 404
        assert mdb.generations.find_one({"id": gid})["inbox"] == []
        c = requests.post(f"{API}/generations/{gid}/cancel")
        assert c.status_code == 200
        mdb.generations.update_one({"id": gid}, {"$set": {"status": "cancelled"}})


# Launcher / Unreal Engine entries filtered from game lists
class TestGamesFilter:
    def test_filtered(self, dev):
        names = [g["name"] for g in requests.get(f"{API}/devices/{dev['did']}/games").json()]
        assert GAME in names
        assert "Epic Games Launcher" not in names and "Unreal Engine" not in names
        ws = requests.get(f"{API}/workshop/games", params={"device_id": dev["did"]})
        if ws.status_code == 200:
            body = ws.json()
            wn = [g["name"] for g in (body if isinstance(body, list) else body.get("games", []))]
            assert "Epic Games Launcher" not in wn and "Unreal Engine" not in wn


# modagent finalize gate (unit level, fake ws/state)
class FakeWS:
    files = []

    def as_list(self):
        return []


def test_finalize_gate(dev):
    sys.path.insert(0, str(HERE.parent))
    import modagent

    async def go():
        out = {}
        cases = {"all_pass": ({"passed": True, "melty_checks": [{"name": "a", "pass": True}, {"name": "b", "pass": True}]}, ["a", "b"]),
                 "one_missing": ({"passed": True, "melty_checks": [{"name": "a", "pass": True}]}, ["a", "b"]),
                 "test_failed": ({"passed": False, "melty_checks": [{"name": "a", "pass": True}]}, ["a"]),
                 "no_names": ({"passed": True, "melty_checks": [{"name": "a", "pass": True}]}, []),
                 "a_fail": ({"passed": True, "melty_checks": [{"name": "a", "pass": False}]}, ["a"]),
                 "stale_build": ({"passed": True, "melty_checks": [{"name": "a", "pass": True}]}, ["a"])}
        for k, (v, names) in cases.items():
            pid = make_mod(dev["did"])
            gid = "TEST_" + uuid.uuid4().hex
            mdb.generations.insert_one({"id": gid, "project_id": pid, "status": "running", "events": [], "cost": 0, "created_at": "2026-01-01T00:00:00+00:00"})
            mod = mdb.mods.find_one({"id": pid}, {"_id": 0})
            v = {**v, "checks": {"launched": True, "plugin_loaded": True, "no_plugin_errors": True}}
            ws = FakeWS()
            h = modagent.files_hash(ws.as_list())
            state = {"last_build": {"id": "TEST_b", "result": {"ok": True}}, "verification": v, "build_hash": "stale" if k == "stale_build" else h, "verification_hash": h}
            await modagent.finalize(gid, mod, ws, state, {"summary": "TEST done", "spec_md": "x", "feature_checks": names}, "TEST", "edit")
            msg = mdb.messages.find_one({"project_id": pid, "generation_id": gid})
            out[k] = (mdb.mods.find_one({"id": pid})["build_status"], msg["content"])
        return out

    out = asyncio.run(go())
    assert out["all_pass"][0] == "verified"
    for k in ("one_missing", "test_failed", "no_names", "a_fail"):
        assert out[k][0] == "built", (k, out[k])
    assert out["stale_build"][0] == "unbuilt"
    for st, txt in out.values():
        assert "$" not in txt and "cost" not in txt.lower(), txt
        assert "Where it stands" in txt


def test_finish_tool_requires_feature_checks():
    sys.path.insert(0, str(HERE.parent))
    import modagent
    fin = [t for t in modagent.TOOLS if t["function"]["name"] == "finish"][0]
    assert "feature_checks" in fin["function"]["parameters"]["required"]
