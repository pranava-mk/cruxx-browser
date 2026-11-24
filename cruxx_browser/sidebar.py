"""The tab column (left) and the tab strip (top).

Sizes follow the upstream design. See docs/design-notes.md.
A row widget is made once for each tab. A change of title or icon updates
the row in place. The list is never rebuilt.
"""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from .widgets import Glyph, Mark, letter_for, track_hover  # noqa: E402

SIDE_WIDTH = 232
SIDE_PAD = 10
ROW_HEIGHT = 28
ROW_GAP = 2
PIN_SIZE = 34
PIN_GAP = 4
TOP_HEIGHT = 36
TAB_WIDTH = 186
TOP_PIN_WIDTH = 30
TOP_PLUS_WIDTH = 30

# Row metrics for each mode: left pad, mark, gap, right pad.
SIDE_ROW = {"lead": 10, "mark": 15, "gap": 8, "trail": 7}
TOP_ROW = {"lead": 11, "mark": 15, "gap": 6, "trail": 7}


DND_TARGET = "application/x-cruxx-tab"


def _targets():
    return [Gtk.TargetEntry.new(DND_TARGET, Gtk.TargetFlags.SAME_APP, 0)]


drop_targets = _targets


def make_source(widget, win, tab):
    """Let the user drag the row of TAB. Only inside this application."""
    widget.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, _targets(), Gdk.DragAction.MOVE)
    widget.connect("drag-begin", lambda _w, _ctx: win.drag_begin(tab))
    widget.connect("drag-end", lambda _w, _ctx: win.drag_end())
    widget.connect("drag-data-get", lambda _w, _c, sel, _i, _t: sel.set(sel.get_target(), 8, b"tab"))


def make_dest(widget, win, pin, tab=None, horizontal=False):
    """Accept a dragged tab on WIDGET. Drop before or after TAB, or at the end."""

    def motion(_w, ctx, _x, _y, stamp):
        if win.dragging is None:
            return False
        Gdk.drag_status(ctx, Gdk.DragAction.MOVE, stamp)
        return True

    def drop(w, ctx, x, y, stamp):
        if win.dragging is None:
            return False
        if horizontal:
            after = x > w.get_allocated_width() / 2
        else:
            after = y > w.get_allocated_height() / 2
        win.drop_tab(tab, after, pin)
        Gtk.drag_finish(ctx, True, False, stamp)
        return True

    widget.drag_dest_set(0, _targets(), Gdk.DragAction.MOVE)
    widget.connect("drag-motion", motion)
    widget.connect("drag-drop", drop)


class TabRow(Gtk.EventBox):
    """One tab: mark, title and a close button that shows on hover."""

    def __init__(self, win, tab, metrics, width=-1):
        super().__init__()
        self.win = win
        self.tab = tab
        self.set_visible_window(True)
        self.set_size_request(width, ROW_HEIGHT)
        make_source(self, win, tab)
        make_dest(self, win, False, tab, horizontal=width != -1)
        self._entry = None
        context = self.get_style_context()
        context.add_class("cruxx-row")
        box = Gtk.Box(spacing=metrics["gap"])
        self.box = box
        box.set_margin_start(metrics["lead"])
        box.set_margin_end(metrics["trail"])
        self.mark = Mark(metrics["mark"])
        self.label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.label.get_style_context().add_class("cruxx-title")
        self.close = Gtk.EventBox()
        self.close.set_visible_window(True)
        self.close.set_size_request(15, 15)
        self.close.set_valign(Gtk.Align.CENTER)
        self.close.add(Glyph("close", 15, 5, 1.3))
        self.close.get_style_context().add_class("cruxx-close")
        self.close.set_opacity(0)
        self.close.connect("button-press-event", self._on_close_press)
        box.pack_start(self.mark, False, False, 0)
        box.pack_start(self.label, True, True, 0)
        box.pack_end(self.close, False, False, 0)
        self.add(box)
        self.connect("button-press-event", self._on_press)
        track_hover(self, self._hover)
        self.close.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self._shown = None
        self.show_all()
        self.update(False)

    def _hover(self, on):
        self.close.set_opacity(1 if on else 0)

    def _on_close_press(self, _w, event):
        if event.button == 1:
            self.win.close_tab(self.tab)
        return True

    def _on_press(self, _w, event):
        if event.button == 1 and event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self.start_rename()
        elif event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            self.win.select_tab(self.tab)
        elif event.button == 2:
            self.win.close_tab(self.tab)
        elif event.button == 3:
            self.win.tab_menu(self.tab, event)
        return True

    def start_rename(self):
        """Show an entry in place of the title. Enter saves, Esc cancels."""
        if self._entry is not None:
            return
        entry = Gtk.Entry()
        entry.set_max_length(200)
        entry.set_text(self.tab.title)
        entry.connect("activate", lambda *_: self._finish(True))
        entry.connect("focus-out-event", lambda *_: self._finish(False) or False)
        entry.connect("key-press-event", self._on_entry_key)
        self._entry = entry
        self.label.hide()
        self.box.pack_start(entry, True, True, 0)
        self.box.reorder_child(entry, 1)
        entry.show()
        entry.grab_focus()

    def _on_entry_key(self, _entry, event):
        if event.keyval == Gdk.KEY_Escape:
            self._finish(False)
            return True
        return False

    def _finish(self, save):
        entry = self._entry
        if entry is None:
            return
        self._entry = None
        text = entry.get_text()
        self.box.remove(entry)
        self.label.show()
        if save:
            self.win.set_custom_title(self.tab, text)

    def update(self, live):
        tab = self.tab
        paired = self.win.pair_state(tab)
        state = (tab.title, tab.favicon, tab.url, live, tab.private, tab.blocked_popups,
                 paired)
        if state == self._shown:
            return
        self._shown = state
        if self.label.get_text() != tab.title:
            self.label.set_text(tab.title)
        blank = not tab.url or tab.url == "about:blank"
        self.mark.set_visible(not blank)
        self.mark.set_content(tab.favicon, letter_for(tab.url, tab.title))
        context = self.get_style_context()
        for name, on in (("live", live), ("private", tab.private),
                         ("paired", bool(paired))):
            (context.add_class if on else context.remove_class)(name)
        tip = tab.title + ("\n" + tab.url if tab.url else "")
        if self.get_tooltip_text() != tip:
            self.set_tooltip_text(tip)


