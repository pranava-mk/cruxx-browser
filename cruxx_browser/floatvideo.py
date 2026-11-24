"""Video float helpers. PURE logic: this module does not import Gtk.

The window moves a WebView into a small window. On Hyprland, the window
then floats, resizes, moves to a corner and stays on top. These functions
build the names and the hyprctl argument lists. No shell is ever used.
"""

import json
import re
import secrets

FLOAT_W = 480
FLOAT_H = 270
MARGIN = 24
PREFIX = "cruxx float "
_TOKEN = re.compile(r"[a-z0-9]{8,64}")


def new_token():
    """Return a random token. It has only the characters a-z and 0-9."""
    return secrets.token_hex(6)


def valid_token(token):
    return isinstance(token, str) and bool(_TOKEN.fullmatch(token))


def title_for(token):
    if not valid_token(token):
        raise ValueError("bad token")
    return PREFIX + token


def selector(token):
    """Return the Hyprland window selector for the float window of TOKEN."""
    return "title:^%s$" % title_for(token)


def steps(token, x=None, y=None, width=FLOAT_W, height=FLOAT_H):
    """Return the dispatch steps as a list of (lua_text, legacy_args).

    Each step has a Lua call and the older dispatcher name as a fallback.
    The move step is left out if X or Y is None.
    """
    for number in (width, height) + tuple(v for v in (x, y) if v is not None):
        if isinstance(number, bool) or not isinstance(number, int):
            raise ValueError("bad number")
    win = selector(token)
    out = [
        ('hl.dsp.window.float({ window = "%s", action = "on" })' % win,
         ["setfloating", win]),
        ('hl.dsp.window.resize({ window = "%s", x = %d, y = %d })' % (win, width, height),
         ["resizewindowpixel", "exact %d %d,%s" % (width, height, win)]),
    ]
    if x is not None and y is not None:
        out.append(('hl.dsp.window.move({ window = "%s", x = %d, y = %d })' % (win, x, y),
                    ["movewindowpixel", "exact %d %d,%s" % (x, y, win)]))
    out.append(('hl.dsp.window.pin({ window = "%s" })' % win, ["pin", win]))
    return out


def argv(*parts):
    """Return the hyprctl argument list for a dispatch. Never a shell text."""
    return ["hyprctl", "dispatch"] + list(parts)


def corner_position(monitors_json, width=FLOAT_W, height=FLOAT_H, margin=MARGIN):
    """Return (x, y) for the bottom right of the focused monitor, or None.

    MONITORS_JSON is the text of `hyprctl monitors -j`.
    """
    try:
        monitors = json.loads(monitors_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(monitors, list):
        return None
    good = [m for m in monitors if isinstance(m, dict)]
    pick = next((m for m in good if m.get("focused") is True), good[0] if good else None)
    if pick is None:
        return None
    try:
        scale = float(pick.get("scale", 1)) or 1.0
        mx, my = int(pick["x"]), int(pick["y"])
        mw, mh = int(pick["width"] / scale), int(pick["height"] / scale)
        reserved = pick.get("reserved") or [0, 0, 0, 0]
        right, bottom = int(reserved[2]), int(reserved[3])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    return (max(mx, mx + mw - right - width - margin),
            max(my, my + mh - bottom - height - margin))
