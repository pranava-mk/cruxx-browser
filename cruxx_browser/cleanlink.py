"""Clean links. PURE logic: remove tracking parameters from an address.

The list follows CleanLink.swift of Search by Office Commun (MIT),
https://github.com/driceroland/Search. Only names that track and do
nothing else are removed. The other parameters keep their order and
encoding. The fragment stays. An address with a signature stays as it is.
"""

import urllib.parse

TRACKING = frozenset((
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "yclid",
    "twclid", "ttclid", "mc_eid", "igshid", "igsh", "_hsenc", "_hsmi",
    "mkt_tok", "ref_src",
))
# Names that track only on some sites (the share id of YouTube and Spotify).
TRACKING_ON = {"si": ("youtube.com", "youtu.be", "spotify.com")}
SIGNATURES = frozenset(("x-amz-signature", "x-goog-signature", "signature", "sig"))


def _name(piece):
    raw = piece.split("=", 1)[0]
    return urllib.parse.unquote_plus(raw).lower()


def tracks(name, host):
    if name.startswith("utm_") or name in TRACKING:
        return True
    sites = TRACKING_ON.get(name)
    return bool(sites) and any(host == s or host.endswith("." + s) for s in sites)


def clean_link(url):
    """Return URL without tracking parameters. Return URL if nothing changes."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return url
    if parts.scheme.lower() not in ("http", "https") or not parts.query:
        return url
    pieces = parts.query.split("&")
    names = [_name(p) for p in pieces]
    if any(n in SIGNATURES for n in names):
        return url
    kept = [p for p, n in zip(pieces, names) if not tracks(n, host)]
    if len(kept) == len(pieces):
        return url
    return urllib.parse.urlunsplit(parts._replace(query="&".join(kept)))
