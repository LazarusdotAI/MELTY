#!/usr/bin/env python3
"""MELTY Companion — pairs your Windows PC with the MELTY web app and runs a FIXED list of operations:
detect games, build mods with the .NET SDK, install/uninstall packages with a restore journal, launch/stop games,
read logs and take screenshots. It never runs arbitrary commands sent by the server.

Usage:
  python melty_companion.py pair <APP_URL> <PAIRING_CODE>
  python melty_companion.py run
  python melty_companion.py status
  python melty_companion.py deny <op> | allow <op>
  python melty_companion.py folders add "D:\\Games"
Requires Python 3.9+ (stdlib only). Building mods also needs the .NET 8 SDK (https://dot.net).
"""
import os
import re
import sys
import json
import time
import uuid
import shutil
import hashlib
import zipfile
import platform
import threading
import subprocess
import glob
import urllib.request
import urllib.error

VERSION = "0.5.1"
ASSET_OPS = ["asset_scan", "asset_list", "asset_extract", "asset_convert", "asset_validate", "asset_package",
             "asset_test_package", "asset_install", "asset_cleanup", "setup_tools", "detect_tools", "trainer_install", "trainer_apply", "trainer_status"]
ALL_OPS = ["doctor", "detect_games", "inspect_game", "build_mod", "test_mod", "install_package", "uninstall_package",
           "launch_game", "stop_game", "collect_logs", "screenshot"] + ASSET_OPS
BEPINEX_URL = "https://github.com/BepInEx/BepInEx/releases/download/v5.4.23.2/BepInEx_win_x64_5.4.23.2.zip"
IS_WIN = platform.system() == "Windows"
HOME = os.environ.get("APPDATA") or os.path.expanduser("~")
CFG_DIR = os.path.join(HOME, "MeltyCompanion")
CFG_PATH = os.path.join(CFG_DIR, "config.json")
WS = os.path.join(CFG_DIR, "workspace")
FORBIDDEN_PROJ = re.compile(r"<\s*(Exec|UsingTask|Target|Import)\b", re.I)
PROCS = {}
RESULTS = {}
LOCK = threading.Lock()
NOT_GAME = re.compile(r"^(launcher|social club|unreal engine( \d.*)?|epic games launcher|.*\b(redistributables?|directx|easyanticheat|battleye|crash ?reporter|updater|uninstaller?|helper|service)s?)$", re.I)
SCAN_EVERY = 1800


def load_cfg():
    if os.path.exists(CFG_PATH):
        return json.load(open(CFG_PATH, encoding="utf-8"))
    return {"allowed_ops": ALL_OPS, "extra_folders": [], "games": []}


def save_cfg(c):
    os.makedirs(CFG_DIR, exist_ok=True)
    json.dump(c, open(CFG_PATH, "w", encoding="utf-8"), indent=1)


CFG = load_cfg()
for _op in ALL_OPS:
    if _op not in CFG.get("known_ops", []) and _op not in CFG["allowed_ops"]:
        CFG["allowed_ops"].append(_op)
CFG["known_ops"] = ALL_OPS
MA = None


def assets_module():
    global MA
    if MA is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "melty_assets.py")
        if not os.path.exists(path) and CFG.get("server"):
            code = http("GET", "/api/companion-app/download/melty_assets.py", raw=True)
            compile(code, "melty_assets.py", "exec")
            open(path, "wb").write(code)
        sys.path.insert(0, here)
        import melty_assets
        MA = melty_assets
    return MA


# ---------------- HTTP ----------------
def http(method, path, body=None, raw=False, headers=None, timeout=60):
    url = CFG["server"].rstrip("/") + path
    h = {"X-Device-Token": CFG.get("token", ""), "User-Agent": f"MeltyCompanion/{VERSION}", **(headers or {})}
    data = None
    if body is not None and not isinstance(body, bytes):
        data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
    elif isinstance(body, bytes):
        data = body
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = r.read()
    return out if raw else json.loads(out or b"null")


def upload(job_id, name, data: bytes):
    b = uuid.uuid4().hex
    parts = (f"--{b}\r\nContent-Disposition: form-data; name=\"name\"\r\n\r\n{name}\r\n"
             f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
             f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    return http("POST", f"/api/companion/jobs/{job_id}/artifact", parts,
                headers={"Content-Type": f"multipart/form-data; boundary={b}"}, timeout=180)


def download_url(url, timeout=300):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "MeltyCompanion"}), timeout=timeout) as r:
        return r.read()


def sha256(data: bytes):
    return hashlib.sha256(data).hexdigest()


