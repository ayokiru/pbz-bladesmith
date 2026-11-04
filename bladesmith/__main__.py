"""bladesmith catalog | build RECIPE [-o OUT] [--install]"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import catalog, config, recipe
from .game import Game
from .ops import RecipeError
from .recolor import PresetError
from .tools import ToolError


def cmd_catalog(cfg, args) -> None:
    g = Game(cfg)
    ws = catalog.build(g, include_variants=args.all)
    catalog.save(ws, Path(args.out))
    if not args.all:
        catalog.save(ws, cfg.cache_dir / "catalog.json")
    for w in ws:
        meshes = ", ".join((s.mesh or "?").rsplit("/", 1)[-1] for s in w.slots)
        print(f"{w.key:24s} {w.kind:19s} fade={'Y' if w.fades else '-'}  {meshes}")
    print(f"\n{len(ws)} weapons -> {args.out}")


def cmd_build(cfg, args) -> None:
    g = Game(cfg)
    r = recipe.load(args.recipe)
    out = Path(args.out)
    utoc, log, _ = recipe.run(g, r, cfg.cache_dir / "stage", out, allow_mismatch=args.allow_mismatch)
    print("\n".join(log))
    print(f"\nbuilt {utoc.with_suffix('.pak').name}, {utoc.name}, {utoc.with_suffix('.ucas').name} in {out}")
    if args.install:
        for ext in (".pak", ".utoc", ".ucas"):
            shutil.copy2(utoc.with_suffix(ext), cfg.mods_dir / utoc.with_suffix(ext).name)
        print(f"installed to {cfg.mods_dir} (close the game first: it locks mod files)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bladesmith", description="Weapon transmog builder for Phantom Blade Zero")
    ap.add_argument("-c", "--config", default=None, help="config file (default: bladesmith.toml)")
    sub = ap.add_subparsers(dest="cmd")  # no command: open the window
    c = sub.add_parser("catalog", help="list player weapons and write catalog.json")
    c.add_argument("-o", "--out", default="catalog.json")
    c.add_argument("--all", action="store_true", help="include prologue/test variants")
    b = sub.add_parser("build", help="build a pak from a recipe")
    b.add_argument("recipe")
    b.add_argument("-o", "--out", default="out")
    b.add_argument("--install", action="store_true", help="copy the pak into the game's ~mods folder")
    b.add_argument("--allow-mismatch", action="store_true", help="allow a skin from another weapon type")
    w = sub.add_parser("gui", help="open the Bladesmith window")
    w.add_argument("--debug", action="store_true", help="enable the web inspector")
    args = ap.parse_args(argv)
    if args.cmd in (None, "gui"):
        from . import app
        # the window handles a missing game folder or runtime itself, with a setup screen
        app.run(config.load(args.config) if args.config else None, debug=getattr(args, "debug", False))
        return 0
    try:
        cfg = config.load(args.config)
    except config.ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    try:
        {"catalog": cmd_catalog, "build": cmd_build}[args.cmd](cfg, args)
    except (RecipeError, PresetError, ToolError, KeyError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
