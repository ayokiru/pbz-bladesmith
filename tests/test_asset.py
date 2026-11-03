"""Checks that need no game files: python -m unittest"""
import unittest

from bladesmith.asset import Asset
from bladesmith.ops import RecipeError
from bladesmith.recipe import pak_name


def asset():
    return Asset({"NameMap": ["/Game/Old", "Old", "Package"], "Imports": [
        {"ObjectName": "/Game/Old", "OuterIndex": 0, "ClassName": "Package"},
        {"ObjectName": "Old", "OuterIndex": -1, "ClassName": "SkeletalMesh"}], "Exports": []})


class AssetTests(unittest.TestCase):
    def test_fname_base_is_added(self):
        # 'Foo_101' is stored as 'Foo' + 101; without the base UAssetGUI writes nothing
        a = asset()
        a.ensure_name("/X/Hun_Blade_101")
        self.assertIn("/X/Hun_Blade", a.names)
        a.ensure_name("Mesh_001")  # leading zero: stored whole, no base needed
        self.assertNotIn("Mesh", a.names)

    def test_repoint_replaces_names_in_place(self):
        a = asset()
        a.repoint_import(-2, "/Game/New", "New")
        self.assertEqual(a.names[:2], ["/Game/New", "New"])
        self.assertEqual(a.package_of(-2), "/Game/New")

    def test_add_import_is_reused(self):
        a = asset()
        i = a.add_object_import("/Game/Sc_101", "Sc_101", "SkeletalMesh", "/Script/Engine")
        self.assertEqual(a.add_object_import("/Game/Sc_101", "Sc_101", "SkeletalMesh", "/Script/Engine"), i)
        self.assertIn("Sc", a.names)


class PakNameTests(unittest.TestCase):
    def test_suffix_and_validation(self):
        self.assertEqual(pak_name({"pak_name": "zzz_Mine"}), "zzz_Mine_P")
        self.assertEqual(pak_name({"pak_name": "zzz_Mine_P"}), "zzz_Mine_P")
        for bad in ("../evil", "a/b", "x y", "C:\\x"):
            with self.assertRaises(RecipeError):
                pak_name({"pak_name": bad})


class TintTests(unittest.TestCase):
    def test_tint_keeps_greys_and_brightness(self):
        import colorsys
        from bladesmith.recolor import tint_rgb
        self.assertEqual(tint_rgb(0.5, 0.5, 0.5, 212), (0.5, 0.5, 0.5))      # grey stays grey
        r, g, b = tint_rgb(4.0, 0.2, 0.1, 212)                               # HDR red -> azure
        self.assertAlmostEqual(max(r, g, b), 4.0, places=5)                  # brightness kept
        self.assertAlmostEqual(colorsys.rgb_to_hsv(r / 4, g / 4, b / 4)[0] * 360, 212, delta=1)


