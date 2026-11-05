"""Thin wrappers around retoc (IoStore <-> legacy) and UAssetGUI (uasset <-> JSON)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .config import Config

ENGINE = "VER_UE5_6"  # PBZ is UE 5.7, but its packages use the 5.6 layout


class ToolError(RuntimeError):
    pass


# retoc and UAssetGUI are console programs: without this flag a windowed Bladesmith.exe flashes a console per call
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(args: list[str]) -> str:
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                       encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise ToolError(f"{Path(args[0]).name} failed ({r.returncode}): {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def list_game_files(cfg: Config) -> list[str]:
    """All package paths in the game, as ProjectPBZ/... relative paths with extension."""
    out = _run([cfg.retoc, "-a", cfg.aes_key, "list", "--path", cfg.paks_dir])
    files = []
    for line in out.splitlines():
        i = line.find("../../../")
        if i >= 0:
            files.append(line[i + 9:].strip())
    return files


def extract(cfg: Config, filters: list[str], dest: Path) -> str:
    """Convert matching game packages to legacy .uasset/.uexp files under dest. Returns retoc's output:
    it exits 0 even when a package fails to convert and only says why there."""
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(0, len(filters), 40):  # one retoc run scans all containers, so batch the filters
        args = [cfg.retoc, "-a", cfg.aes_key, "to-legacy", "--no-shaders"]
        for f in filters[i:i + 40]:
            args += ["-f", f]
        out.append(_run(args + [cfg.paks_dir, dest]))
    return "\n".join(out)


def pack(cfg: Config, stage: Path, utoc: Path) -> None:
    utoc.parent.mkdir(parents=True, exist_ok=True)
    for ext in (".utoc", ".ucas", ".pak"):
        utoc.with_suffix(ext).unlink(missing_ok=True)
    _run([cfg.retoc, "to-zen", "--version", "UE5_6", stage, utoc])


def to_json(cfg: Config, uasset: Path, out: Path, mapped: bool = True) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    args = [cfg.uassetgui, "tojson", uasset, out, ENGINE] + ([cfg.mappings] if mapped else [])
    _run(args)
    if not out.exists():
        raise ToolError(f"UAssetGUI wrote no JSON for {uasset}")


def from_json(cfg: Config, js: Path, uasset: Path, mapped: bool = True) -> None:
    """UAssetGUI fails silently on bad input, so the output is checked explicitly."""
    uasset.parent.mkdir(parents=True, exist_ok=True)
    for ext in (".uasset", ".uexp"):
        uasset.with_suffix(ext).unlink(missing_ok=True)
    args = [cfg.uassetgui, "fromjson", js, uasset] + ([cfg.mappings] if mapped else [])
    _run(args)
    if not uasset.exists() or not uasset.with_suffix(".uexp").exists():
        raise ToolError(f"UAssetGUI wrote nothing for {js} (often an FName whose base name is missing)")
