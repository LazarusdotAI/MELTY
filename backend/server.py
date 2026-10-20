import re
import asyncio
from typing import List, Optional
from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import Response, PlainTextResponse
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from core import db, now, new_id, logger, ROOT_DIR
import budget
import llm
import sfx
import adapters
import modagent
import devices
import packages
import suggestions
import workshop
import trainer
import playtest
from luasyntax import lua_syntax_errors
from assets import put_object, get_object, APP_NAME, init_storage

app = FastAPI()
api = APIRouter(prefix="/api")
MIN_START_BUDGET = 0.40
ASPECTS = ["mechanics", "world_structure", "progression", "atmosphere", "visual_style", "characters", "audio"]


class GameRef(BaseModel):
    name: str
    role: str = "asset-source"


class ModIn(BaseModel):
    title: str = ""
    host: GameRef
    secondary: List[GameRef] = []
    aspects: List[str] = []
    description: str
    device_id: Optional[str] = None


class TextIn(BaseModel):
    message: str


class FileIn(BaseModel):
    path: str
    content: str


class NameIn(BaseModel):
    name: str


class SettingsIn(BaseModel):
    daily_ceiling: float = Field(gt=0, le=100)
    generation_ceiling: float = Field(gt=0, le=100)


class ModelIn(BaseModel):
    preferred_model: str


class SfxIn(BaseModel):
    prompt: str = Field(min_length=3, max_length=300)
    duration: float = Field(default=2.0, ge=0.5, le=10)
    project_id: str = ""


class NoteIn(BaseModel):
    game: str
    note: str
    game_version: str = ""


async def get_mod(pid):
    m = await db.mods.find_one({"id": pid}, {"_id": 0})
    if not m:
        raise HTTPException(404, "Mod project not found")
    return m


async def active_gen(pid):
    return await db.generations.find_one({"project_id": pid, "status": {"$in": ["queued", "running"]}}, {"_id": 0, "id": 1})


async def require_budget():
    st = await budget.day_state()
    if st["remaining"] < MIN_START_BUDGET:
        raise HTTPException(402, f"Daily AI budget nearly exhausted (${st['remaining']:.2f} left of ${st['ceiling']:.2f}). "
                                 "Paid AI work is paused until tomorrow (UTC) or until you raise the ceiling.")


async def spent_for(pid):
    agg = await db.ai_calls.aggregate([{"$match": {"project_id": pid}}, {"$group": {"_id": None, "c": {"$sum": "$cost"}}}]).to_list(1)
    return agg[0]["c"] if agg else 0.0


async def new_generation(pid, kind, prompt, message_id=None):
    mod = await get_mod(pid)
    await adapters.reject_unverified_host(mod["host"], mod.get("device_id"))
    gid = new_id()
    await db.generations.insert_one({"id": gid, "project_id": pid, "kind": kind, "status": "queued", "prompt": prompt,
                                     "events": [], "cost": 0.0, "calls": 0, "created_at": now()})
    if message_id:
        await db.messages.update_one({"id": message_id}, {"$set": {"generation_id": gid, "queued": False, "started_at": now()}})
    else:
        await db.messages.insert_one({"id": new_id(), "project_id": pid, "role": "user", "content": prompt,
                                      "generation_id": gid, "created_at": now()})
    modagent.start(gid, pid, prompt, kind)
    return gid


async def start_next_queued(pid):
    if await active_gen(pid):
        return
    m = await db.messages.find_one({"project_id": pid, "role": "user", "queued": True}, {"_id": 0}, sort=[("created_at", 1)])
    if not m:
        return
    try:
        await require_budget()
        await new_generation(pid, "edit", m["content"], m["id"])
    except HTTPException as e:
        await db.messages.insert_one({"id": new_id(), "project_id": pid, "role": "system", "created_at": now(),
                                      "content": f"Your waiting request couldn't start yet: {e.detail}"})


modagent.on_finished = start_next_queued


@api.get("/health")
async def health():
    return {"ok": True}


@api.get("/providers/status")
async def providers():
    return await llm.provider_status()


