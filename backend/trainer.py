"""Game Trainer: per-engine profiles, live settings and evidence-based feature status (runs through the companion)."""
import json
import time
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core import db, now, new_id
from devices import enqueue, online_device

router = APIRouter(prefix="/api/trainer")


def F(key, label, cat, kind="toggle", lo=None, hi=None, default=None, desc="", method=None, requires=None):
    return {"key": key, "label": label, "category": cat, "kind": kind, "min": lo, "max": hi, "default": default, "desc": desc,
            "method": method, "requires": requires}


NEEDS_BUILD = "Needs a custom mod — ask Copilot to build it"
PROFILES = {
    "redengine4": {"tool": "cet", "mod_dir": "bin/x64/plugins/cyber_engine_tweaks/mods/MeltyTrainer", "online_safe": False, "features": [
        F("god_mode", "God Mode", "Health", desc="You can't be killed", method="live"),
        F("super_speed", "Super Speed", "Movement", "slider", 1, 4, 1, "Movement speed multiplier", "live"),
        F("super_jump", "Super Jump", "Movement", "slider", 1, 4, 1, "Jump height multiplier", "live"),
        F("bullet_time", "Bullet Time", "Weapons", "slider", 0.1, 1, 1, "Slows the world down (1 = normal)", "live"),
        F("time_of_day", "Time of Day", "World", "slider", 0, 23, 12, "Sets the in-game hour", "live"),
        F("weather", "Weather", "World", "select", default="", desc="Changes the weather", method="live"),
        F("no_recoil", "No Recoil", "Weapons", requires=NEEDS_BUILD), F("rapid_fire", "Rapid Fire", "Weapons", requires=NEEDS_BUILD),
        F("infinite_ammo", "Infinite Ammo", "Weapons", requires=NEEDS_BUILD), F("no_clip", "No Clip", "Movement", requires=NEEDS_BUILD),
        F("crosshair", "Custom Crosshair", "Visuals", requires=NEEDS_BUILD), F("aim_assist", "Visual Aim Assist", "Visuals", requires=NEEDS_BUILD),
    ], "weather": ["24h_weather_sunny", "24h_weather_rain", "24h_weather_fog", "24h_weather_sandstorm", "24h_weather_toxic_fallout"]},
    "unreal": {"tool": None, "features": [F(k, lbl, c, requires="Planned: needs the UE4SS trainer build for this game (not built yet)") for k, lbl, c in [
        ("god_mode", "God Mode", "Health"), ("super_speed", "Super Speed", "Movement"), ("super_jump", "Super Jump", "Movement"),
        ("no_recoil", "No Recoil", "Weapons"), ("infinite_ammo", "Infinite Ammo", "Weapons"), ("aim_assist", "Visual Aim Assist", "Visuals")]]},
}

