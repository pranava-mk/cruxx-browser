"""Password storage and the pure rules for passwords.

The secrets live in the system keyring (libsecret). This module never writes
a secret to a file. It never logs a user name, a password, or a full URL.

A Backend has five calls. Each call takes a callback. The callback runs on the
main loop. A failed call gives None (or False) to the callback.
"""

import json
import logging
import urllib.parse

from . import security, store

log = logging.getLogger(__name__)

SCHEMA_NAME = "dev.cruxx.Browser.Password"
USERNAME_MAX = 512
PASSWORD_MAX = 4096
MESSAGE_MAX = 20000
PENDING_SECONDS = 60
CLIPBOARD_CLEAR_SECONDS = 45
REVEAL_SECONDS = 10
OFF_NOTICE = "Passwords are off: the system keyring is not available."


# pure rules
def vault_origin(uri):
    """Return the origin of URI if passwords may use it, or "".

    The origin comes from Python, from the address of the top-level page.
    Allow https. Allow http only for the local machine.
    """
    origin = security.permission_origin(uri)
    if origin and security.remember_allowed(origin):
        return origin
    return ""


def origin_host(origin):
    """Return the host name of ORIGIN for display."""
    try:
        return urllib.parse.urlsplit(origin).hostname or ""
    except ValueError:
        return ""


def same_site(origin_a, origin_b):
    """Return True if two origins are on one site.

    The hosts must be equal (without "www."), or one host must be a
    sub domain of the other. There is no public suffix list.
    """
    host_a = store.registrable_host(origin_host(origin_a))
    host_b = store.registrable_host(origin_host(origin_b))
    if not host_a or not host_b:
        return False
    return (host_a == host_b or host_a.endswith("." + host_b)
            or host_b.endswith("." + host_a))


def _clean_text(value, low, high):
    if not isinstance(value, str) or "\x00" in value:
        return None
    if not low <= len(value) <= high:
        return None
    return value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or abs(value) > 1e6:
        return None
    return float(value)


def parse_message(raw):
    """Return a checked message dict from the JSON text RAW, or None.

    Page script sends the text. Nothing in it is trusted.
    Kinds: submit (username, password), focus (rect), hide.
    """
    if not isinstance(raw, str) or len(raw) > MESSAGE_MAX:
        return None
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    return check_message(body)


def check_message(body):
    if not isinstance(body, dict):
        return None
    kind = body.get("kind")
    if kind == "submit":
        username = _clean_text(body.get("username"), 0, USERNAME_MAX)
        password = _clean_text(body.get("password"), 1, PASSWORD_MAX)
        if username is None or password is None:
            return None
        return {"kind": "submit", "username": username, "password": password}
    if kind == "focus":
        rect = body.get("rect")
        if not isinstance(rect, dict):
            return None
        out = {}
        for key in ("x", "y", "w", "h"):
            number = _number(rect.get(key))
            if number is None:
                return None
            out[key] = number
        if out["w"] < 0 or out["h"] < 0:
            return None
        return {"kind": "focus", "rect": out}
    if kind == "hide":
        return {"kind": "hide"}
    return None


def pending_valid(pending, now):
    """Return True if the pending credential PENDING is not too old."""
    return pending is not None and now - pending["time"] <= PENDING_SECONDS


def offer_kind(existing, password):
    """Return "save", "update" or "none" for a new PASSWORD.

    EXISTING is the saved password for the same origin and user name, or None.
    """
    if existing is None:
        return "save"
    return "none" if existing == password else "update"


def clipboard_should_clear(current, copied):
    """Return True if the clipboard still holds the COPIED password."""
    return current is not None and current == copied


def entry_label(username, host):
    return "cruxx browser: %s @ %s" % (username, host)


