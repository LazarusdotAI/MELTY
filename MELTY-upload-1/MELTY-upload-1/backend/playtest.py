"""Copilot one-tap actions: install a mod to play, confirm features from the game's own log, remove it."""
import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException
from core import db, now, new_id, logger
from devices import enqueue, online_device, wait_job
import adapters
import packages
from modagent import feature_results, confirmed

router = APIRouter(prefix="/api/mods")


async def mod_or_404(pid):
    m = await db.mods.find_one({"id": pid}, {"_id": 0, "files": 0})
    if not m:
        raise HTTPException(404, "Mod not found")
    return m


async def pc_for(mod):
    d = await online_device(mod.get("device_id"))
    if not d:
        raise HTTPException(409, "Your PC isn't connected. Start MELTY Companion on it first.")
    return d


async def current_install(pid):
    rids = [r["id"] async for r in db.releases.find({"project_id": pid}, {"id": 1})]
    return await db.installs.find_one({"release_id": {"$in": rids}, "status": "installed"}, {"_id": 0}, sort=[("installed_at", -1)]) if rids else None


async def say(pid, text, **extra):
    await db.messages.insert_one({"id": new_id(), "project_id": pid, "role": "assistant", "content": text, "created_at": now(), **extra})


@router.get("/{pid}/play")
async def play_state(pid: str):
    m = await mod_or_404(pid)
    inst = await current_install(pid)
    lc = m.get("last_confirm") or {}
    v = m.get("verification") or {}
    loaded = bool(lc.get("loaded") or (v.get("checks") or {}).get("plugin_loaded"))
    stage = "confirmed" if m.get("build_status") == "verified" else "loaded" if inst and loaded else "installed" if inst \
        else "built" if m.get("last_build_job_id") else "planned"
    return {"stage": stage, "installed": bool(inst), "install_id": (inst or {}).get("install_id"), "built": bool(m.get("last_build_job_id")),
            "status": m.get("build_status"), "feature_checks": m.get("feature_checks") or [], "checking": lc.get("state") == "checking" and (lc.get("since") or "") > (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat(),
            "features": lc.get("features") or feature_results(m.get("feature_checks") or [], (m.get("verification") or {}).get("melty_checks"))}


@router.post("/{pid}/play")
async def play(pid: str):
    m = await mod_or_404(pid)
    await adapters.reject_unverified_host(m["host"], m.get("device_id"))
    if not m.get("last_build_job_id"):
        raise HTTPException(400, "Copilot hasn't built this mod on your PC yet")
    d = await pc_for(m)
    rel = await db.releases.find_one({"project_id": pid, "version_id": m.get("current_version_id")}, {"_id": 0})
    if not rel:
        n = await db.releases.count_documents({"project_id": pid})
        rel = await packages.create_release(pid, packages.ReleaseIn(version=f"0.{n + 1}.0", notes="Installed from Copilot"))
    out = await packages.install(rel["id"], packages.InstallIn(device_id=d["id"], launch=True))
    await say(pid, "Installing it in your game and starting the game. Try the new features, then tap “Check it worked”.")
    return out


async def _finish_check(pid, jid):
    j = await wait_job(jid, 600)
    m = await db.mods.find_one({"id": pid}, {"_id": 0, "files": 0})
    r = j.get("result") or {}
    checks = r.get("checks") or []
    names = m.get("feature_checks") or sorted({c["name"] for c in checks})
    feats = feature_results(names, checks)
    ok = j["status"] == "done" and confirmed(names, checks)
    await db.mods.update_one({"id": pid}, {"$set": {"last_confirm": {"state": "done", "at": now(), "features": feats, "ok": ok,
                                                                     "log_tail": (r.get("log_tail") or "")[-6000:], "loaded": bool(r.get("mod_loaded"))},
                                                    "build_status": "verified" if ok else ("built" if m.get("build_status") == "verified" else m.get("build_status"))}})
    if j["status"] == "cancelled":
        txt = "The log check wasn't allowed on your PC, so nothing was checked. Tap “Check it worked” again and choose Allow."
    elif j["status"] != "done":
        txt = "I couldn't read the game's log from your PC. Make sure MELTY Companion is running and try again."
    elif "checks" not in r:
        txt = "Your PC's MELTY Companion is too old to read the game's log. Close it and start it again from the desktop shortcut — it updates itself — then check again."
    elif not checks:
        txt = "I didn't find any sign of the mod in the game's log. Start the game with the mod installed, play a bit, then check again."
    elif ok:
        txt = "Confirmed in your game — every feature reported back working."
    else:
        miss = [f["name"].replace("_", " ") for f in feats if not f["seen"]]
        bad = [f["name"].replace("_", " ") for f in feats if f["seen"] and not f["pass"]]
        txt = "Not confirmed yet." + (f" Not seen in the game yet: {', '.join(miss)} — play the part where it should happen." if miss else "") + \
              (f" Not working: {', '.join(bad)}. Say “fix it” and I'll repair it using what the game reported." if bad else "")
    await say(pid, txt, features=feats)


@router.post("/{pid}/confirm")
async def confirm(pid: str):
    m = await mod_or_404(pid)
    d = await pc_for(m)
    j = await enqueue(d["id"], "collect_logs", {"host_name": m["host"]["name"], "slug": m["slug"], "toolchain": m.get("toolchain")}, pid,
                      label=f"Check {m['title']} in the game's log")
    await db.mods.update_one({"id": pid}, {"$set": {"last_confirm": {**(m.get("last_confirm") or {}), "state": "checking", "since": now()}}})
    t = asyncio.create_task(_finish_check(pid, j["id"]))
    t.add_done_callback(lambda f: f.exception() and logger.error("confirm failed: %s", f.exception()))
    return {"job_id": j["id"], "needs_approval": j["status"] == "needs_approval"}


@router.post("/{pid}/remove")
async def remove(pid: str):
    await mod_or_404(pid)
    inst = await current_install(pid)
    if not inst:
        raise HTTPException(404, "This mod isn't installed in your game")
    out = await packages.restore_install(inst["install_id"])
    await say(pid, "Removing the mod and putting your game's files back the way they were.")
    return out