LUA = r'''-- MELTY Trainer (generated). Reads settings.json live, writes status.json with what the game reports back.
local S, applied, mods, last, rev = {}, {}, {}, 0, -1
local ST = { features = {}, loaded = os.time() }
-- Game types (CName, Game, ...) don't exist yet while CET loads this file; NAME is created in onInit.
local NAME = nil
-- ok = the command ran without a Lua error; verified = the game's own state was read back and matches the request
-- (true/false), or nil when the game can't report it. Only verified == true may be shown as Active.
local function mark(k, ok, info, verified) ST.features[k] = { ok = ok, info = tostring(info or ""), verified = verified } end
local function readSettings()
  local f = io.open("settings.json", "r"); if not f then return end
  local t = f:read("*a"); f:close()
  local ok, v = pcall(json.decode, t); if ok and type(v) == "table" then S = v end
end
local function writeStatus()
  ST.t = os.time(); ST.rev = rev
  local f = io.open("status.json", "w"); if f then f:write(json.encode(ST)); f:close() end
end
local function on(k) return S.features and S.features[k] and S.features[k].on end
local function val(k, d) return (S.features and S.features[k] and tonumber(S.features[k].value)) or d end
local function statMult(p, k, stype, m)
  local ss, id = Game.GetStatsSystem(), p:GetEntityID()
  if mods[k] then ss:RemoveModifier(id, mods[k]); mods[k] = nil end
  local before = ss:GetStatValue(id, stype)
  if m and m ~= 1 then mods[k] = RPGManager.CreateStatModifier(stype, gameStatModifierType.Multiplier, m); ss:AddModifier(id, mods[k]) end
  return before, ss:GetStatValue(id, stype)
end
local function statFeature(p, k, key, stype, label)
  local m = on(key) and val(key, 1) or 1
  local before, after = statMult(p, k, stype, m)
  -- proven only if the game's own stat moved at least halfway to the requested multiple
  local verified = (m == 1) or (before > 0 and after >= before + before * (m - 1) * 0.5)
  return label .. "=" .. tostring(after) .. " (was " .. tostring(before) .. ", x" .. tostring(m) .. ")", verified
end
local function apply(p)
  NAME = NAME or CName.new("MeltyTrainer")
  local id = p:GetEntityID()
  local function try(k, fn)
    local ok, info, verified = pcall(fn)
    if not ok then verified = nil end
    mark(k, ok, info, verified)
  end
  try("god_mode", function()
    local gm, want = Game.GetGodModeSystem(), on("god_mode") and true or false
    if want then gm:AddGodMode(id, gameGodModeType.Invulnerable, NAME) else gm:RemoveGodMode(id, gameGodModeType.Invulnerable, NAME) end
    local has = gm:HasGodMode(id, gameGodModeType.Invulnerable) and true or false
    return "invulnerable=" .. tostring(has), has == want
  end)
  try("super_speed", function() return statFeature(p, "speed", "super_speed", gamedataStatType.MaxSpeed, "MaxSpeed") end)
  try("super_jump", function() return statFeature(p, "jump", "super_jump", gamedataStatType.JumpHeight, "JumpHeight") end)
  try("bullet_time", function()
    local ts = Game.GetTimeSystem()
    local want = (on("bullet_time") and val("bullet_time", 1) < 1) and true or false
    if want then ts:SetTimeDilation(NAME, val("bullet_time", 1)) else ts:UnsetTimeDilation(NAME) end
    local active = ts:IsTimeDilationActive() and true or false
    return "dilation_active=" .. tostring(active), active == want
  end)
  if on("time_of_day") then try("time_of_day", function()
    local ts, h = Game.GetTimeSystem(), math.floor(val("time_of_day", 12))
    ts:SetGameTimeByHMS(h, 0, 0)
    local okh, cur = pcall(function() return ts:GetGameTime():Hours() end)
    if okh and type(cur) == "number" then return "hour=" .. tostring(cur), cur == h end
    return "hour set (the game didn't report the time back)", nil
  end) end
  if on("weather") and S.features.weather.value and S.features.weather.value ~= "" then
    try("weather", function()
      Game.GetWeatherSystem():SetWeather(CName.new(S.features.weather.value), 10, 0)
      return S.features.weather.value .. " requested (weather fades in, so it can't be read back yet)", nil
    end)
  end
end
-- Touching the player or game systems on the main menu crashes the game (seen 2026-10-19: every launch crashed
-- 1 s after onInit). Only act once the player is attached to a loaded save, plus a few seconds to settle.
local attached, attachedFor = false, 0
registerForEvent("onInit", function()
  NAME = CName.new("MeltyTrainer")
  Observe("PlayerPuppet", "OnGameAttached", function() attached, attachedFor = true, 0 end)
  Observe("PlayerPuppet", "OnDetach", function() attached, attachedFor, rev, mods = false, 0, -1, {} end)  -- re-apply on the next save
  spdlog.info("MELTY_READY MeltyTrainer"); readSettings(); writeStatus()
end)
registerForEvent("onUpdate", function(dt)
  if attached then attachedFor = attachedFor + dt end
  last = last + dt; if last < 1 then return end; last = 0
  readSettings()
  local p = (attached and attachedFor >= 3) and Game.GetPlayer() or nil
  ST.in_game = p ~= nil
  if p and S.rev and S.rev ~= rev then
    rev = S.rev
    if S.emergency then S.features = {} end
    apply(p)
  end
  writeStatus()
end)
'''


def profile_for(g):
    return PROFILES.get(g.get("engine"))


async def game_or_404(device_id, install_dir):
    g = await db.games.find_one({"device_id": device_id, "install_dir": install_dir}, {"_id": 0})
    if not g:
        raise HTTPException(404, "Game not found on this PC")
    return g


