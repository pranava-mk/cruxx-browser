"""Wall behind the blank tab. PURE logic: this module does not import Gtk.

The user chooses what shows behind an empty tab: nothing, the Omarchy
wallpaper, a colour, a gradient or a picture. This module checks the choice
and does the geometry. The window code in wallview.py draws it.
"""

import math
import os
import re

KINDS = ("off", "omarchy", "color", "gradient", "picture")
PICTURE_MAX_BYTES = 50 * 1024 * 1024
PATH_MAX = 4096
ANGLE_STEP = 15
DEFAULT_WALL = {
    "kind": "off", "color": "#1a1b26", "from": "#1a1b26", "to": "#7aa2f7",
    "angle": 135, "picture": "",
}
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")


def clean_color(value, default):
    """Return VALUE as a lower-case #rrggbb text, or DEFAULT if it is not valid."""
    if isinstance(value, str) and _HEX.fullmatch(value):
        return value.lower()
    return default


def clean_angle(value, default):
    """Return VALUE as a whole angle from 0 to 359, or DEFAULT."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if value != value or value in (float("inf"), float("-inf")):
        return default
    return int(round(value)) % 360


def clean_path(value):
    """Return VALUE if it is a usable absolute path text, else an empty text."""
    if (isinstance(value, str) and 0 < len(value) <= PATH_MAX and "\0" not in value
            and os.path.isabs(value)):
        return value
    return ""


def clean_wall(raw):
    """Return a complete, valid wall dict. Anything not valid becomes the default."""
    out = dict(DEFAULT_WALL)
    if not isinstance(raw, dict):
        return out
    if raw.get("kind") in KINDS:
        out["kind"] = raw["kind"]
    for key in ("color", "from", "to"):
        out[key] = clean_color(raw.get(key), DEFAULT_WALL[key])
    out["angle"] = clean_angle(raw.get("angle"), DEFAULT_WALL["angle"])
    out["picture"] = clean_path(raw.get("picture"))
    return out


def check_picture(path):
    """Return the real path of PATH if it is a regular file of allowed size.

    Return None otherwise. A symlink is followed (the Omarchy wallpaper is one).
    """
    if not clean_path(path):
        return None
    try:
        real = os.path.realpath(path)
        info = os.stat(real)
    except OSError:
        return None
    import stat
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > PICTURE_MAX_BYTES:
        return None
    return real


def gradient_points(width, height, angle):
    """Return (x0, y0, x1, y1) for a gradient that follows a CSS angle.

    Angle 0 goes to the top, 90 to the right, 180 to the bottom.
    """
    rad = math.radians(angle)
    dx, dy = math.sin(rad), -math.cos(rad)
    half = (abs(width * dx) + abs(height * dy)) / 2
    cx, cy = width / 2, height / 2
    return (cx - dx * half, cy - dy * half, cx + dx * half, cy + dy * half)


def cover_geometry(src_w, src_h, width, height):
    """Return (scaled_w, scaled_h, crop_x, crop_y) to cover WIDTH x HEIGHT.

    The picture keeps its shape. The crop is centred. Sizes are whole pixels
    and never smaller than the target.
    """
    if min(src_w, src_h, width, height) <= 0:
        return (max(width, 1), max(height, 1), 0, 0)
    scale = max(width / src_w, height / src_h)
    sw = max(width, int(math.ceil(src_w * scale)))
    sh = max(height, int(math.ceil(src_h * scale)))
    return (sw, sh, (sw - width) // 2, (sh - height) // 2)
