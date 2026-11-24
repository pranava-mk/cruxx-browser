import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cruxx_browser import omnibox  # noqa: E402
from cruxx_browser.__main__ import parse_args  # noqa: E402

DDG = "https://duckduckgo.com/?q="


class ClassifyTest(unittest.TestCase):
    CASES = [
        ("https://example.com", "https://example.com"),
        ("http://example.com/a b", DDG + "http%3A%2F%2Fexample.com%2Fa+b"),
        ("HTTP://Example.com", "HTTP://Example.com"),
        ("example.com", "https://example.com"),
        ("example.com/path?q=1", "https://example.com/path?q=1"),
        ("www.example.co.uk", "https://www.example.co.uk"),
        ("example.com:8080/x", "https://example.com:8080/x"),
        ("localhost", "http://localhost"),
        ("localhost:8080", "http://localhost:8080"),
        ("localhost:3000/a", "http://localhost:3000/a"),
        ("127.0.0.1", "http://127.0.0.1"),
        ("192.168.1.1:80/x", "http://192.168.1.1:80/x"),
        ("[::1]:3000", "http://[::1]:3000"),
        ("[::1]", "http://[::1]"),
        ("about:blank", "about:blank"),
        ("hello world", DDG + "hello+world"),
        ("hello", DDG + "hello"),
        ("javascript:alert(1)", DDG + "javascript%3Aalert%281%29"),
        ("file:///etc/passwd", DDG + "file%3A%2F%2F%2Fetc%2Fpasswd"),
        ("data:text/html,x", DDG + "data%3Atext%2Fhtml%2Cx"),
        ("what is 2+2", DDG + "what+is+2%2B2"),
        ("a.b", DDG + "a.b"),
        ("999.1.1.1", DDG + "999.1.1.1"),
        ("about:config", DDG + "about%3Aconfig"),
        ("café crème", DDG + "caf%C3%A9+cr%C3%A8me"),
        ("  example.com  ", "https://example.com"),
        ("user@example.com", DDG + "user%40example.com"),
        ("ftp://example.com", DDG + "ftp%3A%2F%2Fexample.com"),
    ]

    def test_cases(self):
        for text, want in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(omnibox.classify(text), want)

    def test_empty(self):
        for text in ("", "   ", "\t\n", None):
            self.assertIsNone(omnibox.classify(text))

    def test_engines(self):
        for name in omnibox.ENGINES:
            self.assertIn("q=a+b", omnibox.classify("a b", name))
        self.assertIn("google.com", omnibox.classify("x", "google"))
        self.assertTrue(omnibox.classify("x", "nope").startswith("https://duckduckgo.com"))


class RankTest(unittest.TestCase):
    def test_ranking(self):
        entries = [
            {"url": "https://other.com/example", "title": "x", "visits": 50, "last": 9},
            {"url": "https://example.com/a", "title": "x", "visits": 1, "last": 1},
            {"url": "https://www.example.org/", "title": "x", "visits": 5, "last": 2},
            {"url": "https://example.net/", "title": "x", "visits": 5, "last": 3},
            {"url": "https://nomatch.io/", "title": "x", "visits": 99, "last": 99},
        ]
        got = omnibox.rank(entries, "example")
        self.assertEqual(got, [
            "https://example.net/", "https://www.example.org/",
            "https://example.com/a", "https://other.com/example"])

    def test_title_match_and_empty(self):
        entries = [{"url": "https://a.com/", "title": "Cats", "visits": 1, "last": 1}]
        self.assertEqual(omnibox.rank(entries, "cat"), ["https://a.com/"])
        self.assertEqual(omnibox.rank(entries, " "), [])

    def test_limit(self):
        entries = [{"url": "https://a%d.com/" % i, "title": "", "visits": i, "last": i}
                   for i in range(20)]
        self.assertEqual(len(omnibox.rank(entries, "a")), 8)


class ArgsTest(unittest.TestCase):
    def test_defaults(self):
        opts = parse_args([])
        self.assertEqual(opts.urls, [])
        self.assertFalse(opts.private)
        self.assertFalse(opts.dev)

    def test_private_flag(self):
        self.assertTrue(parse_args(["--private"]).private)

    def test_incognito_aliases(self):
        # omarchy-launch-browser sends --incognito to most browsers.
        self.assertTrue(parse_args(["--incognito"]).private)
        self.assertTrue(parse_args(["--private-window"]).private)

    def test_private_with_urls(self):
        opts = parse_args(["--private", "example.com", "b.org"])
        self.assertTrue(opts.private)
        self.assertEqual(opts.urls, ["example.com", "b.org"])

    def test_test_flags(self):
        opts = parse_args(["--test-url", "http://x/", "--test-exit-after-load"])
        self.assertEqual(opts.test_url, "http://x/")
        self.assertTrue(opts.test_exit_after_load)

    def test_bad_flag(self):
        with self.assertRaises(ValueError):
            parse_args(["--nope"])


if __name__ == "__main__":
    unittest.main()