async def latest(device_id, install_dir, op):
    return await db.jobs.find_one({"device_id": device_id, "op": op, "status": "done", "params.install_dir": install_dir},
                                  {"_id": 0}, sort=[("created_at", -1)])


def feature_state(f, prof, tool_ok, installed, status, saved):
    if f.get("requires"):
        return "Requires Build" if "build" in f["requires"].lower() or "Planned" in f["requires"] else "Unsupported", f["requires"]
    if not tool_ok:
        return "Requires Build", "Install Cyber Engine Tweaks first (Set up modding tools)"
    if not installed:
        return "Install First", "Install the trainer into the game first"
    on = ((saved or {}).get(f["key"]) or {}).get("on")
    if status and status.get("load_error"):
        return "Broken", f"The trainer didn't start in the game: {status['load_error'][:200]}"
    fresh = bool(status and status.get("rev") == (saved or {}).get("__rev") and status.get("in_game"))
    rep = ((status or {}).get("features") or {}).get(f["key"]) if fresh else None
    if status and not status.get("loaded"):
        return "Requires Restart", "Start (or restart) the game so it loads the trainer"
    if not on:
        return "Available", None
    if status and status.get("runtime_error"):
        return "Broken", f"The trainer hit an error in the game: {status['runtime_error'][:200]}"
    if rep and rep.get("ok") is False:
        return "Broken", f"The game rejected it: {rep.get('info', '')[:160]}"
    if rep and rep.get("ok"):
        # A command that ran without error isn't proof: only the game's own read-back can make it Active.
        if rep.get("verified") is True:
            return "Active", rep.get("info")
        if rep.get("verified") is False:
            return "Broken", f"The game took the command but the effect isn't on: {rep.get('info', '')[:160]}"
        return "Needs Testing", f"Sent, but the game can't report this one back. Check it yourself in game ({rep.get('info', '')[:120]})"
    if on:
        return "Needs Testing", "Sent — waiting for the game to confirm (load a save)"
    return "Available", None


@router.get("/game")
async def trainer_game(install_dir: str, device_id: Optional[str] = None):
    d = await online_device(device_id) or await db.devices.find_one({"id": device_id} if device_id else {"revoked": {"$ne": True}}, {"_id": 0}, sort=[("last_seen", -1)])
    if not d:
        raise HTTPException(404, "No PC paired")
    g = await game_or_404(d["id"], install_dir)
    prof = profile_for(g)
    saved = (await db.trainer_settings.find_one({"device_id": d["id"], "install_dir": install_dir}, {"_id": 0}) or {}).get("features", {})
    if not prof:
        return {"game": g["name"], "supported": False, "reason": "MELTY has no trainer profile for this game's engine yet.", "features": []}
    tool_ok = not prof["tool"] or prof["tool"] in (g.get("frameworks") or [])
    inst = await latest(d["id"], install_dir, "trainer_install")
    unin = inst and await db.jobs.find_one({"device_id": d["id"], "op": "uninstall_package", "status": "done",
                                            "params.install_id": inst["result"].get("install_id")}, {"_id": 0, "id": 1})
    installed = bool(inst and not unin)
    st = await latest(d["id"], install_dir, "trainer_status")
    status = (st or {}).get("result", {}).get("status")
    if status and inst and status.get("loaded", 0) and st["created_at"] < inst["created_at"]:
        status = None
    feats = []
    for f in prof["features"]:
        s, why = feature_state(f, prof, tool_ok, installed, status, saved)
        feats.append({**f, "status": s, "why": why, "on": bool((saved.get(f["key"]) or {}).get("on")), "value": (saved.get(f["key"]) or {}).get("value", f["default"]),
                      "options": prof.get("weather") if f["key"] == "weather" else None})
    return {"game": g["name"], "device_id": d["id"], "install_dir": install_dir, "supported": True, "live": bool(prof.get("mod_dir")), "tool_ok": tool_ok, "installed": installed,
            "install_id": (inst or {}).get("result", {}).get("install_id") if installed else None, "in_game": bool(status and status.get("in_game")),
            "status_at": (st or {}).get("finished_at"), "features": feats, "presets": await db.trainer_presets.find(
                {"install_dir": install_dir, "device_id": {"$in": [d["id"], None]}}, {"_id": 0}).to_list(50)}


class GameRef(BaseModel):
    install_dir: str
    device_id: str


