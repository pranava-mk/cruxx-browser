import unittest

from cruxx_browser.cleanlink import clean_link


class CleanLinkTest(unittest.TestCase):
    def test_removes_tracking(self):
        self.assertEqual(
            clean_link("https://a.com/p?x=1&utm_source=n&fbclid=z&y=2#frag"),
            "https://a.com/p?x=1&y=2#frag")

    def test_all_removed(self):
        self.assertEqual(clean_link("https://a.com/?gclid=1&ref_src=tw"), "https://a.com/")

    def test_no_change_is_same(self):
        url = "https://a.com/?q=a%20b&z=1"
        self.assertEqual(clean_link(url), url)

    def test_signature_untouched(self):
        url = "https://s3.example.com/f?X-Amz-Signature=abc&utm_source=x"
        self.assertEqual(clean_link(url), url)

    def test_si_only_on_share_sites(self):
        self.assertEqual(clean_link("https://youtu.be/abc?si=1&t=5"), "https://youtu.be/abc?t=5")
        self.assertEqual(clean_link("https://a.com/?si=1"), "https://a.com/?si=1")

    def test_other_schemes_and_junk(self):
        for url in ("javascript:alert(1)", "file:///a?utm_x=1", "", "http://[bad"):
            self.assertEqual(clean_link(url), url)

    def test_case_and_order(self):
        self.assertEqual(clean_link("http://a.com/?B=2&UTM_Medium=x&a=1"), "http://a.com/?B=2&a=1")


if __name__ == "__main__":
    unittest.main()
