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

import json
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
