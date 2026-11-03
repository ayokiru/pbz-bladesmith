"""Color presets for trail effects.

Setting a color through Niagara user parameters crashes this game on load, so colors are written into copies of
the effects instead. A trail's color usually comes from several places at once:
  * material instances it renders with (vector parameters: Main_Color_*, Color_R/G, channel weights);
  * constants baked into emitter spawn scripts (CachedScriptVM.ScriptLiterals, pattern [0, 0, 1, R, G, B, ...]);
  * a ColorCurve lookup table.
A preset lists all of them for one effect family. The copies live in the recipe's fx_folder; the game's own
assets are never touched, so enemies using the same effects keep their colors.
"""
from __future__ import annotations

import colorsys
import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .asset import Asset, prop
from .game import Game

PRESET_DIR = Path(__file__).with_name("presets")


class PresetError(ValueError):
    pass


def load_preset(name_or_path: str) -> dict:
    p = Path(name_or_path)
    if not p.suffix:
        p = PRESET_DIR / f"{name_or_path}.json"
    if not p.exists():
        names = sorted(x.stem for x in PRESET_DIR.glob("*.json"))
        raise PresetError(f"unknown color preset '{name_or_path}' (available: {', '.join(names)})")
    return json.loads(p.read_text(encoding="utf-8"))


def _floats(*vals: float) -> bytes:
    return b"".join(struct.pack("<f", v) for v in vals)


def _num(v) -> float:
    return float(str(v).replace("+", ""))


def spawn_literals(mapped: dict, emitter: str) -> bytes:
    """Raw bytes of an emitter's spawn-script constants (read from the mapped JSON, which is fine for reading)."""
    ex = mapped["Exports"]
    for e in ex:
        if e.get("ObjectName") == "SpawnScript" and ex[e["OuterIndex"] - 1].get("ObjectName") == emitter:
            vm = prop(e["Data"], "CachedScriptVM")["Value"]
            lits = next(x for x in vm if isinstance(x, dict) and x.get("Name") == "ScriptLiterals")["Value"]
            return bytes(int(x["Value"]) for x in lits)
    raise PresetError(f"no spawn script for emitter '{emitter}'")


def color_lut(mapped: dict) -> list[float]:
    e = next((x for x in mapped["Exports"] if str(x.get("ObjectName", "")).startswith("NiagaraDataInterfaceColorCurve")), None)
    if e is None:
        raise PresetError("effect has no ColorCurve")
    return [_num(x["Value"]) for x in prop(e["Data"], "ShaderLUT")["Value"]]


@dataclass
class BytePatch:
    label: str
    old: bytes
    new: bytes


@dataclass
class RecoloredEffect:
    source: str                     # original package
    target: str                     # copy's package
    asset: Asset                    # raw JSON of the copy
    patches: list[BytePatch] = field(default_factory=list)


def material_copy(game: Game, mi_package: str, new_package: str, params: dict[str, list[float]]) -> tuple[Asset, list[str]]:
    """Copy of a material instance (mapped JSON is lossless for MICs) with vector parameters overridden."""
    a = Asset(game.json_of(mi_package))
    a.rename(mi_package, new_package, None)
    if a.j.get("FolderName") == mi_package:
        a.j["FolderName"] = new_package
    done = []
    for d in a.main_data():
        if d.get("Name") != "VectorParameterValues":
            continue
        for el in d["Value"]:
            f = {x["Name"]: x for x in el["Value"]}
            pname = next(x["Value"] for x in f["ParameterInfo"]["Value"] if x["Name"] == "Name")
            v = f["ParameterValue"]["Value"]
            if pname in params and v:
                r, g, b, al = params[pname]
                v[0]["Value"].update({"R": r, "G": g, "B": b, "A": al})
                done.append(pname)
    missing = set(params) - set(done)
    if missing:
        raise PresetError(f"{mi_package.rsplit('/', 1)[1]} has no vector parameters {sorted(missing)}")
    return a, done


def effect_copy(game: Game, source: str, target: str, spec: dict, mi_targets: dict[str, str]) -> RecoloredEffect:
    """Relocated raw copy of a Niagara system, rendering with the recolored material copies, plus the byte
    patches (same size) to apply to its .uexp after it is written."""
    a = Asset(game.json_of(source, mapped=False))
    a.rename(source, target, None)
    if a.j.get("FolderName") == source:
        a.j["FolderName"] = target
    for imp in a.imports:
        if imp["ObjectName"] in mi_targets:
            a.rename(imp["ObjectName"], mi_targets[imp["ObjectName"]], None)
            imp["ObjectName"] = mi_targets[imp["ObjectName"]]
    eff = RecoloredEffect(source, target, a)
    mapped = game.json_of(source)
    if "lut_from" in spec:
        donor = color_lut(game.json_of(game.resolve(spec["lut_from"])))
        mine = color_lut(mapped)
        if len(donor) != len(mine):
            raise PresetError("lut_from: tables differ in size")
        eff.patches.append(BytePatch("ColorCurve LUT", _floats(*mine), _floats(*donor)))
    for lit in spec.get("literals", []):
        raw = spawn_literals(mapped, lit["emitter"])
        s, vals = lit["start"], lit["values"]
        eff.patches.append(BytePatch(f"{lit['emitter']}[{s}:{s + len(vals)}]", raw[s * 4:(s + len(vals)) * 4], _floats(*vals)))
    return eff


