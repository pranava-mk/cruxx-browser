"""Ad and tracker blocker.

Domain and selector lists adapted from Search by Office Commun (MIT),
https://github.com/driceroland/Search

The rules use the Safari content-blocker format. WebKitGTK compiles them
with UserContentFilterStore. The compiled filter is cached on disk.
"""

import hashlib
import json
import logging
import os
import weakref

log = logging.getLogger(__name__)

UNWANTED = [
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "googletagservices.com", "google-analytics.com", "googletagmanager.com",
    "adservice.google.com", "amazon-adsystem.com", "adnxs.com", "adsrvr.org",
    "criteo.com", "criteo.net", "taboola.com", "outbrain.com",
    "rubiconproject.com", "pubmatic.com", "openx.net", "casalemedia.com",
    "smartadserver.com", "sharethrough.com", "indexww.com", "bidswitch.net",
    "33across.com", "teads.tv", "moatads.com", "adroll.com",
    "scorecardresearch.com", "quantserve.com", "chartbeat.com",
    "hotjar.com", "mouseflow.com", "fullstory.com", "clarity.ms",
    "mixpanel.com", "amplitude.com", "segment.com", "segment.io",
    "branch.io", "appsflyer.com", "adjust.com", "analytics.tiktok.com",
    "connect.facebook.net", "ads-twitter.com", "analytics.twitter.com",
    "intergient.com", "btloader.com", "ad-delivery.net", "mentorsticks.com",
    "dns-finder.com", "confiant-integrations.net", "cloudflareinsights.com",
]

SLOTS = [
    ".adsbygoogle", "ins.adsbygoogle", '[id^="google_ads_"]',
    '[id^="div-gpt-ad"]', '[id^="taboola-"]', "#taboola-below-article",
    'iframe[src*="doubleclick.net"]', 'iframe[src*="googlesyndication"]',
    'iframe[src*="amazon-adsystem"]',
    ".ad-slot", ".ad-slot-container", ".top-banner-ad-container",
    ".ad-leaderboard", ".ad-billboard", ".ad-giga", ".ad-mpu", ".ad-mrec",
    ".ad-unit", ".adunit", ".adslot", ".dfp-ad", ".gpt-ad", ".w_ad",
]

SLOTS_BY_SITE = [
    (["*as.com", "*elpais.com"], ".ad"),
    (["*theguardian.com"], ".top-fronts-banner-ad-container"),
    (["*independent.co.uk", "*the-independent.com"], "#billboard-wrapper"),
    (["*cnn.com"], ".ad-slot-header__wrapper"),
    (["*albumoftheyear.org"], ".headerAd, .homePageAdSquare"),
]

REDDIT_SITES = ["*reddit.com"]
REDDIT = [
    "shreddit-ad-post", "shreddit-comments-page-ad", "shreddit-sidebar-ad",
    "shreddit-dynamic-ad-link", "comment-tree-ad", ".promotedlink",
]


def network_filter(domain):
    """Return the url-filter regex for DOMAIN (same as upstream)."""
    escaped = domain.replace(".", "\\.")
    return "^https?://([^/]+\\.)?" + escaped + "[:/]"


def build_rules():
    """Return the list of content-blocker rules."""
    rules = [
        {"trigger": {"url-filter": network_filter(d), "load-type": ["third-party"]},
         "action": {"type": "block"}}
        for d in UNWANTED
    ]
    rules.append({"trigger": {"url-filter": ".*"},
                  "action": {"type": "css-display-none",
                             "selector": ", ".join(SLOTS)}})
    for sites, selector in SLOTS_BY_SITE:
        rules.append({"trigger": {"url-filter": ".*", "if-domain": sites},
                      "action": {"type": "css-display-none", "selector": selector}})
    rules.append({"trigger": {"url-filter": ".*", "if-domain": REDDIT_SITES},
                  "action": {"type": "css-display-none",
                             "selector": ", ".join(REDDIT)}})
    return rules


def rules_json(rules=None):
    """Return the rules as stable JSON text."""
    return json.dumps(build_rules() if rules is None else rules,
                      sort_keys=True, separators=(",", ":"))


def identifier(text):
    """Return the store identifier. It changes when the rules change."""
    return "cruxx-shield-" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class Shield:
    """Compile the filter once. Add it to or remove it from content managers."""

    READY_WAIT_MS = 1500

    def __init__(self, cache_dir):
        self._path = os.path.join(cache_dir, "filters")
        self.filter = None
        self.settled = False
        self._waiting = []
        # Applied state and wanted state, per content manager.
        self._state = weakref.WeakKeyDictionary()
        self._want = weakref.WeakKeyDictionary()

    def compile(self):
        """Load the cached filter, or compile it. Run once at start."""
        from gi.repository import GLib, WebKit2
        os.makedirs(self._path, mode=0o700, exist_ok=True)
        text = rules_json()
        ident = identifier(text)
        store = WebKit2.UserContentFilterStore.new(self._path)

        def saved(_store, result):
            try:
                self._ready(store.save_finish(result))
            except GLib.Error as exc:
                log.warning("shield compile failed: %s", exc.message)
                self._release()

        def loaded(_store, result):
            try:
                self._ready(store.load_finish(result))
            except GLib.Error:
                data = GLib.Bytes.new(text.encode("utf-8"))
                store.save(ident, data, None, saved)

        store.load(ident, None, loaded)
        GLib.timeout_add(self.READY_WAIT_MS, self._release)

    def _ready(self, flt):
        self.filter = flt
        # This can run after the READY_WAIT_MS timeout. Managers that asked
        # for the filter before it existed get it now.
        for manager, active in list(self._want.items()):
            self._apply(manager, active)
        self._release()

    def _release(self):
        self.settled = True
        waiting, self._waiting = self._waiting, []
        for callback in waiting:
            try:
                callback()
            except Exception:
                log.exception("shield ready callback failed")
        return False

    def when_ready(self, callback):
        """Call CALLBACK now, or when the filter is ready or has failed."""
        if self.settled:
            callback()
        else:
            self._waiting.append(callback)

    def set_active(self, manager, active):
        """Add or remove the filter on content manager MANAGER."""
        self._want[manager] = active
        self._apply(manager, active)

    def _apply(self, manager, active):
        if self.filter is None or self._state.get(manager, False) == active:
            return
        if active:
            manager.add_filter(self.filter)
        else:
            manager.remove_filter(self.filter)
        self._state[manager] = active
