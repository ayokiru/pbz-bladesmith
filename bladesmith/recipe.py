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
import shutil
from pathlib import Path

from . import ops, recolor, tools
from .asset import Asset
from .catalog import load_weapon
from .game import Game

STRICT_KINDS = True


def _kind_family(kind: str) -> str:
    return kind.split("+")[0]


class Builder:
    def __init__(self, game: Game, recipe: dict, stage: Path, allow_mismatch: bool = False):
        self.game, self.r, self.stage = game, recipe, stage
        self.allow_mismatch = allow_mismatch
        self.edited: dict[str, tuple[Asset, bool]] = {}   # package -> (asset, mapped)
        self.patches: dict[str, list[recolor.BytePatch]] = {}
        self.log: list[str] = []
        self.fx_folder = recipe.get("fx_folder", "/PBZVFXPack/VFX/Bladesmith").rstrip("/")

    def _asset(self, package: str, mapped: bool = True) -> Asset:
        if package not in self.edited:
            self.edited[package] = (Asset(self.game.json_of(package, mapped)), mapped)
        return self.edited[package][0]

    def weapon(self, w: dict) -> None:
        g = self.game
        base = load_weapon(g, w["base"])
        self.log.append(f"[{base.key}] {base.kind}")
        if "skin" in w:
            skin = load_weapon(g, w["skin"], with_fade=False)
            slots = w.get("slots", list(range(len(base.slots))))
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
                    if s.scabbard:
                        ops.set_scabbard(self._asset(base.package), i, s.scabbard, s.scabbard_socket)
                        self.log.append(f"  slot {i}: scabbard {s.scabbard.rsplit('/', 1)[1]}")
        if w.get("trails"):
            for line in ops.set_trails(self._asset(base.package), w["trails"], base, g):
                self.log.append("  " + line)
        if w.get("trail_color"):
            preset = recolor.load_preset(w["trail_color"])
            remap, effects, materials = recolor.plan(g, preset, self.fx_folder)
            for line in ops.retarget_trails(self._asset(base.package), remap, g.canon):
                self.log.append(f"  {line} ({preset['id']})")
            for e in effects:
                self.edited[e.target] = (e.asset, False)
                self.patches[e.target] = e.patches
            for pkg, a in materials.items():
                self.edited[pkg] = (a, True)
        for em in w.get("effect_meshes", []):
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
            sample = next(v for k, v in self.game.files.items() if k.startswith("/" + plugin + "/"))
            root = sample.split("/Content/")[0] + "/Content/"
            rel = root + "/".join(package.split("/")[2:])
        return self.stage / (rel + ".uasset")

    def write(self) -> list[Path]:
        if self.stage.exists():
            shutil.rmtree(self.stage)
        tmp = self.game.cfg.cache_dir / "edit"
        tmp.mkdir(parents=True, exist_ok=True)
        out = []
        for i, (pkg, (a, mapped)) in enumerate(sorted(self.edited.items())):
            js = tmp / f"{i:03d}.json"
            js.write_text(a.dump(), encoding="utf-8")
            dst = self.stage_path(pkg)
            tools.from_json(self.game.cfg, js, dst, mapped)
            if pkg in self.patches:
                recolor.apply_patches(dst.with_suffix(".uexp"), self.patches[pkg])
            out.append(dst)
        return out


def run(game: Game, recipe: dict, stage: Path, out_dir: Path, allow_mismatch: bool = False) -> tuple[Path, list[str]]:
    b = Builder(game, recipe, stage, allow_mismatch)
    for w in recipe["weapons"]:
        b.weapon(w)
    b.write()
    utoc = out_dir / (recipe.get("pak_name", "zzz_Bladesmith_P") + ".utoc")
    tools.pack(game.cfg, stage, utoc)
    return utoc, b.log


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