def apply_patches(uexp: Path, patches: list[BytePatch]) -> None:
    buf = bytearray(uexp.read_bytes())
    for p in patches:
        n = buf.count(p.old)
        if n != 1:
            raise PresetError(f"{uexp.name}: '{p.label}' found {n} times, expected exactly once")
        i = buf.find(p.old)
        buf[i:i + len(p.old)] = p.new
    uexp.write_bytes(bytes(buf))


def plan(game: Game, preset: dict, fx_folder: str) -> tuple[dict[str, str], list[RecoloredEffect], dict[str, Asset]]:
    """-> (original system package -> copy package, effect copies, material copies by package)."""
    folder = fx_folder.rstrip("/")
    mi_targets, materials = {}, {}
    for name, params in preset.get("materials", {}).items():
        src = game.resolve(name)
        dst = f"{folder}/MI/{name}"
        materials[dst], _ = material_copy(game, src, dst, params)
        mi_targets[src] = dst
    remap, effects = {}, []
    for name, spec in preset["systems"].items():
        src = game.resolve(name)
        dst = f"{folder}/{name}"
        effects.append(effect_copy(game, src, dst, spec, mi_targets))
        remap[src] = dst
    return remap, effects, materials


# --- automatic tint (experimental) ------------------------------------------------------------------
# Hand-made presets know every color source of one effect. A tint works on any effect instead: it moves the
# hue of every saturated color in the effect's color curves and in its material colors to one target hue,
# keeping brightness and saturation, and leaves white, grey and black alone. Colors baked into script
# constants are not touched, so some effects keep a part of their original color.
TINTS = {"crimson": 355, "ember": 18, "gold": 44, "jade": 140, "azure": 212, "violet": 278}
COLOR_PARAM = re.compile(r"colou?r|tint|emiss|glow|fresnel|edge|rim|weight", re.I)


def tint_rgb(r: float, g: float, b: float, hue: float) -> tuple[float, float, float]:
    """Same brightness and saturation, new hue; nearly grey colors stay as they are."""
    top = max(r, g, b)
    if top <= 0:
        return r, g, b
    h, s, v = colorsys.rgb_to_hsv(r / top, g / top, b / top)   # HDR values: normalise, then scale back
    if s < 0.12:
        return r, g, b
    nr, ng, nb = colorsys.hsv_to_rgb(hue / 360, s, v)
    return nr * top, ng * top, nb * top


def tint_material(game: Game, mi_package: str, new_package: str, hue: float) -> Asset | None:
    """Copy of a material instance with its colorful vector parameters tinted, or None if it has none."""
    a = Asset(game.json_of(mi_package))
    changed = False
    for d in a.main_data():
        if d.get("Name") != "VectorParameterValues":
            continue
        for el in d["Value"]:
            f = {x["Name"]: x for x in el["Value"]}
            pname = next(x["Value"] for x in f["ParameterInfo"]["Value"] if x["Name"] == "Name")
            v = f["ParameterValue"]["Value"]
            if not v or not COLOR_PARAM.search(str(pname)):
                continue
            c = v[0]["Value"]
            rgb = tuple(_num(c[k]) for k in "RGB")
            if max(rgb) > 50:   # not a color
                continue
            new = tint_rgb(*rgb, hue)
            if new != rgb:
                c.update({"R": new[0], "G": new[1], "B": new[2]})
                changed = True
    if not changed:
        return None
    a.rename(mi_package, new_package, None)
    if a.j.get("FolderName") == mi_package:
        a.j["FolderName"] = new_package
    return a


def tint_plan(game: Game, systems: list[str], tint: str, fx_folder: str) -> tuple[dict[str, str], list[RecoloredEffect], dict[str, Asset]]:
    """Tinted copies of the given effects (and of the materials they render with)."""
    if tint not in TINTS:
        raise PresetError(f"unknown tint '{tint}' (available: {', '.join(TINTS)})")
    hue = TINTS[tint]
    folder = f"{fx_folder.rstrip('/')}/{tint}"
    remap, effects, materials, mi_targets = {}, [], {}, {}
    game.prefetch(systems)
    for src in systems:
        raw = Asset(game.json_of(src, mapped=False))
        for i in raw.find_imports("MaterialInstanceConstant"):
            mi = raw.package_of(i)
            if mi in mi_targets or not game.has(mi):
                continue
            dst = f"{folder}/MI/{mi.rsplit('/', 1)[1]}"
            copy = tint_material(game, game.canon(mi), dst, hue)
            if copy is not None:
                materials[dst], mi_targets[mi] = copy, dst
        dst = f"{folder}/{src.rsplit('/', 1)[1]}"
        eff = effect_copy(game, src, dst, {}, mi_targets)
        mapped = game.json_of(src)
        for e in mapped["Exports"]:
            if str(e.get("ObjectName", "")).startswith("NiagaraDataInterfaceColorCurve"):
                lut = [_num(x["Value"]) for x in prop(e["Data"], "ShaderLUT")["Value"]]
                new = []
                for k in range(0, len(lut) - 3, 4):
                    new += [*tint_rgb(*lut[k:k + 3], hue), lut[k + 3]]
                if new != lut:
                    eff.patches.append(BytePatch(f"{e['ObjectName']} LUT", _floats(*lut), _floats(*new)))
        effects.append(eff)
        remap[src] = dst
    return remap, effects, materials
