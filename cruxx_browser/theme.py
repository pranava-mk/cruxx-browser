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


# The grey steps of the design. Each one is the text colour at a low alpha
# over the page colour. Light and dark themes use the same steps.
# See docs/design-notes.md for the upstream names.
INK_STEPS = {
    "muted_ink": 0.55,
    "faint_ink": 0.30,
    "hairline": 0.11,
    "wash": 0.075,
    "hover": 0.045,
    "tile": 0.04,
    "pin_live": 0.10,
}


def css(c):
    """Return GTK CSS for colour dict C. All values are validated."""
    values = dict(c)
    for name, alpha in INK_STEPS.items():
        values[name] = "alpha(%s, %s)" % (c["foreground"], alpha)
    # The column and the strip are a little off the page colour.
    values["frame"] = "mix(%s, %s, 0.04)" % (c["background"], c["foreground"])
    return _CSS.format(**values)


_CSS = """
window, .background {{ background-color: {background}; color: {foreground}; }}
entry {{ background-color: {lighter_background}; color: {light_foreground};
  border: 1px solid {hairline}; border-radius: 8px; padding: 4px 8px; box-shadow: none; }}
entry:focus {{ border-color: {accent}; }}
button {{ background-image: none; background-color: transparent;
  color: {foreground}; border: 1px solid transparent; border-radius: 8px;
  box-shadow: none; text-shadow: none; }}
button:hover {{ background-color: {hover}; }}
.cruxx-panel {{ background-color: {frame}; border-left: 1px solid {hairline}; }}
.cruxx-panel list, .cruxx-panel row {{ background-color: transparent; color: {foreground}; }}
.cruxx-panel row {{ border-radius: 9px; padding: 2px 4px; }}
.cruxx-panel row:hover {{ background-color: {hover}; }}
.cruxx-panel row:selected, .cruxx-panel row:selected label {{
  background-color: {wash}; color: {foreground}; }}
infobar, infobar box {{ background-color: {lighter_background}; color: {light_foreground}; }}
infobar button {{ padding: 2px 10px; border-color: {hairline}; }}
.private label {{ font-style: italic; color: {accent}; }}
.muted {{ color: {muted_ink}; }}
.error {{ color: {red}; }}
progressbar progress {{ background-color: {accent}; }}
popover, popover box {{ background-color: {background}; color: {foreground}; }}
menu, .menu {{ background-color: {background}; color: {foreground};
  border: 1px solid {hairline}; border-radius: 10px; padding: 4px; }}
menuitem {{ border-radius: 6px; padding: 5px 10px; }}
menuitem:hover {{ background-color: {wash}; }}

/* Column and strip */
.cruxx-sidebar, .cruxx-strip {{ background-color: {frame}; }}
.cruxx-divider {{ background-color: {hairline}; min-width: 1px; min-height: 1px; }}
.cruxx-row, .cruxx-pin, .cruxx-new, .cruxx-door {{
  border-radius: 9px; background-color: transparent; }}
.cruxx-row label, .cruxx-new label {{ font-size: 12.5px; color: {muted_ink}; }}
.cruxx-row.hover {{ background-color: {hover}; }}
.cruxx-row.hover label {{ color: alpha({foreground}, 0.7); }}
.cruxx-row.live {{ background-color: {wash}; }}
.cruxx-row.live label {{ color: {foreground}; }}
.cruxx-row.private label {{ font-style: italic; }}
.cruxx-pin {{ background-color: {tile}; color: {muted_ink}; }}
.cruxx-pin.hover {{ background-color: {hover}; color: alpha({foreground}, 0.7); }}
.cruxx-pin.live {{ background-color: {pin_live}; color: {foreground}; }}
.cruxx-new {{ color: {faint_ink}; }}
.cruxx-new label {{ color: {faint_ink}; }}
.cruxx-new.hover {{ background-color: {hover}; color: alpha({foreground}, 0.7); }}
.cruxx-new.hover label {{ color: alpha({foreground}, 0.7); }}
.cruxx-mark {{ color: {foreground}; }}
.cruxx-close {{ color: {muted_ink}; background-color: alpha({foreground}, 0.07); border-radius: 50%; }}
.cruxx-door {{ color: {muted_ink}; padding: 0; border: none; min-width: 26px;
  min-height: 26px; border-radius: 8px; }}
.cruxx-door:hover, .cruxx-door:checked {{ background-color: {hover}; color: alpha({foreground}, 0.7); }}
scrolledwindow.cruxx-scroll, scrolledwindow.cruxx-scroll viewport {{ background-color: transparent; }}
.cruxx-scroll undershoot, .cruxx-scroll overshoot {{ background: none; }}

/* Split panes, split rows and spaces */
.cruxx-pane {{ border: 2px solid transparent; border-radius: 4px; }}
.cruxx-pane.focus {{ border-color: {accent}; }}
paned.cruxx-split > separator {{ background-color: {hairline}; min-width: 5px; min-height: 5px; }}
.cruxx-row.paired {{ border-left: 3px solid {hairline}; border-radius: 3px 9px 9px 3px; }}
.cruxx-row.paired.live {{ border-left-color: {accent}; }}
.cruxx-dropzone {{ background-color: alpha({accent}, 0.10); border: 2px dashed {accent}; }}
.cruxx-space {{ border-radius: 50%; background-color: {tile}; color: {muted_ink};
  font-size: 10px; font-weight: 500; }}
.cruxx-space label {{ font-size: 10px; }}
.cruxx-space.hover {{ background-color: {hover}; color: alpha({foreground}, 0.7); }}
.cruxx-space.live {{ background-color: {pin_live}; color: {foreground}; }}

/* Floating things */
.cruxx-scrim {{ background-color: alpha({background}, 0.74); }}
.cruxx-card {{ background-color: {background}; border: 1px solid {hairline};
  border-radius: 14px; box-shadow: 0 8px 24px alpha(black, 0.10); }}
.cruxx-card.refused {{ border-color: alpha({red}, 0.35); }}
.cruxx-field {{ padding: 14px 22px; }}
.cruxx-hint {{ font-size: 15.5px; color: alpha({foreground}, 0.3); }}
.cruxx-list {{ padding: 6px; }}
.cruxx-card selection, .cruxx-find selection {{ background-color: {accent}; color: {background}; }}
.cruxx-card entry, .cruxx-field entry {{ background: none; border: none; box-shadow: none;
  padding: 0; min-height: 22px; font-size: 15.5px; color: {foreground}; caret-color: {foreground}; }}
.cruxx-field entry:focus {{ border: none; box-shadow: none; }}
.cruxx-offer {{ border-radius: 9px; background-color: transparent; }}
.cruxx-offer.hover {{ background-color: {hover}; }}
.cruxx-offer.picked {{ background-color: {wash}; }}
.cruxx-offer .cruxx-key {{ font-size: 13px; color: {foreground}; }}
.cruxx-offer .cruxx-sub {{ font-size: 12px; color: {muted_ink}; }}
.cruxx-offer .cruxx-sym {{ color: {muted_ink}; }}
.cruxx-note {{ font-size: 13px; color: {muted_ink}; }}
.cruxx-status {{ background-color: {background}; border: 1px solid {hairline};
  border-radius: 13px; padding: 0 11px; min-height: 24px; font-size: 12px;
  color: {foreground}; box-shadow: 0 3px 12px alpha(black, 0.10); }}
.cruxx-find {{ background-color: {background}; border: 1px solid {hairline};
  border-radius: 999px; padding: 8px 8px 8px 16px; box-shadow: 0 5px 18px alpha(black, 0.12); }}
.cruxx-find.missed {{ border-color: alpha({red}, 0.35); }}
.cruxx-find entry {{ background: none; border: none; box-shadow: none; padding: 0;
  min-height: 16px; font-size: 12.5px; color: {foreground}; caret-color: {foreground}; }}
.cruxx-find .cruxx-count {{ font-size: 10px; font-weight: 500; color: {muted_ink}; }}
.cruxx-find.missed .cruxx-count {{ color: {red}; }}
.cruxx-find button {{ padding: 0; min-width: 24px; min-height: 24px; border: none;
  border-radius: 12px; color: {muted_ink}; }}
.cruxx-settings {{ background-color: {background}; }}
.cruxx-nav {{ background-color: transparent; padding: 14px 8px; }}
.cruxx-nav row {{ border-radius: 9px; padding: 6px 12px; background-color: transparent;
  color: {muted_ink}; }}
.cruxx-nav row:hover {{ background-color: {hover}; }}
.cruxx-nav row:selected {{ background-color: {wash}; }}
.cruxx-nav row:selected label {{ color: {foreground}; }}
.cruxx-section-title {{ font-size: 20px; font-weight: 600; color: {foreground}; }}
.cruxx-subtitle {{ font-size: 13px; font-weight: 600; color: {foreground};
  margin-top: 14px; }}
.cruxx-key {{ font-size: 12px; color: {foreground}; }}
.cruxx-formrow {{ padding: 9px 0; }}
.cruxx-action {{ padding: 3px 12px; background-color: {tile}; color: {foreground};
  border-radius: 8px; min-height: 22px; }}
.cruxx-action:hover {{ background-color: {hover}; }}
.cruxx-action:disabled {{ color: {faint_ink}; }}
.cruxx-pop {{ background-color: {background}; border: 1px solid {hairline};
  border-radius: 12px; }}
.cruxx-pop .cruxx-subtitle {{ margin-top: 0; }}
switch {{ background-color: {wash}; border: 1px solid {hairline}; color: {foreground}; }}
switch:checked {{ background-color: {accent}; }}
switch slider {{ background-color: {foreground}; border: none; }}
"""


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
