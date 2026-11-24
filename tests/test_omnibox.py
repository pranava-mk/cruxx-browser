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


class EditableTest(unittest.TestCase):
    def test_cases(self):
        cases = [
            ("https://example.com/", "example.com"),
            ("https://example.com/a?b=1", "example.com/a?b=1"),
            ("http://127.0.0.1:8000/", "127.0.0.1:8000"),
            ("http://localhost:3000/x", "localhost:3000/x"),
            # The field would add https. So plain http must keep its scheme.
            ("http://example.com/", "http://example.com/"),
            ("about:blank", "about:blank"),
            ("", ""),
        ]
        for url, want in cases:
            with self.subTest(url=url):
                self.assertEqual(omnibox.editable(url), want)

    def test_round_trip(self):
        for url in ("https://example.com/", "http://127.0.0.1:8000/a",
                    "https://example.com/dir/"):
            self.assertEqual(omnibox.classify(omnibox.editable(url)).rstrip("/"),
                             url.rstrip("/"))


class SuggestionsTest(unittest.TestCase):
    HISTORY = [
        {"url": "https://example.com/a", "title": "Example A", "visits": 3, "last": 5},
        {"url": "https://other.org/", "title": "Other", "visits": 1, "last": 1},
    ]
    MARKS = [{"url": "https://exam.dev/", "title": "Exam notes"}]

    def test_search_row_first(self):
        rows = omnibox.suggestions("exam", self.HISTORY, self.MARKS)
        self.assertEqual(rows[0]["kind"], "search")
        self.assertIn("Search DuckDuckGo for", rows[0]["label"])
        self.assertTrue(rows[0]["url"].startswith("https://duckduckgo.com/?q=exam"))
        kinds = {r["url"]: r["kind"] for r in rows[1:]}
        self.assertEqual(kinds["https://exam.dev/"], "bookmark")
        self.assertEqual(kinds["https://example.com/a"], "history")
        self.assertNotIn("https://other.org/", kinds)

    def test_engine_in_label(self):
        rows = omnibox.suggestions("a b", [], [], "google")
        self.assertIn("Google", rows[0]["label"])
        self.assertIn("google.com", rows[0]["url"])

    def test_address_gives_go_row(self):
        rows = omnibox.suggestions("example.com", self.HISTORY, [])
        self.assertEqual(rows[0]["kind"], "go")
        self.assertEqual(rows[0]["url"], "https://example.com")

    def test_empty_and_limit(self):
        self.assertEqual(omnibox.suggestions("  ", self.HISTORY, self.MARKS), [])
        many = [{"url": "https://a%d.com/" % i, "title": "", "visits": i, "last": i}
                for i in range(30)]
        self.assertEqual(len(omnibox.suggestions("a", many, [], limit=6)), 6)

    def test_duplicate_bookmark_not_repeated(self):
        marks = [{"url": "https://example.com/a", "title": "A"}]
        rows = omnibox.suggestions("example", self.HISTORY, marks)
        self.assertEqual([r["url"] for r in rows].count("https://example.com/a"), 1)


class FuzzyTest(unittest.TestCase):
    def test_miss(self):
        self.assertIsNone(omnibox.fuzzy_score("zzz", "GitHub"))
        self.assertIsNone(omnibox.fuzzy_score("git zzz", "GitHub"))

    def test_tiers(self):
        start = omnibox.fuzzy_score("git", "Mac git hub")
        inside = omnibox.fuzzy_score("hub", "GitHub")
        typo = omnibox.fuzzy_score("githb", "GitHub")
        self.assertEqual((start, inside, typo), (3, 2, 1))

    def test_all_words_needed(self):
        self.assertEqual(omnibox.fuzzy_score("mac apple", "Mac Studio - Apple"), 6)
        self.assertIsNone(omnibox.fuzzy_score("mac pear", "Mac Studio - Apple"))

    def test_typo_rules(self):
        # No typo is forgiven in a short word.
        self.assertIsNone(omnibox.fuzzy_score("gti", "github"))
        # A swap of the first two letters is one typo.
        self.assertEqual(omnibox.fuzzy_score("igthub", "github"), 1)
        # The first letter must be right.
        self.assertIsNone(omnibox.fuzzy_score("xithub", "github"))

    def test_abbreviation(self):
        self.assertEqual(omnibox.fuzzy_score("dwn", "downloads"), 1)

    def test_case_and_empty(self):
        self.assertEqual(omnibox.fuzzy_score("APPLE", "apple"), 3)
        self.assertEqual(omnibox.fuzzy_score("", "x"), 0)

    def test_switch_rank(self):
        tabs = [("Mac Studio - Apple", "https://apple.com/mac"),
                ("driceroland - GitHub", "https://github.com/driceroland"),
                ("Are.na", "https://are.na/"),
                ("Notes", "https://example.com/github")]
        self.assertEqual(omnibox.switch_rank("", tabs), [0, 1, 2, 3])
        # A title match is better than a URL match.
        self.assertEqual(omnibox.switch_rank("github", tabs), [1, 3])
        self.assertEqual(omnibox.switch_rank("apple", tabs), [0])
        self.assertEqual(omnibox.switch_rank("nothing", tabs), [])


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


class HugeInputTest(unittest.TestCase):
    def test_huge_title_is_fast(self):
        import time
        title = "lorem ipsum " * 90000
        start = time.monotonic()
        omnibox.fuzzy_score("zzzqqq lorem", title)
        omnibox.fuzzy_score("loerm ipsmu dolr", title)
        omnibox.switch_rank("lorem ipsum dolor sit amet x y z w", [(title, title)])
        self.assertLess(time.monotonic() - start, 0.05)

    def test_limits_keep_match(self):
        self.assertEqual(omnibox.fuzzy_score("apple", "apple " + "x" * 5000), 3)
        self.assertIsNone(omnibox.fuzzy_score("late", "x" * 400 + " late"))


if __name__ == "__main__":
    unittest.main()
