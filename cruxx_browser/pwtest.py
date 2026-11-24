"""Hidden test driver for the password feature (--test-action pwsave, pwfill).

It serves a small login page from 127.0.0.1 and drives it with JavaScript.
It uses the memory backend. It never touches the real keyring.
"""

import http.server
import logging
import threading

from gi.repository import GLib

log = logging.getLogger(__name__)
ACTIONS = ("pwsave", "pwfill")
USER, SECRET = "alice", "s3cret-pw"
LOGIN = (b"<!doctype html><title>login</title><form id=f method=post action=/home.html>"
         b"<input id=u name=u type=text><input id=p name=p type=password>"
         b"<button id=b type=submit>Sign in</button></form>")
HOME = b"<!doctype html><title>home</title><p>Welcome</p>"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _send(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(LOGIN if self.path.startswith("/login") else HOME)

    def do_POST(self):
        length = min(int(self.headers.get("Content-Length") or 0), 4096)
        self.rfile.read(length)
        self._send(HOME)


def start_server():
    """Start the server. Return (server, port)."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_port


class Driver:
    def __init__(self, app, action, port):
        self.app = app
        self.win = app.window
        self.action = action
        self.origin = "http://127.0.0.1:%d" % port
        self.login = self.origin + "/login.html"
        self.manager = self.win.passwords
        self.delay = self.manager.test_delay_ms
        self.loads = 0
        self.win.finished_cb = self._finished

    def _finished(self, _tab):
        self.loads += 1

    def fail(self, why):
        log.error("password test failed: %s", why)
        self.app._exit(5)
        return False

    def wait(self, check, then, why, seconds=10):
        state = {"left": seconds * 20}

        def poll():
            if check():
                then()
                return False
            state["left"] -= 1
            if state["left"] <= 0:
                self.fail("timeout: " + why)
                return False
            return True

        GLib.timeout_add(50, poll)

    def main_js(self, source, then):
        view = self.win.active.view

        def done(_view, result, _data=None):
            try:
                then(view.run_javascript_finish(result).get_js_value().to_string())
            except GLib.Error as exc:
                self.fail("script error: %s" % exc.message)

        view.run_javascript(source, None, done, None)

    def world_js(self, source):
        from .tab import WORLD
        self.win.active.view.run_javascript_in_world(source, WORLD, None, None, None)

    def start(self):
        if self.action == "pwfill":
            self.manager.backend.items[(self.origin, USER)] = SECRET
            self.step_focus()
        else:
            self.step_type()
        return False

    # pwsave: type, capture, submit, wait for the bar, wait for the save
    def step_type(self):
        self.main_js(
            "document.getElementById('u').value=%r;document.getElementById('p').value=%r;'ok'"
            % (USER, SECRET), lambda _r: self.step_capture())

    def step_capture(self):
        self.world_js("window.__cruxxPwTestSubmit(document.forms[0]);")
        self.wait(lambda: "pending" in self.manager.events, self.step_submit, "no pending submit")

    def step_submit(self):
        before = self.loads
        self.world_js("document.forms[0].submit();")
        self.wait(lambda: self.loads > before, lambda: self.wait(
            lambda: "offered" in self.manager.events, self.step_saved, "no offer bar"),
            "no page after submit")

    def step_saved(self):
        self.wait(lambda: "saved" in self.manager.events, self.step_check_saved, "not saved")

    def step_check_saved(self):
        if self.manager.backend.items != {(self.origin, USER): SECRET}:
            self.fail("wrong stored entries")
            return
        self.step_focus()

    # pwfill: load login, focus, popover, click
    def step_focus(self):
        before = self.loads
        self.win.active.load(self.login)
        self.wait(lambda: self.loads > before, self._focus_now, "login did not load")

    def _focus_now(self):
        self.world_js("window.__cruxxPwTestFocus(document.getElementById('p'));")
        self.wait(lambda: self.manager.popover is not None and self.manager.popover_buttons,
                  self.step_empty, "no popover")

    def step_empty(self):
        # Nothing is filled before the click.
        self.main_js("document.getElementById('u').value+'|'+document.getElementById('p').value",
                     self._after_empty)

    def _after_empty(self, text):
        if text != "|":
            self.fail("a field was filled before the click")
            return
        GLib.timeout_add(self.delay, self._click)

    def _click(self):
        self.manager.popover_buttons[0].clicked()
        self.wait(lambda: "filled" in self.manager.events, self.step_values, "no fill")
        return False

    def step_values(self):
        def check(text):
            if text != "%s|%s" % (USER, SECRET):
                self.fail("field values wrong")
                return
            GLib.timeout_add(self.delay, self.app._exit, 0)

        # Wait a moment: the script runs after the click.
        GLib.timeout_add(300, lambda: self.main_js(
            "document.getElementById('u').value+'|'+document.getElementById('p').value",
            check) or False)