# ---------------- game detection ----------------
def steam_roots():
    cands = [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam", os.path.expanduser("~/.steam/steam"),
             os.path.expanduser("~/.local/share/Steam"), os.path.expanduser("~/Library/Application Support/Steam")]
    roots = [c for c in cands if os.path.isdir(c)]
    for r in list(roots):
        vdf = os.path.join(r, "steamapps", "libraryfolders.vdf")
        if os.path.exists(vdf):
            for p in re.findall(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8", errors="ignore").read()):
                p = p.replace("\\\\", "\\")
                if os.path.isdir(p) and p not in roots:
                    roots.append(p)
    return roots


def acf_val(txt, key):
    m = re.search(r'"%s"\s+"([^"]*)"' % key, txt)
    return m.group(1) if m else None


def is_cold_war(game):
    name = re.sub(r"[^a-z0-9]", "", (game.get("name") or game.get("game") or "").lower())
    exe = (game.get("exe") or "").replace(chr(92), "/").rsplit("/", 1)[-1].lower()
    return ("blackopscoldwar" in name or name in ("codcoldwar", "callofdutycoldwar")
            or exe == "blackopscoldwar.exe" or str(game.get("steam_appid")) == "1985810"
            or game.get("adapter_id") == "cold-war-t9")


def is_wwii(game):
    name = re.sub(r"[^a-z0-9]", "", (game.get("name") or game.get("game") or "").lower())
    exe = (game.get("exe") or "").replace(chr(92), "/").rsplit("/", 1)[-1].lower()
    return (name in ("callofdutywwii", "codwwii", "callofdutywwiimultiplayer", "callofdutywwiisingleplayer", "callofdutywwiicampaign")
            or exe in ("s2_sp64_ship.exe", "s2_mp64_ship.exe") or str(game.get("steam_appid")) == "476600"
            or game.get("adapter_id") == "cod-wwii-s2")


def wwii_metadata(game, entries=None):
    """List known S2 executables only; never choose a helper or execute a binary."""
    d = game["install_dir"]
    found = False
    if entries is None:
        try:
            entries = os.listdir(d)
        except FileNotFoundError:
            entries = []
        except OSError:
            entries, found = [], None
    campaign = next((e for e in entries if e.lower() == "s2_sp64_ship.exe" and os.path.isfile(os.path.join(d, e))), None)
    multiplayer = next((e for e in entries if e.lower() == "s2_mp64_ship.exe" and os.path.isfile(os.path.join(d, e))), None)
    mode = "multiplayer" if "multiplayer" in (game.get("name") or "").lower() else "campaign"
    return {"engine": "s2", "adapter_id": "cod-wwii-s2", "exe": campaign if mode == "campaign" else multiplayer,
            "campaign_exe": campaign, "multiplayer_exe": multiplayer,
            "campaign_executable_found": True if campaign else found, "wwii_mode": mode,
            "loader_installed": False}


def require_supported_host(game):
    if is_cold_war(game):
        raise RuntimeError("Not supported by MELTY — host compatibility unverified")
    if is_wwii(game):
        raise RuntimeError("Not supported by MELTY — WWII campaign loader compatibility unverified")


def executable_version(path):
    """Read the Windows file-version resource only; never execute or load the game."""
    if not IS_WIN or not os.path.isfile(path):
        return None
    try:
        import ctypes
        from ctypes import wintypes
        class FixedInfo(ctypes.Structure):
            _fields_ = [(key, wintypes.DWORD) for key in (
                "signature", "struct_version", "file_ms", "file_ls", "product_ms", "product_ls",
                "flags_mask", "flags", "os", "type", "subtype", "date_ms", "date_ls")]
        lib = ctypes.WinDLL("version", use_last_error=True)
        lib.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        lib.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        lib.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        lib.GetFileVersionInfoW.restype = wintypes.BOOL
        lib.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        lib.VerQueryValueW.restype = wintypes.BOOL
        unused = wintypes.DWORD()
        size = lib.GetFileVersionInfoSizeW(path, ctypes.byref(unused))
        if not size or size > 1024 * 1024:
            return None
        data = ctypes.create_string_buffer(size)
        if not lib.GetFileVersionInfoW(path, 0, size, data):
            return None
        ptr, length = ctypes.c_void_p(), wintypes.UINT()
        if not lib.VerQueryValueW(data, chr(92), ctypes.byref(ptr), ctypes.byref(length)) or length.value < ctypes.sizeof(FixedInfo):
            return None
        info = ctypes.cast(ptr, ctypes.POINTER(FixedInfo)).contents
        if info.signature != 0xFEEF04BD:
            return None
        return ".".join(str(v) for v in (info.file_ms >> 16, info.file_ms & 65535, info.file_ls >> 16, info.file_ls & 65535))
    except (OSError, ValueError, AttributeError):
        return None


def cold_war_metadata(game):
    d = game["install_dir"]
    exists = os.path.isdir(d)
    exe = None
    try:
        exe = next((e for e in os.listdir(d) if e.lower() == "blackopscoldwar.exe"), None)
    except OSError:
        pass
    path = os.path.join(d, exe) if exe else None
    present = bool(path and os.path.isfile(path))
    version = executable_version(path) if present else None
    return {"install_dir": d, "exe": exe, "engine": "t9", "installation_exists": exists,
            "executable_exists": present, "executable_version": version,
            "inspection_note": None if version else "Executable version unavailable. You can record the displayed version manually; this does not verify compatibility."}


RED_MARKERS = {"cet": "bin/x64/plugins/cyber_engine_tweaks.asi", "redmod": "tools/redmod/bin/redMod.exe", "red4ext": "red4ext/RED4ext.dll",
               "redscript": "engine/tools/scc.exe", "archivexl": "red4ext/plugins/ArchiveXL/ArchiveXL.dll",
               "tweakxl": "red4ext/plugins/TweakXL/TweakXL.dll", "codeware": "red4ext/plugins/Codeware/Codeware.dll"}


def frameworks_in(d, markers):
    return sorted(k for k, m in markers.items() if m and os.path.exists(os.path.join(d, *m.split("/"))))


def exe_version(path):
    try:
        return assets_module().file_version(path)
    except Exception:
        return None


def identify_redengine(d):
    bx = os.path.join(d, "bin", "x64")
    if not (os.path.isdir(bx) and os.path.isdir(os.path.join(d, "archive", "pc", "content"))):
        return None
    exes = [f for f in os.listdir(bx) if f.lower().endswith(".exe") and not re.search(r"(crash|redprelauncher|launcher|unins)", f, re.I)]
    if not exes:
        return None
    exe = os.path.join("bin", "x64", sorted(exes, key=lambda f: (not f.lower().startswith("cyberpunk"), len(f)))[0])
    return {"engine": "redengine4", "exe": exe, "frameworks": frameworks_in(d, RED_MARKERS),
            "engine_version": "REDengine 4", "executable_version": exe_version(os.path.join(d, exe))}


def identify(d):
    info = {"engine": "unknown", "exe": None, "managed_dir": None, "unity_version": None, "company": None, "product": None}
    try:
        entries = os.listdir(d)
    except OSError:
        return info
    red = identify_redengine(d)
    if red:
        return {**info, **red}
    cold_exe = next((e for e in entries if e.lower() == "blackopscoldwar.exe"), None)
    if cold_exe:
        return {**info, "engine": "t9", "exe": cold_exe}
    if any(e.lower() in ("s2_sp64_ship.exe", "s2_mp64_ship.exe") and os.path.isfile(os.path.join(d, e)) for e in entries):
        return {**info, **wwii_metadata({"install_dir": d}, entries)}
    datas = [e for e in entries if e.endswith("_Data") and os.path.isdir(os.path.join(d, e))]
    for data in datas:
        stem = data[:-5]
        exe = stem + ".exe"
        if exe in entries or stem in entries:
            info["exe"] = exe if exe in entries else stem
            mdir = os.path.join(d, data, "Managed")
            if os.path.exists(os.path.join(mdir, "Assembly-CSharp.dll")):
                info["engine"], info["managed_dir"] = "unity-mono", mdir
            elif "GameAssembly.dll" in entries:
                info["engine"] = "unity-il2cpp"
            for f in ("globalgamemanagers", "data.unity3d", "mainData"):
                fp = os.path.join(d, data, f)
                if os.path.exists(fp):
                    head = open(fp, "rb").read(65536)
                    m = re.search(rb"(20\d\d\.\d+\.\d+[abfpx]\d+|[56]\.\d\.\d+[abfp]\d+)", head)
                    if m:
                        info["unity_version"] = m.group(1).decode()
                        break
            ai = os.path.join(d, data, "app.info")
            if os.path.exists(ai):
                lines = open(ai, encoding="utf-8", errors="ignore").read().splitlines()
                info["company"], info["product"] = (lines + [None, None])[:2]
            break
    b64 = os.path.join(d, "Binaries", "Win64")
    if info["engine"] == "unknown" and os.path.isdir(b64):
        gdirs = [e for e in entries if e.endswith("Game") and os.path.isdir(os.path.join(d, e, "Config"))]
        exes = [f for f in os.listdir(b64) if f.lower().endswith(".exe")]
        main = next((f for f in exes if gdirs and f.lower() == gdirs[0].lower() + ".exe"), None)
        if gdirs and main and not any(f.endswith("-Shipping.exe") for f in exes):
            info.update(engine="unreal3", exe=os.path.join("Binaries", "Win64", main), game_folder=gdirs[0],
                        sdk_installed=any(f.lower().endswith("editor.exe") for f in exes))
    if info["engine"] == "unknown" and any(e.lower().startswith("re_chunk_000") for e in entries):
        exes = [e for e in entries if e.lower().endswith(".exe") and "helper" not in e.lower() and "crash" not in e.lower()]
        info.update(engine="re-engine", exe=exes[0] if exes else None,
                    store_locked=("xboxgames" in d.lower() or "windowsapps" in d.lower()))
    if info["engine"] == "unknown":
        for root, dirs, files in os.walk(d):
            if root.count(os.sep) - d.count(os.sep) > 3:
                dirs[:] = []
                continue
            ship = [f for f in files if f.endswith("-Shipping.exe")]
            if ship:
                info["engine"], info["exe"] = "unreal", os.path.relpath(os.path.join(root, ship[0]), d)
                info["ue4ss_installed"] = os.path.exists(os.path.join(root, "UE4SS.dll")) or os.path.exists(os.path.join(root, "ue4ss", "UE4SS.dll"))
                break
        if not info["exe"]:
            exes = [e for e in entries if e.lower().endswith(".exe") and not re.search(r"(unins|crash|setup|redist|launcher|dloguploader)", e, re.I)]
            info["exe"] = exes[0] if exes else None
    return info


def detect_games(_params, _job):
    games = []
    for root in steam_roots():
        for acf in sorted(os.listdir(os.path.join(root, "steamapps")) if os.path.isdir(os.path.join(root, "steamapps")) else []):
            if not acf.startswith("appmanifest_"):
                continue
            txt = open(os.path.join(root, "steamapps", acf), encoding="utf-8", errors="ignore").read()
            name, inst = acf_val(txt, "name"), acf_val(txt, "installdir")
            d = os.path.join(root, "steamapps", "common", inst or "")
            if name and os.path.isdir(d) and not re.search(r"(redistributable|steamworks|proton|runtime|sdk)", name, re.I):
                games.append({"name": name, "source": "steam", "steam_appid": acf_val(txt, "appid"), "install_dir": d,
                              "game_version": "build " + (acf_val(txt, "buildid") or "?")})
    epic = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"
    if os.path.isdir(epic):
        for f in os.listdir(epic):
            if f.endswith(".item"):
                try:
                    j = json.load(open(os.path.join(epic, f), encoding="utf-8"))
                    games.append({"name": j.get("DisplayName"), "source": "epic", "install_dir": j.get("InstallLocation"),
                                  "game_version": j.get("AppVersionString")})
                except Exception:
                    pass
    if IS_WIN:
        try:
            import winreg
            for hp in (r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"):
                try:
                    k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, hp)
                except OSError:
                    continue
                for i in range(winreg.QueryInfoKey(k)[0]):
                    sub = winreg.OpenKey(k, winreg.EnumKey(k, i))
                    try:
                        games.append({"name": winreg.QueryValueEx(sub, "gameName")[0], "source": "gog",
                                      "install_dir": winreg.QueryValueEx(sub, "path")[0],
                                      "game_version": None})
                    except OSError:
                        pass
        except Exception:
            pass
    games += registry_games() + launcher_folder_games()
    for folder in CFG.get("extra_folders", []):
        if os.path.isdir(folder):
            for e in os.listdir(folder):
                d = os.path.join(folder, e)
                if os.path.isdir(d):
                    c = os.path.join(d, "Content")
                    games.append({"name": e, "source": "folder", "install_dir": c if os.path.isdir(c) else d, "game_version": None})
    out, seen = [], set()
    for g in games:
        d = g.get("install_dir")
        if not d or not os.path.isdir(d) or os.path.normcase(os.path.realpath(d)) in seen:
            continue
        g.update(wwii_metadata(g) if is_wwii(g) else cold_war_metadata(g) if is_cold_war(g) else identify(d))
        g["loader_installed"] = os.path.exists(os.path.join(d, "BepInEx", "core", "BepInEx.dll")) or bool(g.get("ue4ss_installed")) or bool(g.get("sdk_installed"))
        if is_wwii(g):
            g["loader_installed"] = False
        if g["source"] in ("folder", "registry") and NOT_GAME.search(g["name"]):
            continue
        if g["source"] in ("folder", "registry") and g["engine"] == "unknown":
            if g["source"] == "registry" or not g["exe"]:
                continue
        seen.add(os.path.normcase(os.path.realpath(d)))
        out.append(g)
    with LOCK:
        CFG["games"] = out
        CFG["last_scan"] = time.time()
        save_cfg(CFG)
    return {"games": out, "count": len(out)}, f"Detected {len(out)} games"


def drives():
    if not IS_WIN:
        return []
    return [f"{c}:\\" for c in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]


def launcher_folder_games():
    """Common install roots used by launchers and by people who install games by hand, on every drive."""
    rel = ["Games", "XboxGames", "GOG Games", "Epic Games", "Program Files\\Epic Games", "Program Files (x86)\\GOG Galaxy\\Games",
           "Program Files\\EA Games", "Program Files (x86)\\Origin Games", "Program Files\\Ubisoft\\Ubisoft Game Launcher\\games",
           "Program Files (x86)\\Ubisoft\\Ubisoft Game Launcher\\games", "Riot Games", "Program Files\\ModifiableWindowsApps",
           "Program Files (x86)\\Battle.net", "Program Files\\Rockstar Games", "Program Files\\WindowsApps"]
    roots = [os.path.join(d, r) for d in drives() for r in rel]
    roots.append(os.path.join(os.environ.get("APPDATA", ""), "itch", "apps"))
    roots.append(os.path.expanduser("~/Games"))
    out = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            for e in os.listdir(root):
                d = os.path.join(root, e)
                if os.path.isdir(d):
                    content = os.path.join(d, "Content")
                    out.append({"name": e, "source": "folder", "install_dir": content if os.path.isdir(content) else d,
                                "game_version": None})
        except OSError:
            pass
    return out


def registry_games():
    """Installed-programs list; kept only when the folder is a recognisable game engine build."""
    if not IS_WIN:
        return []
    import winreg
    out = []
    keys = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in keys:
        try:
            k = winreg.OpenKey(hive, path)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(k)[0]):
            try:
                sub = winreg.OpenKey(k, winreg.EnumKey(k, i))
                name = winreg.QueryValueEx(sub, "DisplayName")[0]
                loc = winreg.QueryValueEx(sub, "InstallLocation")[0]
                ver = None
                try:
                    ver = winreg.QueryValueEx(sub, "DisplayVersion")[0]
                except OSError:
                    pass
                if name and loc:
                    out.append({"name": name, "source": "registry", "install_dir": loc.strip('"'), "game_version": ver})
            except OSError:
                pass
    return out


