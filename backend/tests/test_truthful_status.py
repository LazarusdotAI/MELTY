# Offline tests: trainer status needs the game's read-back, "Check it worked" reads only the selected mod's log,
# feature checks come from an independent QA list, and Lua syntax is checked before building.
# The trainer Lua runs in LuaJIT 2.1 (CET's engine) against a STUBBED game API: this proves the logic, not the
# real game. Real-game proof still needs CET's log and the Trainer page on the PC.
import ast
import json
import re
import sys
import importlib
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def load_defs(path, names, env=None):
    """Exec only the named top-level defs/assignments of a backend module (its imports need MongoDB/LLM keys)."""
    tree = ast.parse((BACKEND / path).read_text(encoding="utf-8"))
    keep = [n for n in tree.body if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names) or
            (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in names for t in n.targets))]
    ns = {"re": re, "json": json, **(env or {})}
    exec(compile(ast.Module(body=keep, type_ignores=[]), path, "exec"), ns)
    return ns


# ---------- Lua syntax check ----------

def test_lua_syntax_check_uses_the_games_dialect():
    pytest.importorskip("lupa")
    sys.path.insert(0, str(BACKEND))
    ls = importlib.import_module("luasyntax")
    errs, note = ls.lua_syntax_errors([{"path": "init.lua", "content": "local x = = 1"}, {"path": "ok.lua", "content": "local y = 2"},
                                       {"path": "README.md", "content": "not lua = ="}], "cet-lua")
    assert note is None and len(errs) == 1 and errs[0].startswith("init.lua:1:")
    floor_div = [{"path": "Scripts/main.lua", "content": "local a = 7 // 2"}]
    assert ls.lua_syntax_errors(floor_div, "cet-lua")[0], "LuaJIT (CET) has no // operator"
    assert ls.lua_syntax_errors(floor_div, "ue4ss-lua") == ([], None), "Lua 5.4 (UE4SS) does"
    assert ls.lua_syntax_errors([{"path": "a.cs", "content": "x"}], "bepinex5-csharp") == ([], None)


def test_trainer_lua_compiles_in_luajit():
    pytest.importorskip("lupa")
    sys.path.insert(0, str(BACKEND))
    ls = importlib.import_module("luasyntax")
    assert ls.lua_syntax_errors([{"path": "init.lua", "content": trainer_lua()}], "cet-lua") == ([], None)


# ---------- trainer Lua behaviour (LuaJIT + stub game) ----------

def trainer_lua():
    return load_defs("trainer.py", {"LUA"})["LUA"]


HARNESS = r"""
local H = {}
registerForEvent = function(e, f) H[e] = f end
spdlog = { info = function() end }
STORE = { settings = SETTINGS }
json = { decode = function() return STORE.settings end, encode = function(t) STORE.status = t; return "{}" end }
io = { open = function(path, mode)
  if mode == "r" then return { read = function() return "{}" end, close = function() end } end
  return { write = function() end, close = function() end } end }
local OBS = {}
Observe = function(cls, fn, cb) OBS[cls .. "." .. fn] = cb end
CName, Game = nil, nil
assert(loadstring(TRAINER, "=init.lua"))()   -- the real failure: CET runs this before CName/Game exist
CName = { new = function(s) return s end }
H.onInit()
for _ = 1, 5 do H.onUpdate(1.0) end          -- main menu: Game is still nil, so any game call here would error
assert(STORE.status.rev == -1 and STORE.status.in_game == false, "trainer acted before a save was loaded")
OBS["PlayerPuppet.OnGameAttached"]()
H.onUpdate(1.0)                              -- just attached: still settling, must not act yet
assert(STORE.status.rev == -1, "trainer acted before the player settled")
gameGodModeType, gamedataStatType, gameStatModifierType = { Invulnerable = 1 }, { MaxSpeed = 1, JumpHeight = 2 }, { Multiplier = 1 }
local stats, god, dil = { [1] = 5, [2] = 1 }, false, false
RPGManager = { CreateStatModifier = function(stype, _, m) return { stype = stype, m = m } end }
local ss = { GetStatValue = function(_, _, t) return stats[t] end,
  AddModifier = function(_, _, mod) if WORKS then stats[mod.stype] = stats[mod.stype] * mod.m end end,
  RemoveModifier = function() end }
local gm = { AddGodMode = function() if WORKS then god = true end end, RemoveGodMode = function() god = false end,
  HasGodMode = function() return god end }
local ts = { SetTimeDilation = function() if WORKS then dil = true end end, UnsetTimeDilation = function() dil = false end,
  IsTimeDilationActive = function() return dil end, SetGameTimeByHMS = function() end,
  GetGameTime = function() return { Hours = function() return 99 end } end }
local player = { GetEntityID = function() return 7 end }
Game = { GetPlayer = function() return player end, GetGodModeSystem = function() return gm end,
  GetStatsSystem = function() return ss end, GetTimeSystem = function() return ts end }
for _ = 1, 3 do H.onUpdate(1.0) end
local first = STORE.status.rev
OBS["PlayerPuppet.OnDetach"]()               -- back to menu / loading another save
for _ = 1, 2 do H.onUpdate(1.0) end
assert(STORE.status.rev == -1, "trainer kept acting after the player left")
OBS["PlayerPuppet.OnGameAttached"]()
for _ = 1, 4 do H.onUpdate(1.0) end
assert(first == 5 and STORE.status.rev == 5, "trainer didn't re-apply on the next save")
return STORE.status
"""


