"""Asset Workshop: permission-aware asset jobs that run on the user's PC through the companion."""
import json
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core import db, now
import devices
from devices import enqueue, wait_job, online_device

router = APIRouter(prefix="/api/workshop")
ASSET_OPS = {
    "asset_scan": "Read game version, engine evidence and asset containers (read-only)",
    "asset_list": "List the files inside one asset container (read-only)",
    "asset_extract": "Copy selected files out of a game container into the MELTY workspace",
    "asset_convert": "Convert workspace files to PNG/WAV/JSON and write a compatibility report",
    "asset_validate": "Check converted files are valid",
    "asset_package": "Build a .pak from workspace files and verify it",
    "asset_test_package": "Check a built package opens correctly and matches what is installed",
    "asset_install": "Copy a package into the game's ~mods folder (backed up, journaled)",
    "asset_cleanup": "Delete temporary extraction data from the workspace",
}
ALWAYS_ASK = {"asset_install"}
UNSUPPORTED = {"unsupported", "blocked", "possible_not_implemented", "unsupported_by_toolkit", "blocked_by_protection", "impossible"}


def state_of(j: dict) -> dict:
    s, r = j["status"], j.get("result") or {}
    if s == "needs_approval":
        st = "Permission Required"
    elif s == "queued":
        st = "Pending"
    elif s == "running":
        st = "Running"
    elif s == "cancelled":
        st, r = "Failed", {**r, "error": r.get("error") or "Cancelled before it ran"}
    elif s == "failed":
        st = "Permission Required" if r.get("state") == "permission" else ("Unsupported" if r.get("state") in UNSUPPORTED else "Failed")
    else:
        st = "Completed"
        if j["op"] == "asset_extract" and not r.get("extracted") and r.get("problems"):
            st = "Unsupported" if all(p.get("state") in UNSUPPORTED for p in r["problems"]) else "Failed"
        if j["op"] == "asset_convert" and r.get("reports") and not any(x.get("converted") for x in r["reports"]):
            st = "Failed" if any(x.get("error") for x in r["reports"]) else "Unsupported"
        if j["op"] == "asset_validate" and not r.get("all_ok"):
            st = "Failed"
    return {"state": st, "why": r.get("error")}


async def device_or_404(device_id: Optional[str] = None):
    d = await online_device(device_id)
    if not d:
        raise HTTPException(409, "Your PC is offline. Start the MELTY Companion, then try again.")
    return d


async def game_or_404(device_id: str, install_dir: str):
    g = await db.games.find_one({"device_id": device_id, "install_dir": install_dir}, {"_id": 0})
    if not g:
        raise HTTPException(404, "That game is not in this PC's detected games. Run Detect games first.")
    return g


async def granted(device_id, install_dir) -> bool:
    return bool(await db.asset_grants.find_one({"device_id": device_id, "install_dir": install_dir}))


async def submit(op: str, install_dir: str, params: dict, device_id=None, project_id=None, generation_id=None) -> dict:
    d = await device_or_404(device_id)
    g = await game_or_404(d["id"], install_dir)
    status = None
    if op in ALWAYS_ASK or (op == "asset_extract" and not await granted(d["id"], install_dir)):
        status = "needs_approval"
    p = {"install_dir": install_dir, "name": g["name"], **params}
    j = await enqueue(d["id"], op, p, project_id, generation_id, f"{ASSET_OPS[op].split(' (')[0]} — {g['name']}", force_status=status)
    return {**j, **state_of(j)}


async def latest_scan(device_id, install_dir):
    j = await db.jobs.find_one({"device_id": device_id, "op": "asset_scan", "status": "done", "params.install_dir": install_dir},
                               {"_id": 0}, sort=[("created_at", -1)])
    return (j or {}).get("result")


def public_job(j):
    r = j.get("result") or {}
    return {k: j.get(k) for k in ("id", "op", "label", "status", "created_at", "finished_at", "progress", "progress_msg", "log", "artifacts")} | \
        {"install_dir": (j.get("params") or {}).get("install_dir"), "params": {k: v for k, v in (j.get("params") or {}).items() if k not in ("paths", "files")},
         "count": len((j.get("params") or {}).get("paths") or (j.get("params") or {}).get("files") or []), "result": r, **state_of(j)}


# ---------- web routes ----------
class GameIn(BaseModel):
    install_dir: str
    device_id: Optional[str] = None


class ListIn(GameIn):
    container: str
    filter: str = ""
    offset: int = 0
    limit: int = 500


