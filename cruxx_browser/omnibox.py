"""Pure logic for the omnibox.

This module turns typed text into a URL. It also ranks history entries for
completion. It does not import Gtk or WebKit.
"""

import re
import urllib.parse

ENGINES = {
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "google": "https://www.google.com/search?q={q}",
    "brave": "https://search.brave.com/search?q={q}",
    "startpage": "https://www.startpage.com/do/search?q={q}",
    "kagi": "https://kagi.com/search?q={q}",
}
DEFAULT_ENGINE = "duckduckgo"

_SCHEME = re.compile(r"^https?://\S+$", re.IGNORECASE)
_LOCALHOST = re.compile(r"^localhost(:\d{1,5})?([/?#]\S*)?$", re.IGNORECASE)
_IPV4 = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(:\d{1,5})?([/?#]\S*)?$")
_IPV6 = re.compile(r"^\[[0-9A-Fa-f:.]+\](:\d{1,5})?([/?#]\S*)?$")
_HOST = re.compile(
    r"^(?:[\w-]+\.)+[^\W\d_]{2,}(?::\d{1,5})?(?:[/?#]\S*)?$"
)


def search_url(text, engine=DEFAULT_ENGINE):
    """Return the search URL for TEXT."""
    template = ENGINES.get(engine, ENGINES[DEFAULT_ENGINE])
    return template.replace("{q}", urllib.parse.quote_plus(text))


def classify(text, engine=DEFAULT_ENGINE):
    """Return a URL for typed TEXT. Return None for empty input."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    if _SCHEME.match(text):
        return text
    if text.lower() == "about:blank":
        return "about:blank"
    if _LOCALHOST.match(text) or _IPV6.match(text):
        return "http://" + text
    match = _IPV4.match(text)
    if match and all(int(part) <= 255 for part in match.groups()[:4]):
        return "http://" + text
    if _HOST.match(text):
        return "https://" + text
    return search_url(text, engine)


def _host_of(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def rank(entries, text, limit=8):
    """Rank history ENTRIES for TEXT.

    Order: host prefix match, then visit count, then recency.
    An entry is a dict with url, title, visits and last.
    """
    needle = text.strip().lower()
    if not needle:
        return []
    if "://" in needle:
        needle = needle.split("://", 1)[1]
    if needle.startswith("www."):
        needle = needle[4:]
    scored = []
    for entry in entries:
        url = entry["url"]
        host = _host_of(url).lower()
        if host.startswith(needle):
            tier = 0
        elif needle in url.lower() or needle in entry.get("title", "").lower():
            tier = 1
        else:
            continue
        scored.append((tier, -entry.get("visits", 0), -entry.get("last", 0), url))
    scored.sort()
    return [item[3] for item in scored[:limit]]
