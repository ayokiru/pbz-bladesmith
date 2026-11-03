"""Recolor DXT1 (BC1) texture data in place, without decoding or encoding the texture: every 4x4 block stores two
565 endpoint colors and 2-bit indices between them, so changing the endpoints recolors the block and the data keeps
its exact size. Works the same on plain mips and on virtual texture tiles."""
from __future__ import annotations

import struct

import numpy as np


def _unpack565(c: np.ndarray) -> np.ndarray:
    r = ((c >> 11) & 31).astype(np.float32) / 31
    g = ((c >> 5) & 63).astype(np.float32) / 63
    b = (c & 31).astype(np.float32) / 31
    return np.stack([r, g, b], -1)


def _pack565(rgb: np.ndarray) -> np.ndarray:
    rgb = np.clip(rgb, 0, 1)
    return ((np.rint(rgb[..., 0] * 31).astype(np.uint16) << 11) | (np.rint(rgb[..., 1] * 63).astype(np.uint16) << 5)
            | np.rint(rgb[..., 2] * 31).astype(np.uint16))


def recolor_colors(rgb: np.ndarray, target: tuple[float, float, float], hue_from: float = 0.0, hue_width: float = 40.0,
                   min_sat: float = 0.25, brightness: float = 1.0) -> np.ndarray:
    """Colors whose hue is within hue_width degrees of hue_from (and saturated enough) move to `target`'s color,
    keeping their own brightness (times `brightness`); the rest stay. Full strength up to 20 degrees short of the
    edge, then a blend, so crimson and pink shades of the same red all change and outlines don't band."""
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    d = np.maximum(mx - mn, 1e-6)
    hue = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    dist = np.abs((hue - hue_from + 180) % 360 - 180)
    weight = np.clip((hue_width - dist) / 20, 0, 1) * np.clip((sat - min_sat) / 0.15, 0, 1)
    target = np.asarray(target, np.float32)
    tmax = max(float(target.max()), 1e-6)
    new = mx[..., None] * brightness * (target / tmax)  # the target color at the old color's brightness
    return rgb + (new - rgb) * weight[..., None]


RAW_GPU = 4  # EVirtualTextureCodec: the tiles are stored as plain GPU blocks


def vt_chunks(uexp: bytes, ubulk_size: int) -> list[tuple[int, int]]:
    """(offset of the tile data, its length) for each chunk of a DXT1 virtual texture's .ubulk. A chunk is
    a codec payload followed by whole tiles. Read from FVirtualTextureBuiltData: tile size + border give the
    bytes per tile, and the chunk table after the layer's pixel format and fallback color gives each chunk's size,
    payload size and codec. The sizes must add up to the .ubulk exactly, or nothing is touched."""
    first = uexp.find(b"PF_DXT1\0")
    layer = uexp.find(b"PF_DXT1\0", first + 1)
    if first < 0 or layer < 0:
        raise ValueError("not a DXT1 virtual texture")
    tile, border = struct.unpack_from("<II", uexp, first + 8 + 28)  # after the pixel format: 8 bytes, 5 u32, tile, border
    if tile <= 0 or tile & (tile - 1) or border > 16:
        raise ValueError(f"unexpected tile size {tile} / border {border}")
    side = tile + 2 * border
    tile_bytes = (side // 4) * (side // 4) * 8
    pos = layer + 8 + 16  # pixel format, then the fallback color (4 floats)
    (count,) = struct.unpack_from("<I", uexp, pos)
    pos += 4
    chunks, at = [], 0
    for _ in range(count):
        # each entry: hash, size, payload size, codec per layer, then a bulk data header; find the size by its shape
        for p in range(pos, len(uexp) - 9):
            size, payload = struct.unpack_from("<II", uexp, p)
            if size > payload and payload < 64 and (size - payload) % tile_bytes == 0 and uexp[p + 8] == RAW_GPU:
                break
        else:
            raise ValueError("chunk table not understood")
        chunks.append((at + payload, size - payload))
        at += size
        pos = p + 9
    if at != ubulk_size:
        raise ValueError(f"chunk sizes add up to {at}, the .ubulk has {ubulk_size} bytes")
    return chunks


def recolor_vt(uexp: bytes, ubulk: bytes, target: tuple[float, float, float], **kw) -> bytes:
    """The .ubulk of a DXT1 virtual texture with its colors moved (see recolor_colors); payloads stay as they are."""
    out = bytearray(ubulk)
    for start, length in vt_chunks(uexp, len(ubulk)):
        out[start:start + length] = recolor_dxt1(ubulk[start:start + length], target, **kw)
    return bytes(out)


def recolor_dxt1(data: bytes | bytearray, target: tuple[float, float, float], **kw) -> bytes:
    """`data` is a whole number of 8-byte DXT1 blocks."""
    blocks = np.frombuffer(bytes(data), np.uint8).reshape(-1, 8).copy()
    c0 = blocks[:, 0].astype(np.uint16) | (blocks[:, 1].astype(np.uint16) << 8)
    c1 = blocks[:, 2].astype(np.uint16) | (blocks[:, 3].astype(np.uint16) << 8)
    idx = blocks[:, 4:8].view("<u4").ravel()
    four = c0 > c1  # 4-color mode; otherwise 3 colors + transparent black, which must not flip
    n0 = _pack565(recolor_colors(_unpack565(c0), target, **kw))
    n1 = _pack565(recolor_colors(_unpack565(c1), target, **kw))
    # keep each block's mode: if the new endpoints compare the other way, swap them and remap the indices
    swap = np.where(four, n0 < n1, n0 > n1)
    n0, n1 = np.where(swap, n1, n0), np.where(swap, n0, n1)
    # 4-color: 0<->1, 2<->3 is a flip of the low bit; 3-color: 0<->1, 2 (midpoint) and 3 (transparent) stay
    flip4 = idx ^ np.uint32(0x55555555)
    hi = idx & np.uint32(0xAAAAAAAA)
    flip3 = idx ^ (np.uint32(0x55555555) & ~(hi >> 1))  # flip the low bit only where the high bit is 0
    idx = np.where(swap, np.where(four, flip4, flip3), idx)
    # equal endpoints in 4-color mode would switch the block to 3-color mode: make it solid color 0 instead
    same = four & (n0 == n1)
    idx = np.where(same, np.uint32(0), idx)
    top = same & (n0 == 0xFFFF)
    n0 = np.where(same & ~top, n0 + 1, n0)
    n1 = np.where(top, n1 - 1, n1)
    blocks[:, 0], blocks[:, 1] = (n0 & 0xFF).astype(np.uint8), (n0 >> 8).astype(np.uint8)
    blocks[:, 2], blocks[:, 3] = (n1 & 0xFF).astype(np.uint8), (n1 >> 8).astype(np.uint8)
    blocks[:, 4:8] = idx.astype("<u4").view(np.uint8).reshape(-1, 4)
    return blocks.tobytes()
