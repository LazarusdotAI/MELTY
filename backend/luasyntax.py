"""Compile-only Lua syntax check for Lua mod builds, using the same Lua dialect the game's loader runs.

Cyber Engine Tweaks runs LuaJIT 2.1 and UE4SS runs Lua 5.4. Nothing here executes mod code: Lua's own load()
only compiles the chunk and returns the syntax error, if any. A clean result proves the code parses, not that it
works in the game.
"""
import importlib

ENGINES = {"cet-lua": ("lupa.luajit21", "LuaJIT 2.1"), "ue4ss-lua": ("lupa.lua54", "Lua 5.4")}
_runtimes = {}


def _checker(toolchain):
    if toolchain not in _runtimes:
        mod, _ = ENGINES[toolchain]
        rt = importlib.import_module(mod).LuaRuntime(register_eval=False, register_builtins=False)
        _runtimes[toolchain] = rt.eval("function(src, name) local f, err = (loadstring or load)(src, '=' .. name); return err end")
    return _runtimes[toolchain]


def lua_syntax_errors(files, toolchain):
    """Return (errors, note). errors lists 'path:line: message'; note explains when the check could not run."""
    if toolchain not in ENGINES:
        return [], None
    try:
        check = _checker(toolchain)
    except ImportError:
        return [], "Lua syntax was not checked: the server is missing the 'lupa' package (see requirements.txt)."
    errors = []
    for f in files:
        path = (f.get("path") or "").replace("\\", "/")
        if path.endswith(".lua"):
            err = check(f.get("content") or "", path)
            if err:
                errors.append(str(err))
    return errors, None


def engine_name(toolchain):
    return ENGINES.get(toolchain, (None, "Lua"))[1]
