"""Small drawn widgets: glyphs, site marks. They read colours from CSS.

Icons are drawn with cairo. Thus they do not depend on an icon theme.
"""

import math

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gtk, Pango, PangoCairo  # noqa: E402

# Upstream: Icons.swift Mark. Corner radius is 22% of the size.
MARK_RADIUS = 0.22
MARK_TILE_ALPHA = 0.06
MARK_LETTER = 0.56


def rounded_path(cr, x, y, w, h, r):
    """Add a rounded rectangle to the cairo path."""
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _color(widget):
    context = widget.get_style_context()
    return context.get_color(widget.get_state_flags())


def _set(cr, rgba, factor=1.0):
    cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha * factor)


def draw_letter(widget, cr, text, size_px, weight, width, height, rgba):
    """Draw TEXT in the middle of the area, in the system UI font."""
    layout = PangoCairo.create_layout(cr)
    font = widget.get_style_context().get_font(widget.get_state_flags()).copy()
    font.set_absolute_size(size_px * Pango.SCALE)
    font.set_weight(weight)
    layout.set_font_description(font)
    layout.set_text(text, -1)
    _ink, logical = layout.get_pixel_extents()
    cr.move_to((width - logical.width) / 2 - logical.x,
               (height - logical.height) / 2 - logical.y)
    _set(cr, rgba)
    PangoCairo.show_layout(cr, layout)


class Glyph(Gtk.DrawingArea):
    """A small line icon. KIND is close, plus, sliders, up, down or bookmark."""

    def __init__(self, kind, size, extent, width=1.4):
        super().__init__()
        self.kind = kind
        self.extent = extent
        self.line = width
        self.set_size_request(size, size)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def _draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        cx, cy = w / 2, h / 2
        e = self.extent / 2
        _set(cr, _color(widget))
        cr.set_line_width(self.line)
        cr.set_line_cap(1)  # round
        cr.set_line_join(1)
        kind = self.kind
        if kind in ("close", "plus"):
            if kind == "close":
                cr.move_to(cx - e, cy - e)
                cr.line_to(cx + e, cy + e)
                cr.move_to(cx + e, cy - e)
                cr.line_to(cx - e, cy + e)
            else:
                cr.move_to(cx - e, cy)
                cr.line_to(cx + e, cy)
                cr.move_to(cx, cy - e)
                cr.line_to(cx, cy + e)
            cr.stroke()
        elif kind in ("up", "down"):
            d = -1 if kind == "up" else 1
            cr.move_to(cx - e, cy - d * e / 2)
            cr.line_to(cx, cy + d * e / 2)
            cr.line_to(cx + e, cy - d * e / 2)
            cr.stroke()
        elif kind == "sliders":
            for index, knob in enumerate((0.3, 0.7, 0.45)):
                y = cy + (index - 1) * e * 0.8
                cr.move_to(cx - e, y)
                cr.line_to(cx + e, y)
                cr.stroke()
                cr.arc(cx - e + 2 * e * knob, y, 1.7, 0, 2 * math.pi)
                cr.fill_preserve()
                cr.stroke()
        elif kind == "bookmark":
            cr.move_to(cx - e * 0.6, cy - e)
            cr.line_to(cx + e * 0.6, cy - e)
            cr.line_to(cx + e * 0.6, cy + e)
            cr.line_to(cx, cy + e * 0.5)
            cr.line_to(cx - e * 0.6, cy + e)
            cr.close_path()
            cr.stroke()
        elif kind == "search":
            cr.arc(cx - e * 0.15, cy - e * 0.15, e * 0.7, 0, 2 * math.pi)
            cr.stroke()
            cr.move_to(cx + e * 0.35, cy + e * 0.35)
            cr.line_to(cx + e, cy + e)
            cr.stroke()
        return False


class Mark(Gtk.DrawingArea):
    """A site mark: the favicon in a rounded square, or a letter tile.

    PLAIN draws the bare letter, with no tile, at LETTER_PX.
    """

    def __init__(self, size, plain=False, letter_px=None):
        super().__init__()
        self.size = size
        self.plain = plain
        self.letter_px = letter_px or size * MARK_LETTER
        self.icon = None
        self.letter = ""
        self.set_size_request(size, size)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def set_content(self, icon, letter):
        """Set the favicon surface (or None) and the fallback letter."""
        if icon is self.icon and letter == self.letter:
            return
        self.icon = icon
        self.letter = letter
        self.queue_draw()

    def _draw(self, widget, cr):
        size = self.size
        ink = _color(widget)
        if self.icon is not None:
            width, height = self.icon.get_width(), self.icon.get_height()
            if width and height:
                rounded_path(cr, 0, 0, size, size, size * MARK_RADIUS)
                cr.clip()
                cr.scale(size / width, size / height)
                cr.set_source_surface(self.icon, 0, 0)
                cr.get_source().set_filter(3)  # best
                cr.paint()
            return False
        if self.plain:
            draw_letter(widget, cr, self.letter, self.letter_px,
                        Pango.Weight.MEDIUM, size, size, ink)
            return False
        rounded_path(cr, 0, 0, size, size, size * MARK_RADIUS)
        _set(cr, ink, MARK_TILE_ALPHA)
        cr.fill()
        # The letter uses the muted step of the ink.
        muted = Gdk.RGBA(ink.red, ink.green, ink.blue, ink.alpha * 0.55)
        draw_letter(widget, cr, self.letter, self.letter_px,
                    Pango.Weight.MEDIUM, size, size, muted)
        return False


def track_hover(box, extra=None):
    """Add the CSS class "hover" to BOX while the pointer is on it.

    A child with its own window (a button) does not end the hover.
    """
    box.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)

    def enter(_w, _e):
        box.get_style_context().add_class("hover")
        if extra:
            extra(True)
        return False

    def leave(_w, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        box.get_style_context().remove_class("hover")
        if extra:
            extra(False)
        return False

    box.connect("enter-notify-event", enter)
    box.connect("leave-notify-event", leave)


def letter_for(url, title):
    """Return the letter that stands for a page.

    Use the first letter of the host. A local or numeric host says nothing,
    so use the first letter of the title there.
    """
    from . import store
    host = store.host_of(url or "")
    if host.startswith("www."):
        host = host[4:]
    if host and host[0].isalpha() and host != "localhost":
        return host[0].upper()
    for ch in title or "":
        if ch.isalnum():
            return ch.upper()
    return host[:1].upper() if host else ""
