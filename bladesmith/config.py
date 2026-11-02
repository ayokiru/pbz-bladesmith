"""Settings: where the game and the helper tools live."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_FILE = "bladesmith.toml"


@dataclass
class Config:
    game_dir: Path
    aes_key: str
    retoc: Path
    uassetgui: Path
    mappings: str
    cache_dir: Path

    @property
    def paks_dir(self) -> Path:
        return self.game_dir / "ProjectPBZ" / "Content" / "Paks"

    @property
    def mods_dir(self) -> Path:
        return self.paks_dir / "~mods"


def load(path: str | os.PathLike | None = None) -> Config:
    p = Path(path or DEFAULT_FILE)
    if not p.exists():
        raise SystemExit(f"config not found: {p} (copy bladesmith.example.toml to {DEFAULT_FILE} and edit it)")
    raw = tomllib.loads(p.read_text(encoding="utf-8"))
    base = p.resolve().parent

    def path_of(key: str, default: str | None = None) -> Path:
        v = raw.get(key, default)
        if v is None:
            raise SystemExit(f"config: '{key}' is missing")
        q = Path(os.path.expandvars(os.path.expanduser(v)))
        return q if q.is_absolute() else base / q

    cfg = Config(
        game_dir=path_of("game_dir"),
        aes_key=raw.get("aes_key", ""),
        retoc=path_of("retoc", "tools/retoc.exe"),
        uassetgui=path_of("uassetgui", "tools/UAssetGUI.exe"),
        mappings=raw.get("mappings", "PBZ"),
        cache_dir=path_of("cache_dir", ".cache"),
    )
    if not cfg.paks_dir.is_dir():
        raise SystemExit(f"config: no Paks folder under game_dir: {cfg.paks_dir}")
    for tool in (cfg.retoc, cfg.uassetgui):
        if not tool.exists():
            raise SystemExit(f"config: tool not found: {tool}")
    return cfg
