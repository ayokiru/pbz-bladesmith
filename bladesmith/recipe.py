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
    {"base": "Horizontal", "skin": "Tang", "blade_color": {"to": "#7a7a7a"}},  # optional "from": hue to replace
    {"base": "SnakeDual", "skin": "Double", "scabbard": true,
     "effect_meshes": [{"slot": 1, "system": "NS_SnakeDual_PhantomSword_001", "mesh": "SM_FX_DoubleBlade_101"}]}
  ]
}
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from . import ops, recolor, texrecolor, tools
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
        self.bulk: dict[str, bytes] = {}                   # package -> its .ubulk (recolored texture copies)
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
        if w.get("blade_color"):
            self._blade_color(base, w)
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

    def _blade_color(self, base, w: dict) -> None:
        """One color of the skin's albedo texture replaced, in copies of the texture and material that only this
        weapon's blades use (the mesh's material is overridden on the blueprint): the same skin elsewhere keeps its
        colors. Hilt, blade and scabbard share one texture, so a color used on all of them changes on all of them."""
        g, spec = self.game, w["blade_color"]
        skin = load_weapon(g, w["skin"], with_fade=False) if "skin" in w else base
        try:
            target = texrecolor.hex_rgb(str(spec.get("to", "")))
        except ValueError as e:
            raise ops.RecipeError(f"{base.key}: blade_color: {e}") from None
        for i in w.get("slots", list(range(len(base.slots)))):
            mesh = skin.slots[min(i, len(skin.slots) - 1)].mesh
            try:
                mi, tex, tex_idx = texrecolor.blade_material(g, mesh)
                uexp, ubulk = texrecolor.texture_files(g, tex)
                pal = texrecolor.palette(uexp, ubulk)
            except ValueError as e:
                raise ops.RecipeError(f"{base.key}: blade_color: {e}") from None
            hue = float(spec["from"]) if "from" in spec else (pal[0]["hue"] if pal else None)
            if hue is None:
                raise ops.RecipeError(f"{base.key}: {tex.rsplit('/', 1)[1]} has no colored areas to replace")
            # the picked color is what the typical shade of the old one becomes; lighter and darker shades follow
            near = min(pal, key=lambda p: abs((p["hue"] - hue + 180) % 360 - 180), default=None)
            bright = max(target) / max(max(near["color"]), 1e-3) if near else 1.0
            kw = {"hue_from": hue, "hue_width": float(spec.get("width", 40)), "brightness": min(bright, 3.0)}
            # c<hash>, not a bare hash: an FName ending in _<digits> is stored as base + number, which breaks the copy
            tag = "c" + hashlib.sha1(json.dumps([tex, target, kw], sort_keys=True).encode()).hexdigest()[:8]
            tex_dst = f"{self.fx_folder}/T/{tex.rsplit('/', 1)[1]}_{tag}"
            mi_dst = f"{self.fx_folder}/MI/{mi.rsplit('/', 1)[1]}_{tag}"
            if tex_dst not in self.edited:
                copy, bulk = texrecolor.texture_copy(g, tex, tex_dst, texrecolor.recolor_vt(uexp, ubulk, target, **kw))
                self.edited[tex_dst] = (copy, False)
                self.bulk[tex_dst] = bulk
                m = recolor.material_copy(g, mi, mi_dst, {})[0]
                m.repoint_import(tex_idx, tex_dst, tex_dst.rsplit("/", 1)[1])
                # the blueprint imports <package>.<last path segment>: an object still named after the original
                # isn't found, and the game silently keeps the mesh's own material
                m.ensure_name(mi_dst.rsplit("/", 1)[1])
                m.export(mi.rsplit("/", 1)[1])["ObjectName"] = mi_dst.rsplit("/", 1)[1]
                self.edited[mi_dst] = (m, True)
            ops.set_blade_material(self._asset(base.slots[i].bp), mi_dst)
            self.log.append(f"  slot {i}: {tex.rsplit('/', 1)[1]} hue {hue:g} -> {spec['to']}")

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
            if pkg in self.bulk:
                dst.with_suffix(".ubulk").write_bytes(self.bulk[pkg])
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