def find_game(name):
    for g in CFG.get("games", []):
        if g["name"].lower() == (name or "").lower():
            return g
    raise RuntimeError(f"Game '{name}' not found on this PC — run detect_games first")


def inspect_game(p, _job):
    g = find_game(p.get("name"))
    if p.get("install_dir"):
        g = next((x for x in CFG.get("games", []) if x["install_dir"] == p["install_dir"] and x["name"] == p.get("name")), None)
        if not g:
            raise RuntimeError("Detected installation not found — rescan your library first")
    if is_cold_war(g):
        return cold_war_metadata(g), "Read installation metadata only; no game files changed."
    if p.get("metadata_only"):
        raise RuntimeError("Metadata-only assessment is currently available for Cold War only")
    managed = sorted(os.listdir(g["managed_dir"])) if g.get("managed_dir") and os.path.isdir(g["managed_dir"]) else []
    return {"install_dir": g["install_dir"], "managed": [m for m in managed if m.endswith(".dll")][:600],
            "loader_installed": os.path.exists(os.path.join(g["install_dir"], "BepInEx", "core", "BepInEx.dll"))}, ""


# ---------------- journaled install ----------------
def journals():
    d = os.path.join(WS, "installs")
    os.makedirs(d, exist_ok=True)
    return d


def owned_paths():
    owned = {}
    for f in os.listdir(journals()):
        if not f.endswith(".json"):
            continue
        j = json.load(open(os.path.join(journals(), f), encoding="utf-8"))
        if j.get("status") == "installed":
            for e in j["entries"]:
                owned[os.path.normcase(e["dest"])] = j["install_id"]
    return owned


class Journal:
    def __init__(self, host_dir, name):
        self.j = {"install_id": uuid.uuid4().hex, "name": name, "host_dir": host_dir, "entries": [],
                  "status": "installing", "created_at": time.time()}
        self.owned = owned_paths()
        self.bdir = os.path.join(journals(), self.j["install_id"] + "_backup")

    def write(self, rel, data: bytes):
        host = os.path.realpath(self.j["host_dir"])
        dest = os.path.realpath(os.path.join(host, rel))
        if not dest.startswith(host + os.sep):
            raise RuntimeError(f"Refusing to write outside the game folder: {rel}")
        owner = self.owned.get(os.path.normcase(dest))
        if owner:
            raise RuntimeError(f"File conflict: {rel} is owned by another MELTY install ({owner[:8]}). Uninstall it first.")
        entry = {"dest": dest, "rel": rel, "sha256": sha256(data)}
        if os.path.exists(dest):
            os.makedirs(self.bdir, exist_ok=True)
            backup = os.path.join(self.bdir, uuid.uuid4().hex)
            shutil.copy2(dest, backup)
            entry.update(action="replaced", backup=backup)
        else:
            entry["action"] = "created"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "wb").write(data)
        self.j["entries"].append(entry)
        self.save()

    def save(self):
        json.dump(self.j, open(os.path.join(journals(), self.j["install_id"] + ".json"), "w", encoding="utf-8"), indent=1)

    def commit(self):
        self.j["status"] = "installed"
        self.save()


def restore_journal(install_id):
    path = os.path.join(journals(), install_id + ".json")
    if not os.path.exists(path):
        raise RuntimeError("Install journal not found")
    j = json.load(open(path, encoding="utf-8"))
    report = {"restored": 0, "deleted": 0, "modified_kept": []}
    for e in reversed(j["entries"]):
        cur = open(e["dest"], "rb").read() if os.path.exists(e["dest"]) else None
        if cur is not None and sha256(cur) != e["sha256"]:
            report["modified_kept"].append(e["rel"])
        if e["action"] == "replaced":
            shutil.copy2(e["backup"], e["dest"])
            report["restored"] += 1
        elif cur is not None and e["rel"] not in report["modified_kept"]:
            os.remove(e["dest"])
            report["deleted"] += 1
            d = os.path.dirname(e["dest"])
            while d.startswith(j["host_dir"]) and d != j["host_dir"] and os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
                d = os.path.dirname(d)
    j["status"] = "restored"
    json.dump(j, open(path, "w", encoding="utf-8"), indent=1)
    shutil.rmtree(os.path.join(journals(), install_id + "_backup"), ignore_errors=True)
    return report