class PinTile(Gtk.EventBox):
    """A pinned tab: a square with the favicon or a letter."""

    def __init__(self, win, tab, width, height):
        super().__init__()
        self.win = win
        self.tab = tab
        self.set_visible_window(True)
        self.set_size_request(width, height)
        make_source(self, win, tab)
        make_dest(self, win, True, tab, horizontal=True)
        self.get_style_context().add_class("cruxx-pin")
        self.mark = Mark(16, plain=True, letter_px=12)
        self.add(self.mark)
        self.connect("button-press-event", self._on_press)
        track_hover(self)
        self._shown = None
        self.show_all()
        self.update(False)

    def _on_press(self, _w, event):
        if event.button == 1 and event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self.start_rename()
        elif event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            self.win.select_tab(self.tab)
        elif event.button == 2:
            self.win.close_tab(self.tab)
        elif event.button == 3:
            self.win.tab_menu(self.tab, event)
        return True

    def start_rename(self):
        """Ask for a new title in a small popover."""
        popover = Gtk.Popover.new(self)
        entry = Gtk.Entry()
        entry.set_max_length(200)
        entry.set_text(self.tab.title)
        state = {"save": False}

        def activate(*_):
            state["save"] = True
            popover.popdown()

        def closed(*_):
            if state["save"]:
                self.win.set_custom_title(self.tab, entry.get_text())
            GLib.idle_add(popover.destroy)

        entry.connect("activate", activate)
        popover.connect("closed", closed)
        popover.set_border_width(6)
        popover.add(entry)
        entry.show()
        popover.popup()
        entry.grab_focus()

    def update(self, live):
        tab = self.tab
        state = (tab.title, tab.favicon, tab.url, live, tab.private)
        if state == self._shown:
            return
        self._shown = state
        self.mark.set_content(tab.favicon, letter_for(tab.url, tab.title))
        context = self.get_style_context()
        (context.add_class if live else context.remove_class)("live")
        self.set_tooltip_text(tab.title)


class NewRow(Gtk.EventBox):
    """The faded "New tab" row at the end of the list."""

    def __init__(self, win, wide):
        super().__init__()
        self.set_visible_window(True)
        context = self.get_style_context()
        context.add_class("cruxx-new")
        box = Gtk.Box(spacing=SIDE_ROW["gap"])
        box.set_halign(Gtk.Align.START if wide else Gtk.Align.CENTER)
        plus = Glyph("plus", 15, 9, 1.2)
        box.pack_start(plus, False, False, 0)
        if wide:
            self.set_size_request(-1, ROW_HEIGHT)
            box.set_margin_start(SIDE_ROW["lead"])
            box.pack_start(Gtk.Label(label="New tab"), False, False, 0)
        else:
            self.set_size_request(TOP_PLUS_WIDTH, ROW_HEIGHT)
            self.set_tooltip_text("New tab")
        self.add(box)
        self.win = win
        make_dest(self, win, False, None)
        self.connect("button-press-event", self._on_press)
        track_hover(self)
        self.show_all()

    def _on_press(self, _w, event):
        if event.button == 1:
            self.win.open_tab()
        return True


