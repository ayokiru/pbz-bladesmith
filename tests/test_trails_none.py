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


