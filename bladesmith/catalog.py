"""What the game offers: player weapons, their slots, meshes, scabbards and trails."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

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
    game.ensure([s.bp for s in w.slots if game.has(s.bp)])
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
        out.append(load_weapon(game, k))
    return out


def save(weapons: list[Weapon], path: Path) -> None:
    data = [dict(asdict(w), kind=w.kind, fades=w.fades, variant=w.variant) for w in weapons]
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load(path: Path) -> list[Weapon]:
    out = []
    for d in json.loads(Path(path).read_text(encoding="utf-8")):
        w = Weapon(d["key"], d["package"])
        w.slots = [Slot(**s) for s in d["slots"]]
        w.trails = [Trail(**t) for t in d["trails"]]
        out.append(w)
    return out


def cached(game: Game) -> list[Weapon]:
    """Catalog from the cache, built on first use."""
    p = game.cfg.cache_dir / "catalog.json"
    if p.exists():
        return load(p)
    ws = build(game)
    save(ws, p)
    return ws


TRAIL_NAME = re.compile(r"trail", re.I)
NOT_A_BLADE_TRAIL = re.compile(r"kick|foot|smoke|dust|_hand_|seq|notrail|absorb", re.I)


def trail_library(game: Game, weapons: list[Weapon]) -> dict[str, dict]:
    """Effects usable as attack trails: every system on player weapons plus every '*Trail*' system in the game.
    -> package -> {"fade": exposes UE_StartFade, "blade": built on NE_Template_BladeTrail (the template of the
    hero's own trails; streamer-style effects tend to leave a shape hanging on the blade tip), "player": bool}.
    Cached in cache_dir/trails.json."""
    p = game.cfg.cache_dir / "trails.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    player = {game.canon(t.system) for w in weapons for t in w.trails
              if game.has(t.system) and not t.tag.startswith("Kick")}
    others = {m for m in game.files if m.rsplit("/", 1)[1].startswith("NS_")
              and TRAIL_NAME.search(m.rsplit("/", 1)[1]) and not NOT_A_BLADE_TRAIL.search(m.rsplit("/", 1)[1])}
    pkgs = sorted(player | others, key=lambda m: m.rsplit("/", 1)[1].lower())
    game.ensure(pkgs)
    lib = {}
    for m in pkgs:
        try:
            raw = game.raw_bytes(m)
        except Exception:
            continue
        lib[m] = {"fade": b"UE_StartFade" in raw, "blade": b"NE_Template_BladeTrail" in raw, "player": m in player}
    p.write_text(json.dumps(lib, indent=1), encoding="utf-8")
    return lib


NAMES_FILE = Path(__file__).with_name("data") / "names.json"


def display_names() -> dict[str, str]:
    return json.loads(NAMES_FILE.read_text(encoding="utf-8")) if NAMES_FILE.exists() else {}