class ExtractIn(GameIn):
    container: str
    paths: List[str]


class ConvertIn(GameIn):
    files: List[str]
    dst_install_dir: Optional[str] = None
    analyze_only: bool = False


class FilesIn(GameIn):
    files: List[str]


class PackFile(BaseModel):
    src: str
    dest: str


class PackageIn(GameIn):
    package_name: str
    files: List[PackFile]


class PkgIn(GameIn):
    package: str


class CleanupIn(GameIn):
    what: List[str] = ["extracted", "converted", "analysis"]


class RollbackIn(BaseModel):
    install_id: str
    device_id: Optional[str] = None


@router.get("/games")
async def games(device_id: Optional[str] = None):
    d = await online_device(device_id) or await db.devices.find_one({"revoked": {"$ne": True}, **({"id": device_id} if device_id else {})}, {"_id": 0}, sort=[("last_seen", -1)])
    if not d:
        return {"device": None, "games": []}
    out = []
    async for g in db.games.find({"device_id": d["id"]}, {"_id": 0}).sort("name", 1):
        if devices.NOT_GAME.search(g.get("name") or ""):
            continue
        out.append({**g, "scan": await latest_scan(d["id"], g["install_dir"]), "extract_granted": await granted(d["id"], g["install_dir"])})
    ver = (d.get("status") or {}).get("version") or d.get("companion_version") or "0"
    return {"device": {"id": d["id"], "hostname": d.get("hostname"), "online": bool(await online_device(d["id"])), "version": ver,
                       "asset_tools": tuple(int(x) for x in ver.split(".") if x.isdigit()) >= (0, 4, 0)}, "games": out}


@router.post("/detect")
async def detect(device_id: Optional[str] = None):
    d = await device_or_404(device_id)
    j = await enqueue(d["id"], "detect_games", {}, label="Detect installed games")
    return {**j, **state_of(j)}


@router.post("/scan")
async def scan(b: GameIn):
    return await submit("asset_scan", b.install_dir, {}, b.device_id)


@router.post("/list")
async def list_assets(b: ListIn):
    j = await submit("asset_list", b.install_dir, {"container": b.container, "filter": b.filter, "offset": b.offset, "limit": min(b.limit, 2000)}, b.device_id)
    j = await wait_job(j["id"], 90)
    if j["status"] != "done":
        raise HTTPException(400, (j.get("result") or {}).get("error") or "Listing timed out — is the companion running?")
    return j["result"]


@router.post("/extract")
async def extract(b: ExtractIn):
    if not b.paths:
        raise HTTPException(400, "Pick at least one file")
    return await submit("asset_extract", b.install_dir, {"container": b.container, "paths": b.paths[:2000]}, b.device_id)


async def engine_of(device_id, install_dir):
    s = await latest_scan(device_id, install_dir) if install_dir else None
    return f"UE {s['engine_version']}" if s and s.get("engine_version") else None


@router.post("/convert")
async def convert(b: ConvertIn):
    d = await device_or_404(b.device_id)
    return await submit("asset_convert", b.install_dir, {"files": b.files[:500], "analyze_only": b.analyze_only,
                                                         "src_engine": await engine_of(d["id"], b.install_dir),
                                                         "dst_engine": await engine_of(d["id"], b.dst_install_dir)}, b.device_id)


@router.post("/validate")
async def validate(b: FilesIn):
    return await submit("asset_validate", b.install_dir, {"files": b.files[:500]}, b.device_id)


@router.post("/package")
async def package(b: PackageIn):
    if not b.files:
        raise HTTPException(400, "Pick files to package")
    return await submit("asset_package", b.install_dir, {"package_name": b.package_name, "files": [f.model_dump() for f in b.files]}, b.device_id)


@router.post("/test-package")
async def test_package(b: PkgIn):
    return await submit("asset_test_package", b.install_dir, {"package": b.package}, b.device_id)


@router.post("/install")
async def install(b: PkgIn):
    return await submit("asset_install", b.install_dir, {"package": b.package}, b.device_id)


@router.post("/rollback")
async def rollback(b: RollbackIn):
    d = await device_or_404(b.device_id)
    j = await enqueue(d["id"], "uninstall_package", {"install_id": b.install_id}, label="Roll back a mod install")
    return {**j, **state_of(j)}


@router.post("/cleanup")
async def cleanup(b: CleanupIn):
    return await submit("asset_cleanup", b.install_dir, {"what": b.what}, b.device_id)


