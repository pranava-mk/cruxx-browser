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

from . import cleanlink, memory, omnibox, reorder, security, sleep, store, theme  # noqa: E402
from .addressbar import (FIELD_HEIGHT, FIELD_WIDTH, LIFT, AddressPrompt,  # noqa: E402
                         SwitcherPrompt)
from .sidebar import TabStrip  # noqa: E402
from .tab import Tab, js_call, read_resource, rgba  # noqa: E402
from .widgets import Glyph  # noqa: E402

log = logging.getLogger(__name__)
CLOSED_CAP = 25
STATUS_HIDE_MS = 120
ZOOM_STEP = 0.1

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
        self.tabs = []
        self.active = None
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
        self._last_normal = 0
        # Private tab data. It lives in memory for this window only.
        self.private_paused = set()
        self.private_grants = {}
        self.dragging = None
        self.private_awake = set()
        self.sleep_override_min = None
        self._external_open = False
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
        GLib.timeout_add_seconds(sleep.CHECK_SECONDS, self._sleep_timer)

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
        self.panel = Panel(self)
        # Floating things lie over the page, in this order from the bottom.
        self.overlay = Gtk.Overlay()
        self.overlay.add(self.stack)
        self.scrim = Gtk.EventBox()
        self.scrim.set_visible_window(True)
        self.scrim.get_style_context().add_class("cruxx-scrim")
        self.scrim.connect("button-press-event", lambda *_: self.hide_prompts() or True)
        self.status = Gtk.Label(ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.status.get_style_context().add_class("cruxx-status")
        self.status.set_halign(Gtk.Align.START)
        self.status.set_valign(Gtk.Align.END)
        self.status.set_margin_start(10)
        self.status.set_margin_end(10)
        self.status.set_margin_bottom(10)
        self.find_bar = self._build_find_bar()
        for widget in (self.scrim, self.status, self.find_bar,
                       self.prompt.card, self.switcher.card):
            widget.set_no_show_all(True)
            widget.hide()
            self.overlay.add_overlay(widget)
        self.overlay.set_overlay_pass_through(self.status, True)
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
        self.pause_item = Gtk.CheckMenuItem(label="Pause shield on this site")
        self.pause_item.connect("toggled", self._on_pause_toggled)
        self.popup_item = Gtk.MenuItem(label="Blocked popups: 0")
        self.popup_item.set_sensitive(False)
        reader = Gtk.MenuItem(label="Reading mode")
        reader.connect("activate", lambda *_: self.toggle_reader())
        hide = Gtk.MenuItem(label="Hide element")
        hide.connect("activate", lambda *_: self.start_hide())
        unhide = Gtk.MenuItem(label="Show hidden elements on this site")
        unhide.connect("activate", lambda *_: self.unhide_site())
        origin = Gtk.MenuItem(label="Reload from origin (Ctrl+Alt+R)")
        origin.connect("activate", lambda *_: self._reload_origin())
        self.awake_item = Gtk.CheckMenuItem(label="Keep This Site Awake")
        self.awake_item.set_no_show_all(True)
        self.awake_item.connect("toggled", self._on_awake_toggled)
        self.awake_enable_item = Gtk.CheckMenuItem(label="Offer keep-awake for sites")
        self.awake_enable_item.connect("toggled", self._on_awake_enable_toggled)
        for item in (self.pause_item, reader, hide, unhide, origin, self.awake_item,
                     self.awake_enable_item, self.popup_item):
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
        self.awake_enable_item.set_active(enabled)
        self.awake_item.set_visible(enabled)
        self.awake_item.set_sensitive(bool(tab and tab.host))
        self.awake_item.set_active(bool(tab and self.is_kept_awake(tab)))
        self._menu_updating = False
        self.popup_item.set_label("Blocked popups: %d" % (tab.blocked_popups if tab else 0))

    def _on_pause_toggled(self, item):
        tab = self.active
        if self._menu_updating or tab is None or not tab.host:
            return
        if tab.private:
            # A private tab must not write to settings.json.
            site = store.registrable_host(tab.host)
            if item.get_active():
                self.private_paused.add(site)
            else:
                self.private_paused.discard(site)
        else:
            try:
                self.store.set_shield_paused(tab.host, item.get_active())
            except OSError as exc:
                log.warning("shield pause save failed: %s", exc)
        tab.tune_shield(tab.host)
        tab.view.reload()

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
        for tab in self.tabs:
            if tab.view is not None:
                tab.view.set_background_color(rgba(self.colors["background"]))

    # contexts and views
    def context(self, private):
        return self.ephemeral_ctx if private else self.persistent_ctx

    def add_view(self, tab):
        tab.view.show()
        self.stack.add_named(tab.view, str(id(tab)))

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
        self.hide_prompts(refocus=False)
        self._hide_status()
        now = time.monotonic()
        if self.active is not None:
            self.active.last_active = now
        tab.last_active = now
        self.active = tab
        if not tab.private:
            self._last_normal = self.tabs.index(tab)
        tab.ensure_view()
        self.stack.set_visible_child(tab.view)
        self._sync_bars()
        self._sync_strip()
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
        self.tabs.remove(tab)
        if tab.view is not None:
            self.stack.remove(tab.view)
            tab.view.destroy()
            tab.view = None
        if not self.tabs:
            self.open_tab()
        elif tab is self.active:
            self.select_tab(self.tabs[min(index, len(self.tabs) - 1)])
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
        self.strip.update(tab, self.active)
        self.schedule_save()
        if tab is self.active:
            self._set_title()

    def load_changed(self, tab, event):
        if event == WebKit2.LoadEvent.FINISHED:
            if not tab.private:
                self.store.add_visit(tab.url, tab.title if tab.view.get_title() else "")
            if self.finished_cb:
                self.finished_cb(tab)
        if event in (WebKit2.LoadEvent.COMMITTED, WebKit2.LoadEvent.FINISHED):
            self.tab_changed(tab)

    def load_failed(self, tab):
        if self.failed_cb:
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
        if tab is not self.active:
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
            for other in self.tabs:
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
            for other in self.tabs:
                other.update_hidden_script()
            tab.view.reload()

    def zoom(self, step):
        if self.active and self.active.view:
            view = self.active.view
            level = 1.0 if step == 0 else min(5.0, max(0.3, view.get_zoom_level() + step))
            view.set_zoom_level(level)

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
        normal = [t for t in self.tabs if not t.private]
        if self.active is not None and not self.active.private and self.active in normal:
            active = normal.index(self.active)
        else:
            active = max(0, min(self._last_normal, len(normal) - 1))
        rows = [{"url": t.url, "title": t.page_title, "pinned": t.pinned,
                 "custom_title": t.custom_title} for t in normal]
        try:
            self.store.save_session(rows, active, self.side)
        except OSError as exc:
            log.warning("session save failed: %s", exc)

    def restore_session(self, urls, private_urls=0):
        session = self.store.load_session()
        self.side = session["side"]
        self._layout()
        for entry in session["tabs"]:
            tab = Tab(self, entry["url"], entry["title"], entry["pinned"])
            tab.custom_title = entry["custom_title"]
            self.tabs.append(tab)
        self._sort_tabs()
        if self.tabs:
            self.select_tab(self.tabs[min(session["active"], len(self.tabs) - 1)])
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
            return False
        if not ctrl:
            return False
        if alt and not shift and name == "r":
            return self._do(self._reload_origin)
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
        table = self._shift_keys if shift else self._plain_keys
        action = table.get(name)
        return self._do(getattr(self, action)) if action else False

    _plain_keys = {
        "t": "open_tab", "w": "_close_active", "l": "focus_omnibox", "k": "open_switcher",
        "r": "_reload", "f": "open_find", "d": "duplicate", "b": "_toggle_bookmarks",
        "y": "_toggle_history", "s": "toggle_strip", "bracketleft": "_back",
        "bracketright": "_forward",
    }
    _shift_keys = {
        "t": "reopen_closed", "s": "toggle_side", "d": "toggle_pin", "c": "copy_url",
        "v": "paste_and_go", "b": "bookmark", "j": "_toggle_downloads",
        "n": "_open_private", "h": "start_hide", "u": "unhide_site", "r": "toggle_reader",
    }

    @staticmethod
    def _do(func):
        func()
        return True

    def _escape(self):
        if self.prompt.is_open() or self.switcher.is_open():
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

    def _on_awake_enable_toggled(self, item):
        if self._menu_updating:
            return
        self.store.settings["keep_awake_enabled"] = item.get_active()
        try:
            self.store.save_settings()
        except OSError as exc:
            log.warning("settings save failed: %s", exc)

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
        for index, tab in enumerate(self.tabs):
            view = tab.view
            infos.append({
                "id": index, "selected": tab is self.active,
                "last_active": tab.last_active, "has_view": view is not None,
                "playing": bool(view is not None and view.is_playing_audio()),
                "downloading": self._download_pending(tab), "pinned": tab.pinned,
                "keep_awake": enabled and self.is_kept_awake(tab)})
        for index in sleep.candidates(infos, now, wanted):
            self.sleep_tab(self.tabs[index])

    def sleep_tab(self, tab):
        """Save the state of TAB and destroy its WebView. The row stays."""
        view = tab.view
        if view is None or tab is self.active:
            return
        tab.stored_url = view.get_uri() or tab.stored_url
        if view.get_title():
            tab.stored_title = view.get_title()
        self.clear_permission_bars(tab)
        self.stack.remove(view)
        view.destroy()
        tab.view = None
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

    def drag_end(self):
        self.dragging = None
        self.strip.drag_zone(False)

    def drop_tab(self, target, after, pin):
        tab = self.dragging
        if tab is None or tab not in self.tabs:
            return
        if target is tab:
            return
        if reorder.move_tab(self.tabs, tab, target, after, pin):
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
