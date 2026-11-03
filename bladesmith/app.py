"""Bladesmith desktop window (pywebview + Edge WebView2). The page lives in web/, this is its Python API."""
from __future__ import annotations

import base64
import json
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path

import webview

from . import catalog, config, images, recipe
from .config import Config, ConfigError
from .game import Game
from .recolor import PRESET_DIR, TINTS

WEB = Path(__file__).with_name("web")
INSTALLED = config.USER_DIR / "installed.json"
PAK_EXT = (".pak", ".utoc", ".ucas")


def short(pkg: str | None) -> str:
    return (pkg or "?").rsplit("/", 1)[-1]


class Api:
    # pywebview exposes every public attribute to JavaScript and walks it recursively, so state is kept private
    def __init__(self, cfg: Config | None = None):
        self._cfg = cfg
        self._game: Game | None = None
        self._window: webview.Window | None = None
        self._lock = threading.Lock()

    # --- helpers --------------------------------------------------------------------------------------
    def _log(self, msg: str) -> None:
        if self._window:
            try:
                self._window.evaluate_js(f"window.onLog && window.onLog({json.dumps(msg)})")
            except Exception:
                pass  # a broken log line must never stop a build

    @staticmethod
    def _data_url(p: Path) -> str:
        return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()

    @staticmethod
    def _registry() -> dict:
        return json.loads(INSTALLED.read_text(encoding="utf-8")) if INSTALLED.exists() else {}

    @staticmethod
    def _save_registry(reg: dict) -> None:
        INSTALLED.parent.mkdir(parents=True, exist_ok=True)
        INSTALLED.write_text(json.dumps(reg, indent=2), encoding="utf-8")

    # --- called from JavaScript -------------------------------------------------------------------------
    def init(self) -> dict:
        """Everything the page needs, or {"setup": ...} when the game or a requirement is missing.
        The first run extracts weapon assets from the game (a few minutes)."""
        with self._lock:
            if self._cfg is None:
                try:
                    self._cfg = config.load()
                except ConfigError as e:
                    return {"setup": {"kind": e.kind, "message": str(e), "url": config.DOTNET_URL if e.kind == "dotnet" else None}}
            self._log("Reading the game...")
            self._game = Game(self._cfg)
            if not (self._cfg.cache_dir / "catalog.json").exists():
                self._log("First run: collecting weapons (about a minute)...")
            ws = catalog.cached(self._game)
            if not (self._cfg.cache_dir / "trails.json").exists():
                self._log("First run: indexing trail effects (a few minutes)...")
            lib = catalog.trail_library(self._game, ws)
            self._log("Loading weapon pictures...")
            imgs = images.weapon_images(self._game)
            names = catalog.display_names()
            presets = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(PRESET_DIR.glob("*.json"))]
            weapons = []
            for w in ws:
                weapons.append({
                    "key": w.key,
                    "name": names.get(w.key, w.key),
                    "named": w.key in names,
                    "kind": w.kind,
                    "family": w.kind.split("+")[0],
                    "fades": w.fades,
                    "blades": len(w.slots),
                    "skinnable": bool(w.slots) and all(s.mesh for s in w.slots),
                    "scabbard": any(s.scabbard for s in w.slots),
                    "tested": w.key in catalog.TESTED,
                    "img": self._data_url(imgs[w.key]) if w.key in imgs else None,
                    "trails": [{"tag": t.tag, "system": t.system, "name": short(t.system)}
                               for t in w.trails if not t.tag.startswith("Kick")],
                })
            self._log(f"{len(weapons)} weapons, {len(lib)} trail effects ready.")
            return {
                "weapons": weapons,
                "trails": [{"pkg": p, "name": short(p), **info} for p, info in lib.items()],
                "presets": [{"id": p["id"], "description": p.get("description", ""),
                             "systems": [s.lower() for s in p["systems"]]} for p in presets],
                "tints": [{"id": k, "hue": h} for k, h in TINTS.items()],
            }

    def choose_game_folder(self) -> dict:
        res = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not res:
            return {"ok": False}
        folder = Path(res[0] if isinstance(res, (list, tuple)) else res)
        if not config.is_game_dir(folder):
            return {"ok": False, "error": f"No ProjectPBZ\\Content\\Paks inside {folder}. Pick the folder Steam installed the game to."}
        config.save_game_dir(folder)
        return {"ok": True}

    def open_url(self, url: str) -> None:
        if url == config.DOTNET_URL:  # the only link the page opens
            os.startfile(url)

    def build(self, r: dict, install: bool) -> dict:
        with self._lock:
            try:
                name = recipe.pak_name(r)
                if install and name not in self._registry() and any((self._cfg.mods_dir / (name + e)).exists() for e in PAK_EXT):
                    return {"ok": False, "error": f"~mods already has a {name} that Bladesmith did not make. Pick another pak name."}
                out = self._cfg.cache_dir.parent / "out" / name
                self._log(f"Building {name}...")
                utoc, log = recipe.run(self._game, r, self._cfg.cache_dir / "stage", out, allow_mismatch=True)
                for line in log:
                    self._log(line)
                if install:
                    self._cfg.mods_dir.mkdir(exist_ok=True)
                    for ext in PAK_EXT:
                        shutil.copy2(utoc.with_suffix(ext), self._cfg.mods_dir / (name + ext))
                    reg = self._registry()
                    reg[name] = {"recipe": dict(r, pak_name=name), "date": datetime.now().strftime("%Y-%m-%d %H:%M")}
                    self._save_registry(reg)
                    self._log(f"Installed into {self._cfg.mods_dir}")
                return {"ok": True, "folder": str(out)}
            except PermissionError:
                return {"ok": False, "error": "A mod file is locked. Close the game and try again."}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def installed(self) -> list[dict]:
        """Paks this program installed that are still in ~mods (entries for paks deleted by hand are dropped)."""
        reg = self._registry()
        alive = {n: v for n, v in reg.items() if (self._cfg.mods_dir / (n + ".pak")).exists()}
        if alive != reg:
            self._save_registry(alive)
        return [{"name": n, **v} for n, v in sorted(alive.items())]

    def uninstall(self, name: str) -> dict:
        with self._lock:
            reg = self._registry()
            if name not in reg or not recipe.PAK_NAME.match(name):  # only paks this program installed
                return {"ok": False, "error": f"{name} was not installed by Bladesmith."}
            try:
                for ext in PAK_EXT:
                    (self._cfg.mods_dir / (name + ext)).unlink(missing_ok=True)
            except PermissionError:
                return {"ok": False, "error": "A mod file is locked. Close the game and try again."}
            del reg[name]
            self._save_registry(reg)
            self._log(f"Removed {name} from {self._cfg.mods_dir}")
            return {"ok": True}

    def save_recipe(self, r: dict) -> bool:
        res = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=f"{r.get('pak_name', 'recipe')}.json",
                                              file_types=("Recipe (*.json)",))
        if not res:
            return False
        Path(res if isinstance(res, str) else res[0]).write_text(json.dumps(r, indent=2), encoding="utf-8")
        return True

    def open_recipe(self) -> dict | None:
        res = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=("Recipe (*.json)",))
        if not res:
            return None
        return json.loads(Path(res[0]).read_text(encoding="utf-8"))


def run(cfg: Config | None = None, debug: bool = False) -> None:
    api = Api(cfg)
    api._window = webview.create_window("Bladesmith", str(WEB / "index.html"), js_api=api,
                                        width=1280, height=820, min_size=(1024, 680), background_color="#141215")
    webview.start(debug=debug)
