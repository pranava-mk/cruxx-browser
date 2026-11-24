import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cruxx_browser import security  # noqa: E402


class SchemeTest(unittest.TestCase):
    TABLE = [
        ("https://example.com", True, "allow"),
        ("http://example.com", False, "allow"),
        ("HTTPS://EXAMPLE.COM", True, "allow"),
        ("about:blank", True, "allow"),
        ("about:srcdoc", False, "allow"),
        ("about:config", True, "block"),
        ("blob:https://example.com/uuid", True, "allow"),
        ("data:text/html,x", True, "block"),
        ("data:text/html,x", False, "allow"),
        ("file:///etc/passwd", True, "block"),
        ("file:///etc/passwd", False, "block"),
        ("javascript:alert(1)", True, "block"),
        ("mailto:a@b.c", True, "external"),
        ("tel:123", True, "external"),
        ("magnet:?xt=urn:btih:x", True, "external"),
        ("", True, "block"),
        (None, True, "block"),
        ("/relative/path", True, "block"),
    ]

    def test_table(self):
        for uri, main, want in self.TABLE:
            with self.subTest(uri=uri, main=main):
                self.assertEqual(security.scheme_decision(uri, main), want)


class DownloadNameTest(unittest.TestCase):
    def test_traversal(self):
        self.assertEqual(security.safe_download_name("../../.bashrc"), "bashrc")
        self.assertEqual(security.safe_download_name("..\\..\\evil.exe"), "evil.exe")

    def test_absolute(self):
        self.assertEqual(security.safe_download_name("/etc/passwd"), "passwd")
        self.assertEqual(security.safe_download_name("/"), "download")

    def test_control_chars(self):
        self.assertEqual(security.safe_download_name("a\x00b\x07c.txt"), "abc.txt")

    def test_leading_dots_dashes(self):
        self.assertEqual(security.safe_download_name("--rf .hidden"), "rf .hidden")
        self.assertEqual(security.safe_download_name(".."), "download")

    def test_whitespace(self):
        self.assertEqual(security.safe_download_name("a   b\t\nc.txt"), "a b c.txt")

    def test_empty(self):
        for name in ("", None, "   ", "\x00\x00", "...", "---"):
            self.assertEqual(security.safe_download_name(name), "download")

    def test_unicode(self):
        self.assertEqual(security.safe_download_name("résumé 日本.pdf"),
                         "résumé 日本.pdf")

    def test_long_keeps_extension(self):
        out = security.safe_download_name("a" * 500 + ".tar.gz")
        self.assertLessEqual(len(out.encode()), 200)
        self.assertTrue(out.endswith(".gz"))

    def test_long_unicode_valid(self):
        out = security.safe_download_name("日" * 300 + ".pdf")
        self.assertLessEqual(len(out.encode()), 200)
        self.assertTrue(out.endswith(".pdf"))
        out.encode("utf-8")

    def test_unique_name(self):
        taken = {"/d/a.txt", "/d/a (1).txt"}
        self.assertEqual(security.unique_name("/d", "a.txt", lambda p: p in taken), "a (2).txt")
        self.assertEqual(security.unique_name("/d", "b.txt", lambda p: p in taken), "b.txt")


class FakeSettings:
    def __init__(self, known):
        self.known = known
        self.values = {}

    def find_property(self, name):
        return object() if name in self.known else None

    def set_property(self, name, value):
        self.values[name] = value


class SettingsTest(unittest.TestCase):
    def test_required(self):
        table = security.WEBKIT_SETTINGS
        for name in ("allow-file-access-from-file-urls", "allow-universal-access-from-file-urls",
                     "javascript-can-open-windows-automatically",
                     "javascript-can-access-clipboard", "enable-developer-extras",
                     "enable-write-console-messages-to-stdout", "enable-dns-prefetching",
                     "enable-hyperlink-auditing"):
            self.assertIs(table[name], False, name)
        self.assertIs(table["enable-mediasource"], True)
        self.assertIs(table["enable-smooth-scrolling"], True)
        self.assertNotIn("enable-java", table)
        self.assertNotIn("hardware-acceleration-policy", table)

    def test_dev_flag(self):
        self.assertIs(security.settings_for(True)["enable-developer-extras"], True)
        self.assertIs(security.settings_for(False)["enable-developer-extras"], False)
        self.assertIs(security.WEBKIT_SETTINGS["enable-developer-extras"], False)

    def test_apply_skips_unknown(self):
        fake = FakeSettings({"enable-mediasource", "enable-developer-extras"})
        security.apply_settings(fake, True, logging.getLogger("t"))
        self.assertEqual(fake.values, {"enable-mediasource": True,
                                       "enable-developer-extras": True})


class DownloadHardeningTest(unittest.TestCase):
    def test_format_chars_removed(self):
        # U+202E bidi override, U+200B zero width space, U+FEFF
        self.assertEqual(security.safe_download_name("a\u202eexe.txt\u200b\ufeff"), "aexe.txt")

    def test_reserve_name_loop(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(security.reserve_name(tmp, "f.txt")[0], "f.txt")
            self.assertEqual(security.reserve_name(tmp, "f.txt")[0], "f (1).txt")
            name, path = security.reserve_name(tmp, "f.txt")
            self.assertEqual(name, "f (2).txt")
            self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")

    def test_reserve_name_dangling_symlink(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "victim")
            os.symlink(target, os.path.join(tmp, "f.txt"))
            name, _path = security.reserve_name(tmp, "f.txt")
            self.assertEqual(name, "f (1).txt")
            self.assertFalse(os.path.exists(target))

    def test_reserve_name_exhausted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            security.reserve_name(tmp, "f")
            with self.assertRaises(OSError):
                security.reserve_name(tmp, "f", max_tries=1)

    def test_reserve_name_bad_directory(self):
        with self.assertRaises(OSError):
            security.reserve_name("/nonexistent-dir-for-test", "f")


class PermissionOriginTest(unittest.TestCase):
    def test_origin_default_ports(self):
        o = security.permission_origin
        self.assertEqual(o("https://Example.com/x?y"), "https://example.com:443")
        self.assertEqual(o("https://example.com:443/"), "https://example.com:443")
        self.assertEqual(o("http://example.com"), "http://example.com:80")
        self.assertEqual(o("https://example.com:8443/"), "https://example.com:8443")
        self.assertEqual(o("http://[::1]:3000/"), "http://[::1]:3000")
        self.assertNotEqual(o("https://a.com"), o("http://a.com"))
        for bad in ("", "about:blank", "file:///x", "https://", "https://a.com:99999/", None):
            self.assertEqual(o(bad), "", repr(bad))

    def test_remember_allowed(self):
        o = security.permission_origin
        r = security.remember_allowed
        self.assertTrue(r(o("https://example.com/")))
        self.assertFalse(r(o("http://example.com/")))
        self.assertTrue(r(o("http://localhost:8080/")))
        self.assertTrue(r(o("http://127.0.0.1/")))
        self.assertTrue(r(o("http://[::1]/")))
        self.assertFalse(r(o("http://localhost.evil.com/")))
        self.assertFalse(r(""))

    def test_loadable_and_display(self):
        self.assertTrue(security.loadable("https://a.com/"))
        self.assertFalse(security.loadable("javascript:1"))
        self.assertFalse(security.loadable(None))
        text = security.display_uri("x-app:a\nb\x00c\u202ed" + "z" * 300)
        self.assertNotIn("\n", text)
        self.assertNotIn("\u202e", text)
        self.assertLessEqual(len(text), 203)


if __name__ == "__main__":
    unittest.main()
