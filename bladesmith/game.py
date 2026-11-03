"""Index of the game's packages, and access to extracted copies of them."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from . import tools
from .config import Config

WEAPON_DIR = "/PBZCombatAsset/ActorData/Players/Hun/Weapon/"
# everything in the cache that comes from the game; wiped when a patch changes the game
GAME_DERIVED = ("legacy", "json", "img", "stage", "edit", "index.json", "catalog.json", "trails.json")


def game_fingerprint(paks_dir: Path) -> str:
    """Hash of the container tables: any patch that changes an asset changes its entry in a .utoc."""
    h = hashlib.sha1()
    for f in sorted(paks_dir.glob("*.utoc")):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def mount_of(rel: str) -> str:
    """ProjectPBZ/Plugins/<...>/<Plugin>/Content/X/Y.uasset -> /<Plugin>/X/Y ; ProjectPBZ/Content/X -> /Game/X"""
    p = rel.rsplit(".", 1)[0]
    parts = p.split("/")
    if parts[1] == "Plugins":
        i = parts.index("Content")
        return "/" + parts[i - 1] + "/" + "/".join(parts[i + 1:])
    if parts[1] == "Content":
        return "/Game/" + "/".join(parts[2:])
    raise ValueError(rel)


class Game:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.legacy = cfg.cache_dir / "legacy"
        self.json_dir = cfg.cache_dir / "json"
        self._fingerprint = game_fingerprint(cfg.paks_dir)
        stamp = cfg.cache_dir / "game.txt"
        if not stamp.exists() or stamp.read_text(encoding="utf-8") != self._fingerprint:
            for name in GAME_DERIVED:  # never reuse assets extracted from another game version
                p = cfg.cache_dir / name
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            cfg.cache_dir.mkdir(parents=True, exist_ok=True)
            stamp.write_text(self._fingerprint, encoding="utf-8")
        idx = cfg.cache_dir / "index.json"
        if idx.exists():
            self.files: dict[str, str] = json.loads(idx.read_text(encoding="utf-8"))
        else:
            files = [f for f in tools.list_game_files(cfg) if f.endswith(".uasset")]
            self.files = {mount_of(f): f[:-len(".uasset")] for f in files}
            idx.parent.mkdir(parents=True, exist_ok=True)
            idx.write_text(json.dumps(self.files), encoding="utf-8")
        self._by_name: dict[str, list[str]] = {}
        self._lower: dict[str, str] = {}
        for m in self.files:
            self._by_name.setdefault(m.rsplit("/", 1)[1].lower(), []).append(m)
            self._lower[m.lower()] = m

    def canon(self, package: str) -> str | None:
        """Package paths are case-insensitive in UE (imports say JigSaw, the file is Jigsaw)."""
        return self._lower.get(package.lower())

    def has(self, package: str | None) -> bool:
        return bool(package) and self.canon(package) is not None

    def fingerprint(self) -> str:
        return self._fingerprint

    # --- lookup -----------------------------------------------------------------------------------
    def resolve(self, name_or_path: str) -> str:
        """Asset name (NS_Foo) or package path (/Plugin/.../NS_Foo) -> package path."""
        if name_or_path.startswith("/"):
            c = self.canon(name_or_path)
            if c is None:
                raise KeyError(f"no such package in the game: {name_or_path}")
            return c
        hits = self._by_name.get(name_or_path.lower(), [])
        if len(hits) != 1:
            raise KeyError(f"'{name_or_path}' matches {len(hits)} packages{': ' + ', '.join(hits[:5]) if hits else ''}")
        return hits[0]

    def weapon_keys(self) -> list[str]:
        return sorted(m.rsplit("/", 1)[1][len("Weapon_Hun_"):] for m in self.files
                      if m.startswith(WEAPON_DIR) and m.rsplit("/", 1)[1].startswith("Weapon_Hun_"))

    def weapon_package(self, key: str) -> str:
        hits = [m for m in self.files if m.startswith(WEAPON_DIR) and m.endswith("/Weapon_Hun_" + key)]
        if len(hits) != 1:
            raise KeyError(f"weapon '{key}' not found (try `bladesmith catalog`)")
        return hits[0]

    # --- files --------------------------------------------------------------------------------------
    def rel(self, package: str) -> str:
        return self.files[self.canon(package)]

    def legacy_file(self, package: str) -> Path:
        f = self.legacy / (self.rel(package) + ".uasset")
        if not f.exists():
            tools.extract(self.cfg, [self.rel(package).split("/", 1)[1] + "."], self.legacy)
        if not f.exists():
            raise tools.ToolError(f"could not extract {package}")
        return f

    def ensure(self, packages: list[str]) -> None:
        missing = sorted({self.rel(p) for p in packages if not (self.legacy / (self.rel(p) + ".uasset")).exists()})
        if missing:
            tools.extract(self.cfg, [r.split("/", 1)[1] + "." for r in missing], self.legacy)

    def json_of(self, package: str, mapped: bool = True) -> dict:
        tag = "m" if mapped else "raw"
        js = self.json_dir / (self.rel(package) + f".{tag}.json")
        for attempt in range(2):
            if not js.exists():
                tools.to_json(self.cfg, self.legacy_file(package), js, mapped)
            data = json.loads(js.read_text(encoding="utf-8-sig"))
            # UAssetGUI falls back to unparsed exports when it can't use the mappings; versions up to 0.3.1 cached
            # such files on every PC but the developer's, so a cached one is converted again before giving up
            # without mappings *every* export is raw; a parsed asset can still have one (a skeletal mesh itself is)
            if not mapped or not all("RawExport" in str(e.get("$type", "")) for e in data.get("Exports", [])):
                return data
            js.unlink()
        raise tools.ToolError(f"UAssetGUI couldn't read {package.rsplit('/', 1)[-1]} with the game mappings ({self.cfg.mappings})")

    def prefetch(self, packages: list[str], mapped: bool = True) -> None:
        """Extract in one retoc run, then convert to JSON. Conversions stay sequential: parallel UAssetGUI runs
        race on the mappings and silently return unparsed (raw) exports."""
        packages = sorted({p for p in packages if self.has(p)})
        self.ensure(packages)
        for p in packages:
            self.json_of(p, mapped)

    def raw_bytes(self, package: str) -> bytes:
        f = self.legacy_file(package)
        return f.read_bytes() + f.with_suffix(".uexp").read_bytes()
