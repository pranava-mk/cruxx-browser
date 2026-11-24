"""Site card and hidden list: popovers that hang on the tab row.

Upstream: SiteCard.swift, Hidden.swift. In a private tab the changes stay in
memory (see the private_* fields of the window).
"""

import urllib.parse

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from . import store  # noqa: E402
from .forms import button, divider, label, row, switch  # noqa: E402


class _Pop(Gtk.Popover):
    def __init__(self, win, tab, anchor):
        super().__init__()
        self.win = win
        self.tab = tab
        self.set_relative_to(anchor)
        self.set_position(Gtk.PositionType.RIGHT if win.side == "left"
                          else Gtk.PositionType.BOTTOM)
        self.get_style_context().add_class("cruxx-pop")
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.body.set_border_width(14)
        self.body.set_size_request(320, -1)
        self.add(self.body)
        self.connect("closed", lambda *_: self.destroy())

    def rebuild(self):
        for child in self.body.get_children():
            child.destroy()
        self.fill()
        self.body.show_all()

    def popup(self):
        self.rebuild()
        super().popup()


def connection_info(tab):
    """Return (state text, detail lines) for the page of TAB."""
    url = tab.url or ""
    if url.startswith("http://"):
        return "Not secure (http)", []
    if not url.startswith("https://"):
        return "Local page", []
    if tab.view is None:
        return "Secure (https)", []
    try:
        ok, cert, errors = tab.view.get_tls_info()
    except (TypeError, ValueError):
        return "Secure (https)", []
    if not ok:
        return "Connection not verified", []
    lines = []
    if cert is not None:
        for title, getter in (("Issued to", "get_subject_name"),
                              ("Issued by", "get_issuer_name")):
            try:
                text = getattr(cert, getter)()
            except (AttributeError, TypeError):
                text = None
            if text:
                lines.append("%s: %s" % (title, text))
    return "Secure connection (https)", lines


