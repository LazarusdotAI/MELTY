"""Adapter library: game-specific integration knowledge, supported versions and loaders."""
import re
from fastapi import HTTPException
from core import db, now, new_id

COLD_WAR_REASON = "Not supported by MELTY — host compatibility unverified"
COLD_WAR_ADAPTER = {
    "id": "cold-war-t9", "name": "Black Ops Cold War (T9)", "kind": "game", "engine": "t9",
    "match": {}, "loader": None, "status": "unverified", "hostable": False,
    "host_reason": COLD_WAR_REASON, "integration_methods": [],
    "doc_md": """## Cold War is the intended host — not a substitute
Detected installation, community scripting tools, and working MELTY hosting are separate facts.
Atian Tools documents unofficial T9 scripting and compiler revisions 37 and 38. These are script revisions, not retail game versions or proof of a working, authorized loader.
MELTY has no verified Cold War loading route. Build, install and mod-launch remain unavailable.
Activision's policy covers unauthorized game-modifying software and injectors. No general private-match exemption or account-safety guarantee was established.
""",
}


def is_cold_war(game: dict) -> bool:
    name = re.sub(r"[^a-z0-9]", "", (game.get("name") or game.get("game") or "").lower())
    exe = (game.get("exe") or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return ("blackopscoldwar" in name or name in ("codcoldwar", "callofdutycoldwar")
            or exe == "blackopscoldwar.exe" or str(game.get("steam_appid")) == "1985810"
            or game.get("adapter_id") == "cold-war-t9")


WWII_REASON = "Not supported by MELTY — WWII campaign loader compatibility unverified"
WWII_ADAPTER = {
    "id": "cod-wwii-s2", "name": "Call of Duty: WWII — campaign (S2)", "kind": "game", "engine": "s2",
    "match": {}, "loader": None, "status": "unverified", "hostable": False,
    "host_reason": WWII_REASON, "integration_methods": [],
    "doc_md": """## WWII single-player campaign
The campaign executable is `s2_sp64_ship.exe`. `DLogUploader.exe` is a helper, not the game. Multiplayer uses a separate executable, `s2_mp64_ship.exe`; finding it does not prove campaign files are installed.
MELTY has no verified compatible campaign loader for this installation. This is a campaign integration limitation, not a blanket claim that the campaign is an online game.
S2MP-Mod documents Multiplayer/Zombies use, not campaign hosting. S2x describes its modding support as unfinished. GSC Tool's S2 script compilation support is not a runtime loader.
A Steam library build number is not proof of compatible loading. Single-player use alone does not establish authorization or account safety.
Build, install and mod-launch remain unavailable. No game changes or third-party tool installations are performed by detection.
""",
}


def is_wwii(game: dict) -> bool:
    name = _norm(game.get("name") or game.get("game"))
    exe = (game.get("exe") or "").replace(chr(92), "/").rsplit("/", 1)[-1].lower()
    return (name in ("callofdutywwii", "codwwii", "callofdutywwiimultiplayer", "callofdutywwiisingleplayer", "callofdutywwiicampaign")
            or exe in ("s2_sp64_ship.exe", "s2_mp64_ship.exe") or str(game.get("steam_appid")) == "476600"
            or game.get("adapter_id") == "cod-wwii-s2")


def unverified_reason(game: dict):
    return COLD_WAR_REASON if is_cold_war(game) else WWII_REASON if is_wwii(game) else None


async def reject_unverified_host(game: dict, device_id=None):
    """Re-resolve stored installation identity; never trust a caller's engine/toolchain."""
    reason = unverified_reason(game)
    if reason:
        raise HTTPException(400, reason)
    name = game.get("name") or game.get("game")
    if name:
        q = {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}
        if device_id:
            q["device_id"] = device_id
        async for rec in db.games.find(q, {"_id": 0}):
            reason = unverified_reason(rec)
            if reason:
                raise HTTPException(400, reason)


def unverified_host_status(game: dict) -> dict:
    if is_wwii(game):
        exe = (game.get("exe") or "").replace(chr(92), "/").rsplit("/", 1)[-1]
        if exe.lower() not in ("s2_sp64_ship.exe", "s2_mp64_ship.exe"):
            exe = None
        return {**game, "engine": "s2", "adapter_id": "cod-wwii-s2", "adapter_status": "unverified",
                "hostable": False, "host_reason": WWII_REASON, "toolchain": None, "exe": exe,
                "loader_installed": False}
    if is_cold_war(game):
        return {**game, "engine": "t9", "adapter_id": "cold-war-t9", "adapter_status": "unverified", "hostable": False,
                "host_reason": COLD_WAR_REASON, "toolchain": None}
    return game


def cold_war_report(game: dict) -> dict:
    source = game.get("source")
    reported = game.get("game_version")
    if str(reported).strip().lower() in ("unknown", "build ?", "?", "none", ""):
        reported = None
    return {
        "intended_host": game["name"], "status": "unverified", "status_label": COLD_WAR_REASON,
        "detected": True, "community_tools_documented": True, "melty_loader_supported": False,
        "installation": {"install_dir": game.get("install_dir"), "exe": game.get("exe"),
                         "store": {"steam": "Steam", "epic": "Epic Games", "gog": "GOG", "battle.net": "Battle.net"}.get(source),
                         "detection_source": source, "installation_exists": game.get("installation_exists"),
                         "executable_exists": game.get("executable_exists"),
                         "executable_version": game.get("executable_version"),
                         "reported_version": reported,
                         "manual_version": game.get("cold_war_manual_version"),
                         "checked_at": game.get("compatibility_checked_at"), "detected_at": game.get("detected_at"),
                         "inspection_note": game.get("inspection_note")},
        "missing_prerequisites": [
            "A documented, authorized retail loading route.",
            "Verified compatibility with this specific legitimate game build.",
            "A tested MELTY host adapter with explicit approval before any game changes."],
        "limits": [
            "Script revisions 37 and 38 are not retail build versions or evidence that a mod will load.",
            "No authorized retail loading route was established by the reviewed sources.",
            "No general private-match exemption or account-safety guarantee was established.",
            "This check reads installation metadata only. No game changes, tool installs, binary uploads, or AI credits."],
        "sources": [
            {"id": "atian-tools", "label": "Atian Tools — unofficial T9 scripting capabilities",
             "url": "https://github.com/ate47/atian-cod-tools"},
            {"id": "activision-policy", "label": "Activision — security and enforcement policy",
             "url": "https://support.activision.com/articles/call-of-duty-security-and-enforcement-policy"}],
    }

BEPINEX5 = {"name": "BepInEx", "version": "5.4.23.2",
            "url": "https://github.com/BepInEx/BepInEx/releases/download/v5.4.23.2/BepInEx_win_x64_5.4.23.2.zip",
            "sha256": None, "install_to": "{host}", "license": "LGPL-2.1"}

UE4SS = {"name": "UE4SS", "version": "3.0.1",
         "url": "https://github.com/UE4SS-RE/RE-UE4SS/releases/download/v3.0.1/UE4SS_v3.0.1.zip",
         "sha256": None, "install_to": "{exe_dir}", "license": "MIT"}

RED_TOOLS = [
    {"key": "cet", "name": "Cyber Engine Tweaks", "repo": "maximegmd/CyberEngineTweaks", "marker": "bin/x64/plugins/cyber_engine_tweaks.asi",
     "role": "Runs MELTY's Lua script mods and trainer controls", "required": True},
    {"key": "redmod", "name": "REDmod (official)", "repo": None, "marker": "tools/redmod/bin/redMod.exe",
     "role": "Official mod loader — free DLC from Steam, GOG or Epic", "install_hint": "Install the free REDmod DLC from your game store"},
    {"key": "red4ext", "name": "RED4ext", "repo": "wopss/RED4ext", "marker": "red4ext/RED4ext.dll", "role": "Plugin loader needed by ArchiveXL, TweakXL and Codeware"},
    {"key": "redscript", "name": "redscript", "repo": "jac3km4/redscript", "marker": "engine/tools/scc.exe", "role": "Deeper gameplay scripting"},
    {"key": "archivexl", "name": "ArchiveXL", "repo": "psiberx/cp2077-archive-xl", "marker": "red4ext/plugins/ArchiveXL/ArchiveXL.dll", "role": "Loads new items and assets", "needs": ["red4ext"]},
    {"key": "tweakxl", "name": "TweakXL", "repo": "psiberx/cp2077-tweak-xl", "marker": "red4ext/plugins/TweakXL/TweakXL.dll", "role": "Gameplay data changes", "needs": ["red4ext"]},
    {"key": "codeware", "name": "Codeware", "repo": "psiberx/cp2077-codeware", "marker": "red4ext/plugins/Codeware/Codeware.dll", "role": "Shared scripting library some mods need", "needs": ["red4ext"]},
    {"key": "wolvenkit", "name": "WolvenKit", "repo": None, "marker": None, "role": "Separate desktop app for editing game assets (optional)",
     "install_hint": "Download from wolvenkit.github.io if you want to author new assets"},
]
STATUSES = ("READY TO MOD", "SETUP REQUIRED", "LIMITED SUPPORT", "UNSUPPORTED")

SEED = [
    COLD_WAR_ADAPTER,
    WWII_ADAPTER,
    {"id": "unity-mono-bepinex5", "name": "Unity (Mono) via BepInEx 5", "kind": "engine", "engine": "unity-mono",
     "match": {}, "loader": BEPINEX5, "target_framework": "netstandard2.1", "status": "documented",
     "toolchain": "bepinex5-csharp", "hostable": True,
     "integration_methods": ["host-mod", "asset-source"],
     "doc_md": """## Unity Mono + BepInEx 5
- Plugin: class deriving `BaseUnityPlugin` with `[BepInPlugin(GUID, Name, Version)]`; patch with HarmonyX (`new Harmony(GUID).PatchAll()`).
- Game code lives in `<Game>_Data/Managed/Assembly-CSharp.dll`; reference it, never redistribute it.
- Use `Logger.LogInfo` — output goes to `BepInEx/LogOutput.log` (the companion reads it to verify loading).
- Frame hooks: `Update()` on the plugin MonoBehaviour; scene hooks: `SceneManager.sceneLoaded`.
- Prefer postfix patches; keep prefixes returning `true` unless intentionally replacing behaviour.
- Secondary-game assets: read the path from the env var given in the manifest (e.g. `MELTY_SECONDARY_0_DIR`). Loose files (ogg/wav/png) can be loaded with `UnityWebRequestMultimedia` / `Texture2D.LoadImage`. Unity AssetBundles from another game only load if the Unity versions are compatible; otherwise extract at runtime with a reader library and document the limitation.
- Never ship the other game's files inside the package.
- IL2CPP games need BepInEx 6 (Il2CppInterop) — not supported by this adapter."""},
    {"id": "unity-il2cpp", "name": "Unity (IL2CPP)", "kind": "engine", "engine": "unity-il2cpp", "match": {},
     "loader": None, "status": "unsupported", "integration_methods": [], "hostable": False,
     "host_reason": "Unity IL2CPP needs BepInEx 6 with Il2CppInterop, which isn't supported yet. It can still be a game to borrow from.",
     "doc_md": "IL2CPP builds need BepInEx 6 + Il2CppInterop. Detected, but not supported for building in this release."},
    {"id": "unreal", "name": "Unreal Engine 4/5 via UE4SS (Lua)", "kind": "engine", "engine": "unreal", "match": {},
     "loader": UE4SS, "status": "documented", "toolchain": "ue4ss-lua", "hostable": True,
     "integration_methods": ["host-mod", "mechanic-inspiration"],
     "doc_md": """## Unreal 4/5 + UE4SS Lua
- Mod = `Scripts/main.lua` (+ more .lua files). UE4SS loads `Mods/<ModName>/Scripts/main.lua` when `enabled.txt` exists.
- Print with `print("MELTY_READY <name>\\n")` — output goes to `UE4SS.log` next to the game exe (the companion reads it).
- Hooks: `RegisterHook("/Script/Engine.PlayerController:ClientRestart", fn)`, `NotifyOnNewObject("/Script/Engine.Character", fn)`, `LoopAsync(ms, fn)`, `ExecuteInGameThread(fn)`, `FindFirstOf("PlayerController")`, `RegisterKeyBind(Key.F, fn)`.
- Class/function paths differ per game: discover them defensively (check `obj:IsValid()`), log what you find, and save knowledge notes.
- Games with kernel anti-cheat (EAC/BattlEye online) must only be modded in offline/single-player modes."""},
    {"id": "redengine4", "name": "REDengine 4 via Cyber Engine Tweaks (Lua)", "kind": "engine", "engine": "redengine4", "match": {},
     "loader": None, "status": "documented", "toolchain": "cet-lua", "hostable": True,
     "integration_methods": ["host-mod", "mechanic-inspiration", "asset-source"], "frameworks": RED_TOOLS,
     "capabilities": [
         {"feature": "Gameplay scripts (Lua)", "needs": ["cet"]}, {"feature": "Weapon & item stats", "needs": ["cet"]},
         {"feature": "On-screen HUD widgets (crosshair, indicators)", "needs": ["cet"]},
         {"feature": "Time, weather & game speed", "needs": ["cet"]},
         {"feature": "Deep gameplay scripts (redscript)", "needs": ["redscript"]},
         {"feature": "Tweak database packs", "needs": ["red4ext", "tweakxl"]},
         {"feature": "New items, meshes & textures", "needs": ["red4ext", "archivexl"], "note": "assets authored with WolvenKit"},
         {"feature": "Official REDmod packs", "needs": ["redmod"]}],
     "doc_md": """## REDengine 4 (Cyberpunk 2077) · Cyber Engine Tweaks Lua mod
- Mod folder: `bin/x64/plugins/cyber_engine_tweaks/mods/<slug>/init.lua` (more .lua files allowed; `require("file")`).
- Entry: `registerForEvent("onInit", function() spdlog.info("MELTY_READY <slug>") end)`. Log lines go to `<slug>.log` in the mod folder, which the companion reads. Self-checks: `spdlog.info("MELTY_CHECK name PASS detail")`.
- Runtime: `Game.GetPlayer()` (nil on main menu — check it), `Game.GetStatsSystem()`, `Game.GetTimeSystem():SetTimeDilation("melty", 0.5)`, `TweakDB:GetFlat("Items.Preset_Ajax_Default.magazineCapacity")`, `TweakDB:SetFlat(id, value)` for weapon/item stats, `Game.GetWeatherSystem()`.
- Events: `onUpdate(delta)` for per-frame logic, `onDraw` + ImGui for always-on HUD widgets (crosshair/indicators render in game), `registerHotkey(id, label, fn)` / `registerInput` for keys (user binds them in the CET overlay).
- Verify behaviour in-game by reading values back (e.g. TweakDB:GetFlat after SetFlat) and logging MELTY_CHECK lines.
- Single-player only. Never touch online services."""},
    {"id": "unreal3", "name": "Unreal Engine 3", "kind": "engine", "engine": "unreal3", "match": {}, "loader": None,
     "status": "unsupported", "hostable": False, "integration_methods": [],
     "host_reason": "Unreal Engine 3 games need that game's own SDK. Supported so far: Killing Floor 2.",
     "doc_md": "UE3 mods are UnrealScript packages compiled with the game's editor/SDK."},
    {"id": "game-kf2", "name": "Killing Floor 2", "kind": "game", "engine": "unreal3", "base": "unreal3",
     "match": {"steam_appid": "232090", "exe": "KFGame.exe"}, "loader": None, "status": "documented",
     "toolchain": "ue3-unrealscript", "hostable": True, "docs_name": "KillingFloor2", "game_folder": "KFGame",
     "default_map": "KF-BioticsLab", "integration_methods": ["host-mod", "mechanic-inspiration"],
     "requires": "Killing Floor 2 SDK (free, Steam → Library → Tools)",
     "doc_md": """## Killing Floor 2 · UnrealScript mutator
- Package name = mod slug. Files are `.uc` classes; the main class is `class <Slug> extends KFMutator;` with the same name as the package.
- Built with `KFEditor.exe make -useunpublished` (from the free **Killing Floor 2 SDK**). Output: `Documents/My Games/KillingFloor2/KFGame/Unpublished/BrewedPC/Script/<Slug>.u`.
- Test launch: `KFGame.exe KF-BioticsLab?Mutator=<Slug>.<Slug> -useunpublished -log` (solo/offline). Log: `Documents/My Games/KillingFloor2/KFGame/Logs/Launch.log`.
- Log with `` `log("MELTY_READY <Slug>"); `` in `PostBeginPlay()`, and `` `log("MELTY_CHECK name PASS detail"); `` for self-checks.
- Useful hooks: `ModifyPlayer(Pawn Other)`, `NetDamage(...)`, `ScoreKill(Controller Killer, Controller Killed)`, `CheckReplacement(Actor Other)`, `SetTimer(rate, true, nameof(Tick5))`. Classes: `KFPawn_Human`, `KFPawn_Monster`, `KFGameInfo`, `KFWeapon`.
- Only play modded in solo or on unranked/custom servers. Ranked servers reject mutators."""},
    {"id": "re-engine", "name": "RE Engine", "kind": "engine", "engine": "re-engine", "match": {}, "loader": None,
     "status": "unsupported", "hostable": False, "integration_methods": ["mechanic-inspiration"],
     "host_reason": "RE Engine needs REFramework, which isn't supported yet. Xbox/Game Pass copies are encrypted, so they can't host even with it — the Steam copy can.",
     "doc_md": "REFramework (Lua) supports Steam releases. Microsoft Store / Game Pass builds are encrypted and not moddable."},
    {"id": "blocked-anticheat", "name": "Online games without supported mod loading", "kind": "game", "engine": "iw",
     "match": {"name_regex": "call of duty|valorant|fortnite|apex legends|counter-strike|rainbow six|pubg|warzone|destiny 2|overwatch"},
     "loader": None, "status": "blocked", "hostable": False, "integration_methods": [],
     "host_reason": "MELTY does not support loading mods into this online game. Unauthorized modification can risk account penalties.",
     "doc_md": "No supported MELTY loading route is available. The restriction does not establish which protection technology the game uses."},
    {"id": "game-repo", "name": "R.E.P.O.", "kind": "game", "engine": "unity-mono", "base": "unity-mono-bepinex5",
     "toolchain": "bepinex5-csharp", "hostable": True,
     "match": {"steam_appid": "3241660", "exe": "REPO.exe"}, "loader": BEPINEX5, "target_framework": "netstandard2.1",
     "status": "community-notes", "integration_methods": ["host-mod"],
     "doc_md": "Community-reported host for BepInEx 5 mods (co-op, Photon networking). Not yet verified by this platform — "
               "record a knowledge note after your first successful in-game test."},
    {"id": "game-ultrakill", "name": "ULTRAKILL", "kind": "game", "engine": "unity-mono", "base": "unity-mono-bepinex5",
     "toolchain": "bepinex5-csharp", "hostable": True,
     "match": {"steam_appid": "1229490", "exe": "ULTRAKILL.exe"}, "loader": BEPINEX5,
     "target_framework": "netstandard2.1", "status": "community-notes", "integration_methods": ["host-mod", "asset-source"],
     "doc_md": "Unity Mono game, BepInEx 5 compatible. Can act as an asset source via its install path; assets are "
               "Addressables bundles. Not yet verified by this platform."},
]


async def seed():
    for a in SEED:
        await db.adapters.update_one({"id": a["id"]}, {"$set": {**a, "updated_at": now()},
                                                      "$setOnInsert": {"created_at": now()}}, upsert=True)


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


async def match(game: dict) -> dict:
    """Return the best adapter for a detected game: game-specific first, then engine-level."""
    if is_cold_war(game):
        return dict(COLD_WAR_ADAPTER)
    if is_wwii(game):
        return dict(WWII_ADAPTER)
    async for a in db.adapters.find({"kind": "game"}, {"_id": 0}):
        m = a.get("match", {})
        if m.get("name_regex") and re.search(m["name_regex"], game.get("name") or "", re.I):
            return a
        if (m.get("steam_appid") and str(game.get("steam_appid")) == m["steam_appid"]) or \
                (m.get("exe") and _norm(game.get("exe")) == _norm(m["exe"])) or _norm(a["name"]) == _norm(game.get("name")):
            return a
    return await db.adapters.find_one({"kind": "engine", "engine": game.get("engine")}, {"_id": 0}) or {
        "id": None, "status": "unidentified", "hostable": False,
        "host_reason": "MELTY couldn't tell how this game loads mods yet. Rescan, or set its engine by hand in the game's details — it can still inspire mechanics for another host."}


def tools_for(game: dict, a: dict) -> list:
    have = set(game.get("frameworks") or [])
    return [{"key": t["key"], "name": t["name"], "role": t.get("role"), "installed": t["key"] in have, "required": bool(t.get("required")),
             "installable": bool(t.get("repo")), "install_hint": t.get("install_hint"), "needs": t.get("needs", [])} for t in a.get("frameworks", [])]


def capabilities_for(game: dict, a: dict) -> list:
    have = set(game.get("frameworks") or [])
    return [{**c, "ready": all(n in have for n in c["needs"])} for c in a.get("capabilities", [])]


def mod_status(game: dict, a: dict, hostable: bool) -> str:
    if a.get("status") == "blocked":
        return "UNSUPPORTED"
    if not hostable:
        return "SETUP REQUIRED" if a.get("status") == "unidentified" else "LIMITED SUPPORT"
    tools = tools_for(game, a)
    if any(t["required"] and not t["installed"] for t in tools) or (a.get("toolchain") == "ue3-unrealscript" and game.get("sdk_installed") is False):
        return "SETUP REQUIRED"
    return "READY TO MOD"


def host_info(game: dict, a: dict) -> dict:
    if is_cold_war(game):
        return {"hostable": False, "host_reason": COLD_WAR_REASON, "toolchain": None}
    if is_wwii(game):
        return {"hostable": False, "host_reason": WWII_REASON, "toolchain": None}
    ok, reason = bool(a.get("hostable")), a.get("host_reason")
    if ok and game.get("store_locked"):
        ok, reason = False, "This is a Microsoft Store/Game Pass copy; its files are locked, so mods can't be loaded."
    if ok and a.get("toolchain") == "ue3-unrealscript" and game.get("sdk_installed") is False:
        reason = f"Hostable — first install the {a['name']} SDK (free, Steam → Library → Tools) so mods can be compiled."
    st = mod_status(game, a, ok)
    if st == "SETUP REQUIRED" and ok and not reason:
        missing = [t["name"] for t in tools_for(game, a) if t["required"] and not t["installed"]]
        reason = f"{game.get('name') or 'This game'} can host mods. Some modding tools need setup: {', '.join(missing)}."
    return {"hostable": ok, "host_reason": reason, "toolchain": a.get("toolchain") if ok else None, "mod_status": st,
            "tools": tools_for(game, a), "capabilities": capabilities_for(game, a)}


async def docs_for(names: list) -> str:
    out = []
    base = {"id": None}
    for n in names:
        a = await match({"name": n})
        if a and a["id"] != base["id"]:
            out.append(f"## Adapter: {a['name']} ({a['status']})\n{a['doc_md']}")
        notes = await db.knowledge.find({"game": {"$regex": f"^{re.escape(n)}$", "$options": "i"}}, {"_id": 0}).sort(
            "created_at", -1).to_list(15)
        if notes:
            out.append(f"## What worked before for {n}\n" + "\n".join(
                f"- [{x.get('game_version') or 'any version'}] {x['note']}" for x in notes))
    return "\n\n".join(out)


async def add_note(game: str, note: str, game_version: str = "", source: str = "ai", project_id=None):
    await db.knowledge.insert_one({"id": new_id(), "game": game, "note": note[:1000], "game_version": game_version,
                                   "source": source, "project_id": project_id, "created_at": now()})