def bepinex_zip(expected_sha=None):
    cache = os.path.join(WS, "loaders", "BepInEx_5.4.23.2.zip")
    if not os.path.exists(cache):
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        open(cache, "wb").write(download_url(BEPINEX_URL))
    data = open(cache, "rb").read()
    if expected_sha and sha256(data) != expected_sha:
        raise RuntimeError("BepInEx download checksum mismatch")
    return data


def install_zip(jr, data):
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
        for n in z.namelist():
            if not n.endswith("/"):
                jr.write(n, z.read(n))


def install_package(p, _job):
    m = p["manifest"]
    g = find_game(m["host"]["game"])
    require_supported_host(g)
    warnings = []
    sv = m["host"].get("supported_versions") or []
    if sv and g.get("game_version") not in sv:
        warnings.append(f"Game version {g.get('game_version')} is not in the tested list {sv}")
    for s in m.get("secondary", []):
        try:
            find_game(s["game"])
        except RuntimeError:
            warnings.append(f"Secondary game {s['game']} not found — crossover content will be missing")
    root = install_root(g, m.get("install_root", "{host}"), m.get("docs"))
    jr = Journal(root, m["name"])
    try:
        for dep in m.get("dependencies", []):
            if dep.get("name") == "BepInEx" and os.path.exists(os.path.join(g["install_dir"], "BepInEx", "core", "BepInEx.dll")):
                continue
            if dep.get("name") == "UE4SS" and (os.path.exists(os.path.join(root, "UE4SS.dll")) or os.path.exists(os.path.join(root, "ue4ss", "UE4SS.dll"))):
                continue
            data = bepinex_zip(dep.get("sha256")) if dep.get("name") == "BepInEx" else download_url(dep["url"])
            if dep.get("sha256") and sha256(data) != dep["sha256"]:
                raise RuntimeError(f"Checksum mismatch for {dep['name']}")
            install_zip(jr, data)
        for f in m["files"]:
            data = http("GET", "/api/companion/download?path=" + urllib.request.quote(f["storage_path"]), raw=True, timeout=180)
            if sha256(data) != f["sha256"]:
                raise RuntimeError(f"Checksum mismatch for {f['path']}")
            if f.get("kind") == "zip":
                with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
                    for n in z.namelist():
                        if not n.endswith("/"):
                            jr.write(f["path"].rstrip("/") + "/" + n, z.read(n))
            else:
                jr.write(f["path"], data)
        jr.commit()
    except Exception:
        jr.save()
        restore_journal(jr.j["install_id"])
        raise
    e = jr.j["entries"]
    return {"install_id": jr.j["install_id"], "host_dir": root, "warnings": warnings,
            "created": sum(1 for x in e if x["action"] == "created"),
            "replaced": sum(1 for x in e if x["action"] == "replaced")}, "\n".join(warnings)


def uninstall_package(p, _job):
    r = restore_journal(p["install_id"])
    return r, f"Restored {r['restored']} files, removed {r['deleted']}"


# ---------------- launch / logs / screenshot ----------------
def game_env(secondary_names):
    env = dict(os.environ)
    for i, n in enumerate(secondary_names):
        try:
            env[f"MELTY_SECONDARY_{i}_DIR"] = find_game(n)["install_dir"]
        except RuntimeError:
            pass
    return env


def install_root(g, spec, docs=None):
    if spec == "{exe_dir}":
        return os.path.dirname(os.path.join(g["install_dir"], g["exe"]))
    if spec == "{docs}":
        return docs_dir(g, docs)
    return g["install_dir"]


def docs_dir(g, docs):
    base = os.path.join(os.path.expanduser("~"), "Documents", "My Games", docs or g["name"].replace(" ", ""), g.get("game_folder") or "")
    os.makedirs(base, exist_ok=True)
    return base


def launch(g, env, args=None):
    require_supported_host(g)
    exe = os.path.join(g["install_dir"], g["exe"])
    proc = subprocess.Popen([exe] + list(args or []), cwd=os.path.dirname(exe), env=env)
    PROCS[proc.pid] = (proc, os.path.basename(exe))
    return proc


def alive(proc, image):
    if proc.poll() is None:
        return True
    if IS_WIN:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}"], capture_output=True, text=True).stdout
        return image.lower() in out.lower()
    return False


def stop(proc, image):
    if IS_WIN:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        subprocess.run(["taskkill", "/F", "/IM", image], capture_output=True)
    else:
        proc.kill()


def launch_game(p, _job):
    if p.get("after_job") and RESULTS.get(p["after_job"]) != "done":
        raise RuntimeError("Install step did not succeed; not launching")
    m = p["manifest"]
    g = find_game(m["host"]["game"])
    proc = launch(g, game_env([s["game"] for s in m.get("secondary", [])]), (m.get("launch") or {}).get("args"))
    return {"pid": proc.pid, "exe": g["exe"]}, f"Launched {g['exe']} (pid {proc.pid})"


def stop_game(_p, _job):
    for pid, (proc, image) in list(PROCS.items()):
        stop(proc, image)
        PROCS.pop(pid, None)
    return {"stopped": True}, ""


def tail(path, n=200000):
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - n))
        return f.read().decode("utf-8", "ignore")


def player_log(g):
    if not (g.get("company") and g.get("product")):
        return ""
    return os.path.join(os.path.expanduser("~"), "AppData", "LocalLow", g["company"], g["product"], "Player.log")


def collect_logs(p, job):
    g = find_game(p.get("host_name") or p.get("name"))
    bl = tail(os.path.join(g["install_dir"], "BepInEx", "LogOutput.log"))
    pl = tail(player_log(g))
    if bl:
        upload(job["id"], "LogOutput.log", bl.encode())
    if pl:
        upload(job["id"], "Player.log", pl.encode())
    root = install_root(g, "{exe_dir}") if g.get("exe") else g["install_dir"]
    extra = ""
    for lp in [os.path.join(root, "UE4SS.log"), os.path.join(root, "ue4ss", "UE4SS.log")] + \
            glob.glob(os.path.join(g["install_dir"], "bin", "x64", "plugins", "cyber_engine_tweaks", "mods", "*", "*.log")):
        t = tail(lp)
        if "MELTY_READY" in t:
            t = t[t.rfind("MELTY_READY"):]
        if t:
            extra += t
            upload(job["id"], os.path.basename(lp), t.encode())
    text = bl[bl.rfind("MELTY_READY"):] if "MELTY_READY" in bl else bl
    text += "\n" + extra
    checks = {}
    for m in re.findall(r"MELTY_CHECK (\S+) (PASS|FAIL) ?([^\r\n]*)", text):
        checks[m[0]] = {"name": m[0], "pass": m[1] == "PASS", "detail": m[2].strip()}
    return {"bepinex_log_tail": bl[-6000:], "player_log_tail": pl[-4000:], "log_tail": (bl + extra)[-8000:],
            "mod_loaded": "MELTY_READY" in text, "checks": list(checks.values())}, ""


def screenshot_bytes():
    if not IS_WIN:
        return None
    out = os.path.join(WS, "shot.png")
    ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing;$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
          "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;$g=[System.Drawing.Graphics]::FromImage($bmp);"
          "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
          f"$bmp.Save('{out}',[System.Drawing.Imaging.ImageFormat]::Png)")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=30)
    return open(out, "rb").read() if os.path.exists(out) else None


def screenshot(_p, job):
    data = screenshot_bytes()
    if not data:
        raise RuntimeError("Screenshot unavailable on this OS")
    upload(job["id"], "screenshot.png", data)
    return {"screenshot": True}, ""


# ---------------- build & test ----------------
def dotnet_version():
    try:
        return subprocess.run(["dotnet", "--version"], capture_output=True, text=True, timeout=30).stdout.strip() or None
    except Exception:
        return None


def loader_ref_root():
    root = os.path.join(WS, "loaders", "BepInEx_5.4.23.2")
    if not os.path.exists(os.path.join(root, "BepInEx", "core", "BepInEx.dll")):
        with zipfile.ZipFile(__import__("io").BytesIO(bepinex_zip())) as z:
            z.extractall(root)
    return root


def write_tree(dest_root, files, exts):
    for f in files:
        rel = f["path"].replace("\\", "/")
        if ".." in rel.split("/") or rel.startswith("/") or not rel.endswith(exts):
            continue
        dest = os.path.join(dest_root, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "w", encoding="utf-8").write(f["content"])