class SiteCard(_Pop):
    def fill(self):
        win, tab, body = self.win, self.tab, self.body
        host = tab.host or "this page"
        body.pack_start(label(host, "cruxx-subtitle", ellipsize=True), False, False, 2)
        state, lines = connection_info(tab)
        body.pack_start(label(state, "muted"), False, False, 0)
        for line in lines:
            body.pack_start(label(line, "cruxx-note", ellipsize=True), False, False, 0)
        body.pack_start(divider(), False, False, 6)
        if not tab.host:
            return
        enabled = win.store.settings["shield_enabled"]
        shield = switch(enabled and not win.site_paused(tab),
                        lambda on: win.set_site_shield(tab, not on))
        shield.set_sensitive(enabled)
        body.pack_start(row("Shield on this site", shield,
                            None if enabled else "The shield is off in Settings."),
                        False, False, 4)
        if win.store.settings["keep_awake_enabled"]:
            body.pack_start(row("Keep this site awake", switch(
                win.is_kept_awake(tab), lambda on: win.set_kept_awake(tab, on))),
                False, False, 4)
        body.pack_start(row("Zoom", self._zoom_controls()), False, False, 4)
        body.pack_start(divider(), False, False, 6)
        self._permissions(body)
        saved = label("Saved passwords: …", "cruxx-note")
        body.pack_start(saved, False, False, 4)
        win.passwords.count_for(tab, lambda n: saved.set_text(
            "%d saved password%s" % (n, "" if n == 1 else "s")))
        count = len(win.store.hidden.get(store.registrable_host(tab.host), []))
        body.pack_start(row("Hidden elements: %d" % count, button(
            "Show hidden list", self._show_hidden)), False, False, 4)
        clear = button("Clear cookies for this site", self._clear_cookies)
        clear.set_sensitive(not tab.private)
        body.pack_start(row("Cookies and site data", clear,
                            "Private tab: nothing is saved." if tab.private else None),
                        False, False, 4)
        body.pack_start(label("Blocked popups: %d" % tab.blocked_popups, "cruxx-note"),
                        False, False, 4)

    def _zoom_controls(self):
        box = Gtk.Box(spacing=4)
        self.zoom_text = label("")
        self.zoom_text.set_width_chars(5)
        self._sync_zoom()

        def step(delta):
            level = 1.0 if delta == 0 else self.win.zoom_level_for(self.tab) + delta
            self.win.set_zoom_level(self.tab, level)
            self._sync_zoom()

        box.pack_start(button("−", lambda: step(-0.1)), False, False, 0)
        box.pack_start(self.zoom_text, False, False, 0)
        box.pack_start(button("Reset", lambda: step(0)), False, False, 0)
        box.pack_start(button("+", lambda: step(0.1)), False, False, 0)
        return box

    def _sync_zoom(self):
        self.zoom_text.set_text("%d%%" % round(self.win.zoom_level_for(self.tab) * 100))

    def _origins(self):
        """Return {origin: {kind: allowed}} for the host of the tab."""
        win, host = self.win, store.registrable_host(self.tab.host)
        found = {}
        for source in (win.store.settings["permissions"],
                       win.private_grants if self.tab.private else {}):
            for origin, kinds in source.items():
                site = store.registrable_host(urllib.parse.urlsplit(origin).hostname or "")
                if site == host and kinds:
                    found.setdefault(origin, {}).update(kinds)
        return found

    def _permissions(self, body):
        found = self._origins()
        body.pack_start(label("Remembered permissions", "cruxx-note"), False, False, 2)
        if not found:
            body.pack_start(label("None", "muted"), False, False, 2)
        for origin, kinds in found.items():
            for kind, allowed in sorted(kinds.items()):
                text = "%s: %s" % (kind, "allow" if allowed else "deny")
                body.pack_start(row(text, button(
                    "Revoke", lambda o=origin, k=kind: self._revoke(o, k))),
                    False, False, 2)

    def _revoke(self, origin, kind):
        win = self.win
        win.private_grants.get(origin, {}).pop(kind, None)
        if not self.tab.private:
            try:
                win.store.forget_permission(origin, kind)
            except OSError:
                pass
        self.rebuild()

    def _show_hidden(self):
        win, tab = self.win, self.tab
        self.popdown()
        win.open_hidden_list(tab)

    def _clear_cookies(self):
        self.win.clear_site_data(self.tab.host)
        self.popdown()


class HiddenList(_Pop):
    def fill(self):
        win, tab, body = self.win, self.tab, self.body
        site = store.registrable_host(tab.host)
        sels = win.store.hidden.get(site, [])
        body.pack_start(label("Hidden on " + site, "cruxx-subtitle", ellipsize=True),
                        False, False, 2)
        if tab.private:
            body.pack_start(label("Private tab: the rules do not change here.",
                                  "cruxx-note", wrap=True), False, False, 2)
        if not sels:
            body.pack_start(label("Nothing is hidden on this site.", "muted"),
                            False, False, 6)
            return
        body.pack_start(divider(), False, False, 4)
        for sel in sels:
            text = label(sel, ellipsize=True)
            text.set_tooltip_text(sel)
            text.set_max_width_chars(34)
            line = Gtk.Box(spacing=8)
            line.pack_start(text, True, True, 0)
            remove = button("Remove", lambda s=sel: self._remove(s))
            remove.set_sensitive(not tab.private)
            line.pack_end(remove, False, False, 0)
            body.pack_start(line, False, False, 3)
        body.pack_start(divider(), False, False, 4)
        every = button("Unhide all", self._clear)
        every.set_sensitive(not tab.private)
        body.pack_start(every, False, False, 2)

    def _remove(self, selector):
        try:
            self.win.store.remove_hidden(self.tab.host, selector)
        except OSError:
            return
        self.win.reapply_hidden(self.tab)
        self.rebuild()

    def _clear(self):
        try:
            self.win.store.clear_hidden(self.tab.host)
        except OSError:
            return
        self.win.reapply_hidden(self.tab)
        self.rebuild()
