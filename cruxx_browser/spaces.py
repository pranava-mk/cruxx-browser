"""Spaces and split pairs. PURE logic.

This module does not import Gtk or WebKit.
A space is a set of tabs with its own pins, split pairs and active tab.
A split pair is two tabs that show side by side.
"""

DEFAULT_NAME = "Home"
MAX_SPACES = 9
NAME_MAX = 40
RATIO_MIN = 0.15
RATIO_MAX = 0.85
RATIO_DEFAULT = 0.5
SESSION_VERSION = 2


class Split:
    """A pair of tabs. A is the left pane. B is the right pane."""

    def __init__(self, a, b, ratio=RATIO_DEFAULT):
        self.a = a
        self.b = b
        self.ratio = clamp_ratio(ratio)
        # The window sets these when it builds the widgets.
        self.widget = None
        self.panes = None
        self.sized = False

    def other(self, tab):
        return self.b if tab is self.a else self.a

    def has(self, tab):
        return tab is self.a or tab is self.b


class Space:
    """The tabs of one space. TABS holds objects with "pinned" and "private"."""

    def __init__(self, name=DEFAULT_NAME, icon=""):
        self.name = clean_name(name)
        self.icon = clean_icon(icon, self.name)
        self.tabs = []
        self.active = None
        self.splits = []
        self.last_normal = 0


def clamp_ratio(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return RATIO_DEFAULT
    return min(RATIO_MAX, max(RATIO_MIN, float(value)))


def clean_name(text, fallback=DEFAULT_NAME):
    """Return TEXT with single spaces and a length limit. Use FALLBACK if empty."""
    text = " ".join(text.split())[:NAME_MAX] if isinstance(text, str) else ""
    return text or fallback


def first_glyph(text):
    """Return the first character of TEXT with its joiners (emoji sequences)."""
    out = ""
    join = False
    for ch in text:
        code = ord(ch)
        glue = (code in (0x200D, 0xFE0F, 0x20E3) or 0x1F3FB <= code <= 0x1F3FF)
        if not out or join or glue:
            out += ch
            join = code == 0x200D
        else:
            break
        if len(out) >= 12:
            break
    return out


def clean_icon(text, name=""):
    """Return one icon character. Default: first letter of NAME, upper case."""
    text = text.strip() if isinstance(text, str) else ""
    if text:
        return first_glyph(text)
    for ch in name or "":
        if ch.isalnum():
            return ch.upper()
    return "?"


def next_name(spaces):
    """Return a name for a new space that no other space uses."""
    used = {s.name for s in spaces}
    number = len(spaces) + 1
    while "Space %d" % number in used:
        number += 1
    return "Space %d" % number


def clean_splits(items, rows):
    """Keep the valid split dicts of ITEMS. ROWS are the tab dicts of the space.

    A pair needs two different rows in range. Pinned rows cannot pair.
    A tab is in one pair only.
    """
    out = []
    used = set()
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        a, b = item.get("a"), item.get("b")
        ok = all(isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(rows)
                 for i in (a, b))
        if not ok or a == b or a in used or b in used:
            continue
        if rows[a].get("pinned") or rows[b].get("pinned"):
            continue
        used.update((a, b))
        out.append({"a": a, "b": b, "ratio": clamp_ratio(item.get("ratio"))})
    return out


def _clean_space(raw, clean_tabs):
    rows = clean_tabs(raw.get("tabs"))
    active = raw.get("active")
    if not isinstance(active, int) or isinstance(active, bool) or not 0 <= active < len(rows):
        active = 0
    name = clean_name(raw.get("name"))
    return {"name": name, "icon": clean_icon(raw.get("icon"), name), "tabs": rows,
            "active": active, "splits": clean_splits(raw.get("splits"), rows)}


def migrate(raw, clean_tabs):
    """Return {"spaces": [...], "current": int} for a session dict RAW.

    CLEAN_TABS maps a list of raw tab rows to a list of valid tab rows.
    An old session has a flat "tabs" list. It becomes the space "Home".
    """
    if not isinstance(raw, dict):
        raw = {}
    spaces = []
    listed = raw.get("spaces")
    if isinstance(listed, list):
        spaces = [_clean_space(s, clean_tabs) for s in listed
                  if isinstance(s, dict)][:MAX_SPACES]
    if not spaces:
        spaces = [_clean_space({"name": DEFAULT_NAME, "tabs": raw.get("tabs"),
                                "active": raw.get("active")}, clean_tabs)]
    current = raw.get("current")
    if not isinstance(current, int) or isinstance(current, bool) \
            or not 0 <= current < len(spaces):
        current = 0
    return {"spaces": spaces, "current": current}


def split_rows(tabs, splits):
    """Return the split dicts to save. TABS are the saved (not private) tabs.

    A pair with a tab that is not in TABS is dropped (private tabs are not saved).
    """
    out = []
    for split in splits:
        if split.a in tabs and split.b in tabs:
            out.append({"a": tabs.index(split.a), "b": tabs.index(split.b),
                        "ratio": round(split.ratio, 4)})
    return out


def find_split(splits, tab):
    for split in splits:
        if split.has(tab):
            return split
    return None


def visible_tabs(space):
    """Return the tabs that show now in SPACE: the active pair, or the active tab."""
    if space.active is None:
        return []
    split = find_split(space.splits, space.active)
    return [split.a, split.b] if split else [space.active]


def regroup(tabs, splits):
    """Put the partner of each pair next to its first tab. Change TABS in place.

    Return True if the order changed.
    """
    before = list(tabs)
    for split in splits:
        if split.a in tabs and split.b in tabs:
            tabs.remove(split.b)
            tabs.insert(tabs.index(split.a) + 1, split.b)
    return before != tabs


def choose_partner(tabs, tab, splits):
    """Return the tab to pair with TAB: the next free tab, or None."""
    if tab not in tabs:
        return None
    start = tabs.index(tab)
    for offset in range(1, len(tabs)):
        other = tabs[(start + offset) % len(tabs)]
        if (not other.pinned and not getattr(other, "floating", False)
                and find_split(splits, other) is None):
            return other
    return None


def step(current, count, delta):
    """Return the space index DELTA steps from CURRENT, with wrap."""
    return (current + delta) % count if count else 0


def remove_space(spaces, index, current):
    """Remove spaces[INDEX]. Return the new current index, or None if refused.

    The last space cannot go.
    """
    if len(spaces) <= 1 or not 0 <= index < len(spaces):
        return None
    del spaces[index]
    if index < current:
        return current - 1
    return min(current, len(spaces) - 1)
