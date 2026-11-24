"""One browser tab. A tab owns a WebView, or none until first use."""

import json
import logging
import os
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, Gio, GLib, WebKit2  # noqa: E402

from . import cleanlink, security, store  # noqa: E402

log = logging.getLogger(__name__)
WORLD = "cruxx"
POPUP_GAP_S = 1.0
# Navigation types that start a top-level load. See Tab._on_policy.
TOP_NAV_TYPES = ("LINK_CLICKED", "FORM_SUBMITTED", "BACK_FORWARD", "RELOAD")
RES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def read_resource(name):
    with open(os.path.join(RES_DIR, name), "r", encoding="utf-8") as handle:
        return handle.read()


def js_call(function_source, argument):
    """Return JS that calls FUNCTION_SOURCE with ARGUMENT as a JSON literal."""
    return "(" + function_source.strip() + ")(" + json.dumps(argument) + ");"


def rgba(hex_color):
    color = Gdk.RGBA()
    color.parse(hex_color)
    return color


class Tab:
    def __init__(self, win, url="", title="", pinned=False, private=False, peek=False):
        self.win = win
        # A peek tab lives in the floating card. It is not in a tab list until
        # the user opens it as a tab.
        self.peek = peek
        # True while the WebView is in the float window (see Window.toggle_float).
        self.floating = False
        self.stored_url = url
        self.stored_title = title
        self.pinned = pinned
        self.private = private
        self.view = None
        self.favicon = None
        self.blocked_popups = 0
        self.reader = False
        self.custom_title = ""
        self.last_active = time.monotonic()
        self.manager = None
        self._actions = []
        self._last_popup = None

    # state
    @property
    def url(self):
        if self.view is not None:
            return self.view.get_uri() or self.stored_url
        return self.stored_url

    @property
    def page_title(self):
        if self.view is not None and self.view.get_title():
            return self.view.get_title()
        return self.stored_title or self.url or "New tab"

    @property
    def title(self):
        return self.custom_title or self.page_title

    @property
    def host(self):
        return store.host_of(self.url)

    # view creation
    def ensure_view(self):
        """Create the WebView if needed. Load the stored URL."""
        if self.view is not None:
            return self.view
        win = self.win
        manager = WebKit2.UserContentManager()
        manager.register_script_message_handler_in_world("cruxxHide", WORLD)
        manager.connect("script-message-received::cruxxHide", self._on_hide_message)
        settings = WebKit2.Settings()
        security.apply_settings(settings, win.opts.dev, log)
        view = WebKit2.WebView(
            web_context=win.context(self.private),
            user_content_manager=manager,
            settings=settings)
        view.set_background_color(rgba(win.colors["background"]))
        self.view = view
        self.manager = manager
        self.update_hidden_script()
        for name, handler in (
                ("notify::title", self._on_meta),
                ("notify::uri", self._on_meta),
                ("notify::favicon", self._on_favicon),
                ("load-changed", self._on_load_changed),
                ("load-failed", self._on_load_failed),
                ("decide-policy", self._on_policy),
                ("create", self._on_create),
                ("permission-request", self._on_permission),
                ("context-menu", self._on_context_menu),
                ("mouse-target-changed", self._on_target),
                ("leave-notify-event", self._on_leave),
                ("load-failed-with-tls-errors", self._on_tls_error),
                ("enter-fullscreen", self._on_enter_fullscreen),
                ("leave-fullscreen", self._on_leave_fullscreen)):
            view.connect(name, handler)
        if self.peek:
            win.add_peek_view(self)
        else:
            win.add_view(self)
        url = self.stored_url
        if url:
            self.load(url)
        return view

    def load(self, url, clean=False):
        """Load URL. Set the shield state for its host just before the load.

        If CLEAN is true, the user started the load: remove tracking parameters.
        """
        if clean:
            url = cleanlink.clean_link(url)
        if not security.loadable(url):
            log.debug("load refused: scheme not allowed")
            return
        self.ensure_view()
        view = self.view
        self.stored_url = url
        host = store.host_of(url)

        def start():
            # The tab can close while the load waits for the shield.
            if view is None or self.view is not view:
                return
            self.tune_shield(host)
            view.load_uri(url)

        self.win.shield.when_ready(start)

    def tune_shield(self, host):
        win = self.win
        paused = win.store.shield_paused(host) or (
            self.private and store.registrable_host(host) in win.private_paused)
        on = win.store.settings["shield_enabled"] and not paused
        win.shield.set_active(self.manager, on)

    def update_hidden_script(self):
        """Replace the document-start script with the current rules."""
        if self.view is None:
            return
        self.manager.remove_all_scripts()
        source = js_call(read_resource("hidden.js"), self.win.store.hidden)
        self.manager.add_script(WebKit2.UserScript.new_for_world(
            source, WebKit2.UserContentInjectedFrames.TOP_FRAME,
            WebKit2.UserScriptInjectionTime.START, WORLD, None, None))

    def run_in_world(self, source):
        if self.view is not None:
            self.view.run_javascript_in_world(source, WORLD, None, None, None)

    # signal handlers
    def _on_meta(self, *_args):
        self.win.tab_changed(self)

    def _on_favicon(self, view, _pspec):
        self.favicon = view.get_favicon()
        self.win.tab_changed(self)

    def _on_load_changed(self, view, event):
        if event == WebKit2.LoadEvent.STARTED:
            self.reader = False
            self.blocked_popups = 0
            self.win.clear_permission_bars(self)
        if event == WebKit2.LoadEvent.COMMITTED:
            self.win.apply_zoom(self)
        self.win.load_changed(self, event)

    def _on_load_failed(self, _view, _event, _uri, _error):
        self.win.load_failed(self)
        return False

    def _on_policy(self, view, decision, kind):
        types = WebKit2.PolicyDecisionType
        if kind not in (types.NAVIGATION_ACTION, types.NEW_WINDOW_ACTION):
            return False
        action = decision.get_navigation_action()
        uri = action.get_request().get_uri()
        # WebKit 4.1 does not say which frame navigates. Subframe loads also
        # come here (iframe srcdoc and data: frames). WebKit itself blocks a
        # top-level data: navigation that a script starts. Thus treat a
        # navigation as main frame when it opens a window or the user starts it.
        main = kind == types.NEW_WINDOW_ACTION or action.is_user_gesture()
        verdict = security.scheme_decision(uri, main)
        if (verdict == "allow" and kind == types.NAVIGATION_ACTION and not self.peek
                and action.get_navigation_type() == WebKit2.NavigationType.LINK_CLICKED
                and not action.get_frame_name() and security.loadable(uri)
                and self._peek_held(action.get_modifiers())):
            # The user held the peek key and clicked a link: show it in a card.
            decision.ignore()
            GLib.idle_add(self.win.open_peek, self, uri)
            return True
        if verdict == "allow":
            nav = action.get_navigation_type()
            # Limit: WebKit does not say if a navigation is for the main frame.
            # Retune the shield only for user-started navigation of the main
            # frame (no frame name). A redirect or a script navigation is not
            # covered. Tab.load always tunes the shield for its own URL.
            if (kind == types.NAVIGATION_ACTION and not action.get_frame_name()
                    and nav in [getattr(WebKit2.NavigationType, n)
                                for n in TOP_NAV_TYPES]):
                self.tune_shield(store.host_of(uri))
            decision.use()
        else:
            decision.ignore()
            if verdict == "external" and action.is_user_gesture():
                GLib.idle_add(self.win.confirm_external, uri, self.host)
        return True

    def _peek_held(self, state):
        """Return True if STATE has the modifier key of the peek setting."""
        wanted = {"alt": Gdk.ModifierType.MOD1_MASK, "shift": Gdk.ModifierType.SHIFT_MASK}
        mask = wanted.get(self.win.store.settings["peek_modifier"])
        return mask is not None and bool(state & mask)

    def _on_create(self, view, action):
        if not action.is_user_gesture():
            self.blocked_popups += 1
            self.win.tab_changed(self)
            return None
        # Allow one popup tab for each gesture. Count the others as blocked.
        now = time.monotonic()
        if self._last_popup is not None and now - self._last_popup < POPUP_GAP_S:
            self.blocked_popups += 1
            self.win.tab_changed(self)
            return None
        uri = action.get_request().get_uri()
        if security.scheme_decision(uri, True) == "allow":
            self._last_popup = now
            self.win.open_tab(uri, private=self.private, clean=True)
        return None

    def _on_target(self, _view, hit, _modifiers):
        """Tell the window which link is under the pointer."""
        uri = hit.get_link_uri() if hit.context_is_link() else None
        self.win.link_hover(self, uri)

    def _on_leave(self, _view, _event):
        self.win.link_hover(self, None)
        return False

    def _on_permission(self, view, request):
        if self.peek:
            # A card has no permission bar. Deny the request.
            request.deny()
            return True
        return self.win.ask_permission(self, request)

    def _on_tls_error(self, view, failing_uri, certificate, errors):
        self.win.show_tls_error(self, failing_uri, errors)
        return True

    def _on_enter_fullscreen(self, _view):
        if self.peek:
            return True
        self.win.set_page_fullscreen(True)
        return False

    def _on_leave_fullscreen(self, _view):
        self.win.set_page_fullscreen(False)
        return False

    def _on_hide_message(self, _manager, result):
        value = result.get_js_value() if hasattr(result, "get_js_value") else result
        if value is not None and value.is_string():
            self.win.hide_selector(self, value.to_string())

    def _on_context_menu(self, view, menu, _event, hit):
        if not self.win.opts.dev:
            for item in list(menu.get_items()):
                if item.get_stock_action() == WebKit2.ContextMenuAction.INSPECT_ELEMENT:
                    menu.remove(item)
        if hit.context_is_link():
            link = hit.get_link_uri()
            if security.scheme_decision(link, True) == "allow":
                action = Gio.SimpleAction.new("open-in-new-tab", None)
                action.connect("activate", lambda *_a: self.win.open_tab(
                    link, private=self.private, background=True, clean=True))
                self._actions = [action]
                menu.append(WebKit2.ContextMenuItem.new_from_gaction(
                    action, "Open link in new tab", None))
        return False
