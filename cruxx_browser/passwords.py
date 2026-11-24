"""Passwords: the offer to save, the fill list, and the passwords window.

Rules (see SECURITY.md):
- The origin always comes from the top-level address of the tab, in Python.
- The page script only says what the user typed or where a field is.
- Nothing is filled until the user clicks an account in the list.
- A private tab never saves anything.
"""

import hashlib
import logging
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import vault  # noqa: E402
from .forms import button, confirm, divider, label  # noqa: E402
from .tab import WORLD, js_call, read_resource  # noqa: E402

log = logging.getLogger(__name__)
TEST_ACTIONS = ("pwsave", "pwfill")
FILL_JS = "function (a) { return window.__cruxxPwFill(a[0], a[1]); }"
VISIBLE_JS = "(function () { return !!(window.__cruxxPwVisible && window.__cruxxPwVisible()); })();"


class _NoRequest:
    """Stands in for a permission request on an info bar of the window."""

    def deny(self):
        pass


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


BAR_SECONDS = 120


class Passwords:
    def __init__(self, win):
        self.win = win
        self.backend = vault.make_backend(getattr(win.opts, "test_vault", None))
        self.test = getattr(win.opts, "test_action", None) in TEST_ACTIONS
        self.test_delay_ms = max(1, min(getattr(win.opts, "test_hold", 6), 20)) * 250
        self.events = []
        self.popover = None
        self.popover_buttons = []
        self._token = 0
        self._panel = None
        self._copy_src = 0
        self._copied = None
        probe = getattr(self.backend, "probe", None)
        if probe is not None:
            probe(self._probed)

    def _probed(self, ok):
        if not ok:
            self.backend.available = False
            self._refresh_settings()

    # state
    @property
    def available(self):
        return self.backend.available

    def offers_on(self):
        return self.available and self.win.store.settings["passwords_enabled"]

    def notice(self):
        return "" if self.available else self.backend.notice

    def _refresh_settings(self):
        page = getattr(self.win, "_settings_win", None)
        if page is not None:
            page.refresh_passwords()

    def user_script(self):
        from gi.repository import WebKit2
        return WebKit2.UserScript.new_for_world(
            read_resource("passwords.js"), WebKit2.UserContentInjectedFrames.TOP_FRAME,
            WebKit2.UserScriptInjectionTime.START, WORLD, None, None)

    def _log_event(self, name):
        if self.test:
            self.events.append(name)

    # messages from the page
    def on_message(self, tab, raw):
        if tab.peek or tab.view is None:
            return
        message = vault.parse_message(raw)
        if message is None:
            return
        origin = vault.vault_origin(tab.url)
        if not origin:
            return
        kind = message["kind"]
        if kind == "submit":
            self._on_submit(tab, origin, message)
        elif kind == "focus":
            self._show_fill(tab, origin, message["rect"])
        else:
            self.hide_fill()

    def _on_submit(self, tab, origin, message):
        if tab.private or not self.offers_on():
            return
        if origin in self.win.store.settings["password_never"]:
            return
        self._drop_pending(tab)
        tab.pw_pending = {"origin": origin, "username": message["username"],
                          "password": message["password"], "time": time.monotonic()}
        # Forget the credential when no page load uses it in time.
        tab.pw_timer = GLib.timeout_add_seconds(
            vault.PENDING_SECONDS, self._expire_pending, tab)
        self._log_event("pending")

    def _drop_pending(self, tab):
        """Forget the pending credential of TAB and cancel its timer."""
        timer = getattr(tab, "pw_timer", 0)
        if timer:
            GLib.source_remove(timer)
        tab.pw_timer = 0
        tab.pw_pending = None

    def _expire_pending(self, tab):
        tab.pw_timer = 0
        tab.pw_pending = None
        return False

    # load events
    def page_started(self, tab):
        if tab is not None:
            self.hide_fill()

    def page_finished(self, tab):
        pending = getattr(tab, "pw_pending", None)
        if pending is None:
            return
        # Use the pending credential once, at the first finished load.
        self._drop_pending(tab)
        if tab.private or tab.peek or tab.view is None or not self.offers_on():
            return
        if not vault.pending_valid(pending, time.monotonic()):
            return
        origin = vault.vault_origin(tab.url)
        if not origin or not vault.same_site(origin, pending["origin"]):
            return
        if pending["origin"] in self.win.store.settings["password_never"]:
            return
        view = tab.view

        def answered(_view, result, _data=None):
            try:
                value = view.run_javascript_in_world_finish(result).get_js_value()
                shown = value.to_boolean()
            except GLib.Error:
                return
            if shown or tab.view is not view or tab.private:
                return
            self._offer(tab, pending)

        view.run_javascript_in_world(VISIBLE_JS, WORLD, None, answered, None)

    def tab_gone(self, tab):
        self._drop_pending(tab)
        self.hide_fill()
        for bar in list(self.win.bars.get_children()):
            if bar.tab is tab and getattr(bar, "key", "") == "password":
                bar.answered = True
                bar.destroy()

    # offer to save
    def _offer(self, tab, pending):
        origin, username, password = pending["origin"], pending["username"], pending["password"]

        def known(existing):
            if tab.view is None or not self.available:
                return
            kind = vault.offer_kind(existing, password)
            if kind == "none":
                self._log_event("same")
                return
            self._show_bar(tab, origin, username, password, kind)

        self.backend.get(origin, username, known)

    def _show_bar(self, tab, origin, username, password, kind):
        win = self.win
        for old in list(win.bars.get_children()):
            if old.tab is tab and getattr(old, "key", "") == "password":
                old.answered = True
                old.destroy()
        host = vault.origin_host(origin)
        shown = username if username else "this account"
        held = [password]
        password = None
        bar = Gtk.InfoBar()
        bar.tab = tab
        bar.key = "password"
        bar.request = _NoRequest()
        bar.answered = False
        text = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        verb = "Update password" if kind == "update" else "Save password"
        text.set_text("%s for %s on %s?" % (verb, shown, host))
        bar.get_content_area().pack_start(text, True, True, 0)
        bar.add_button("Update" if kind == "update" else "Save", Gtk.ResponseType.YES)
        if kind == "save":
            bar.add_button("Never for this site", Gtk.ResponseType.NO)
        bar.add_button("Not now", Gtk.ResponseType.CANCEL)

        def response(_bar, answer):
            if bar.answered:
                return
            bar.answered = True
            # Take the password first: closing the bar drops it.
            secret = held[0]
            bar.destroy()
            if answer == Gtk.ResponseType.YES and secret is not None:
                self.backend.put(origin, username, secret, self._saved)
            elif answer == Gtk.ResponseType.NO:
                try:
                    win.store.add_password_never(origin)
                except OSError as exc:
                    log.warning("never list save failed: %s", exc)

        timer = [0]

        def expire():
            timer[0] = 0
            held[0] = None
            return False

        # Keep no password for long: drop it when the bar closes or at 120 s.
        timer[0] = GLib.timeout_add_seconds(BAR_SECONDS, expire)

        def closed(_bar):
            if timer[0]:
                GLib.source_remove(timer[0])
            expire()

        bar.connect("destroy", closed)
        bar.connect("response", response)
        win.bars.pack_start(bar, False, False, 0)
        bar.show_all()
        win._sync_bars()
        self._log_event("offered")
        if self.test:
            GLib.timeout_add(self.test_delay_ms, lambda: bar.response(Gtk.ResponseType.YES) or False)

    def _saved(self, ok):
        if ok:
            self._log_event("saved")
            self._refresh_panel()
        else:
            self._log_event("save-failed")
            self.win.toast("Could not save the password.")
            self._refresh_settings()

    # fill list
    def hide_fill(self):
        self._token += 1
        pop, self.popover = self.popover, None
        self.popover_buttons = []
        if pop is not None:
            pop.destroy()

    def _show_fill(self, tab, origin, rect):
        win = self.win
        if tab is not win.active or not self.available:
            return
        self._token += 1
        token = self._token

        def listed(found):
            if token != self._token or not found or tab.view is None:
                return
            if vault.vault_origin(tab.url) != origin or tab is not win.active:
                return
            names = [name for _origin, name in found]
            self._build_popover(tab, origin, names, rect)

        self.backend.list(origin, listed)

    def _build_popover(self, tab, origin, names, rect):
        view = tab.view
        old, self.popover = self.popover, None
        if old is not None:
            old.destroy()
        zoom = view.get_zoom_level()
        target = Gdk.Rectangle()
        target.x, target.y = int(rect["x"] * zoom), int(rect["y"] * zoom)
        target.width, target.height = int(rect["w"] * zoom), int(rect["h"] * zoom)
        pop = Gtk.Popover()
        pop.set_relative_to(view)
        pop.set_pointing_to(target)
        pop.set_position(Gtk.PositionType.BOTTOM)
        # A popover that takes the grab would move focus out of the page.
        pop.set_modal(False)
        pop.get_style_context().add_class("cruxx-pop")
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        body.set_border_width(8)
        body.pack_start(label("Saved passwords", "cruxx-note"), False, False, 2)
        buttons = []
        for name in names[:8]:
            item = Gtk.Button()
            item.set_relief(Gtk.ReliefStyle.NONE)
            item.set_focus_on_click(False)
            item.set_can_focus(False)
            text = label(name if name else "(no user name)", ellipsize=True)
            text.set_max_width_chars(36)
            item.add(text)
            item.connect("clicked", lambda _b, n=name: self._pick(tab, origin, n))
            body.pack_start(item, False, False, 0)
            buttons.append(item)
        pop.add(body)
        body.show_all()
        self.popover, self.popover_buttons = pop, buttons
        pop.popup()
        self._log_event("popover:%d" % len(names))

    def _pick(self, tab, origin, username):
        def got(password):
            self.hide_fill()
            if password is None or tab.view is None:
                return
            # The address can change while the keyring answers.
            if vault.vault_origin(tab.url) != origin:
                return
            tab.view.run_javascript_in_world(
                js_call(FILL_JS, [username, password]), WORLD, None, None, None)
            self._log_event("filled")

        self.backend.get(origin, username, got)

    # site card and panel
    def count_for(self, tab, done):
        origin = vault.vault_origin(tab.url)
        if not origin or not self.available:
            done(0)
            return
        self.backend.list(origin, lambda found: done(len(found or [])))

    def open_panel(self):
        if self._panel is None:
            self._panel = PasswordsWindow(self)
            self._panel.connect("destroy", lambda *_: setattr(self, "_panel", None))
        self._panel.reload()
        self._panel.present()

    def _refresh_panel(self):
        if self._panel is not None:
            self._panel.reload()

    def copy_password(self, origin, username):
        """Copy a password. Clear the clipboard after 45 s if it still holds it."""
        def got(password):
            if password is None:
                return
            clipboard = Gtk.Clipboard.get_default(Gdk.Display.get_default())
            clipboard.set_text(password, -1)
            copied = digest(password)
            self._copied = copied
            if self._copy_src:
                GLib.source_remove(self._copy_src)
            self._copy_src = GLib.timeout_add_seconds(
                vault.CLIPBOARD_CLEAR_SECONDS, self._clear_clipboard, copied)

        self.backend.get(origin, username, got)

    def _clear_clipboard(self, copied):
        self._copy_src = 0
        self._copied = None
        clipboard = Gtk.Clipboard.get_default(Gdk.Display.get_default())

        def seen(_clipboard, text):
            now = digest(text) if text is not None else None
            if vault.clipboard_should_clear(now, copied):
                clipboard.clear()

        clipboard.request_text(seen)
        return False


    def shutdown(self):
        """Clear the clipboard now if it still holds the copied password."""
        copied, self._copied = self._copied, None
        if self._copy_src:
            GLib.source_remove(self._copy_src)
            self._copy_src = 0
        if copied is None:
            return
        clipboard = Gtk.Clipboard.get_default(Gdk.Display.get_default())
        text = clipboard.wait_for_text()
        now = digest(text) if text is not None else None
        if vault.clipboard_should_clear(now, copied):
            clipboard.clear()
            clipboard.store()