@api.put("/providers/preferred")
async def set_preferred(b: ModelIn):
    if b.preferred_model not in llm.CATALOG:
        raise HTTPException(400, "Unknown model")
    await db.settings.update_one({"id": "settings"}, {"$set": {"preferred_model": b.preferred_model}}, upsert=True)
    return await llm.provider_status()


@api.get("/mods")
async def list_mods():
    out = []
    for m in await db.mods.find({}, {"_id": 0, "files": 0}).sort("updated_at", -1).to_list(200):
        out.append({**m, "spent": await spent_for(m["id"])})
    return out


@api.post("/mods")
async def create_mod(b: ModIn):
    if not b.host.name.strip() or not b.description.strip():
        raise HTTPException(400, "Host game and description are required")
    await adapters.reject_unverified_host(b.host.model_dump(), b.device_id)
    host_rec = None
    if b.device_id:
        host_rec = await db.games.find_one({"device_id": b.device_id, "name": b.host.name}, {"_id": 0})
    adapter = await adapters.match(host_rec or {"name": b.host.name})
    hi = adapters.host_info(host_rec or {}, adapter)
    if not hi["hostable"]:
        raise HTTPException(400, f"{b.host.name} can't be a host: {hi['host_reason']}")
    dev = await db.devices.find_one({"id": b.device_id}, {"_id": 0}) if b.device_id else None
    ver = ((dev or {}).get("status") or {}).get("version") or (dev or {}).get("companion_version") or "0"
    vt = tuple(int(x) for x in re.findall(r"\d+", ver)[:3]) or (0,)
    if dev and hi["toolchain"] != "bepinex5-csharp" and vt < (0, 2, 0):
        raise HTTPException(409, f"Your PC's companion ({ver}) is too old for {b.host.name}. Update it from the My PC page first.")
    await require_budget()
    title = b.title.strip() or f"{b.host.name} × {' × '.join(s.name for s in b.secondary) or 'Remix'}"
    slug = modagent.slugify(title)
    pid = new_id()
    await db.mods.insert_one({"id": pid, "title": title[:80], "slug": slug, "host": {"name": b.host.name, "role": "host"},
                              "secondary": [s.model_dump() for s in b.secondary], "aspects": [a for a in b.aspects if a in ASPECTS],
                              "description": b.description, "device_id": b.device_id, "adapter_id": adapter.get("id"),
                              "toolchain": hi["toolchain"],
                              "files": modagent.scaffold(slug, title, adapter.get("target_framework", "netstandard2.1"), hi["toolchain"]),
                              "spec_md": "", "build_status": "unbuilt", "created_at": now(), "updated_at": now()})
    await modagent.create_version(pid, "Scaffold", "scaffold")
    gid = await new_generation(pid, "create", b.description)
    return {"project_id": pid, "generation_id": gid}


@api.get("/mods/{pid}")
async def mod_detail(pid: str):
    m = await get_mod(pid)
    g = await active_gen(pid)
    blocked_reason = None
    try:
        await adapters.reject_unverified_host(m["host"], m.get("device_id"))
    except HTTPException as e:
        blocked_reason = e.detail
    return {**m, "hosting_blocked_reason": blocked_reason, "active_generation_id": g["id"] if g else None, "spent": await spent_for(pid)}


@api.patch("/mods/{pid}")
async def rename_mod(pid: str, b: NameIn):
    await get_mod(pid)
    await db.mods.update_one({"id": pid}, {"$set": {"title": b.name[:80]}})
    return {"ok": True}


@api.delete("/mods/{pid}")
async def delete_mod(pid: str):
    await get_mod(pid)
    if await active_gen(pid):
        raise HTTPException(409, "Stop the running AI work before deleting this mod")
    await db.mods.delete_one({"id": pid})
    await db.releases.update_many({"project_id": pid}, {"$set": {"published": False, "orphaned": True}})
    await db.versions.delete_many({"project_id": pid})
    await db.messages.delete_many({"project_id": pid})
    return {"ok": True}