def run_trainer(works):
    lupa = pytest.importorskip("lupa.luajit21")
    rt = lupa.LuaRuntime()
    g = rt.globals()
    g.TRAINER, g.WORKS = trainer_lua(), works
    g.SETTINGS = rt.eval('{ rev = 5, features = { god_mode = { on = true }, super_speed = { on = true, value = 2 },'
                         ' bullet_time = { on = true, value = 0.5 }, time_of_day = { on = true, value = 8 } } }')
    st = rt.execute(HARNESS)
    return {k: dict(v.items()) for k, v in st["features"].items()}


def test_trainer_reports_verified_only_when_the_game_agrees():
    good, bad = run_trainer(True), run_trainer(False)
    for k in ("god_mode", "super_speed", "bullet_time"):
        assert good[k]["ok"] is True and good[k]["verified"] is True, (k, good[k])
        assert bad[k]["ok"] is True and bad[k]["verified"] is False, (k, bad[k])  # pcall succeeded, effect absent
    assert bad["god_mode"]["info"] == "invulnerable=false"
    assert good["time_of_day"]["verified"] is False and "hour=99" in good["time_of_day"]["info"]  # read back, mismatched


# ---------- trainer status shown in the app ----------

def feature_state():
    return load_defs("trainer.py", {"feature_state"})["feature_state"]


LIVE = {"key": "god_mode", "requires": None}


def state(rep=None, extra=None, on=True):
    status = {"loaded": 1, "in_game": True, "rev": 3, "features": {"god_mode": rep} if rep else {}, **(extra or {})}
    return feature_state()(LIVE, {}, True, True, status, {"god_mode": {"on": on}, "__rev": 3})[0]


def test_trainer_status_needs_the_games_confirmation():
    assert state({"ok": True, "info": "invulnerable=false", "verified": False}) == "Broken"
    assert state({"ok": True, "info": "invulnerable=true", "verified": True}) == "Active"
    assert state({"ok": True, "info": "sent"}) == "Needs Testing"  # old trainer or a feature the game can't report
    assert state({"ok": False, "info": "nil value"}) == "Broken"
    assert state(extra={"load_error": "init.lua:4: attempt to index global 'CName'"}, on=False) == "Broken"
    assert state(extra={"runtime_error": "init.lua:60: boom"}) == "Broken"


# ---------- companion: scoped logs and trainer log errors ----------

