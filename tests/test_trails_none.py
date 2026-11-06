import unittest
from unittest import mock

from bladesmith import ops


def entry(tag):
    key = {"Value": [{"Value": "Weapon.Trail." + tag}]}
    val = {"Value": [{"Name": "Particle_12_ABC", "Value": -3, "IsZero": False}]}
    return [key, val]


class NoneTrailTests(unittest.TestCase):
    def test_none_points_at_the_empty_effect_not_at_nothing(self):
        # an empty reference makes the game fall back to a default trail (tested in game 05.11.2026)
        trails = [entry("Normal.A"), entry("Kick.L")]
        data = mock.Mock()
        data.main_data.return_value = [{"Name": "Trails", "Value": trails}]
        data.add_object_import.side_effect = lambda pkg, name, cls, cpkg: -9 if pkg == ops.EMPTY_SYSTEM else -1
        game = mock.Mock(resolve=lambda p: p, has=lambda p: False)
        report = ops.set_trails(data, {"*": "none"}, mock.Mock(fades=True, key="Iron"), game)
        self.assertEqual([t[1]["Value"][0]["Value"] for t in trails], [-9, -9])
        self.assertEqual(report, ["Normal.A -> none", "Kick.L -> none"])


class AddEquipTagTests(unittest.TestCase):
    def test_adds_once_and_registers_the_name(self):
        from bladesmith.ops import add_equip_tag
        from bladesmith.asset import Asset
        data = [{"Name": "Weapon Equip Tags", "Value": [{"Name": "Weapon Equip Tags", "Value": ["Weapon.Type.Global.DualHanded"]}]}]
        a = Asset({"NameMap": ["Weapon Equip Tags"], "Imports": [], "Exports": [{"ObjectName": "Default__X", "Data": data}]})
        a.main_data = lambda: data
        self.assertTrue(add_equip_tag(a, "Weapon.Type.Jade"))
        self.assertFalse(add_equip_tag(a, "Weapon.Type.Jade"))
        self.assertEqual(data[0]["Value"][0]["Value"], ["Weapon.Type.Global.DualHanded", "Weapon.Type.Jade"])
        self.assertIn("Weapon.Type.Jade", a.names)
