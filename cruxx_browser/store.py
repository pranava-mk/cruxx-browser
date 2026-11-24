"""Pure persistence logic: XDG paths, atomic JSON, history, bookmarks,
session, settings and hidden-element rules.

This module does not import Gtk or WebKit.
"""

import json
import logging
import os
import tempfile
import time
import urllib.parse

from . import security, sleep, spaces, wall

log = logging.getLogger(__name__)

APP_DIR = "cruxx-browser"
HISTORY_CAP = 20000
HIDDEN_CAP = 200
SELECTOR_MAX = 512
SELECTOR_BAD = set("{}<;@\\")
DEFAULT_SETTINGS = {
    "engine": "duckduckgo",
    "shield_enabled": True,
    "shield_paused_hosts": [],
    "permissions": {},
    "sleep_after_min": 30,
    "sleep_pinned": False,
    "keep_awake_enabled": False,
    "keep_awake_hosts": [],
    "split_enabled": False,
    "restore_session": True,
    "zoom_by_host": {},
    "wall": dict(wall.DEFAULT_WALL),
    "peek_modifier": "alt",
    "passwords_enabled": True,
    "password_never": [],
}
# Search engines that the omnibox knows. A test keeps this in step.
ENGINES = ("duckduckgo", "google", "brave", "startpage", "kagi")
SLEEP_CHOICES = (0, 15, 30, 60, 120)
PEEK_MODIFIERS = ("alt", "shift", "off")
BOOL_OPTIONS = ("shield_enabled", "restore_session", "sleep_pinned",
                "keep_awake_enabled", "split_enabled", "passwords_enabled")
NEVER_MAX = 500
ZOOM_MIN = 0.3
ZOOM_MAX = 5.0


def clean_zoom(value):
    """Return VALUE as a zoom level (rounded, in range), or None if not valid."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return round(min(ZOOM_MAX, max(ZOOM_MIN, float(value))), 2)


def clean_never(value):
    """Return the list of origins in VALUE that are valid. Drop the others."""
    out = []
    if isinstance(value, list):
        for item in value:
            if (isinstance(item, str) and len(item) <= 300
                    and security.permission_origin(item) == item and item not in out):
                out.append(item)
    return out[:NEVER_MAX]


def check_option(key, value):
    """Return the clean VALUE for the setting KEY. Raise ValueError if bad."""
    if key == "engine":
        if value in ENGINES:
            return value
    elif key == "peek_modifier":
        if value in PEEK_MODIFIERS:
            return value
    elif key == "wall":
        if isinstance(value, dict):
            return wall.clean_wall(value)
    elif key == "password_never":
        if isinstance(value, list):
            return clean_never(value)
    elif key in BOOL_OPTIONS:
        if isinstance(value, bool):
            return value
    elif key == "sleep_after_min":
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and value in SLEEP_CHOICES):
            return int(value)
    raise ValueError("bad value for setting %r" % (key,))


def data_matches(record, host):
    """Return True if the website data record name RECORD belongs to HOST.

    A record can be a cookie domain (".example.com") or a host name. It
    matches when it is HOST or a parent domain of HOST, or a sub domain of HOST.
    """
    record = (record or "").lower().strip(".")
    host = (host or "").lower().strip(".")
    if not record or not host:
        return False
    return (record == host or host.endswith("." + record)
            or record.endswith("." + host))


def _xdg(var, fallback):
    return os.environ.get(var) or os.path.expanduser(fallback)


def data_dir():
    return os.path.join(_xdg("XDG_DATA_HOME", "~/.local/share"), APP_DIR)


def cache_dir():
    return os.path.join(_xdg("XDG_CACHE_HOME", "~/.cache"), APP_DIR)


def config_dir():
    return os.path.join(_xdg("XDG_CONFIG_HOME", "~/.config"), APP_DIR)


def make_private_dir(path):
    """Create PATH and its parents. The leaf gets mode 0700."""
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def write_json_atomic(path, obj):
    """Write OBJ as JSON to PATH. Use a temp file and a rename."""
    directory = os.path.dirname(path)
    make_private_dir(directory)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(obj, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path, default):
    """Read JSON from PATH. Move a corrupt file aside. Return DEFAULT then."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except OSError as exc:
        # Read errors (permissions, I/O) say nothing about the content.
        # Keep the file where it is.
        log.warning("data file not readable: %s: %s", os.path.basename(path), exc)
        return default
    except (ValueError, UnicodeDecodeError, RecursionError, TypeError):
        try:
            os.replace(path, "%s.corrupt-%d" % (path, int(time.time())))
        except OSError:
            pass
        log.warning("corrupt data file moved aside: %s", os.path.basename(path))
        return default


