# Offline regression tests for the 2026-10-19 ATLAS failures: trainer CName crash, UE4SS-layout CET packages,
# BepInEx/UE4SS fallthrough for Cyberpunk, reinstall file conflicts, and several companions serving one PC.
# Synthetic fixtures only: passing these does NOT prove anything loads in the real game.
import ast
import hashlib
import io
import json
import sys
import zipfile
import importlib
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture()
def comp(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    sys.path.insert(0, str(BACKEND / "companion"))
    sys.modules.pop("melty_companion", None)
    mc = importlib.import_module("melty_companion")
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"forbidden call {a[:1]}"))
    for name in ("download_url", "upload", "http", "bepinex_zip", "dotnet_version"):
        monkeypatch.setattr(mc, name, boom)
    monkeypatch.setattr(mc.subprocess, "Popen", boom)
    monkeypatch.setattr(mc.subprocess, "run", boom)
    yield mc
    sys.modules.pop("melty_companion", None)


def trainer_lua():
    tree = ast.parse((BACKEND / "trainer.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "LUA" for t in node.targets):
            return node.value.value
    raise AssertionError("LUA not found in trainer.py")


GAME_GLOBALS = ("CName", "Game.", "gamedataStatType", "gameGodModeType", "gameStatModifierType", "RPGManager")


def test_trainer_main_chunk_uses_no_game_globals():
    # CET runs init.lua before it registers CName/Game; touching them at file level killed the trainer on every launch.
    for line in trainer_lua().splitlines():
        top_level = line and not line[0].isspace() and not line.startswith(("--", "local function", "registerForEvent", "end"))
        if top_level:
            assert not any(g in line for g in GAME_GLOBALS), f"game global used at load time: {line}"
    lua = trainer_lua()
    start = lua.index('registerForEvent("onInit"')
    oninit = lua[start:lua.index("\nend)", start)]
    assert 'NAME = CName.new("MeltyTrainer")' in oninit


def names_of(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return sorted(z.namelist())


def test_build_cet_rejects_nested_init(comp, monkeypatch):
    monkeypatch.setattr(comp, "upload", lambda *a: (_ for _ in ()).throw(AssertionError("must not upload a bad package")))
    p = {"slug": "Remix", "files": [{"path": "Scripts/init.lua", "content": "x"}, {"path": "Scripts/main.lua", "content": "x"}]}
    res, _ = comp.build_cet(p, {"id": "j"}, {"name": "Cyberpunk 2077"})
    assert res["ok"] is False and "Remix/init.lua is missing" in res["errors"][0] and "Scripts/init.lua" in res["errors"][0]


def test_build_cet_packages_root_init(comp, monkeypatch):
    got = {}
    monkeypatch.setattr(comp, "upload", lambda jid, name, data: got.update(name=name, data=data))
    p = {"slug": "Remix", "files": [{"path": "init.lua", "content": "x"}, {"path": "Scripts\\main.lua", "content": "y"}]}
    res, _ = comp.build_cet(p, {"id": "j"}, {"name": "Cyberpunk 2077"})
    assert res["ok"] is True and got["name"] == "Remix.zip"
    assert names_of(got["data"]) == ["Remix/Scripts/main.lua", "Remix/init.lua"]


def test_cet_layout_errors(comp):
    assert comp.cet_layout_errors(["Remix/init.lua", "Remix/data/x.lua"], "remix") == []
    ue4ss = comp.cet_layout_errors(["Remix/enabled.txt", "Remix/Scripts/init.lua", "Remix/Scripts/main.lua"], "Remix")
    assert any("init.lua is missing" in e for e in ue4ss) and any("UE4SS" in e for e in ue4ss)
    assert comp.cet_layout_errors(["init.lua"], "Remix")  # no mod folder at all
    assert comp.cet_layout_errors(["A/init.lua", "B/init.lua"], None)  # two mod folders


def test_toolchain_follows_the_game(comp):
    red = {"name": "Cyberpunk 2077", "engine": "redengine4"}
    assert comp.expected_toolchain(red, None) == "cet-lua"
    assert comp.expected_toolchain(red, "cet-lua") == "cet-lua"
    for wrong in ("ue4ss-lua", "bepinex5-csharp"):
        with pytest.raises(RuntimeError, match="Cyber Engine Tweaks"):
            comp.expected_toolchain(red, wrong)
    assert comp.expected_toolchain({"name": "U", "engine": "unity-mono"}, None) == "bepinex5-csharp"
    assert comp.expected_toolchain({"name": "R", "engine": "unreal"}, "ue4ss-lua") == "ue4ss-lua"


def test_test_mod_never_runs_bepinex_for_cyberpunk(comp, monkeypatch):
    g = {"name": "Cyberpunk 2077", "engine": "redengine4", "install_dir": "C:/nowhere", "exe": "bin/x64/Cyberpunk2077.exe"}
    monkeypatch.setattr(comp, "find_game", lambda n: g)
    monkeypatch.setattr(comp, "require_supported_host", lambda g: None)
    with pytest.raises(RuntimeError, match="only loads Cyber Engine Tweaks"):
        comp.test_mod({"host_name": "Cyberpunk 2077", "toolchain": "bepinex5-csharp", "slug": "Remix"}, {"id": "j"})


@pytest.fixture()
def cyberpunk(comp, tmp_path, monkeypatch):
    host = tmp_path / "Cyberpunk 2077"
    host.mkdir()
    g = {"name": "Cyberpunk 2077", "engine": "redengine4", "install_dir": str(host), "exe": "bin/x64/Cyberpunk2077.exe"}
    monkeypatch.setattr(comp, "find_game", lambda n: g)
    monkeypatch.setattr(comp, "require_supported_host", lambda g: None)
    return host


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, c in files.items():
            z.writestr(n, c)
    return buf.getvalue()


def manifest(data, toolchain="cet-lua"):
    return {"id": "remix", "name": "Cyberpunk 2077 x Remix", "toolchain": toolchain, "install_root": "{host}",
            "host": {"game": "Cyberpunk 2077"}, "dependencies": [],
            "files": [{"path": "bin/x64/plugins/cyber_engine_tweaks/mods/", "kind": "zip", "storage_path": "s",
                       "sha256": hashlib.sha256(data).hexdigest()}]}


def journal(comp, iid):
    return json.load(open(Path(comp.journals()) / f"{iid}.json", encoding="utf-8"))


def test_reinstall_replaces_previous_copy(comp, cyberpunk, monkeypatch):
    v1 = zip_bytes({"Remix/init.lua": "v1"})
    monkeypatch.setattr(comp, "http", lambda *a, **k: v1)
    first, _ = comp.install_package({"manifest": manifest(v1)}, {"id": "j1"})
    init = cyberpunk / "bin/x64/plugins/cyber_engine_tweaks/mods/Remix/init.lua"
    assert init.read_text() == "v1" and first["replaced_installs"] == []

    v2 = zip_bytes({"Remix/init.lua": "v2"})
    monkeypatch.setattr(comp, "http", lambda *a, **k: v2)
    second, _ = comp.install_package({"manifest": manifest(v2)}, {"id": "j2"})  # used to fail: "File conflict"
    assert init.read_text() == "v2" and second["replaced_installs"] == [first["install_id"]]
    assert journal(comp, first["install_id"])["status"] == "restored"
    assert journal(comp, second["install_id"])["status"] == "installed"


def test_bad_cet_release_is_refused_and_keeps_old_copy(comp, cyberpunk, monkeypatch):
    good = zip_bytes({"Remix/init.lua": "good"})
    monkeypatch.setattr(comp, "http", lambda *a, **k: good)
    first, _ = comp.install_package({"manifest": manifest(good)}, {"id": "j1"})

    bad = zip_bytes({"Remix/enabled.txt": "", "Remix/Scripts/init.lua": "x", "Remix/Scripts/main.lua": "x"})
    monkeypatch.setattr(comp, "http", lambda *a, **k: bad)
    with pytest.raises(RuntimeError, match="can't load in Cyber Engine Tweaks"):
        comp.install_package({"manifest": manifest(bad)}, {"id": "j2"})
    mods = cyberpunk / "bin/x64/plugins/cyber_engine_tweaks/mods/Remix"
    assert (mods / "init.lua").read_text() == "good" and not (mods / "enabled.txt").exists()
    assert journal(comp, first["install_id"])["status"] == "installed"


def test_cyberpunk_release_with_wrong_toolchain_is_refused(comp, cyberpunk, monkeypatch):
    data = zip_bytes({"Remix/init.lua": "x"})
    monkeypatch.setattr(comp, "http", lambda *a, **k: data)
    with pytest.raises(RuntimeError, match="only loads Cyber Engine Tweaks"):
        comp.install_package({"manifest": manifest(data, toolchain="ue4ss-lua")}, {"id": "j"})
    assert not (cyberpunk / "bin").exists()


def test_trainer_update_replaces_old_trainer(comp, cyberpunk):
    p = {"install_dir": str(cyberpunk), "mod_dir": "bin/x64/plugins/cyber_engine_tweaks/mods/MeltyTrainer"}
    comp.known_game_dir = lambda p: p["install_dir"]
    first, _ = comp.trainer_install({**p, "files": {"init.lua": "old"}}, {"id": "j1"})
    second, _ = comp.trainer_install({**p, "files": {"init.lua": "new"}}, {"id": "j2"})  # used to fail: "File conflict"
    assert (cyberpunk / p["mod_dir"] / "init.lua").read_text() == "new"
    assert journal(comp, first["install_id"])["status"] == "restored"


def test_newest_companion_wins(comp):
    assert comp.is_leader() is False  # nobody claimed yet
    comp.claim_leadership()
    assert comp.is_leader() is True
    json.dump({"pid": -1, "version": "9.9.9"}, open(comp.LEADER_PATH, "w", encoding="utf-8"))  # a newer instance started
    assert comp.is_leader() is False
