"""MELTY asset engine (stdlib only). Read-only inspection, extraction and conversion of accessible Unreal game files.
Game files are only ever opened for reading. Encrypted data is reported, never decrypted."""
import os
import re
import json
import zlib
import gzip
import wave
import glob
import time
import shutil
import ctypes
import struct
import hashlib
import subprocess

VERSION = "1"
PAK_MAGIC = 0x5A6F12E1
UTOC_MAGIC = b"-==--==--==--==-"
NONE32 = 0xFFFFFFFF
# feasibility levels shown to the user
LEVELS = {
    "impossible": "Impossible",
    "unsupported_by_toolkit": "Unsupported by the current toolkit",
    "possible_not_implemented": "Technically possible, not built into MELTY yet",
    "possible_with_conversion": "Possible with conversion",
    "possible_recreated_equivalent": "Possible as a recreated equivalent",
    "blocked_by_protection": "Blocked by licensing or security protection",
}
CLASSES = ["SkeletalMesh", "StaticMesh", "AnimSequence", "AnimMontage", "Skeleton", "PhysicsAsset", "Texture2D", "TextureCube",
           "MaterialInstanceConstant", "Material", "SoundWave", "SoundCue", "DataTable", "CurveTable", "BlueprintGeneratedClass",
           "WidgetBlueprintGeneratedClass", "World", "NiagaraSystem", "ParticleSystem"]


class AssetError(Exception):
    def __init__(self, state, msg):
        super().__init__(msg)
        self.state = state


class R:
    def __init__(self, b, p=0):
        self.b, self.p = b, p

    def take(self, n):
        v = self.b[self.p:self.p + n]
        if len(v) < n or n < 0:
            raise ValueError("file is truncated or not in the expected format")
        self.p += n
        return v

    def u8(self): return self.take(1)[0]
    def u16(self): return struct.unpack("<H", self.take(2))[0]
    def u32(self): return struct.unpack("<I", self.take(4))[0]
    def i32(self): return struct.unpack("<i", self.take(4))[0]
    def u64(self): return struct.unpack("<Q", self.take(8))[0]
    def i64(self): return struct.unpack("<q", self.take(8))[0]

    def fstr(self):
        n = self.i32()
        if abs(n) > 1 << 20:
            raise ValueError("bad string length")
        if n == 0:
            return ""
        if n < 0:
            return self.take(-n * 2).decode("utf-16-le", "replace").rstrip("\0")
        return self.take(n).decode("utf-8", "replace").rstrip("\0")


def fstr_bytes(s):
    b = s.encode("utf-8") + b"\0"
    return struct.pack("<i", len(b)) + b


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def clean_mount(m):
    return re.sub(r"^(\.\./)+", "", m.replace("\\", "/"))


# ---------------- Oodle (uses the game's own library; it is compression, not protection) ----------------
def find_oodle(game_dir):
    for pat in ("**/oo2core_*win64.dll", "**/oo2core*.dll", "**/liboo2core*.so"):
        hits = glob.glob(os.path.join(game_dir, pat), recursive=True)
        if hits:
            return hits[0]
    return None


class Oodle:
    def __init__(self, path):
        self.path = path
        lib = ctypes.WinDLL(path) if os.name == "nt" else ctypes.CDLL(path)
        f = lib.OodleLZ_Decompress
        f.restype = ctypes.c_ssize_t
        f.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_int, ctypes.c_int,
                      ctypes.c_int, ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                      ctypes.c_ssize_t, ctypes.c_int]
        self.f = f

    def __call__(self, comp, n):
        out = ctypes.create_string_buffer(n)
        r = self.f(comp, len(comp), out, n, 1, 0, 0, None, 0, None, None, None, 0, 3)
        if r != n:
            raise AssetError("failed", f"Oodle could not unpack a block ({r} of {n} bytes)")
        return out.raw


def decompress(method, comp, n, oodle):
    m = (method or "").lower()
    if m == "zlib":
        return zlib.decompress(comp)[:n]
    if m == "gzip":
        return gzip.decompress(comp)[:n]
    if m == "oodle":
        if not oodle:
            raise AssetError("unsupported", "This file is Oodle-compressed and no Oodle library (oo2core_*.dll) was found in the game folder. "
                                            "Many UE5 games build Oodle into the .exe, so MELTY cannot unpack it with the game's own unpacker.")
        return oodle(comp, n)
    raise AssetError("unsupported", f"Compression '{method}' is not supported by MELTY yet")


# ---------------- .pak ----------------
def pak_footer(f, size):
    for fs in (221, 222, 189, 61, 44):
        if size < fs:
            continue
        f.seek(size - fs)
        b = f.read(fs)
        mp = 0 if fs == 44 else 17
        magic, ver = struct.unpack_from("<II", b, mp)
        ok = {221: ver in (8, 10, 11), 222: ver == 9, 189: ver == 8, 61: ver == 7, 44: 1 <= ver < 7}[fs]
        if magic != PAK_MAGIC or not ok:
            continue
        r = R(b, mp + 8)
        off, isz = r.i64(), r.i64()
        r.take(20)
        if ver == 9:
            r.u8()
        methods = []
        if ver >= 8:
            for _ in range(4 if fs == 189 else 5):
                nm = r.take(32).split(b"\0")[0].decode("ascii", "replace")
                if nm:
                    methods.append(nm)
        return {"version": ver, "index_offset": off, "index_size": isz, "methods": methods,
                "encrypted_index": fs != 44 and b[16] != 0, "key_guid": b[:16].hex() if fs != 44 else ""}
    raise AssetError("unsupported", "Not a readable Unreal .pak file (no pak footer found)")


