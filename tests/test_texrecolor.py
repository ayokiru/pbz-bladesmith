import struct
import unittest

import numpy as np

from bladesmith import texrecolor as T


def block(c0, c1, idx=0x1B1B1B1B):
    return struct.pack("<HHI", c0, c1, idx)


def endpoints(data, bc3=False):
    rows = np.frombuffer(data, np.uint8).reshape(-1, 16 if bc3 else 8)[:, -8:]
    return [T._unpack565(np.array(struct.unpack_from("<HH", r.tobytes()), np.uint16)) for r in rows]


RED, DARK_RED, GRAY = 0xF800, 0x8000, 0x8410
BLUE = (0.2, 0.4, 1.0)


class RecolorTests(unittest.TestCase):
    def test_red_turns_blue_gray_stays(self):
        data = block(RED, DARK_RED) + block(GRAY, 0x4208)
        out = T.recolor_blocks(data, BLUE)
        self.assertEqual(len(out), len(data))
        red, gray = endpoints(out)
        self.assertTrue((red[:, 2] > red[:, 0]).all())  # blue now dominates both endpoints
        self.assertEqual(out[8:], data[8:])

    def test_block_mode_kept(self):
        # 4-color (c0 > c1) and 3-color (c0 <= c1) blocks must keep their mode after the endpoints change
        for c0, c1 in ((RED, DARK_RED), (DARK_RED, RED)):
            out = T.recolor_blocks(block(c0, c1), BLUE)
            n0, n1 = struct.unpack_from("<HH", out)
            self.assertEqual(c0 > c1, n0 > n1)

    def test_dxt5_alpha_untouched(self):
        alpha = bytes(range(8))
        out = T.recolor_blocks(alpha + block(DARK_RED, RED), BLUE, bc3=True)
        self.assertEqual(out[:8], alpha)
        self.assertTrue((endpoints(out, True)[0][:, 2] > 0.5).all())

    def test_hex(self):
        self.assertEqual(T.hex_rgb("#ff0080"), (1.0, 0.0, 128 / 255))
        with self.assertRaises(ValueError):
            T.hex_rgb("red")


if __name__ == "__main__":
    unittest.main()


class GrayLutTests(unittest.TestCase):
    def test_colors_turn_grey_at_their_brightest_channel_and_alpha_stays(self):
        from bladesmith.recolor import gray_lut
        self.assertEqual(gray_lut([0.004, 1.0, 0.5, 0.8, 1.0, 0.0, 0.0, 1.0]), [1.0, 1.0, 1.0, 0.8, 1.0, 1.0, 1.0, 1.0])

    def test_level_zero_is_black(self):
        from bladesmith.recolor import gray_lut
        self.assertEqual(gray_lut([0.004, 1.0, 0.5, 0.8], 0), [0.0, 0.0, 0.0, 0.8])


class AllColorsTests(unittest.TestCase):
    def test_grey_and_colored_pixels_all_turn_dark_grey_keeping_their_order(self):
        import numpy as np
        from bladesmith.texrecolor import recolor_colors
        rgb = np.array([[0.8, 0.8, 0.8], [0.4, 0.4, 0.4], [0.9, 0.1, 0.1]], np.float32)
        out = recolor_colors(rgb, (0.2, 0.2, 0.2), all_colors=True, brightness=0.2)
        self.assertTrue(np.allclose(out[:, 0], out[:, 1]) and np.allclose(out[:, 1], out[:, 2]))  # grey
        self.assertTrue(np.allclose(out[:, 0], [0.16, 0.08, 0.18], atol=1e-6))  # brightness kept in order
