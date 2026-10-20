"""meltpack/1 packages: release building, explicit publishing, catalog, compatibility and install requests."""
from modagent import files_hash
import io
import json
import hashlib
import zipfile
import asyncio
import httpx
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from core import db, now, new_id
from assets import get_object
import adapters
from devices import enqueue, online_device

router = APIRouter(prefix="/api")
COMPAT_KEYS = ["install_launch", "singleplayer", "save_load", "mp_join", "mp_sync"]
COMPAT_LABEL = {"install_launch": "Installation & launch", "singleplayer": "Single-player gameplay",
                "save_load": "Saving & loading", "mp_join": "Multiplayer joining", "mp_sync": "Multiplayer state sync"}


async def loader_with_checksum(loader: dict) -> dict:
    if not loader:
        return None
    cached = await db.loader_cache.find_one({"url": loader["url"]}, {"_id": 0})
    if cached:
        return {**loader, "sha256": cached["sha256"], "size": cached["size"]}
    async with httpx.AsyncClient(follow_redirects=True, timeout=120) as c:
        r = await c.get(loader["url"])
        r.raise_for_status()
    sha = hashlib.sha256(r.content).hexdigest()
    await db.loader_cache.insert_one({"url": loader["url"], "sha256": sha, "size": len(r.content), "at": now()})
    return {**loader, "sha256": sha, "size": len(r.content)}


async def build_manifest(mod: dict, version: str, build_job: dict, mp: dict, notes: str) -> dict:
    dll = next((a for a in build_job.get("artifacts", []) if a["name"].endswith((".dll", ".u", ".zip"))), None)
    if not dll:
        raise HTTPException(400, "The last build produced no mod artifact")
    host_rec = await db.games.find_one({"device_id": mod.get("device_id"), "name": mod["host"]["name"]}, {"_id": 0}) or {}
    await adapters.reject_unverified_host(mod["host"], mod.get("device_id"))
    adapter = await adapters.match({"name": mod["host"]["name"], **host_rec})
    loader = await loader_with_checksum(adapter.get("loader"))
    tc = mod.get("toolchain") or "bepinex5-csharp"
    sec_env = {f"MELTY_SECONDARY_{i}_DIR": "{game:" + s["name"] + "}" for i, s in enumerate(mod.get("secondary", []))}
    if tc == "ue3-unrealscript":
        layout = {"install_root": "{docs}", "docs": adapter.get("docs_name"),
                  "files": [{"path": f"Published/BrewedPC/Script/{mod['slug']}.u", "storage_path": dll["storage_path"],
                             "sha256": dll["sha256"], "size": dll["size"]}],
                  "args": [f"{adapter.get('default_map') or 'KF-BioticsLab'}?Mutator={mod['slug']}.{mod['slug']}", "-log"]}
    elif tc == "cet-lua":
        layout = {"install_root": "{host}", "files": [{"path": "bin/x64/plugins/cyber_engine_tweaks/mods/", "kind": "zip", "storage_path": dll["storage_path"],
                                                       "sha256": dll["sha256"], "size": dll["size"]}], "args": []}
    elif tc == "ue4ss-lua":
        layout = {"install_root": "{exe_dir}", "files": [{"path": "Mods/", "kind": "zip", "storage_path": dll["storage_path"],
                                                          "sha256": dll["sha256"], "size": dll["size"]}], "args": []}
    else:
        layout = {"install_root": "{host}", "files": [{"path": f"BepInEx/plugins/{mod['slug']}/{mod['slug']}.dll",
                                                       "storage_path": dll["storage_path"], "sha256": dll["sha256"],
                                                       "size": dll["size"]}], "args": []}
    return {
        "toolchain": tc, "install_root": layout["install_root"], "docs": layout.get("docs"),
        "schema": "meltpack/1", "id": mod["slug"].lower(), "name": mod["title"], "version": version,
        "host": {"game": mod["host"]["name"], "steam_appid": host_rec.get("steam_appid"), "exe": host_rec.get("exe"),
                 "engine": host_rec.get("engine"), "supported_versions": [v for v in [host_rec.get("game_version")] if v]},
        "secondary": [{"game": s["name"], "role": s["role"], "env": f"MELTY_SECONDARY_{i}_DIR", "required": True,
                       "note": "Your own installation is used at runtime; no files from it are shipped."}
                      for i, s in enumerate(mod.get("secondary", []))],
        "dependencies": [{**loader, "dest": "{host}", "kind": "zip"}] if loader else [],
        "files": layout["files"],
        "launch": {"exe": host_rec.get("exe"), "args": layout["args"], "steam_appid": host_rec.get("steam_appid"), "env": sec_env},
        "multiplayer": mp, "first_launch_notes": notes,
        "conflicts": "Existing files are backed up before replacement and restored on uninstall (install journal).",
    }