def ue3_paths(g, p):
    docs = docs_dir(g, p.get("docs"))
    return docs, os.path.join(docs, "Src", p["slug"], "Classes"), os.path.join(docs, "Unpublished", "BrewedPC", "Script", p["slug"] + ".u"), os.path.join(docs, "Logs", "Launch.log")


def build_ue3(p, job, g):
    editor = next((os.path.join(g["install_dir"], "Binaries", "Win64", f) for f in os.listdir(os.path.join(g["install_dir"], "Binaries", "Win64"))
                   if f.lower().endswith("editor.exe")), None)
    if not editor:
        raise RuntimeError(f"{g['name']} SDK not found. In Steam: Library → Tools → install '{g['name']} SDK', then rescan.")
    docs, classes, out_u, log_path = ue3_paths(g, p)
    shutil.rmtree(classes, ignore_errors=True)
    write_tree(classes, [{"path": os.path.basename(f["path"]), "content": f["content"]} for f in p["files"]], (".uc",))
    ini = os.path.join(docs, "Config", "KFEditor.ini" if "kf" in g.get("game_folder", "").lower() else "DefaultEditor.ini")
    if os.path.exists(ini):
        txt = open(ini, encoding="utf-8", errors="ignore").read()
        if f"ModPackages={p['slug']}" not in txt:
            bak = os.path.join(WS, "backups", os.path.basename(ini) + ".orig")
            os.makedirs(os.path.dirname(bak), exist_ok=True)
            if not os.path.exists(bak):
                shutil.copy2(ini, bak)
            txt = txt.replace("[ModPackages]", f"[ModPackages]\nModPackages={p['slug']}", 1) if "[ModPackages]" in txt else txt + f"\n[ModPackages]\nModPackages={p['slug']}\n"
            open(ini, "w", encoding="utf-8").write(txt)
    r = subprocess.run([editor, "make", "-useunpublished", "-full", "-unattended", "-nopause"], capture_output=True, text=True, timeout=600,
                       cwd=os.path.dirname(editor))
    log = tail(log_path) + r.stdout[-4000:]
    errors = sorted(set(l.strip() for l in log.splitlines() if re.search(r"(: Error,|Error:|error:)", l)))[:60]
    upload(job["id"], "build.log", log.encode())
    ok = os.path.exists(out_u) and not errors
    if ok:
        upload(job["id"], p["slug"] + ".u", open(out_u, "rb").read())
    return {"ok": ok, "errors": errors, "warnings": [l for l in log.splitlines() if "Warning," in l][:40]}, log[-15000:]


def build_lua(p, job, g):
    files = [f for f in p["files"] if f["path"].endswith(".lua")]
    if not any(os.path.basename(f["path"]) == "main.lua" for f in files):
        return {"ok": False, "errors": ["Scripts/main.lua is missing"]}, ""
    import io as _io
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in files:
            z.writestr(f"{p['slug']}/Scripts/{os.path.basename(f['path'])}", f["content"])
        z.writestr(f"{p['slug']}/enabled.txt", "")
    upload(job["id"], p["slug"] + ".zip", buf.getvalue())
    return {"ok": True, "errors": [], "warnings": [], "note": "Lua is checked when the game loads it (no compile step)"}, "packaged Lua mod"


def observe(g, p, job, args, log_path, before, res):
    proc = launch(g, game_env(p.get("secondary", [])), args)
    res["launched"] = True
    deadline = time.time() + p.get("seconds", 45)
    while time.time() < deadline:
        time.sleep(3)
    res["alive_at_end"] = alive(proc, os.path.basename(g["exe"]))
    shot = screenshot_bytes()
    if shot:
        upload(job["id"], "screenshot.png", shot)
    text = tail(log_path) if os.path.exists(log_path) and os.path.getmtime(log_path) > before else ""
    res["plugin_loaded"] = "MELTY_READY" in text
    res["plugin_errors"] = [l for l in text.splitlines() if re.search(r"(Error|ScriptWarning|\[Lua\].*error)", l, re.I) and p["slug"].lower() in l.lower()][:20]
    res["checks"] = [{"name": m[0], "pass": m[1] == "PASS", "detail": m[2].strip()} for m in re.findall(r"MELTY_CHECK (\S+) (PASS|FAIL) ?([^\r\n]*)", text)]
    res["bepinex_log_tail"] = text[-8000:]
    if text:
        upload(job["id"], os.path.basename(log_path), text.encode())
    stop(proc, os.path.basename(g["exe"]))
    time.sleep(3)


def test_ue3(p, job, g):
    docs, _, out_u, log_path = ue3_paths(g, p)
    res = {"installed": os.path.exists(out_u), "launched": False, "plugin_loaded": False, "plugin_errors": [], "checks": [],
           "restored": True, "game_version": g.get("game_version"), "alive_at_end": False,
           "note": "UE3 dev builds run from the Unpublished folder; nothing in the game folder is changed"}
    if not res["installed"]:
        raise RuntimeError("Build the mod first")
    before = os.path.getmtime(log_path) if os.path.exists(log_path) else 0
    args = [f"{p.get('map') or 'KF-BioticsLab'}?Mutator={p['slug']}.{p.get('mutator_class') or p['slug']}", "-useunpublished", "-log", "-windowed"]
    observe(g, p, job, args, log_path, before, res)
    return res, ""


def test_lua(p, job, g):
    root = install_root(g, "{exe_dir}")
    log_path = os.path.join(root, "UE4SS.log") if os.path.exists(os.path.join(root, "UE4SS.log")) or not os.path.isdir(os.path.join(root, "ue4ss")) else os.path.join(root, "ue4ss", "UE4SS.log")
    res = {"installed": False, "launched": False, "plugin_loaded": False, "plugin_errors": [], "checks": [], "restored": False,
           "game_version": g.get("game_version"), "alive_at_end": False}
    pkg = http("GET", "/api/companion/download?path=" + urllib.request.quote(p["dll"]["storage_path"]), raw=True, timeout=180)
    jr = Journal(root, "dev-test " + p["slug"])
    try:
        if not (os.path.exists(os.path.join(root, "UE4SS.dll")) or os.path.exists(os.path.join(root, "ue4ss", "UE4SS.dll"))):
            install_zip(jr, download_url(p["loader_url"]))
        mods = "ue4ss/Mods" if os.path.isdir(os.path.join(root, "ue4ss")) else "Mods"
        with zipfile.ZipFile(__import__("io").BytesIO(pkg)) as z:
            for n in z.namelist():
                jr.write(f"{mods}/{n}", z.read(n))
        jr.commit()
        res["installed"] = True
        before = os.path.getmtime(log_path) if os.path.exists(log_path) else 0
        observe(g, p, job, [], log_path, before, res)
    finally:
        try:
            restore_journal(jr.j["install_id"])
            res["restored"] = True
        except Exception as e:
            res["restore_error"] = str(e)
    return res, ""


def build_mod(p, job):
    g = find_game(p["host_name"])
    require_supported_host(g)
    tc = p.get("toolchain", "bepinex5-csharp")
    if tc != "bepinex5-csharp":
        g = find_game(p["host_name"])
        return build_ue3(p, job, g) if tc == "ue3-unrealscript" else build_cet(p, job, g) if tc == "cet-lua" else build_lua(p, job, g)
    if not dotnet_version():
        raise RuntimeError(".NET SDK not found. Install the .NET 8 SDK from https://dot.net and restart the companion.")
    g = find_game(p["host_name"])
    if g.get("engine") != "unity-mono" or not g.get("managed_dir"):
        raise RuntimeError(f"{g['name']} is {g.get('engine')}; only Unity Mono hosts can be built in this release")
    src = os.path.join(WS, "mods", p["slug"])
    shutil.rmtree(src, ignore_errors=True)
    for f in p["files"]:
        rel = f["path"].replace("\\", "/")
        if ".." in rel or rel.startswith("/"):
            raise RuntimeError(f"Bad path {rel}")
        if rel.endswith((".csproj", ".props", ".targets")) and FORBIDDEN_PROJ.search(f["content"]):
            raise RuntimeError(f"{rel} contains build tasks that are blocked by the companion's local policy")
        dest = os.path.join(src, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "w", encoding="utf-8").write(f["content"])
    proj = os.path.join(src, p["slug"] + ".csproj")
    cmd = ["dotnet", "build", proj, "-c", "Release", "-nologo", f"-p:GameDir={loader_ref_root()}",
           f"-p:ManagedDir={g['managed_dir']}", "-p:TreatWarningsAsErrors=false"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=420, cwd=src)
    out = r.stdout + r.stderr
    errors = sorted(set(re.findall(r"[^\r\n]*error (?:CS|MSB|NU)\d+:[^\r\n]*", out)))
    warnings = sorted(set(re.findall(r"[^\r\n]*warning CS\d+:[^\r\n]*", out)))
    dll = None
    for root, _, files in os.walk(os.path.join(src, "bin", "Release")):
        if p["slug"] + ".dll" in files:
            dll = os.path.join(root, p["slug"] + ".dll")
    upload(job["id"], "build.log", out.encode())
    ok = r.returncode == 0 and dll is not None
    if ok:
        upload(job["id"], p["slug"] + ".dll", open(dll, "rb").read())
    return {"ok": ok, "errors": [e.replace(src, "") for e in errors][:60], "warnings": warnings[:60],
            "dotnet": dotnet_version()}, out[-15000:]


