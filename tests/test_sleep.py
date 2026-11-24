import unittest

from cruxx_browser import sleep


def info(i, **kw):
    base = {"id": i, "selected": False, "last_active": 0, "has_view": True,
            "playing": False, "downloading": False, "pinned": False,
            "keep_awake": False}
    base.update(kw)
    return base


class SleepTest(unittest.TestCase):
    S = {"sleep_after_min": 30, "sleep_pinned": False}

    def test_old_tab_sleeps(self):
        self.assertEqual(sleep.candidates([info(1)], 1800, self.S), [1])

    def test_recent_tab_stays(self):
        self.assertEqual(sleep.candidates([info(1)], 1799, self.S), [])

    def test_never(self):
        self.assertEqual(sleep.candidates([info(1)], 10 ** 9, {"sleep_after_min": 0}), [])

    def test_exclusions(self):
        tabs = [info(1, selected=True), info(2, playing=True), info(3, downloading=True),
                info(4, pinned=True), info(5, keep_awake=True), info(6, has_view=False),
                info(7)]
        self.assertEqual(sleep.candidates(tabs, 99999, self.S), [7])

    def test_pinned_allowed(self):
        s = dict(self.S, sleep_pinned=True)
        self.assertEqual(sleep.candidates([info(1, pinned=True)], 99999, s), [1])

    def test_bad_setting_uses_default(self):
        self.assertEqual(sleep.clean_minutes("x"), 30)
        self.assertEqual(sleep.clean_minutes(True), 30)
        self.assertEqual(sleep.clean_minutes(-1), 30)
        self.assertEqual(sleep.clean_minutes(0.5), 0.5)


if __name__ == "__main__":
    unittest.main()