class SpaceBar(Gtk.Box):
    """A row of small round marks, one for each space. Click to switch."""

    SIZE = 18

    def __init__(self, win):
        super().__init__(spacing=2)
        self.win = win
        self.dots = []
        self._shown = None
        self.set_valign(Gtk.Align.CENTER)
        self.set_margin_start(6)

    def sync(self, spaces, current):
        """Make the marks match SPACES. Do nothing if nothing changed."""
        state = (tuple((sp.name, sp.icon) for sp in spaces), current)
        if state == self._shown:
            return
        self._shown = state
        for dot in self.dots:
            dot.destroy()
        self.dots = []
        for index, space in enumerate(spaces):
            dot = Gtk.EventBox()
            dot.set_visible_window(True)
            dot.set_size_request(self.SIZE, self.SIZE)
            dot.set_halign(Gtk.Align.START)
            dot.set_valign(Gtk.Align.CENTER)
            context = dot.get_style_context()
            context.add_class("cruxx-space")
            if index == current:
                context.add_class("live")
            dot.add(Gtk.Label(label=space.icon))
            dot.set_tooltip_text(space.name)
            dot.connect("button-press-event", self._on_press, index)
            track_hover(dot)
            self.pack_start(dot, False, False, 0)
            dot.show_all()
            self.dots.append(dot)

    def _on_press(self, dot, event, index):
        if event.button == 1:
            self.win.switch_space(index)
        elif event.button == 3:
            self.win.space_menu(index, event, dot)
        return True