def test_mod(p, job):
    g = find_game(p["host_name"])
    require_supported_host(g)
    tc = p.get("toolchain", "bepinex5-csharp")
    if tc == "cet-lua":
        return test_cet(p, job, g)
    if tc == "ue3-unrealscript":
        return test_ue3(p, job, g)
    if tc == "ue4ss-lua":
        return test_lua(p, job, g)
    res = {"installed": False, "launched": False, "plugin_loaded": False, "plugin_errors": [], "checks": [],
           "restored": False, "game_version": g.get("game_version"), "alive_at_end": False}
    dll = http("GET", "/api/companion/download?path=" + urllib.request.quote(p["dll"]["storage_path"]), raw=True, timeout=180)
    if sha256(dll) != p["dll"]["sha256"]:
        raise RuntimeError("Dev build checksum mismatch")
    jr = Journal(g["install_dir"], "dev-test " + p["slug"])
    log_path = os.path.join(g["install_dir"], "BepInEx", "LogOutput.log")
    proc = None
    try:
        if not os.path.exists(os.path.join(g["install_dir"], "BepInEx", "core", "BepInEx.dll")):
            install_zip(jr, bepinex_zip())
        jr.write(f"BepInEx/plugins/{p['slug']}/{p['slug']}.dll", dll)
        jr.commit()
        res["installed"] = True
        before = os.path.getmtime(log_path) if os.path.exists(log_path) else 0
        proc = launch(g, game_env(p.get("secondary", [])))
        res["launched"] = True
        deadline = time.time() + p.get("seconds", 45)
        while time.time() < deadline:
            time.sleep(3)
            if "MELTY_READY" in tail(log_path) and os.path.getmtime(log_path) > before and time.time() > deadline - 5:
                break
        res["alive_at_end"] = alive(proc, os.path.basename(g["exe"]))
        shot = screenshot_bytes()
        if shot:
            upload(job["id"], "screenshot.png", shot)
        text = tail(log_path) if os.path.exists(log_path) and os.path.getmtime(log_path) > before else ""
        res["plugin_loaded"] = "MELTY_READY" in text
        res["plugin_errors"] = [l for l in text.splitlines() if re.search(r"\[(Error|Fatal)", l) and
                                (p["slug"].lower() in l.lower() or p["plugin_guid"] in l)][:20]
        res["checks"] = [{"name": m[0], "pass": m[1] == "PASS", "detail": m[2].strip()}
                         for m in re.findall(r"MELTY_CHECK (\S+) (PASS|FAIL) ?([^\r\n]*)", text)]
        res["bepinex_log_tail"] = text[-8000:]
        if text:
            upload(job["id"], "LogOutput.log", text.encode())
    finally:
        if proc:
            stop(proc, os.path.basename(g["exe"]))
            time.sleep(3)
        try:
            restore_journal(jr.j["install_id"])
            res["restored"] = True
        except Exception as e:
            res["restore_error"] = str(e)
    return res, ""


def doctor(_p, _job):
    return {"python": sys.version.split()[0], "dotnet": dotnet_version(), "os": platform.platform(),
            "steam_roots": steam_roots(), "workspace": WS, "allowed_ops": CFG.get("allowed_ops")}, ""


# ---------------- Asset Workshop (read-only on game files; outputs go to the MELTY workspace) ----------------
def asset_ws(p, sub=""):
    key = re.sub(r"[^a-z0-9]+", "-", (p.get("name") or "game").lower()).strip("-")[:40] + "-" + hashlib.sha1(p["install_dir"].lower().encode()).hexdigest()[:8]
    d = os.path.join(WS, "assets", key, sub)
    os.makedirs(d, exist_ok=True)
    return d


def inside(path, root):
    rp, rr = os.path.realpath(path), os.path.realpath(root)
    return rp == rr or rp.startswith(rr + os.sep)


def known_game_dir(p):
    d = p.get("install_dir") or ""
    if not os.path.isdir(d):
        raise RuntimeError(f"Game folder not found on this PC: {d}")
    return d


def progress_cb(job):
    last = [0.0]

    def cb(pct, msg):
        if job and time.time() - last[0] > 1:
            last[0] = time.time()
            try:
                http("POST", f"/api/companion/jobs/{job['id']}/progress", {"pct": pct, "msg": str(msg)[:200]})
            except Exception:
                pass
    return cb


def asset_scan(p, _job):
    r = assets_module().scan_game(known_game_dir(p), p.get("name", ""), CFG.get("games", []))
    r["workspace"] = asset_ws(p)
    return r, f"Scanned {len(r['containers'])} containers; engine {r['engine']} {r['engine_version'] or '(version not proven)'}"


def asset_list(p, _job):
    d = known_game_dir(p)
    c = p["container"]
    if not inside(c, d) or not c.lower().endswith((".pak", ".utoc")):
        raise RuntimeError("That container is not inside this game's folder")
    r = assets_module().list_assets(c, p.get("filter", ""), int(p.get("offset", 0)), min(int(p.get("limit", 500)), 2000))
    return r, f"{r['total']} matching files"


def asset_extract(p, job):
    d = known_game_dir(p)
    c = p["container"]
    if not inside(c, d):
        raise RuntimeError("That container is not inside this game's folder")
    r = assets_module().extract(d, c, p["paths"][:2000], asset_ws(p, "extracted"), progress_cb(job))
    return r, f"Extracted {len(r['extracted'])} files, {len(r['problems'])} problems; game files untouched: {r['source_untouched']}"


def asset_convert(p, job):
    root = asset_ws(p)
    out = asset_ws(p, "analysis" if p.get("analyze_only") else "converted")
    cb, reps = progress_cb(job), []
    files = p["files"][:500]
    for i, f in enumerate(files):
        cb(int(100 * i / max(1, len(files))), f)
        if not inside(f, root):
            reps.append({"source": f, "level": "unsupported_by_toolkit", "reason": "Only files in the MELTY workspace can be converted", "error": True})
            continue
        sub = os.path.join(out, os.path.dirname(os.path.relpath(f, asset_ws(p, "extracted")))) if inside(f, asset_ws(p, "extracted")) else out
        rep = assets_module().convert_one(f, sub, {"src_engine": p.get("src_engine"), "dst_engine": p.get("dst_engine"), "tools_dir": os.path.join(WS, "tools")})
        thumb = rep.pop("_thumb", None)
        rep["validation"] = [assets_module().validate_output(o) for o in rep["outputs"] if os.path.splitext(o)[1].lower() in (".png", ".wav", ".json")]
        if rep["converted"] and not all(v["ok"] for v in rep["validation"]):
            rep.update(converted=False, error=True, reason="Output failed validation: " + "; ".join(v["check"] for v in rep["validation"] if not v["ok"]))
        if thumb and job:
            try:
                name = f"preview_{i}.png"
                upload(job["id"], name, thumb)
                rep["preview"] = name
            except Exception as e:
                rep["preview_error"] = str(e)[:200]
        reps.append(rep)
    ok = sum(1 for r in reps if r.get("converted"))
    return {"reports": reps, "out_dir": out}, f"Converted {ok} of {len(reps)} files"


