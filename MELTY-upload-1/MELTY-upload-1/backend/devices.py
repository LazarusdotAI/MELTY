"""Companion pairing, device registry and the restricted job queue."""
import re
import unicodedata
import asyncio
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel, Field
from core import db, now, new_id
from assets import put_object, get_object, APP_NAME
import adapters

OPS = {
    "doctor": "Check Python, .NET SDK and companion health",
    "detect_games": "Scan Steam/Epic/GOG libraries and identify engines & versions",
    "inspect_game": "Read installation metadata and loader state without changing game files",
    "build_mod": "Compile a mod project with the .NET SDK in the companion workspace",
    "test_mod": "Install a dev build, launch the game, read logs, screenshot, then restore files",
    "install_package": "Install a released package (checksums verified, journaled)",
    "uninstall_package": "Restore every file changed by an install from its journal",
    "launch_game": "Launch an installed game with the package's launch settings",
    "stop_game": "Stop a game process started by the companion",
    "collect_logs": "Read loader and Unity logs for a game",
    "screenshot": "Capture the primary screen",
    "asset_scan": "Read game version, engine evidence and asset containers (read-only)",
    "asset_list": "List the files inside one asset container (read-only)",
    "asset_extract": "Copy selected files out of a game container into the MELTY workspace",
    "asset_convert": "Convert workspace files and write a compatibility report",
    "asset_validate": "Check converted files are valid",
    "asset_package": "Build a .pak from workspace files and verify it",
    "asset_test_package": "Check a built package opens correctly",
    "asset_install": "Copy a package into the game's ~mods folder (backed up, journaled)",
    "asset_cleanup": "Delete temporary extraction data from the workspace",
    "trainer_install": "Install the MELTY trainer script into a game (backed up, removable)",
    "trainer_apply": "Send trainer settings to the game's trainer script",
    "trainer_status": "Read what the game's trainer script reports",
    "detect_tools": "Check which modding tools are installed in a game (read-only)",
    "setup_tools": "Download and install modding tools into a game from their official release pages (backed up, removable)",
}
SELF_GATED = {k for k in OPS if k.startswith("asset_")} | {"setup_tools", "detect_tools", "trainer_install", "trainer_apply", "trainer_status"}
ONLINE_SECONDS = 30

web = APIRouter(prefix="/api")
comp = APIRouter(prefix="/api/companion")


def _hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def online(d: dict) -> bool:
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(d.get("last_seen")) < timedelta(seconds=ONLINE_SECONDS)
    except Exception:
        return False


def public_device(d: dict) -> dict:
    d = {k: v for k, v in d.items() if k != "token_hash"}
    d["online"] = online(d)
    return d


async def auth(token: Optional[str]) -> dict:
    if not token:
        raise HTTPException(401, "Missing device token")
    d = await db.devices.find_one({"token_hash": _hash(token), "revoked": {"$ne": True}}, {"_id": 0})
    if not d:
        raise HTTPException(401, "Unknown or revoked device")
    return d


async def validate_host_job(device_id: str, op: str, params: dict, project_id=None):
    if op not in ("build_mod", "test_mod", "install_package", "launch_game"):
        return
    host = (params.get("manifest") or {}).get("host") or {}
    await adapters.reject_unverified_host(host, device_id)
    await adapters.reject_unverified_host({"name": params.get("host_name")}, device_id)
    pid = project_id or params.get("project_id")
    if pid:
        mod = await db.mods.find_one({"id": pid}, {"_id": 0})
        if mod:
            await adapters.reject_unverified_host(mod.get("host") or {}, device_id)


