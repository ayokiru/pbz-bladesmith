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


if __name__ == "__main__":
    unittest.main()
