"""The floating search panel (/), shared with nāda: one box over
everything. Your own things answer at once, YouTube after a short pause;
Tab picks where to look; actions work on the selected row without leaving
the box. The app gives it a provider that answers queries:

    provider.scopes            ["All", "YouTube", ...]
    provider.instant(q, scope) -> [section]    quick answers (your files, history, commands)
    provider.remote(q, scope)  -> [section]    slow ones (YouTube); called on a worker thread
    provider.home()            -> [section]    the empty box (recently played…)
    provider.act(item, how)    how: play | next | add | download | open
    provider.prefix(q)         -> (scope or None, q without the prefix)

A section is {"title", "right" (optional), "items": [item], "top": bool};
an item is {"title", "sub", "badge": (text, css), "dur", "lead": () -> widget,
"kind" ("command", "link", "more" or anything), ...provider data}."""
import json
import os

from gi.repository import Gdk, GLib, Gtk

from .widgets import box, hint, keycap, label

DEBOUNCE_MS = 350
RECENT_MAX = 12


class SearchPanel(Gtk.Box):
    def __init__(self, win, provider, state_dir, placeholder):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.START,
                         css_classes=["search-panel"])
        self.win, self.provider = win, provider
        self.recent_path = os.path.join(state_dir, "recent-searches.json")
        self.scope = 0
        self.sel = 0
        self.items = []          # selectable items, in order
        self.rows = []           # their widgets
        self.gen = 0             # a newer query makes older answers stale
        self.timer = None
        self.remote_sections = []
        self.remote_for = None
        self.set_size_request(760, -1)

        self.entry = Gtk.Text(hexpand=True, placeholder_text=placeholder)
        self.entry.add_css_class("search-entry")
        self.entry.connect("changed", lambda *_: self._changed())
        self.spin = Gtk.Spinner(spinning=False, visible=False)
        top = box(label("\U000f0349", "glyph search-glyph", ellipsize=False), self.entry, self.spin, keycap("Esc"),
                  spacing=10, cls="search-top")
        self.scopebox = box(spacing=4, cls="search-scopes")
        self.list = box(vertical=True, cls="search-list")
        self.scroll = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=470)
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.add_css_class("noscrollbar")
        self.scroll.set_child(self.list)
        foot = box(hint("Tab", "where"), hint("Ctrl+j Ctrl+k", "move"), hint("Enter", "play"),
                   hint("Ctrl+Enter", "next"), hint("Shift+Enter", "add"), hint("Ctrl+d", "download"),
                   label("yt · lib · : to narrow", "dim", hexpand=True, xalign=1), spacing=14, cls="search-foot")
        for w in (top, self.scopebox, self.scroll, foot):
            self.append(w)

    # ------------------------------------------------------------ open / close
    def open(self, text="", scope=0):
        self.scope = scope
        self.set_visible(True)
        self.entry.set_text(text)
        self.entry.grab_focus()
        self.entry.set_position(-1)
        self._changed()

    def close(self):
        self.set_visible(False)
        self.gen += 1
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        self.spin.stop()
        self.spin.set_visible(False)

    # ------------------------------------------------------------ queries
    def query(self):
        """(scope index, the words) with a typed prefix applied."""
        text = self.entry.get_text()
        scope, q = self.provider.prefix(text)
        return (self.scope if scope is None else scope), q

    def _changed(self):
        self.sel = 0
        self.gen += 1
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        scope, q = self.query()
        self.remote_sections = []
        if q.strip() and self.provider.wants_remote(q, scope):
            self.spin.set_visible(True)
            self.spin.start()
            self.timer = GLib.timeout_add(DEBOUNCE_MS, self._ask_remote, self.gen, q, scope)
        else:
            self.spin.stop()
            self.spin.set_visible(False)
        self.render()

    def _ask_remote(self, gen, q, scope):
        self.timer = None

        def work():
            return self.provider.remote(q, scope)

        def then(sections):
            if gen == self.gen and self.get_visible():
                self.remote_sections = sections
                self.spin.stop()
                self.spin.set_visible(False)
                self.render(keep=True)

        def fail(e):
            if gen == self.gen:
                self.spin.stop()
                self.spin.set_visible(False)
                self.remote_sections = [{"title": "YouTube", "items": [], "note": f"Couldn't search YouTube: {e}"}]
                self.render(keep=True)
        self.win.core.bg(work, then, fail)
        return False

    # ------------------------------------------------------------ drawing
    def render(self, keep=False):
        scope, q = self.query()
        child = self.scopebox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.scopebox.remove(child)
            child = nxt
        for i, name in enumerate(self.provider.scopes):
            b = label(name, "search-scope on" if i == scope else "search-scope", ellipsize=False)
            g = Gtk.GestureClick()
            g.connect("pressed", lambda *_a, i=i: self.set_scope(i))
            b.add_controller(g)
            self.scopebox.append(b)
        if q.strip():
            sections = self.provider.instant(q, scope) + self.remote_sections
        else:
            sections = self._recent_section() + self.provider.home()
        sel_item = self.items[self.sel] if keep and 0 <= self.sel < len(self.items) else None
        child = self.list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.list.remove(child)
            child = nxt
        self.items, self.rows = [], []
        for sec in sections:
            if not sec.get("items") and not sec.get("note"):
                continue
            head = box(label(sec["title"].upper(), hexpand=True), cls="search-sect")
            if sec.get("right"):
                head.append(label(sec["right"], ellipsize=False))
            self.list.append(head)
            if sec.get("note"):
                self.list.append(label(sec["note"], "dim search-note", wrap=True))
            for it in sec.get("items", []):
                w = self._row(it, top=sec.get("top"))
                i = len(self.items)
                g = Gtk.GestureClick()
                g.connect("pressed", lambda _g, n, *_a, i=i: self._clicked(i, n))
                w.add_controller(g)
                self.items.append(it)
                self.rows.append(w)
                self.list.append(w)
        if not self.items and q.strip() and self.spin.get_visible():
            self.list.append(label("Searching YouTube…", "dim search-note", xalign=0.5))
        elif not self.items and q.strip():
            where = self.provider.scopes[scope]
            self.list.append(label(f"Nothing for “{q}”" + (f" in {where}" if scope else "") + " · Tab looks elsewhere",
                                   "dim search-note", xalign=0.5))
        if sel_item is not None and sel_item in self.items:
            self.sel = self.items.index(sel_item)
        self.sel = max(0, min(self.sel, len(self.items) - 1))
        self._paint()

    def _row(self, it, top=False):
        lead = it["lead"]() if it.get("lead") else None
        text = box(label(it.get("title") or "", "search-title" if not top else "search-top-title"),
                   label(it.get("sub") or "", "search-sub"), vertical=True, spacing=2, hexpand=True,
                   valign=Gtk.Align.CENTER)
        acts = box(spacing=10, cls="search-acts", valign=Gtk.Align.CENTER)
        for k, what in it.get("acts") or self._default_acts(it):
            acts.append(hint(k, what))
        kids = [lead, text, acts]
        if it.get("badge"):
            kids.append(label(it["badge"][0], f"badge {it['badge'][1]}", ellipsize=False, valign=Gtk.Align.CENTER))
        if it.get("dur"):
            kids.append(label(it["dur"], "dur", ellipsize=False, valign=Gtk.Align.CENTER))
        w = box(*kids, spacing=12, cls="search-row top" if top else "search-row")
        return w

    @staticmethod
    def _default_acts(it):
        kind = it.get("kind")
        if kind == "command":
            return [("Enter", "run")]
        if kind in ("recent", "more", "scope"):
            return [("Enter", "open")]
        if kind == "link":
            return [("Enter", "play"), ("Ctrl+d", "save")]
        return [("Enter", "play"), ("Ctrl+Enter", "next")]

    def _paint(self):
        for i, w in enumerate(self.rows):
            (w.add_css_class if i == self.sel else w.remove_css_class)("sel")
        if 0 <= self.sel < len(self.rows):
            GLib.idle_add(self._scroll_to, self.sel)

    def _scroll_to(self, i):
        if not (0 <= i < len(self.rows)):
            return False
        ok, rect = self.rows[i].compute_bounds(self.list)
        if ok:
            adj = self.scroll.get_vadjustment()
            top, bot = rect.get_y(), rect.get_y() + rect.get_height()
            if top - 30 < adj.get_value():
                adj.set_value(max(0, top - 30))
            elif bot + 8 > adj.get_value() + adj.get_page_size():
                adj.set_value(bot + 8 - adj.get_page_size())
        return False

    def refresh_thumbs(self):
        if self.get_visible():
            self.render(keep=True)

    # ------------------------------------------------------------ actions
    def set_scope(self, i):
        text = self.entry.get_text()
        _, q = self.provider.prefix(text)
        if q != text:
            self.entry.set_text(q)   # a typed prefix gives way to the chosen scope
        self.scope = i % len(self.provider.scopes)
        self._changed()

    def _clicked(self, i, n):
        self.sel = i
        self._paint()
        if n == 2:
            self.activate("play")

    def activate(self, how):
        if not (0 <= self.sel < len(self.items)):
            return
        it = self.items[self.sel]
        kind = it.get("kind")
        if kind == "recent":
            self.entry.set_text(it["query"])
            self.entry.set_position(-1)
            return
        _, q = self.query()
        if q.strip() and kind not in ("command",):
            self._remember(q.strip())
        keep_open = self.provider.act(it, how)
        if not keep_open:
            self.win.close_search()

    # ------------------------------------------------------------ recent searches
    def _recent(self):
        try:
            with open(self.recent_path) as f:
                r = json.load(f)
            return [x for x in r if isinstance(x, str)][:RECENT_MAX]
        except (OSError, ValueError):
            return []

    def _remember(self, q):
        r = [q] + [x for x in self._recent() if x.lower() != q.lower()]
        try:
            os.makedirs(os.path.dirname(self.recent_path), exist_ok=True)
            with open(self.recent_path, "w") as f:
                json.dump(r[:RECENT_MAX], f, ensure_ascii=False)
        except OSError:
            pass

    def clear_recent(self):
        try:
            os.remove(self.recent_path)
        except OSError:
            pass
        self.render()

    def _recent_section(self):
        r = self._recent()
        if not r:
            return []
        return [{"title": "Recent searches", "right": "Ctrl+x clears", "items": [
            {"kind": "recent", "query": q, "title": q, "sub": "", "lead": lambda: label("\U000f02da", "glyph search-lead-glyph",
                                                                                      ellipsize=False)}
            for q in r[:6]]}]

    # ------------------------------------------------------------ keys
    def key(self, name, state):
        """Keys while the panel is open: True when handled (else the box types it)."""
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if name == "Escape":
            self.win.close_search()
            return True
        if name in ("Tab", "ISO_Left_Tab") and not ctrl:
            self.set_scope(self.scope + (-1 if name == "ISO_Left_Tab" or shift else 1))
            return True
        if ctrl and name in ("j", "n", "Down") or name == "Down":
            self.sel = min(len(self.items) - 1, self.sel + 1)
            self._paint()
            return True
        if ctrl and name in ("k", "p", "Up") or name == "Up":
            self.sel = max(0, self.sel - 1)
            self._paint()
            return True
        if name in ("Return", "KP_Enter"):
            self.activate("next" if ctrl else "add" if shift else "play")
            return True
        if ctrl and name == "d":
            self.activate("download")
            return True
        if ctrl and name == "x":
            self.clear_recent()
            return True
        if ctrl and name == "u":
            self.entry.set_text("")
            return True
        return False
