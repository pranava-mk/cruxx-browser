"""Main window: tab strip, stack of WebViews, omnibox and side panels."""

import html
import logging
import os
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, WebKit2  # noqa: E402

from . import (cleanlink, floatvideo, memory, omnibox, reorder, security,  # noqa: E402
               shortcuts, sleep, spaces, store, theme)
from . import passwords as passwords_mod  # noqa: E402
from .addressbar import (FIELD_HEIGHT, FIELD_WIDTH, LIFT, AddressPrompt,  # noqa: E402
                         SwitcherPrompt)
from .sidebar import TabStrip, drop_targets  # noqa: E402
from .tab import Tab, js_call, read_resource, rgba  # noqa: E402
from .wallview import WallView  # noqa: E402
from .widgets import Glyph  # noqa: E402

log = logging.getLogger(__name__)
CLOSED_CAP = 25
STATUS_HIDE_MS = 120
ZOOM_STEP = 0.1
TOAST_MS = 2200
HYPR_DELAY_MS = 300
PEEK_SHARE = 0.8

PERMISSION_KINDS = (
    (WebKit2.GeolocationPermissionRequest, "geolocation"),
    (WebKit2.NotificationPermissionRequest, "notifications"),
    (WebKit2.ClipboardPermissionRequest, "clipboard"),
    (WebKit2.DeviceInfoPermissionRequest, "device info"),
    (WebKit2.MediaKeySystemPermissionRequest, "protected media"),
    (WebKit2.WebsiteDataAccessPermissionRequest, "cross-site cookies"),
)

# Kinds that are never saved. They are too broad to be a clear user choice.
NEVER_REMEMBER = ("this permission", "camera or microphone")

TLS_REASONS = (
    ("UNKNOWN_CA", "The certificate authority is not trusted."),
    ("BAD_IDENTITY", "The certificate is for a different site."),
    ("NOT_ACTIVATED", "The certificate is not valid yet."),
    ("EXPIRED", "The certificate has expired."),
    ("REVOKED", "The certificate was revoked."),
    ("INSECURE", "The certificate uses weak cryptography."),
    ("GENERIC_ERROR", "The certificate has an unspecified error."),
)


def _configure_context(ctx):
    """Harden and tune a WebContext. Sandbox first."""
    memory.apply(WebKit2)
    ctx.set_sandbox_enabled(True)
    ctx.set_process_model(WebKit2.ProcessModel.MULTIPLE_SECONDARY_PROCESSES)
    ctx.set_cache_model(WebKit2.CacheModel.WEB_BROWSER)
    return ctx


def create_persistent_context():
    data = os.path.join(store.data_dir(), "web")
    cache = os.path.join(store.cache_dir(), "web")
    store.make_private_dir(data)
    store.make_private_dir(cache)
    manager = WebKit2.WebsiteDataManager(
        base_data_directory=data, base_cache_directory=cache)
    manager.set_itp_enabled(True)
    cookies = manager.get_cookie_manager()
    cookies.set_accept_policy(WebKit2.CookieAcceptPolicy.NO_THIRD_PARTY)
    cookies.set_persistent_storage(
        os.path.join(data, "cookies.sqlite"), WebKit2.CookiePersistentStorage.SQLITE)
    ctx = WebKit2.WebContext.new_with_website_data_manager(manager)
    _configure_context(ctx)
    if hasattr(ctx, "set_favicon_database_directory"):
        icons = os.path.join(data, "favicons")
        store.make_private_dir(icons)
        ctx.set_favicon_database_directory(icons)
    return ctx


def create_ephemeral_context():
    ctx = _configure_context(WebKit2.WebContext.new_ephemeral())
    manager = ctx.get_website_data_manager()
    manager.set_itp_enabled(True)
    manager.get_cookie_manager().set_accept_policy(
        WebKit2.CookieAcceptPolicy.NO_THIRD_PARTY)
    return ctx


def media_kinds(request):
    """Return the kind names for a user-media request.

    Use the separate camera, microphone and screen kinds. If WebKit has no
    function to tell them apart, return one combined kind that is never saved.
    """
    tests = (("microphone", "user_media_permission_is_for_audio_device"),
             ("camera", "user_media_permission_is_for_video_device"),
             ("screen", "user_media_permission_is_for_display_device"))
    if not all(hasattr(WebKit2, fn) for _name, fn in tests):
        return ["camera or microphone"]
    kinds = [name for name, fn in tests if getattr(WebKit2, fn)(request)]
    return kinds or ["camera or microphone"]


class Panel(Gtk.Revealer):
    """Side panel for history, bookmarks and downloads."""

    def __init__(self, win):
        super().__init__(transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT)
        self.win = win
        self.mode = None
        self._timer = 0
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.get_style_context().add_class("cruxx-panel")
        box.set_size_request(320, -1)
        box.set_border_width(8)
        self.title = Gtk.Label(xalign=0)
        self.search = Gtk.SearchEntry()
        self.search.connect("search-changed", lambda *_: self.populate())
        self.list = Gtk.ListBox()
        self.list.connect("row-activated", self._activated)
        self.list.connect("key-press-event", self._key)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.list)
        self.clear = Gtk.Button(label="Clear history")
        self.clear.connect("clicked", self._clear)
        for widget in (self.title, self.search, scroll, self.clear):
            box.pack_start(widget, widget is scroll, True, 0)
        self.add(box)
        box.show_all()

    def toggle(self, mode):
        if self.get_reveal_child() and self.mode == mode:
            self.close()
            return
        self.mode = mode
        self.title.set_text(mode.capitalize())
        self.clear.set_visible(mode == "history")
        self.search.set_text("")
        self.set_reveal_child(True)
        self.populate()
        self.search.grab_focus()

    def close(self):
        self.set_reveal_child(False)

    def is_open(self):
        return self.get_reveal_child()

    def schedule(self):
        """Refresh a download list at most four times a second."""
        if self.mode == "downloads" and self.is_open() and not self._timer:
            self._timer = GLib.timeout_add(250, self._tick)

    def _tick(self):
        self._timer = 0
        self.populate()
        return False

    def populate(self):
        for child in self.list.get_children():
            child.destroy()
        needle = self.search.get_text().strip().lower()
        if self.mode == "downloads":
            for item in reversed(self.win.downloads):
                if needle in item["name"].lower():
                    self._add_download(item)
        else:
            if self.mode == "history":
                items = sorted(self.win.store.history, key=lambda e: -e["last"])
            else:
                items = self.win.store.bookmarks
            shown = 0
            for entry in items:
                if needle and needle not in (entry["title"] + " " + entry["url"]).lower():
                    continue
                self._add_entry(entry)
                shown += 1
                if shown >= 500:
                    break
        self.list.show_all()

    def _add_entry(self, entry):
        row = Gtk.ListBoxRow()
        row.url = entry["url"]
        label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        label.set_text(entry["title"] or entry["url"])
        label.set_tooltip_text(entry["url"])
        row.add(label)
        self.list.add(row)

    def _add_download(self, item):
        row = Gtk.ListBoxRow()
        row.url = None
        row.item = item
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        label.set_text(item["name"])
        bar = Gtk.ProgressBar()
        bar.set_fraction(1.0 if item["done"] else item["progress"])
        state = "failed" if item["failed"] else "done" if item["done"] else "downloading"
        status = Gtk.Label(xalign=0)
        status.set_text(state)
        status.get_style_context().add_class("error" if item["failed"] else "muted")
        box.pack_start(label, False, False, 0)
        box.pack_start(bar, False, False, 0)
        box.pack_start(status, False, False, 0)
        if item["done"]:
            button = Gtk.Button(label="Open folder")
            button.connect("clicked", lambda *_: self.win.open_folder(item))
            box.pack_start(button, False, False, 0)
        row.add(box)
        self.list.add(row)

    def _activated(self, _list, row):
        if row.url:
            self.win.open_in_current(row.url)

    def _key(self, _list, event):
        if event.keyval != Gdk.KEY_Delete:
            return False
        row = self.list.get_selected_row()
        if row is None:
            return True
        if self.mode == "history":
            self.win.store.remove_history(row.url)
        elif self.mode == "bookmarks":
            self.win.store.remove_bookmark(row.url)
        elif self.mode == "downloads":
            self.win.downloads.remove(row.item)
        self.populate()
        return True

    def _clear(self, _button):
        self.win.store.clear_history()
        self.populate()


