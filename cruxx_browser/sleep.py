"""Tab sleep. PURE logic: choose which tabs to put to sleep.

This module does not import Gtk or WebKit.
A tab that is not selected for a set time loses its WebView. The tab row
stays. The next select makes a new WebView and loads the saved address.
"""

DEFAULT_AFTER_MIN = 30
CHECK_SECONDS = 60
MAX_AFTER_MIN = 7 * 24 * 60


def clean_minutes(value):
    """Return VALUE as a number of minutes, or the default if it is not valid."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_AFTER_MIN
    if value != value or value < 0:
        return DEFAULT_AFTER_MIN
    return min(value, MAX_AFTER_MIN)


def candidates(tabs_info, now, settings):
    """Return the ids of the tabs that must go to sleep now.

    TABS_INFO is a list of dicts with these keys: id, selected, last_active
    (seconds, same clock as NOW), has_view, playing, downloading, pinned,
    keep_awake. SETTINGS has sleep_after_min (0 = never) and sleep_pinned.
    """
    minutes = clean_minutes(settings.get("sleep_after_min", DEFAULT_AFTER_MIN))
    if minutes == 0:
        return []
    wait = minutes * 60
    allow_pinned = bool(settings.get("sleep_pinned", False))
    out = []
    for info in tabs_info:
        if info.get("selected") or not info.get("has_view"):
            continue
        if info.get("playing") or info.get("downloading") or info.get("keep_awake"):
            continue
        if info.get("pinned") and not allow_pinned:
            continue
        if now - info.get("last_active", now) >= wait:
            out.append(info["id"])
    return out
