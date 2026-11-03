"""Weapon pictures for the UI, decoded from the game's own inventory renders (DT_WeaponData.RenderIcon)."""
from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image

from .asset import Asset
from .game import Game

WEAPON_TABLE = "/Game/PBZContent/DataTable/UI/DT_WeaponData"
BYTES_PER_PIXEL = {"PF_DXT1": 0.5, "PF_DXT5": 1, "PF_BC7": 1, "PF_B8G8R8A8": 4}


def _dds(w: int, h: int, pf: str, data: bytes) -> Image.Image:
    if pf == "PF_B8G8R8A8":
        return Image.frombytes("RGBA", (w, h), data, "raw", "BGRA")
    four = {"PF_DXT1": b"DXT1", "PF_DXT5": b"DXT5"}.get(pf, b"DX10")
    hdr = struct.pack("<4sIIIIIII44sII4sIIIIIIIIII", b"DDS ", 124, 0x1007 | 0x80000, h, w, len(data), 0, 1,
                      b"\0" * 44, 32, 4, four, 0, 0, 0, 0, 0, 0x1000, 0, 0, 0, 0)
    if four == b"DX10":
        hdr += struct.pack("<IIIII", 98, 3, 0, 1, 0)  # BC7_UNORM
    im = Image.open(io.BytesIO(hdr + data))
    im.load()
    return im


def decode_texture(uasset: Path) -> Image.Image:
    """Top mip of a legacy Texture2D. Inline mips sit right before the 24-byte tail (SizeX/Y/Z + padding);
    streamed mips start the .ubulk."""
    ue = uasset.with_suffix(".uexp").read_bytes()
    i = ue.find(b"PF_")
    if i < 0:
        raise ValueError(f"{uasset.name}: no pixel format")
    pf = ue[i:ue.index(b"\0", i)].decode()
    if pf not in BYTES_PER_PIXEL:
        raise ValueError(f"{uasset.name}: unsupported {pf}")
    w, h = struct.unpack_from("<II", ue, i - 16)
    ubulk = uasset.with_suffix(".ubulk")
    if ubulk.exists():
        blob = ubulk.read_bytes()
        while w * h * BYTES_PER_PIXEL[pf] > len(blob) and w > 4:
            w, h = w // 2, h // 2
        data = blob[:int(w * h * BYTES_PER_PIXEL[pf])]
    else:
        size = int(w * h * BYTES_PER_PIXEL[pf])
        # shortcut: fixed 24-byte tail, checked on PBZ's 2048px DXT5 renders; parse FTexturePlatformData if others look wrong
        start = len(ue) - size - 24
        data = ue[start:start + size]
    return _dds(w, h, pf, data).convert("RGBA")


def render_paths(game: Game) -> dict[str, str]:
    """Weapon key -> render texture package, from the UI weapon table."""
    a = Asset(game.json_of(WEAPON_TABLE))
    table = next((e["Table"] for e in a.j["Exports"] if "Table" in e), None)
    if table is None:
        kinds = ", ".join(str(e.get("$type", "?")).split(",")[0].rsplit(".", 1)[-1] for e in a.j["Exports"])
        raise RuntimeError(f"{WEAPON_TABLE.rsplit('/', 1)[-1]} has no readable table (exports: {kinds or 'none'})")
    out = {}
    for row in table["Data"]:
        v = {p["Name"]: p.get("Value") for p in row["Value"]}
        cfg, render = v.get("WeaponConfig"), v.get("RenderIcon")
        if not (isinstance(cfg, dict) and isinstance(render, dict)):
            continue
        key_pkg = (cfg.get("AssetPath") or {}).get("PackageName") or ""
        tex = (render.get("AssetPath") or {}).get("PackageName")
        key = key_pkg.rsplit("/", 1)[-1].removeprefix("Weapon_Hun_")
        if key and tex and key not in out:
            out[key] = tex
    return out


def weapon_images(game: Game, size: int = 512) -> dict[str, Path]:
    """Weapon key -> PNG in cache_dir/img (trimmed to the blade and scaled down)."""
    folder = game.cfg.cache_dir / "img"
    folder.mkdir(parents=True, exist_ok=True)
    paths = {k: t for k, t in render_paths(game).items() if game.has(t)}
    todo = {k: t for k, t in paths.items() if not (folder / f"{k}.png").exists()}
    game.ensure(list(todo.values()))
    for key, tex in todo.items():
        try:
            im = decode_texture(game.legacy_file(tex))
        except Exception:
            continue
        box = im.getchannel("A").getbbox()
        if box:
            im = im.crop(box)
        im.thumbnail((size, size), Image.LANCZOS)
        im.save(folder / f"{key}.png")
    return {k: folder / f"{k}.png" for k in paths if (folder / f"{k}.png").exists()}