@router.get("/ops")
async def ops(install_dir: Optional[str] = None, device_id: Optional[str] = None, limit: int = 40):
    q = {"op": {"$in": list(ASSET_OPS) + ["detect_games", "uninstall_package"]}}
    if device_id:
        q["device_id"] = device_id
    if install_dir:
        q["params.install_dir"] = install_dir
    return [public_job(j) async for j in db.jobs.find(q, {"_id": 0}).sort("created_at", -1).limit(min(limit, 200))]


@router.post("/grants/revoke")
async def revoke(b: GameIn):
    await db.asset_grants.delete_many({"install_dir": b.install_dir, **({"device_id": b.device_id} if b.device_id else {})})
    return {"ok": True}


async def on_approve(j: dict):
    if j["op"] == "asset_extract":
        await db.asset_grants.update_one({"device_id": j["device_id"], "install_dir": j["params"]["install_dir"]},
                                         {"$set": {"device_id": j["device_id"], "install_dir": j["params"]["install_dir"], "granted_at": now()}},
                                         upsert=True)


# ---------- AI agent tools ----------
def _s(t):
    return {"type": "string", "description": t}


GAME = {"install_dir": _s("Game folder exactly as returned by detect_game_installations")}
AGENT_TOOLS = [
    ("detect_game_installations", "Scan the user's PC for installed games (Steam, Epic, GOG, Microsoft Store/Xbox, folders).", {}, []),
    ("inspect_game_files", "Read-only scan of a game's folder: store, version, executable and asset containers.", GAME, ["install_dir"]),
    ("identify_engine_version", "Engine and exact build from verified evidence (exe build tag, file version, container formats).", GAME, ["install_dir"]),
    ("inspect_asset_containers", "List .pak/.utoc containers with format version, encryption, compression and file types.", GAME, ["install_dir"]),
    ("list_available_assets", "List files inside one container (filter by text, e.g. '.cfg' or 'Weapons').",
     {**GAME, "container": _s("Full container path from inspect_asset_containers"), "filter": _s("optional text filter")}, ["install_dir", "container"]),
    ("extract_selected_assets", "Copy chosen files out of a container into the MELTY workspace. Asks the user once per game. Never decrypts.",
     {**GAME, "container": _s("container path"), "paths": {"type": "array", "items": {"type": "string"}}}, ["install_dir", "container", "paths"]),
    ("analyze_asset_compatibility", "Report what each extracted file is and whether it can be reused, converted or must be rebuilt.",
     {**GAME, "files": {"type": "array", "items": {"type": "string"}, "description": "workspace paths from extract"},
      "dst_install_dir": _s("destination game folder (optional)")}, ["install_dir", "files"]),
    ("convert_supported_asset", "Convert extracted files to PNG / WAV / JSON with a compatibility report per file.",
     {**GAME, "files": {"type": "array", "items": {"type": "string"}}, "dst_install_dir": _s("destination game folder (optional)")}, ["install_dir", "files"]),
    ("validate_converted_asset", "Verify converted output files are valid.", {**GAME, "files": {"type": "array", "items": {"type": "string"}}}, ["install_dir", "files"]),
    ("build_mod_package", "Build a .pak for the destination game from workspace files (your changes/authorised files only) and verify it.",
     {**GAME, "package_name": _s("short name"), "files": {"type": "array", "items": {"type": "object", "properties": {"src": _s("workspace path"), "dest": _s("path inside the game, e.g. Stalker2/Content/GameLite/...")}}}},
     ["install_dir", "package_name", "files"]),
    ("test_mod_package", "Check a built package opens, is loadable without keys and matches what is installed.", {**GAME, "package": _s("package path")}, ["install_dir", "package"]),
    ("install_mod_package", "Install a built package into the game's ~mods folder. Always asks the user first; fully reversible.", {**GAME, "package": _s("package path")}, ["install_dir", "package"]),
    ("trainer_controls", "Show the Trainer switches for a game and their real status (Active only when the game confirmed it).", GAME, ["install_dir"]),
    ("trainer_set", "Turn trainer switches on/off or set slider values in the running game, e.g. {'super_speed': {'on': true, 'value': 2}}. Merges with current settings.",
     {**GAME, "features": {"type": "object"}}, ["install_dir", "features"]),
    ("rollback_mod_installation", "Undo an install using its journal (restores every changed file).", {"install_id": _s("install id")}, ["install_id"]),
]
TOOLS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object", "properties": p, "required": r}}}
         for n, d, p, r in AGENT_TOOLS]
