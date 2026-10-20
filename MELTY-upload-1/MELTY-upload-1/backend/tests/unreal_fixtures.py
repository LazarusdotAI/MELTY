"""Synthetic, freely-licensed Unreal containers built byte-by-byte for tests."""
import os
import zlib
import struct
import hashlib

MAGIC = 0x5A6F12E1
NONE = 0xFFFFFFFF


def fstr(s):
    b = s.encode() + b"\0"
    return struct.pack("<i", len(b)) + b


def pak_v11(path, files, compress=(), encrypted_index=False, encrypted=()):
    """files: {"Dir/Sub/name.ext": bytes} (paths relative to mount ../../../)"""
    data, enc_entries, dirs = bytearray(), bytearray(), {}
    for rel, raw in files.items():
        off = len(data)
        comp = rel in compress
        payload = zlib.compress(raw) if comp else raw
        h = hashlib.sha1(raw).digest()
        if comp:
            hdr = struct.pack("<qqqI", 0, len(payload), len(raw), 1) + h + struct.pack("<I", 1) + struct.pack("<qq", 73, 73 + len(payload)) + b"\0" + struct.pack("<I", len(raw))
        else:
            hdr = struct.pack("<qqqI", 0, len(raw), len(raw), 0) + h + b"\0" + struct.pack("<I", 0)
        data += hdr + payload
        v = 0x3F | ((1 if comp else 0) << 6) | ((1 if comp else 0) << 23) | (1 << 30) | (1 << 31) | ((1 << 29) if comp else 0) | ((1 << 22) if rel in encrypted else 0)
        loc = len(enc_entries)
        enc_entries += struct.pack("<II", v, len(raw)) + struct.pack("<II", off, len(raw)) + (struct.pack("<I", len(payload)) if comp else b"")
        d, _, n = rel.rpartition("/")
        dirs.setdefault((d + "/") if d else "/", []).append((n, loc))
    fdi = struct.pack("<i", len(dirs)) + b"".join(fstr(d) + struct.pack("<i", len(fs)) + b"".join(fstr(n) + struct.pack("<i", l) for n, l in fs)
                                                   for d, fs in dirs.items())
    idx_off = len(data)
    fdi_off_placeholder = 0

    def index(fdi_off):
        return fstr("../../../") + struct.pack("<iQI", len(files), 0, 0) + struct.pack("<I", 1) + struct.pack("<qq", fdi_off, len(fdi)) + b"\0" * 20 + \
            struct.pack("<i", len(enc_entries)) + bytes(enc_entries) + struct.pack("<i", 0)
    idx = index(fdi_off_placeholder)
    fdi_off = idx_off + len(idx)
    idx = index(fdi_off)
    names = b"Zlib".ljust(32, b"\0") + b"\0" * 128
    footer = b"\0" * 16 + (b"\1" if encrypted_index else b"\0") + struct.pack("<IIqq", MAGIC, 11, idx_off, len(idx)) + hashlib.sha1(idx).digest() + names
    with open(path, "wb") as f:
        f.write(bytes(data) + idx + fdi + footer)
    return path


