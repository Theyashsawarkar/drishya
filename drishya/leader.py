"""The Space leader's widgets, shared with drishya (keep the two in step):
the which-key strip (what the next key can be, 300 ms after a prefix), the
palette (Space Space: every action here, fuzzy) and the key sheet (? and
Space ?), all built from the keymap (keymap.py, on Vyom's keys.py)."""
from gi.repository import GLib, Gtk

from . import keys
from .widgets import box, keycap, label

WHICH_DELAY = 300   # ms after a prefix before the strip shows (fast typing never sees it)


class WhichKey(Gtk.Box):
    """A rounded strip over the bottom of the window: the keys that can come
    next, groups ending in …"""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["menu", "whichkey"],
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.END, can_target=False, visible=False)
        self.title = label("", "menu-title")
        self.grid = Gtk.Grid(column_spacing=22, row_spacing=3)
        self.append(self.title)
        self.append(self.grid)
        self.append(label("Esc cancels", "dim menu-note"))
        self.timer = None

    def schedule(self, km, pending):
        """Show the strip for `pending` after WHICH_DELAY, unless a key comes first."""
        self.cancel()
        self.timer = GLib.timeout_add(WHICH_DELAY, self._show, km, pending)

    def cancel(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        self.set_visible(False)

    def _show(self, km, pending):
        self.timer = None
        items = km.next_keys(pending)
        if not items:
            return False
        child = self.grid.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.grid.remove(child)
            child = nxt
        name = km.group_name(pending)
        self.title.set_text(f"{keys.spell(pending)} › {name}")
        rows = max(1, (len(items) + 2) // 3)
        for i, (tok, what, is_group) in enumerate(sorted(items, key=lambda x: (x[2], x[0].lower()))):
            cell = box(keycap(keys.spell_token(tok)), label(what, "d" + (" group" if is_group else ""), ellipsize=False),
                       spacing=8)
            self.grid.attach(cell, i // rows, i % rows, 1, 1)
        self.set_visible(True)
        return False


class Palette(Gtk.Box):
    """Space Space: type to filter every action of this view, Enter runs it.
    Ctrl+j / Ctrl+k (or the arrows) move, Esc closes."""

    def __init__(self, run):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["menu", "palette"],
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.START, margin_top=70, visible=False)
        self.run = run
        self.entry = Gtk.Text(hexpand=True, placeholder_text="Run an action…")
        self.entry.add_css_class("palette-entry")
        self.entry.connect("changed", lambda *_: self._fill())
        self.list = box(vertical=True, spacing=2)
        sc = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=420)
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.add_css_class("noscrollbar")
        sc.set_child(self.list)
        self.scroll = sc
        self.append(box(label("", "palette-glyph"), self.entry, spacing=8))
        self.append(sc)
        self.rows, self.shown, self.sel = [], [], 0

    def open(self, rows):
        self.rows = rows
        self.entry.set_text("")
        self.set_visible(True)
        self._fill()
        self.entry.grab_focus()

    def close(self):
        self.set_visible(False)

    def _fill(self):
        q = self.entry.get_text()
        self.shown = [r for r in self.rows if keys.fuzzy(q, f"{r[1]} {r[0]}")]
        self.sel = 0
        child = self.list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.list.remove(child)
            child = nxt
        self.widgets = []
        for k, what, _b in self.shown[:60]:
            w = box(label(what, hexpand=True), box(*[keycap(t) for t in k.split()], spacing=3), spacing=10,
                    cls="menu-row")
            self.widgets.append(w)
            self.list.append(w)
        if not self.shown:
            self.list.append(label("Nothing matches", "dim menu-note"))
        self._paint()

    def _paint(self):
        for i, w in enumerate(self.widgets):
            (w.add_css_class if i == self.sel else w.remove_css_class)("sel")

    def key(self, name, ctrl):
        """True when the palette used the key (it takes every key while open)."""
        if name == "Escape":
            self.close()
            return True
        if name in ("Return", "KP_Enter"):
            pick = self.shown[self.sel] if 0 <= self.sel < len(self.shown) else None
            self.close()
            if pick:
                self.run(pick[2])
            return True
        if name in ("Down", "Up") or (ctrl and name in ("j", "k", "n", "p")):
            step = 1 if name in ("Down", "j", "n") else -1
            if self.widgets:
                self.sel = max(0, min(len(self.widgets) - 1, self.sel + step))
                self._paint()
            return True
        return False   # typing goes to the box


class KeySheet(Gtk.Box):
    """? and Space ?: every key of this view, from the keymap, grouped."""

    def __init__(self, commands=""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["help"],
                         valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, visible=False)
        self.title = label("", "h")
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=1,
                                column_spacing=34, row_spacing=14, homogeneous=False)
        sc = Gtk.ScrolledWindow(propagate_natural_height=True, propagate_natural_width=True, max_content_height=560)
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.add_css_class("noscrollbar")
        sc.set_child(self.flow)
        self.scroll = sc
        self.append(self.title)
        self.append(sc)
        if commands:
            self.append(label(commands, "d", wrap=True, max_width_chars=110))
        self.append(label("j / k scroll · ? or Esc closes", "dim"))

    def open(self, km, where, extra=()):
        child = self.flow.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.flow.remove(child)
            child = nxt
        self.title.set_text(f"KEYS · {where.upper()}")
        for section, rows in list(keys.help_rows(km)) + list(extra):
            col = box(label(section.upper(), "h"), vertical=True, spacing=4, valign=Gtk.Align.START)
            for k, d in rows:
                col.append(box(box(*[keycap(t) for t in k.split()], spacing=3), label(d, "d", ellipsize=False,
                                                                                      wrap=True, max_width_chars=44),
                               spacing=8))
            self.flow.append(col)
        self.scroll.get_vadjustment().set_value(0)
        self.set_visible(True)

    def key(self, name):
        if name in ("question", "Escape", "q"):
            self.set_visible(False)
        elif name in ("j", "k", "Down", "Up", "d", "u"):
            adj = self.scroll.get_vadjustment()
            step = 40 if name in ("j", "k", "Down", "Up") else adj.get_page_size() / 2
            adj.set_value(adj.get_value() + (step if name in ("j", "Down", "d") else -step))
        return True