NAMES = {t[0] for t in AGENT_TOOLS}
SCAN_VIEW = {"inspect_game_files": ("name", "install_dir", "store", "store_version", "package_name", "exe", "exe_version", "engine", "engine_version", "paks_dirs", "inventory", "sdk_candidates", "workspace"),
             "identify_engine_version": ("engine", "engine_version", "engine_version_note", "exe", "exe_version", "store", "store_version", "evidence"),
             "inspect_asset_containers": ("containers", "oodle_dll", "inventory")}


def _trim(obj, n=12000):
    t = json.dumps(obj, default=str)
    return t if len(t) <= n else t[:n] + "…(truncated)"


async def agent_tool(name, args, mod, gid, log):
    did = mod.get("device_id")
    d = await online_device(did)
    if not d:
        return "ERROR: the user's PC is offline, so local game files cannot be reached. Say so plainly."

    async def run(op, install_dir, params, timeout=900):
        try:
            j = await submit(op, install_dir, params, d["id"], mod["id"], gid)
        except HTTPException as e:
            return None, f"ERROR: {e.detail}"
        if j["status"] == "needs_approval":
            await log(gid, f"Waiting for your permission in Asset Workshop: {j['label']}", "warn")
        j = await wait_job(j["id"], timeout)
        return j, None

    if name == "detect_game_installations":
        j = await enqueue(d["id"], "detect_games", {}, mod["id"], gid, "Detect installed games")
        j = await wait_job(j["id"], 300)
        return _trim([{k: g.get(k) for k in ("name", "install_dir", "source", "engine", "game_version", "exe")} for g in (j.get("result") or {}).get("games", [])])
    if name in ("trainer_controls", "trainer_set"):
        import trainer
        try:
            if name == "trainer_set":
                cur = await trainer.trainer_game(args.get("install_dir", ""), d["id"])
                feats = {f["key"]: {"on": f["on"], "value": f["value"]} for f in cur["features"] if f["on"]} | (args.get("features") or {})
                await trainer.apply(trainer.ApplyIn(install_dir=args["install_dir"], device_id=d["id"], features=feats))
                await log(gid, "Trainer settings sent to the game", "info")
            t = await trainer.trainer_game(args.get("install_dir", ""), d["id"])
        except HTTPException as e:
            return f"ERROR: {e.detail}"
        return _trim({k: t.get(k) for k in ("game", "supported", "tool_ok", "installed", "in_game")} |
                     {"features": [{k: f.get(k) for k in ("key", "label", "status", "on", "value", "why")} for f in t.get("features", [])]})
    if name == "rollback_mod_installation":
        j = await enqueue(d["id"], "uninstall_package", {"install_id": args.get("install_id", "")}, mod["id"], gid, "Roll back a mod install")
        j = await wait_job(j["id"], 300)
        return _trim({"state": state_of(j)["state"], "result": j.get("result")})
    inst = args.get("install_dir", "")
    if name in SCAN_VIEW:
        j, err = await run("asset_scan", inst, {}, 600)
        if err:
            return err
        r = j.get("result") or {}
        return _trim({"state": state_of(j)["state"], **{k: r.get(k) for k in SCAN_VIEW[name]}, "error": r.get("error")})
    eng = lambda x: engine_of(d["id"], x)  # noqa: E731
    op, params = {
        "list_available_assets": ("asset_list", {"container": args.get("container"), "filter": args.get("filter", ""), "limit": 300}),
        "extract_selected_assets": ("asset_extract", {"container": args.get("container"), "paths": (args.get("paths") or [])[:500]}),
        "analyze_asset_compatibility": ("asset_convert", {"files": args.get("files") or [], "analyze_only": True}),
        "convert_supported_asset": ("asset_convert", {"files": args.get("files") or []}),
        "validate_converted_asset": ("asset_validate", {"files": args.get("files") or []}),
        "build_mod_package": ("asset_package", {"package_name": args.get("package_name"), "files": args.get("files") or []}),
        "test_mod_package": ("asset_test_package", {"package": args.get("package")}),
        "install_mod_package": ("asset_install", {"package": args.get("package")}),
    }[name]
    if op == "asset_convert":
        params.update(src_engine=await eng(inst), dst_engine=await eng(args.get("dst_install_dir")))
    j, err = await run(op, inst, params)
    if err:
        return err
    st = state_of(j)
    await log(gid, f"{name}: {st['state']}" + (f" — {st['why']}" if st["why"] else ""), "info" if st["state"] == "Completed" else "warn")
    return _trim({"state": st["state"], "result": j.get("result"), "timed_out": j.get("timed_out", False)})