def registrable_host(host):
    """Return the key for HOST: lower case, without a leading "www.".

    There is no public suffix list. Thus the key is the full host name and
    not the last two labels. A key does not cover a sibling host name.
    """
    host = (host or "").lower().strip(".")
    if host.startswith("www.") and len(host) > 4:
        host = host[4:]
    return host


def host_of(url):
    try:
        return urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return ""


def valid_selector(sel):
    """Return True if SEL is a safe CSS selector string."""
    return (isinstance(sel, str) and 0 < len(sel) <= SELECTOR_MAX
            and not any(ch in SELECTOR_BAD for ch in sel)
            and "/*" not in sel and "*/" not in sel
            and not any(ord(ch) < 32 for ch in sel))


def _clean_list(items, shape, allow_empty_url=False):
    """Keep the dicts in ITEMS that match SHAPE (key -> type tuple).

    Drop an entry when its "url" may not be loaded (see security.loadable).
    An empty URL is only kept when ALLOW_EMPTY_URL is true (blank tabs).
    """
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        ok = all(isinstance(item.get(k), t) and not isinstance(item.get(k), bool)
                 if t is not bool else isinstance(item.get(k), bool)
                 for k, t in shape.items())
        if ok and "url" in shape:
            url = item["url"]
            ok = (allow_empty_url and url == "") or security.loadable(url)
        if ok:
            out.append({k: item[k] for k in shape})
    return out


_HISTORY_SHAPE = {"url": str, "title": str, "visits": int, "last": (int, float)}
_BOOKMARK_SHAPE = {"url": str, "title": str}
_TAB_SHAPE = {"url": str, "title": str, "pinned": bool, "custom_title": str}


