import unittest

from cruxx_browser import spaces


class T:
    def __init__(self, pinned=False, private=False):
        self.pinned = pinned
        self.private = private


def keep(rows):
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


class MigrateTest(unittest.TestCase):
    def test_old_flat_session(self):
        out = spaces.migrate({"tabs": [{"url": "a"}, {"url": "b"}], "active": 1}, keep)
        self.assertEqual(len(out["spaces"]), 1)
        home = out["spaces"][0]
        self.assertEqual(home["name"], "Home")
        self.assertEqual(home["icon"], "H")
        self.assertEqual(home["active"], 1)
        self.assertEqual(out["current"], 0)

    def test_garbage(self):
        for raw in (None, [], 5, {"spaces": "x"}, {"spaces": [1, None]}):
            out = spaces.migrate(raw, keep)
            self.assertEqual([s["name"] for s in out["spaces"]], ["Home"])

    def test_new_session(self):
        raw = {"current": 1, "spaces": [
            {"name": "Work", "icon": "W", "tabs": [{"u": 1}, {"u": 2}], "active": 5,
             "splits": [{"a": 0, "b": 1, "ratio": 0.3}]},
            {"name": "  Fun  ", "icon": "\U0001F600x", "tabs": [{"u": 3}]}]}
        out = spaces.migrate(raw, keep)
        self.assertEqual(out["current"], 1)
        self.assertEqual(out["spaces"][0]["active"], 0)
        self.assertEqual(out["spaces"][0]["splits"], [{"a": 0, "b": 1, "ratio": 0.3}])
        self.assertEqual(out["spaces"][1]["name"], "Fun")
        self.assertEqual(out["spaces"][1]["icon"], "\U0001F600")

    def test_bad_current_and_cap(self):
        raw = {"current": 99, "spaces": [{"name": str(i)} for i in range(20)]}
        out = spaces.migrate(raw, keep)
        self.assertEqual(len(out["spaces"]), spaces.MAX_SPACES)
        self.assertEqual(out["current"], 0)


class SplitCleanTest(unittest.TestCase):
    def test_clean(self):
        rows = [{"pinned": False}, {"pinned": False}, {"pinned": True}, {"pinned": False}]
        items = [{"a": 0, "b": 1, "ratio": 9}, {"a": 1, "b": 3}, {"a": 2, "b": 3},
                 {"a": 0, "b": 0}, {"a": 7, "b": 1}, {"a": True, "b": 3}, "x",
                 {"a": 3, "b": 1}]
        out = spaces.clean_splits(items, rows)
        self.assertEqual(out, [{"a": 0, "b": 1, "ratio": spaces.RATIO_MAX}])
        self.assertEqual(spaces.clean_splits(None, rows), [])

    def test_ratio(self):
        self.assertEqual(spaces.clamp_ratio("x"), 0.5)
        self.assertEqual(spaces.clamp_ratio(0), spaces.RATIO_MIN)
        self.assertEqual(spaces.clamp_ratio(float("nan")), 0.5)


class OpsTest(unittest.TestCase):
    def test_split_rows_skip_private(self):
        a, b, c = T(), T(), T(private=True)
        saved = [a, b]
        pairs = [spaces.Split(a, b, 0.4), spaces.Split(b, c)]
        self.assertEqual(spaces.split_rows(saved, pairs), [{"a": 0, "b": 1, "ratio": 0.4}])
        self.assertEqual(spaces.split_rows([a, b], [spaces.Split(a, c)]), [])

    def test_regroup(self):
        a, b, c, d = T(), T(), T(), T()
        tabs = [a, b, c, d]
        self.assertTrue(spaces.regroup(tabs, [spaces.Split(a, d)]))
        self.assertEqual(tabs, [a, d, b, c])
        self.assertFalse(spaces.regroup(tabs, [spaces.Split(a, d)]))

    def test_choose_partner(self):
        a, b, c = T(), T(pinned=True), T()
        tabs = [b, a, c]
        self.assertIs(spaces.choose_partner(tabs, a, []), c)
        self.assertIsNone(spaces.choose_partner(tabs, a, [spaces.Split(c, T())]))
        self.assertIsNone(spaces.choose_partner([a], a, []))

    def test_visible(self):
        space = spaces.Space()
        a, b, c = T(), T(), T()
        space.tabs = [a, b, c]
        self.assertEqual(spaces.visible_tabs(space), [])
        space.active = c
        self.assertEqual(spaces.visible_tabs(space), [c])
        space.splits = [spaces.Split(a, b)]
        space.active = b
        self.assertEqual(spaces.visible_tabs(space), [a, b])

    def test_remove_and_step(self):
        items = [spaces.Space("a"), spaces.Space("b"), spaces.Space("c")]
        self.assertEqual(spaces.remove_space(items, 0, 2), 1)
        self.assertEqual(spaces.remove_space(items, 1, 1), 0)
        self.assertEqual(spaces.remove_space(items, 5, 0), None)
        self.assertIsNone(spaces.remove_space([spaces.Space()], 0, 0))
        self.assertEqual(spaces.step(0, 3, -1), 2)
        self.assertEqual(spaces.step(2, 3, 1), 0)

    def test_names_icons(self):
        self.assertEqual(spaces.clean_name("  a   b "), "a b")
        self.assertEqual(spaces.clean_name(""), "Home")
        self.assertEqual(spaces.clean_icon("", "work"), "W")
        self.assertEqual(spaces.clean_icon("", "!!"), "?")
        self.assertEqual(spaces.next_name([spaces.Space("Space 2")]), "Space 3")


if __name__ == "__main__":
    unittest.main()
