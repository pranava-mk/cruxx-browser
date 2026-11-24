"""Main window: tab strip, stack of WebViews, omnibox and side panels."""

import html
import logging
import os

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, WebKit2  # noqa: E402

from . import omnibox, security, store, theme  # noqa: E402
from .tab import Tab, js_call, read_resource, rgba  # noqa: E402

log = logging.getLogger(__name__)
CLOSED_CAP = 25
STRIP_WIDTH = 220
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
        self._rebuilding = False
        self._refresh_src = 0
        self._save_src = 0
        self._provider = None
        self._last_normal = 0
        # Private tab data. It lives in memory for this window only.
        self.private_paused = set()
        self.private_grants = {}
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

    # construction
    def _build(self):
        self.entry = Gtk.Entry(hexpand=True)
        self.entry.set_placeholder_text("Search or enter address")
        self.entry.connect("activate", self._on_entry_activate)
        self.entry.connect("changed", self._on_entry_changed)
        self.completion = Gtk.EntryCompletion()
        self.completion_model = Gtk.ListStore(str)
        self.completion.set_model(self.completion_model)
        self.completion.set_text_column(0)
        self.completion.set_match_func(lambda *_a: True)
        self.completion.set_inline_completion(False)
        self.completion.connect("match-selected", self._on_match_selected)
        self.entry.set_completion(self.completion)
        self.menu_button = Gtk.MenuButton()
        self.menu_button.add(Gtk.Image.new_from_icon_name(
            "open-menu-symbolic", Gtk.IconSize.BUTTON))
        self._build_menu()
        self.omni_box = Gtk.Box(spacing=4)
        self.omni_box.set_border_width(4)
        self.omni_box.pack_start(self.entry, True, True, 0)
        self.omni_box.pack_start(self.menu_button, False, False, 0)

        self.tab_list = Gtk.ListBox()
        self.tab_list.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.tab_list.connect("row-selected", self._on_row_selected)
        self.left_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.left_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.left_scroll.add(self.tab_list)
        self.left_slot = Gtk.Box()
        self.left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.left_col.set_size_request(STRIP_WIDTH, -1)
        self.left_col.get_style_context().add_class("cruxx-strip")
        self.left_col.pack_start(self.left_slot, False, False, 0)
        self.left_col.pack_start(self.left_scroll, True, True, 0)

        self.top_slot = Gtk.Box()
        self.tab_bar = Gtk.Box(spacing=2)
        self.top_scroll = Gtk.ScrolledWindow()
        self.top_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.top_scroll.add(self.tab_bar)

        self.bars = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.stack = Gtk.Stack()
        self.find_bar = self._build_find_bar()
        self.panel = Panel(self)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.pack_start(self.top_slot, False, False, 0)
        right.pack_start(self.top_scroll, False, False, 0)
        right.pack_start(self.bars, False, False, 0)
        right.pack_start(self.stack, True, True, 0)
        right.pack_start(self.find_bar, False, False, 0)
        root = Gtk.Box()
        root.pack_start(self.left_col, False, False, 0)
        root.pack_start(right, True, True, 0)
        root.pack_start(self.panel, False, False, 0)
        self.add(root)
        for widget in (self.left_col, self.left_scroll, self.top_scroll, self.find_bar):
            widget.set_no_show_all(True)
        root.show_all()
        self._build_switcher()
        self._layout()

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
        for item in (self.pause_item, reader, hide, unhide, self.popup_item):
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
        bar = Gtk.Box(spacing=4)
        bar.set_border_width(4)
        self.find_entry = Gtk.SearchEntry(hexpand=True)
        self.find_entry.connect("search-changed", self._on_find_changed)
        self.find_entry.connect("activate", lambda *_: self._find_step(False))
        self.find_entry.connect("key-press-event", self._on_find_key)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        close.connect("clicked", lambda *_: self.close_find())
        bar.pack_start(self.find_entry, True, True, 0)
        bar.pack_start(close, False, False, 0)
        return bar

    def _build_switcher(self):
        self.switcher = Gtk.Popover(relative_to=self.entry)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(6)
        self.switch_entry = Gtk.SearchEntry()
        self.switch_list = Gtk.ListBox()
        self.switch_list.set_filter_func(self._switch_filter)
        self.switch_entry.connect("search-changed", lambda *_: self.switch_list.invalidate_filter())
        self.switch_entry.connect("activate", self._switch_first)
        self.switch_list.connect("row-activated", self._switch_pick)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(260)
        scroll.set_min_content_width(380)
        scroll.add(self.switch_list)
        box.pack_start(self.switch_entry, False, False, 0)
        box.pack_start(scroll, True, True, 0)
        self.switcher.add(box)
        box.show_all()

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
        parent = self.omni_box.get_parent()
        if parent is not None:
            parent.remove(self.omni_box)
        left = self.side == "left"
        (self.left_slot if left else self.top_slot).pack_start(self.omni_box, True, True, 0)
        self.left_col.set_visible(left)
        self.left_scroll.set_visible(left and self.strip_visible)
        self.top_scroll.set_visible((not left) and self.strip_visible)
        # left_col has no_show_all, so show_all() does not show its slot.
        self.left_slot.show()
        self.top_slot.show()
        self.omni_box.show_all()
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
        if not self._refresh_src:
            self._refresh_src = GLib.idle_add(self._do_refresh)

    def _item(self, tab):
        box = Gtk.Box(spacing=6)
        box.set_border_width(4)
        if tab.favicon is not None:
            image = Gtk.Image()
            image.set_from_surface(tab.favicon)
            box.pack_start(image, False, False, 0)
        label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        if tab.pinned:
            label.set_text((tab.title or "?")[0].upper())
            box.set_tooltip_text(tab.title)
        else:
            label.set_text(tab.title)
        if tab.private:
            box.get_style_context().add_class("private")
        box.pack_start(label, True, True, 0)
        return box

    def _do_refresh(self):
        self._refresh_src = 0
        self._rebuilding = True
        for child in self.tab_list.get_children():
            child.destroy()
        for child in self.tab_bar.get_children():
            child.destroy()
        selected = None
        for tab in self.tabs:
            row = Gtk.ListBoxRow()
            row.tab = tab
            event_box = Gtk.EventBox()
            event_box.add(self._item(tab))
            event_box.connect("button-press-event", self._on_item_press, tab)
            row.add(event_box)
            self.tab_list.add(row)
            if tab is self.active:
                selected = row
            button = Gtk.Button()
            button.add(self._item(tab))
            button.set_relief(Gtk.ReliefStyle.NONE)
            if tab is self.active:
                button.get_style_context().add_class("active-tab")
            button.connect("clicked", lambda _b, t=tab: self.select_tab(t))
            button.connect("button-press-event", self._on_item_press, tab)
            self.tab_bar.pack_start(button, tab.pinned is False, tab.pinned is False, 0)
        self.tab_list.show_all()
        self.tab_bar.show_all()
        if selected is not None:
            self.tab_list.select_row(selected)
        self._rebuilding = False
        self.set_title(((self.active.title + " - ") if self.active else "") + "cruxx browser")
        return False

    def _on_item_press(self, _widget, event, tab):
        if event.button == 2:
            self.close_tab(tab)
            return True
        return False

    def _on_row_selected(self, _list, row):
        if not self._rebuilding and row is not None:
            self.select_tab(row.tab)

    # tab operations
    def _sort_tabs(self):
        self.tabs.sort(key=lambda t: not t.pinned)

    def open_tab(self, url="", private=False, background=False, title="", pinned=False):
        tab = Tab(self, url, title, pinned, private)
        self.tabs.append(tab)
        self._sort_tabs()
        if background:
            self.refresh()
            self.schedule_save()
        else:
            self.select_tab(tab)
            if not url:
                self.entry.grab_focus()
        return tab

    def open_in_current(self, url):
        if self.active is None:
            self.open_tab(url)
        else:
            self.active.load(url)

    def select_tab(self, tab):
        if tab not in self.tabs:
            return
        self.close_find()
        self.active = tab
        if not tab.private:
            self._last_normal = self.tabs.index(tab)
        tab.ensure_view()
        self.stack.set_visible_child(tab.view)
        self._sync_entry()
        self._sync_bars()
        self.refresh()
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
        self.refresh()
        self.schedule_save()
        if tab is self.active:
            self._sync_entry()

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

    # omnibox
    def _sync_entry(self):
        if self.entry.has_focus() or self.active is None:
            return
        url = self.active.url
        self.entry.set_text("" if url in ("", "about:blank") else url)

    def _on_entry_activate(self, entry):
        url = omnibox.classify(entry.get_text(), self.store.settings["engine"])
        if url is None:
            return
        self.open_in_current(url)
        if self.active and self.active.view:
            self.active.view.grab_focus()

    def _on_entry_changed(self, entry):
        text = entry.get_text()
        self.completion_model.clear()
        if not entry.has_focus():
            return
        for url in omnibox.rank(self.store.history, text):
            self.completion_model.append([url])

    def _on_match_selected(self, _completion, model, tree_iter):
        self.entry.set_text(model[tree_iter][0])
        self.entry.emit("activate")
        return True

    def focus_omnibox(self):
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    # find
    def open_find(self):
        if self.active is None:
            return
        self.find_bar.show_all()
        self.find_entry.grab_focus()
        self.find_entry.select_region(0, -1)

    def close_find(self):
        if self.find_bar.get_visible():
            self.find_bar.hide()
            if self.active and self.active.view:
                self.active.view.get_find_controller().search_finish()
                self.active.view.grab_focus()

    def _on_find_changed(self, entry):
        if not (self.active and self.active.view):
            return
        controller = self.active.view.get_find_controller()
        text = entry.get_text()
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

    # switcher
    def open_switcher(self):
        for child in self.switch_list.get_children():
            child.destroy()
        for tab in self.tabs:
            row = Gtk.ListBoxRow()
            row.tab = tab
            label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
            label.set_text(tab.title)
            label.set_tooltip_text(tab.url)
            row.add(label)
            self.switch_list.add(row)
        self.switch_list.show_all()
        self.switch_entry.set_text("")
        self.switcher.popup()
        self.switch_entry.grab_focus()

    def _switch_filter(self, row):
        needle = self.switch_entry.get_text().strip().lower()
        return not needle or needle in (row.tab.title + " " + row.tab.url).lower()

    def _switch_first(self, *_args):
        for row in self.switch_list.get_children():
            if row.get_child_visible() and self._switch_filter(row):
                self._switch_pick(None, row)
                return

    def _switch_pick(self, _list, row):
        self.switcher.popdown()
        self.select_tab(row.tab)

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
                self.open_in_current(url)
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
                "failed": False, "dir": "", "download": download}
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
        rows = [{"url": t.url, "title": t.title, "pinned": t.pinned} for t in normal]
        try:
            self.store.save_session(rows, active, self.side)
        except OSError as exc:
            log.warning("session save failed: %s", exc)

    def restore_session(self, urls, private_urls=0):
        session = self.store.load_session()
        self.side = session["side"]
        self._layout()
        for entry in session["tabs"]:
            self.tabs.append(Tab(self, entry["url"], entry["title"], entry["pinned"]))
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
        if self.panel.is_open():
            self.panel.close()
        elif self.find_bar.get_visible():
            self.close_find()
        elif self.active and self.active.view and self.active.url and not self.entry.has_focus():
            self.active.run_in_world("if (window.__cruxxPick) { window.__cruxxPick.stop(); }")
            return False
        elif self.entry.has_focus():
            self._sync_entry_force()
            if self.active and self.active.view:
                self.active.view.grab_focus()
        else:
            return False
        return True

    def _sync_entry_force(self):
        url = self.active.url if self.active else ""
        self.entry.set_text("" if url in ("", "about:blank") else url)

    def _close_active(self):
        if self.active:
            self.close_tab(self.active)

    def _reload(self):
        if self.active and self.active.view:
            self.active.view.reload()

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
