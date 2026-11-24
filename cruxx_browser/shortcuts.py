"""Keyboard shortcut tables. PURE: this module does not import Gtk.

The window reads PLAIN and SHIFT to find the action for a Ctrl key.
The settings window shows rows(). Thus the list can not drift from the code.
"""

# Ctrl + key. The value is the name of a Window method.
PLAIN = {
    "t": "open_tab", "w": "_close_active", "l": "focus_omnibox", "k": "open_switcher",
    "r": "_reload", "f": "open_find", "d": "duplicate", "b": "_toggle_bookmarks",
    "y": "_toggle_history", "s": "toggle_strip", "bracketleft": "_back",
    "bracketright": "_forward", "i": "open_site_card", "comma": "open_settings",
}
# Ctrl + Shift + key.
SHIFT = {
    "t": "reopen_closed", "s": "toggle_side", "d": "toggle_pin", "c": "copy_url",
    "v": "paste_and_go", "b": "bookmark", "j": "_toggle_downloads",
    "n": "_open_private", "h": "start_hide", "u": "open_hidden_list",
    "r": "toggle_reader", "p": "toggle_float",
}
# Keys that the window handles with its own rules (not in the two tables).
SPECIAL = (
    ("Ctrl+Alt+R", "Reload from the origin"),
    ("Ctrl+Alt+N", "Split the current page"),
    ("Ctrl+Alt+Left, Ctrl+Alt+Right", "Move focus to the left or right pane"),
    ("Ctrl+Alt+Page Up, Ctrl+Alt+Page Down", "Previous, next space"),
    ("Alt+1 to Alt+9", "Go to space 1 to 9"),
    ("Alt+Left, Alt+Right", "Back, forward"),
    ("Ctrl+Tab, Ctrl+Shift+Tab", "Next, previous tab"),
    ("Ctrl+Shift+], Ctrl+Shift+[", "Next, previous tab"),
    ("Ctrl+1 to Ctrl+8", "Go to tab 1 to 8"),
    ("Ctrl+9", "Go to last tab"),
    ("Ctrl+plus, Ctrl+minus, Ctrl+0", "Zoom in, zoom out, reset zoom"),
    ("F5", "Reload"),
    ("F11", "Fullscreen"),
    ("Alt+click on a link", "Peek: show the link in a card (see Tabs in Settings)"),
    ("Esc", "Close peek card, address field, switcher, panel, find bar, or picker"),
)
LABELS = {
    "open_tab": "New tab", "_close_active": "Close tab",
    "focus_omnibox": "Show the address field", "open_switcher": "Tab switcher",
    "_reload": "Reload", "open_find": "Find in page", "duplicate": "Duplicate tab",
    "_toggle_bookmarks": "Bookmarks panel", "_toggle_history": "History panel",
    "toggle_strip": "Hide or show tab strip", "_back": "Back", "_forward": "Forward",
    "open_site_card": "Site card", "open_settings": "Settings",
    "reopen_closed": "Reopen closed tab", "toggle_side": "Move tab strip left or top",
    "toggle_pin": "Pin or unpin tab", "copy_url": "Copy URL",
    "paste_and_go": "Paste and go", "bookmark": "Bookmark page",
    "_toggle_downloads": "Downloads panel", "_open_private": "Private tab",
    "start_hide": "Hide element", "open_hidden_list": "Hidden elements on this site",
    "toggle_reader": "Reading mode", "toggle_float": "Float the video of this page",
}
KEY_NAMES = {"bracketleft": "[", "bracketright": "]", "comma": ","}


def key_label(prefix, key):
    return prefix + KEY_NAMES.get(key, key.upper() if len(key) == 1 else key)


def rows():
    """Return a list of (keys, action) text pairs for all shortcuts."""
    out = []
    for prefix, table in (("Ctrl+", PLAIN), ("Ctrl+Shift+", SHIFT)):
        for key, action in table.items():
            out.append((key_label(prefix, key), LABELS[action]))
    out.extend(SPECIAL)
    return out