class TabStrip:
    """Holds the left column and the top strip. Only one is shown."""

    def __init__(self, win, menu_button):
        self.win = win
        self.mode = "left"
        self.visible = True
        self.items = {}
        self.menu_button = menu_button
        self.spacebar = SpaceBar(win)

        # Left column: scrolled list, then the settings button at the bottom.
        self.pins_flow = Gtk.FlowBox()
        self.pins_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.pins_flow.set_homogeneous(True)
        self.pins_flow.set_column_spacing(PIN_GAP)
        self.pins_flow.set_row_spacing(PIN_GAP)
        self.pins_flow.set_min_children_per_line(1)
        self.pins_flow.set_max_children_per_line(
            (SIDE_WIDTH - 2 * SIDE_PAD + PIN_GAP) // (PIN_SIZE + PIN_GAP))
        self.pins_flow.set_halign(Gtk.Align.START)
        self.pins_flow.set_valign(Gtk.Align.START)
        self.pins_flow.set_no_show_all(True)
        make_dest(self.pins_flow, win, True, None, horizontal=True)
        self.rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=ROW_GAP)
        make_dest(self.rows_box, win, False, None)
        self.side_new = NewRow(win, True)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        column.set_margin_start(SIDE_PAD)
        column.set_margin_end(SIDE_PAD)
        column.set_margin_top(12)
        column.set_margin_bottom(8)
        column.pack_start(self.pins_flow, False, False, 0)
        column.pack_start(self.rows_box, False, False, 0)
        self.left_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.left_scroll.get_style_context().add_class("cruxx-scroll")
        self.left_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.left_scroll.add(column)
        self.left_foot = Gtk.Box()
        self.left_foot.set_margin_start(SIDE_PAD)
        self.left_foot.set_margin_bottom(SIDE_PAD)
        self.left_foot.set_margin_top(4)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.set_size_request(SIDE_WIDTH - 1, -1)
        side.get_style_context().add_class("cruxx-sidebar")
        side.pack_start(self.left_scroll, True, True, 0)
        side.pack_start(self.left_foot, False, False, 0)
        divider = Gtk.Box()
        divider.get_style_context().add_class("cruxx-divider")
        divider.set_size_request(1, -1)
        self.left = Gtk.Box()
        self.left.pack_start(side, False, False, 0)
        self.left.pack_start(divider, False, False, 0)

        # Top strip: one scrolled row, then the settings button.
        self.top_box = Gtk.Box(spacing=ROW_GAP)
        self.top_box.set_margin_start(8)
        make_dest(self.top_box, win, False, None, horizontal=True)
        self.top_box.set_valign(Gtk.Align.CENTER)
        self.top_scroll = Gtk.ScrolledWindow(hexpand=True)
        self.top_scroll.get_style_context().add_class("cruxx-scroll")
        self.top_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.top_scroll.add(self.top_box)
        self.top_foot = Gtk.Box()
        self.top_foot.set_margin_end(8)
        self.top_foot.set_valign(Gtk.Align.CENTER)
        self.top = Gtk.Box()
        self.top.set_size_request(-1, TOP_HEIGHT)
        self.top.get_style_context().add_class("cruxx-strip")
        self.top.pack_start(self.top_scroll, True, True, 0)
        self.top.pack_start(self.top_foot, False, False, 0)
        self.top_new = NewRow(win, False)
        self.top_new.set_valign(Gtk.Align.CENTER)
        self.top_new.set_halign(Gtk.Align.START)

        # Show the children first. Then the window may hide a whole part.
        self.left.show_all()
        self.top.show_all()
        for widget in (self.left, self.top):
            widget.set_no_show_all(True)
        self._apply_mode()

    # mode and visibility
    def set_mode(self, mode):
        if mode == self.mode:
            return
        self.mode = mode
        for entry in list(self.items.values()):
            entry.destroy()
        self.items.clear()
        self._apply_mode()

    def set_visible(self, visible):
        self.visible = visible
        self._apply_mode()

    def _apply_mode(self):
        left = self.mode == "left"
        self.left.set_visible(left and self.visible)
        self.top.set_visible((not left) and self.visible)
        foot = self.left_foot if left else self.top_foot
        button = self.menu_button
        for widget in (button, self.spacebar):
            parent = widget.get_parent()
            if parent is not foot:
                if parent is not None:
                    parent.remove(widget)
                foot.pack_start(widget, False, False, 0)
                widget.show_all()
        button.set_direction(Gtk.ArrowType.UP if left else Gtk.ArrowType.DOWN)

    def drag_zone(self, on):
        """Show an empty pin area while a tab is dragged, so it can be pinned."""
        if on:
            self.pins_flow.set_size_request(-1, PIN_SIZE)
            self.pins_flow.set_visible(True)
        else:
            self.pins_flow.set_size_request(-1, -1)
            self.pins_flow.set_visible(bool(self.pins_flow.get_children()))

    # content
    def sync(self, tabs, active):
        """Make the rows match TABS. Reuse the widgets that exist."""
        left = self.mode == "left"
        for tab in list(self.items):
            if tab not in tabs or self.items[tab].pin_state != tab.pinned:
                self.items.pop(tab).destroy()
        pins, rest = [], []
        for tab in tabs:
            if tab not in self.items:
                if tab.pinned:
                    widget = (PinTile(self.win, tab, PIN_SIZE, PIN_SIZE) if left
                              else PinTile(self.win, tab, TOP_PIN_WIDTH, ROW_HEIGHT))
                elif left:
                    widget = TabRow(self.win, tab, SIDE_ROW)
                else:
                    widget = TabRow(self.win, tab, TOP_ROW, TAB_WIDTH)
                widget.pin_state = tab.pinned
                if not left:
                    widget.set_valign(Gtk.Align.CENTER)
                self.items[tab] = widget
            (pins if tab.pinned else rest).append(self.items[tab])
        if left:
            self._place_flow(pins)
            self._place_box(self.rows_box, rest + [self.side_new])
            self.pins_flow.set_visible(bool(pins))
        else:
            self._place_box(self.top_box, pins + rest + [self.top_new])
        self.update_all(active)

    def _place_box(self, box, widgets):
        for index, widget in enumerate(widgets):
            if widget.get_parent() is not box:
                box.pack_start(widget, False, False, 0)
            box.reorder_child(widget, index)
        for child in box.get_children():
            if child not in widgets:
                box.remove(child)

    def _place_flow(self, widgets):
        wanted = list(widgets)
        current = [child.get_child() for child in self.pins_flow.get_children()]
        if current == wanted:
            return
        for child in self.pins_flow.get_children():
            inner = child.get_child()
            child.remove(inner)
            self.pins_flow.remove(child)
        for widget in wanted:
            self.pins_flow.add(widget)
        self.pins_flow.show_all()
        for child in self.pins_flow.get_children():
            child.set_can_focus(False)

    def update_all(self, active):
        for tab, widget in self.items.items():
            widget.update(tab is active)
        if active in self.items:
            GLib.idle_add(self._reveal, self.items[active])

    def update(self, tab, active):
        """Update the row of TAB in place."""
        widget = self.items.get(tab)
        if widget is not None:
            widget.update(tab is active)

    def _reveal(self, widget):
        scroll = self.left_scroll if self.mode == "left" else self.top_scroll
        alloc = widget.get_allocation()
        if self.mode == "left":
            if widget.get_parent() is self.rows_box:
                moved = widget.translate_coordinates(self.rows_box.get_parent(), 0, 0)
                if moved is not None:
                    scroll.get_vadjustment().clamp_page(moved[1], moved[1] + alloc.height)
        else:
            scroll.get_hadjustment().clamp_page(alloc.x, alloc.x + alloc.width)
        return False