class SafetyTests(unittest.TestCase):
    """The three places that silently damage data when they break."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from bladesmith.config import Config
        self.root = Path(tempfile.mkdtemp())
        paks = self.root / "PBZ" / "ProjectPBZ" / "Content" / "Paks"
        (paks / "~mods").mkdir(parents=True)
        (paks / "a.utoc").write_bytes(b"v1")
        self.cfg = Config(self.root / "PBZ", "0x0", Path("retoc.exe"), Path("UAssetGUI.exe"), "PBZ", self.root / "cache")

    def test_cache_is_wiped_after_a_game_patch(self):
        from unittest import mock
        from bladesmith import game
        with mock.patch.object(game.tools, "list_game_files", return_value=[]):
            game.Game(self.cfg)
            old = self.cfg.cache_dir / "legacy" / "old.uasset"
            old.parent.mkdir(parents=True)
            old.write_bytes(b"x")
            game.Game(self.cfg)                      # same game: cache kept
            self.assertTrue(old.exists())
            (self.cfg.paks_dir / "a.utoc").write_bytes(b"v2")   # patch
            game.Game(self.cfg)
            self.assertFalse(old.exists())

    def test_install_never_overwrites_a_foreign_pak(self):
        from unittest import mock
        from bladesmith import app
        (self.cfg.mods_dir / "zzz_Other_P.pak").write_bytes(b"theirs")
        with mock.patch.object(app, "INSTALLED", self.root / "installed.json"):
            res = app.Api(self.cfg).build({"pak_name": "zzz_Other_P", "weapons": [{"base": "Iron"}]}, True)
        self.assertFalse(res["ok"])
        self.assertEqual((self.cfg.mods_dir / "zzz_Other_P.pak").read_bytes(), b"theirs")

    def test_shared_color_curve_is_tinted_everywhere(self):
        from bladesmith.recolor import BytePatch, PresetError, apply_patches
        f = self.root / "x.uexp"
        f.write_bytes(b"..AAAA..AAAA..")
        apply_patches(f, [BytePatch("lut", b"AAAA", b"BBBB", every=True)])
        self.assertEqual(f.read_bytes(), b"..BBBB..BBBB..")
        with self.assertRaises(PresetError):                 # presets stay strict
            apply_patches(f, [BytePatch("lut", b"BBBB", b"CCCC")])


class MappingsTests(unittest.TestCase):
    """Up to 0.3.1 Bladesmith passed the mappings by name, which UAssetGUI only finds in the developer's own
    %LOCALAPPDATA%\\UAssetGUI; everyone else got unparsed assets."""

    def test_bundled_mappings_need_portable_mode(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from bladesmith import config
        tools = Path(tempfile.mkdtemp())
        exe, usmap = tools / "UAssetGUI.exe", tools / "Data" / "Mappings" / "PBZ.usmap"
        usmap.parent.mkdir(parents=True)
        usmap.write_bytes(b"usmap")
        with mock.patch.dict("os.environ", {"LOCALAPPDATA": str(tools / "nobody")}):
            with self.assertRaises(config.ConfigError):  # no config.json: UAssetGUI would not look in Data\Mappings
                config.find_mappings("PBZ", exe)
            (tools / "Data" / "config.json").write_text(config.PORTABLE_CONFIG)
            self.assertEqual(config.find_mappings("PBZ", exe), usmap)

    def test_cached_unparsed_json_is_converted_again(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock
        from bladesmith import game, tools
        g = game.Game.__new__(game.Game)
        g.json_dir = Path(tempfile.mkdtemp())
        g.cfg = mock.Mock(mappings="PBZ.usmap")
        g.rel = lambda p: "Weapon"
        g.legacy_file = lambda p: Path("Weapon.uasset")
        cached = g.json_dir / "Weapon.m.json"
        cached.write_text(json.dumps({"Exports": [{"$type": "UAssetAPI.ExportTypes.RawExport, UAssetAPI"}]}))
        good = {"Exports": [{"$type": "UAssetAPI.ExportTypes.NormalExport, UAssetAPI", "Data": []}]}
        with mock.patch.object(tools, "to_json", side_effect=lambda cfg, src, out, mapped: out.write_text(json.dumps(good))):
            self.assertEqual(g.json_of("/Game/Weapon"), good)
        cached.unlink()
        raw = json.dumps({"Exports": [{"$type": "RawExport"}]})
        with mock.patch.object(tools, "to_json", side_effect=lambda cfg, src, out, mapped: out.write_text(raw)):
            with self.assertRaises(tools.ToolError):
                g.json_of("/Game/Weapon")


class ImageTableTests(unittest.TestCase):
    def test_unreadable_weapon_table_names_the_export(self):
        # a user's run got the weapon table without its rows (KeyError 'Table' on the loading screen)
        from unittest import mock
        from bladesmith import images
        game = mock.Mock()
        game.json_of.return_value = {"NameMap": [], "Imports": [], "Exports": [{"$type": "UAssetAPI.ExportTypes.RawExport, UAssetAPI"}]}
        with self.assertRaisesRegex(RuntimeError, "no readable table.*RawExport"):
            images.render_paths(game)


if __name__ == "__main__":
    unittest.main()
