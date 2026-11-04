import unittest

from bladesmith.catalog import Slot, Weapon


def weapon(sockets, hands=""):
    return Weapon("W", "/W", slots=[Slot(None, s, "", "", None) for s in sockets], hands=hands)


class KindTests(unittest.TestCase):
    def test_game_tag_wins_over_the_back_socket(self):
        # the Fanatic's swords: one-handed in the game, carried on the back like a greatsword
        self.assertEqual(weapon(["Pt_LongBlade_Back_Socket"], "SingleHanded").kind, "one-handed")

    def test_tags(self):
        self.assertEqual(weapon(["Pt_LongBlade_Back_Socket"], "TwoHanded").kind, "two-handed")
        self.assertEqual(weapon(["Pt_DoubleBlade_L", "Pt_DoubleBlade_R"], "DualHanded").kind, "dual")
        self.assertEqual(weapon(["Pt_TangBlade", "Pt_TangBlade_L"], "SingleHanded").kind, "one-handed+offhand")
        self.assertEqual(weapon(["Pt_Chakram_L", "Pt_Chakram_R"], "DualHanded").kind, "chakram")

    def test_sockets_when_there_is_no_tag(self):
        self.assertEqual(weapon(["Pt_LongBlade_Back_Socket"]).kind, "two-handed")
        self.assertEqual(weapon(["Pt_TangBlade_Socket"]).kind, "one-handed")


if __name__ == "__main__":
    unittest.main()