class ApplyIn(GameRef):
    features: dict = {}
    emergency: bool = False


class PresetIn(GameRef):
    name: str
    features: dict = {}


@router.post("/install")
async def install(b: GameRef):
    g = await game_or_404(b.device_id, b.install_dir)
    prof = profile_for(g)
    if not prof or not prof.get("mod_dir"):
        raise HTTPException(400, "No installable trainer for this game yet")
    if prof["tool"] not in (g.get("frameworks") or []):
        raise HTTPException(400, "Set up Cyber Engine Tweaks for this game first")
    return await enqueue(b.device_id, "trainer_install", {"install_dir": b.install_dir, "name": g["name"], "mod_dir": prof["mod_dir"],
                                                          "files": {"init.lua": LUA}}, label=f"Install MELTY trainer — {g['name']}", force_status="needs_approval")


@router.post("/apply")
async def apply(b: ApplyIn):
    g = await game_or_404(b.device_id, b.install_dir)
    prof = profile_for(g)
    if not prof or not prof.get("mod_dir"):
        raise HTTPException(400, "No live trainer for this game yet")
    allowed = {f["key"]: f for f in prof["features"] if not f.get("requires")}
    if any(not isinstance(v, dict) for v in b.features.values()):
        raise HTTPException(400, "Each feature needs on/value settings")
    blocked = [k for k, v in b.features.items() if v.get("on") and k not in allowed]
    if blocked:
        raise HTTPException(400, f"Not available for this game yet: {', '.join(blocked)}")
    feats = {}
    for k, v in ({} if b.emergency else b.features).items():
        if k not in allowed or not isinstance(v, dict):
            continue
        f = allowed[k]
        val = v.get("value", f["default"])
        if f["kind"] == "slider" and val is not None:
            try:
                val = max(f["min"], min(f["max"], float(val)))
            except (TypeError, ValueError):
                raise HTTPException(400, f"{f['label']} needs a number")
        feats[k] = {"on": bool(v.get("on")), "value": val}
    prev = ((await db.trainer_settings.find_one({"device_id": b.device_id, "install_dir": b.install_dir}, {"features.__rev": 1})) or {}).get("features", {}).get("__rev", 0)
    rev = max(int(time.time() * 1000), prev + 1)
    await db.trainer_settings.update_one({"device_id": b.device_id, "install_dir": b.install_dir},
                                         {"$set": {"features": {**feats, "__rev": rev}, "updated_at": now()}}, upsert=True)
    settings = {"rev": rev, "emergency": b.emergency, "features": feats}
    j = await enqueue(b.device_id, "trainer_apply", {"install_dir": b.install_dir, "name": g["name"], "mod_dir": prof["mod_dir"],
                                                    "settings": json.loads(json.dumps(settings))}, label=f"Trainer settings — {g['name']}")
    return {"job": j["id"], "rev": rev}


@router.post("/refresh")
async def refresh(b: GameRef):
    g = await game_or_404(b.device_id, b.install_dir)
    prof = profile_for(g) or {}
    return await enqueue(b.device_id, "trainer_status", {"install_dir": b.install_dir, "name": g["name"], "mod_dir": prof.get("mod_dir", "")},
                         label=f"Read trainer status — {g['name']}")


@router.post("/presets")
async def save_preset(b: PresetIn):
    p = {"id": new_id(), "device_id": b.device_id, "install_dir": b.install_dir, "name": b.name.strip()[:60] or "Preset", "features": b.features, "created_at": now()}
    await db.trainer_presets.update_one({"device_id": b.device_id, "install_dir": b.install_dir, "name": p["name"]}, {"$set": p}, upsert=True)
    return p


@router.delete("/presets/{pid}")
async def delete_preset(pid: str):
    if not (await db.trainer_presets.delete_one({"id": pid})).deleted_count:
        raise HTTPException(404, "Preset not found")
    return {"ok": True}


class RenameIn(BaseModel):
    name: str


@router.patch("/presets/{pid}")
async def rename_preset(pid: str, b: RenameIn):
    if not b.name.strip():
        raise HTTPException(400, "Give the preset a name")
    if not (await db.trainer_presets.update_one({"id": pid}, {"$set": {"name": b.name.strip()[:60]}})).matched_count:
        raise HTTPException(404, "Preset not found")
    return {"ok": True}