@api.post("/mods/{pid}/chat")
async def chat(pid: str, b: TextIn):
    m = await get_mod(pid)
    await adapters.reject_unverified_host(m["host"], m.get("device_id"))
    if not b.message.strip():
        raise HTTPException(400, "Empty message")
    g = await active_gen(pid)
    if g:
        mid = new_id()
        await db.messages.insert_one({"id": mid, "project_id": pid, "role": "user", "content": b.message.strip(),
                                      "queued": True, "generation_id": None, "created_at": now()})
        await db.generations.update_one({"id": g["id"]}, {"$push": {"inbox": {"id": mid, "text": b.message.strip()[:2000]}}})
        return {"queued": True, "message_id": mid}
    await require_budget()
    return {"generation_id": await new_generation(pid, "edit", b.message)}


@api.delete("/mods/{pid}/queue/{mid}")
async def unqueue(pid: str, mid: str):
    r = await db.messages.delete_one({"id": mid, "project_id": pid, "queued": True})
    if not r.deleted_count:
        raise HTTPException(404, "That request already started or was removed")
    await db.generations.update_many({"project_id": pid}, {"$pull": {"inbox": {"id": mid}}})
    return {"ok": True}


@api.post("/mods/{pid}/queue/start")
async def queue_start(pid: str):
    if await active_gen(pid):
        raise HTTPException(409, "The AI is already working; your requests start after it")
    await start_next_queued(pid)
    return {"ok": True}


@api.get("/mods/{pid}/messages")
async def messages(pid: str):
    return await db.messages.find({"project_id": pid}, {"_id": 0}).sort("created_at", 1).to_list(500)


@api.get("/mods/{pid}/generations")
async def generations(pid: str):
    return await db.generations.find({"project_id": pid}, {"_id": 0, "files": 0, "events": 0}).sort("created_at", -1).to_list(100)


@api.get("/generations/{gid}")
async def generation(gid: str):
    g = await db.generations.find_one({"id": gid}, {"_id": 0, "files": 0})
    if not g:
        raise HTTPException(404, "Generation not found")
    return g


@api.post("/generations/{gid}/cancel")
async def cancel(gid: str):
    await db.generations.update_one({"id": gid}, {"$set": {"cancel": True}})
    return {"ok": True}


@api.get("/mods/{pid}/versions")
async def versions(pid: str):
    return await db.versions.find({"project_id": pid}, {"_id": 0, "files": 0}).sort("created_at", -1).to_list(200)


@api.post("/mods/{pid}/versions")
async def checkpoint(pid: str, b: NameIn):
    await get_mod(pid)
    return {"version_id": await modagent.create_version(pid, b.name.strip()[:80] or "Checkpoint", "manual")}


