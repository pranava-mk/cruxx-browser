"""Pure security helpers: URL schemes, download names, WebKit settings."""

import os
import re
import unicodedata
import urllib.parse

# Base WebKit settings. Applied to every WebView.
# "enable-developer-extras" is set from the --dev flag.
# "hardware-acceleration-policy" stays at the WebKit default.
WEBKIT_SETTINGS = {
    "enable-developer-extras": False,
    "allow-file-access-from-file-urls": False,
    "allow-universal-access-from-file-urls": False,
    "javascript-can-open-windows-automatically": False,
    "javascript-can-access-clipboard": False,
    "enable-write-console-messages-to-stdout": False,
    "enable-dns-prefetching": False,
    "enable-hyperlink-auditing": False,
    "enable-mediasource": True,
    "enable-smooth-scrolling": True,
}

# WebKit 2.54 ignores these and prints a warning when they are set.
DEPRECATED_NOOP = ("enable-hyperlink-auditing",)

MAX_NAME_BYTES = 200


def settings_for(dev):
    """Return the settings table for the DEV flag."""
    table = dict(WEBKIT_SETTINGS)
    table["enable-developer-extras"] = bool(dev)
    return table


def apply_settings(settings, dev, log):
    """Apply the table to a WebKit2.Settings object.

    Skip unknown and deprecated names. Log unknown names at debug level.
    """
    for name, value in settings_for(dev).items():
        if name in DEPRECATED_NOOP:
            continue
        if settings.find_property(name) is None:
            log.debug("unknown WebKit setting skipped: %s", name)
            continue
        settings.set_property(name, value)


def scheme_decision(uri, is_main_frame):
    """Return "allow", "block" or "external" for a navigation to URI."""
    if not uri:
        return "block"
    try:
        scheme = urllib.parse.urlsplit(uri.strip()).scheme.lower()
    except ValueError:
        return "block"
    if scheme in ("http", "https", "blob"):
        return "allow"
    if scheme == "about":
        # about:srcdoc is only possible in a subframe (<iframe srcdoc>).
        return "allow" if uri.strip().lower() in ("about:blank", "about:srcdoc") else "block"
    if scheme == "data":
        return "block" if is_main_frame else "allow"
    if scheme in ("file", ""):
        return "block"
    if scheme == "javascript":
        return "block"
    return "external"


def _truncate(text, limit):
    return text.encode("utf-8")[:limit].decode("utf-8", "ignore")


def safe_download_name(name):
    """Return a safe file name for a download. Never return a path."""
    text = unicodedata.normalize("NFC", str(name or ""))
    text = text.replace("\\", "/").split("/")[-1]
    text = re.sub(r"\s+", " ", text)
    # Remove control characters (Cc) and format characters (Cf). Cf includes
    # bidi overrides and zero-width characters.
    text = "".join(ch for ch in text
                   if unicodedata.category(ch) not in ("Cc", "Cf")).strip()
    text = text.lstrip(".- ").rstrip(". ")
    if not text:
        return "download"
    if len(text.encode("utf-8")) > MAX_NAME_BYTES:
        stem, ext = os.path.splitext(text)
        if len(ext.encode("utf-8")) > 20:
            stem, ext = text, ""
        stem = _truncate(stem, MAX_NAME_BYTES - len(ext.encode("utf-8")))
        text = (stem.rstrip() + ext) or "download"
    return text


def unique_name(directory, name, exists=os.path.exists):
    """Return NAME, or NAME with a suffix like " (1)", that is free."""
    if not exists(os.path.join(directory, name)):
        return name
    stem, ext = os.path.splitext(name)
    counter = 1
    while True:
        candidate = "%s (%d)%s" % (stem, counter, ext)
        if not exists(os.path.join(directory, candidate)):
            return candidate
        counter += 1


def reserve_name(directory, name, max_tries=1000):
    """Create an empty file for NAME in DIRECTORY. Return (name, path).

    Try NAME, then "stem (1).ext" and so on. O_EXCL makes the reservation
    safe against races. It also fails on a dangling symlink. O_NOFOLLOW
    stops a symlink at the last path part. Raise OSError if no name is free.
    """
    stem, ext = os.path.splitext(name)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
    for counter in range(max_tries):
        candidate = name if counter == 0 else "%s (%d)%s" % (stem, counter, ext)
        path = os.path.join(directory, candidate)
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            continue
        os.close(fd)
        return candidate, path
    raise OSError("no free file name for %r" % name)


def loadable(url):
    """Return True if URL may be loaded in a tab or kept in saved data."""
    return isinstance(url, str) and scheme_decision(url, True) == "allow"


_DEFAULT_PORTS = {"http": 80, "https": 443}
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def permission_origin(uri):
    """Return "scheme://host:port" for URI, or "" if URI has no origin.

    Default ports are made explicit. The host is lower case.
    """
    try:
        parts = urllib.parse.urlsplit((uri or "").strip())
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return ""
    if scheme not in _DEFAULT_PORTS or not host:
        return ""
    if port is None:
        port = _DEFAULT_PORTS[scheme]
    if ":" in host:
        host = "[%s]" % host
    return "%s://%s:%d" % (scheme, host, port)


def remember_allowed(origin):
    """Return True if a permission for ORIGIN may be saved.

    Allow https origins. Allow http only for the local machine.
    """
    if origin.startswith("https://"):
        return True
    if not origin.startswith("http://"):
        return False
    try:
        host = urllib.parse.urlsplit(origin).hostname or ""
    except ValueError:
        return False
    return host in _LOCAL_HOSTS


def display_uri(uri, limit=200):
    """Return URI for a dialog: no control or format characters, cut to LIMIT."""
    text = "".join(ch for ch in str(uri or "")
                   if unicodedata.category(ch) not in ("Cc", "Cf"))
    if len(text) > limit:
        text = text[:limit] + "..."
    return text


def uri_scheme(uri):
    """Return the lower case scheme of URI, or an empty string."""
    try:
        return urllib.parse.urlsplit((uri or "").strip()).scheme.lower()
    except ValueError:
        return ""
