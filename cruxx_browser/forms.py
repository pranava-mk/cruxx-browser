"""Small form helpers for the settings window and the site card.

All text that comes from a page or from the user is set with set_text.
No markup is used.
"""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Pango  # noqa: E402


def label(text, css=None, wrap=False, ellipsize=False, selectable=False):
    widget = Gtk.Label(xalign=0)
    widget.set_text(text)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_max_width_chars(48)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
    if selectable:
        widget.set_selectable(True)
    if css:
        widget.get_style_context().add_class(css)
    return widget


def divider():
    line = Gtk.Box()
    line.get_style_context().add_class("cruxx-divider")
    line.set_size_request(-1, 1)
    return line


def row(title, control=None, note=None):
    """Return a row: TITLE (and a muted NOTE) on the left, CONTROL on the right."""
    box = Gtk.Box(spacing=12)
    box.get_style_context().add_class("cruxx-formrow")
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    text.pack_start(label(title, wrap=True), False, False, 0)
    if note:
        text.pack_start(label(note, "cruxx-note", wrap=True), False, False, 0)
    box.pack_start(text, True, True, 0)
    if control is not None:
        control.set_valign(Gtk.Align.CENTER)
        box.pack_end(control, False, False, 0)
    return box


def switch(active, callback):
    """Return a switch. CALLBACK gets the new state (a bool)."""
    widget = Gtk.Switch()
    widget.set_active(active)
    widget.connect("notify::active", lambda w, _p: callback(w.get_active()))
    return widget


def choice(items, current, callback):
    """Return a drop-down. ITEMS is a list of (id, text) pairs, ids are strings."""
    widget = Gtk.ComboBoxText()
    for ident, text in items:
        widget.append(ident, text)
    widget.set_active_id(current)
    widget.connect("changed", lambda w: w.get_active_id() and callback(w.get_active_id()))
    return widget


def button(text, callback, css=None):
    widget = Gtk.Button()
    widget.set_label(text)
    widget.set_relief(Gtk.ReliefStyle.NONE)
    widget.get_style_context().add_class("cruxx-action")
    if css:
        widget.get_style_context().add_class(css)
    widget.connect("clicked", lambda *_: callback())
    return widget


def confirm(parent, question, detail, action):
    """Ask the user. Return True if the user chose ACTION."""
    dialog = Gtk.MessageDialog(
        transient_for=parent, modal=True, message_type=Gtk.MessageType.WARNING,
        buttons=Gtk.ButtonsType.NONE, text=question)
    dialog.format_secondary_text(detail)
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    dialog.add_button(action, Gtk.ResponseType.ACCEPT)
    dialog.set_default_response(Gtk.ResponseType.CANCEL)
    answer = dialog.run()
    dialog.destroy()
    return answer == Gtk.ResponseType.ACCEPT