def asset_validate(p, _job):
    root = assets_root()
    res = [assets_module().validate_output(f) if inside(f, root) and os.path.exists(f) else {"path": f, "ok": False, "check": "not found in workspace"}
           for f in p["files"][:500]]
    return {"results": res, "all_ok": all(r["ok"] for r in res)}, f"{sum(r['ok'] for r in res)}/{len(res)} valid"


def assets_root():
    return os.path.join(WS, "assets")


def asset_package(p, _job):
    root = assets_root()
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", p.get("package_name") or "MeltyMod")[:60]
    files, personal = {}, False
    for f in p["files"][:2000]:
        src, dest = f["src"], f["dest"].replace("\\", "/").lstrip("/")
        if not inside(src, root) or ".." in dest.split("/"):
            raise RuntimeError(f"Refusing to package {src}: only workspace files with clean in-game paths are allowed")
        personal = personal or f"{os.sep}extracted{os.sep}" in os.path.realpath(src)
        files[dest] = open(src, "rb").read()
    out = os.path.join(asset_ws(p, "packages"), name + "_P.pak")
    if shutil.disk_usage(os.path.dirname(out)).free < sum(map(len, files.values())) * 1.2 + (32 << 20):
        raise RuntimeError("Not enough disk space to build the package")
    assets_module().write_pak(out, files)
    v = assets_module().verify_pak(out, files)
    if not v["ok"]:
        raise RuntimeError(f"Package failed verification: {v}")
    return {"package": out, "size": os.path.getsize(out), "sha256": assets_module().sha256_file(out), "verify": v,
            "personal_use_only": personal}, f"Built and verified {name}_P.pak ({v['files']} files)"


def mods_dir(d):
    _e, paks = assets_module().unreal_layout(d)
    main = [x for x in paks if "engine" not in x.lower()]
    if not main:
        raise RuntimeError("No Content/Paks folder found for this game")
    return os.path.join(sorted(main, key=len)[0], "~mods")


def asset_test_package(p, _job):
    pkg = p["package"]
    if not inside(pkg, assets_root()):
        raise RuntimeError("Package must be in the MELTY workspace")
    info = assets_module().read_pak(pkg)
    target = os.path.join(mods_dir(known_game_dir(p)), os.path.basename(pkg))
    installed = os.path.exists(target) and assets_module().sha256_file(target) == assets_module().sha256_file(pkg)
    checks = [{"check": "Package opens and lists its files", "ok": info["listable"], "detail": f"{len(info['entries'])} files, pak v{info['version']}"},
              {"check": "Nothing encrypted or compressed (loads without keys)", "ok": not any(e["encrypted"] or e["method"] for e in info["entries"])},
              {"check": "Installed copy matches", "ok": installed, "detail": target if installed else "not installed yet"}]
    return {"checks": checks, "package_ok": all(c["ok"] for c in checks[:2]), "installed": installed,
            "note": "Whether the game actually loads it is only proven by launching the game."}, "package checks done"


def asset_install(p, _job):
    d = known_game_dir(p)
    pkg = p["package"]
    if not inside(pkg, assets_root()) or not pkg.lower().endswith(".pak"):
        raise RuntimeError("Only packages built in the MELTY workspace can be installed")
    data = open(pkg, "rb").read()
    rel = os.path.relpath(os.path.join(mods_dir(d), os.path.basename(pkg)), d)
    if shutil.disk_usage(d).free < len(data) + (64 << 20):
        raise RuntimeError("Not enough disk space in the game drive")
    jr = Journal(d, os.path.basename(pkg))
    jr.write(rel, data)
    jr.commit()
    ok = sha256(open(os.path.join(d, rel), "rb").read()) == sha256(data)
    if not ok:
        restore_journal(jr.j["install_id"])
        raise RuntimeError("Installed file did not match the package; rolled back")
    return {"install_id": jr.j["install_id"], "installed_to": rel, "backup_and_journal": True}, f"Installed {rel} (journal {jr.j['install_id'][:8]})"


def detect_tools(p, _job):
    d = known_game_dir(p)
    fw = frameworks_in(d, p.get("markers") or RED_MARKERS)
    return {"install_dir": d, "frameworks": fw}, f"Installed tools: {', '.join(fw) or 'none'}"


