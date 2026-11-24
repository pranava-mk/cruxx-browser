import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cruxx_browser import theme  # noqa: E402

GOOD = """
mode = "light"
accent = "#509475"
selection = "#32473B"
muted = "#53685B"
background = "#111c18"
dark_background = "#0c1512"
lighter_background = "#23372B"
foreground = "#C1C497"
light_foreground = "#D6D5BC"
red = "#FF5345"
"""


class ThemeTest(unittest.TestCase):
    def test_newline_rejected(self):
        # A "$" anchor accepts a trailing newline. fullmatch must not.
        self.assertFalse(theme._HEX.fullmatch("#509475\n"))
        self.assertTrue(theme._HEX.fullmatch("#509475"))
        bad = GOOD.replace('accent = "#509475"', 'accent = "#509475\\n"')
        self.assertEqual(theme.parse(bad), theme.FALLBACK)

    def test_valid(self):
        colors = theme.parse(GOOD)
        self.assertEqual(colors["accent"], "#509475")
        self.assertEqual(colors["mode"], "light")

    def test_css_has_accent(self):
        self.assertIn("#509475", theme.css(theme.parse(GOOD)))

    def test_missing_file(self):
        self.assertEqual(theme.load("/nonexistent/colors.toml"), theme.FALLBACK)

    def test_load_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "colors.toml")
            with open(path, "w") as handle:
                handle.write(GOOD)
            self.assertEqual(theme.load(path)["background"], "#111c18")

    def test_invalid_colour(self):
        for bad in ("red", "#fff", "#GGGGGG", "#1234567", 5):
            text = GOOD.replace('accent = "#509475"', "accent = %s" % (
                '"%s"' % bad if isinstance(bad, str) else bad))
            self.assertEqual(theme.parse(text), theme.FALLBACK, bad)

    def test_injection(self):
        text = GOOD.replace('"#509475"', '"#fff; } * { color: red"')
        colors = theme.parse(text)
        self.assertEqual(colors, theme.FALLBACK)
        self.assertNotIn("* { color: red", theme.css(colors))

    def test_bad_toml(self):
        self.assertEqual(theme.parse("not = = toml"), theme.FALLBACK)

    def test_bad_mode(self):
        self.assertEqual(theme.parse(GOOD.replace("light", "weird"))["mode"], "dark")

    def test_fallback_is_valid(self):
        for key in theme.COLOR_KEYS:
            self.assertRegex(theme.FALLBACK[key], r"^#[0-9A-Fa-f]{6}$")


if __name__ == "__main__":
    unittest.main()
