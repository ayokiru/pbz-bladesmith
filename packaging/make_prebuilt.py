"""Writes bladesmith/data/prebuilt.json (weapon catalog + trail library) for the installed game build, so a
release starts without the minute-long first scan. Run it from a fresh cache before each release."""
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bladesmith import catalog, config  # noqa: E402
from bladesmith.game import Game  # noqa: E402

cfg = config.load()
cfg.cache_dir = Path(tempfile.mkdtemp()) / "cache"   # never reuse a cache that may predate a fix
game = Game(cfg)
ws = catalog.build(game)
trails = catalog.trail_library(game, ws)
data = {"fingerprint": game.fingerprint(), "catalog": [asdict(w) for w in ws], "trails": trails}
catalog.PREBUILT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
print(catalog.PREBUILT, len(ws), "weapons,", len(trails), "trails, fingerprint", data["fingerprint"])