async def enqueue(device_id: str, op: str, params: dict, project_id=None, generation_id=None, label="", force_status=None) -> dict:
    await validate_host_job(device_id, op, params, project_id)
    if op == "inspect_game" and params.get("metadata_only"):
        g = await cold_war_game(device_id, params.get("install_dir", ""))
        if g["name"] != params.get("name"):
            raise HTTPException(400, "Installation and game name do not match")
    if op not in OPS:
        raise HTTPException(400, f"Operation '{op}' is not allowed")
    d = await db.devices.find_one({"id": device_id, "revoked": {"$ne": True}}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Device not found")
    job = {"id": new_id(), "device_id": device_id, "op": op, "params": params, "label": label or OPS[op],
           "status": force_status or ("queued" if op in d.get("approved_ops", []) or op in SELF_GATED else "needs_approval"),
           "project_id": project_id, "generation_id": generation_id, "result": None, "log": "", "artifacts": [],
           "created_at": now()}
    await db.jobs.insert_one(dict(job))
    return job


async def wait_job(jid: str, timeout: float) -> dict:
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        j = await db.jobs.find_one({"id": jid}, {"_id": 0})
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        await asyncio.sleep(2)
    await db.jobs.update_one({"id": jid, "status": {"$in": ["queued", "needs_approval"]}}, {"$set": {"status": "cancelled"}})
    return await db.jobs.find_one({"id": jid}, {"_id": 0}) | {"timed_out": True}


async def online_device(device_id: Optional[str]):
    q = {"revoked": {"$ne": True}}
    if device_id:
        q["id"] = device_id
    async for d in db.devices.find(q, {"_id": 0}).sort("last_seen", -1):
        if online(d):
            return d
    return None


# ---------- web-facing ----------
class OpsIn(BaseModel):
    approved_ops: list


class JobIn(BaseModel):
    op: str
    params: dict = {}


@web.get("/companion/ops")
async def ops():
    return OPS


@web.post("/devices/pairing-code")
async def pairing_code():
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    exp = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    await db.pairing.insert_one({"code": code, "expires_at": exp, "used": False, "created_at": now()})
    return {"code": code, "expires_at": exp}


@web.get("/devices")
async def devices():
    return [public_device(d) for d in await db.devices.find({"revoked": {"$ne": True}}, {"_id": 0}).to_list(50)]


@web.patch("/devices/{did}")
async def set_ops(did: str, b: OpsIn):
    allowed = [o for o in b.approved_ops if o in OPS]
    if not await db.devices.find_one({"id": did}):
        raise HTTPException(404, "Device not found")
    await db.devices.update_one({"id": did}, {"$set": {"approved_ops": allowed}})
    return {"approved_ops": allowed}


@web.delete("/devices/{did}")
async def revoke(did: str):
    await db.devices.update_one({"id": did}, {"$set": {"revoked": True}})
    await db.jobs.update_many({"device_id": did, "status": {"$in": ["queued", "needs_approval"]}},
                              {"$set": {"status": "cancelled"}})
    return {"ok": True}


@web.get("/devices/{did}/games")
async def device_games(did: str):
    games = await db.games.find({"device_id": did}, {"_id": 0, "managed": 0}).sort("name", 1).to_list(2000)
    return [adapters.unverified_host_status(g) for g in games if not NOT_GAME.search(g.get("name") or "")]


@web.get("/games/details")
async def game_details(device_id: str, install_dir: str):
    g = await db.games.find_one({"device_id": device_id, "install_dir": install_dir}, {"_id": 0})
    if not g:
        raise HTTPException(404, "Game not found")
    g = adapters.unverified_host_status(g)
    a = await adapters.match(g)
    if not adapters.is_cold_war(g) and not adapters.is_wwii(g):
        g |= adapters.host_info(g, a)
    notes = await db.knowledge.find({"game": {"$regex": f"^{re.escape(g['name'])}$", "$options": "i"}}, {"_id": 0}).sort(
        "created_at", -1).to_list(30)
    mods = await db.mods.find({"$or": [{"host.name": g["name"]}, {"secondary.name": g["name"]}]},
                              {"_id": 0, "id": 1, "title": 1, "build_status": 1}).to_list(20)
    g["managed_count"] = len(g.pop("managed", []) or [])
    return {"game": g, "adapter": {k: a.get(k) for k in ("id", "name", "status", "loader", "integration_methods",
                                                         "target_framework", "doc_md")} if a else None,
            "notes": notes, "mods": mods, "buildable_host": bool(g.get("hostable"))}


class ColdWarCheckIn(BaseModel):
    device_id: str
    install_dir: str


class ColdWarVersionIn(ColdWarCheckIn):
    version: str = Field(max_length=80, pattern=r"^[^\x00-\x1f\x7f]*$")


async def cold_war_game(device_id: str, install_dir: str):
    g = await db.games.find_one({"device_id": device_id, "install_dir": install_dir}, {"_id": 0})
    if not g:
        raise HTTPException(404, "Detected game not found")
    if not adapters.is_cold_war(g):
        raise HTTPException(400, "This assessment is only for Black Ops Cold War")
    return g


@web.get("/games/cold-war/compatibility")
async def cold_war_compatibility(device_id: str, install_dir: str):
    return adapters.cold_war_report(await cold_war_game(device_id, install_dir))


@web.patch("/games/cold-war/version")
async def cold_war_version(b: ColdWarVersionIn):
    g = await cold_war_game(b.device_id, b.install_dir)
    if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in b.version):
        raise HTTPException(422, "Version must be a single line of visible text")
    version = b.version.strip() or None
    await db.games.update_one({"device_id": b.device_id, "install_dir": b.install_dir},
                              {"$set": {"cold_war_manual_version": version}})
    return adapters.cold_war_report({**g, "cold_war_manual_version": version})


