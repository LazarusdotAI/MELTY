"""Asset engine tests on synthetic Unreal containers (no real game data)."""
import os
import sys
import json
import hashlib
import importlib
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "companion"))
import unreal_fixtures as fx  # noqa: E402
ma = importlib.import_module("melty_assets")

FILES = {"Stalker2/Content/GameLite/Weapons/GunAKM.cfg": fx.STALKER_CFG.encode(),
         "Stalker2/Content/Textures/T_Red.dds": fx.dds_bc1(),
         "Stalker2/Content/Weapons/T_Rifle.uasset": fx.legacy_uasset(),
         "Stalker2/Content/readme.txt": b"hello zone"}


@pytest.fixture
def stalker(tmp_path):
    inst, paks = fx.unreal_game(str(tmp_path / "XboxGames" / "S.T.A.L.K.E.R. 2- Heart of Chornobyl" / "Content"), "Stalker2", "WinGDK",
                                "Stalker2-WinGDK-Shipping.exe", "++UE5+Release-5.1", utf16=True, xbox_manifest=("GSCGameWorld.STALKER2", "1.5.2.0"))
    fx.pak_v11(os.path.join(paks, "pakchunk0-WinGDK.pak"), FILES, compress={"Stalker2/Content/readme.txt", "Stalker2/Content/GameLite/Weapons/GunAKM.cfg"})
    fx.pak_v11(os.path.join(paks, "pakchunk9-WinGDK.pak"), {"Stalker2/Content/secret.bin": b"x" * 64}, encrypted_index=True)
    fx.utoc_v3(os.path.join(paks, "global"), {"Game/shot.wav": b"RIFF....", "Game/rifle.json": b'{"rpm": 800}'}, compress={"Game/rifle.json"})
    return inst, paks


@pytest.fixture
def ron(tmp_path):
    common = tmp_path / "steamapps" / "common"
    inst, paks = fx.unreal_game(str(common / "Ready Or Not"), "ReadyOrNot", "Win64", "ReadyOrNotSteam-Win64-Shipping.exe",
                                "++UE5+Release-5.3", steam_build="18888888")
    from melty_assets import write_pak
    write_pak(os.path.join(paks, "pakchunk0-Windows.pak"), {"ReadyOrNot/Content/Weapons/M4.ini": b"[Weapon]\nDamage=34\n+Attachments=Scope\n"})
    return inst, paks


def test_scan_detects_xbox_stalker_version_and_engine_from_evidence(stalker):
    inst, _ = stalker
    r = ma.scan_game(inst, "S.T.A.L.K.E.R. 2- Heart of Chornobyl")
    assert r["store"] == "Microsoft Store / Xbox" and r["store_version"] == "1.5.2.0"
    assert r["engine"] == "unreal" and r["engine_version"] == "5.1"
    assert r["exe"].endswith("Stalker2-WinGDK-Shipping.exe")
    assert any("build tag" in e for e in r["evidence"])
    states = {os.path.basename(c["path"]): c["state"] for c in r["containers"]}
    assert states == {"pakchunk0-WinGDK.pak": "ok", "pakchunk9-WinGDK.pak": "blocked_by_protection", "global.utoc": "ok"}
    assert r["inventory"][".cfg"] == 1 and r["inventory"][".json"] == 1


def test_scan_ready_or_not_engine_not_hardcoded(ron):
    inst, _ = ron
    r = ma.scan_game(inst, "Ready or Not")
    assert r["engine_version"] == "5.3"  # whatever the exe says, not an assumption
    assert r["store"] == "Steam" and r["store_version"] == "build 18888888"
    c = r["containers"][0]
    assert c["format"] == "pak" and c["version"] == 8 and c["files"] == 1


def test_pak_v11_listing_and_extraction_roundtrip(stalker, tmp_path):
    inst, paks = stalker
    pak = os.path.join(paks, "pakchunk0-WinGDK.pak")
    lst = ma.list_assets(pak, ".cfg")
    assert lst["total"] == 1 and lst["items"][0]["compression"] == "Zlib"
    before = hashlib.sha256(open(pak, "rb").read()).hexdigest()
    out = tmp_path / "ws" / "extracted"
    r = ma.extract(inst, pak, list(FILES), str(out))
    assert len(r["extracted"]) == 4 and not r["problems"] and r["source_untouched"]
    for e in r["extracted"]:
        assert open(e["out"], "rb").read() == FILES[e["path"]]
    assert hashlib.sha256(open(pak, "rb").read()).hexdigest() == before


