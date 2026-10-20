# Companion (stdlib) Cold War metadata-only inspection + local refusal tests. Windows version.dll is mocked.
import os
import sys
import ctypes
import importlib
import pytest
from pathlib import Path


@pytest.fixture()
def comp(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
    sys.modules.pop("melty_companion", None)
    mc = importlib.import_module("melty_companion")
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"forbidden call {a[:1]}"))
    for name in ("download_url", "upload", "http", "bepinex_zip", "install_zip", "dotnet_version"):
        monkeypatch.setattr(mc, name, boom)
    monkeypatch.setattr(mc.subprocess, "Popen", boom)
    monkeypatch.setattr(mc.subprocess, "run", boom)
    yield mc
    sys.modules.pop("melty_companion", None)


def snapshot(d):
    return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in Path(d).rglob("*"))


@pytest.fixture()
def cw_dir(tmp_path):
    d = tmp_path / "Call of Duty Black Ops Cold War"
    (d / "X_Data" / "Managed").mkdir(parents=True)
    (d / "X_Data" / "Managed" / "Assembly-CSharp.dll").write_bytes(b"MZ")
    (d / "X.exe").write_bytes(b"MZ")
    (d / "BlackOpsColdWar.exe").write_bytes(b"MZ-fixture-not-executable")
    return d


def test_version_and_alias(comp):
    assert comp.VERSION == "0.5.0"
    for n in ("Call of Duty®: Black Ops Cold War", "Black Ops Cold War™", "COD Cold War"):
        assert comp.is_cold_war({"name": n})
    assert not comp.is_cold_war({"name": "Cold War", "exe": "coldwar.exe"})
    assert comp.is_cold_war({"name": "x", "exe": "C:\\G\\BlackOpsColdWar.exe"})
    assert comp.is_cold_war({"name": "x", "steam_appid": 1985810})
    assert not comp.is_cold_war({"name": "Call of Duty: Modern Warfare"})


def test_metadata_fixture_no_writes(comp, cw_dir):
    before = snapshot(cw_dir)
    m = comp.cold_war_metadata({"install_dir": str(cw_dir)})
    assert m["installation_exists"] and m["executable_exists"] and m["exe"] == "BlackOpsColdWar.exe"
    assert m["executable_version"] is None and m["inspection_note"]  # non-Windows -> None
    assert snapshot(cw_dir) == before


def test_metadata_missing(comp, tmp_path):
    m = comp.cold_war_metadata({"install_dir": str(tmp_path / "nope")})
    assert m["installation_exists"] is False and m["executable_exists"] is False and m["exe"] is None
    (tmp_path / "empty").mkdir()
    m = comp.cold_war_metadata({"install_dir": str(tmp_path / "empty")})
    assert m["installation_exists"] is True and m["executable_exists"] is False


def test_executable_version_non_windows(comp, cw_dir):
    assert comp.executable_version(str(cw_dir / "BlackOpsColdWar.exe")) is None


def test_executable_version_mocked_windows(comp, cw_dir, monkeypatch):
    from ctypes import wintypes

    class FixedInfo(ctypes.Structure):
        _fields_ = [(k, wintypes.DWORD) for k in ("signature", "struct_version", "file_ms", "file_ls", "product_ms", "product_ls",
                                                 "flags_mask", "flags", "os", "type", "subtype", "date_ms", "date_ls")]
    info = FixedInfo(0xFEEF04BD, 0, (1 << 16) | 34, (5 << 16) | 15931218 % 65536)
    calls = []

    class Fn:
        def __init__(self, f):
            self.f = f

        def __call__(self, *a):
            calls.append(self.f.__name__)
            return self.f(*a)

    def GetFileVersionInfoSizeW(path, _): return 512
    def GetFileVersionInfoW(path, h, size, buf): return 1
    def VerQueryValueW(buf, sub, pptr, plen):
        assert sub == "\\"
        pptr._obj.value = ctypes.addressof(info)
        plen._obj.value = ctypes.sizeof(info)
        return 1

    class Lib:
        pass
    lib = Lib()
    for f in (GetFileVersionInfoSizeW, GetFileVersionInfoW, VerQueryValueW):
        setattr(lib, f.__name__, Fn(f))
    monkeypatch.setattr(comp, "IS_WIN", True)
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, use_last_error=False: lib if name == "version" else None, raising=False)
    assert comp.executable_version(str(cw_dir / "BlackOpsColdWar.exe")) == f"1.34.5.{15931218 % 65536}"
    assert calls == ["GetFileVersionInfoSizeW", "GetFileVersionInfoW", "VerQueryValueW"]
    info.signature = 0
    assert comp.executable_version(str(cw_dir / "BlackOpsColdWar.exe")) is None
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: (_ for _ in ()).throw(OSError("no dll")), raising=False)
    assert comp.executable_version(str(cw_dir / "BlackOpsColdWar.exe")) is None


