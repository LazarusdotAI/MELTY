"""Rank crossover pairs from a device's detected games by moddability; optional AI pitches."""
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core import db, now, new_id
from budget import BudgetExceeded
from llm import complete
import adapters
import devices

router = APIRouter(prefix="/api")


def _year(v):
    try:
        return int((v or "").split(".")[0])
    except ValueError:
        return None


async def host_score(g, notes):
    if not g.get("hostable"):
        return 0, []
    a = await adapters.match(g)
    s, why = 50, [{"bepinex5-csharp": "Unity Mono: BepInEx 5 C# mods", "ue3-unrealscript": "UnrealScript mutators via the official SDK",
                   "ue4ss-lua": "Unreal 4/5: UE4SS Lua mods, no compile step"}.get(g.get("toolchain"), "Moddable host")]
    if a.get("kind") == "game":
        s += 20
        why.append(f"Game-specific adapter ({a['status']})")
    if g.get("loader_installed"):
        s += 10
        why.append("Mod loader / SDK already installed")
    elif g.get("toolchain") == "ue3-unrealscript":
        why.append("Needs the free game SDK from Steam Tools")
    if g.get("unity_version"):
        s += 5
    if g.get("managed_count") or g.get("inspected_at"):
        s += 5
    if notes:
        s += min(10, 2 * notes)
        why.append(f"{notes} saved notes from earlier work")
    return min(100, s), why


def secondary_fit(host, g):
    hy, gy = _year(host.get("unity_version")), _year(g.get("unity_version"))
    if g.get("engine", "").startswith("unity") and hy and gy and abs(hy - gy) <= 1:
        return 100, "asset-source", f"Unity {g['unity_version']} is close to the host's {host['unity_version']}, so its assets are likely loadable"
    if g.get("engine", "").startswith("unity"):
        return 65, "asset-source", "Unity game: loose sounds/textures usable; bundles may need conversion"
    if g.get("engine") in ("unreal", "unreal3"):
        return 40, "mechanic-inspiration", "Unreal packages can't be loaded into another engine, so its mechanics are re-implemented in the host instead"
    if g.get("engine") == "re-engine":
        return 40, "mechanic-inspiration", "RE Engine assets are packed and encrypted, so its mechanics are re-implemented in the host instead"
    return 35, "mechanic-inspiration", "Unknown engine, so its mechanics are re-implemented in the host instead"


@router.get("/suggestions")
async def suggestions(device_id: str):
    games = [adapters.unverified_host_status(g) for g in await db.games.find({"device_id": device_id}, {"_id": 0, "managed": 0}).to_list(3000)]
    notes = {}
    async for n in db.knowledge.aggregate([{"$group": {"_id": {"$toLower": "$game"}, "n": {"$sum": 1}}}]):
        notes[n["_id"]] = n["n"]
    hosts = []
    for g in games:
        s, why = await host_score(g, notes.get(g["name"].lower(), 0))
        if s:
            hosts.append((s, why, g))
    hosts.sort(key=lambda x: -x[0])
    pitches = {p["key"]: p for p in await db.pitches.find({"device_id": device_id}, {"_id": 0}).to_list(200)}
    pairs = []
    for hs, why, h in hosts[:10]:
        for g in games:
            if g["install_dir"] == h["install_dir"] or adapters.is_cold_war(g) or adapters.is_wwii(g):
                continue
            fs, role, reason = secondary_fit(h, g)
            score = round(hs * 0.7 + fs * 0.3)
            key = f"{h['name']}|{g['name']}"
            pairs.append({"key": key, "score": score, "host": {"name": h["name"], "steam_appid": h.get("steam_appid"), "score": hs},
                          "secondary": {"name": g["name"], "steam_appid": g.get("steam_appid"), "role": role, "fit": fs},
                          "reasons": why + [reason], "pitch": pitches.get(key)})
    pairs.sort(key=lambda p: -p["score"])
    seen, out = {}, []
    for p in pairs:
        if seen.get(p["host"]["name"], 0) >= 3:
            continue
        seen[p["host"]["name"]] = seen.get(p["host"]["name"], 0) + 1
        out.append(p)
        if len(out) >= 12:
            break
    blocked = [{"name": g["name"], "reason": g.get("host_reason")} for g in games if not g.get("hostable")]
    return {"pairs": out, "host_count": len(hosts), "game_count": len(games), "not_hostable": len(blocked), "blocked": blocked}


class PitchIn(BaseModel):
    device_id: str
    keys: list
    fresh: bool = False


