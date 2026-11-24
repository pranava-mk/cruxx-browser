"""The address field and the tab switcher.

There is no toolbar. The field is a floating card in the middle of the page.
It shows for Ctrl+L and for a new tab. The tab switcher (Ctrl+K) uses the
same card with a list of open tabs. See docs/design-notes.md.

Typed text stays local. Nothing is sent to the network before Enter.
"""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

from . import omnibox, store  # noqa: E402
from .widgets import Glyph, Mark, letter_for, track_hover  # noqa: E402

FIELD_WIDTH = 560
# The field is lifted this far above the middle of the page.
LIFT = 30
# Text 22 high, with 14 of air above and below it. See Omnibox.swift.
FIELD_HEIGHT = 22 + 2 * 14
MAX_ROWS = 8


class OfferRow(Gtk.EventBox):
    """One row of a suggestion list."""

    def __init__(self, offer, on_click):
        super().__init__()
        self.offer = offer
        self.set_visible_window(True)
        context = self.get_style_context()
        context.add_class("cruxx-offer")
        box = Gtk.Box(spacing=10)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(9)
        box.set_margin_bottom(9)
        if offer.get("symbol") == "search":
            lead = Glyph("search", 14, 9, 1.3)
            lead.get_style_context().add_class("cruxx-sym")
        else:
            lead = Mark(14)
            lead.set_content(offer.get("icon"), offer.get("letter", ""))
        box.pack_start(lead, False, False, 0)
        key = Gtk.Label(label=offer["label"], xalign=0, ellipsize=Pango.EllipsizeMode.END)
        key.get_style_context().add_class("cruxx-key")
        box.pack_start(key, False, False, 0)
        if offer.get("title"):
            sub = Gtk.Label(label=offer["title"], xalign=0, ellipsize=Pango.EllipsizeMode.END)
            sub.get_style_context().add_class("cruxx-sub")
            box.pack_start(sub, True, True, 0)
        else:
            box.pack_start(Gtk.Box(), True, True, 0)
        if offer.get("kind") == "bookmark":
            mark = Glyph("bookmark", 14, 9, 1.2)
            mark.get_style_context().add_class("cruxx-sym")
            box.pack_end(mark, False, False, 0)
        self.add(box)
        track_hover(self)
        self._on_click = on_click
        self.connect("button-press-event", self._on_press)
        self.show_all()

    def _on_press(self, _w, event):
        if event.button == 1:
            self._on_click(self)
        return True

    def set_picked(self, picked):
        context = self.get_style_context()
        (context.add_class if picked else context.remove_class)("picked")


