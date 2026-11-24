import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cruxx_browser import store  # noqa: E402


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old = {k: os.environ.get(k) for k in
                     ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME")}
        os.environ["XDG_DATA_HOME"] = os.path.join(self.tmp.name, "d")
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name, "c")
        os.environ["XDG_CACHE_HOME"] = os.path.join(self.tmp.name, "k")
        self.addCleanup(self._restore)

    def _restore(self):
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    @staticmethod
    def load(path):
        with open(path) as handle:
            return json.load(handle)

    def mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_atomic_write_and_perms(self):
        path = os.path.join(self.tmp.name, "sub", "x.json")
        store.write_json_atomic(path, {"a": 1})
        self.assertEqual(self.load(path), {"a": 1})
        self.assertEqual(self.mode(path), 0o600)
        self.assertEqual(self.mode(os.path.dirname(path)), 0o700)
        self.assertEqual(os.listdir(os.path.dirname(path)), ["x.json"])

    def test_write_failure_leaves_old_file(self):
        path = os.path.join(self.tmp.name, "x.json")
        store.write_json_atomic(path, {"a": 1})
        with self.assertRaises(TypeError):
            store.write_json_atomic(path, {"a": object()})
        self.assertEqual(self.load(path), {"a": 1})
        self.assertEqual(os.listdir(self.tmp.name), ["x.json"])

    def test_corrupt_recovery(self):
        path = os.path.join(self.tmp.name, "bad.json")
        with open(path, "w") as handle:
            handle.write("{not json")
        self.assertEqual(store.read_json(path, []), [])
        names = os.listdir(self.tmp.name)
        self.assertTrue(any(n.startswith("bad.json.corrupt-") for n in names))
        self.assertNotIn("bad.json", names)

    def test_store_dirs_and_files(self):
        data = store.Store()
        data.save_session([], 0, "left")
        self.assertEqual(self.mode(store.data_dir()), 0o700)
        self.assertEqual(self.mode(os.path.join(store.data_dir(), "session.json")), 0o600)

    def test_bad_types_dropped(self):
        os.makedirs(store.data_dir())
        with open(os.path.join(store.data_dir(), "history.json"), "w") as handle:
            json.dump([{"url": "https://a.com", "title": "A", "visits": 1, "last": 1.0},
                       {"url": 5, "title": "x", "visits": 1, "last": 1},
                       {"url": "https://b.com", "title": "B", "visits": "1", "last": 1},
                       "junk", None], handle)
        with open(os.path.join(store.data_dir(), "session.json"), "w") as handle:
            json.dump({"tabs": [{"url": "https://a", "title": "t", "pinned": False},
                                {"url": "https://b", "title": "t", "pinned": "yes"}],
                       "active": 7, "side": "bottom"}, handle)
        data = store.Store()
        self.assertEqual([e["url"] for e in data.history], ["https://a.com"])
        session = data.load_session()
        self.assertEqual(len(session["tabs"]), 1)
        self.assertEqual(session["active"], 0)
        self.assertEqual(session["side"], "left")

    def test_history_cap_drops_oldest(self):
        data = store.Store()
        data.history = [{"url": "https://h%d.com" % i, "title": "", "visits": 1, "last": i}
                        for i in range(store.HISTORY_CAP)]
        data.add_visit("https://new.com", "New")
        self.assertEqual(len(data.history), store.HISTORY_CAP)
        urls = {e["url"] for e in data.history}
        self.assertIn("https://new.com", urls)
        self.assertNotIn("https://h0.com", urls)

    def test_history_visit_and_flush(self):
        data = store.Store()
        data.add_visit("https://a.com/", "A")
        data.add_visit("https://a.com/", "A2")
        data.add_visit("about:blank", "")
        self.assertEqual(len(data.history), 1)
        self.assertEqual(data.history[0]["visits"], 2)
        data.flush()
        self.assertEqual(len(store.Store().history), 1)

    def test_hidden_validation(self):
        data = store.Store()
        for bad in ("", "a" * 513, "a{b", "a}", "a<b", "a;b", "@import", "a\\b", 5, None,
                    "a/*b", "a*/b"):
            self.assertFalse(data.add_hidden("example.com", bad), repr(bad))
        self.assertTrue(data.add_hidden("www.example.com", "div.ad > p"))
        self.assertEqual(data.hidden, {"example.com": ["div.ad > p"]})
        self.assertEqual(store.Store().hidden, data.hidden)
        data.clear_hidden("shop.example.com")
        self.assertEqual(data.hidden, {"example.com": ["div.ad > p"]})
        data.clear_hidden("www.example.com")
        self.assertEqual(data.hidden, {})

    def test_hidden_cap(self):
        data = store.Store()
        for i in range(store.HIDDEN_CAP):
            self.assertTrue(data.add_hidden("example.com", "#a%d" % i))
        self.assertFalse(data.add_hidden("example.com", "#extra"))
        self.assertEqual(len(data.hidden["example.com"]), store.HIDDEN_CAP)

    def test_hidden_load_filters_bad(self):
        os.makedirs(store.data_dir())
        with open(os.path.join(store.data_dir(), "hidden.json"), "w") as handle:
            json.dump({"a.com": ["#ok", "x{y}", 5], "b.com": "nope", "c.com": ["a;b"]}, handle)
        self.assertEqual(store.Store().hidden, {"a.com": ["#ok"]})

    def test_registrable_host(self):
        for host, want in (("www.example.com", "example.com"), ("a.b.example.co.uk", "a.b.example.co.uk"),
                           ("example.com", "example.com"), ("localhost", "localhost"),
                           ("127.0.0.1", "127.0.0.1"), ("", ""),
                           ("WWW.Example.COM.", "example.com"), ("www.", "www")):
            self.assertEqual(store.registrable_host(host), want)

    def test_settings_validation_and_pause(self):
        os.makedirs(store.config_dir())
        with open(os.path.join(store.config_dir(), "settings.json"), "w") as handle:
            json.dump({"engine": 5, "shield_paused_hosts": ["a.com", 3],
                       "permissions": {"a.com": {"geolocation": True, "x": "bad"}}}, handle)
        data = store.Store()
        self.assertEqual(data.settings["engine"], "duckduckgo")
        self.assertEqual(data.settings["shield_paused_hosts"], ["a.com"])
        self.assertEqual(data.permission("a.com", "geolocation"), True)
        self.assertIsNone(data.permission("a.com", "x"))
        data.set_shield_paused("www.b.com", True)
        self.assertTrue(store.Store().shield_paused("b.com"))
        data.set_shield_paused("b.com", False)
        self.assertFalse(store.Store().shield_paused("b.com"))

    def test_bookmarks(self):
        data = store.Store()
        self.assertTrue(data.add_bookmark("https://a.com", "A"))
        self.assertFalse(data.add_bookmark("https://a.com", "A"))
        self.assertFalse(data.add_bookmark("file:///x", "x"))
        self.assertEqual(len(store.Store().bookmarks), 1)
        data.remove_bookmark("https://a.com")
        self.assertEqual(store.Store().bookmarks, [])


