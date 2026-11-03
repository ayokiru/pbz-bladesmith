"""Recipe -> edited assets in a stage folder -> pak.

Recipe (JSON):
{
  "pak_name": "zzz_MySkins_P",
  "fx_folder": "/PBZVFXPack/VFX/Bladesmith",           # where copied effects go (optional)
  "weapons": [
    {"base": "Iron", "skin": "Tang", "scabbard": true,
     "trails": {"Normal.A": "NS_JinYe_BloodTrail_101"}},
    {"base": "LuanYing_Evolution", "skin": "Tang", "slots": [0], "scabbard": true},
    {"base": "ZhanMaBlade", "skin": "Long", "scabbard": true, "trail_color": "outlaw-crimson"},
    {"base": "SnakeDual", "skin": "Double", "scabbard": true,
     "effect_meshes": [{"slot": 1, "system": "NS_SnakeDual_PhantomSword_001", "mesh": "SM_FX_DoubleBlade_101"}]}
  ]
}
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import ops, recolor, tools
from .asset import Asset, prop
from .catalog import load_weapon
from .game import Game

PAK_NAME = re.compile(r"^[A-Za-z0-9_\-]+$")


def _kind_family(kind: str) -> str:
    return kind.split("+")[0]


class Builder:
    def __init__(self, game: Game, recipe: dict, stage: Path, allow_mismatch: bool = False):
        self.game, self.stage = game, stage
        self.allow_mismatch = allow_mismatch
        self.edited: dict[str, tuple[Asset, bool]] = {}   # package -> (asset, mapped)
        self.patches: dict[str, list[recolor.BytePatch]] = {}
        self.log: list[str] = []
        self.fx_folder = recipe.get("fx_folder", "/PBZVFXPack/VFX/Bladesmith").rstrip("/")

    def _asset(self, package: str, mapped: bool = True) -> Asset:
        if package not in self.edited:
            self.edited[package] = (Asset(self.game.json_of(package, mapped)), mapped)
        return self.edited[package][0]

    def _add_copies(self, effects: list, materials: dict) -> None:
        for e in effects:
            self.edited[e.target] = (e.asset, False)   # Niagara copies: raw JSON, lossless
            self.patches[e.target] = e.patches
        for pkg, a in materials.items():
            self.edited[pkg] = (a, True)

    def weapon(self, w: dict) -> None:
        g = self.game
        base = load_weapon(g, w["base"])
        self.log.append(f"[{base.key}] {base.kind}")
        if "skin" in w:
            skin = load_weapon(g, w["skin"], with_fade=False)
            slots = w.get("slots", list(range(len(base.slots))))
            if any(not isinstance(i, int) or not 0 <= i < len(base.slots) for i in slots):
                raise ops.RecipeError(f"{base.key}: slots must be in 0..{len(base.slots) - 1}, got {slots}")
            if not self.allow_mismatch:
                if _kind_family(base.kind) != _kind_family(skin.kind):
                    raise ops.RecipeError(f"{base.key} is {base.kind}, skin {skin.key} is {skin.kind} "
                                          f"(hitboxes and animations stay with the base; use --allow-mismatch to force)")
                if "slots" not in w and len(base.slots) != len(skin.slots):
                    raise ops.RecipeError(f"{base.key} has {len(base.slots)} blades, {skin.key} has {len(skin.slots)}; "
                                          f"list the base slots to reskin with \"slots\"")
            for i in slots:
                b, s = base.slots[i], skin.slots[min(i, len(skin.slots) - 1)]
                if not b.bp or not s.mesh:
                    raise ops.RecipeError(f"slot {i}: missing blueprint or skin mesh")
                dropped = ops.set_blade_mesh(self._asset(b.bp), s.mesh)
                self.log.append(f"  slot {i}: {b.mesh.rsplit('/', 1)[1] if b.mesh else '?'} -> {s.mesh.rsplit('/', 1)[1]}"
                                + (f" (dropped {', '.join(dropped)})" if dropped else ""))
            if w.get("scabbard"):
                for i in slots:
                    s = skin.slots[min(i, len(skin.slots) - 1)]
                    if not s.scabbard:
                        continue
                    if base.slots[i].scabbard_socket != s.scabbard_socket:  # moving the scabbard crashes the game on equip
                        self.log.append(f"  slot {i}: {s.scabbard.rsplit('/', 1)[1]} doesn't fit {base.key}, skipped")
                    else:
                        ops.set_scabbard(self._asset(base.package), i, s.scabbard, s.scabbard_socket)
                        self.log.append(f"  slot {i}: scabbard {s.scabbard.rsplit('/', 1)[1]}")
        if w.get("blade_albedo"):  # experimental: the "Albedo Controls" vector of the blade's material, per weapon
            vals = [float(v) for v in w["blade_albedo"]]
            skin = load_weapon(g, w["skin"], with_fade=False) if "skin" in w else base
            for i in w.get("slots", list(range(len(base.slots)))):
                mesh = skin.slots[min(i, len(skin.slots) - 1)].mesh
                mi = Asset(g.json_of(mesh)).find_imports("MaterialInstanceConstant")
                if not mi:
                    raise ops.RecipeError(f"{mesh.rsplit('/', 1)[1]} has no material instance to recolor")
                src = g.canon(Asset(g.json_of(mesh)).package_of(mi[0]))
                # r0p2g1b1a0, not 0p2_1_1_0: an FName ending in _<digits> is stored as base + number, which breaks the copy
                tag = "".join(c + f"{v:g}".replace(".", "p").replace("-", "m") for c, v in zip("rgba", vals))
                dst = f"{self.fx_folder}/MI/{src.rsplit('/', 1)[1]}_{tag}"
                if dst not in self.edited:
                    self.edited[dst] = (recolor.material_copy(g, src, dst, {"Albedo Controls": vals})[0], True)
                ops.set_blade_material(self._asset(base.slots[i].bp), dst)
                self.log.append(f"  slot {i}: blade material {dst.rsplit('/', 1)[1]}")
        if w.get("trails"):
            for line in ops.set_trails(self._asset(base.package), w["trails"], base, g):
                self.log.append("  " + line)
        if w.get("trail_color"):
            preset = recolor.load_preset(w["trail_color"])
            remap, effects, materials = recolor.plan(g, preset, self.fx_folder)
            for line in ops.retarget_trails(self._asset(base.package), remap, g.canon, f"trail_color {preset['id']}"):
                self.log.append(f"  {line} ({preset['id']})")
            self._add_copies(effects, materials)
        if w.get("trail_tint"):
            data = self._asset(base.package)
            systems = []
            for key, val in prop(data.main_data(), "Trails")["Value"]:
                if key["Value"][0]["Value"].startswith("Weapon.Trail.Kick"):
                    continue
                idx = next(x for x in val["Value"] if x["Name"].startswith("Particle_")).get("Value")
                if isinstance(idx, int) and idx < 0 and g.has(data.package_of(idx)):
                    systems.append(g.canon(data.package_of(idx)))
            remap, effects, materials = recolor.tint_plan(g, sorted(set(systems)), w["trail_tint"], self.fx_folder)
            for line in ops.retarget_trails(data, remap, g.canon, f"trail_tint {w['trail_tint']}"):
                self.log.append(f"  {line} (tint {w['trail_tint']})")
            self._add_copies(effects, materials)
        for em in w.get("effect_meshes", []):
            if not 0 <= em.get("slot", -1) < len(base.slots) or not base.slots[em["slot"]].bp:
                raise ops.RecipeError(f"{base.key}: effect_meshes slot {em.get('slot')} has no blade blueprint")
            bp = base.slots[em["slot"]].bp
            old = g.resolve(em["system"])
            mesh_to = g.resolve(em["mesh"])
            raw = g.json_of(old, mapped=False)
            src_mesh = next(Asset(raw).package_of(i) for i in Asset(raw).find_imports("StaticMesh"))
            new = self.fx_folder + "/" + old.rsplit("/", 1)[1]
            copy = ops.copy_effect_with_mesh(raw, old, new, src_mesh, mesh_to)
            self.edited[new] = (copy, False)
            ops.repoint_attached_effect(self._asset(bp), old, new)
            self.log.append(f"  slot {em['slot']}: {old.rsplit('/', 1)[1]} copy with {mesh_to.rsplit('/', 1)[1]} -> {new}")

    def stage_path(self, package: str) -> Path:
        if self.game.has(package):
            rel = self.game.rel(package)
        else:  # new package: put it next to an existing one from the same mount root
            plugin = package.split("/")[1]
            sample = next((v for k, v in self.game.files.items() if k.startswith("/" + plugin + "/")), None)
            if sample is None:
                raise ops.RecipeError(f"unknown mount point for {package}")
            root = sample.split("/Content/")[0] + "/Content/"
            rel = root + "/".join(package.split("/")[2:])
        return self.stage / (rel + ".uasset")

    def write(self) -> None:
        if self.stage.exists():
            shutil.rmtree(self.stage)
        tmp = self.game.cfg.cache_dir / "edit"
        tmp.mkdir(parents=True, exist_ok=True)
        for i, (pkg, (a, mapped)) in enumerate(sorted(self.edited.items())):
            js = tmp / f"{i:03d}.json"
            js.write_text(a.dump(), encoding="utf-8")
            dst = self.stage_path(pkg)
            tools.from_json(self.game.cfg, js, dst, mapped)
            if pkg in self.patches:
                recolor.apply_patches(dst.with_suffix(".uexp"), self.patches[pkg])


def pak_name(recipe: dict) -> str:
    """Validated pak name; the engine mounts *_P paks after the game's own, so the suffix is added if missing."""
    name = str(recipe.get("pak_name") or "zzz_Bladesmith_P").strip()
    if not PAK_NAME.match(name):
        raise ops.RecipeError(f"pak_name may only use letters, digits, '_' and '-': {name!r}")
    return name if name.endswith("_P") else name + "_P"


def run(game: Game, recipe: dict, stage: Path, out_dir: Path, allow_mismatch: bool = False) -> tuple[Path, list[str]]:
    name = pak_name(recipe)
    if not recipe.get("weapons"):
        raise ops.RecipeError("the recipe has no weapons")
    b = Builder(game, recipe, stage, allow_mismatch)
    for w in recipe["weapons"]:
        b.weapon(w)
    b.write()
    utoc = out_dir / (name + ".utoc")
    tools.pack(game.cfg, stage, utoc)
    return utoc, b.log


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