@pytest.fixture()
def comp(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    sys.path.insert(0, str(BACKEND / "companion"))
    sys.modules.pop("melty_companion", None)
    mc = importlib.import_module("melty_companion")
    monkeypatch.setattr(mc, "upload", lambda *a, **k: None)
    yield mc
    sys.modules.pop("melty_companion", None)


@pytest.fixture()
def cyberpunk(comp, tmp_path, monkeypatch):
    host = tmp_path / "Cyberpunk 2077"
    mods = host / "bin/x64/plugins/cyber_engine_tweaks/mods"
    for name, body in {"Remix": "old\nMELTY_READY Remix\nMELTY_CHECK squad_spawn PASS ok\n",
                       "Other": "MELTY_READY Other\nMELTY_CHECK squad_spawn FAIL x\nMELTY_CHECK recoil_tweak PASS y\n",
                       "MeltyTrainer": ""}.items():
        (mods / name).mkdir(parents=True)
        (mods / name / f"{name}.log").write_text(body)
    g = {"name": "Cyberpunk 2077", "engine": "redengine4", "install_dir": str(host), "exe": "bin/x64/Cyberpunk2077.exe"}
    monkeypatch.setattr(comp, "find_game", lambda n: g)
    monkeypatch.setattr(comp, "known_game_dir", lambda p: str(host))
    return mods


def test_check_it_worked_reads_only_the_selected_mod(comp, cyberpunk):
    r, _ = comp.collect_logs({"host_name": "Cyberpunk 2077", "slug": "remix", "toolchain": "cet-lua"}, {"id": "j"})
    assert r["mod_loaded"] is True and r["log_source"] == "Remix.log"
    assert r["checks"] == [{"name": "squad_spawn", "pass": True, "detail": "ok"}]  # not Other's FAIL or recoil_tweak
    none, _ = comp.collect_logs({"host_name": "Cyberpunk 2077", "slug": "NotInstalled", "toolchain": "cet-lua"}, {"id": "j"})
    assert none["mod_loaded"] is False and none["checks"] == []  # other mods' MELTY_READY doesn't count


def test_trainer_log_errors_only_count_after_install(comp, cyberpunk):
    p = {"install_dir": str(cyberpunk.parents[4]), "mod_dir": "bin/x64/plugins/cyber_engine_tweaks/mods/MeltyTrainer"}
    log = cyberpunk / "MeltyTrainer" / "MeltyTrainer.log"
    full = str(cyberpunk / "MeltyTrainer")
    log.write_text("sol: runtime error: init.lua:4: attempt to index global 'CName' (a nil value)\n")
    comp.trainer_install({**p, "files": {"init.lua": "fixed"}}, {"id": "j"})
    assert comp.trainer_log_errors(p, full) == {}  # the old trainer's error must not blame the new one
    with open(log, "a") as f:
        f.write("sol: runtime error: init.lua:9: attempt to call a nil value\n")
    assert "init.lua:9" in comp.trainer_log_errors(p, full)["load_error"]
    with open(log, "a") as f:
        f.write("MELTY_READY MeltyTrainer\n")
    assert comp.trainer_log_errors(p, full) == {}
    with open(log, "a") as f:
        f.write("sol: runtime error: init.lua:60: boom\n")
    assert "init.lua:60" in comp.trainer_log_errors(p, full)["runtime_error"]


# ---------- independent feature checks ----------

def checks_ns():
    return load_defs("modagent.py", {"CHECK_NAME", "NOT_FEATURES", "parse_checks", "feature_check_names", "required_checks_text"})


def test_parse_independent_checks():
    ns = checks_ns()
    got = ns["parse_checks"]('Sure! {"checks": [{"name": "Squad Follow", "what": "Squadmates follow V"}, {"name": "loaded", "what": "x"},'
                             ' {"name": "squad_follow", "what": "dupe"}, {"name": "x", "what": "too short"}, "junk",'
                             ' {"name": "harsher_recoil", "what": "Guns kick more"}]}')
    assert [c["name"] for c in got] == ["squad_follow", "harsher_recoil"]
    assert ns["parse_checks"]("no json here") == [] and ns["parse_checks"]('{"checks": "nope"}') == []


def test_required_checks_lead_and_coder_extras_follow():
    ns = checks_ns()
    assert ns["feature_check_names"](["squad_follow"], ["easy_one", "squad_follow", 3]) == ["squad_follow", "easy_one"]
    txt = ns["required_checks_text"]([{"name": "squad_follow", "what": "Squadmates follow V"}])
    assert "MELTY_CHECK <name>" in txt and "- squad_follow: Squadmates follow V" in txt
    assert ns["required_checks_text"]([]) == ""