def entry_header_size(ver, compressed, nblocks):
    return 8 * 3 + 4 + (8 if ver == 1 else 0) + 20 + ((4 + 16 * nblocks if compressed else 0) + 5 if ver >= 3 else 0)


def legacy_entry(r, ver, methods):
    off, size, usize = r.i64(), r.i64(), r.i64()
    raw = r.u32()
    if ver == 1:
        r.u64()
    r.take(20)
    blocks, enc, bs = [], False, 0
    if ver >= 3:
        if raw:
            blocks = [(r.i64(), r.i64()) for _ in range(r.u32())]
        enc, bs = r.u8() != 0, r.u32()
    method = (methods[raw - 1] if 0 < raw <= len(methods) else f"#{raw}") if ver >= 8 and raw else \
        ({0: None, 1: "Zlib", 2: "Gzip", 4: "Oodle"}.get(raw, f"flags{raw}") if raw else None)
    return {"offset": off, "size": size, "usize": usize, "method": method, "blocks": blocks, "encrypted": enc,
            "block_size": bs, "hdr": entry_header_size(ver, bool(raw), len(blocks))}


def encoded_entry(buf, p, methods):
    v = struct.unpack_from("<I", buf, p)[0]
    p += 4
    if v & 0x3F == 0x3F:
        bs = struct.unpack_from("<I", buf, p)[0]
        p += 4
    else:
        bs = (v & 0x3F) << 11

    def num(safe):
        nonlocal p
        fmt, n = ("<I", 4) if safe else ("<Q", 8)
        x = struct.unpack_from(fmt, buf, p)[0]
        p += n
        return x
    midx = (v >> 23) & 0x3F
    off = num(v >> 31 & 1)
    usize = num(v >> 30 & 1)
    size = num(v >> 29 & 1) if midx else usize
    enc = bool(v >> 22 & 1)
    nb = (v >> 6) & 0xFFFF
    hdr = 8 * 3 + 4 + 20 + (4 + 16 * nb if midx else 0) + 5
    blocks = []
    if nb == 1 and not enc:
        blocks = [(hdr, hdr + size)]
    elif nb:
        o = hdr
        for _ in range(nb):
            bsz = struct.unpack_from("<I", buf, p)[0]
            p += 4
            blocks.append((o, o + bsz))
            o += (bsz + 15) // 16 * 16 if enc else bsz
    return {"offset": off, "size": size, "usize": usize, "method": (methods[midx - 1] if midx <= len(methods) else f"#{midx}") if midx else None,
            "blocks": blocks, "encrypted": enc, "block_size": bs or usize, "hdr": hdr}