class Window(Gtk.ApplicationWindow):
    def __init__(self, app, opts, data):
        super().__init__(application=app, title="cruxx browser")
        self.set_default_size(1200, 800)
        self.opts = opts
        self.store = data
        self.shield = app.shield
        # The tabs live in the spaces. See the properties "tabs" and "active".
        self.spaces = [spaces.Space()]
        self.space_index = 0
        self.closed = []
        self.downloads = []
        self.finished_cb = None
        self.failed_cb = None
        self.side = "left"
        self.strip_visible = True
        self._fullscreen = False
        self._status_src = 0
        self._refresh_src = 0
        self._save_src = 0
        self._provider = None
        # Private tab data. It lives in memory for this window only.
        self.private_paused = set()
        self.private_grants = {}
        self.dragging = None
        self.private_awake = set()
        self.private_zoom = {}
        self._settings_win = None
        self.sleep_override_min = None
        self._external_open = False
        self.peek = None
        self.floats = {}
        self._toast_src = 0
        self.colors = theme.load()
        self._apply_theme()
        self._theme_watcher = theme.Watcher(self._on_theme_changed)
        self.persistent_ctx = create_persistent_context()
        self.ephemeral_ctx = create_ephemeral_context()
        for ctx in (self.persistent_ctx, self.ephemeral_ctx):
            ctx.connect("download-started", self._on_download_started)
        self._build()
        self.connect("key-press-event", self._on_key)
        self.connect("window-state-event", self._on_state)
        self.passwords = passwords_mod.Passwords(self)
        GLib.timeout_add_seconds(sleep.CHECK_SECONDS, self._sleep_timer)

    # spaces: the current space holds the tabs that the strip shows
    @property
    def space(self):
        return self.spaces[self.space_index]

    @property
    def tabs(self):
        return self.space.tabs

    @property
    def active(self):
        return self.space.active

    @active.setter
    def active(self, tab):
        self.space.active = tab

    def all_tabs(self):
        return [tab for space in self.spaces for tab in space.tabs]

    def visible_tabs(self):
        """Return the tabs that show now. A split pair gives two tabs."""
        return spaces.visible_tabs(self.space)

    # construction
    def _build(self):
        # The settings button replaces the old toolbar menu.
        self.menu_button = Gtk.MenuButton()
        self.menu_button.set_relief(Gtk.ReliefStyle.NONE)
        self.menu_button.get_style_context().add_class("cruxx-door")
        self.menu_button.add(Glyph("sliders", 26, 11, 1.3))
        self.menu_button.set_tooltip_text("Menu")
        self._build_menu()
        self.strip = TabStrip(self, self.menu_button)
        self.prompt = AddressPrompt(self)
        self.switcher = SwitcherPrompt(self)

        self.bars = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.stack = Gtk.Stack()
        # A floated tab leaves an empty page. This note shows in its place.
        self.float_hint = Gtk.Label(
            label="The video is floating. Press Ctrl+Shift+P to bring it back.")
        self.float_hint.get_style_context().add_class("muted")
        self.float_hint.show()
        self.stack.add_named(self.float_hint, "floating")
        self.panel = Panel(self)
        # Floating things lie over the page, in this order from the bottom.
        self.overlay = Gtk.Overlay()
        self.overlay.add(self.stack)
        # The wall lies over a blank tab. A click goes through to the page.
        self.wall = WallView()
        self.wall.on_kind_change = self._sync_wall
        self.toast_label = Gtk.Label()
        self.toast_label.get_style_context().add_class("cruxx-status")
        self.toast_label.set_halign(Gtk.Align.CENTER)
        self.toast_label.set_valign(Gtk.Align.END)
        self.toast_label.set_margin_bottom(48)
        self._build_peek()
        self.scrim = Gtk.EventBox()
        self.scrim.set_visible_window(True)
        self.scrim.get_style_context().add_class("cruxx-scrim")
        self.scrim.connect("button-press-event", lambda *_: self.hide_prompts() or True)
        # While a tab is dragged, this zone lies over the page. A drop splits.
        self.dropzone = Gtk.EventBox()
        self.dropzone.set_visible_window(True)
        self.dropzone.get_style_context().add_class("cruxx-dropzone")
        self.dropzone.drag_dest_set(0, drop_targets(), Gdk.DragAction.MOVE)
        self.dropzone.connect("drag-motion", self._on_zone_motion)
        self.dropzone.connect("drag-drop", self._on_zone_drop)
        self.status = Gtk.Label(ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.status.get_style_context().add_class("cruxx-status")
        self.status.set_halign(Gtk.Align.START)
        self.status.set_valign(Gtk.Align.END)
        self.status.set_margin_start(10)
        self.status.set_margin_end(10)
        self.status.set_margin_bottom(10)
        self.find_bar = self._build_find_bar()
        for widget in (self.wall, self.scrim, self.dropzone, self.status, self.find_bar,
                       self.peek_layer, self.toast_label,
                       self.prompt.card, self.switcher.card):
            widget.set_no_show_all(True)
            widget.hide()
            self.overlay.add_overlay(widget)
        for widget in (self.wall, self.status, self.toast_label):
            self.overlay.set_overlay_pass_through(widget, True)
        self.overlay.connect("size-allocate", self._size_peek)
        self.overlay.connect("get-child-position", self._place_child)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.pack_start(self.strip.top, False, False, 0)
        right.pack_start(self.bars, False, False, 0)
        right.pack_start(self.overlay, True, True, 0)
        root = Gtk.Box()
        root.pack_start(self.strip.left, False, False, 0)
        root.pack_start(right, True, True, 0)
        root.pack_start(self.panel, False, False, 0)
        self.add(root)
        root.show_all()
        self._layout()
        self.apply_wall()

    def _place_child(self, overlay, widget, rect):
        """Put a prompt card in the middle of the page, a little high."""
        if widget not in (self.prompt.card, self.switcher.card):
            return False
        area = overlay.get_allocation()
        width = min(FIELD_WIDTH, max(200, area.width - 28))
        rect.x = (area.width - width) // 2
        rect.y = max(16, (area.height - FIELD_HEIGHT) // 2 - LIFT)
        rect.width = width
        rect.height = widget.get_preferred_height_for_width(width)[1]
        return True

    def _build_menu(self):
        menu = Gtk.Menu()
        settings_item = Gtk.MenuItem(label="Settings\u2026")
        settings_item.connect("activate", lambda *_: self.open_settings())
        self.pause_item = Gtk.CheckMenuItem(label="Pause shield on this site")
        self.pause_item.connect("toggled", self._on_pause_toggled)
        self.popup_item = Gtk.MenuItem(label="Blocked popups: 0")
        self.popup_item.set_sensitive(False)
        reader = Gtk.MenuItem(label="Reading mode")
        reader.connect("activate", lambda *_: self.toggle_reader())
        hide = Gtk.MenuItem(label="Hide element")
        hide.connect("activate", lambda *_: self.start_hide())
        unhide = Gtk.MenuItem(label="Hidden elements on this site\u2026")
        unhide.connect("activate", lambda *_: self.open_hidden_list())
        origin = Gtk.MenuItem(label="Reload from origin (Ctrl+Alt+R)")
        origin.connect("activate", lambda *_: self._reload_origin())
        self.awake_item = Gtk.CheckMenuItem(label="Keep This Site Awake")
        self.awake_item.set_no_show_all(True)
        self.awake_item.connect("toggled", self._on_awake_toggled)
        self.split_item = Gtk.MenuItem(label="Split current page (Ctrl+Alt+N)")
        self.split_item.set_no_show_all(True)
        self.split_item.connect("activate", lambda *_: self.split_current())
        self.unsplit_item = Gtk.MenuItem(label="Separate split tabs")
        self.unsplit_item.set_no_show_all(True)
        self.unsplit_item.connect("activate", lambda *_: self.unsplit_active())
        space_item = Gtk.MenuItem(label="New space")
        space_item.connect("activate", lambda *_: self.new_space())
        for item in (settings_item, Gtk.SeparatorMenuItem(), self.pause_item, reader,
                     hide, unhide, origin, self.awake_item, self.split_item,
                     self.unsplit_item, space_item, self.popup_item):
            menu.append(item)
        menu.show_all()
        menu.connect("show", self._on_menu_show)
        self.menu_button.set_popup(menu)
        self._menu_updating = False

    def _on_menu_show(self, *_args):
        tab = self.active
        self._menu_updating = True
        paused = bool(tab and (
            self.store.shield_paused(tab.host)
            or (tab.private and store.registrable_host(tab.host) in self.private_paused)))
        self.pause_item.set_active(paused)
        enabled = self.store.settings["keep_awake_enabled"]
        self.awake_item.set_visible(enabled)
        self.awake_item.set_sensitive(bool(tab and tab.host))
        self.awake_item.set_active(bool(tab and self.is_kept_awake(tab)))
        split_on = self.split_on()
        self.split_item.set_visible(split_on)
        self.unsplit_item.set_visible(split_on)
        self.unsplit_item.set_sensitive(bool(tab and self.split_of(tab)))
        self._menu_updating = False
        self.popup_item.set_label("Blocked popups: %d" % (tab.blocked_popups if tab else 0))

    def _on_pause_toggled(self, item):
        tab = self.active
        if self._menu_updating or tab is None or not tab.host:
            return
        self.set_site_shield(tab, item.get_active())

    def site_paused(self, tab):
        """Return True if the shield is paused for the site of TAB."""
        return bool(tab and tab.host and (
            self.store.shield_paused(tab.host)
            or (tab.private and store.registrable_host(tab.host) in self.private_paused)))

    def set_site_shield(self, tab, paused, reload=True):
        if tab is None or not tab.host:
            return
        if tab.private:
            # A private tab must not write to settings.json.
            site = store.registrable_host(tab.host)
            if paused:
                self.private_paused.add(site)
            else:
                self.private_paused.discard(site)
        else:
            try:
                self.store.set_shield_paused(tab.host, paused)
            except OSError as exc:
                log.warning("shield pause save failed: %s", exc)
        tab.tune_shield(tab.host)
        if reload and tab.view is not None:
            tab.view.reload()

    # settings that the settings window changes. They apply at once.
    def set_option(self, key, value):
        """Save one setting and apply it. Return False if it was not saved."""
        try:
            self.store.set_option(key, value)
        except (ValueError, OSError) as exc:
            log.warning("setting not saved: %s", exc)
            return False
        if key == "shield_enabled":
            for tab in self.all_tabs():
                if tab.view is not None:
                    tab.tune_shield(tab.host)
            if self.active is not None and self.active.view is not None:
                self.active.view.reload()
        elif key == "split_enabled":
            if not value:
                for space in self.spaces:
                    for split in list(space.splits):
                        self._drop_split(split)
                if self.active is not None:
                    self._show(self.active)
                self.refresh()
                self.schedule_save()
        elif key == "keep_awake_enabled":
            self.refresh()
        elif key == "wall":
            self.apply_wall()
        return True

    def set_side(self, side):
        if side in ("left", "top") and side != self.side:
            self.side = side
            self._layout()
            self.schedule_save()

    # settings window, site card, hidden list
    def open_settings(self, section=None):
        from .settingswin import SettingsWindow
        if getattr(self, "_settings_win", None) is None:
            self._settings_win = SettingsWindow(self)
            self._settings_win.connect(
                "destroy", lambda *_: setattr(self, "_settings_win", None))
        self._settings_win.show_section(section)

    def open_passwords(self):
        self.passwords.open_panel()

    def _popover_anchor(self, tab):
        widget = self.strip.items.get(tab)
        if widget is None or not widget.get_mapped():
            widget = self.overlay
        return widget

    def open_site_card(self, tab=None):
        from .sitecard import SiteCard
        tab = tab or self.active
        if tab is None or not tab.url:
            return
        SiteCard(self, tab, self._popover_anchor(tab)).popup()

    def open_hidden_list(self, tab=None):
        from .sitecard import HiddenList
        tab = tab or self.active
        if tab is None or not tab.host:
            return
        HiddenList(self, tab, self._popover_anchor(tab)).popup()

    def reapply_hidden(self, tab):
        """Rebuild the hidden-element scripts. Reload the tab to show the change."""
        for other in self.all_tabs():
            other.update_hidden_script()
        if tab.view is not None:
            tab.view.reload()

    # website data (cookies, storage, caches)
    def _all_types(self):
        types = 0
        for name in dir(WebKit2.WebsiteDataTypes):
            if name.isupper() and isinstance(getattr(WebKit2.WebsiteDataTypes, name), int):
                types |= int(getattr(WebKit2.WebsiteDataTypes, name))
        return WebKit2.WebsiteDataTypes(types)

    def clear_website_data(self, done=None):
        """Remove all website data of the normal profile."""
        manager = self.persistent_ctx.get_website_data_manager()

        def finished(_m, result):
            try:
                manager.clear_finish(result)
                ok = True
            except GLib.Error as exc:
                log.warning("clear data failed: %s", exc.message)
                ok = False
            if done:
                done(ok)

        manager.clear(self._all_types(), 0, None, finished)

    def clear_site_data(self, host, done=None):
        """Remove the website data records of HOST only."""
        manager = self.persistent_ctx.get_website_data_manager()
        types = self._all_types()

        def removed(_m, result):
            try:
                manager.remove_finish(result)
                ok = True
            except GLib.Error as exc:
                log.warning("remove data failed: %s", exc.message)
                ok = False
            if done:
                done(ok)

        def fetched(_m, result):
            try:
                records = manager.fetch_finish(result)
            except GLib.Error as exc:
                log.warning("fetch data failed: %s", exc.message)
                if done:
                    done(False)
                return
            mine = [r for r in records if store.data_matches(r.get_name(), host)]
            # WebKit can name a record by the registrable domain. Delete the
            # cookies of this exact host in a separate step.
            self._clear_host_cookies(host)
            if not mine:
                if done:
                    done(True)
                return
            manager.remove(types, mine, None, removed)

        manager.fetch(types, None, fetched)

    def _clear_host_cookies(self, host):
        """Delete the cookies of HOST only. Keep parent domain cookies."""
        manager = self.persistent_ctx.get_website_data_manager()
        cookies = manager.get_cookie_manager()

        def got(_m, result, uri):
            try:
                found = cookies.get_cookies_finish(result)
            except GLib.Error as exc:
                log.warning("read cookies failed: %s", exc.message)
                return
            for cookie in found:
                if store.data_matches(cookie.get_domain(), host):
                    cookies.delete_cookie(cookie, None, lambda *_a: None)

        for scheme in ("https", "http"):
            uri = "%s://%s/" % (scheme, host)
            cookies.get_cookies(uri, None, got, uri)

    # zoom. The level is saved for each host.
    def apply_zoom(self, tab):
        if tab.view is None or not tab.host:
            return
        tab.view.set_zoom_level(self.zoom_level_for(tab))

    def zoom_level_for(self, tab):
        site = store.registrable_host(tab.host)
        if tab.private:
            return self.private_zoom.get(site, self.store.zoom_for(tab.host))
        return self.store.zoom_for(tab.host)

    def set_zoom_level(self, tab, level):
        level = store.clean_zoom(level)
        if tab.view is None or level is None:
            return
        tab.view.set_zoom_level(level)
        if not tab.host:
            return
        if tab.private:
            self.private_zoom[store.registrable_host(tab.host)] = level
            return
        try:
            self.store.set_zoom(tab.host, level)
        except OSError as exc:
            log.warning("zoom save failed: %s", exc)

    def _build_find_bar(self):
        bar = Gtk.Box(spacing=6)
        bar.get_style_context().add_class("cruxx-find")
        bar.set_halign(Gtk.Align.END)
        bar.set_valign(Gtk.Align.START)
        bar.set_margin_top(12)
        bar.set_margin_end(14)
        self.find_entry = Gtk.Entry()
        self.find_entry.set_has_frame(False)
        self.find_entry.set_placeholder_text("Find on page")
        self.find_entry.set_size_request(150, -1)
        self.find_entry.set_valign(Gtk.Align.CENTER)
        self.find_entry.connect("changed", self._on_find_changed)
        self.find_entry.connect("activate", lambda *_: self._find_step(False))
        self.find_entry.connect("key-press-event", self._on_find_key)
        self.find_count = Gtk.Label()
        self.find_count.get_style_context().add_class("cruxx-count")
        bar.pack_start(self.find_entry, False, False, 0)
        bar.pack_start(self.find_count, False, False, 0)
        for kind, action in (("up", lambda *_: self._find_step(True)),
                             ("down", lambda *_: self._find_step(False)),
                             ("close", lambda *_: self.close_find())):
            button = Gtk.Button()
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.add(Glyph(kind, 24, 7 if kind == "close" else 8, 1.4))
            button.connect("clicked", action)
            bar.pack_start(button, False, False, 0)
        bar.show_all()
        return bar

    # theme
    def _apply_theme(self):
        screen = Gdk.Screen.get_default()
        provider = Gtk.CssProvider()
        try:
            provider.load_from_data(theme.css(self.colors).encode("utf-8"))
        except GLib.Error as exc:
            log.warning("theme CSS rejected: %s", exc.message)
            return
        if self._provider is not None:
            Gtk.StyleContext.remove_provider_for_screen(screen, self._provider)
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._provider = provider
        Gtk.Settings.get_default().set_property(
            "gtk-application-prefer-dark-theme", self.colors["mode"] == "dark")

    def _on_theme_changed(self):
        self.colors = theme.load()
        self._apply_theme()
        for tab in self.all_tabs():
            if tab.view is not None:
                tab.view.set_background_color(rgba(self.colors["background"]))
        # The Omarchy wallpaper can change with the theme.
        self.apply_wall()

    # contexts and views
    def context(self, private):
        return self.ephemeral_ctx if private else self.persistent_ctx

    def add_view(self, tab):
        tab.view.show()
        tab.view.connect("focus-in-event", self._on_view_focus, tab)
        self._place(tab)

    def _place(self, tab):
        """Put the view of TAB where it belongs: a pane of its pair, or the stack."""
        view = tab.view
        if tab.floating:
            return
        split = self.split_of(tab)
        if split is not None and split.panes is not None:
            holder = split.panes[0 if tab is split.a else 1]
        else:
            holder = self.stack
        parent = view.get_parent()
        if parent is holder:
            return
        if parent is not None:
            parent.remove(view)
        if holder is self.stack:
            holder.add_named(view, str(id(tab)))
        else:
            holder.pack_start(view, True, True, 0)

    def _destroy_view(self, tab):
        self.passwords.tab_gone(tab)
        self._release_float(tab)
        view = tab.view
        if view is not None:
            parent = view.get_parent()
            if parent is not None:
                parent.remove(view)
            view.destroy()
            tab.view = None

    def _show(self, tab):
        """Show TAB. If it is in a pair, show the pair. TAB is the focused pane."""
        tab.ensure_view()
        if tab.floating:
            self.stack.set_visible_child(self.float_hint)
            return
        split = self.split_of(tab)
        if split is None:
            self._place(tab)
            self.stack.set_visible_child(tab.view)
            return
        split.other(tab).ensure_view()
        self._build_pair(split)
        self.stack.set_visible_child(split.widget)
        self._mark_focus(split)

    def _build_pair(self, split):
        if split.widget is None:
            split.panes = []
            paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
            paned.set_wide_handle(True)
            paned.get_style_context().add_class("cruxx-split")
            for index in range(2):
                pane = Gtk.Box()
                pane.get_style_context().add_class("cruxx-pane")
                pane.show()
                split.panes.append(pane)
                (paned.pack1 if index == 0 else paned.pack2)(pane, True, False)
            split.widget = paned
            split.sized = False
            paned.connect("size-allocate", self._on_pair_allocate, split)
            paned.connect("notify::position", self._on_pair_moved, split)
            paned.show()
            self.stack.add_named(paned, "split-%d" % id(split))
        self._place(split.a)
        self._place(split.b)

    def _mark_focus(self, split):
        """Draw the outline on the pane of the active tab only."""
        for pane, tab in zip(split.panes, (split.a, split.b)):
            context = pane.get_style_context()
            (context.add_class if tab is self.active else context.remove_class)("focus")

    def _on_pair_allocate(self, paned, alloc, split):
        """Set the divider from the saved ratio, once, when the width is known."""
        if split.sized or alloc.width < 40 or getattr(split, "pending", False):
            return
        split.pending = True

        def apply():
            split.pending = False
            if split.widget is paned:
                paned.set_position(int(paned.get_allocated_width() * split.ratio))
                split.sized = True
            return False

        GLib.idle_add(apply)

    def _on_pair_moved(self, paned, _pspec, split):
        width = paned.get_allocated_width()
        if split.sized and width > 40:
            split.ratio = spaces.clamp_ratio(paned.get_position() / width)
            self.schedule_save()

    def _on_view_focus(self, _view, _event, tab):
        """A click in a pane gives it the focus."""
        split = self.split_of(tab)
        if split is not None and tab is not self.active and self.active in (split.a, split.b):
            self.select_tab(tab)
        return False

    # split view
    def split_on(self):
        return bool(self.store.settings["split_enabled"])

    def split_of(self, tab):
        for space in self.spaces:
            split = spaces.find_split(space.splits, tab)
            if split is not None:
                return split
        return None

    def pair_state(self, tab):
        return "pair" if self.split_of(tab) is not None else ""

    def _drop_split(self, split):
        """Remove the pair. The views go back to the stack. The tabs stay."""
        for space in self.spaces:
            if split in space.splits:
                space.splits.remove(split)
        for tab in (split.a, split.b):
            if tab.view is not None:
                self._place(tab)
        if split.widget is not None:
            self.stack.remove(split.widget)
            split.widget.destroy()
            split.widget = None
            split.panes = None

    def split_current(self):
        """Pair the current tab with the next free tab, or with a new blank tab."""
        tab = self.active
        if (not self.split_on() or tab is None or tab.pinned or self.split_of(tab)
                or tab.floating):
            return
        partner = spaces.choose_partner(self.tabs, tab, self.space.splits)
        fresh = partner is None
        if fresh:
            partner = self.open_tab(private=tab.private, background=True)
        self._pair(tab, partner)
        if fresh:
            self.focus_omnibox()

    def split_with(self, other):
        """Pair the current tab with OTHER (a tab that the user dropped)."""
        tab = self.active
        if (not self.split_on() or tab is None or other is None or other is tab
                or other not in self.tabs or tab.pinned or other.pinned
                or self.split_of(tab) or tab.floating or other.floating):
            return
        old = self.split_of(other)
        if old is not None:
            self._drop_split(old)
        self._pair(tab, other)

    def _pair(self, first, second):
        self.space.splits.append(spaces.Split(first, second))
        spaces.regroup(self.tabs, self.space.splits)
        self.select_tab(second)

    def unsplit_active(self):
        split = self.split_of(self.active) if self.active else None
        if split is None:
            return
        self._drop_split(split)
        self._show(self.active)
        if self.active.view is not None:
            self.active.view.grab_focus()
        self.refresh()
        self.schedule_save()

    def focus_pane(self, delta):
        split = self.split_of(self.active) if self.active else None
        if split is not None:
            target = split.a if delta < 0 else split.b
            if target is not self.active:
                self.select_tab(target)

    def _on_zone_motion(self, _zone, ctx, _x, _y, stamp):
        if self.dragging is None:
            return False
        Gdk.drag_status(ctx, Gdk.DragAction.MOVE, stamp)
        return True

    def _on_zone_drop(self, _zone, ctx, _x, _y, stamp):
        tab = self.dragging
        if tab is None:
            return False
        self.drag_end()
        Gtk.drag_finish(ctx, True, False, stamp)
        self.split_with(tab)
        return True

    # spaces
    def switch_space(self, index):
        if index == self.space_index or not 0 <= index < len(self.spaces):
            return
        self.close_find()
        self.hide_prompts(refocus=False)
        now = time.monotonic()
        for tab in self.visible_tabs():
            tab.last_active = now
        self.space_index = index
        space = self.space
        if not space.tabs:
            self.open_tab()
        else:
            self.select_tab(space.active if space.active in space.tabs else space.tabs[0])
        self.refresh()
        self.schedule_save()

    def cycle_space(self, delta):
        self.switch_space(spaces.step(self.space_index, len(self.spaces), delta))

    def new_space(self):
        if len(self.spaces) >= spaces.MAX_SPACES:
            return
        self.spaces.append(spaces.Space(spaces.next_name(self.spaces)))
        self.switch_space(len(self.spaces) - 1)

    def rename_space(self, index):
        """Ask for a name and an icon (a letter or an emoji) in a small popover."""
        bar = self.strip.spacebar
        if not 0 <= index < len(self.spaces) or index >= len(bar.dots):
            return
        space = self.spaces[index]
        popover = Gtk.Popover.new(bar.dots[index])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(6)
        name = Gtk.Entry()
        name.set_max_length(spaces.NAME_MAX)
        name.set_text(space.name)
        name.set_placeholder_text("Name")
        icon = Gtk.Entry()
        icon.set_max_length(12)
        icon.set_text(space.icon)
        icon.set_placeholder_text("Icon: a letter or an emoji")
        state = {"save": False}

        def activate(*_):
            state["save"] = True
            popover.popdown()

        def closed(*_):
            if state["save"]:
                space.name = spaces.clean_name(name.get_text(), space.name)
                space.icon = spaces.clean_icon(icon.get_text(), space.name)
                self.refresh()
                self.schedule_save()
            GLib.idle_add(popover.destroy)

        for entry in (name, icon):
            entry.connect("activate", activate)
            box.pack_start(entry, False, False, 0)
        popover.connect("closed", closed)
        popover.add(box)
        box.show_all()
        popover.popup()
        name.grab_focus()

    def delete_space(self, index):
        if len(self.spaces) <= 1 or not 0 <= index < len(self.spaces):
            return
        space = self.spaces[index]
        if space.tabs:
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO, text="Delete this space?")
            dialog.set_property("secondary-text", "The space \"%s\" and its %d tab%s will close." % (
                space.name, len(space.tabs), "" if len(space.tabs) == 1 else "s"))
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.YES:
                return
        for split in list(space.splits):
            self._drop_split(split)
        for tab in list(space.tabs):
            self.clear_permission_bars(tab)
            self._destroy_view(tab)
        was_current = index == self.space_index
        self.space_index = spaces.remove_space(self.spaces, index, self.space_index)
        if was_current:
            now = self.space
            if now.tabs:
                self.select_tab(now.active if now.active in now.tabs else now.tabs[0])
            else:
                self.open_tab()
        self.refresh()
        self.schedule_save()

    def space_menu(self, index, event, widget):
        menu = Gtk.Menu()
        rename = Gtk.MenuItem(label="Rename space")
        rename.connect("activate", lambda *_: self.rename_space(index))
        delete = Gtk.MenuItem(label="Delete space")
        delete.set_sensitive(len(self.spaces) > 1)
        delete.connect("activate", lambda *_: self.delete_space(index))
        new = Gtk.MenuItem(label="New space")
        new.set_sensitive(len(self.spaces) < spaces.MAX_SPACES)
        new.connect("activate", lambda *_: self.new_space())
        for item in (rename, delete, new):
            menu.append(item)
        menu.show_all()
        menu.attach_to_widget(widget, None)
        menu.connect("selection-done", lambda m: GLib.idle_add(m.destroy))
        menu.popup_at_pointer(event)

    # wall behind a blank tab
    def apply_wall(self):
        """Read the wall setting. Load its picture once. Show or hide it."""
        spec = self.store.settings["wall"]
        kind = self.wall.configure(
            spec, os.path.join(theme.state_dir(), "background"),
            self.colors["background"])
        if kind != spec["kind"]:
            log.warning("wall falls back to off")
        self._sync_wall()

    def _sync_wall(self):
        """Show the wall only over a blank tab that is not in a pair."""
        tab = self.active
        blank = (tab is not None and not tab.floating
                 and tab.url in ("", "about:blank") and self.split_of(tab) is None)
        want = bool(blank and self.wall.kind != "off")
        if want != self.wall.get_visible():
            self.wall.set_visible(want)

    # toast
    def toast(self, text):
        """Show a short note over the page for a moment."""
        self.toast_label.set_text(text)
        self.toast_label.show()
        if self._toast_src:
            GLib.source_remove(self._toast_src)
        self._toast_src = GLib.timeout_add(TOAST_MS, self._hide_toast)

    def _hide_toast(self):
        self._toast_src = 0
        self.toast_label.hide()
        return False

    # peek: a link in a floating card
    def _build_peek(self):
        self.peek_layer = Gtk.EventBox()
        self.peek_layer.set_visible_window(True)
        self.peek_layer.get_style_context().add_class("cruxx-scrim")
        self.peek_layer.connect("button-press-event", self._on_peek_press)
        self.peek_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.peek_card.set_halign(Gtk.Align.CENTER)
        self.peek_card.set_valign(Gtk.Align.CENTER)
        context = self.peek_card.get_style_context()
        context.add_class("cruxx-card")
        context.add_class("cruxx-peek")
        head = Gtk.Box(spacing=8)
        head.get_style_context().add_class("cruxx-peek-head")
        self.peek_host = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.peek_host.get_style_context().add_class("cruxx-title")
        open_button = Gtk.Button(label="Open as tab")
        open_button.set_relief(Gtk.ReliefStyle.NONE)
        open_button.get_style_context().add_class("cruxx-action")
        open_button.connect("clicked", lambda *_: self.adopt_peek())
        close_button = Gtk.Button()
        close_button.set_relief(Gtk.ReliefStyle.NONE)
        close_button.add(Glyph("close", 24, 7, 1.4))
        close_button.set_tooltip_text("Close (Esc)")
        close_button.connect("clicked", lambda *_: self.close_peek())
        head.pack_start(self.peek_host, True, True, 0)
        head.pack_end(close_button, False, False, 0)
        head.pack_end(open_button, False, False, 0)
        # GTK CSS cannot clip a child to round corners. A margin keeps the page
        # away from the corners of the card.
        self.peek_body = Gtk.Box()
        self.peek_body.set_margin_start(8)
        self.peek_body.set_margin_end(8)
        self.peek_body.set_margin_bottom(8)
        self.peek_card.pack_start(head, False, False, 0)
        self.peek_card.pack_start(self.peek_body, True, True, 0)
        self.peek_layer.add(self.peek_card)
        self.peek_card.show_all()

    def _size_peek(self, overlay, alloc):
        self.peek_card.set_size_request(int(alloc.width * PEEK_SHARE),
                                        int(alloc.height * PEEK_SHARE))

    def _on_peek_press(self, _layer, event):
        """A click on the dim area, outside the card, closes the peek."""
        if event.window is self.peek_layer.get_window():
            box = self.peek_card.get_allocation()
            inside = (box.x <= event.x < box.x + box.width
                      and box.y <= event.y < box.y + box.height)
            if not inside:
                self.close_peek()
        return True

    def _set_peek_head(self, tab):
        self.peek_host.set_text(tab.host or tab.url or "")
        self.peek_host.set_tooltip_text(security.display_uri(tab.url, 200))

    def open_peek(self, source, uri):
        """Show URI in a card over the page of SOURCE. One card at a time."""
        if source is not self.active or source.view is None:
            return False
        self.close_peek(refocus=False)
        self.close_find()
        self.hide_prompts(refocus=False)
        # Same private rule as the source tab: the context and rules come from Tab.
        peek = Tab(self, "", private=source.private, peek=True)
        peek.load(uri, clean=True)
        if peek.view is None:
            return False
        self.peek = peek
        self._set_peek_head(peek)
        self.peek_layer.show()
        peek.view.grab_focus()
        return False

    def add_peek_view(self, tab):
        tab.view.show()
        # Keep the handler id: adopt_peek disconnects it.
        tab.peek_close_id = tab.view.connect(
            "close", lambda *_: self.peek is tab and self.close_peek())
        self.peek_body.pack_start(tab.view, True, True, 0)

    def close_peek(self, refocus=True):
        """Close the card. Destroy its WebView."""
        tab = self.peek
        if tab is None:
            return
        self.peek = None
        self.peek_layer.hide()
        self._destroy_view(tab)
        if refocus and self.active is not None and self.active.view is not None:
            self.active.view.grab_focus()

    def adopt_peek(self):
        """Move the page of the card into a new tab. The page does not reload."""
        tab = self.peek
        if tab is None or tab.view is None:
            return
        self.peek = None
        self.peek_layer.hide()
        tab.peek = False
        handler = getattr(tab, "peek_close_id", 0)
        if handler:
            tab.view.disconnect(handler)
            tab.peek_close_id = 0
        tab.stored_url = tab.view.get_uri() or tab.stored_url
        tab.view.connect("focus-in-event", self._on_view_focus, tab)
        self.tabs.append(tab)
        self._sort_tabs()
        self.select_tab(tab)

    # video float: the WebView of a tab moves into a small window
    def toggle_float(self):
        tab = self.active
        if tab is None:
            return
        if tab.floating:
            self.unfloat(tab)
            return
        view = tab.view
        if view is None or not tab.url or self.split_of(tab) is not None:
            self.toast("No video on this page")
            return

        def found(_view, result, _data=None):
            try:
                value = view.run_javascript_in_world_finish(result).get_js_value()
                ok = value.to_boolean()
            except GLib.Error as exc:
                log.debug("video search failed: %s", exc.message)
                ok = False
            if tab.view is not view or tab.floating:
                return
            if ok:
                self._start_float(tab)
            else:
                self.toast("No video on this page")

        view.run_javascript_in_world(read_resource("float-find.js"), "cruxx", None, found, None)

    def _start_float(self, tab):
        view = tab.view
        token = floatvideo.new_token()
        win = Gtk.Window(title=floatvideo.title_for(token))
        win.token = token
        win.set_default_size(floatvideo.FLOAT_W, floatvideo.FLOAT_H)
        win.set_keep_above(True)
        win.connect("delete-event", lambda *_: self.unfloat(tab) or True)
        win.connect("key-press-event", self._on_float_key, tab)
        parent = view.get_parent()
        if parent is not None:
            parent.remove(view)
        win.add(view)
        tab.floating = True
        self.floats[tab] = win
        view.show()
        win.show()
        tab.run_in_world(read_resource("float-on.js"))
        if tab is self.active:
            self._show(tab)
        self.refresh()
        self._float_on_desktop(token)

    def _on_float_key(self, _win, event, tab):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        both = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        name = Gdk.keyval_name(Gdk.keyval_to_lower(event.keyval)) or ""
        if state == both and name == "p":
            GLib.idle_add(self.unfloat, tab)
            return True
        return False

    def _release_float(self, tab):
        """Take the WebView out of its float window. Close that window."""
        win = self.floats.pop(tab, None)
        if win is None:
            return False
        tab.floating = False
        view = tab.view
        if view is not None:
            tab.run_in_world(read_resource("float-off.js"))
            if view.get_parent() is win:
                win.remove(view)
        win.destroy()
        return True

    def unfloat(self, tab):
        """Put the WebView back in its tab. Remove the float style."""
        if not self._release_float(tab):
            return False
        if tab.view is not None:
            self._place(tab)
            if tab is self.active:
                self._show(tab)
                tab.view.grab_focus()
        self.refresh()
        return False

    # Hyprland: float, size, move and pin the window. Only when Hyprland runs.
    def _float_on_desktop(self, token):
        if not (os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
                and GLib.find_program_in_path("hyprctl")):
            return

        def start():
            self._spawn(["hyprctl", "monitors", "-j"], lambda ok, out: self._place_float(
                token, floatvideo.corner_position(out) if ok else None))
            return False

        GLib.timeout_add(HYPR_DELAY_MS, start)

    def _place_float(self, token, corner):
        x, y = corner if corner else (None, None)
        self._hypr_chain(floatvideo.steps(token, x, y))

    def _hypr_chain(self, items):
        """Run each step. If the Lua call fails, run the older name."""
        if not items:
            return
        lua, legacy = items[0]

        def after_lua(ok, _out):
            if ok:
                self._hypr_chain(items[1:])
                return

            def after_legacy(ok2, _out2):
                if not ok2:
                    log.debug("hyprctl step failed")
                self._hypr_chain(items[1:])

            self._spawn(floatvideo.argv(*legacy), after_legacy)

        self._spawn(floatvideo.argv(lua), after_lua)

    def _spawn(self, argv, done):
        """Run ARGV (a list, never a shell). Call DONE(ok, stdout) at the end."""
        try:
            proc = Gio.Subprocess.new(
                argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error as exc:
            log.debug("spawn failed: %s", exc.message)
            done(False, "")
            return

        def finished(_proc, result):
            try:
                _ok, out, _err = proc.communicate_utf8_finish(result)
            except GLib.Error as exc:
                log.debug("spawn read failed: %s", exc.message)
                done(False, "")
                return
            out = out or ""
            good = proc.get_successful() and (argv[1:2] != ["dispatch"] or out.strip() == "ok")
            done(good, out)

        proc.communicate_utf8_async(None, None, finished)

    # layout
    def _layout(self):
        self.strip.set_mode(self.side)
        self.strip.set_visible(self.strip_visible)
        self.refresh()

    def toggle_side(self):
        self.side = "top" if self.side == "left" else "left"
        self._layout()
        self.schedule_save()

    def toggle_strip(self):
        self.strip_visible = not self.strip_visible
        self._layout()

    def set_page_fullscreen(self, on):
        if on:
            self.fullscreen()
        else:
            self.unfullscreen()

    def _on_state(self, _w, event):
        self._fullscreen = bool(event.new_window_state & Gdk.WindowState.FULLSCREEN)

    # strip
    def refresh(self):
        """Match the strip to the tab list. Do it once in an idle call."""
        if not self._refresh_src:
            self._refresh_src = GLib.idle_add(self._do_refresh)

    def _do_refresh(self):
        self._refresh_src = 0
        self._sync_strip()
        return False

    def _sync_strip(self):
        self.strip.sync(self.tabs, self.active)
        self.strip.spacebar.sync(self.spaces, self.space_index)
        self._set_title()

    def _set_title(self):
        self.set_title(((self.active.title + " - ") if self.active else "") + "cruxx browser")

    def icon_for(self, url):
        """Return a favicon of an open tab on the same host, or None."""
        host = store.host_of(url)
        for tab in self.tabs:
            if tab.favicon is not None and host and tab.host == host:
                return tab.favicon
        return None

    # tab operations
    def _sort_tabs(self):
        self.tabs.sort(key=lambda t: not t.pinned)
        spaces.regroup(self.tabs, self.space.splits)

    def open_tab(self, url="", private=False, background=False, title="", pinned=False,
                 clean=False):
        """Open a tab. If CLEAN is true, the user chose URL: drop tracking parameters."""
        if clean and url:
            url = cleanlink.clean_link(url)
        tab = Tab(self, url, title, pinned, private)
        self.tabs.append(tab)
        self._sort_tabs()
        if background:
            self.refresh()
            self.schedule_save()
        else:
            self.select_tab(tab)
            if not url:
                self.focus_omnibox()
        return tab

    def open_in_current(self, url, clean=False):
        if self.active is None:
            self.open_tab(url, clean=clean)
        else:
            self.active.load(url, clean=clean)

    def select_tab(self, tab):
        if tab not in self.tabs:
            return
        self.close_find()
        self.close_peek(refocus=False)
        self.hide_prompts(refocus=False)
        self._hide_status()
        now = time.monotonic()
        if self.active is not None:
            self.active.last_active = now
        tab.last_active = now
        self.active = tab
        if not tab.private:
            self.space.last_normal = self.tabs.index(tab)
        self._show(tab)
        self._sync_bars()
        self._sync_strip()
        self._sync_wall()
        self.schedule_save()
        if tab.url:
            tab.view.grab_focus()

    def close_tab(self, tab):
        if tab not in self.tabs:
            return
        index = self.tabs.index(tab)
        if not tab.private and tab.url:
            self.closed.append({"url": tab.url, "title": tab.title, "pinned": tab.pinned})
            del self.closed[:-CLOSED_CAP]
        self.clear_permission_bars(tab)
        # The other pane of a pair takes the whole area.
        split = self.split_of(tab)
        partner = split.other(tab) if split is not None else None
        if split is not None:
            self._drop_split(split)
        self.tabs.remove(tab)
        self._destroy_view(tab)
        if not self.tabs:
            self.open_tab()
        elif tab is self.active:
            self.select_tab(partner or self.tabs[min(index, len(self.tabs) - 1)])
        elif partner is not None and partner is self.active:
            self._show(partner)
        self.refresh()
        self.schedule_save()

    def reopen_closed(self):
        if self.closed:
            item = self.closed.pop()
            self.open_tab(item["url"], title=item["title"], pinned=item["pinned"])

    def duplicate(self):
        if self.active and self.active.url:
            self.open_tab(self.active.url, private=self.active.private)

    def toggle_pin(self):
        if self.active:
            split = self.split_of(self.active)
            if split is not None:
                # Pinned tabs cannot be in a pair.
                self._drop_split(split)
                self._show(self.active)
            self.active.pinned = not self.active.pinned
            self._sort_tabs()
            self.refresh()
            self.schedule_save()

    def cycle(self, delta):
        if self.active and self.tabs:
            self.select_tab(self.tabs[(self.tabs.index(self.active) + delta) % len(self.tabs)])

    def jump(self, number):
        if not self.tabs:
            return
        self.select_tab(self.tabs[-1] if number == 9 else self.tabs[min(number - 1, len(self.tabs) - 1)])

    # tab callbacks
    def tab_changed(self, tab):
        """A title, address or icon changed. Update its row in place."""
        if tab.peek:
            self._set_peek_head(tab)
            return
        self.strip.update(tab, self.active)
        self.schedule_save()
        if tab is self.active:
            self._set_title()
            self._sync_wall()

    def load_changed(self, tab, event):
        if event == WebKit2.LoadEvent.FINISHED:
            # A private peek is not recorded, like a private tab.
            if not tab.private:
                self.store.add_visit(tab.url, tab.title if tab.view.get_title() else "")
            if self.finished_cb and not tab.peek:
                self.finished_cb(tab)
        if event in (WebKit2.LoadEvent.COMMITTED, WebKit2.LoadEvent.FINISHED):
            self.tab_changed(tab)

    def load_failed(self, tab):
        if self.failed_cb and not tab.peek:
            self.failed_cb(tab)

    # address field and tab switcher
    def focus_omnibox(self):
        """Show the address field with the current address selected."""
        tab = self.active
        if tab is None:
            return
        self.switcher.close()
        text = omnibox.editable(tab.url) if tab.url != "about:blank" else ""
        # Over a page the page is dimmed. An empty tab has no cover.
        self.scrim.set_visible(bool(text))
        self.prompt.open(text)

    def open_switcher(self):
        self.prompt.close()
        self.scrim.show()
        self.switcher.open("")

    def hide_prompts(self, refocus=True):
        was_open = self.prompt.is_open() or self.switcher.is_open()
        self.prompt.close()
        self.switcher.close()
        self.scrim.hide()
        if was_open and refocus and self.active and self.active.view:
            self.active.view.grab_focus()

    # status line
    def link_hover(self, tab, uri):
        """Show the link under the pointer. Hide it a moment after it goes."""
        if tab not in self.visible_tabs():
            return
        if self._status_src:
            GLib.source_remove(self._status_src)
            self._status_src = 0
        if not uri:
            self._status_src = GLib.timeout_add(STATUS_HIDE_MS, self._hide_status)
            return
        area = self.overlay.get_allocation()
        self.status.set_max_width_chars(max(10, int(min(area.width * 0.6, 640) / 7)))
        self.status.set_text(uri[:600])
        # A bubble under the pointer moves to the other corner.
        self.status.set_halign(Gtk.Align.END if self._pointer_in_corner(area)
                               else Gtk.Align.START)
        self.status.show()

    def _hide_status(self):
        if self._status_src:
            GLib.source_remove(self._status_src)
        self._status_src = 0
        self.status.hide()
        return False

    def _pointer_in_corner(self, area):
        window = self.get_window()
        if window is None:
            return False
        device = Gdk.Display.get_default().get_default_seat().get_pointer()
        _w, x, y, _mask = window.get_device_position(device)
        origin = self.overlay.translate_coordinates(self, 0, 0)
        if origin is None:
            return False
        x, y = x - origin[0], y - origin[1]
        return area.height - y < 50 and x < min(area.width * 0.6, 640) + 22

    # find
    def open_find(self):
        if self.active is None:
            return
        self.hide_prompts(refocus=False)
        self._wire_find(self.active)
        self.find_bar.show()
        self.find_entry.grab_focus()
        self.find_entry.select_region(0, -1)
        self._on_find_changed(self.find_entry)

    def close_find(self):
        if self.find_bar.get_visible():
            self.find_bar.hide()
            if self.active and self.active.view:
                self.active.view.get_find_controller().search_finish()
                self.active.view.grab_focus()

    def _wire_find(self, tab):
        """Connect the find results of TAB once."""
        if tab.view is None or getattr(tab, "find_wired", False):
            return
        tab.find_wired = True
        controller = tab.view.get_find_controller()
        controller.connect("found-text", self._on_found, tab)
        controller.connect("failed-to-find-text", self._on_not_found, tab)

    def _on_found(self, _controller, count, tab):
        if tab is self.active:
            self._show_found("%d match%s" % (count, "" if count == 1 else "es"), False)

    def _on_not_found(self, _controller, tab):
        if tab is self.active:
            self._show_found("No matches", True)

    def _show_found(self, text, missed):
        self.find_count.set_text(text)
        context = self.find_bar.get_style_context()
        (context.add_class if missed else context.remove_class)("missed")

    def _on_find_changed(self, entry):
        if not (self.active and self.active.view):
            return
        controller = self.active.view.get_find_controller()
        text = entry.get_text()
        if not text:
            self._show_found("", False)
        if text:
            options = WebKit2.FindOptions.CASE_INSENSITIVE | WebKit2.FindOptions.WRAP_AROUND
            controller.search(text, int(options), 1000)
        else:
            controller.search_finish()

    def _find_step(self, backwards):
        if self.active and self.active.view:
            controller = self.active.view.get_find_controller()
            (controller.search_previous if backwards else controller.search_next)()

    def _on_find_key(self, _entry, event):
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._find_step(bool(event.state & Gdk.ModifierType.SHIFT_MASK))
            return True
        return False

    # reader, hide, zoom
    def toggle_reader(self):
        tab = self.active
        if tab is None or tab.view is None or not tab.url:
            return
        if tab.reader:
            tab.view.reload()
            return
        keys = ("accent", "muted", "background", "lighter_background",
                "foreground", "light_foreground")
        tab.run_in_world(js_call(read_resource("reader.js"), {k: self.colors[k] for k in keys}))
        tab.reader = True

    def start_hide(self):
        if self.active and self.active.view and self.active.url:
            self.active.run_in_world(read_resource("hide.js"))
            self.active.view.grab_focus()

    def hide_selector(self, tab, selector):
        if tab.private:
            return
        try:
            stored = self.store.add_hidden(tab.host, selector)
        except OSError as exc:
            log.warning("hidden rule save failed: %s", exc)
            return
        if stored:
            for other in self.all_tabs():
                other.update_hidden_script()
            tab.run_in_world(js_call(read_resource("hidden.js"), self.store.hidden))
        else:
            log.debug("hide selector rejected")

    def unhide_site(self):
        tab = self.active
        if tab and tab.host:
            try:
                self.store.clear_hidden(tab.host)
            except OSError as exc:
                log.warning("hidden rules clear failed: %s", exc)
            for other in self.all_tabs():
                other.update_hidden_script()
            tab.view.reload()

    def zoom(self, step):
        if self.active and self.active.view:
            view = self.active.view
            level = 1.0 if step == 0 else view.get_zoom_level() + step
            self.set_zoom_level(self.active, level)

    # clipboard
    def copy_url(self):
        if self.active and self.active.url:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.active.url, -1)

    def paste_and_go(self):
        def got(_clipboard, text):
            url = omnibox.classify(text or "", self.store.settings["engine"])
            if url:
                self.open_in_current(url, clean=True)
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).request_text(got)

    def bookmark(self):
        tab = self.active
        if tab and not tab.private and tab.url:
            try:
                self.store.add_bookmark(tab.url, tab.title)
            except OSError as exc:
                log.warning("bookmark save failed: %s", exc)
            if self.panel.is_open() and self.panel.mode == "bookmarks":
                self.panel.populate()

    # permissions, TLS, external
    def _saved_permission(self, tab, origin, kind):
        """Return True, False or None for a saved answer."""
        if tab.private and kind in self.private_grants.get(origin, {}):
            return self.private_grants[origin][kind]
        return self.store.permission(origin, kind)

    def _remember(self, tab, origin, kind, allowed):
        if kind in NEVER_REMEMBER or not security.remember_allowed(origin):
            return
        if tab.private:
            self.private_grants.setdefault(origin, {})[kind] = bool(allowed)
            return
        try:
            self.store.remember_permission(origin, kind, allowed)
        except OSError as exc:
            log.warning("permission save failed: %s", exc)

    def ask_permission(self, tab, request):
        if isinstance(request, WebKit2.PointerLockPermissionRequest):
            request.allow()
            return True
        kinds = None
        if isinstance(request, WebKit2.UserMediaPermissionRequest):
            kinds = media_kinds(request)
        else:
            for cls, name in PERMISSION_KINDS:
                if isinstance(request, cls):
                    kinds = [name]
                    break
        if kinds is None:
            kinds = ["this permission"]
        host = tab.host
        origin = security.permission_origin(tab.url)
        if not host or not origin:
            request.deny()
            return True
        saved = [self._saved_permission(tab, origin, k) for k in kinds]
        if all(v is True for v in saved):
            request.allow()
            return True
        if any(v is False for v in saved):
            request.deny()
            return True
        key = "+".join(kinds)
        for old in self.bars.get_children():
            if old.tab is tab and old.key == key:
                # One question for each tab and kind. Deny the extra request.
                request.deny()
                return True
        bar = Gtk.InfoBar()
        bar.tab = tab
        bar.key = key
        bar.request = request
        bar.answered = False
        label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        label.set_text("%s wants %s" % (host, " and ".join(kinds)))
        content = bar.get_content_area()
        content.pack_start(label, True, True, 0)
        # A private tab keeps answers in memory. It has no Remember choice.
        remember = Gtk.CheckButton(label="Remember")
        can_ask = (not tab.private and security.remember_allowed(origin)
                   and not any(k in NEVER_REMEMBER for k in kinds))
        if can_ask:
            content.pack_start(remember, False, False, 0)
        bar.add_button("Allow", Gtk.ResponseType.YES)
        bar.add_button("Deny", Gtk.ResponseType.NO)

        def answered(_bar, response):
            if bar.answered:
                return
            bar.answered = True
            allowed = response == Gtk.ResponseType.YES
            bar.destroy()
            (request.allow if allowed else request.deny)()
            if tab.private or (can_ask and remember.get_active()):
                for kind in kinds:
                    self._remember(tab, origin, kind, allowed)

        bar.connect("response", answered)
        self.bars.pack_start(bar, False, False, 0)
        bar.show_all()
        self._sync_bars()
        return True

    def clear_permission_bars(self, tab):
        """Destroy the permission bars of TAB. Deny their requests."""
        for bar in list(self.bars.get_children()):
            if bar.tab is tab:
                if not bar.answered:
                    bar.answered = True
                    bar.request.deny()
                bar.destroy()

    def _sync_bars(self):
        for bar in self.bars.get_children():
            bar.set_visible(bar.tab is self.active)

    def show_tls_error(self, tab, uri, flags):
        reasons = [text for name, text in TLS_REASONS
                   if flags & getattr(Gio.TlsCertificateFlags, name)]
        items = "".join("<li>%s</li>" % html.escape(r) for r in reasons)
        c = self.colors
        page = (
            "<!doctype html><meta charset=utf-8><title>Connection not private</title>"
            "<style>body{font:16px sans-serif;background:%s;color:%s;max-width:40em;"
            "margin:4em auto;padding:0 1em}h1{color:%s}code{color:%s}</style>"
            "<h1>Connection not private</h1><p>cruxx browser stopped this page "
            "because it cannot verify the site.</p><p><code>%s</code></p><ul>%s</ul>"
        ) % (c["background"], c["foreground"], c["red"], c["accent"],
             html.escape(uri or ""), items)
        tab.view.load_alternate_html(page, uri or "about:blank", None)

    def confirm_external(self, uri, source_host=""):
        if self._external_open:
            # One dialog at a time. Drop the extra request.
            return False
        self._external_open = True
        try:
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO, text="Open in external app?")
            dialog.set_property("secondary-text", "Scheme: %s\nFrom site: %s\n\n%s" % (
                security.display_uri(security.uri_scheme(uri), 40),
                security.display_uri(source_host or "(none)", 100),
                security.display_uri(uri, 200)))
            response = dialog.run()
            dialog.destroy()
        finally:
            self._external_open = False
        if response == Gtk.ResponseType.YES:
            try:
                Gio.AppInfo.launch_default_for_uri(uri, None)
            except GLib.Error as exc:
                log.warning("external launch failed: %s", exc.message)
        return False

    # downloads
    def _on_download_started(self, _ctx, download):
        item = {"name": "download", "progress": 0.0, "done": False,
                "failed": False, "dir": "", "download": download,
                "view": download.get_web_view()}
        self.downloads.append(item)
        del self.downloads[:-50]
        download.connect("decide-destination", self._on_decide_destination, item)
        download.connect("notify::estimated-progress", self._on_download_progress, item)
        download.connect("finished", self._on_download_end, item, False)
        download.connect("failed", self._on_download_end, item, True)

    def _on_decide_destination(self, download, suggested, item):
        directory = (GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
                     or os.path.expanduser("~/Downloads"))
        try:
            os.makedirs(directory, exist_ok=True)
            name, path = security.reserve_name(
                directory, security.safe_download_name(suggested))
        except OSError as exc:
            log.warning("download destination failed: %s", exc)
            item["failed"] = True
            download.cancel()
            self.panel.schedule()
            return True
        item["name"] = name
        item["dir"] = directory
        # The empty file is ours. WebKit may write into it.
        download.set_allow_overwrite(True)
        download.set_destination(GLib.filename_to_uri(path, None))
        self.panel.schedule()
        return True

    def _on_download_progress(self, download, _pspec, item):
        item["progress"] = download.get_estimated_progress()
        self.panel.schedule()

    def _on_download_end(self, _download, *args):
        item, failed = args[-2], args[-1]
        if failed:
            item["failed"] = True
        else:
            item["done"] = True
        self.panel.schedule()

    def open_folder(self, item):
        try:
            Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(item["dir"], None), None)
        except GLib.Error as exc:
            log.warning("open folder failed: %s", exc.message)

    # session
    def schedule_save(self):
        if not self._save_src:
            self._save_src = GLib.timeout_add(1000, self._save_timer)

    def _save_timer(self):
        self._save_src = 0
        self.save_session()
        return False

    def save_session(self):
        rows = []
        for space in self.spaces:
            normal = [t for t in space.tabs if not t.private]
            if space.active is not None and space.active in normal:
                active = normal.index(space.active)
            else:
                active = max(0, min(space.last_normal, len(normal) - 1))
            rows.append({
                "name": space.name, "icon": space.icon, "active": active,
                "tabs": [{"url": t.url, "title": t.page_title, "pinned": t.pinned,
                          "custom_title": t.custom_title} for t in normal],
                # A pair with a private tab is not saved.
                "splits": spaces.split_rows(normal, space.splits)})
        now = rows[self.space_index]
        try:
            self.store.save_session(now["tabs"], now["active"], self.side,
                                    space_rows=rows, current=self.space_index)
        except OSError as exc:
            log.warning("session save failed: %s", exc)

    def restore_session(self, urls, private_urls=0):
        session = self.store.load_session()
        self.side = session["side"]
        self._layout()
        restored = []
        for entry in session["spaces"]:
            space = spaces.Space(entry["name"], entry["icon"])
            rows = entry["tabs"] if self.store.settings["restore_session"] else []
            for row in rows:
                tab = Tab(self, row["url"], row["title"], row["pinned"])
                tab.custom_title = row["custom_title"]
                space.tabs.append(tab)
            space.tabs.sort(key=lambda t: not t.pinned)
            if space.tabs:
                space.last_normal = min(entry["active"], len(space.tabs) - 1)
                space.active = space.tabs[space.last_normal]
            if self.split_on() and rows:
                for item in entry["splits"]:
                    space.splits.append(spaces.Split(
                        space.tabs[item["a"]], space.tabs[item["b"]], item["ratio"]))
            spaces.regroup(space.tabs, space.splits)
            restored.append(space)
        self.spaces = restored
        self.space_index = session["current"]
        if self.tabs:
            self.select_tab(self.space.active)
        for url in urls:
            self.open_tab(url)
        for _ in range(private_urls):
            self.open_tab(private=True)
        if not self.tabs:
            self.open_tab()

    # keyboard
    def _on_key(self, _widget, event):
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(state & Gdk.ModifierType.MOD1_MASK)
        name = Gdk.keyval_name(Gdk.keyval_to_lower(event.keyval)) or ""
        if name == "escape" or name == "Escape":
            return self._escape()
        if name == "F5":
            return self._do(lambda: self.active and self.active.view and self.active.view.reload())
        if name == "F11":
            return self._do(lambda: self.set_page_fullscreen(not self._fullscreen))
        if name == "F12" and self.opts.dev:
            return self._do(lambda: self.active and self.active.view
                            and self.active.view.get_inspector().show())
        if alt and not ctrl:
            if name == "Left":
                return self._do(self._back)
            if name == "Right":
                return self._do(self._forward)
            if len(name) == 1 and name in "123456789" and not shift:
                return self._do(lambda: self.switch_space(int(name) - 1))
            return False
        if not ctrl:
            return False
        if alt and not shift and name == "r":
            return self._do(self._reload_origin)
        if alt and not shift and name == "l":
            return self._do(self.open_passwords)
        if alt and not shift and name == "n":
            return self._do(self.split_current)
        if alt and not shift and name in ("Left", "Right"):
            return self._do(lambda: self.focus_pane(-1 if name == "Left" else 1))
        if alt and not shift and name in ("Prior", "Next", "Page_Up", "Page_Down"):
            return self._do(lambda: self.cycle_space(-1 if name in ("Prior", "Page_Up") else 1))
        if shift and name in ("bracketleft", "braceleft", "bracketright", "braceright"):
            return self._do(lambda: self.cycle(-1 if "left" in name else 1))
        if name in ("plus", "equal", "KP_Add"):
            return self._do(lambda: self.zoom(ZOOM_STEP))
        if name in ("minus", "KP_Subtract"):
            return self._do(lambda: self.zoom(-ZOOM_STEP))
        if name in ("0", "KP_0") and not shift:
            return self._do(lambda: self.zoom(0))
        if name in ("Tab", "ISO_Left_Tab"):
            return self._do(lambda: self.cycle(-1 if shift or name == "ISO_Left_Tab" else 1))
        if len(name) == 1 and name in "123456789" and not shift:
            return self._do(lambda: self.jump(int(name)))
        table = shortcuts.SHIFT if shift else shortcuts.PLAIN
        action = table.get(name)
        return self._do(getattr(self, action)) if action else False

    @staticmethod
    def _do(func):
        func()
        return True

    def _escape(self):
        if self.peek is not None:
            self.close_peek()
        elif self.prompt.is_open() or self.switcher.is_open():
            self.hide_prompts()
        elif self.panel.is_open():
            self.panel.close()
        elif self.find_bar.get_visible():
            self.close_find()
        elif self.active and self.active.view and self.active.url:
            self.active.run_in_world("if (window.__cruxxPick) { window.__cruxxPick.stop(); }")
            return False
        else:
            return False
        return True

    def _close_active(self):
        if self.active:
            self.close_tab(self.active)

    def _reload(self):
        if self.active and self.active.view:
            self.active.view.reload()

    def _reload_origin(self):
        if self.active and self.active.view:
            self.active.view.reload_bypass_cache()

    # sleep, keep awake, rename, drag
    def is_kept_awake(self, tab):
        site = store.registrable_host(tab.host)
        if not site:
            return False
        if tab.private:
            return site in self.private_awake
        return self.store.keep_awake(tab.host)

    def set_kept_awake(self, tab, on):
        site = store.registrable_host(tab.host)
        if not site:
            return
        if tab.private:
            # A private tab must not write to settings.json.
            (self.private_awake.add if on else self.private_awake.discard)(site)
            return
        try:
            self.store.set_keep_awake(tab.host, on)
        except OSError as exc:
            log.warning("keep awake save failed: %s", exc)

    def _on_awake_toggled(self, item):
        if not self._menu_updating and self.active is not None:
            self.set_kept_awake(self.active, item.get_active())

    def _download_pending(self, tab):
        for item in self.downloads:
            if item["done"] or item["failed"]:
                continue
            # A download with no known view blocks sleep for all tabs.
            if item.get("view") is None or item["view"] is tab.view:
                return True
        return False

    def _sleep_timer(self):
        self.sleep_tick()
        return True

    def sleep_tick(self):
        """Put the tabs that were not used for a long time to sleep."""
        now = time.monotonic()
        if self.active is not None:
            self.active.last_active = now
        settings = self.store.settings
        wanted = {"sleep_after_min": (settings["sleep_after_min"]
                                      if self.sleep_override_min is None
                                      else self.sleep_override_min),
                  "sleep_pinned": settings["sleep_pinned"]}
        enabled = settings["keep_awake_enabled"]
        infos = []
        # Both panes of a visible pair stay awake.
        visible = self.visible_tabs()
        everything = self.all_tabs()
        for index, tab in enumerate(everything):
            view = tab.view
            infos.append({
                "id": index, "selected": tab in visible or tab.floating,
                "last_active": tab.last_active, "has_view": view is not None,
                "playing": bool(view is not None and view.is_playing_audio()),
                "downloading": self._download_pending(tab), "pinned": tab.pinned,
                "keep_awake": enabled and self.is_kept_awake(tab)})
        for index in sleep.candidates(infos, now, wanted):
            self.sleep_tab(everything[index])

    def sleep_tab(self, tab):
        """Save the state of TAB and destroy its WebView. The row stays."""
        view = tab.view
        if view is None or tab.floating or tab in self.visible_tabs():
            return
        tab.stored_url = view.get_uri() or tab.stored_url
        if view.get_title():
            tab.stored_title = view.get_title()
        self.clear_permission_bars(tab)
        self._destroy_view(tab)
        tab.manager = None
        tab.reader = False
        log.debug("tab put to sleep")
        self.refresh()

    def set_custom_title(self, tab, text):
        """Set the title the user typed. An empty text resets it."""
        tab.custom_title = " ".join(text.split())[:200]
        self.tab_changed(tab)
        if tab is self.active and tab.view is not None:
            tab.view.grab_focus()

    def rename_tab(self, tab):
        widget = self.strip.items.get(tab)
        if widget is not None:
            widget.start_rename()

    def tab_menu(self, tab, event):
        menu = Gtk.Menu()
        rename = Gtk.MenuItem(label="Rename tab")
        rename.connect("activate", lambda *_: self.rename_tab(tab))
        menu.append(rename)
        if self.split_on() and self.split_of(tab) is not None:
            separate = Gtk.MenuItem(label="Separate split tabs")
            separate.connect("activate", lambda *_: self.unsplit_active())
            menu.append(separate)
        if self.store.settings["keep_awake_enabled"] and tab.host:
            awake = Gtk.CheckMenuItem(label="Keep This Site Awake")
            awake.set_active(self.is_kept_awake(tab))
            awake.connect("toggled", lambda i: self.set_kept_awake(tab, i.get_active()))
            menu.append(awake)
        menu.show_all()
        menu.attach_to_widget(self.strip.items.get(tab) or self, None)
        menu.connect("selection-done", lambda m: GLib.idle_add(m.destroy))
        menu.popup_at_pointer(event)

    def drag_begin(self, tab):
        self.dragging = tab
        self.strip.drag_zone(True)
        if self.split_on() and self.active is not None:
            self.dropzone.show()

    def drag_end(self):
        self.dragging = None
        self.strip.drag_zone(False)
        self.dropzone.hide()

    def drop_tab(self, target, after, pin):
        tab = self.dragging
        if tab is None or tab not in self.tabs:
            return
        if target is tab:
            return
        split = self.split_of(tab)
        if pin and split is not None:
            self._drop_split(split)
            self._show(self.active)
        if reorder.move_tab(self.tabs, tab, target, after, pin):
            spaces.regroup(self.tabs, self.space.splits)
            self.refresh()
            self.schedule_save()

    def _back(self):
        if self.active and self.active.view and self.active.view.can_go_back():
            self.active.view.go_back()

    def _forward(self):
        if self.active and self.active.view and self.active.view.can_go_forward():
            self.active.view.go_forward()

    def _open_private(self):
        self.open_tab(private=True)

    def _toggle_bookmarks(self):
        self.panel.toggle("bookmarks")

    def _toggle_history(self):
        self.panel.toggle("history")

    def _toggle_downloads(self):
        self.panel.toggle("downloads")