@web.post("/games/cold-war/check")
async def cold_war_check(b: ColdWarCheckIn):
    g = await cold_war_game(b.device_id, b.install_dir)
    d = await online_device(b.device_id)
    if not d:
        raise HTTPException(409, "PC offline. Start your paired companion to read installation metadata. Saved details remain available.")
    ver = (d.get("status") or {}).get("version") or d.get("companion_version") or "0"
    if tuple(int(x) for x in re.findall(r"\d+", ver)[:3]) < (0, 3, 0):
        raise HTTPException(409, "Companion 0.3.0 or newer is required. Download the companion update from My PC, replace your current script, then restart it and retry. No game tools are installed by this check.")
    return await enqueue(b.device_id, "inspect_game", {"name": g["name"], "install_dir": g["install_dir"],
                         "metadata_only": True}, label="Cold War read-only compatibility check — no game changes")


@web.post("/devices/{did}/jobs")
async def create_job(did: str, b: JobIn):
    return await enqueue(did, b.op, b.params)


@web.get("/jobs")
async def jobs(device_id: Optional[str] = None, project_id: Optional[str] = None):
    q = {k: v for k, v in {"device_id": device_id, "project_id": project_id}.items() if v}
    return await db.jobs.find(q, {"_id": 0, "params.files": 0}).sort("created_at", -1).to_list(100)


@web.get("/jobs/{jid}")
async def get_job(jid: str):
    j = await db.jobs.find_one({"id": jid}, {"_id": 0, "params.files": 0, "params.manifest": 0})
    if not j:
        raise HTTPException(404, "Job not found")
    return j


@web.post("/jobs/{jid}/approve")
async def approve(jid: str):
    j = await db.jobs.find_one_and_update({"id": jid, "status": "needs_approval"}, {"$set": {"status": "queued", "approved_at": now()}}, projection={"_id": 0})
    if j:
        import workshop
        await workshop.on_approve(j)
    return {"ok": True}


@web.post("/jobs/{jid}/cancel")
async def cancel_job(jid: str):
    await db.jobs.update_one({"id": jid, "status": {"$in": ["queued", "needs_approval"]}}, {"$set": {"status": "cancelled"}})
    return {"ok": True}


@web.get("/jobs/{jid}/artifact/{name}")
async def artifact(jid: str, name: str):
    j = await db.jobs.find_one({"id": jid}, {"_id": 0})
    a = next((x for x in (j or {}).get("artifacts", []) if x["name"] == name), None)
    if not a:
        raise HTTPException(404, "Artifact not found")
    data, ct = await asyncio.to_thread(get_object, a["storage_path"])
    return Response(data, media_type=a.get("content_type") or ct)