@api.post("/mods/{pid}/versions/{vid}/restore")
async def restore(pid: str, vid: str):
    if await active_gen(pid):
        raise HTTPException(409, "Wait for the AI to finish")
    v = await db.versions.find_one({"id": vid, "project_id": pid}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Version not found")
    bj = v.get("build_job_id")
    await db.mods.update_one({"id": pid}, {"$set": {"files": v["files"], "spec_md": v["spec_md"],
                                                   "verification": v.get("verification"), "last_build_job_id": bj,
                                                   "build_status": v.get("build_status") or "unbuilt"}})
    nv = await modagent.create_version(pid, f"Restored v{v['number']}: {v['name']}"[:90], "restore", verification=v.get("verification"))
    await db.versions.update_one({"id": nv}, {"$set": {"build_job_id": bj, "build_status": v.get("build_status") or "unbuilt"}})
    await db.messages.insert_one({"id": new_id(), "project_id": pid, "role": "system",
                                  "content": f"Restored version {v['number']} — “{v['name']}”.", "created_at": now()})
    return {"version_id": nv}


@api.put("/mods/{pid}/files")
async def save_file(pid: str, b: FileIn):
    m = await get_mod(pid)
    try:
        path = modagent.safe(b.path, True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    files = [f for f in m.get("files", []) if f["path"] != path] + [{"path": path, "content": b.content}]
    await db.mods.update_one({"id": pid}, {"$set": {"files": sorted(files, key=lambda f: f["path"]), "dirty": True,
                                                   "last_build_job_id": None, "build_status": "unbuilt", "updated_at": now()}})
    return {"ok": True}


@api.post("/mods/{pid}/build")
async def build_now(pid: str):
    m = await get_mod(pid)
    await adapters.reject_unverified_host(m["host"], m.get("device_id"))
    syntax, _note = lua_syntax_errors(m.get("files") or [], m.get("toolchain"))
    if syntax:
        raise HTTPException(400, "Lua syntax errors, fix these before building: " + " | ".join(syntax[:10]))
    d = await devices.online_device(m.get("device_id"))
    if not d:
        raise HTTPException(409, "No companion online")
    j = await devices.enqueue(d["id"], "build_mod", {"project_id": pid, "slug": m["slug"], "files": m["files"], "host_name": m["host"]["name"],
                                                     **modagent.tc_params(m)}, pid, label=f"Manual build {m['title']}")
    asyncio.create_task(_track_manual_build(pid, j["id"], modagent.files_hash(m["files"])))
    return j


async def _track_manual_build(pid, jid, h):
    j = await devices.wait_job(jid, 420)
    if j["status"] == "done" and (j.get("result") or {}).get("ok"):
        m = await db.mods.find_one({"id": pid}, {"files": 1})
        if m and modagent.files_hash(m["files"]) == h:
            await db.mods.update_one({"id": pid}, {"$set": {"last_build_job_id": jid, "build_hash": h, "build_status": "built", "dirty": False}})


@api.get("/adapters")
async def list_adapters():
    out = []
    for a in await db.adapters.find({}, {"_id": 0}).to_list(200):
        a["notes"] = await db.knowledge.find({"game": a["name"]}, {"_id": 0}).sort("created_at", -1).to_list(30)
        out.append(a)
    return out


@api.get("/knowledge")
async def knowledge():
    return await db.knowledge.find({}, {"_id": 0}).sort("created_at", -1).to_list(300)


@api.post("/knowledge")
async def add_knowledge(b: NoteIn):
    await adapters.add_note(b.game, b.note, b.game_version, "user")
    return {"ok": True}


@api.get("/assets")
async def assets_list():
    items = await db.assets.find({"is_deleted": False}, {"_id": 0}).sort("created_at", -1).to_list(500)
    for a in items:
        a["url"] = f"/api/assets/file/{a['id']}"
    return items


@api.post("/assets/upload")
async def upload(file: UploadFile = File(...), license: str = Form("User-provided")):
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "Max 8 MB per file")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    types = {"png": "image/png", "jpg": "image/jpeg", "wav": "audio/wav", "ogg": "audio/ogg", "mp3": "audio/mpeg"}
    if ext not in types:
        raise HTTPException(400, "Supported: png, jpg, wav, ogg, mp3")
    res = await asyncio.to_thread(put_object, f"{APP_NAME}/uploads/{new_id()}.{ext}", data, types[ext])
    aid = new_id()
    await db.assets.insert_one({"id": aid, "name": file.filename[:80], "kind": "sfx" if ext in ("wav", "ogg", "mp3") else "texture",
                                "storage_path": res["path"], "content_type": types[ext], "size": len(data),
                                "license": license[:120], "source": "upload", "is_deleted": False, "created_at": now()})
    return {"id": aid}


@api.get("/assets/file/{aid}")
async def asset_file(aid: str):
    a = await db.assets.find_one({"id": aid, "is_deleted": False}, {"_id": 0})
    if not a:
        raise HTTPException(404, "not found")
    data, _ = await asyncio.to_thread(get_object, a["storage_path"])
    return Response(data, media_type=a["content_type"])


@api.delete("/assets/{aid}")
async def delete_asset(aid: str):
    await db.assets.update_one({"id": aid}, {"$set": {"is_deleted": True}})
    return {"ok": True}


@api.get("/sfx/status")
async def sfx_status():
    return {"enabled": sfx.enabled(), "cost_per_second": sfx.estimate(1.0)}


@api.post("/sfx/generate")
async def sfx_generate(b: SfxIn):
    if b.project_id:
        m = await db.mods.find_one({"id": b.project_id}, {"_id": 0})
        if m:
            await adapters.reject_unverified_host(m.get("host") or {}, m.get("device_id"))
    if not sfx.enabled():
        raise HTTPException(400, "ElevenLabs is not connected. Add ELEVENLABS_API_KEY to enable sound generation.")
    try:
        return await sfx.generate_sfx(b.prompt, b.duration, b.project_id)
    except budget.BudgetExceeded as e:
        raise HTTPException(402, str(e))
    except Exception as e:
        raise HTTPException(502, f"ElevenLabs error: {str(e)[:300]}")


@api.get("/budget")
async def budget_view():
    st = await budget.day_state()
    per = await db.ai_calls.aggregate([{"$group": {"_id": "$project_id", "cost": {"$sum": "$cost"}, "calls": {"$sum": 1},
                                                   "tin": {"$sum": "$input_tokens"}, "tout": {"$sum": "$output_tokens"}}},
                                       {"$sort": {"cost": -1}}]).to_list(100)
    titles = {m["id"]: m["title"] for m in await db.mods.find({}, {"_id": 0, "id": 1, "title": 1}).to_list(500)}
    titles |= {"suggestions": "Mashup idea pitches", "hf-smoke": "Hugging Face connection test"}
    per_project = [{"project_id": r["_id"], "title": titles.get(r["_id"], "(earlier prototype / deleted)"),
                    **{k: r[k] for k in ("cost", "calls", "tin", "tout")}} for r in per]
    gens = await db.generations.find({}, {"_id": 0, "files": 0, "events": 0}).sort("created_at", -1).to_list(50)
    for g in gens:
        g["title"] = titles.get(g["project_id"], "(deleted)")
    ex = await db.jobs.aggregate([{"$match": {"status": {"$in": ["done", "failed"]}}},
                                  {"$group": {"_id": "$op", "n": {"$sum": 1}}}]).to_list(20)
    return {**st, "settings": await budget.get_settings(), "per_project": per_project, "generations": gens,
            "calls": await db.ai_calls.find({}, {"_id": 0}).sort("created_at", -1).to_list(60),
            "history": await db.budget_days.find({}, {"_id": 0}).sort("day", -1).to_list(14),
            "providers": await llm.provider_status(), "companion_jobs": {e["_id"]: e["n"] for e in ex},
            "outside_limit": [
                {"item": "Emergent hosting & deployment", "note": "Billed in Emergent credits by the platform; not metered here."},
                {"item": "Builds & in-game tests", "note": "Run on your own PC through the companion — electricity only, no API fee."},
                {"item": "Object storage (builds, screenshots, uploads)", "note": "Emergent-managed storage; not metered by this limit."},
                {"item": "ElevenLabs", "note": "Counted inside the limit using an estimated $/credit (configurable)."}]}


@api.put("/budget/settings")
async def budget_settings(b: SettingsIn):
    await db.settings.update_one({"id": "settings"}, {"$set": b.model_dump()}, upsert=True)
    return await budget.get_settings()


SETUP_BAT = r"""@echo off
title MELTY Companion setup
set "SERVER=__SERVER__"
set "DIR=%USERPROFILE%\MeltyCompanion"
echo.
echo  ==== MELTY Companion setup ====
echo.
if not exist "%DIR%" mkdir "%DIR%"
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY (
  echo  Python is not installed. Installing it now with winget...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo.
  echo  Python installed. Please CLOSE this window and double-click this setup file again.
  pause
  exit /b
)
dotnet --list-sdks 2>nul | findstr /r "^[89]\. ^1[0-9]\." >nul
if errorlevel 1 (
  echo  The .NET SDK is needed to build mods. Installing .NET 8 SDK with winget...
  winget install -e --id Microsoft.DotNet.SDK.8 --accept-source-agreements --accept-package-agreements
)
echo  Downloading the latest companion...
powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -UserAgent 'MeltyCompanion' -Uri '%SERVER%/api/companion-app/download' -OutFile '%DIR%\melty_companion.py'"
powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -UserAgent 'MeltyCompanion' -Uri '%SERVER%/api/companion-app/download/melty_assets.py' -OutFile '%DIR%\melty_assets.py'"
if not exist "%DIR%\melty_companion.py" (
  echo  Download failed. Check your internet connection and try again.
  pause
  exit /b
)
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESK=%%D"
(
  echo @echo off
  echo title MELTY Companion
  echo %PY% "%DIR%\melty_companion.py" run
  echo pause
) > "%DESK%\Start MELTY Companion.bat"
echo  Added "Start MELTY Companion" to your desktop for next time.
echo.
echo  Connecting this PC... keep this window open while you use MELTY.
echo.
%PY% "%DIR%\melty_companion.py" pair %SERVER% __CODE__
pause
"""


UPDATE_BAT = r"""@echo off
title Updating MELTY
set "SERVER=__SERVER__"
set "DIR=%USERPROFILE%\MeltyCompanion"
if not exist "%DIR%" mkdir "%DIR%"
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY (
  echo  Python is missing. Run MELTY-Setup.bat from the My PC page instead.
  pause
  exit /b
)
echo  Closing any running companion...
taskkill /fi "WINDOWTITLE eq MELTY Companion*" /f >nul 2>nul
echo  Downloading the latest companion...
powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -UserAgent 'MeltyCompanion' -Uri '%SERVER%/api/companion-app/download' -OutFile '%DIR%\melty_companion.py'"
powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -UserAgent 'MeltyCompanion' -Uri '%SERVER%/api/companion-app/download/melty_assets.py' -OutFile '%DIR%\melty_assets.py'"
if not exist "%DIR%\melty_companion.py" (
  echo  Download failed. Check your internet connection and try again.
  pause
  exit /b
)
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESK=%%D"
(
  echo @echo off
  echo title MELTY Companion
  echo %PY% "%DIR%\melty_companion.py" run
  echo pause
) > "%DESK%\Start MELTY Companion.bat"
echo  Updated. Starting the companion - keep this window open.
echo.
title MELTY Companion
%PY% "%DIR%\melty_companion.py" run
pause
"""


def _valid_server(server: str) -> str:
    s = server.rstrip("/")
    if not re.fullmatch(r"https://[\w.\-]+(:\d+)?", s):
        raise HTTPException(400, "Invalid server")
    return s


@api.get("/companion-app/update.bat")
async def companion_update_bat(server: str):
    bat = UPDATE_BAT.replace("__SERVER__", _valid_server(server)).replace("\n", "\r\n")
    return Response(bat.encode(), media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="MELTY-Update.bat"'})


@api.get("/companion-app/setup.bat")
async def companion_setup(code: str, server: str):
    if not re.fullmatch(r"[A-Z2-9]{8}", code) or not re.fullmatch(r"https://[\w.\-]+(:\d+)?", server.rstrip("/")):
        raise HTTPException(400, "Invalid setup request")
    bat = SETUP_BAT.replace("__SERVER__", server.rstrip("/")).replace("__CODE__", code).replace("\n", "\r\n")
    return Response(bat.encode(), media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="MELTY-Setup.bat"'})


@api.get("/companion-app/version")
async def companion_version():
    m = re.search(r'VERSION = "([\d.]+)"', (ROOT_DIR / "companion" / "melty_companion.py").read_text())
    return {"version": m.group(1)}


@api.get("/companion-app/download/melty_assets.py")
async def companion_assets_download():
    return PlainTextResponse((ROOT_DIR / "companion" / "melty_assets.py").read_text(),
                             headers={"Content-Disposition": 'attachment; filename="melty_assets.py"'})


@api.get("/companion-app/download")
async def companion_download():
    return PlainTextResponse((ROOT_DIR / "companion" / "melty_companion.py").read_text(),
                             headers={"Content-Disposition": 'attachment; filename="melty_companion.py"'})


app.include_router(api)
app.include_router(devices.web)
app.include_router(devices.comp)
app.include_router(packages.router)
app.include_router(suggestions.router)
app.include_router(workshop.router)
app.include_router(trainer.router)
app.include_router(playtest.router)
app.add_middleware(CORSMiddleware, allow_credentials=False, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await db.budget_days.create_index("day", unique=True)
    await db.mods.create_index("id", unique=True)
    await db.jobs.create_index([("device_id", 1), ("status", 1)])
    await db.jobs.create_index([("op", 1), ("params.install_dir", 1), ("created_at", -1)])
    await budget.settle_orphans()
    await db.generations.update_many({"status": {"$in": ["queued", "running"]}},
                                     {"$set": {"status": "failed", "error": "Interrupted by server restart"}})
    await adapters.seed()
    try:
        init_storage()
    except Exception as e:
        logger.error("Storage init failed: %s", e)