class Prompt:
    """A floating field with a list under it. Base of the two prompts."""

    placeholder = ""

    def __init__(self, win):
        self.win = win
        self.rows = []
        self.picked = 0
        self._quiet = False
        self.entry = Gtk.Entry(hexpand=True)
        self.entry.set_has_frame(False)
        self.entry.connect("changed", self._on_changed)
        self.entry.connect("activate", lambda *_: self.activate_picked())
        self.entry.connect("key-press-event", self._on_key)
        self.field = Gtk.Box()
        for name in ("cruxx-card", "cruxx-field"):
            self.field.get_style_context().add_class(name)
        # GTK hides the placeholder of a focused entry. So draw our own.
        self.hint = Gtk.Label(label=self.placeholder, xalign=0)
        self.hint.get_style_context().add_class("cruxx-hint")
        self.hint.set_halign(Gtk.Align.START)
        self.hint.set_valign(Gtk.Align.CENTER)
        holder = Gtk.Overlay()
        holder.add(self.entry)
        holder.add_overlay(self.hint)
        holder.set_overlay_pass_through(self.hint, True)
        self.field.pack_start(holder, True, True, 0)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.list_card = Gtk.Box()
        for name in ("cruxx-card", "cruxx-list"):
            self.list_card.get_style_context().add_class(name)
        self.list_card.pack_start(self.list, True, True, 0)
        self.list_card.set_no_show_all(True)
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.card.set_size_request(FIELD_WIDTH, -1)
        self.card.pack_start(self.field, False, False, 0)
        self.card.pack_start(self.list_card, False, False, 0)
        self.card.set_no_show_all(True)
        self.field.show_all()

    def is_open(self):
        return self.card.get_visible()

    # showing
    def open(self, text="", select=True):
        # An address that is already there gets no list until the user types.
        self._quiet = True
        self.entry.set_text(text)
        self._quiet = False
        self.field.get_style_context().remove_class("refused")
        self._clear()
        self.hint.set_visible(not text)
        self.card.show()
        self.entry.grab_focus()
        if select:
            self.entry.select_region(0, -1)
        else:
            self.entry.set_position(-1)
        if not text:
            self._refill()

    def close(self):
        self.card.hide()
        self._clear()

    def _clear(self):
        for row in self.rows:
            row.destroy()
        self.rows = []
        self.list_card.hide()

    # rows
    def offers(self, text):
        """Return the offers for TEXT. Overridden by the prompts."""
        raise NotImplementedError

    def take(self, offer):
        """Do the action of OFFER. Overridden by the prompts."""
        raise NotImplementedError

    def _on_changed(self, _entry):
        self.hint.set_visible(not self.entry.get_text())
        if self._quiet:
            return
        self.field.get_style_context().remove_class("refused")
        self._refill()

    def _refill(self):
        self._clear()
        if not self.card.get_visible():
            return
        for offer in self.offers(self.entry.get_text()):
            row = OfferRow(offer, lambda r: self.take(r.offer))
            self.list.pack_start(row, False, False, 0)
            self.rows.append(row)
        if self.rows:
            self.list_card.show()
            self.list.show()
        self.picked = 0
        self._paint()

    def _paint(self):
        for index, row in enumerate(self.rows):
            row.set_picked(index == self.picked)

    def _on_key(self, _entry, event):
        name = Gdk.keyval_name(event.keyval)
        if name in ("Down", "KP_Down", "Up", "KP_Up") and self.rows:
            step = 1 if "Down" in name else -1
            self.picked = (self.picked + step) % len(self.rows)
            self._paint()
            return True
        if name == "Tab" and self.rows:
            return True
        return False

    def activate_picked(self):
        if self.rows:
            self.take(self.rows[min(self.picked, len(self.rows) - 1)].offer)

    def refuse(self):
        self.field.get_style_context().add_class("refused")


class AddressPrompt(Prompt):
    placeholder = "Search or enter address"

    def offers(self, text):
        win = self.win
        rows = omnibox.suggestions(text, win.store.history, win.store.bookmarks,
                                   win.store.settings["engine"], MAX_ROWS)
        for row in rows:
            if row["kind"] == "search":
                row["symbol"] = "search"
                continue
            row["letter"] = letter_for(row["url"], row["title"])
            row["icon"] = win.icon_for(row["url"])
        return rows

    def take(self, offer):
        self.win.hide_prompts()
        self.win.open_in_current(offer["url"])
        if self.win.active and self.win.active.view:
            self.win.active.view.grab_focus()


class SwitcherPrompt(Prompt):
    placeholder = "Switch to tab"

    def offers(self, text):
        tabs = self.win.tabs
        order = omnibox.switch_rank(text, [(t.title, t.url) for t in tabs])
        rows = []
        for index in order[:MAX_ROWS]:
            tab = tabs[index]
            rows.append({"kind": "tab", "tab": tab, "label": tab.title,
                         "title": store.host_of(tab.url), "icon": tab.favicon,
                         "letter": letter_for(tab.url, tab.title)})
        if not rows:
            rows.append({"kind": "none", "label": "No open tab matches", "title": "",
                         "letter": ""})
        return rows

    def take(self, offer):
        tab = offer.get("tab")
        if tab is None:
            return
        self.win.hide_prompts()
        self.win.select_tab(tab)