def github_zip(repo):
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest", headers={"User-Agent": "MeltyCompanion", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rel = json.loads(r.read())
    zips = [a for a in rel.get("assets", []) if a["name"].lower().endswith(".zip") and not re.search(r"(pdb|symbol|src|source|debug|cli)", a["name"], re.I)]
    if not zips:
        raise RuntimeError(f"No installable zip in the latest {repo} release")
    a = sorted(zips, key=lambda a: ("mod" not in a["name"].lower(), len(a["name"])))[0]
    req = urllib.request.Request(a["browser_download_url"], headers={"User-Agent": "MeltyCompanion"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    if a.get("size") and len(data) != a["size"]:
        raise RuntimeError(f"Download of {a['name']} was incomplete")
    return rel.get("tag_name"), a["name"], data


def setup_tools(p, _job):
    d = known_game_dir(p)
    if shutil.disk_usage(d).free < 500 << 20:
        raise RuntimeError("Less than 500 MB free on the game drive")
    done, logs = [], []
    for t in p["tools"]:
        if t.get("marker") and os.path.exists(os.path.join(d, *t["marker"].split("/"))):
            logs.append(f"{t['name']}: already installed")
            continue
        tag, asset, data = github_zip(t["repo"])
        jr = Journal(d, f"tool {t['name']} {tag}")
        try:
            install_zip(jr, data)
            jr.commit()
        except Exception:
            restore_journal(jr.j["install_id"])
            raise
        ok = not t.get("marker") or os.path.exists(os.path.join(d, *t["marker"].split("/")))
        if not ok:
            restore_journal(jr.j["install_id"])
            raise RuntimeError(f"{t['name']} {tag} installed, but its main file wasn't where expected, so it was removed again")
        done.append({"key": t["key"], "name": t["name"], "version": tag, "asset": asset, "install_id": jr.j["install_id"]})
        logs.append(f"{t['name']} {tag}: installed")
    return {"install_dir": d, "installed": done, "frameworks": frameworks_in(d, p.get("markers") or RED_MARKERS)}, "\n".join(logs)


def trainer_dir(p):
    d = known_game_dir(p)
    rel = p["mod_dir"].replace("\\", "/").strip("/")
    if ".." in rel.split("/") or not rel:
        raise RuntimeError("Bad trainer folder")
    return d, rel, os.path.join(d, *rel.split("/"))


def trainer_install(p, _job):
    d, rel, full = trainer_dir(p)
    jr = Journal(d, "MELTY trainer")
    try:
        for name, content in p["files"].items():
            jr.write(f"{rel}/{name}", content.encode())
        jr.commit()
    except Exception:
        restore_journal(jr.j["install_id"])
        raise
    ok = all(open(os.path.join(full, n), "rb").read() == c.encode() for n, c in p["files"].items())
    if not ok:
        restore_journal(jr.j["install_id"])
        raise RuntimeError("Trainer files didn't match after writing; removed again")
    return {"install_id": jr.j["install_id"], "installed_to": rel}, f"Trainer installed to {rel}"


def game_running(exe):
    if not IS_WIN or not exe:
        return None
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {os.path.basename(exe)}", "/NH"], capture_output=True, text=True).stdout
    return os.path.basename(exe).lower() in out.lower()


def trainer_apply(p, _job):
    _d, _rel, full = trainer_dir(p)
    if not os.path.exists(os.path.join(full, "init.lua")):
        raise RuntimeError("The trainer isn't installed in this game")
    tmp = os.path.join(full, "settings.json.tmp")
    open(tmp, "w", encoding="utf-8").write(json.dumps(p["settings"]))
    os.replace(tmp, os.path.join(full, "settings.json"))
    return {"written": True, "rev": p["settings"].get("rev")}, "settings written"


def trainer_status(p, _job):
    _d, _rel, full = trainer_dir(p)
    g = next((x for x in CFG.get("games", []) if x.get("install_dir") == p["install_dir"]), {})
    sp = os.path.join(full, "status.json")
    st = None
    if os.path.exists(sp):
        try:
            st = json.load(open(sp, encoding="utf-8"))
            st["age_s"] = round(time.time() - os.path.getmtime(sp), 1)
        except Exception as e:
            st = {"error": str(e)}
    running = game_running(g.get("exe"))
    if st and (running is False or st.get("age_s", 0) > 10):
        st["loaded"] = 0 if running is False else st.get("loaded")
        st["in_game"] = False
    return {"install_dir": p["install_dir"], "status": st, "game_running": running}, "status read"


def cet_mods_dir(g):
    return os.path.join(g["install_dir"], "bin", "x64", "plugins", "cyber_engine_tweaks", "mods")


def build_cet(p, job, g):
    files = [f for f in p["files"] if f["path"].endswith(".lua")]
    if not any(os.path.basename(f["path"]) == "init.lua" for f in files):
        return {"ok": False, "errors": ["init.lua is missing"]}, ""
    import io as _io
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in files:
            z.writestr(f"{p['slug']}/{f['path'].replace(chr(92), '/').lstrip('/')}", f["content"])
    upload(job["id"], p["slug"] + ".zip", buf.getvalue())
    return {"ok": True, "errors": [], "warnings": [], "note": "Lua is checked when the game loads it (no compile step)"}, "packaged CET Lua mod"


def test_cet(p, job, g):
    if not os.path.exists(os.path.join(g["install_dir"], *RED_MARKERS["cet"].split("/"))):
        raise RuntimeError("Cyber Engine Tweaks isn't installed in this game yet. Use 'Set up modding tools' first.")
    mods = cet_mods_dir(g)
    log_path = os.path.join(mods, p["slug"], p["slug"] + ".log")
    res = {"installed": False, "launched": False, "plugin_loaded": False, "plugin_errors": [], "checks": [], "restored": False,
           "game_version": g.get("game_version"), "alive_at_end": False}
    pkg = http("GET", "/api/companion/download?path=" + urllib.request.quote(p["dll"]["storage_path"]), raw=True, timeout=180)
    jr = Journal(g["install_dir"], "dev-test " + p["slug"])
    try:
        rel = os.path.relpath(mods, g["install_dir"]).replace(os.sep, "/")
        with zipfile.ZipFile(__import__("io").BytesIO(pkg)) as z:
            for n in z.namelist():
                jr.write(f"{rel}/{n}", z.read(n))
        jr.commit()
        res["installed"] = True
        observe(g, p, job, [], log_path, time.time() - 1, res)
        if not res["plugin_loaded"]:
            sl = os.path.join(os.path.dirname(mods), "scripting.log")
            if os.path.exists(sl):
                t = tail(sl)
                res["plugin_errors"] += [l for l in t.splitlines() if p["slug"].lower() in l.lower() and "error" in l.lower()][:10]
    finally:
        try:
            restore_journal(jr.j["install_id"])
            res["restored"] = True
        except Exception as e:
            res["restore_error"] = str(e)
    return res, ""


def asset_cleanup(p, _job):
    root = asset_ws(p)
    targets = [os.path.join(root, s) for s in (p.get("what") or ["extracted", "converted", "analysis"]) if s in ("extracted", "converted", "analysis", "packages")]
    freed = 0
    for t in targets:
        for dp, _d, fns in os.walk(t):
            freed += sum(os.path.getsize(os.path.join(dp, f)) for f in fns)
        shutil.rmtree(t, ignore_errors=True)
    return {"freed_bytes": freed, "removed": targets}, f"Freed {freed / 1e6:.1f} MB"


HANDLERS = {n: globals()[n] for n in ALL_OPS}


# ---------------- main loop ----------------
def heartbeat_loop():
    while True:
        try:
            http("POST", "/api/companion/heartbeat", {"status": {"version": VERSION, "dotnet": dotnet_version(),
                                                                "running_games": len(PROCS), "python": sys.version.split()[0]}})
        except Exception as e:
            print("heartbeat failed:", e)
        time.sleep(10)


def scan_loop():
    while True:
        try:
            res, _ = detect_games({}, None)
            http("POST", "/api/companion/games", {"games": res["games"]}, timeout=120)
            print(f"[{time.strftime('%H:%M:%S')}] auto-scan: {res['count']} games reported")
        except Exception as e:
            print("auto-scan failed:", e)
        time.sleep(SCAN_EVERY)


def self_update():
    try:
        latest = http("GET", "/api/companion-app/version").get("version")
        if latest and tuple(map(int, latest.split("."))) > tuple(map(int, VERSION.split("."))):
            code = http("GET", "/api/companion-app/download", raw=True)
            compile(code, "melty_companion.py", "exec")
            me = os.path.abspath(__file__)
            open(me + ".new", "wb").write(code)
            open(os.path.join(os.path.dirname(me), "melty_assets.py"), "wb").write(http("GET", "/api/companion-app/download/melty_assets.py", raw=True))
            os.replace(me + ".new", me)
            print(f"Updated companion {VERSION} -> {latest}, restarting...")
            sys.exit(subprocess.call([sys.executable, me, "run"]))
    except Exception as e:
        print("update check failed:", e)


def run():
    if not CFG.get("token"):
        sys.exit("Not paired. Run: python melty_companion.py pair <APP_URL> <CODE>")
    self_update()
    os.makedirs(WS, exist_ok=True)
    save_cfg(CFG)
    try:
        assets_module()
    except Exception as e:
        print("asset tools unavailable:", e)
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threading.Thread(target=scan_loop, daemon=True).start()
    print(f"MELTY Companion {VERSION} connected to {CFG['server']}. Allowed ops: {', '.join(CFG['allowed_ops'])}")
    while True:
        try:
            job = http("GET", "/api/companion/jobs/next").get("job")
        except Exception as e:
            print("poll failed:", e)
            time.sleep(5)
            continue
        if not job:
            time.sleep(2)
            continue
        print(f"[{time.strftime('%H:%M:%S')}] {job['op']}: {job.get('label', '')}")
        try:
            if job["op"] not in CFG["allowed_ops"] or job["op"] not in HANDLERS:
                raise RuntimeError(f"'{job['op']}' is blocked by this PC's local policy")
            result, logtxt = HANDLERS[job["op"]](job.get("params") or {}, job)
            status = "done"
        except Exception as e:
            result, logtxt, status = {"error": str(e), "state": getattr(e, "state", None)}, f"ERROR: {e}", "failed"
            print("  failed:", e)
        RESULTS[job["id"]] = status
        try:
            http("POST", f"/api/companion/jobs/{job['id']}/result", {"status": status, "result": result, "log": logtxt or ""})
        except Exception as e:
            print("could not report result:", e)


def main():
    a = sys.argv[1:]
    if not a and CFG.get("token"):
        run()
    elif not a:
        print(__doc__)
        input("Not paired yet. Use MELTY-Setup.bat from the My PC page. Press Enter to close...")
    elif a[0] == "pair" and len(a) == 3 and CFG.get("token") and CFG.get("server") == a[1].rstrip("/"):
        print("This PC is already paired. Starting the companion...")
        run()
    elif a[0] == "pair" and len(a) == 3:
        CFG["server"] = a[1].rstrip("/")
        try:
            r = http("POST", "/api/companion/pair", {"code": a[2], "hostname": platform.node(), "os": platform.platform(),
                                                 "companion_version": VERSION})
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            sys.exit(f"Pairing failed (HTTP {e.code}): {detail or e.reason}\nGet a fresh code on the My PC page and try again.")
        except urllib.error.URLError as e:
            sys.exit(f"Can't reach {CFG['server']}: {e.reason}")
        CFG.update(token=r["token"], device_id=r["device_id"])
        save_cfg(CFG)
        print("Paired. Starting — your games will be scanned automatically.")
        run()
    elif a[0] == "run":
        run()
    elif a[0] == "status":
        print(json.dumps({k: v for k, v in CFG.items() if k not in ("token", "games")}, indent=1), f"\ngames cached: {len(CFG.get('games', []))}")
    elif a[0] in ("allow", "deny") and len(a) == 2 and a[1] in ALL_OPS:
        ops = set(CFG["allowed_ops"])
        ops.add(a[1]) if a[0] == "allow" else ops.discard(a[1])
        CFG["allowed_ops"] = [o for o in ALL_OPS if o in ops]
        save_cfg(CFG)
        print("Allowed ops:", ", ".join(CFG["allowed_ops"]))
    elif a[0] == "folders" and len(a) == 3 and a[1] == "add":
        CFG.setdefault("extra_folders", []).append(a[2])
        save_cfg(CFG)
        print("Folders:", CFG["extra_folders"])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
