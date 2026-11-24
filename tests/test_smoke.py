import functools
import http.server
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@unittest.skipUnless(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"),
                     "no display")
class SmokeTest(unittest.TestCase):
    def test_load_and_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            www = os.path.join(tmp, "www")
            os.mkdir(www)
            with open(os.path.join(www, "index.html"), "w") as handle:
                handle.write("<!doctype html><title>smoke</title><p>hello</p>")
            handler = functools.partial(QuietHandler, directory=www)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            env = dict(os.environ)
            for name in ("DATA", "CACHE", "CONFIG", "STATE"):
                path = os.path.join(tmp, name.lower())
                os.mkdir(path)
                env["XDG_%s_HOME" % name] = path
            url = "http://127.0.0.1:%d/" % server.server_port
            result = subprocess.run(
                [sys.executable, "-m", "cruxx_browser", "--test-url", url,
                 "--test-exit-after-load"],
                cwd=ROOT, env=env, timeout=30, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            session = os.path.join(tmp, "data", "cruxx-browser", "session.json")
            # A test run uses a read only store: it writes no session.
            self.assertFalse(os.path.exists(session))


if __name__ == "__main__":
    unittest.main()
