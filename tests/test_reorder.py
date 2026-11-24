import unittest

from cruxx_browser.reorder import move_tab


class T:
    def __init__(self, name, pinned=False):
        self.name, self.pinned = name, pinned

    def __repr__(self):
        return self.name


def names(tabs):
    return [t.name for t in tabs]


class ReorderTest(unittest.TestCase):
    def setUp(self):
        self.p = T("p", True)
        self.a, self.b, self.c = T("a"), T("b"), T("c")
        self.tabs = [self.p, self.a, self.b, self.c]

    def test_before_and_after(self):
        move_tab(self.tabs, self.c, self.a)
        self.assertEqual(names(self.tabs), ["p", "c", "a", "b"])
        move_tab(self.tabs, self.c, self.b, after=True)
        self.assertEqual(names(self.tabs), ["p", "a", "b", "c"])

    def test_end(self):
        move_tab(self.tabs, self.a)
        self.assertEqual(names(self.tabs), ["p", "b", "c", "a"])

    def test_pin_by_drop(self):
        self.assertTrue(move_tab(self.tabs, self.c, None, pin=True))
        self.assertEqual(names(self.tabs), ["p", "c", "a", "b"])
        self.assertTrue(self.c.pinned)

    def test_pin_before_pinned(self):
        move_tab(self.tabs, self.b, self.p, pin=True)
        self.assertEqual(names(self.tabs), ["b", "p", "a", "c"])

    def test_unpin(self):
        move_tab(self.tabs, self.p, self.b, after=True, pin=False)
        self.assertEqual(names(self.tabs), ["a", "b", "p", "c"])
        self.assertFalse(self.p.pinned)

    def test_noop(self):
        self.assertFalse(move_tab(self.tabs, self.a, self.a))
        self.assertFalse(move_tab(self.tabs, self.a, self.b, after=False))


if __name__ == "__main__":
    unittest.main()
