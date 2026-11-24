import json
import unittest

from cruxx_browser import store, vault


def call(func, *args):
    box = []
    func(*args, box.append)
    return box[0]


class MemoryBackendTest(unittest.TestCase):
    def test_round_trip(self):
        mem = vault.MemoryBackend()
        o = "https://example.com:443"
        self.assertTrue(call(mem.put, o, "a", "pw1"))
        self.assertTrue(call(mem.put, o, "b", "pw2"))
        self.assertTrue(call(mem.put, "https://other.org:443", "c", "pw3"))
        self.assertEqual(call(mem.get, o, "a"), "pw1")
        self.assertEqual(call(mem.list, o), [(o, "a"), (o, "b")])
        self.assertEqual(len(call(mem.list, None)), 3)
        self.assertTrue(call(mem.put, o, "a", "new"))
        self.assertEqual(call(mem.get, o, "a"), "new")
        self.assertTrue(call(mem.delete, o, "a"))
        self.assertFalse(call(mem.delete, o, "a"))
        self.assertIsNone(call(mem.get, o, "a"))

    def test_exact_origin_only(self):
        mem = vault.MemoryBackend()
        call(mem.put, "https://example.com:443", "a", "x")
        self.assertEqual(call(mem.list, "https://sub.example.com:443"), [])
        self.assertEqual(call(mem.list, "http://example.com:80"), [])


class OriginTest(unittest.TestCase):
    def test_allowed(self):
        self.assertEqual(vault.vault_origin("https://Example.com/x?y=1"), "https://example.com:443")
        self.assertEqual(vault.vault_origin("https://example.com:443/"), "https://example.com:443")
        self.assertEqual(vault.vault_origin("http://localhost:8080/"), "http://localhost:8080")
        self.assertEqual(vault.vault_origin("http://127.0.0.1/"), "http://127.0.0.1:80")
        self.assertEqual(vault.vault_origin("http://[::1]:3000/"), "http://[::1]:3000")

    def test_refused(self):
        for uri in ("http://example.com/", "file:///etc/passwd", "about:blank", "",
                    "data:text/html,x", "ftp://example.com/", None):
            self.assertEqual(vault.vault_origin(uri), "", uri)

    def test_same_site(self):
        a = "https://login.example.com:443"
        self.assertTrue(vault.same_site(a, "https://example.com:443"))
        self.assertTrue(vault.same_site("https://www.example.com:443", "https://example.com:443"))
        self.assertFalse(vault.same_site(a, "https://example.com.evil.org:443"))
        self.assertFalse(vault.same_site(a, "https://notexample.com:443"))
        self.assertFalse(vault.same_site(a, ""))