PITCH_SYSTEM = """You pitch small, feasible crossover mods. For each pair: the HOST game runs; the SECOND game lends assets (if role asset-source) or mechanics (re-implemented).
Return ONLY JSON: {"pitches":[{"key": str, "title": str, "idea": str (<=45 words, concrete mechanic that touches both games), "first_step": str (<=20 words, smallest testable version)}]}
Use only original names for anything new; refer to the games by name."""


@router.post("/suggestions/pitch")
async def pitch(b: PitchIn):
    sug = {p["key"]: p for p in (await suggestions(b.device_id))["pairs"]}
    pairs = [sug[k] for k in b.keys[:6] if k in sug]
    if not pairs:
        raise HTTPException(400, "No matching suggestions")
    if not b.fresh:  # pitches are saved per pair; only pay for pairs that don't have one yet
        have = {p["key"] async for p in db.pitches.find({"device_id": b.device_id, "key": {"$in": [x["key"] for x in pairs]}}, {"key": 1})}
        pairs = [p for p in pairs if p["key"] not in have]
        if not pairs:
            return {"count": 0, "cost": 0.0, "model": "saved ideas (no AI call needed)"}
    ctx = json.dumps([{"key": p["key"], "host": p["host"]["name"], "second": p["secondary"]["name"],
                       "role": p["secondary"]["role"]} for p in pairs])
    try:
        r = await complete([{"role": "system", "content": PITCH_SYSTEM}, {"role": "user", "content": ctx}], None, 4000,
                           {"project_id": "suggestions", "generation_id": None, "purpose": "mashup pitches"})
    except BudgetExceeded as e:
        raise HTTPException(402, str(e))
    txt = r["message"].get("content") or ""
    try:
        data = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])["pitches"]
    except Exception:
        raise HTTPException(502, "The AI returned an unreadable answer; nothing was saved (cost still counted).")
    for p in data:
        if p.get("key") in sug:
            await db.pitches.update_one({"device_id": b.device_id, "key": p["key"]},
                                        {"$set": {**{k: str(p.get(k, ""))[:400] for k in ("title", "idea", "first_step")},
                                                  "device_id": b.device_id, "key": p["key"], "model": r["model"], "at": now()}},
                                        upsert=True)
    return {"count": len(data), "cost": r["cost"], "model": r["model"]}


@router.get("/checklist")
async def checklist(device_id: str = None):
    d = await devices.online_device(device_id)
    dev = d or await db.devices.find_one({"revoked": {"$ne": True}, **({"id": device_id} if device_id else {})}, {"_id": 0}, sort=[("last_seen", -1)])
    library = await devices.device_games(dev["id"]) if dev else []
    games = len(library)
    hosts = sum(bool(g.get("hostable")) for g in library)
    needs_dotnet = any(g.get("hostable") and g.get("toolchain") == "bepinex5-csharp" for g in library)
    mod = await db.mods.find_one({}, {"_id": 0, "files": 0}, sort=[("updated_at", -1)])
    built = await db.jobs.find_one({"op": "build_mod", "status": "done", "result.ok": True}, {"_id": 0, "id": 1})
    tested = await db.mods.find_one({"verification.passed": True}, {"_id": 0, "id": 1})
    tried = await db.jobs.find_one({"op": "test_mod", "status": {"$in": ["done", "failed"]}}, {"_id": 0, "id": 1})
    rel = await db.releases.find_one({}, {"_id": 0, "id": 1})
    inst = await db.installs.find_one({}, {"_id": 0, "status": 1})
    rest = await db.installs.find_one({"status": "restored"}, {"_id": 0, "install_id": 1})
    steps = [
        ("paired", "Pair the companion", bool(dev)),
        ("online", "Companion online", bool(d)),
        ("games", f"Games detected ({games})", games > 0),
        ("dotnet", ".NET SDK found" if needs_dotnet else ".NET SDK (not needed for your hosts)",
         (not needs_dotnet and bool(dev)) or bool(dev and (dev.get("status") or {}).get("dotnet"))),
        ("host", f"Buildable host available ({hosts})", hosts > 0),
        ("mod", "Create a crossover mod", bool(mod)),
        ("build", "Mod compiles on your PC", bool(built)),
        ("test", "In-game test passes" if tested else ("In-game test ran, not passing yet" if tried else "In-game test"), bool(tested)),
        ("release", "Create a release", bool(rel)),
        ("install", "Install & play", bool(inst)),
        ("restore", "Uninstall & restore files", bool(rest)),
    ]
    return {"steps": [{"key": k, "label": l, "done": v} for k, l, v in steps], "mod_id": (mod or {}).get("id"),
            "release_id": (rel or {}).get("id"), "device_id": (dev or {}).get("id")}
