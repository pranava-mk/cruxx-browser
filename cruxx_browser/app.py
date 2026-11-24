"""Gtk.Application: single instance, command-line handling, start-up."""

import logging
import signal

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import omnibox, pwtest, store  # noqa: E402
from .shield import Shield  # noqa: E402
from .window import Window  # noqa: E402

log = logging.getLogger(__name__)
APP_ID = "dev.cruxx.Browser"
# Wayland app_id. It must be the same as the desktop file name and
# StartupWMClass. Omarchy finds the window with this name.
WM_CLASS = "cruxx-browser"
TEST_TIMEOUT_S = 25


class CruxxApp(Gtk.Application):
    def __init__(self, parse_args, unique=True):
        flags = Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        if not unique:
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=APP_ID, flags=flags)
        self._parse = parse_args
        self.window = None
        self.store = None
        self.shield = None
        self.opts = None
        self.exit_code = 0
        self._acted = False
        GLib.set_application_name("cruxx browser")
        # GTK3 sets the Wayland app_id from the program name.
        GLib.set_prgname(WM_CLASS)
        # Quit cleanly on a stop signal (for example at log out), so the
        # session and history are saved.
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._on_stop_signal)

    def _on_stop_signal(self):
        log.debug("stop signal received")
        self.quit()
        return GLib.SOURCE_REMOVE

    def do_command_line(self, cmdline):
        try:
            opts = self._parse(cmdline.get_arguments()[1:])
        except ValueError as exc:
            cmdline.printerr("cruxx-browser: %s\n" % exc)
            return 2
        if self.window is None:
            self._first_launch(opts)
        else:
            self._open_in_running(opts)
        return 0

    def _urls(self, opts):
        engine = self.store.settings["engine"]
        urls = (omnibox.classify(text, engine) for text in opts.urls)
        return [u for u in urls if u]

    def _first_launch(self, opts):
        self.opts = opts
        self.pw_port = 0
        if opts.test_action in pwtest.ACTIONS:
            # The password tests use a local page and the memory vault.
            self.pw_server, self.pw_port = pwtest.start_server()
            opts.test_url = "http://127.0.0.1:%d/login.html" % self.pw_port
            opts.test_vault = "memory"
        self.store = store.Store()
        self.shield = Shield(store.cache_dir())
        self.shield.compile()
        self.window = Window(self, opts, self.store)
        self.window.present()
        GLib.timeout_add_seconds(5, self._flush)
        if opts.test_url:
            self.window.finished_cb = self._test_finished
            if opts.test_sleep:
                self.window.finished_cb = self._sleep_probe_cb
            self.window.failed_cb = lambda _tab: self._exit(2)
            GLib.timeout_add_seconds(TEST_TIMEOUT_S, lambda: self._exit(3))
            GLib.idle_add(self._start_test, opts.test_url)
        else:
            GLib.idle_add(self._restore, self._urls(opts), 1 if opts.private else 0)

    def _restore(self, urls, private):
        self.window.restore_session(urls, private)
        return False

    def _start_test(self, url):
        self.window.open_tab(url)
        return False

    def _sleep_probe(self, tab):
        """Hidden test: sleep a loaded tab, wake it, exit 0 if all is right."""
        win = self.window
        state = {"step": 0}

        def check(done_tab):
            if state["step"] == 0:
                state["step"] = 1
                other = win.open_tab("about:blank")
                tab.last_active -= 10000
                win.sleep_override_min = 0.001
                win.sleep_tick()
                if tab.view is not None or other.view is None:
                    log.error("sleep probe: tab did not sleep")
                    self._exit(4)
                    return
                win.select_tab(tab)
                if tab.view is None:
                    log.error("sleep probe: tab did not wake")
                    self._exit(4)
            elif state["step"] == 1 and done_tab is tab:
                self._exit(0)

        win.finished_cb = check
        return False

    def _sleep_probe_cb(self, tab):
        self.window.finished_cb = None
        self._sleep_probe(tab)
        self.window.finished_cb(tab)

    def _test_finished(self, _tab):
        if self.opts.test_action:
            if not self._acted:
                self._acted = True
                # Wait a moment so that the page and its video can start.
                GLib.timeout_add(1500, self._run_action, self.opts.test_action)
            return
        if self.opts.test_exit_after_load:
            self._exit(0)

    def _run_action(self, action):
        """Hidden test: do one feature action, hold the window, then exit 0."""
        win = self.window
        hold = max(1, min(self.opts.test_hold, 20))
        if action in pwtest.ACTIONS:
            return pwtest.Driver(self, action, self.pw_port).start()
        if action == "wall":
            if win.store.settings["wall"]["kind"] == "off":
                win.set_option("wall", dict(win.store.settings["wall"], kind="omarchy"))
            win.open_tab()
            win.hide_prompts()
        elif action in ("peek", "peek-adopt"):
            win.open_peek(win.active, win.active.url)
            if action == "peek-adopt":
                GLib.timeout_add_seconds(3, lambda: win.adopt_peek() or False)
        elif action == "settings":
            win.open_settings("Themes")
        else:
            win.toggle_float()
            if action == "float-back":
                GLib.timeout_add_seconds(3, lambda: win.toggle_float() or False)
        GLib.timeout_add_seconds(hold, self._exit, 0)
        return False

    def _open_in_running(self, opts):
        for url in self._urls(opts):
            self.window.open_tab(url)
        if opts.private:
            self.window.open_tab(private=True)
        self.window.present()

    def _exit(self, code):
        if not self.exit_code:
            self.exit_code = code
        self.quit()
        return False

    def _flush(self):
        try:
            self.store.flush()
        except OSError as exc:
            log.warning("history flush failed: %s", exc)
        return True

    def do_shutdown(self):
        if self.window is not None:
            self.window.save_session()
            try:
                self.store.flush()
            except OSError as exc:
                log.warning("history flush failed: %s", exc)
        Gtk.Application.do_shutdown(self)
