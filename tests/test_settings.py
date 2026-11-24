import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cruxx_browser import omnibox, shortcuts, store  # noqa: E402


class OptionTest(unittest.TestCase):
    def test_engine(self):
        self.assertEqual(store.check_option("engine", "kagi"), "kagi")
        for bad in ("bing", 3, None):
            with self.assertRaises(ValueError):
                store.check_option("engine", bad)

    def test_engines_match_omnibox(self):
        self.assertEqual(set(store.ENGINES), set(omnibox.ENGINES))

    def test_bool_and_sleep(self):
        self.assertIs(store.check_option("shield_enabled", False), False)
        with self.assertRaises(ValueError):
            store.check_option("shield_enabled", 1)
        self.assertEqual(store.check_option("sleep_after_min", 60), 60)
        for bad in (45, True, "30", -1):
            with self.assertRaises(ValueError):
                store.check_option("sleep_after_min", bad)
        with self.assertRaises(ValueError):
            store.check_option("unknown", True)

    def test_clean_zoom(self):
        self.assertEqual(store.clean_zoom(1.1000001), 1.1)
        self.assertEqual(store.clean_zoom(99), store.ZOOM_MAX)
        self.assertEqual(store.clean_zoom(0), store.ZOOM_MIN)
        for bad in (True, "1", None, float("nan"), float("inf")):
            self.assertIsNone(store.clean_zoom(bad))

    def test_data_matches(self):
        self.assertTrue(store.data_matches(".example.com", "www.example.com"))
        self.assertTrue(store.data_matches("example.com", "example.com"))
        self.assertFalse(store.data_matches("cdn.example.com", "example.com"))
        self.assertFalse(store.data_matches("example.com", "a.example.com"))
        self.assertFalse(store.data_matches(".example.com", "a.example.com"))
        self.assertTrue(store.data_matches(".a.example.com", "a.example.com"))
        self.assertTrue(store.data_matches("www.example.com", "EXAMPLE.com"))
        self.assertFalse(store.data_matches("badexample.com", "example.com"))
        self.assertFalse(store.data_matches("", "example.com"))


class StoreOptionTest(unittest.TestCase):
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
        self.assertTrue(data.settings["restore_session"])
        self.assertEqual(data.settings["zoom_by_host"], {})
        self.assertTrue(data.settings["shield_enabled"])

    def test_set_option_saves(self):
        data = store.Store()
        data.set_option("engine", "brave")
        with self.assertRaises(ValueError):
            data.set_option("engine", "bing")
        self.assertEqual(store.Store().settings["engine"], "brave")

    def test_zoom_store(self):
        data = store.Store()
        data.set_zoom("www.Example.com", 1.3)
        self.assertEqual(data.zoom_for("example.com"), 1.3)
        self.assertEqual(store.Store().zoom_for("example.com"), 1.3)
        data.set_zoom("example.com", 1.0)
        self.assertEqual(data.zoom_for("example.com"), 1.0)
        self.assertEqual(store.Store().settings["zoom_by_host"], {})

    def test_bad_settings_file(self):
        data = store.Store()
        data.settings["zoom_by_host"] = {"a.com": 9, "b.com": "x", "c.com": 1.0}
        data.settings["engine"] = "bing"
        data.save_settings()
        again = store.Store().settings
        self.assertEqual(again["zoom_by_host"], {"a.com": store.ZOOM_MAX})
        self.assertEqual(again["engine"], "duckduckgo")

    def test_forget_permission(self):
        data = store.Store()
        data.remember_permission("https://a.com", "geolocation", True)
        data.remember_permission("https://a.com", "clipboard", False)
        data.forget_permission("https://a.com", "clipboard")
        self.assertEqual(store.Store().settings["permissions"],
                         {"https://a.com": {"geolocation": True}})
        data.forget_permission("https://a.com")
        self.assertEqual(store.Store().settings["permissions"], {})

    def test_hidden_edit(self):
        data = store.Store()
        data.add_hidden("a.com", ".x")
        data.add_hidden("a.com", ".y")
        data.remove_hidden("a.com", ".x")
        self.assertEqual(store.Store().hidden, {"a.com": [".y"]})
        data.remove_hidden("a.com", ".y")
        self.assertEqual(store.Store().hidden, {})
        data.add_hidden("b.com", ".z")
        data.clear_all_hidden()
        self.assertEqual(store.Store().hidden, {})


class ShortcutTest(unittest.TestCase):
    def test_every_action_has_label(self):
        for table in (shortcuts.PLAIN, shortcuts.SHIFT):
            for action in table.values():
                self.assertIn(action, shortcuts.LABELS)

    def test_rows(self):
        rows = dict(shortcuts.rows())
        self.assertEqual(rows["Ctrl+,"], "Settings")
        self.assertEqual(rows["Ctrl+I"], "Site card")
        self.assertEqual(rows["Ctrl+Shift+U"], "Hidden elements on this site")
        self.assertEqual(len(shortcuts.rows()),
                         len(shortcuts.PLAIN) + len(shortcuts.SHIFT)
                         + len(shortcuts.SPECIAL))

    def test_window_has_actions(self):
        src = open(os.path.join(os.path.dirname(shortcuts.__file__), "window.py")).read()
        for table in (shortcuts.PLAIN, shortcuts.SHIFT):
            for action in table.values():
                self.assertIn("def %s(" % action, src)


if __name__ == "__main__":
    unittest.main()