class Store:
    """All persistent data. Load once, flush when dirty."""

    def __init__(self):
        self.dir = data_dir()
        self.cfg = config_dir()
        make_private_dir(self.dir)
        make_private_dir(self.cfg)
        self.history = _clean_list(
            read_json(self._p("history.json"), []), _HISTORY_SHAPE)
        self.bookmarks = _clean_list(
            read_json(self._p("bookmarks.json"), []), _BOOKMARK_SHAPE)
        self.settings = self._load_settings()
        self.hidden = self._load_hidden()
        self.history_dirty = False

    def _p(self, name):
        return os.path.join(self.cfg if name == "settings.json" else self.dir, name)

    # settings
    def _load_settings(self):
        raw = read_json(self._p("settings.json"), {})
        out = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
               for k, v in DEFAULT_SETTINGS.items()}
        if not isinstance(raw, dict):
            return out
        if raw.get("engine") in ENGINES:
            out["engine"] = raw["engine"]
        if isinstance(raw.get("shield_enabled"), bool):
            out["shield_enabled"] = raw["shield_enabled"]
        hosts = raw.get("shield_paused_hosts")
        if isinstance(hosts, list):
            out["shield_paused_hosts"] = [h for h in hosts if isinstance(h, str)]
        out["password_never"] = clean_never(raw.get("password_never"))
        for key in ("sleep_pinned", "keep_awake_enabled", "split_enabled",
                    "restore_session", "passwords_enabled"):
            if isinstance(raw.get(key), bool):
                out[key] = raw[key]
        out["wall"] = wall.clean_wall(raw.get("wall"))
        if raw.get("peek_modifier") in PEEK_MODIFIERS:
            out["peek_modifier"] = raw["peek_modifier"]
        out["sleep_after_min"] = sleep.clean_minutes(raw.get("sleep_after_min", 30))
        awake = raw.get("keep_awake_hosts")
        if isinstance(awake, list):
            out["keep_awake_hosts"] = [h for h in awake if isinstance(h, str)]
        zooms = raw.get("zoom_by_host")
        if isinstance(zooms, dict):
            for host, level in zooms.items():
                level = clean_zoom(level)
                if isinstance(host, str) and level is not None and level != 1.0:
                    out["zoom_by_host"][host] = level
        perms = raw.get("permissions")
        if isinstance(perms, dict):
            for host, kinds in perms.items():
                if isinstance(host, str) and isinstance(kinds, dict):
                    out["permissions"][host] = {
                        k: v for k, v in kinds.items()
                        if isinstance(k, str) and isinstance(v, bool)}
        return out

    def save_settings(self):
        write_json_atomic(self._p("settings.json"), self.settings)

    def set_option(self, key, value):
        """Check and save one setting. Undo the change if the write fails."""
        value = check_option(key, value)
        before = self.settings[key]
        self.settings[key] = value
        try:
            self.save_settings()
        except OSError:
            self.settings[key] = before
            raise

    def add_password_never(self, origin):
        """Stop offers to save passwords for ORIGIN."""
        current = self.settings["password_never"]
        if origin not in current:
            self.set_option("password_never", current + [origin])

    def remove_password_never(self, origin):
        self.set_option("password_never",
                        [o for o in self.settings["password_never"] if o != origin])

    def zoom_for(self, host):
        return self.settings["zoom_by_host"].get(registrable_host(host), 1.0)

    def set_zoom(self, host, level):
        """Save the zoom LEVEL for HOST. A level of 1.0 removes the entry."""
        site = registrable_host(host)
        level = clean_zoom(level)
        if not site or level is None:
            return
        zooms = self.settings["zoom_by_host"]
        before = zooms.get(site)
        if level == 1.0:
            zooms.pop(site, None)
        else:
            zooms[site] = level
        try:
            self.save_settings()
        except OSError:
            if before is None:
                zooms.pop(site, None)
            else:
                zooms[site] = before
            raise

    def forget_permission(self, origin, kind=None):
        """Remove one saved answer, or all answers of ORIGIN if KIND is None."""
        perms = self.settings["permissions"]
        if origin not in perms:
            return
        before = dict(perms[origin])
        if kind is None:
            del perms[origin]
        else:
            perms[origin].pop(kind, None)
            if not perms[origin]:
                del perms[origin]
        try:
            self.save_settings()
        except OSError:
            perms[origin] = before
            raise

    def keep_awake(self, host):
        return registrable_host(host) in self.settings["keep_awake_hosts"]

    def set_keep_awake(self, host, on):
        site = registrable_host(host)
        hosts = self.settings["keep_awake_hosts"]
        if on and site and site not in hosts:
            hosts.append(site)
        elif not on and site in hosts:
            hosts.remove(site)
        else:
            return
        self.save_settings()

    def shield_paused(self, host):
        return registrable_host(host) in self.settings["shield_paused_hosts"]

    def set_shield_paused(self, host, paused):
        site = registrable_host(host)
        hosts = self.settings["shield_paused_hosts"]
        before = list(hosts)
        if paused and site not in hosts:
            hosts.append(site)
        elif not paused and site in hosts:
            hosts.remove(site)
        try:
            self.save_settings()
        except OSError:
            hosts[:] = before
            raise

    def permission(self, origin, kind):
        return self.settings["permissions"].get(origin, {}).get(kind)

    def remember_permission(self, origin, kind, allowed):
        kinds = self.settings["permissions"].setdefault(origin, {})
        before = kinds.get(kind)
        kinds[kind] = bool(allowed)
        try:
            self.save_settings()
        except OSError:
            if before is None:
                kinds.pop(kind, None)
            else:
                kinds[kind] = before
            raise

    # history
    def add_visit(self, url, title):
        if not url.startswith(("http://", "https://")):
            return
        now = time.time()
        for entry in self.history:
            if entry["url"] == url:
                entry["visits"] += 1
                entry["last"] = now
                if title:
                    entry["title"] = title
                break
        else:
            self.history.append(
                {"url": url, "title": title or "", "visits": 1, "last": now})
            if len(self.history) > HISTORY_CAP:
                self.history.sort(key=lambda e: e["last"])
                del self.history[:len(self.history) - HISTORY_CAP]
        self.history_dirty = True

    def remove_history(self, url):
        self.history = [e for e in self.history if e["url"] != url]
        self.history_dirty = True

    def clear_history(self):
        self.history = []
        self.history_dirty = True

    def flush(self):
        """Write history if it changed."""
        if self.history_dirty:
            write_json_atomic(self._p("history.json"), self.history)
            self.history_dirty = False

    # bookmarks
    def add_bookmark(self, url, title):
        if not url.startswith(("http://", "https://")):
            return False
        if any(b["url"] == url for b in self.bookmarks):
            return False
        self.bookmarks.append({"url": url, "title": title or ""})
        try:
            write_json_atomic(self._p("bookmarks.json"), self.bookmarks)
        except OSError:
            self.bookmarks.pop()
            raise
        return True

    def remove_bookmark(self, url):
        self.bookmarks = [b for b in self.bookmarks if b["url"] != url]
        write_json_atomic(self._p("bookmarks.json"), self.bookmarks)

    # session
    def load_session(self):
        """Return the session. Old flat files become the space "Home".

        The keys "tabs" and "active" are those of the current space.
        """
        raw = read_json(self._p("session.json"), {})
        if not isinstance(raw, dict):
            raw = {}

        def clean_tabs(rows):
            if isinstance(rows, list):
                # Older sessions have no custom title.
                rows = [dict(r, custom_title=r["custom_title"][:200]
                             if isinstance(r.get("custom_title"), str) else "")
                        for r in rows if isinstance(r, dict)]
            return _clean_list(rows, _TAB_SHAPE, allow_empty_url=True)

        found = spaces.migrate(raw, clean_tabs)
        side = raw.get("side") if raw.get("side") in ("left", "top") else "left"
        now = found["spaces"][found["current"]]
        return {"tabs": now["tabs"], "active": now["active"], "side": side,
                "spaces": found["spaces"], "current": found["current"]}

    def save_session(self, tabs, active, side, space_rows=None, current=0):
        """Write the session. SPACE_ROWS is a list of space dicts (name, icon,
        tabs, active, splits). Without it, TABS and ACTIVE make the space "Home".
        """
        if space_rows is None:
            space_rows = [{"name": spaces.DEFAULT_NAME, "icon": "H", "tabs": tabs,
                           "active": active, "splits": []}]
        write_json_atomic(self._p("session.json"),
                          {"version": spaces.SESSION_VERSION, "side": side,
                           "current": current, "spaces": space_rows})

    # hidden rules
    def _load_hidden(self):
        raw = read_json(self._p("hidden.json"), {})
        out = {}
        if isinstance(raw, dict):
            for host, sels in raw.items():
                if isinstance(host, str) and isinstance(sels, list):
                    good = [s for s in sels if valid_selector(s)][:HIDDEN_CAP]
                    if good:
                        out[host] = good
        return out

    def add_hidden(self, host, selector):
        """Save SELECTOR for HOST. Return True if it was stored."""
        site = registrable_host(host)
        if not site or not valid_selector(selector):
            return False
        sels = self.hidden.get(site, [])
        if selector in sels:
            return True
        if len(sels) >= HIDDEN_CAP:
            return False
        # Write a changed copy first. Change memory only if the write works.
        updated = dict(self.hidden)
        updated[site] = sels + [selector]
        write_json_atomic(self._p("hidden.json"), updated)
        self.hidden = updated
        return True

    def clear_hidden(self, host):
        site = registrable_host(host)
        if site in self.hidden:
            updated = {k: v for k, v in self.hidden.items() if k != site}
            write_json_atomic(self._p("hidden.json"), updated)
            self.hidden = updated

    def remove_hidden(self, host, selector):
        """Remove one saved SELECTOR of HOST."""
        site = registrable_host(host)
        sels = self.hidden.get(site, [])
        if selector not in sels:
            return
        updated = dict(self.hidden)
        rest = [s for s in sels if s != selector]
        if rest:
            updated[site] = rest
        else:
            del updated[site]
        write_json_atomic(self._p("hidden.json"), updated)
        self.hidden = updated

    def clear_all_hidden(self):
        write_json_atomic(self._p("hidden.json"), {})
        self.hidden = {}