class MessageTest(unittest.TestCase):
    def msg(self, body):
        return vault.parse_message(json.dumps(body))

    def test_submit(self):
        ok = self.msg({"kind": "submit", "username": "a", "password": "b"})
        self.assertEqual(ok, {"kind": "submit", "username": "a", "password": "b"})
        self.assertIsNotNone(self.msg({"kind": "submit", "username": "", "password": "b"}))

    def test_submit_bad(self):
        bad = [
            {"kind": "submit", "username": "a", "password": ""},
            {"kind": "submit", "username": "a" * 513, "password": "b"},
            {"kind": "submit", "username": "a", "password": "b" * 4097},
            {"kind": "submit", "username": "a", "password": "b\x00c"},
            {"kind": "submit", "username": "a\x00", "password": "b"},
            {"kind": "submit", "username": 1, "password": "b"},
            {"kind": "submit", "username": "a", "password": None},
            {"kind": "submit", "username": "a"},
            {"kind": "other"}, {}, [], "x", 5,
        ]
        for body in bad:
            self.assertIsNone(self.msg(body), body)
        self.assertIsNotNone(self.msg({"kind": "submit", "username": "a" * 512,
                                       "password": "b" * 4096}))

    def test_origin_field_ignored(self):
        got = self.msg({"kind": "submit", "username": "a", "password": "b",
                        "origin": "https://evil.org", "url": "x"})
        self.assertEqual(set(got), {"kind", "username", "password"})

    def test_focus(self):
        got = self.msg({"kind": "focus", "rect": {"x": 1, "y": 2.5, "w": 30, "h": 4}})
        self.assertEqual(got["rect"], {"x": 1.0, "y": 2.5, "w": 30.0, "h": 4.0})
        for rect in ({"x": "1", "y": 2, "w": 3, "h": 4}, {"x": True, "y": 2, "w": 3, "h": 4},
                     {"x": 1, "y": 2, "w": -3, "h": 4}, {"x": 1, "y": 2, "w": 3},
                     {"x": 1e12, "y": 2, "w": 3, "h": 4}, "x", None):
            self.assertIsNone(self.msg({"kind": "focus", "rect": rect}), rect)
        self.assertIsNone(vault.parse_message('{"kind":"focus","rect":{"x":NaN,"y":1,"w":1,"h":1}}'))

    def test_raw(self):
        self.assertIsNone(vault.parse_message("not json"))
        self.assertIsNone(vault.parse_message(None))
        self.assertIsNone(vault.parse_message("x" * (vault.MESSAGE_MAX + 1)))
        self.assertEqual(vault.parse_message('{"kind":"hide"}'), {"kind": "hide"})


class RuleTest(unittest.TestCase):
    def test_offer_kind(self):
        self.assertEqual(vault.offer_kind(None, "a"), "save")
        self.assertEqual(vault.offer_kind("a", "a"), "none")
        self.assertEqual(vault.offer_kind("a", "b"), "update")

    def test_pending(self):
        pending = {"time": 100.0}
        self.assertTrue(vault.pending_valid(pending, 159.0))
        self.assertFalse(vault.pending_valid(pending, 161.0))
        self.assertFalse(vault.pending_valid(None, 1.0))

    def test_clipboard_clear(self):
        self.assertTrue(vault.clipboard_should_clear("h", "h"))
        self.assertFalse(vault.clipboard_should_clear("other", "h"))
        self.assertFalse(vault.clipboard_should_clear(None, "h"))

    def test_label(self):
        self.assertEqual(vault.entry_label("bob", "example.com"),
                         "cruxx browser: bob @ example.com")


class NeverListTest(unittest.TestCase):
    def test_clean(self):
        got = store.clean_never(["https://a.com:443", "https://a.com:443", "a.com", 5,
                                 "https://a.com", "http://localhost:80", "x" * 400])
        self.assertEqual(got, ["https://a.com:443", "http://localhost:80"])
        self.assertEqual(store.clean_never("x"), [])

    def test_option(self):
        self.assertEqual(store.check_option("password_never", ["https://a.com:443", "bad"]),
                         ["https://a.com:443"])
        self.assertEqual(store.check_option("passwords_enabled", False), False)
        with self.assertRaises(ValueError):
            store.check_option("password_never", "https://a.com:443")
        with self.assertRaises(ValueError):
            store.check_option("passwords_enabled", "yes")

    def test_store(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for var in ("DATA", "CACHE", "CONFIG"):
                name = "XDG_%s_HOME" % var
                self.addCleanup(os.environ.pop, name, None)
                os.environ[name] = os.path.join(tmp, var)
            data = store.Store()
            self.assertTrue(data.settings["passwords_enabled"])
            data.add_password_never("https://a.com:443")
            data.add_password_never("https://a.com:443")
            self.assertEqual(data.settings["password_never"], ["https://a.com:443"])
            self.assertEqual(store.Store().settings["password_never"], ["https://a.com:443"])
            data.remove_password_never("https://a.com:443")
            self.assertEqual(data.settings["password_never"], [])


if __name__ == "__main__":
    unittest.main()