def utoc_v3(base, files, compress=()):
    """IoStore container: base + '.utoc' / '.ucas'. Each file sits in its own 64 KiB block."""
    cbs, names = 65536, list(files)
    ucas, offs, blocks = bytearray(), b"", b""
    for i, n in enumerate(names):
        raw = files[n]
        assert len(raw) < cbs
        c = zlib.compress(raw) if n in compress else raw
        blocks += len(ucas).to_bytes(5, "little") + len(c).to_bytes(3, "little") + len(raw).to_bytes(3, "little") + bytes([1 if n in compress else 0])
        ucas += c + b"\0" * ((-len(c)) % 16)
        offs += (i * cbs).to_bytes(5, "big") + len(raw).to_bytes(5, "big")
    strings = ["Game"] + [n.split("/")[-1] for n in names]
    dirs = struct.pack("<i", 2) + struct.pack("<IIII", NONE, 1, NONE, NONE) + struct.pack("<IIII", 0, NONE, NONE, 0)
    fe = struct.pack("<i", len(names)) + b"".join(struct.pack("<III", i + 1, i + 1 if i + 1 < len(names) else NONE, i) for i in range(len(names)))
    di = fstr("../../../") + dirs + fe + struct.pack("<i", len(strings)) + b"".join(fstr(s) for s in strings)
    n = len(names)
    hdr = b"-==--==--==--==-" + struct.pack("<BBH", 3, 0, 0) + struct.pack("<9I", 144, n, n, 12, 1, 32, cbs, len(di), 1) + struct.pack("<Q", 7) + b"\0" * 16 + \
        struct.pack("<BBH", 1 | 8, 0, 0) + struct.pack("<IQI", 0, 1 << 40, 0)
    hdr = hdr.ljust(144, b"\0")
    toc = hdr + b"\0" * 12 * n + offs + blocks + b"Zlib".ljust(32, b"\0") + di
    open(base + ".utoc", "wb").write(toc)
    open(base + ".ucas", "wb").write(bytes(ucas))
    return base + ".utoc"


def dds_bc1(w=8, h=8):
    hdr = b"DDS " + struct.pack("<I", 124) + struct.pack("<IIIIII", 0x1007, h, w, w * h // 2, 0, 1) + b"\0" * 44 + \
        struct.pack("<II4sIIIII", 32, 4, b"DXT1", 0, 0, 0, 0, 0) + struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)
    block = struct.pack("<HHI", 0xF800, 0x001F, 0)  # all pixels = color0 (pure red)
    return hdr + block * ((w // 4) * (h // 4))


def dds_dx10(dxgi=98, w=4, h=4):
    hdr = b"DDS " + struct.pack("<I", 124) + struct.pack("<IIIIII", 0x1007, h, w, 16, 0, 1) + b"\0" * 44 + \
        struct.pack("<II4sIIIII", 32, 4, b"DX10", 0, 0, 0, 0, 0) + struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)
    return hdr + struct.pack("<IIIII", dxgi, 3, 0, 1, 0) + b"\0" * 16


def legacy_uasset(cls="Texture2D"):
    names = ["/Game/Weapons/T_Rifle", cls, "Default__" + cls, "/Script/Engine"]
    nm = b"".join(fstr(n) + b"\0\0\0\0" for n in names)
    head = struct.pack("<Iiiii", 0x9E2A83C1, -7, 864, 0, 0) + struct.pack("<i", 0) + struct.pack("<i", 0) + fstr("None") + struct.pack("<I", 0x80002000)
    name_off = len(head) + 8
    return head + struct.pack("<ii", len(names), name_off) + nm


STALKER_CFG = """// weapon config
GunAKM_ST : struct.begin {refkey=[0]}
   SID = GunAKM_ST
   Damage = 28.5
   FireRate = 600
   Recoil : struct.begin
      Vertical = 0.42
   struct.end
struct.end
"""


def unreal_game(root, project, exe_dir, exe_name, build_tag, utf16=False, xbox_manifest=None, steam_build=None):
    """Lay out a fake installed Unreal game. Returns install_dir."""
    install = root
    exe = os.path.join(install, project, "Binaries", exe_dir, exe_name)
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    tag = build_tag.encode("utf-16-le") if utf16 else build_tag.encode()
    open(exe, "wb").write(b"MZ" + b"\0" * 1000 + tag + b"\0" * 1000)
    paks = os.path.join(install, project, "Content", "Paks")
    os.makedirs(paks, exist_ok=True)
    if xbox_manifest:
        open(os.path.join(install, "appxmanifest.xml"), "w").write(
            f'<Package><Identity Name="{xbox_manifest[0]}" Publisher="CN=x" Version="{xbox_manifest[1]}" /></Package>')
    if steam_build:
        common = os.path.dirname(install)
        steamapps = os.path.dirname(common)
        open(os.path.join(steamapps, "appmanifest_1144200.acf"), "w").write(
            f'"AppState"\n{{\n "installdir" "{os.path.basename(install)}"\n "buildid" "{steam_build}"\n}}')
    return install, paks
