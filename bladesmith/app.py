"""Bladesmith desktop window (pywebview + Edge WebView2). The page lives in web/, this is its Python API."""
from __future__ import annotations

import base64
import json
import shutil
import threading
from pathlib import Path

import webview

from . import catalog, images, recipe
from .config import Config
from .game import Game
from .recolor import PRESET_DIR

WEB = Path(__file__).with_name("web")


def short(pkg: str | None) -> str:
    return (pkg or "?").rsplit("/", 1)[-1]


class Api:
    # pywebview exposes every public attribute to JavaScript and walks it recursively, so state is kept private
    def __init__(self, cfg: Config):
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

    # --- called from JavaScript -------------------------------------------------------------------------
    def init(self) -> dict:
        """Everything the page needs. The first run extracts weapon assets from the game (a few minutes)."""
        with self._lock:
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
            }

    def build(self, r: dict, install: bool) -> dict:
        with self._lock:
            try:
                name = recipe.pak_name(r)
                out = self._cfg.cache_dir.parent / "out" / name
                self._log(f"Building {name}...")
                utoc, log = recipe.run(self._game, r, self._cfg.cache_dir / "stage", out, allow_mismatch=True)
                for line in log:
                    self._log(line)
                if install:
                    for ext in (".pak", ".utoc", ".ucas"):
                        shutil.copy2(utoc.with_suffix(ext), self._cfg.mods_dir / utoc.with_suffix(ext).name)
                    self._log(f"Installed into {self._cfg.mods_dir}")
                return {"ok": True, "folder": str(out)}
            except PermissionError:
                return {"ok": False, "error": "A mod file is locked. Close the game and try again."}
            except Exception as e:
                return {"ok": False, "error": str(e)}

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



def run(cfg: Config, debug: bool = False) -> None:
    api = Api(cfg)
    api._window = webview.create_window("Bladesmith", str(WEB / "index.html"), js_api=api,
                                       width=1280, height=820, min_size=(1024, 680), background_color="#141215")
    webview.start(debug=debug)