class PasswordsWindow(Gtk.Window):
    def __init__(self, manager):
        super().__init__(title="Passwords")
        self.manager = manager
        self.set_transient_for(manager.win)
        self.set_default_size(560, 520)
        self.get_style_context().add_class("cruxx-settings")
        self._timers = set()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(16)
        self.note = label("", "cruxx-note", wrap=True)
        box.pack_start(self.note, False, False, 0)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search saved passwords")
        self.search.connect("search-changed", lambda *_: self.list.invalidate_filter())
        box.pack_start(self.search, False, False, 0)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list.set_filter_func(self._match)
        holder = Gtk.ScrolledWindow()
        holder.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        holder.add(self.list)
        box.pack_start(holder, True, True, 0)
        self.add(box)
        self.connect("key-press-event", self._on_key)
        self.connect("destroy", self._on_destroy)
        box.show_all()

    def _on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False

    def _on_destroy(self, *_args):
        for source in list(self._timers):
            GLib.source_remove(source)
        self._timers.clear()

    def _match(self, row):
        needle = self.search.get_text().strip().lower()
        return not needle or needle in row.haystack

    def reload(self):
        self.note.set_text(self.manager.notice())
        self.manager.backend.list(None, self._listed)

    def _listed(self, found):
        for child in self.list.get_children():
            child.destroy()
        if found is None:
            self.note.set_text(self.manager.notice() or "Could not read the passwords.")
            return
        if not found:
            self.list.add(self._plain_row("No saved passwords."))
        for origin, username in found:
            self.list.add(self._account_row(origin, username))
        self.list.show_all()
        self.list.invalidate_filter()

    def _plain_row(self, text):
        row = Gtk.ListBoxRow()
        row.haystack = ""
        row.set_selectable(False)
        row.add(label(text, "muted"))
        return row

    def _account_row(self, origin, username):
        host = vault.origin_host(origin)
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.haystack = (host + " " + username).lower()
        line = Gtk.Box(spacing=6)
        line.set_border_width(6)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.pack_start(label(host, ellipsize=True), False, False, 0)
        text.pack_start(label(username or "(no user name)", "muted", ellipsize=True),
                        False, False, 0)
        shown = label("", "cruxx-note", ellipsize=True)
        shown.set_no_show_all(True)
        text.pack_start(shown, False, False, 0)
        line.pack_start(text, True, True, 0)
        manager = self.manager
        for title, action in (
                ("Copy user", lambda: self._copy_user(username)),
                ("Copy password", lambda: manager.copy_password(origin, username)),
                ("Show", lambda: self._reveal(origin, username, shown)),
                ("Delete", lambda: self._delete(origin, username))):
            line.pack_start(button(title, action), False, False, 0)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.pack_start(line, False, False, 0)
        outer.pack_start(divider(), False, False, 0)
        row.add(outer)
        return row

    def _copy_user(self, username):
        Gtk.Clipboard.get_default(Gdk.Display.get_default()).set_text(username, -1)

    def _reveal(self, origin, username, shown):
        def got(password):
            if password is None:
                return
            shown.set_text(password)
            shown.show()

            def hide():
                self._timers.discard(source)
                shown.set_text("")
                shown.hide()
                return False

            source = GLib.timeout_add_seconds(vault.REVEAL_SECONDS, hide)
            self._timers.add(source)

        self.manager.backend.get(origin, username, got)

    def _delete(self, origin, username):
        if not confirm(self, "Delete this password?",
                       "The saved password for %s on %s will be removed from the keyring."
                       % (username or "this account", vault.origin_host(origin)), "Delete"):
            return
        self.manager.backend.delete(origin, username, lambda _ok: self.reload())