# ---------- companion-facing ----------
class PairIn(BaseModel):
    code: str
    hostname: str
    os: str
    companion_version: str


class BeatIn(BaseModel):
    status: dict = {}


class ResultIn(BaseModel):
    status: str
    result: dict = {}
    log: str = ""


@comp.post("/pair")
async def pair(b: PairIn):
    p = await db.pairing.find_one_and_update({"code": b.code.strip().upper(), "used": False}, {"$set": {"used": True}})
    if not p or datetime.fromisoformat(p["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(400, "Pairing code invalid or expired")
    token = secrets.token_urlsafe(32)
    did = new_id()
    await db.devices.insert_one({"id": did, "hostname": b.hostname[:80], "os": b.os[:80],
                                 "companion_version": b.companion_version[:20], "token_hash": _hash(token),
                                 "approved_ops": list(OPS.keys()), "status": {}, "last_seen": now(), "created_at": now()})
    return {"device_id": did, "token": token}


@comp.post("/heartbeat")
async def heartbeat(b: BeatIn, x_device_token: str = Header(None)):
    d = await auth(x_device_token)
    await db.devices.update_one({"id": d["id"]}, {"$set": {"last_seen": now(), "status": b.status}})
    return {"approved_ops": d.get("approved_ops", [])}


@comp.get("/jobs/next")
async def next_job(x_device_token: str = Header(None)):
    d = await auth(x_device_token)
    await db.devices.update_one({"id": d["id"]}, {"$set": {"last_seen": now()}})
    j = await db.jobs.find_one_and_update(
        {"device_id": d["id"], "status": "queued", "op": {"$in": list(set(d.get("approved_ops", [])) | SELF_GATED)}},
        {"$set": {"status": "running", "claimed_at": now()}}, sort=[("created_at", 1)], projection={"_id": 0})
    if j:
        try:
            await validate_host_job(d["id"], j["op"], j.get("params") or {}, j.get("project_id"))
        except HTTPException as e:
            await db.jobs.update_one({"id": j["id"]}, {"$set": {"status": "failed", "result": {"error": e.detail}, "finished_at": now()}})
            return {"job": None}
    return {"job": j}


class ProgressIn(BaseModel):
    pct: int = 0
    msg: str = ""


@comp.post("/jobs/{jid}/progress")
async def job_progress(jid: str, b: ProgressIn, x_device_token: str = Header(None)):
    d = await auth(x_device_token)
    await db.jobs.update_one({"id": jid, "device_id": d["id"], "status": "running"},
                             {"$set": {"progress": max(0, min(100, b.pct)), "progress_msg": b.msg[:200]}})
    return {"ok": True}


@comp.post("/jobs/{jid}/result")
async def job_result(jid: str, b: ResultIn, x_device_token: str = Header(None)):
    d = await auth(x_device_token)
    j = await db.jobs.find_one({"id": jid, "device_id": d["id"]}, {"_id": 0})
    if not j:
        raise HTTPException(404, "Job not found")
    status = "done" if b.status == "done" else "failed"
    await db.jobs.update_one({"id": jid}, {"$set": {"status": status, "result": b.result, "log": b.log[-20000:],
                                                   "finished_at": now(), "progress": 100 if status == "done" else j.get("progress")}})
    if j["op"] == "detect_games" and status == "done":
        await _store_games(d["id"], b.result.get("games", []))
    if j["op"] == "inspect_game" and status == "done":
        params = j.get("params") or {}
        query = {"device_id": d["id"], "name": params.get("name")}
        if params.get("install_dir"):
            query["install_dir"] = params["install_dir"]
        g = await db.games.find_one(query, {"_id": 0})
        if g and adapters.is_cold_war(g):
            fields = {k: b.result[k][:500] if isinstance(b.result[k], str) else None for k in
                      ("executable_version", "inspection_note") if k in b.result}
            fields.update({k: b.result[k] if isinstance(b.result[k], bool) else None
                           for k in ("installation_exists", "executable_exists") if k in b.result})
            if isinstance(b.result.get("exe"), str) and b.result["exe"].lower() == "blackopscoldwar.exe":
                fields["exe"] = b.result["exe"]
            if fields:
                fields["compatibility_checked_at"] = now()
                await db.games.update_one({"device_id": d["id"], "install_dir": g["install_dir"]}, {"$set": fields})
        else:
            await db.games.update_one({"device_id": d["id"], "install_dir": b.result.get("install_dir")},
                                      {"$set": {"managed": b.result.get("managed", []), "inspected_at": now(),
                                                "loader_installed": b.result.get("loader_installed")}})
    if j["op"] in ("setup_tools", "detect_tools") and status == "done" and b.result.get("install_dir"):
        g = await db.games.find_one({"device_id": d["id"], "install_dir": b.result["install_dir"]}, {"_id": 0})
        if g:
            g["frameworks"] = b.result.get("frameworks", [])
            a = await adapters.match(g)
            await db.games.update_one({"device_id": d["id"], "install_dir": g["install_dir"]},
                                      {"$set": {"frameworks": g["frameworks"], **adapters.host_info(g, a)}})
    if j["op"] in ("install_package", "uninstall_package") and status == "done":
        await _store_install(d["id"], j, b.result)
    return {"ok": True}


class EngineIn(BaseModel):
    device_id: str
    install_dir: str
    engine: str
    name: Optional[str] = None


@web.post("/games/manual")
async def manual_game(b: EngineIn):
    if not await db.adapters.find_one({"kind": "engine", "engine": b.engine}):
        raise HTTPException(400, "Unknown engine")
    g = await db.games.find_one({"device_id": b.device_id, "install_dir": b.install_dir}, {"_id": 0})
    if not g and not b.name:
        raise HTTPException(400, "Give the game a name")
    g = {**(g or {"name": b.name, "source": "manual", "install_dir": b.install_dir, "device_id": b.device_id}), "engine": b.engine, "manual_engine": b.engine}
    a = await adapters.match(g)
    g |= {"adapter_id": a.get("id"), "adapter_status": a.get("status"), "detected_at": now(), **adapters.host_info(g, a)}
    await db.games.update_one({"device_id": b.device_id, "install_dir": b.install_dir}, {"$set": g}, upsert=True)
    return g


class ToolsIn(BaseModel):
    device_id: str
    install_dir: str
    tools: list = []


@web.post("/games/tools")
async def game_tools(b: ToolsIn):
    g = await db.games.find_one({"device_id": b.device_id, "install_dir": b.install_dir}, {"_id": 0})
    if not g:
        raise HTTPException(404, "Game not found on this PC")
    a = await adapters.match(g)
    spec = {t["key"]: t for t in a.get("frameworks", [])}
    bad = [t for t in b.tools if t not in spec or not spec[t].get("repo")]
    if bad:
        raise HTTPException(400, f"These can't be installed automatically: {', '.join(bad)}")
    want = list(dict.fromkeys([n for t in b.tools for n in spec[t].get("needs", [])] + b.tools))
    params = {"install_dir": b.install_dir, "name": g["name"], "tools": [{"key": k, **{f: spec[k].get(f) for f in ("name", "repo", "marker")}} for k in want],
              "markers": {k: t["marker"] for k, t in spec.items() if t.get("marker")}}
    op = "setup_tools" if want else "detect_tools"
    return await enqueue(b.device_id, op, params, label=("Set up " + ", ".join(spec[k]["name"] for k in want)) if want else f"Check modding tools — {g['name']}",
                         force_status="needs_approval" if want else "queued")


class GamesIn(BaseModel):
    games: list


@comp.post("/games")
async def report_games(b: GamesIn, x_device_token: str = Header(None)):
    d = await auth(x_device_token)
    await _store_games(d["id"], b.games)
    return {"stored": len(b.games)}


NOT_GAME = re.compile(r"^(launcher|social club|unreal engine( \d.*)?|epic games launcher|.*\b(redistributables?|directx|easyanticheat|battleye|crash ?reporter|updater|uninstaller?|helper|service)s?)$", re.I)


async def _store_games(did: str, games: list):
    games = [g for g in games if not (g.get("source") in ("folder", "registry") and NOT_GAME.search(g.get("name") or ""))]
    keep = [g.get("install_dir") for g in games[:3000]]
    await db.games.delete_many({"device_id": did, "install_dir": {"$nin": keep}})
    await db.devices.update_one({"id": did}, {"$set": {"last_scan_at": now(), "game_count": len(keep)}})
    for g in games[:3000]:
        prev = await db.games.find_one({"device_id": did, "install_dir": g.get("install_dir")}, {"_id": 0, "manual_engine": 1}) or {}
        if prev.get("manual_engine") and g.get("engine") in (None, "unknown"):
            g = {**g, "engine": prev["manual_engine"], "manual_engine": prev["manual_engine"]}
        a = await adapters.match(g)
        metadata = {k: g[k] for k in ("executable_version", "installation_exists", "executable_exists", "inspection_note",
                    "campaign_exe", "multiplayer_exe", "campaign_executable_found", "wwii_mode") if k in g}
        g = {k: g.get(k) for k in ("name", "source", "steam_appid", "install_dir", "exe", "engine", "unity_version",
                                   "game_version", "loader_installed", "managed_dir", "company", "product", "game_folder",
                                   "sdk_installed", "store_locked", "ue4ss_installed", "frameworks", "engine_version", "manual_engine")}
        g |= {"device_id": did, "adapter_id": a.get("id"), "adapter_status": a.get("status"), "detected_at": now(),
              **metadata, **adapters.host_info(g, a)}
        await db.games.update_one({"device_id": did, "install_dir": g["install_dir"]}, {"$set": g}, upsert=True)


async def _store_install(did: str, job: dict, res: dict):
    if job["op"] == "install_package":
        await db.installs.update_one({"install_id": res.get("install_id")}, {"$set": {
            "install_id": res.get("install_id"), "device_id": did, "release_id": job["params"].get("release_id"),
            "name": job["params"].get("manifest", {}).get("name"), "host_dir": res.get("host_dir"),
            "files_created": res.get("created", 0), "files_replaced": res.get("replaced", 0),
            "status": "installed", "installed_at": now()}}, upsert=True)
    else:
        await db.installs.update_one({"install_id": job["params"].get("install_id")},
                                     {"$set": {"status": "restored", "restored_at": now(),
                                               "restore_report": res}})


@comp.post("/jobs/{jid}/artifact")
async def upload_artifact(jid: str, file: UploadFile = File(...), name: str = Form(...),
                          x_device_token: str = Header(None)):
    d = await auth(x_device_token)
    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "Artifact too large")
    ct = "image/png" if name.endswith(".png") else ("text/plain" if name.endswith((".log", ".txt")) else "application/octet-stream")
    res = await asyncio.to_thread(put_object, f"{APP_NAME}/artifacts/{d['id']}/{jid}/{new_id()}_{name}", data, ct)
    entry = {"name": name, "storage_path": res["path"], "size": len(data), "content_type": ct,
             "sha256": hashlib.sha256(data).hexdigest()}
    await db.jobs.update_one({"id": jid, "device_id": d["id"]}, {"$pull": {"artifacts": {"name": name}}})
    await db.jobs.update_one({"id": jid, "device_id": d["id"]}, {"$push": {"artifacts": entry}})
    return entry


@comp.get("/download")
async def download(path: str, x_device_token: str = Header(None)):
    await auth(x_device_token)
    if not path.startswith(f"{APP_NAME}/"):
        raise HTTPException(403, "Not allowed")
    data, ct = await asyncio.to_thread(get_object, path)
    return Response(data, media_type=ct)
