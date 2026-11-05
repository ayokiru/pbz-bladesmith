import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bladesmith import tools


class OodleTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.cfg = mock.Mock(retoc=self.dir / "retoc.exe")
        self.good = b"oodle"
        patcher = mock.patch.object(tools, "OODLE_SHA256", hashlib.sha256(self.good).hexdigest())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_falls_back_to_a_mirror_and_skips_wrong_files(self):
        answers = [OSError("blocked"), io.BytesIO(b"captive portal page"), io.BytesIO(self.good)]

        def fake(url, timeout):
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a
        with mock.patch.object(tools.urllib.request, "urlopen", side_effect=fake):
            tools.ensure_oodle(self.cfg)
        self.assertEqual((self.dir / tools.OODLE_DLL).read_bytes(), self.good)

    def test_says_where_to_put_it_when_nothing_works(self):
        with mock.patch.object(tools.urllib.request, "urlopen", side_effect=OSError("offline")):
            with self.assertRaises(tools.ToolError) as e:
                tools.ensure_oodle(self.cfg)
        self.assertIn("jsdelivr", str(e.exception))
        self.assertIn(str(self.dir), str(e.exception))

    def test_a_good_dll_is_left_alone(self):
        (self.dir / tools.OODLE_DLL).write_bytes(self.good)
        with mock.patch.object(tools.urllib.request, "urlopen", side_effect=AssertionError("no download")):
            tools.ensure_oodle(self.cfg)