class ReleaseIn(BaseModel):
    version: str
    notes: str = ""
    multiplayer_supported: bool = False
    multiplayer_notes: str = "Single-player only — multiplayer not implemented or not verified."


class PublishIn(BaseModel):
    publish: bool


class CompatIn(BaseModel):
    key: str
    status: str
    note: str = ""
    game_version: str = ""


class InstallIn(BaseModel):
    device_id: Optional[str] = None
    launch: bool = True


@router.post("/mods/{pid}/releases")
async def create_release(pid: str, b: ReleaseIn):
    mod = await db.mods.find_one({"id": pid}, {"_id": 0})
    if not mod:
        raise HTTPException(404, "Mod not found")
    await adapters.reject_unverified_host(mod["host"], mod.get("device_id"))
    if not mod.get("last_build_job_id") or mod.get("dirty") or (mod.get("build_hash") and mod["build_hash"] != files_hash(mod.get("files") or [])):
        raise HTTPException(400, "Build the current version successfully (and save a checkpoint) before releasing")
    job = await db.jobs.find_one({"id": mod["last_build_job_id"]}, {"_id": 0})
    manifest = await build_manifest(mod, b.version, job, {"supported": b.multiplayer_supported, "notes": b.multiplayer_notes}, b.notes)
    v = mod.get("verification") or {}
    gv = (v.get("game_version") or (manifest["host"]["supported_versions"] or ["unknown"])[0])
    compat = {gv: {k: {"status": "untested", "source": None, "note": "", "at": None} for k in COMPAT_KEYS}}
    if v.get("passed"):
        compat[gv]["install_launch"] = {"status": "verified", "source": "automated in-game test", "note": "",
                                        "at": v.get("at"), "job_id": v.get("job_id")}
    rid = new_id()
    rel = {"id": rid, "project_id": pid, "version": b.version, "manifest": manifest, "compat": compat,
           "version_id": mod.get("current_version_id"), "published": False, "title": mod["title"],
           "spec_md": mod.get("spec_md", ""), "host": mod["host"]["name"],
           "secondary": [s["name"] for s in mod.get("secondary", [])], "created_at": now()}
    await db.releases.insert_one(dict(rel))
    return rel


@router.get("/mods/{pid}/releases")
async def list_releases(pid: str):
    return await db.releases.find({"project_id": pid}, {"_id": 0}).sort("created_at", -1).to_list(50)


async def get_release(rid: str):
    r = await db.releases.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Release not found")
    return r


@router.get("/releases/{rid}")
async def release_public(rid: str):
    r = await db.releases.find_one({"id": rid}, {"_id": 0, "manifest.files.storage_path": 0}) or await get_release(rid)
    r["hosting_blocked_reason"] = None
    try:
        await adapters.reject_unverified_host(r["manifest"]["host"])
    except HTTPException as e:
        r["hosting_blocked_reason"] = e.detail
    return r


@router.post("/releases/{rid}/publish")
async def publish(rid: str, b: PublishIn):
    r = await get_release(rid)
    if b.publish:
        await adapters.reject_unverified_host(r["manifest"]["host"])
    await db.releases.update_one({"id": rid}, {"$set": {"published": b.publish, "published_at": now() if b.publish else None}})
    return {"published": b.publish}


