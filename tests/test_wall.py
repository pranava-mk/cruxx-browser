import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cruxx_browser import floatvideo, shortcuts, store, wall  # noqa: E402


class CleanWallTest(unittest.TestCase):
    def test_default_for_junk(self):
        for raw in (None, 3, "x", [], {}):
            self.assertEqual(wall.clean_wall(raw), wall.DEFAULT_WALL)

    def test_fields_are_checked(self):
        out = wall.clean_wall({"kind": "gradient", "from": "#ABCDEF", "to": "red",
                               "angle": 725, "picture": "relative.png", "color": 5})
        self.assertEqual(out["kind"], "gradient")
        self.assertEqual(out["from"], "#abcdef")
        self.assertEqual(out["to"], wall.DEFAULT_WALL["to"])
        self.assertEqual(out["angle"], 5)
        self.assertEqual(out["picture"], "")
        self.assertEqual(out["color"], wall.DEFAULT_WALL["color"])
        self.assertEqual(wall.clean_wall({"kind": "bad"})["kind"], "off")
        self.assertEqual(wall.clean_wall({"angle": True})["angle"], 135)
        self.assertEqual(wall.clean_wall({"angle": float("nan")})["angle"], 135)

    def test_check_picture(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "a.png")
            with open(good, "wb") as handle:
                handle.write(b"x" * 10)
            link = os.path.join(tmp, "link")
            os.symlink(good, link)
            empty = os.path.join(tmp, "empty")
            open(empty, "wb").close()
            self.assertEqual(wall.check_picture(good), os.path.realpath(good))
            self.assertEqual(wall.check_picture(link), os.path.realpath(good))
            self.assertIsNone(wall.check_picture(tmp))
            self.assertIsNone(wall.check_picture(empty))
            self.assertIsNone(wall.check_picture(os.path.join(tmp, "none")))
            self.assertIsNone(wall.check_picture("relative"))
            self.assertIsNone(wall.check_picture(None))
            old = wall.PICTURE_MAX_BYTES
            wall.PICTURE_MAX_BYTES = 5
            try:
                self.assertIsNone(wall.check_picture(good))
            finally:
                wall.PICTURE_MAX_BYTES = old

    def test_gradient_points(self):
        x0, y0, x1, y1 = wall.gradient_points(200, 100, 90)
        self.assertAlmostEqual(x0, 0)
        self.assertAlmostEqual(x1, 200)
        self.assertAlmostEqual(y0, 50)
        x0, y0, x1, y1 = wall.gradient_points(200, 100, 180)
        self.assertAlmostEqual(y0, 0)
        self.assertAlmostEqual(y1, 100)

    def test_cover_geometry(self):
        sw, sh, cx, cy = wall.cover_geometry(1000, 500, 400, 400)
        self.assertEqual((sw, sh), (800, 400))
        self.assertEqual((cx, cy), (200, 0))
        sw, sh, cx, cy = wall.cover_geometry(500, 1000, 400, 400)
        self.assertEqual((sw, sh, cx, cy), (400, 800, 0, 200))
        for size in ((1920, 1080, 1280, 720), (333, 777, 1001, 503)):
            sw, sh, cx, cy = wall.cover_geometry(*size)
            self.assertGreaterEqual(sw - cx * 2, size[2])
            self.assertGreaterEqual(sh - cy * 2, size[3])
        self.assertEqual(wall.cover_geometry(0, 0, 10, 10), (10, 10, 0, 0))


class WallStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = {k: os.environ.get(k) for k in
                    ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME")}
        for key in self.old:
            os.environ[key] = os.path.join(self.tmp.name, key)
        self.addCleanup(self._restore)

    def _restore(self):
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_defaults(self):
        data = store.Store()
        self.assertEqual(data.settings["wall"]["kind"], "off")
        self.assertEqual(data.settings["peek_modifier"], "alt")

    def test_set_and_reload(self):
        data = store.Store()
        data.set_option("wall", {"kind": "color", "color": "#112233"})
        data.set_option("peek_modifier", "shift")
        again = store.Store()
        self.assertEqual(again.settings["wall"]["kind"], "color")
        self.assertEqual(again.settings["wall"]["color"], "#112233")
        self.assertEqual(again.settings["peek_modifier"], "shift")

    def test_bad_values(self):
        data = store.Store()
        for bad in ("off", None, 3):
            with self.assertRaises(ValueError):
                data.set_option("wall", bad)
        for bad in ("ctrl", True, None):
            with self.assertRaises(ValueError):
                store.check_option("peek_modifier", bad)
        self.assertEqual(data.settings["wall"]["kind"], "off")

    def test_bad_file_is_cleaned(self):
        data = store.Store()
        with open(data._p("settings.json"), "w") as handle:
            json.dump({"wall": {"kind": "picture", "picture": "../x", "angle": "a"},
                       "peek_modifier": "nope"}, handle)
        again = store.Store()
        self.assertEqual(again.settings["wall"]["picture"], "")
        self.assertEqual(again.settings["wall"]["angle"], 135)
        self.assertEqual(again.settings["peek_modifier"], "alt")


class FloatVideoTest(unittest.TestCase):
    def test_token(self):
        token = floatvideo.new_token()
        self.assertTrue(floatvideo.valid_token(token))
        self.assertNotEqual(token, floatvideo.new_token())
        for bad in ("", "ABCDEFGH", "abc def12", 'ab"cd12345', None, "a" * 100):
            self.assertFalse(floatvideo.valid_token(bad))
            with self.assertRaises(ValueError):
                floatvideo.title_for(bad)

    def test_steps(self):
        token = "0123456789ab"
        steps = floatvideo.steps(token, 100, 200)
        self.assertEqual(len(steps), 4)
        self.assertEqual(steps[0][0], 'hl.dsp.window.float({ window = '
                         '"title:^cruxx float 0123456789ab$", action = "on" })')
        self.assertIn("x = 480, y = 270", steps[1][0])
        self.assertIn("x = 100, y = 200", steps[2][0])
        self.assertTrue(steps[3][0].startswith("hl.dsp.window.pin("))
        self.assertEqual(len(floatvideo.steps(token)), 3)
        self.assertEqual(floatvideo.argv("a b", "c"), ["hyprctl", "dispatch", "a b", "c"])
        with self.assertRaises(ValueError):
            floatvideo.steps(token, "1", 2)

    def test_corner(self):
        mons = json.dumps([
            {"x": 0, "y": 0, "width": 1000, "height": 500, "scale": 1, "focused": False,
             "reserved": [0, 0, 0, 0]},
            {"x": 2000, "y": 100, "width": 3840, "height": 2160, "scale": 2.0,
             "focused": True, "reserved": [0, 30, 0, 10]}])
        self.assertEqual(floatvideo.corner_position(mons),
                         (2000 + 1920 - 480 - 24, 100 + 1080 - 10 - 270 - 24))
        for bad in ("", "{}", "[]", "[1]", None, '[{"focused": true}]'):
            self.assertIsNone(floatvideo.corner_position(bad))


class ShortcutFloatTest(unittest.TestCase):
    def test_float_shortcut(self):
        self.assertEqual(shortcuts.SHIFT["p"], "toggle_float")
        self.assertIn("Ctrl+Shift+P", dict(shortcuts.rows()))


if __name__ == "__main__":
    unittest.main()