def test_encrypted_index_is_blocked_not_bypassed(stalker, tmp_path):
    inst, paks = stalker
    with pytest.raises(ma.AssetError) as e:
        ma.extract(inst, os.path.join(paks, "pakchunk9-WinGDK.pak"), ["Stalker2/Content/secret.bin"], str(tmp_path / "o"))
    assert e.value.state == "blocked"


def test_encrypted_entry_reported(tmp_path):
    pak = fx.pak_v11(str(tmp_path / "e.pak"), {"A/x.txt": b"abc", "A/y.txt": b"def"}, encrypted={"A/y.txt"})
    r = ma.extract(str(tmp_path / "game"), pak, ["A/x.txt", "A/y.txt", "A/missing.txt"], str(tmp_path / "out"))
    assert [e["path"] for e in r["extracted"]] == ["A/x.txt"]
    st = {p["path"]: p["state"] for p in r["problems"]}
    assert st == {"A/y.txt": "blocked", "A/missing.txt": "failed"}


def test_iostore_listing_and_extraction(stalker, tmp_path):
    inst, paks = stalker
    toc = os.path.join(paks, "global.utoc")
    info = ma.read_utoc(toc)
    assert info["version"] == 3 and info["compressed"] and not info["encrypted_index"]
    assert sorted(e["path"] for e in info["entries"]) == ["Game/rifle.json", "Game/shot.wav"]
    r = ma.extract(inst, toc, ["Game/rifle.json"], str(tmp_path / "x"))
    assert json.load(open(r["extracted"][0]["out"])) == {"rpm": 800}


def test_refuses_extract_into_game_folder(stalker):
    inst, paks = stalker
    with pytest.raises(ma.AssetError):
        ma.extract(inst, os.path.join(paks, "pakchunk0-WinGDK.pak"), ["Stalker2/Content/readme.txt"], os.path.join(inst, "out"))


def test_disk_space_check(stalker, tmp_path, monkeypatch):
    inst, paks = stalker
    monkeypatch.setattr(ma.shutil, "disk_usage", lambda p: type("U", (), {"free": 10})())
    with pytest.raises(ma.AssetError, match="disk space"):
        ma.extract(inst, os.path.join(paks, "pakchunk0-WinGDK.pak"), ["Stalker2/Content/readme.txt"], str(tmp_path / "o"))


def test_oodle_missing_is_unsupported(tmp_path):
    with pytest.raises(ma.AssetError) as e:
        ma.decompress("Oodle", b"..", 10, None)
    assert e.value.state == "unsupported"


def test_conversions_and_validation(stalker, tmp_path):
    inst, paks = stalker
    r = ma.extract(inst, os.path.join(paks, "pakchunk0-WinGDK.pak"), list(FILES), str(tmp_path / "ext"))
    out = {os.path.splitext(e["path"])[1]: ma.convert_one(e["out"], str(tmp_path / "conv"), {"src_engine": "UE 5.1", "dst_engine": "UE 5.3"})
           for e in r["extracted"]}
    png = out[".dds"]
    assert png["converted"] and png["details"]["encoding"] == "BC1" and png["_thumb"][:4] == b"\x89PNG"
    v = ma.validate_output(png["outputs"][0])
    assert v["ok"] and "8×8" in v["check"]
    cfg = json.load(open(out[".cfg"]["outputs"][0]))
    assert cfg["GunAKM_ST"]["Damage"] == "28.5" and cfg["GunAKM_ST"]["Recoil"]["Vertical"] == "0.42"
    ua = out[".uasset"]
    assert ua["details"]["class"] == "Texture2D" and ua["level"] == "possible_not_implemented" and not ua["converted"]
    assert out[".txt"]["converted"]


def test_bc7_reported_as_not_implemented(tmp_path):
    p = tmp_path / "t.dds"
    p.write_bytes(fx.dds_dx10(98))
    r = ma.convert_one(str(p), str(tmp_path / "o"))
    assert r["level"] == "possible_not_implemented" and not r["converted"]


def test_shader_cache_is_impossible(tmp_path):
    p = tmp_path / "x.ushaderbytecode"
    p.write_bytes(b"\0" * 8)
    assert ma.convert_one(str(p), str(tmp_path / "o"))["level"] == "impossible"


def test_package_build_verify_and_corruption_detected(tmp_path):
    files = {"Stalker2/Content/GameLite/Weapons/GunAKM.cfg": b"Damage = 40\n"}
    out = ma.write_pak(str(tmp_path / "Mod_P.pak"), files)
    v = ma.verify_pak(out, files)
    assert v["ok"] and v["files"] == 1
    assert ma.validate_output(out)["ok"]
    b = bytearray(open(out, "rb").read())
    b[60] ^= 0xFF
    open(out, "wb").write(bytes(b))
    assert not ma.verify_pak(out, files)["ok"]
