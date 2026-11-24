import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cruxx_browser import shield  # noqa: E402


class ShieldTest(unittest.TestCase):
    def test_json_valid(self):
        rules = json.loads(shield.rules_json())
        self.assertIsInstance(rules, list)
        self.assertGreater(len(rules), len(shield.UNWANTED))

    def test_trigger_and_action(self):
        for rule in shield.build_rules():
            self.assertIn("url-filter", rule["trigger"])
            self.assertIn(rule["action"]["type"], ("block", "css-display-none"))
            if rule["action"]["type"] == "css-display-none":
                self.assertTrue(rule["action"]["selector"])

    def test_filters_compile_and_avoid_unsupported(self):
        for rule in shield.build_rules():
            pattern = rule["trigger"]["url-filter"]
            re.compile(pattern)
            self.assertNotIn("{", pattern)
            self.assertNotIn("|", pattern)

    def test_network_filter_matches(self):
        pattern = re.compile(shield.network_filter("doubleclick.net"))
        self.assertTrue(pattern.match("https://ad.doubleclick.net/x"))
        self.assertTrue(pattern.match("http://doubleclick.net:8080/"))
        self.assertFalse(pattern.match("https://notdoubleclick.net/"))
        self.assertFalse(pattern.match("https://example.com/doubleclick.net/"))
        self.assertEqual(shield.network_filter("a.b"), "^https?://([^/]+\\.)?a\\.b[:/]")

    def test_block_rules_third_party(self):
        blocks = [r for r in shield.build_rules() if r["action"]["type"] == "block"]
        self.assertEqual(len(blocks), len(shield.UNWANTED))
        for rule in blocks:
            self.assertEqual(rule["trigger"]["load-type"], ["third-party"])

    def test_site_rules_have_if_domain(self):
        rules = [r for r in shield.build_rules() if "if-domain" in r["trigger"]]
        self.assertEqual(len(rules), len(shield.SLOTS_BY_SITE) + 1)

    def test_identifier_changes(self):
        base = shield.rules_json()
        extra = shield.build_rules() + [{"trigger": {"url-filter": "x"},
                                         "action": {"type": "block"}}]
        self.assertEqual(shield.identifier(base), shield.identifier(shield.rules_json()))
        self.assertNotEqual(shield.identifier(base),
                            shield.identifier(shield.rules_json(extra)))
        self.assertTrue(shield.identifier(base).startswith("cruxx-shield-"))


class FakeManager:
    def __init__(self):
        self.added = 0
        self.removed = 0

    def add_filter(self, _f):
        self.added += 1

    def remove_filter(self, _f):
        self.removed += 1


class ShieldStateTest(unittest.TestCase):
    def test_late_filter_is_attached(self):
        sh = shield.Shield("/nonexistent")
        early, off = FakeManager(), FakeManager()
        sh.set_active(early, True)
        sh.set_active(off, False)
        self.assertEqual(early.added, 0)
        sh._release()  # timeout first
        sh._ready(object())  # late filter
        self.assertEqual((early.added, off.added), (1, 0))
        sh.set_active(early, True)
        self.assertEqual(early.added, 1)
        sh.set_active(early, False)
        self.assertEqual(early.removed, 1)

    def test_release_survives_failing_callback(self):
        sh = shield.Shield("/nonexistent")
        calls = []

        def bad():
            raise RuntimeError("x")
        sh.when_ready(bad)
        sh.when_ready(lambda: calls.append(1))
        with self.assertLogs("cruxx_browser.shield", "ERROR"):
            sh._release()
        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
