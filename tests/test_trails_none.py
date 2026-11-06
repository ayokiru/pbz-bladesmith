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



class WidenTrailRequirementTests(unittest.TestCase):
    def _action(self, tags, stream):
        def item(name, value):
            return {"Name": name, "Value": value}
        dic = [item(str(i), [item("TagName", t)]) for i, t in enumerate(tags)]
        q = [item("TagDictionary", dic), item("QueryTokenStream", [item(str(i), v) for i, v in enumerate(stream)]),
             item("AutoDescription", "")]
        return {"ObjectName": "GAA_PBZWeaponTrail_C_0", "Data": [item("ActivationRequirements", [item("TagQuery", q)])]}

    def test_any_query_gets_the_tag_once(self):
        from bladesmith.asset import Asset
        e = self._action(["Weapon.Type.Jade"], [0, 1, 1, 1, 0])
        a = Asset({"NameMap": [], "Imports": [], "Exports": [e]})
        self.assertEqual(ops.widen_trail_requirement(a, "Weapon.Type.DoubleBlade.Default"), 1)
        self.assertEqual(ops.widen_trail_requirement(a, "Weapon.Type.DoubleBlade.Default"), 0)
        q = a.j["Exports"][0]["Data"][0]["Value"][0]["Value"]  # Asset keeps its own copy
        self.assertEqual([x["Value"] for x in q[1]["Value"]], [0, 1, 1, 2, 0, 1])
        self.assertEqual(q[0]["Value"][1]["Value"][0]["Value"], "Weapon.Type.DoubleBlade.Default")
        self.assertIn("Weapon.Type.DoubleBlade.Default", a.names)

    def test_other_queries_are_left_alone(self):
        from bladesmith.asset import Asset
        e = self._action(["A.B"], [0, 1, 2, 1, 0])  # ALL(...)
        self.assertEqual(ops.widen_trail_requirement(Asset({"NameMap": [], "Imports": [], "Exports": [e]}), "C.D"), 0)