def read_pak(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        ft = pak_footer(f, size)
        info = {"format": "pak", "path": path, "size": size, **ft, "entries": [], "listable": False, "issues": []}
        if ft["encrypted_index"]:
            info["issues"].append("The file list inside this .pak is encrypted. MELTY does not decrypt game files.")
            return info
        f.seek(ft["index_offset"])
        r = R(f.read(ft["index_size"]))
        mount = clean_mount(r.fstr())
        n = r.i32()
        ver = ft["version"]
        if ver < 10:
            for _ in range(n):
                name = r.fstr()
                info["entries"].append({"path": mount + name, **legacy_entry(r, ver, ft["methods"])})
        else:
            r.u64()
            if r.u32():
                r.i64(); r.i64(); r.take(20)
            has_full = r.u32()
            fdi = (r.i64(), r.i64()) if has_full else None
            if has_full:
                r.take(20)
            enc = r.take(r.i32())
            non = [legacy_entry(r, ver, ft["methods"]) for _ in range(r.i32())]
            if not fdi:
                info["issues"].append("This .pak only stores hashed file names, so its file list cannot be shown.")
                return info
            f.seek(fdi[0])
            d = R(f.read(fdi[1]))
            for _ in range(d.i32()):
                dname = d.fstr()
                for _ in range(d.i32()):
                    fname, loc = d.fstr(), d.i32()
                    e = encoded_entry(enc, loc, ft["methods"]) if loc >= 0 else non[-loc - 1]
                    info["entries"].append({"path": (mount + dname.lstrip("/") + fname).replace("//", "/"), **e})
        info["listable"] = True
        info["mount"] = mount
        enc_n = sum(1 for e in info["entries"] if e["encrypted"])
        if enc_n:
            info["issues"].append(f"{enc_n} of {len(info['entries'])} files inside are encrypted and cannot be extracted.")
    return info


def pak_entry_bytes(f, e, ver, oodle):
    if e["encrypted"]:
        raise AssetError("blocked", "This file is encrypted inside the .pak. MELTY does not break encryption.")
    if not e["method"]:
        f.seek(e["offset"] + e["hdr"])
        return f.read(e["size"])
    base = e["offset"] if ver >= 5 else 0
    out, left = bytearray(), e["usize"]
    for s, t in e["blocks"]:
        f.seek(base + s)
        n = min(e["block_size"] or left, left)
        out += decompress(e["method"], f.read(t - s), n, oodle)
        left -= n
    return bytes(out[:e["usize"]])


# ---------------- IoStore .utoc/.ucas ----------------
def read_utoc(path):
    b = open(path, "rb").read()
    if b[:16] != UTOC_MAGIC:
        raise AssetError("unsupported", "Not an IoStore .utoc file")
    r = R(b, 16)
    ver = r.u8(); r.u8(); r.u16()
    hsize, n, nblk, blk_sz, ncm, cml, cbs, dis, parts = (r.u32() for _ in range(9))
    r.u64()
    r.take(16)
    flags = r.u8(); r.u8(); r.u16()
    nseeds, psize, nnoph = r.u32(), r.u64(), r.u32()
    p = hsize + 12 * n
    offs = [(int.from_bytes(b[p + 10 * i:p + 10 * i + 5], "big"), int.from_bytes(b[p + 10 * i + 5:p + 10 * i + 10], "big")) for i in range(n)]
    p += 10 * n
    if ver >= 4:
        p += 4 * nseeds
    if ver >= 5:
        p += 4 * nnoph
    blocks = []
    for i in range(nblk):
        e = b[p + i * blk_sz:p + i * blk_sz + 12]
        blocks.append((int.from_bytes(e[0:5], "little"), int.from_bytes(e[5:8], "little"), int.from_bytes(e[8:11], "little"), e[11]))
    p += nblk * blk_sz
    methods = [b[p + i * cml:p + (i + 1) * cml].split(b"\0")[0].decode("ascii", "replace") for i in range(ncm)]
    p += ncm * cml
    if flags & 4:
        hs = struct.unpack_from("<i", b, p)[0]
        p += 4 + hs * 2 + 20 * nblk
    info = {"format": "iostore", "path": path, "size": os.path.getsize(path), "version": ver, "chunks": n,
            "compressed": bool(flags & 1), "encrypted_index": bool(flags & 2), "signed": bool(flags & 4), "indexed": bool(flags & 8),
            "methods": methods, "block_size": cbs, "partition_size": psize if ver >= 3 else 0, "entries": [], "listable": False,
            "issues": [], "_offs": offs, "_blocks": blocks}
    if flags & 2:
        info["issues"].append("This IoStore container is encrypted. MELTY does not decrypt game files.")
        return info
    if not (flags & 8) or not dis:
        info["issues"].append("This container has no file-name index, so only chunk counts can be shown.")
        return info
    d = R(b[p:p + dis])
    mount = clean_mount(d.fstr())
    dirs = [(d.u32(), d.u32(), d.u32(), d.u32()) for _ in range(d.i32())]
    files = [(d.u32(), d.u32(), d.u32()) for _ in range(d.i32())]
    strings = [d.fstr() for _ in range(d.i32())]

    def walk(i, prefix, depth=0):
        name, child, _sib, fe = dirs[i]
        path_ = prefix + (strings[name] + "/" if name != NONE32 else "")
        while fe != NONE32:
            fname, nxt, ud = files[fe]
            o, ln = offs[ud]
            info["entries"].append({"path": (mount + path_ + strings[fname]).replace("//", "/"), "usize": ln, "size": ln,
                                    "toc_index": ud, "encrypted": False, "method": None})
            fe = nxt
        while child != NONE32 and depth < 64:
            walk(child, path_, depth + 1)
            child = dirs[child][2]
    if dirs:
        walk(0, "")
    info["listable"] = True
    return info


def iostore_entry_bytes(toc, e, oodle):
    off, ln = toc["_offs"][e["toc_index"]]
    cbs, base = toc["block_size"], toc["path"][:-5]
    out = bytearray()
    handles = {}
    try:
        for bi in range(off // cbs, (off + ln - 1) // cbs + 1):
            boff, csz, usz, mi = toc["_blocks"][bi]
            part = boff // toc["partition_size"] if toc["partition_size"] else 0
            ucas = base + (".ucas" if part == 0 else f"_s{part}.ucas")
            if ucas not in handles:
                if not os.path.exists(ucas):
                    raise AssetError("failed", f"Missing data file {os.path.basename(ucas)}")
                handles[ucas] = open(ucas, "rb")
            fh = handles[ucas]
            fh.seek(boff - part * (toc["partition_size"] or 0))
            comp = fh.read(csz)
            out += comp[:usz] if mi == 0 else decompress(toc["methods"][mi - 1], comp, usz, oodle)
    finally:
        for h in handles.values():
            h.close()
    s = off % cbs
    return bytes(out[s:s + ln])


def open_container(path):
    return read_pak(path) if path.lower().endswith(".pak") else read_utoc(path)


# ---------------- engine & version evidence ----------------
def file_version(path):
    if os.name != "nt" or not os.path.exists(path):
        return None
    try:
        v = ctypes.windll.version
        n = v.GetFileVersionInfoSizeW(path, None)
        if not n:
            return None
        buf = ctypes.create_string_buffer(n)
        v.GetFileVersionInfoW(path, 0, n, buf)
        p, ln = ctypes.c_void_p(), ctypes.c_uint()
        if not v.VerQueryValueW(buf, "\\", ctypes.byref(p), ctypes.byref(ln)):
            return None
        ms, ls = struct.unpack_from("<II", ctypes.string_at(p.value, ln.value), 8)
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return None


BUILD_RE = re.compile(rb"\+\+UE([45])\+Release-(\d\.\d+)")
BUILD_RE16 = re.compile(rb"\+\x00\+\x00U\x00E\x00[45]\x00\+\x00R\x00e\x00l\x00e\x00a\x00s\x00e\x00-\x00((?:[0-9.]\x00){3,5})")


def exe_build_strings(exe, cap=400 << 20):
    found = set()
    with open(exe, "rb") as f:
        prev, read = b"", 0
        while read < cap:
            c = f.read(8 << 20)
            if not c:
                break
            read += len(c)
            blob = prev + c
            for m in BUILD_RE.finditer(blob):
                found.add(m.group(2).decode())
            for m in BUILD_RE16.finditer(blob):
                found.add(m.group(1).decode("utf-16-le", "ignore").strip("."))
            prev = c[-128:]
    return sorted(found)


def store_info(install_dir):
    out = {"store": None, "store_version": None, "package_name": None}
    low = install_dir.lower()
    if "xboxgames" in low or "windowsapps" in low or "modifiablewindowsapps" in low:
        out["store"] = "Microsoft Store / Xbox"
    cands = []
    d = install_dir
    for _ in range(3):
        cands += [os.path.join(d, "appxmanifest.xml"), os.path.join(d, "MicrosoftGame.config"), os.path.join(d, "Content", "appxmanifest.xml"),
                  os.path.join(d, "Content", "MicrosoftGame.config")]
        d = os.path.dirname(d)
    for c in cands:
        try:
            t = open(c, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        m = re.search(r"<Identity\b[^>]*>", t)
        if m:
            n = re.search(r'Name="([^"]+)"', m.group(0))
            v = re.search(r'Version="([\d.]+)"', m.group(0))
            out.update(store="Microsoft Store / Xbox", package_name=n and n.group(1), store_version=v and v.group(1), manifest=c)
            return out
    steamapps = os.path.dirname(os.path.dirname(install_dir))
    for acf in glob.glob(os.path.join(steamapps, "appmanifest_*.acf")):
        t = open(acf, encoding="utf-8", errors="ignore").read()
        if re.search(r'"installdir"\s+"%s"' % re.escape(os.path.basename(install_dir)), t, re.I):
            b = re.search(r'"buildid"\s+"(\d+)"', t)
            out.update(store="Steam", store_version=b and f"build {b.group(1)}", manifest=acf)
    return out


def ue_hint(c):
    if c["format"] == "pak":
        return {11: "UE 4.26 or later (incl. UE5)", 10: "UE 4.26", 9: "UE 4.25", 8: "UE 4.22–4.24", 7: "UE 4.21"}.get(c["version"], "UE 4.20 or older")
    return {1: "UE 4.25–4.26", 2: "UE 4.26–4.27", 3: "UE 5.0", 4: "UE 5.1", 5: "UE 5.2–5.3", 6: "UE 5.4", 7: "UE 5.4–5.5", 8: "UE 5.5 or later"}.get(c["version"], "unknown")


def unreal_layout(root, depth=6):
    exes, paks = [], []
    for dp, dns, fns in os.walk(root):
        if dp.count(os.sep) - root.count(os.sep) >= depth:
            dns[:] = []
        if os.path.basename(dp).lower() == "paks":
            paks.append(dp)
            dns[:] = []
            continue
        exes += [os.path.join(dp, f) for f in fns if f.lower().endswith("-shipping.exe")]
    return exes, paks


SDK_RE = re.compile(r"(sdk|mod ?kit|modkit|zone ?kit|dev ?kit|editor|mod tools)", re.I)


def scan_game(install_dir, name="", known_games=()):
    if not os.path.isdir(install_dir):
        raise AssetError("failed", f"Folder not found: {install_dir}")
    try:
        os.listdir(install_dir)
    except PermissionError:
        raise AssetError("permission", "Windows does not allow reading this folder (protected Store folder). Move the game to an "
                                       "XboxGames folder with 'Enable advanced management features' in the Xbox app, then rescan.")
    exes, paks = unreal_layout(install_dir)
    ev = []
    out = {"name": name, "install_dir": install_dir, **store_info(install_dir), "exe": None, "exe_version": None,
           "engine": "unknown", "engine_version": None, "evidence": ev, "paks_dirs": paks, "containers": [], "inventory": {},
           "oodle_dll": find_oodle(install_dir), "sdk_candidates": [], "scanned_at": time.time()}
    if out["store_version"]:
        ev.append(f"{out['store']} reports game version {out['store_version']}")
    if exes:
        exe = sorted(exes, key=lambda p: ("wingdk" not in p.lower() and "win64" not in p.lower(), len(p)))[0]
        out["exe"] = os.path.relpath(exe, install_dir)
        out["engine"] = "unreal"
        fv = file_version(exe)
        out["exe_version"] = fv
        builds = exe_build_strings(exe)
        if builds:
            out["engine_version"] = builds[0]
            ev.append(f"Game .exe contains the engine build tag '++UE{builds[0][0]}+Release-{builds[0]}'")
        if fv:
            ev.append(f"Game .exe file version is {fv}")
            if not builds and re.match(r"^[45]\.\d+\.", fv):
                out["engine_version"] = ".".join(fv.split(".")[:2])
    for pd in paks:
        for dp, _d, fns in os.walk(pd):
            for fn in sorted(fns):
                if not fn.lower().endswith((".pak", ".utoc")):
                    continue
                p = os.path.join(dp, fn)
                st = os.stat(p)
                c = {"path": p, "rel": os.path.relpath(p, install_dir), "size": st.st_size, "mtime": st.st_mtime,
                     "in_mods_folder": "~mods" in p.lower() or "logicmods" in p.lower()}
                try:
                    info = open_container(p)
                    exts = {}
                    for e in info["entries"]:
                        x = os.path.splitext(e["path"])[1].lower() or "(none)"
                        exts[x] = exts.get(x, 0) + 1
                        out["inventory"][x] = out["inventory"].get(x, 0) + 1
                    c.update(format=info["format"], version=info["version"], ue_hint=ue_hint(info), files=len(info["entries"]),
                             listable=info["listable"], encrypted_index=info["encrypted_index"], methods=info["methods"],
                             encrypted_files=sum(1 for e in info["entries"] if e.get("encrypted")), issues=info["issues"],
                             types=dict(sorted(exts.items(), key=lambda kv: -kv[1])[:12]))
                    c["state"] = "blocked_by_protection" if info["encrypted_index"] else ("ok" if info["listable"] else "metadata_only")
                except AssetError as e:
                    c.update(state="unsupported", issues=[str(e)])
                except Exception as e:
                    c.update(state="failed", issues=[f"Could not read: {e}"])
                out["containers"].append(c)
    hints = sorted({c["ue_hint"] for c in out["containers"] if c.get("ue_hint")})
    if hints:
        ev.append("Container formats point to: " + "; ".join(hints))
    if not out["engine_version"] and out["containers"]:
        out["engine_version_note"] = "No exact build tag found; container formats give the range above."
    if out["oodle_dll"]:
        ev.append(f"Game ships its own Oodle unpacker: {os.path.relpath(out['oodle_dll'], install_dir)}")
    for g in known_games:
        gn = g.get("name") or ""
        if gn != name and SDK_RE.search(gn) and name and any(w.lower() in gn.lower() for w in re.findall(r"[A-Za-z]{5,}", name)[:2]):
            out["sdk_candidates"].append({"name": gn, "install_dir": g.get("install_dir")})
    return out


# ---------------- listing & extraction ----------------
def list_assets(container, filt="", offset=0, limit=500):
    info = open_container(container)
    rx = re.compile(re.escape(filt), re.I) if filt else None
    items = [{"path": e["path"], "size": e["usize"], "compression": e.get("method"), "encrypted": bool(e.get("encrypted")),
              "type": os.path.splitext(e["path"])[1].lower()} for e in info["entries"] if not rx or rx.search(e["path"])]
    return {"container": container, "format": info["format"], "listable": info["listable"], "issues": info["issues"],
            "total": len(items), "offset": offset, "items": items[offset:offset + limit]}


def safe_join(base, rel):
    dest = os.path.realpath(os.path.join(base, rel.replace("\\", "/").lstrip("/")))
    if not dest.startswith(os.path.realpath(base) + os.sep):
        raise AssetError("failed", f"Unsafe path inside container: {rel}")
    return dest


def extract(install_dir, container, paths, out_dir, progress=lambda pct, msg: None):
    real_game = os.path.realpath(install_dir)
    if os.path.realpath(out_dir).startswith(real_game + os.sep):
        raise AssetError("failed", "Refusing to extract inside the game folder")
    info = open_container(container)
    if info["encrypted_index"]:
        raise AssetError("blocked", info["issues"][0])
    want = set(paths)
    sel = [e for e in info["entries"] if e["path"] in want]
    missing = sorted(want - {e["path"] for e in sel})
    need = sum(e["usize"] for e in sel)
    os.makedirs(out_dir, exist_ok=True)
    free = shutil.disk_usage(out_dir).free
    if need * 1.1 + (64 << 20) > free:
        raise AssetError("failed", f"Not enough disk space: need about {need / 1e9:.2f} GB, {free / 1e9:.2f} GB free")
    before = os.stat(container)
    oodle = None
    if any((e.get("method") or "").lower() == "oodle" for e in sel) or info["format"] == "iostore":
        dll = find_oodle(install_dir)
        oodle = Oodle(dll) if dll else None
    done, failed = [], [{"path": p, "state": "failed", "reason": "Not found in this container"} for p in missing]
    with open(container, "rb") as f:
        for i, e in enumerate(sel):
            progress(int(100 * i / max(1, len(sel))), e["path"])
            try:
                data = pak_entry_bytes(f, e, info["version"], oodle) if info["format"] == "pak" else iostore_entry_bytes(info, e, oodle)
                if len(data) != e["usize"]:
                    raise AssetError("failed", f"Size check failed ({len(data)} of {e['usize']} bytes)")
                dest = safe_join(out_dir, e["path"])
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as o:
                    o.write(data)
                if os.path.getsize(dest) != len(data):
                    raise AssetError("failed", "Written file size does not match")
                done.append({"path": e["path"], "out": dest, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            except AssetError as ex:
                failed.append({"path": e["path"], "state": ex.state, "reason": str(ex)})
    after = os.stat(container)
    untouched = (before.st_size, before.st_mtime) == (after.st_size, after.st_mtime)
    progress(100, "done")
    return {"extracted": done, "problems": failed, "source_untouched": untouched, "out_dir": out_dir,
            "container": container, "oodle_used": bool(oodle)}


# ---------------- conversion ----------------
def png_bytes(w, h, rgba):
    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def _565(c):
    return ((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31


def _bc1_colors(blk, force4):
    c0, c1 = struct.unpack_from("<HH", blk)
    a, b = _565(c0), _565(c1)
    if c0 > c1 or force4:
        return [a + (255,), b + (255,), tuple((2 * x + y) // 3 for x, y in zip(a, b)) + (255,), tuple((x + 2 * y) // 3 for x, y in zip(a, b)) + (255,)]
    return [a + (255,), b + (255,), tuple((x + y) // 2 for x, y in zip(a, b)) + (255,), (0, 0, 0, 0)]


def _bc_alpha(blk):
    a0, a1 = blk[0], blk[1]
    bits = int.from_bytes(blk[2:8], "little")
    pal = [a0, a1] + ([((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)] if a0 > a1 else [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255])
    return [pal[(bits >> (3 * i)) & 7] for i in range(16)]


def decode_bc(data, w, h, kind):
    out = bytearray(w * h * 4)
    bsz = 8 if kind in ("BC1", "BC4") else 16
    bw, p = (w + 3) // 4, 0
    for by in range((h + 3) // 4):
        for bx in range(bw):
            blk = data[p:p + bsz]
            p += bsz
            if len(blk) < bsz:
                raise AssetError("failed", "Texture data is shorter than its header says")
            if kind == "BC4":
                px = [(v, v, v, 255) for v in _bc_alpha(blk)]
            else:
                cb = blk[8:] if kind == "BC3" else blk
                cols = _bc1_colors(cb, kind == "BC3")
                idx = struct.unpack_from("<I", cb, 4)[0]
                px = [cols[(idx >> (2 * i)) & 3] for i in range(16)]
                if kind == "BC3":
                    al = _bc_alpha(blk[:8])
                    px = [c[:3] + (al[i],) for i, c in enumerate(px)]
            for i, c in enumerate(px):
                x, y = bx * 4 + i % 4, by * 4 + i // 4
                if x < w and y < h:
                    o = (y * w + x) * 4
                    out[o:o + 4] = bytes(c)
    return bytes(out)


def decode_dds(b):
    if b[:4] != b"DDS ":
        raise AssetError("unsupported", "Not a DDS texture")
    h, w = struct.unpack_from("<II", b, 12)
    pf_flags, fourcc, bits = struct.unpack_from("<I4sI", b, 80)
    masks = struct.unpack_from("<IIII", b, 92)
    data = b[128:]
    if fourcc == b"DX10":
        dxgi = struct.unpack_from("<I", b, 128)[0]
        data = b[148:]
        kind = {71: "BC1", 72: "BC1", 74: "BC2", 77: "BC3", 78: "BC3", 80: "BC4", 81: "BC4", 83: "BC5", 98: "BC7", 99: "BC7",
                87: "BGRA", 91: "BGRA", 28: "RGBA", 29: "RGBA"}.get(dxgi, f"DXGI format {dxgi}")
    elif fourcc in (b"DXT1",):
        kind = "BC1"
    elif fourcc in (b"DXT5", b"DXT4"):
        kind = "BC3"
    elif fourcc in (b"ATI1", b"BC4U"):
        kind = "BC4"
    elif pf_flags & 0x40 and bits == 32:
        kind = "BGRA" if masks[0] == 0x00FF0000 else "RGBA"
    else:
        kind = f"format {fourcc!r}"
    if kind in ("BC1", "BC3", "BC4"):
        return w, h, decode_bc(data, w, h, kind), kind
    if kind in ("BGRA", "RGBA"):
        px = bytearray(data[:w * h * 4])
        if kind == "BGRA":
            px[0::4], px[2::4] = px[2::4], px[0::4]
        return w, h, bytes(px), kind
    raise AssetError("possible_not_implemented", f"DDS texture uses {kind}; MELTY's built-in decoder handles BC1, BC3, BC4 and plain RGBA so far")


def decode_tga(b):
    idl, cmt, it = b[0], b[1], b[2]
    w, h, bpp, desc = struct.unpack_from("<HHBB", b, 12)
    if cmt or it not in (2, 10) or bpp not in (24, 32):
        raise AssetError("possible_not_implemented", "Only true-colour 24/32-bit TGA files are decoded so far")
    p, n, step, px = 18 + idl, w * h, bpp // 8, bytearray()
    if it == 2:
        raw = b[p:p + n * step]
    else:
        raw = bytearray()
        while len(raw) < n * step:
            c = b[p]
            p += 1
            if c & 0x80:
                raw += b[p:p + step] * ((c & 0x7F) + 1)
                p += step
            else:
                k = ((c & 0x7F) + 1) * step
                raw += b[p:p + k]
                p += k
    for i in range(n):
        bgr = raw[i * step:i * step + step]
        px += bytes((bgr[2], bgr[1], bgr[0], bgr[3] if step == 4 else 255))
    if not desc & 0x20:
        rows = [px[y * w * 4:(y + 1) * w * 4] for y in range(h)]
        px = b"".join(reversed(rows))
    return w, h, bytes(px)


def thumbnail(w, h, rgba, mx=256):
    s = max(1, (max(w, h) + mx - 1) // mx)
    tw, th = max(1, w // s), max(1, h // s)
    out = bytearray()
    for y in range(th):
        row = (y * s) * w
        for x in range(tw):
            o = (row + x * s) * 4
            out += rgba[o:o + 4]
    return png_bytes(tw, th, bytes(out))


def parse_stalker_cfg(text):
    root, stack = {}, []
    cur = root
    for line in text.splitlines():
        line = re.sub(r"//.*$", "", line).strip()
        if not line:
            continue
        m = re.match(r"^(.+?)\s*:\s*struct\.begin\b\s*(\{[^}]*\})?", line)
        if m:
            node = {"__meta": m.group(2)} if m.group(2) else {}
            cur[m.group(1).strip()] = node
            stack.append(cur)
            cur = node
            continue
        if line.startswith("struct.end"):
            cur = stack.pop() if stack else root
            continue
        m = re.match(r"^(.+?)\s*=\s*(.*)$", line)
        if m:
            cur[m.group(1).strip()] = m.group(2).strip()
    return root


def parse_ini(text):
    out, sec = {}, None
    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] in ";#":
            continue
        if s.startswith("[") and s.endswith("]"):
            sec = out.setdefault(s[1:-1], [])
        elif "=" in s and sec is not None:
            k, v = s.split("=", 1)
            sec.append([k.strip(), v.strip()])
    return out


def uasset_info(b):
    info = {"format": "unknown", "class": None, "names": []}
    try:
        r = R(b)
        if r.u32() == 0x9E2A83C1:
            info["format"] = "legacy uasset"
            legacy = r.i32()
            if legacy != -4:
                r.i32()
            ue4 = r.i32()
            ue5 = r.i32() if legacy <= -8 else 0
            r.i32()
            info.update(file_version_ue4=ue4 or "unversioned (cooked)", file_version_ue5=ue5 or None)
            if legacy >= -8:
                r.take(20 * r.i32())
                r.i32()
                r.fstr()
                flags = r.u32()
                info["unversioned"] = bool(flags & 0x2000) or ue4 == 0
                nc, no = r.i32(), r.i32()
                rr = R(b, no)
                for _ in range(min(nc, 4000)):
                    info["names"].append(rr.fstr())
                    if ue4 == 0 or ue4 >= 504:
                        rr.u32()
        else:
            info["format"] = "IoStore (zen) package or raw data"
    except Exception:
        pass
    hay = set(info["names"]) or None
    for c in CLASSES:
        if (hay and c in hay) or (not hay and c.encode() in b[:65536]):
            info["class"] = c
            break
    info["names"] = info["names"][:40]
    return info


def classify_uasset(cls, src_engine, dst_engine):
    cross = f" Cooked packages are tied to the engine build that made them ({src_engine or 'source'} → {dst_engine or 'destination'}); " \
            "the destination editor cannot open them directly."
    if cls in ("Texture2D", "TextureCube"):
        return "possible_not_implemented", "Texture: export to PNG with a cooked-asset viewer, then re-import in the destination mod kit." + cross
    if cls in ("StaticMesh", "SkeletalMesh"):
        return "possible_not_implemented", "Mesh: export to FBX/glTF with a cooked-asset viewer, re-import and re-rig in the destination mod kit." + cross
    if cls in ("AnimSequence", "AnimMontage", "Skeleton"):
        return "possible_not_implemented", "Animation: export to FBX, retarget onto the destination skeleton in the editor." + cross
    if cls in ("SoundWave", "SoundCue"):
        return "possible_with_conversion", "Audio: the sound data usually sits in a .ubulk/.bnk/.wem file; convert that to WAV and re-import."
    if cls in ("Material", "MaterialInstanceConstant", "NiagaraSystem", "ParticleSystem"):
        return "possible_recreated_equivalent", "Materials and effects contain compiled shaders for one engine build; rebuild an equivalent using the converted textures."
    if cls in ("BlueprintGeneratedClass", "WidgetBlueprintGeneratedClass"):
        return "possible_recreated_equivalent", "Game logic is compiled; recreate the behaviour (e.g. squad commands) as new code in the destination game."
    if cls in ("DataTable", "CurveTable"):
        return "possible_not_implemented", "Data table: values can be read with a cooked-asset viewer and re-entered as a new table or config."
    if cls == "World":
        return "possible_recreated_equivalent", "Maps are too engine-specific to move; rebuild a level using exported meshes and textures."
    return "unsupported_by_toolkit", "MELTY could not tell what kind of asset this is yet."


def tool_path(name, tools_dir=None):
    for d in ([tools_dir] if tools_dir else []):
        for c in glob.glob(os.path.join(d, "**", name + "*"), recursive=True):
            if os.path.isfile(c):
                return c
    return shutil.which(name)


def convert_one(src, out_dir, ctx=None):
    ctx = ctx or {}
    ext = os.path.splitext(src)[1].lower()
    base = os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0])
    os.makedirs(out_dir, exist_ok=True)
    rep = {"source": src, "type": ext, "outputs": [], "converted": False, "level": None, "reason": "", "details": {}}
    b = open(src, "rb").read()
    rep["source_sha256"] = hashlib.sha256(b).hexdigest()
    try:
        if ext in (".dds", ".tga"):
            w, h, px, *kind = decode_dds(b) if ext == ".dds" else decode_tga(b)
            out = base + ".png"
            open(out, "wb").write(png_bytes(w, h, px))
            rep.update(outputs=[out], converted=True, level="possible_with_conversion", reason=f"Converted {w}×{h} texture to PNG",
                       details={"width": w, "height": h, "encoding": kind[0] if kind else "TGA"}, _thumb=thumbnail(w, h, px))
        elif ext in (".png", ".jpg", ".jpeg"):
            out = base + ext
            shutil.copyfile(src, out)
            rep.update(outputs=[out], converted=True, level="possible_with_conversion", reason="Already a standard image; copied as-is")
            if len(b) < 2 << 20:
                rep["_thumb"] = b
        elif ext == ".wav":
            with wave.open(src) as wv:
                rep["details"] = {"channels": wv.getnchannels(), "rate": wv.getframerate(), "seconds": round(wv.getnframes() / wv.getframerate(), 2)}
            out = base + ".wav"
            shutil.copyfile(src, out)
            rep.update(outputs=[out], converted=True, level="possible_with_conversion", reason="Standard WAV audio; copied as-is")
        elif ext in (".ogg", ".wem", ".bnk", ".mp3", ".flac"):
            tool = tool_path("vgmstream-cli", ctx.get("tools_dir")) if ext in (".wem", ".bnk") else tool_path("ffmpeg", ctx.get("tools_dir"))
            if not tool:
                need = "vgmstream-cli" if ext in (".wem", ".bnk") else "ffmpeg"
                rep.update(level="unsupported_by_toolkit", reason=f"Needs the free tool {need}. Put it in your MELTY tools folder or on PATH, then convert again.")
            else:
                out = base + ".wav"
                cmd = [tool, "-o", out, src] if "vgmstream" in tool else [tool, "-y", "-loglevel", "error", "-i", src, out]
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if p.returncode or not os.path.exists(out):
                    raise AssetError("failed", (p.stderr or p.stdout or "converter failed")[-400:])
                rep.update(outputs=[out], converted=True, level="possible_with_conversion", reason=f"Converted to WAV with {os.path.basename(tool)}")
        elif ext == ".cfg":
            data = parse_stalker_cfg(b.decode("utf-8", "replace"))
            out = base + ".cfg.json"
            json.dump(data, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
            rep.update(outputs=[out], converted=True, level="possible_with_conversion", reason=f"Read {len(data)} top-level config blocks into JSON",
                       details={"blocks": list(data)[:30]})
        elif ext == ".ini":
            data = parse_ini(b.decode("utf-8", "replace"))
            out = base + ".ini.json"
            json.dump(data, open(out, "w", encoding="utf-8"), indent=1)
            rep.update(outputs=[out], converted=True, level="possible_with_conversion", reason=f"Read {len(data)} ini sections into JSON")
        elif ext in (".json", ".txt", ".csv", ".xml", ".lua"):
            if ext == ".json":
                json.loads(b.decode("utf-8-sig"))
            out = base + ext
            shutil.copyfile(src, out)
            rep.update(outputs=[out], converted=True, level="possible_with_conversion", reason="Plain text data; copied as-is")
        elif ext in (".uasset", ".umap"):
            ui = uasset_info(b)
            lvl, why = classify_uasset(ui["class"], ctx.get("src_engine"), ctx.get("dst_engine"))
            out = base + ext + ".report.json"
            json.dump(ui, open(out, "w", encoding="utf-8"), indent=1)
            rep.update(outputs=[out], level=lvl, reason=why, details={k: v for k, v in ui.items() if k != "names"})
        elif ext in (".uexp", ".ubulk", ".uptnl"):
            rep.update(level="possible_not_implemented", reason="Companion data for a .uasset; convert the matching .uasset instead.")
        elif ext in (".bik", ".bk2"):
            rep.update(level="unsupported_by_toolkit", reason="Bink video needs the RAD tools; not supported.")
        elif ext in (".ushaderbytecode", ".upipelinecache", ".ushadercache"):
            rep.update(level="impossible", reason="Compiled shaders only work in the exact engine build that made them; rebuild materials instead.")
        else:
            rep.update(level="unsupported_by_toolkit", reason=f"No converter for '{ext}' files yet")
    except AssetError as e:
        rep.update(level=e.state if e.state in LEVELS else "unsupported_by_toolkit", reason=str(e), error=e.state == "failed")
    except Exception as e:
        rep.update(level="unsupported_by_toolkit", reason=f"Could not convert: {e}", error=True)
    rep["level_label"] = LEVELS.get(rep["level"], rep["level"])
    return rep


def validate_output(path):
    b = open(path, "rb").read()
    ext = os.path.splitext(path)[1].lower()
    r = {"path": path, "size": len(b), "sha256": hashlib.sha256(b).hexdigest(), "ok": False, "check": ""}
    try:
        if ext == ".png":
            if b[:8] != b"\x89PNG\r\n\x1a\n":
                raise ValueError("bad PNG signature")
            p, idat = 8, b""
            while p < len(b):
                n, t = struct.unpack_from(">I4s", b, p)
                d = b[p + 8:p + 8 + n]
                if zlib.crc32(t + d) & 0xFFFFFFFF != struct.unpack_from(">I", b, p + 8 + n)[0]:
                    raise ValueError(f"CRC error in {t!r}")
                if t == b"IHDR":
                    w, h = struct.unpack(">II", d[:8])
                if t == b"IDAT":
                    idat += d
                p += 12 + n
            if idat:
                zlib.decompress(idat)
            r.update(ok=True, check=f"PNG {w}×{h}, all chunks valid")
        elif ext == ".wav":
            with wave.open(path) as wv:
                r.update(ok=wv.getnframes() > 0, check=f"WAV {wv.getnchannels()}ch {wv.getframerate()}Hz")
        elif ext == ".json":
            json.loads(b.decode("utf-8"))
            r.update(ok=True, check="valid JSON")
        elif ext == ".pak":
            info = read_pak(path)
            r.update(ok=info["listable"], check=f"pak v{info['version']} with {len(info['entries'])} files")
        else:
            r.update(ok=len(b) > 0, check="file exists and is not empty")
    except Exception as e:
        r["check"] = f"Invalid: {e}"
    return r


# ---------------- packaging (only your own changes / authorised files) ----------------
def write_pak(out, files, mount="../../../"):
    """Write an uncompressed, unencrypted v8 .pak. files: {path inside game (e.g. 'Stalker2/Content/x.cfg'): bytes}"""
    ver, entries = 8, []
    with open(out, "wb") as f:
        for rel, data in files.items():
            off = f.tell()
            h = hashlib.sha1(data).digest()
            hdr = struct.pack("<qqqI", 0, len(data), len(data), 0) + h + b"\0" + struct.pack("<I", 0)
            f.write(hdr + data)
            entries.append((rel.replace("\\", "/"), struct.pack("<qqqI", off, len(data), len(data), 0) + h + b"\0" + struct.pack("<I", 0)))
        idx = fstr_bytes(mount) + struct.pack("<i", len(entries)) + b"".join(fstr_bytes(n) + e for n, e in entries)
        io_ = f.tell()
        f.write(idx)
        f.write(b"\0" * 16 + b"\0" + struct.pack("<IIqq", PAK_MAGIC, ver, io_, len(idx)) + hashlib.sha1(idx).digest() + b"\0" * 160)
    return out


def verify_pak(out, files, mount="../../../"):
    info = read_pak(out)
    got = {}
    with open(out, "rb") as f:
        for e in info["entries"]:
            got[e["path"]] = hashlib.sha256(pak_entry_bytes(f, e, info["version"], None)).hexdigest()
    m = clean_mount(mount)
    exp = {m + k.replace("\\", "/"): hashlib.sha256(v).hexdigest() for k, v in files.items()}
    bad = [k for k in exp if got.get(k) != exp[k]]
    return {"ok": not bad and len(got) == len(exp), "files": len(got), "mismatched": bad, "pak_version": info["version"]}