@router.patch("/releases/{rid}/compat")
async def set_compat(rid: str, b: CompatIn):
    if b.key not in COMPAT_KEYS or b.status not in ("verified", "failed", "untested", "partial"):
        raise HTTPException(400, "Invalid compatibility entry")
    r = await get_release(rid)
    gv = b.game_version or next(iter(r["compat"].keys()))
    entry = ({"status": "untested", "source": None, "note": "", "at": None} if b.status == "untested"
             else {"status": b.status, "source": "manual playtest", "note": b.note[:500], "at": now()})
    await db.releases.update_one({"id": rid}, {"$set": {f"compat.{gv}.{b.key}": entry}})
    return await release_public(rid)


@router.get("/catalog")
async def catalog():
    return await db.releases.find({"published": True}, {"_id": 0, "manifest.files.storage_path": 0}).sort(
        "published_at", -1).to_list(200)


@router.get("/compat/keys")
async def compat_keys():
    return COMPAT_LABEL


@router.post("/releases/{rid}/install")
async def install(rid: str, b: InstallIn):
    r = await get_release(rid)
    await adapters.reject_unverified_host(r["manifest"]["host"], b.device_id)
    d = await online_device(b.device_id)
    if not d:
        raise HTTPException(409, "No companion online. Start MELTY Companion on your PC first.")
    j = await enqueue(d["id"], "install_package", {"release_id": rid, "manifest": r["manifest"]}, r["project_id"],
                      label=f"Install {r['title']} {r['version']}")
    out = {"install_job": j["id"], "device": d["hostname"]}
    if b.launch:
        lj = await enqueue(d["id"], "launch_game", {"manifest": r["manifest"], "after_job": j["id"]}, r["project_id"],
                           label=f"Launch {r['manifest']['host']['game']}")
        out["launch_job"] = lj["id"]
    return out


@router.get("/installs")
async def installs(device_id: Optional[str] = None):
    q = {"device_id": device_id} if device_id else {}
    return await db.installs.find(q, {"_id": 0}).sort("installed_at", -1).to_list(100)


@router.post("/installs/{iid}/restore")
async def restore_install(iid: str):
    i = await db.installs.find_one({"install_id": iid}, {"_id": 0})
    if not i:
        raise HTTPException(404, "Install not found")
    j = await enqueue(i["device_id"], "uninstall_package", {"install_id": iid}, label=f"Restore files for {i.get('name')}")
    return {"job_id": j["id"]}


@router.get("/mods/{pid}/export")
async def export(pid: str):
    mod = await db.mods.find_one({"id": pid}, {"_id": 0})
    if not mod:
        raise HTTPException(404, "Mod not found")
    buf = io.BytesIO()
    await adapters.reject_unverified_host(mod["host"], mod.get("device_id"))
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in mod.get("files", []):
            z.writestr(f"{mod['slug']}/src/{f['path']}", f["content"])
        z.writestr(f"{mod['slug']}/DESIGN.md", mod.get("spec_md", ""))
        rel = await db.releases.find_one({"project_id": pid}, {"_id": 0}, sort=[("created_at", -1)])
        if rel:
            z.writestr(f"{mod['slug']}/meltpack.json", json.dumps(rel["manifest"], indent=2))
            for f in rel["manifest"]["files"]:
                data, _ = await asyncio.to_thread(get_object, f["storage_path"])
                z.writestr(f"{mod['slug']}/package/{f['path']}", data)
        z.writestr(f"{mod['slug']}/README.md",
                   f"# {mod['title']}\n\nBepInEx 5 crossover mod made with MELTY.\n\nHost: {mod['host']['name']}\n"
                   f"Secondary: {', '.join(s['name'] for s in mod.get('secondary', [])) or '-'}\n\n## Build\n"
                   "```\ndotnet build src -c Release -p:GameDir=\"<host game dir>\" -p:ManagedDir=\"<host>_Data/Managed\"\n```\n"
                   "Copy the DLL to `<host>/BepInEx/plugins/<mod>/`. Requires your own copies of the games. "
                   "No game files are included.\n")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{mod["slug"]}.zip"'})
