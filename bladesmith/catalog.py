"""What the game offers: player weapons, their slots, meshes, scabbards and trails."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .asset import Asset, prop_value
from .game import Game

VARIANT = re.compile(r"Temp_|Prologue|HorseCart|Young_|Evaluation|^MoQie$|^XieHuo$|^ZhuGuangBaoQi$")


@dataclass
class Slot:
    bp: str | None            # package path of the weapon actor blueprint
    unarmed_socket: str
    armed_socket: str
    scabbard_socket: str
    scabbard: str | None      # package path of the scabbard mesh
    mesh: str | None = None   # package path of the blade mesh (from the blueprint)


@dataclass
class Trail:
    tag: str                  # part after "Weapon.Trail."
    slot: int
    socket: str
    system: str | None        # package path of the Niagara system
    fade: bool | None = None  # system exposes UE_StartFade


@dataclass
class Weapon:
    key: str
    package: str
    slots: list[Slot] = field(default_factory=list)
    trails: list[Trail] = field(default_factory=list)

    @property
    def kind(self) -> str:
        s = " ".join(x.unarmed_socket for x in self.slots)
        if "Chakram" in s:
            return "chakram"
        if len(self.slots) == 2 and "DoubleBlade" in s and "TangBlade" not in s:
            return "dual"
        if "LongBlade" in s:
            return "two-handed"
        if "TangBlade" in s:
            return "one-handed" + ("+offhand" if len(self.slots) > 1 else "")
        return "other"

    @property
    def fades(self) -> bool:
        """Trails of this weapon are ended with UE_StartFade; replacements must support it."""
        return any(t.fade for t in self.trails if not t.tag.startswith("Kick"))

    @property
    def variant(self) -> bool:
        return bool(VARIANT.search(self.key))


def blade_mesh(game: Game, bp_package: str) -> str | None:
    a = Asset(game.json_of(bp_package))
    try:
        wm = a.export("Weapon Mesh")
    except KeyError:
        return None
    idx = prop_value(wm["Data"], "SkeletalMesh")
    return a.package_of(idx) if isinstance(idx, int) and idx < 0 else None


def load_weapon(game: Game, key: str, with_fade: bool = True) -> Weapon:
    pkg = game.weapon_package(key)
    a = Asset(game.json_of(pkg))
    data = a.main_data()
    w = Weapon(key, pkg)
    for s in prop_value(data, "Display Data", []):
        v = {x["Name"]: x.get("Value") for x in s["Value"]}
        cls, sc = v.get("WeaponClass"), v.get("ScabbardMesh")
        bp = a.package_of(cls) if isinstance(cls, int) and cls < 0 else None
        w.slots.append(Slot(bp, v.get("UnarmedSocket") or "", v.get("ArmedSocket") or "", v.get("ScabbardSocket") or "",
                            a.package_of(sc) if isinstance(sc, int) and sc < 0 else None))
    for k, val in prop_value(data, "Trails", []):
        tag = k["Value"][0]["Value"]
        vv = {x["Name"].split("_")[0]: x.get("Value") for x in val["Value"]}
        n = vv.get("Particle")
        sysp = a.package_of(n) if isinstance(n, int) and n < 0 else None
        w.trails.append(Trail(tag.removeprefix("Weapon.Trail."), vv.get("WeaponIndex") or 0, vv.get("Slot") or "", sysp))
    for s in w.slots:
        if game.has(s.bp):
            s.mesh = blade_mesh(game, s.bp)
    if with_fade:
        systems = sorted({t.system for t in w.trails if game.has(t.system)})
        game.ensure(systems)
        for t in w.trails:
            if game.has(t.system):
                t.fade = b"UE_StartFade" in game.raw_bytes(t.system)
    return w


def build(game: Game, include_variants: bool = False) -> list[Weapon]:
    keys = game.weapon_keys()
    game.ensure([game.weapon_package(k) for k in keys])
    out = []
    for k in keys:
        if VARIANT.search(k) and not include_variants:
            continue
        w = load_weapon(game, k, with_fade=False)
        game.ensure([s.bp for s in w.slots if game.has(s.bp)])
        out.append(load_weapon(game, k))
    return out
