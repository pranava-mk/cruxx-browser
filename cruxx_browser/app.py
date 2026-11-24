"""Gtk.Application: single instance, command-line handling, start-up."""

import logging
import signal

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import omnibox, store  # noqa: E402
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
        self.store = store.Store()
        self.shield = Shield(store.cache_dir())
        self.shield.compile()
        self.window = Window(self, opts, self.store)
        self.window.present()
        GLib.timeout_add_seconds(5, self._flush)
        if opts.test_url:
            self.window.finished_cb = self._test_finished
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

    def _test_finished(self, _tab):
        if self.opts.test_exit_after_load:
            self._exit(0)

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
