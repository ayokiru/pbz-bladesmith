"""What the game offers: player weapons, their slots, meshes, scabbards and trails."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .asset import Asset, prop_value
from .game import Game

# Weapons whose edited versions were checked in the game (as bases or as skins)
TESTED = {"BaiShanFengLeiJian", "BaiYing", "ChiRen", "ChiZheCanJian", "CiGuHunDunJian", "Double", "DualHook", "GuiTouBlade", "HeiMoShang", "Horizontal", "Iron", "JadeDual", "Jigsaw", "JueYing", "Long", "LuanYing_Evolution", "PoJun", "SlitheringSword", "SnakeDual", "Tang", "TianXuanQingTongJian", "WoodenSword", "YanYueDao", "YuuBlade", "ZhanMaBlade", "ZiMingJian"}  # checked in the game
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


def _parse(game: Game, key: str) -> Weapon:
    """Slots and trails from the weapon's data asset (blade meshes and fade flags are filled in by _enrich)."""
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
    return w


def _enrich(game: Game, w: Weapon, with_fade: bool) -> Weapon:
    for s in w.slots:
        if game.has(s.bp):
            s.mesh = blade_mesh(game, s.bp)
    if with_fade:
        for t in w.trails:
            if game.has(t.system):
                t.fade = b"UE_StartFade" in game.raw_bytes(t.system)
    return w


def load_weapon(game: Game, key: str, with_fade: bool = True) -> Weapon:
    w = _parse(game, key)
    game.prefetch([s.bp for s in w.slots])
    if with_fade:
        game.ensure([t.system for t in w.trails if game.has(t.system)])
    return _enrich(game, w, with_fade)


def build(game: Game, include_variants: bool = False) -> list[Weapon]:
    """All player weapons. Each stage is one retoc run plus parallel JSON conversion, not one run per weapon."""
    keys = [k for k in game.weapon_keys() if include_variants or not VARIANT.search(k)]
    game.prefetch([game.weapon_package(k) for k in keys])
    ws = [_parse(game, k) for k in keys]
    game.prefetch([s.bp for w in ws for s in w.slots])
    game.ensure([t.system for w in ws for t in w.trails if game.has(t.system)])
    return [_enrich(game, w, True) for w in ws]


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


PREBUILT = Path(__file__).with_name("data") / "prebuilt.json"


def _prebuilt(game: Game, part: str):
    """Catalog or trail library shipped for the game build the release was made with, if the game matches."""
    if PREBUILT.exists():
        d = json.loads(PREBUILT.read_text(encoding="utf-8"))
        if d.get("fingerprint") == game.fingerprint():
            return d[part]
    return None


def cached(game: Game) -> list[Weapon]:
    """Catalog from the cache; on first use from the shipped copy, or built from the game after a patch."""
    p = game.cfg.cache_dir / "catalog.json"
    if not p.exists():
        pre = _prebuilt(game, "catalog")
        if pre is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(pre, ensure_ascii=False), encoding="utf-8")
        else:
            save(build(game), p)
    return load(p)


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
    pre = _prebuilt(game, "trails")
    if pre is not None:
        p.write_text(json.dumps(pre), encoding="utf-8")
        return pre
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