# backends
class Backend:
    """Interface. All callbacks run on the main loop."""

    available = True
    notice = ""

    def list(self, origin, done):
        """Call DONE with a sorted list of (origin, username). ORIGIN None = all."""
        raise NotImplementedError

    def get(self, origin, username, done):
        """Call DONE with the password, or None."""
        raise NotImplementedError

    def put(self, origin, username, password, done):
        """Save or replace. Call DONE with True or False."""
        raise NotImplementedError

    def delete(self, origin, username, done):
        """Remove. Call DONE with True or False."""
        raise NotImplementedError


class MemoryBackend(Backend):
    """Keeps entries in memory only. For tests."""

    def __init__(self):
        self.items = {}

    def list(self, origin, done):
        found = sorted(key for key in self.items if origin is None or key[0] == origin)
        done(found)

    def get(self, origin, username, done):
        done(self.items.get((origin, username)))

    def put(self, origin, username, password, done):
        self.items[(origin, username)] = password
        done(True)

    def delete(self, origin, username, done):
        done(self.items.pop((origin, username), None) is not None)


class SecretBackend(Backend):
    """The system keyring through libsecret (Secret Service)."""

    def __init__(self):
        self.available = False
        self.notice = OFF_NOTICE
        self._secret = None
        self._schema = None
        try:
            import gi
            gi.require_version("Secret", "1")
            from gi.repository import Secret
        except (ImportError, ValueError):
            return
        self._secret = Secret
        self._schema = Secret.Schema.new(
            SCHEMA_NAME, Secret.SchemaFlags.NONE,
            {"origin": Secret.SchemaAttributeType.STRING,
             "username": Secret.SchemaAttributeType.STRING})
        self.available = True

    def probe(self, done):
        """Check that the Secret Service answers. Do not unlock. DONE(bool)."""
        if self._secret is None:
            done(False)
            return
        Secret = self._secret

        def got(_source, result, _data=None):
            try:
                Secret.Service.get_finish(result)
            except Exception as exc:  # GLib.Error
                self._fail(exc)
                done(False)
                return
            done(True)

        Secret.Service.get(Secret.ServiceFlags.NONE, None, got, None)

    def _fail(self, exc):
        # Log the error code only. The message can hold item data.
        log.warning("keyring call failed: %s", type(exc).__name__)
        self.available = False

    def list(self, origin, done):
        Secret = self._secret
        # With no attribute, the search lists all items of this schema.
        attrs = {} if origin is None else {"origin": origin}

        def got(_source, result, _data=None):
            try:
                items = Secret.password_search_finish(result)
            except Exception as exc:
                self._fail(exc)
                done(None)
                return
            found = []
            for item in items or []:
                data = item.get_attributes()
                if data.get("origin") and data.get("username") is not None:
                    found.append((data["origin"], data["username"]))
            done(sorted(found))

        Secret.password_search(self._schema, attrs, Secret.SearchFlags.ALL,
                               None, got, None)

    def get(self, origin, username, done):
        Secret = self._secret

        def got(_source, result, _data=None):
            try:
                done(Secret.password_lookup_finish(result))
            except Exception as exc:
                self._fail(exc)
                done(None)

        Secret.password_lookup(self._schema, {"origin": origin, "username": username},
                               None, got, None)

    def put(self, origin, username, password, done):
        Secret = self._secret

        def got(_source, result, _data=None):
            try:
                Secret.password_store_finish(result)
            except Exception as exc:
                self._fail(exc)
                done(False)
                return
            done(True)

        Secret.password_store(
            self._schema, {"origin": origin, "username": username},
            Secret.COLLECTION_DEFAULT, entry_label(username, origin_host(origin)),
            password, None, got, None)

    def delete(self, origin, username, done):
        Secret = self._secret

        def got(_source, result, _data=None):
            try:
                done(bool(Secret.password_clear_finish(result)))
            except Exception as exc:
                self._fail(exc)
                done(False)

        Secret.password_clear(self._schema, {"origin": origin, "username": username},
                              None, got, None)


def make_backend(kind=None):
    """Return the backend. KIND "memory" gives the test backend."""
    if kind == "memory":
        return MemoryBackend()
    return SecretBackend()
