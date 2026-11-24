"""Omarchy theme: parse colors.toml, build GTK CSS, watch for changes."""

import logging
import os
import re
import tomllib

log = logging.getLogger(__name__)

COLOR_KEYS = (
    "accent", "selection", "muted", "background", "dark_background",
    "lighter_background", "foreground", "light_foreground", "red",
)
FALLBACK = {
    "mode": "dark",
    "accent": "#7aa2f7",
    "selection": "#33467c",
    "muted": "#565f89",
    "background": "#1a1b26",
    "dark_background": "#16161e",
    "lighter_background": "#292e42",
    "foreground": "#c0caf5",
    "light_foreground": "#d5d6db",
    "red": "#f7768e",
}
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "omarchy", "current")


def colors_path():
    return os.path.join(state_dir(), "theme", "colors.toml")


def parse(text):
    """Parse TOML TEXT. Return a colour dict. Return FALLBACK if bad."""
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, TypeError):
        return dict(FALLBACK)
    result = dict(FALLBACK)
    for key in COLOR_KEYS:
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, str) or not _HEX.fullmatch(value):
            return dict(FALLBACK)
        result[key] = value
    mode = data.get("mode")
    result["mode"] = "light" if mode == "light" else "dark"
    return result


def load(path=None):
    """Read the theme file. Return FALLBACK if it is missing or bad."""
    try:
        with open(path or colors_path(), "r", encoding="utf-8") as handle:
            return parse(handle.read())
    except (OSError, UnicodeDecodeError):
        return dict(FALLBACK)


def css(c):
    """Return GTK CSS for colour dict C. All values are validated."""
    return """
window, .background {{ background-color: {background}; color: {foreground}; }}
entry {{ background-color: {lighter_background}; color: {light_foreground};
  border: 1px solid {muted}; border-radius: 6px; padding: 4px 8px; box-shadow: none; }}
entry:focus {{ border-color: {accent}; }}
list, row, .cruxx-strip {{ background-color: {dark_background}; color: {foreground}; }}
row:hover {{ background-color: {lighter_background}; }}
row:selected, row:selected label {{ background-color: {selection}; color: {light_foreground}; }}
button {{ background-image: none; background-color: {lighter_background};
  color: {foreground}; border: 1px solid {muted}; box-shadow: none; }}
button:hover {{ border-color: {accent}; }}
button.active-tab {{ background-color: {selection}; }}
.cruxx-panel {{ background-color: {dark_background}; border-left: 1px solid {muted}; }}
infobar, infobar box {{ background-color: {lighter_background}; color: {light_foreground}; }}
infobar button {{ padding: 2px 10px; }}
.private label {{ font-style: italic; color: {accent}; }}
.muted {{ color: {muted}; }}
.error {{ color: {red}; }}
progressbar progress {{ background-color: {accent}; }}
popover, popover box {{ background-color: {dark_background}; color: {foreground}; }}
""".format(**c)


class Watcher:
    """Watch the Omarchy theme files. Call CALLBACK after a 300 ms pause."""

    def __init__(self, callback):
        from gi.repository import Gio
        self._callback = callback
        self._source = 0
        self._monitors = []
        base = state_dir()
        # The "theme" entry is a symlink that Omarchy replaces.
        # A watch on its parent directory sees the replacement.
        targets = ((os.path.join(base, "theme.name"), False), (base, True))
        for path, is_dir in targets:
            gfile = Gio.File.new_for_path(path)
            try:
                monitor = (gfile.monitor_directory if is_dir else gfile.monitor_file)(
                    Gio.FileMonitorFlags.NONE, None)
            except Exception as exc:  # GLib.Error when path is missing
                log.debug("theme watch failed: %s", exc)
                continue
            monitor.connect("changed", self._changed)
            self._monitors.append(monitor)

    def _changed(self, *_args):
        from gi.repository import GLib
        if self._source:
            GLib.source_remove(self._source)
        self._source = GLib.timeout_add(300, self._fire)

    def _fire(self):
        self._source = 0
        self._callback()
        return False