class ReadOnlyTest(StoreTest):
    def test_read_only_refuses_writes(self):
        data = store.Store(read_only=True)
        data.save_settings()
        data.save_session([], 0, False)
        data.history.append({"url": "https://example.com/", "title": "E", "time": 1})
        data.history_dirty = True
        data.flush()
        for name in os.listdir(data.dir) + os.listdir(data.cfg):
            self.assertNotIn(name, ("settings.json", "session.json", "history.json"))

    def test_normal_store_writes(self):
        data = store.Store()
        data.save_settings()
        self.assertTrue(os.path.exists(os.path.join(data.cfg, "settings.json"))
                        or os.path.exists(os.path.join(data.dir, "settings.json")))


class StoreHardeningTest(StoreTest):
    def _write(self, directory, name, text):
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, name)
        with open(path, "w") as handle:
            handle.write(text)
        return path

    def test_loaded_entries_filtered_by_scheme(self):
        bad = ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,x", "", "ftp://x/"]
        hist = [{"url": u, "title": "t", "visits": 1, "last": 1.0}
                for u in bad + ["https://ok.example/"]]
        marks = [{"url": u, "title": "t"} for u in bad + ["http://ok.example/"]]
        tabs = [{"url": u, "title": "t", "pinned": False} for u in bad]
        tabs.append({"url": "https://ok.example/", "title": "t", "pinned": False})
        self._write(store.data_dir(), "history.json", json.dumps(hist))
        self._write(store.data_dir(), "bookmarks.json", json.dumps(marks))
        self._write(store.data_dir(), "session.json",
                    json.dumps({"tabs": tabs, "active": 0, "side": "left"}))
        data = store.Store()
        self.assertEqual([e["url"] for e in data.history], ["https://ok.example/"])
        self.assertEqual([e["url"] for e in data.bookmarks], ["http://ok.example/"])
        session = data.load_session()
        # Blank tab (empty URL) stays. Other bad URLs go.
        self.assertEqual([t["url"] for t in session["tabs"]], ["", "https://ok.example/"])

    def test_read_json_recursion_error(self):
        path = self._write(self.tmp.name, "deep.json", "[" * 100000)
        self.assertEqual(store.read_json(path, "dflt"), "dflt")
        self.assertFalse(os.path.exists(path))
        self.assertTrue(any(n.startswith("deep.json.corrupt-") for n in os.listdir(self.tmp.name)))

    def test_read_json_type_error(self):
        path = os.path.join(self.tmp.name, "t.json")
        os.makedirs(self.tmp.name, exist_ok=True)
        from unittest import mock
        with open(path, "w") as handle:
            handle.write("{}")
        with mock.patch("json.load", side_effect=TypeError("x")):
            self.assertEqual(store.read_json(path, 7), 7)
        self.assertFalse(os.path.exists(path))

    def test_read_json_oserror_keeps_file(self):
        # A directory in place of the file gives IsADirectoryError (OSError).
        path = os.path.join(self.tmp.name, "dir.json")
        os.makedirs(path)
        self.assertEqual(store.read_json(path, "dflt"), "dflt")
        self.assertTrue(os.path.isdir(path))
        self.assertEqual(os.listdir(self.tmp.name), ["dir.json"])

    def test_add_hidden_rolls_back_on_write_failure(self):
        from unittest import mock
        data = store.Store()
        with mock.patch.object(store, "write_json_atomic", side_effect=OSError("full")):
            with self.assertRaises(OSError):
                data.add_hidden("example.com", "#x")
        self.assertEqual(data.hidden, {})


if __name__ == "__main__":
    unittest.main()
