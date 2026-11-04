import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from bladesmith import app, recipe


class FakeGame:
    """The bits of Game that the after-update check uses."""
    def __init__(self, hashes: dict[str, str], fingerprint: str = "new"):
        self.hashes, self.fp, self.ensured = hashes, fingerprint, []

    def has(self, p):
        return p in self.hashes

    def ensure(self, packages):
        self.ensured.append(list(packages))

    def source_hash(self, p):
        return self.hashes[p]

    def fingerprint(self):
        return self.fp


SOURCES = {"/Fx/NS_Trail_C": "old-c", "/Fx/NS_Trail_B": "b", "/Data/Weapon_Gone": "w"}


class SourcesChangedTests(unittest.TestCase):
    def test_changed_and_removed(self):
        g = FakeGame({"/Fx/NS_Trail_C": "new-c", "/Fx/NS_Trail_B": "b"})
        self.assertEqual(recipe.sources_changed(g, SOURCES), ["/Data/Weapon_Gone", "/Fx/NS_Trail_C"])
        self.assertEqual(len(g.ensured), 1)  # one extraction run, not one per package

    def test_nothing_changed(self):
        self.assertEqual(recipe.sources_changed(FakeGame(dict(SOURCES)), SOURCES), [])


class InstalledTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.mods = root / "mods"
        self.mods.mkdir()
        for name in ("zzz_Old_P", "zzz_Fine_P", "zzz_Legacy_P"):
            (self.mods / f"{name}.pak").write_bytes(b"")
        self.reg = root / "installed.json"
        self.reg.write_text(json.dumps({
            "zzz_Old_P": {"recipe": {}, "date": "d", "game": "old", "sources": SOURCES},
            "zzz_Fine_P": {"recipe": {}, "date": "d", "game": "old", "sources": {"/Fx/NS_Trail_B": "b"}},
            "zzz_Legacy_P": {"recipe": {}, "date": "d"},  # built before Bladesmith kept sources
        }), encoding="utf-8")
        self.patch = mock.patch.object(app, "INSTALLED", self.reg)
        self.patch.start()
        self.api = app.Api(SimpleNamespace(mods_dir=self.mods))
        self.api._game = FakeGame({"/Fx/NS_Trail_C": "new-c", "/Fx/NS_Trail_B": "b"})

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_stale_paks_after_a_game_update(self):
        got = {p["name"]: p["stale"] for p in self.api.installed()}
        self.assertEqual(got, {"zzz_Fine_P": [], "zzz_Legacy_P": [], "zzz_Old_P": ["Weapon_Gone", "NS_Trail_C"]})
        saved = json.loads(self.reg.read_text(encoding="utf-8"))
        self.assertEqual(saved["zzz_Fine_P"]["game"], "new")  # checked once, not again on every start
        self.assertEqual(saved["zzz_Old_P"]["game"], "old")   # still out of date until rebuilt
        self.assertNotIn("sources", self.api.installed()[0])  # the page doesn't need the hashes


if __name__ == "__main__":
    unittest.main()
