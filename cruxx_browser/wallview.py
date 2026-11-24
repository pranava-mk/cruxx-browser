"""The wall widget. It lies over the blank tab and under the other floating things.

It is a GTK widget, not web content. A picture is scaled to cover the
widget once for each size and the result is kept. A draw only paints the kept
pixbuf. A hidden widget keeps no pixbuf.
"""

import logging
import threading

import cairo
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from . import wall  # noqa: E402

log = logging.getLogger(__name__)
SOURCE_MAX = 3840
PIXELS_MAX = 40_000_000
RESIZE_DELAY_MS = 120


def _rgb(text):
    return tuple(int(text[i:i + 2], 16) / 255 for i in (1, 3, 5))


class WallView(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_app_paintable(True)
        self.kind = "off"
        self.spec = dict(wall.DEFAULT_WALL)
        self.background = "#000000"
        self._source = None
        self._cached = None
        self._timer = 0
        self._job = 0            # a new job number makes older results stale
        self.on_kind_change = None
        self.connect("draw", self._on_draw)
        self.connect("size-allocate", self._on_size)
        self._path = ""
        self.connect("unmap", lambda *_: self._release())
        self.connect("map", self._on_map)

    def configure(self, spec, omarchy_path, background):
        """Take a new wall choice. Return the kind that is in use now.

        A picture that cannot load makes the kind "off". A log line says why.
        """
        self.spec = spec
        self.background = background
        self._release()
        kind = spec["kind"]
        if kind in ("omarchy", "picture"):
            self._path = omarchy_path if kind == "omarchy" else spec["picture"]
            if wall.check_picture(self._path) is None:
                log.warning("wall picture refused: not a regular file of allowed size")
                kind = "off"
            elif self.get_mapped():
                # Show the plain background until the picture is ready.
                self._load_async(self._path)
            # A hidden widget keeps no pixbuf. The next map loads it.
        self.kind = kind
        self.queue_draw()
        return kind

    def _release(self):
        """Free the pixbufs and stop the resize timer."""
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self._cached = None
        self._source = None
        self._job += 1

    def _on_map(self, _w):
        if self.kind in ("omarchy", "picture") and self._source is None:
            self._load_async(self._path)

    def _load_async(self, path):
        """Load PATH in a thread. Hand the result to the main loop."""
        self._job += 1
        job = self._job

        def work():
            # Only GdkPixbuf runs here. No GTK call is safe in this thread.
            pixbuf = self._load(path)
            GLib.idle_add(self._loaded, job, pixbuf)

        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, job, pixbuf):
        """Take a loaded picture on the main loop. Ignore a stale result."""
        if job != self._job:
            return False
        if pixbuf is None:
            self.kind = "off"
            if self.on_kind_change:
                self.on_kind_change()
        else:
            self._source = pixbuf
            self._cached = None
        self.queue_draw()
        return False

    @staticmethod
    def _load(path):
        real = wall.check_picture(path)
        if real is None:
            log.warning("wall picture refused: not a regular file of allowed size")
            return None
        try:
            info = GdkPixbuf.Pixbuf.get_file_info(real)
            if info[0] is None or info[1] * info[2] > PIXELS_MAX:
                raise GLib.Error("picture is not readable or too large")
            if max(info[1], info[2]) > SOURCE_MAX:
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    real, SOURCE_MAX, SOURCE_MAX, True)
            return GdkPixbuf.Pixbuf.new_from_file(real)
        except (GLib.Error, TypeError) as exc:
            log.warning("wall picture failed to load: %s", getattr(exc, "message", exc))
            return None

    def _rescale(self, width, height):
        """Scale the source to cover WIDTH x HEIGHT. Crop it. Keep the result."""
        src = self._source
        if src is None or width < 1 or height < 1:
            self._cached = None
            return
        sw, sh, cx, cy = wall.cover_geometry(src.get_width(), src.get_height(),
                                             width, height)
        scaled = src.scale_simple(sw, sh, GdkPixbuf.InterpType.BILINEAR)
        self._cached = (width, height, scaled.new_subpixbuf(cx, cy, width, height).copy())

    def _on_size(self, _w, alloc):
        if self.kind not in ("omarchy", "picture"):
            return
        if self._source is None:
            return
        if self._cached is None:
            self._rescale(alloc.width, alloc.height)
            return
        if (self._cached[0], self._cached[1]) == (alloc.width, alloc.height):
            return
        # While the window changes size, wait until it stops.
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(RESIZE_DELAY_MS, self._after_resize)

    def _after_resize(self):
        self._timer = 0
        self._rescale(self.get_allocated_width(), self.get_allocated_height())
        self.queue_draw()
        return False

    def _on_draw(self, _w, ctx):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        ctx.set_source_rgb(*_rgb(self.background))
        ctx.paint()
        spec = self.spec
        if self.kind == "color":
            ctx.set_source_rgb(*_rgb(spec["color"]))
            ctx.paint()
        elif self.kind == "gradient":
            x0, y0, x1, y1 = wall.gradient_points(width, height, spec["angle"])
            grad = cairo.LinearGradient(x0, y0, x1, y1)
            grad.add_color_stop_rgb(0, *_rgb(spec["from"]))
            grad.add_color_stop_rgb(1, *_rgb(spec["to"]))
            ctx.set_source(grad)
            ctx.paint()
        elif self.kind in ("omarchy", "picture"):
            if self._cached is None:
                self._rescale(width, height)
            if self._cached is not None:
                Gdk.cairo_set_source_pixbuf(ctx, self._cached[2], 0, 0)
                ctx.paint()
        return True
