"""Settings window: a list of sections on the left, the content on the right.

Each control saves through Window.set_option or the Store, and applies at once.
"""

import os

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import __version__, omnibox, shortcuts, store, wall  # noqa: E402
from .forms import button, choice, confirm, divider, label, row, switch  # noqa: E402

SECTIONS = ("General", "Tabs", "Themes", "Privacy", "Passwords", "Shortcuts", "About")
PEEK_TEXT = {"alt": "Alt+click", "shift": "Shift+click", "off": "Off"}
WALL_TEXT = (("off", "Off"), ("omarchy", "Omarchy wallpaper"), ("color", "Colour"),
             ("gradient", "Gradient"), ("picture", "Picture"))
SLEEP_TEXT = {0: "Never", 15: "15 minutes", 30: "30 minutes", 60: "1 hour",
              120: "2 hours"}


class SettingsWindow(Gtk.Window):
    def __init__(self, win):
        super().__init__(title="Settings")
        self.win = win
        self.set_transient_for(win)
        self.set_default_size(800, 560)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.get_style_context().add_class("cruxx-settings")
        self.pages = {}
        self.nav = Gtk.ListBox()
        self.nav.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav.get_style_context().add_class("cruxx-nav")
        for name in SECTIONS:
            item = Gtk.ListBoxRow()
            item.name = name
            item.add(label(name))
            self.nav.add(item)
        self.nav.connect("row-selected", self._on_nav)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.get_style_context().add_class("cruxx-sidebar")
        side.set_size_request(180, -1)
        side.pack_start(self.nav, True, True, 0)
        self.stack = Gtk.Stack()
        for name in SECTIONS:
            holder = Gtk.ScrolledWindow()
            holder.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.pages[name] = holder
            self.stack.add_named(holder, name)
            self._fill(name)
        root = Gtk.Box()
        root.pack_start(side, False, False, 0)
        split = Gtk.Box()
        split.get_style_context().add_class("cruxx-divider")
        split.set_size_request(1, -1)
        root.pack_start(split, False, False, 0)
        root.pack_start(self.stack, True, True, 0)
        self.add(root)
        self.connect("key-press-event", self._on_key)
        root.show_all()

    def show_section(self, name=None):
        name = name if name in SECTIONS else "General"
        self.nav.select_row(self.nav.get_row_at_index(SECTIONS.index(name)))
        self.present()

    def _on_nav(self, _list, item):
        if item is not None:
            self.stack.set_visible_child_name(item.name)

    def _on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        # Ctrl+1 to Ctrl+5 go to a section.
        if event.state & Gdk.ModifierType.CONTROL_MASK and 49 <= event.keyval < 49 + len(SECTIONS):
            self.show_section(SECTIONS[event.keyval - 49])
            return True
        return False

    def _fill(self, name):
        holder = self.pages[name]
        for child in holder.get_children():
            child.destroy()
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        page.set_border_width(28)
        page.pack_start(label(name, "cruxx-section-title"), False, False, 8)
        getattr(self, "_page_" + name.lower())(page)
        holder.add(page)
        holder.show_all()

    def _add(self, page, widget):
        page.pack_start(widget, False, False, 0)
        page.pack_start(divider(), False, False, 0)

    def _opt(self, key):
        return self.win.store.settings[key]

    def _bool(self, page, key, title, note=None):
        self._add(page, row(title, switch(
            self._opt(key), lambda on: self.win.set_option(key, on)), note))

    # sections
    def _page_general(self, page):
        engines = [(name, omnibox.engine_label(name)) for name in store.ENGINES]
        self._add(page, row("Search engine", choice(
            engines, self._opt("engine"),
            lambda v: self.win.set_option("engine", v))))
        self._bool(page, "restore_session", "Restore last session",
                   "Open the tabs of the last session at start.")
        self._add(page, row("Tabs side", choice(
            [("left", "Left"), ("top", "Top")], self.win.side, self.win.set_side)))

    def _page_tabs(self, page):
        current = self._opt("sleep_after_min")
        items = [(str(m), SLEEP_TEXT[m]) for m in store.SLEEP_CHOICES]
        if current not in store.SLEEP_CHOICES:
            items.append((str(int(current)), "%d minutes" % current))
        self._add(page, row("Sleep tabs after", choice(
            items, str(int(current)),
            lambda v: self.win.set_option("sleep_after_min", int(v))),
            "A tab that you did not use frees its web process."))
        self._bool(page, "sleep_pinned", "Let pinned tabs sleep")
        self._bool(page, "keep_awake_enabled", "Offer keep-awake for sites",
                   "Shows Keep This Site Awake in the menu and the site card.")
        self._bool(page, "split_enabled", "Split View",
                   "Show two pages side by side.")
        self._add(page, row("Peek", choice(
            [(k, PEEK_TEXT[k]) for k in store.PEEK_MODIFIERS], self._opt("peek_modifier"),
            lambda v: self.win.set_option("peek_modifier", v)),
            "Hold this key and click a link to preview it in a card."))

    def _wall_set(self, **changes):
        spec = dict(self._opt("wall"))
        spec.update(changes)
        self.win.set_option("wall", spec)
        self._wall_sensitive()

    def _wall_sensitive(self):
        kind = self._opt("wall")["kind"]
        for name, widget in self._wall_rows.items():
            widget.set_sensitive(kind == name)

    def _color_button(self, key):
        widget = Gtk.ColorButton()
        color = Gdk.RGBA()
        color.parse(self._opt("wall")[key])
        widget.set_rgba(color)
        widget.connect("color-set", lambda w: self._wall_set(**{key: _hex(w.get_rgba())}))
        return widget

    def _page_themes(self, page):
        spec = self._opt("wall")
        self._wall_rows = {}
        self._add(page, row("Wall behind a blank tab", choice(
            list(WALL_TEXT), spec["kind"], lambda v: self._wall_set(kind=v)),
            "Draws once and is kept. It costs nothing while you browse."))
        rows = {}
        rows["color"] = row("Colour", self._color_button("color"))
        gradient = Gtk.Box(spacing=8)
        gradient.pack_start(self._color_button("from"), False, False, 0)
        gradient.pack_start(self._color_button("to"), False, False, 0)
        angle = Gtk.SpinButton.new_with_range(0, 359, wall.ANGLE_STEP)
        angle.set_value(spec["angle"])
        angle.set_tooltip_text("Angle in degrees. 0 goes up, 90 goes right.")
        angle.connect("value-changed", lambda w: self._wall_set(angle=int(w.get_value())))
        gradient.pack_start(angle, False, False, 0)
        rows["gradient"] = row("Gradient: two colours and an angle", gradient)
        chooser = Gtk.FileChooserButton(
            title="Choose a picture", action=Gtk.FileChooserAction.OPEN)
        images = Gtk.FileFilter()
        images.set_name("Pictures")
        images.add_pixbuf_formats()
        chooser.add_filter(images)
        if spec["picture"]:
            chooser.set_filename(spec["picture"])
        chooser.connect("file-set", lambda w: self._wall_set(
            picture=w.get_filename() or ""))
        chooser.set_size_request(220, -1)
        rows["picture"] = row("Picture", chooser,
                              "A picture file up to 50 MB. A bad file turns the wall off.")
        for name in ("color", "gradient", "picture"):
            self._add(page, rows[name])
            self._wall_rows[name] = rows[name]
        self._wall_sensitive()

    def _page_privacy(self, page):
        self._bool(page, "shield_enabled", "Ad and tracker shield",
                   "Blocks ads and trackers on all sites.")
        paused = self._opt("shield_paused_hosts")
        self._add(page, label("Sites where the shield is paused", "cruxx-subtitle"))
        for host in list(paused) or [None]:
            if host is None:
                self._add(page, row("None", None))
                continue
            self._add(page, self._item(host, lambda h=host: self._unpause(h)))
        self._add(page, label("Remembered permissions", "cruxx-subtitle"))
        perms = self._opt("permissions")
        for origin in list(perms) or [None]:
            if origin is None:
                self._add(page, row("None", None))
                continue
            kinds = ", ".join("%s: %s" % (k, "allow" if v else "deny")
                              for k, v in sorted(perms[origin].items()))
            self._add(page, self._item(origin, lambda o=origin: self._forget(o), kinds))
        self._add(page, label("Clear data", "cruxx-subtitle"))
        self.note = label("", "cruxx-note")
        self._add(page, row("History", button("Clear history", self._clear_history)))
        self._add(page, row("Cookies and site data", button(
            "Clear cookies and site data…", self._clear_data),
            "Removes cookies, storage, and caches of all sites."))
        self._add(page, row("Hidden elements", button(
            "Clear hidden-element rules", self._clear_hidden)))
        page.pack_start(self.note, False, False, 6)

    def _page_passwords(self, page):
        manager = self.win.passwords
        self._bool(page, "passwords_enabled", "Offer to save passwords",
                   "Asks after a sign-in worked. The browser never fills a field by itself.")
        if manager.notice():
            self._add(page, label(manager.notice(), "cruxx-note", wrap=True))
        self._add(page, row("Saved passwords", button(
            "Open passwords", self.win.open_passwords),
            "Stored in the system keyring. Shortcut: Ctrl+Alt+L."))
        self._add(page, label("Sites where the browser does not offer to save", "cruxx-subtitle"))
        for origin in list(self._opt("password_never")) or [None]:
            if origin is None:
                self._add(page, row("None", None))
                continue
            self._add(page, self._item(origin, lambda o=origin: self._allow_offers(o)))

    def refresh_passwords(self):
        self._fill("Passwords")

    def _allow_offers(self, origin):
        try:
            self.win.store.remove_password_never(origin)
        except OSError:
            pass
        self._fill("Passwords")

    def _item(self, text, remove, note=None):
        return row(text, button("Remove", remove), note)

    def _page_shortcuts(self, page):
        grid = Gtk.Grid(column_spacing=24, row_spacing=7)
        for index, (keys, action) in enumerate(shortcuts.rows()):
            grid.attach(label(keys, "cruxx-key"), 0, index, 1, 1)
            grid.attach(label(action, "muted", wrap=True), 1, index, 1, 1)
        page.pack_start(grid, False, False, 0)
        if self.win.opts.dev:
            page.pack_start(label("F12: Web inspector (--dev)", "cruxx-note"),
                            False, False, 8)

    def _page_about(self, page):
        page.pack_start(label("cruxx browser", "cruxx-subtitle"), False, False, 0)
        for text in ("Version " + __version__,
                     "Design from Search by Office Commun (MIT)",
                     "No telemetry. The app makes no network requests by itself."):
            page.pack_start(label(text, "muted", wrap=True), False, False, 3)
        page.pack_start(label("Data folders", "cruxx-subtitle"), False, False, 10)
        for title, path in (("Data", store.data_dir()), ("Config", store.config_dir()),
                            ("Cache", store.cache_dir())):
            page.pack_start(label(title, "cruxx-note"), False, False, 0)
            page.pack_start(label(path, "muted", ellipsize=True, selectable=True),
                            False, False, 2)

    # actions
    def _say(self, text):
        self.note.set_text(text)

    def _unpause(self, host):
        try:
            self.win.store.set_shield_paused(host, False)
        except OSError:
            pass
        for tab in self.win.all_tabs():
            if tab.view is not None:
                tab.tune_shield(tab.host)
        self._fill("Privacy")

    def _forget(self, origin):
        try:
            self.win.store.forget_permission(origin)
        except OSError:
            pass
        self._fill("Privacy")

    def _clear_history(self):
        self.win.store.clear_history()
        try:
            self.win.store.flush()
        except OSError:
            pass
        if self.win.panel.is_open():
            self.win.panel.populate()
        self._say("History cleared.")

    def _clear_data(self):
        if not confirm(self, "Clear all cookies and site data?",
                       "You will be signed out of all sites. This cannot be undone.",
                       "Clear"):
            return
        self.win.clear_website_data(
            lambda ok: self._say("Site data cleared." if ok else "Could not clear data."))

    def _clear_hidden(self):
        try:
            self.win.store.clear_all_hidden()
        except OSError:
            self._say("Could not clear the rules.")
            return
        if self.win.active is not None:
            self.win.reapply_hidden(self.win.active)
        self._say("Hidden-element rules cleared.")


def _hex(color):
    """Return a Gdk.RGBA as a #rrggbb text."""
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in (color.red, color.green, color.blue))