def test_identify_exe_before_unity(comp, cw_dir):
    i = comp.identify(str(cw_dir))
    assert i["engine"] == "t9" and i["exe"] == "BlackOpsColdWar.exe" and i["managed_dir"] is None


def test_detect_registry_cold_war_without_engine(comp, tmp_path, monkeypatch):
    d = tmp_path / "reg"
    d.mkdir()
    monkeypatch.setattr(comp, "steam_roots", lambda: [])
    monkeypatch.setattr(comp, "launcher_folder_games", lambda: [])
    monkeypatch.setattr(comp, "registry_games", lambda: [
        {"name": "Call of Duty®: Black Ops Cold War", "source": "registry", "install_dir": str(d), "game_version": "1.0"},
        {"name": "Random App", "source": "registry", "install_dir": str(d / ".."), "game_version": None}])
    res, _ = comp.detect_games({}, {})
    names = [g["name"] for g in res["games"]]
    assert names == ["Call of Duty®: Black Ops Cold War"]
    assert res["games"][0]["engine"] == "t9" and res["games"][0]["executable_exists"] is False


def test_inspect_metadata_only(comp, cw_dir):
    g = {"name": "Call of Duty®: Black Ops Cold War", "install_dir": str(cw_dir), "exe": "BlackOpsColdWar.exe", "managed_dir": str(cw_dir / "X_Data" / "Managed")}
    comp.CFG["games"] = [g]
    before = snapshot(cw_dir)
    res, msg = comp.inspect_game({"name": g["name"], "install_dir": str(cw_dir), "metadata_only": True}, {})
    assert "managed" not in res and res["executable_exists"] is True and "no game files changed" in msg
    assert snapshot(cw_dir) == before
    with pytest.raises(RuntimeError):
        comp.inspect_game({"name": g["name"], "install_dir": "/other", "metadata_only": True}, {})


@pytest.mark.parametrize("tc", ["bepinex5-csharp", "ue4ss-lua", "ue3-unrealscript"])
def test_refuse_host_ops(comp, cw_dir, tc):
    g = {"name": "TEST_CW Renamed", "install_dir": str(cw_dir), "exe": "BlackOpsColdWar.exe", "engine": "unity-mono",
         "managed_dir": str(cw_dir / "X_Data" / "Managed")}
    comp.CFG["games"] = [g]
    before = snapshot(cw_dir)
    ws_before = os.path.exists(comp.WS) and snapshot(comp.WS)
    manifest = {"host": {"game": g["name"]}, "files": [], "secondary": [], "launch": {}}
    for fn, p in ((comp.build_mod, {"host_name": g["name"], "toolchain": tc, "files": [{"path": "a.cs", "content": "x"}], "slug": "s"}),
                  (comp.test_mod, {"host_name": g["name"], "toolchain": tc, "manifest": manifest}),
                  (comp.install_package, {"manifest": manifest}),
                  (comp.launch_game, {"manifest": manifest})):
        with pytest.raises(RuntimeError, match="Not supported by MELTY"):
            fn(p, {"id": "j"})
    assert snapshot(cw_dir) == before
    assert (os.path.exists(comp.WS) and snapshot(comp.WS)) == ws_before
