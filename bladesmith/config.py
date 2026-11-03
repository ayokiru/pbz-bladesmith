"""Settings: where the game and the helper tools live.

Nothing has to be configured by hand: the game is found through Steam, the tools ship next to the program
(tools/), and a bladesmith.toml (next to the program or in %LOCALAPPDATA%/Bladesmith) only overrides that.
"""
from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

# AES key of the game's containers (build 5.7.4-301524), public in the modding community
PBZ_AES = "0x4BC8A51E5381325073F2BC7D4E3089CD557C4E9B7D453901C2C795518867E01D"
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
USER_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Bladesmith"
DOTNET_URL = "https://dotnet.microsoft.com/download/dotnet/8.0"


class ConfigError(RuntimeError):
    """kind: 'game' (folder not found), 'tool' (missing helper), 'dotnet' (UAssetGUI needs .NET 8 Desktop)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


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


def is_game_dir(p: Path | None) -> bool:
    return bool(p) and (Path(p) / "ProjectPBZ" / "Content" / "Paks").is_dir()


def find_game() -> Path | None:
    """The game's folder in any Steam library, or None."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        return None
    libraries = [steam]
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        libraries += [Path(m.replace("\\\\", "\\")) for m in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace"))]
    for lib in libraries:
        p = lib / "steamapps" / "common" / "PBZ"
        if is_game_dir(p):
            return p
    return None


def dotnet_desktop_8() -> bool:
    roots = [Path(os.environ.get(v, "")) / "dotnet" / "shared" / "Microsoft.WindowsDesktop.App"
             for v in ("ProgramFiles", "ProgramW6432")]
    return any(r.is_dir() and any(x.name.startswith("8.") for x in r.iterdir()) for r in roots)


def config_file(path: str | os.PathLike | None = None) -> Path | None:
    for p in ([Path(path)] if path else []) + [Path("bladesmith.toml"), APP_DIR / "bladesmith.toml", USER_DIR / "bladesmith.toml"]:
        if p.exists():
            return p
    if path:
        raise ConfigError("tool", f"config not found: {path}")
    return None


PORTABLE_CONFIG = '{"Note": "UAssetGUI portable mode for Bladesmith"}\n'  # UAssetGUI checks for its own name in it


def find_mappings(name: str, uassetgui: Path) -> Path:
    """The .usmap that UAssetGUI will load for `name`, or a clear error. UAssetGUI's command line only takes mappings
    by name (a file path is silently ignored, and the asset comes out unparsed) and looks for them in Data\\Mappings
    next to the exe when Data\\config.json mentions "UAssetGUI" (portable mode), else in %LOCALAPPDATA%\\UAssetGUI."""
    data = uassetgui.parent / "Data"
    try:
        portable = "UAssetGUI" in (data / "config.json").read_text(encoding="utf-8", errors="replace")
    except OSError:
        portable = False
    folder = data if portable else Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "UAssetGUI"
    usmap = folder / "Mappings" / f"{name}.usmap"
    if not usmap.is_file():
        raise ConfigError("tool", f"Game mappings missing: {usmap}. Unpack the whole Bladesmith archive, tools folder included.")
    return usmap


def load(path: str | os.PathLike | None = None) -> Config:
    f = config_file(path)
    raw = tomllib.loads(f.read_text(encoding="utf-8")) if f else {}
    base = f.resolve().parent if f else APP_DIR

    def path_of(key: str, default: Path | None) -> Path | None:
        v = raw.get(key)
        if v is None:
            return default
        q = Path(os.path.expandvars(os.path.expanduser(v)))
        return q if q.is_absolute() else base / q

    game = path_of("game_dir", None) or find_game()
    if not is_game_dir(game):
        raise ConfigError("game", "Bladesmith couldn't find Phantom Blade Zero. Pick the game folder, the one that contains ProjectPBZ.")
    cfg = Config(
        game_dir=game,
        aes_key=raw.get("aes_key", PBZ_AES),
        retoc=path_of("retoc", APP_DIR / "tools" / "retoc.exe"),
        uassetgui=path_of("uassetgui", APP_DIR / "tools" / "UAssetGUI.exe"),
        mappings=raw.get("mappings", "PBZ"),
        cache_dir=path_of("cache_dir", USER_DIR / "cache"),
    )
    for tool in (cfg.retoc, cfg.uassetgui):
        if not tool.exists():
            raise ConfigError("tool", f"Helper tool missing: {tool}. Unpack the whole Bladesmith archive, tools folder included.")
    find_mappings(cfg.mappings, cfg.uassetgui)
    if not dotnet_desktop_8():
        raise ConfigError("dotnet", "UAssetGUI needs the .NET 8 Desktop Runtime (x64). Install it, then start Bladesmith again.")
    return cfg


def save_game_dir(game: Path) -> None:
    """Remember a game folder the user picked by hand."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    f = USER_DIR / "bladesmith.toml"
    lines = [l for l in (f.read_text(encoding="utf-8").splitlines() if f.exists() else []) if not l.startswith("game_dir")]
    f.write_text("\n".join([f'game_dir = "{Path(game).as_posix()}"'] + lines) + "\n", encoding="utf-8")
