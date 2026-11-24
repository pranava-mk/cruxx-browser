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


def address_url(text):
    """Return the URL for TEXT if TEXT is an address. Else return None."""
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
    return None


def classify(text, engine=DEFAULT_ENGINE):
    """Return a URL for typed TEXT. Return None for empty input."""
    if text is None or not text.strip():
        return None
    return address_url(text) or search_url(text.strip(), engine)


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


ENGINE_NAMES = {
    "duckduckgo": "DuckDuckGo",
    "google": "Google",
    "brave": "Brave Search",
    "startpage": "Startpage",
    "kagi": "Kagi",
}


def engine_label(engine):
    """Return the display name of ENGINE."""
    return ENGINE_NAMES.get(engine, ENGINE_NAMES[DEFAULT_ENGINE])


def editable(url):
    """Return URL as the address field shows it for editing.

    Remove the scheme only if the field would add the same scheme again.
    Remove a lone trailing "/" in the same way.
    """
    if not url:
        return ""
    low = url.lower()
    for scheme in ("https://", "http://"):
        if low.startswith(scheme):
            short = url[len(scheme):]
            candidates = [short]
            if short.endswith("/") and short.count("/") == 1:
                candidates.insert(0, short[:-1])
            for candidate in candidates:
                back = address_url(candidate)
                if back is not None and back.lower().rstrip("/") == low.rstrip("/"):
                    return candidate
            return url
    return url


def suggestions(text, history, bookmarks, engine=DEFAULT_ENGINE, limit=8):
    """Return the suggestion rows for typed TEXT.

    A row is a dict with kind, url, title and label. Kinds: "search",
    "go", "history", "bookmark". The first row is what Enter does for
    the typed text. The other rows come from local data only.
    """
    text = (text or "").strip()
    if not text:
        return []
    target = address_url(text)
    if target is None:
        first = {"kind": "search", "url": search_url(text, engine), "title": "",
                 "label": "Search %s for \u201c%s\u201d" % (engine_label(engine), text)}
    else:
        first = {"kind": "go", "url": target, "title": "", "label": text}
    rows = [first]
    marked = {b["url"] for b in bookmarks}
    titles = {}
    entries = []
    for entry in history:
        titles[entry["url"]] = entry.get("title", "")
        entries.append(entry)
    for mark in bookmarks:
        if mark["url"] not in titles:
            titles[mark["url"]] = mark.get("title", "")
            entries.append({"url": mark["url"], "title": mark.get("title", ""),
                            "visits": 0, "last": 0})
    for url in rank(entries, text, limit):
        if url == first["url"]:
            continue
        rows.append({"kind": "bookmark" if url in marked else "history", "url": url,
                     "title": titles.get(url, ""),
                     "label": _host_of(url) + urllib.parse.urlsplit(url).path.rstrip("/")})
    return rows[:limit]


# Fuzzy match, ported from the idea of the upstream Fuzzy.swift.

def _is_word_char(ch):
    return ch.isalnum()


def _word_starts(text):
    """Return the words of TEXT with their start positions."""
    words = []
    start = None
    for index, ch in enumerate(text + " "):
        if _is_word_char(ch):
            if start is None:
                start = index
        elif start is not None:
            words.append((start, text[start:index]))
            start = None
    return words


def _distance(a, b):
    """Return the edit distance of A and B. A swap of two letters costs 1."""
    rows = [list(range(len(b) + 1))]
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            best = min(rows[i - 1][j] + 1, row[j - 1] + 1,
                       rows[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                best = min(best, rows[i - 2][j - 2] + 1)
            row[j] = best
        rows.append(row)
    return rows[-1][-1]


def _nearly(word, text_words):
    """Return True if WORD is a typo of the start of a word in TEXT_WORDS.

    Allow 1 typo in words of 4 to 7 letters and 2 in longer words. Allow none
    in shorter words. Require the first letter, or a swap with the second.
    """
    allowed = 0 if len(word) < 4 else 1 if len(word) < 8 else 2
    if not allowed:
        return False
    for _pos, other in text_words:
        if len(other) < max(2, len(word) - allowed):
            continue
        if not (other[0] == word[0] or other[:2] == word[1::-1]):
            continue
        for size in range(max(1, len(word) - allowed), len(word) + allowed + 1):
            if size <= len(other) and _distance(word, other[:size]) <= allowed:
                return True
    return False


def _abbreviates(typed, word):
    """Return True if TYPED is the first letter and later letters of WORD."""
    if not typed or not word or word[0] != typed[0]:
        return False
    rest = typed[1:]
    for ch in word[1:]:
        if rest and ch == rest[0]:
            rest = rest[1:]
    return not rest


def fuzzy_score(needle, text):
    """Score NEEDLE against TEXT. Return None if it does not match.

    Every word of NEEDLE must match. Per word: 3 if it starts a word of TEXT,
    2 if it is inside TEXT, 1 for an abbreviation or one forgiven typo.
    The result is the sum. A larger score is a better match.
    """
    words = needle.lower().split()
    if not words:
        return 0
    low = text.lower()
    text_words = _word_starts(low)
    total = 0
    for word in words:
        if any(other.startswith(word) for _pos, other in text_words):
            total += 3
        elif word in low:
            total += 2
        elif (any(_abbreviates(word, other) for _pos, other in text_words)
              and len(word) >= 3) or _nearly(word, text_words):
            total += 1
        else:
            return None
    return total


def switch_rank(needle, tabs):
    """Rank TABS (pairs of title and URL) for NEEDLE. Return their indexes.

    A title match counts double. Equal scores keep the tab order. An empty
    NEEDLE returns every index in the tab order.
    """
    if not needle.strip():
        return list(range(len(tabs)))
    scored = []
    for index, (title, url) in enumerate(tabs):
        by_title = fuzzy_score(needle, title)
        by_url = fuzzy_score(needle, url)
        if by_title is None and by_url is None:
            continue
        best = max(2 * by_title if by_title is not None else -1,
                   by_url if by_url is not None else -1)
        scored.append((-best, index))
    scored.sort()
    return [index for _score, index in scored]
