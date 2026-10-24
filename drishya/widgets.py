"""Shared widgets: labels and boxes, key caps, the vim-driven list (from
nāda), 16:9 thumbnails, and the video surface (mpv draws into a GLArea)."""
import hashlib
import logging

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from . import mpv

log = logging.getLogger("drishya.widgets")

# Nerd Font glyphs
G = {
    "eye": "\U000f0208", "prev": "\U000f04ae", "next": "\U000f04ad", "play": "\U000f040a", "pause": "\U000f03e4",
    "back": "\U000f0d2a", "fwd": "\U000f0d71", "vol": "\U000f057e", "mute": "\U000f075f", "dl": "\U000f01da",
    "yt": "\U000f05c3", "radio": "\U000f0439", "watch": "\U000f0567", "queue": "\U000f0cb8", "lib": "\U000f0fce",
    "history": "\U000f02da", "search": "\U000f0349", "folder": "\U000f024b", "film": "\U000f0231",
    "warn": "\U000f0026", "check": "\U000f012c", "full": "\U000f0293", "unfull": "\U000f0294", "cc": "\U000f0a6e",
    "speed": "\U000f04c5", "lock": "\U000f033e", "theater": "\U000f0379", "pip": "\U000f0a2e", "chapter": "\U000f0c7f",
}


def label(text="", cls=None, xalign=0.0, ellipsize=True, wrap=False, markup=False, **kw):
    w = Gtk.Label(xalign=xalign, **kw)
    if markup:
        w.set_markup(text)
    else:
        w.set_text(text or "")
    if ellipsize and not wrap:
        w.set_ellipsize(Pango.EllipsizeMode.END)
    if wrap:
        w.set_wrap(True)
        w.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        if "width_chars" not in kw:
            w.set_width_chars(18)   # else GTK measures it one character wide (and very tall)
        if "max_width_chars" not in kw:
            w.set_max_width_chars(46)   # and its natural width would stretch the window
    for c in (cls.split() if isinstance(cls, str) else cls or []):
        w.add_css_class(c)
    return w


def box(*children, vertical=False, spacing=0, cls=None, **kw):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing, **kw)
    for c in (cls.split() if isinstance(cls, str) else cls or []):
        b.add_css_class(c)
    for ch in children:
        if ch is not None:
            b.append(ch)
    return b


def keycap(text):
    return label(text, "keycap", ellipsize=False)


def hint(keys, what):
    b = box(spacing=5)
    for k in keys.split():
        b.append(keycap(k))
    b.append(label(what, "dim", ellipsize=False))
    return b


def esc(s):
    return GLib.markup_escape_text(s or "")


def fmt_bytes(n):
    for unit, k in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= k:
            return f"{n / k:.1f} {unit}"
    return f"{n} B"


_textures = {}


def texture(path, w, h):
    """A texture of an image file, cropped to w:h and scaled (cached)."""
    key = (path, w, h)
    if key in _textures:
        return _textures[key]
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(path)
    except GLib.Error:
        return None
    pw, ph = pb.get_width(), pb.get_height()
    if pw * h > ph * w:   # wider than w:h: crop the sides
        cw, ch = ph * w // h, ph
    else:                 # taller (a 4:3 thumbnail with bars): crop top and bottom
        cw, ch = pw, pw * h // w
    pb = pb.new_subpixbuf((pw - cw) // 2, (ph - ch) // 2, cw, ch).scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
    t = Gdk.Texture.new_for_pixbuf(pb)
    if len(_textures) > 400:
        _textures.clear()
    _textures[key] = t
    return t


def thumb_widget(path, w, h, glyph="\U000f0231", progress=None):
    """A rounded 16:9 thumbnail (or a placeholder with a glyph until it
    loads); progress (0..1) draws YouTube's red "watched" bar under it."""
    t = texture(path, w, h) if path else None
    if t is not None:
        pic = Gtk.Picture.new_for_paintable(t)
        pic.set_can_shrink(True)
        pic.set_content_fit(Gtk.ContentFit.COVER)
    else:
        pic = label(glyph, "glyph thumb-glyph", xalign=0.5, ellipsize=False)
    pic.set_size_request(w, h)
    over = Gtk.Overlay()
    over.set_child(pic)
    over.add_css_class("thumb")
    over.set_overflow(Gtk.Overflow.HIDDEN)
    over.set_size_request(w, h)
    over.set_valign(Gtk.Align.CENTER)
    over.set_halign(Gtk.Align.START)
    over.set_vexpand(False)
    over.set_hexpand(False)
    if progress:
        bar = Gtk.ProgressBar(fraction=max(0.02, min(1.0, progress)), valign=Gtk.Align.END)
        bar.add_css_class("watched")
        over.add_overlay(bar)
    return over


def tint(key):
    return int(hashlib.md5((key or "").encode()).hexdigest(), 16)


class RowList(Gtk.ScrolledWindow):
    """A scrolling list of selectable rows and section headers. Selection
    is ours (vim keys), not GTK's: sel is an index into the items."""

    def __init__(self, on_activate=None, on_select=None, row_height=54):
        super().__init__(hexpand=True, vexpand=True)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.inner = box(vertical=True, cls="list")
        self.set_child(self.inner)
        self.items, self.widgets = [], []
        self.sel, self.vstart = 0, None
        self.on_activate, self.on_select = on_activate, on_select
        self.placeholder = None
        self.row_height = row_height

    def set_rows(self, rows, keep=True, empty=None):
        """rows: [("header", widget) | ("item", data, widget)]."""
        old = self.items[self.sel] if keep and 0 <= self.sel < len(self.items) else None
        child = self.inner.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.inner.remove(child)
            child = nxt
        self.items, self.widgets = [], []
        for r in rows:
            if r[0] == "header":
                self.inner.append(r[1])
                continue
            _, data, w = r
            i = len(self.items)
            self.items.append(data)
            self.widgets.append(w)
            w.add_css_class("row")
            click = Gtk.GestureClick()
            click.connect("pressed", self._clicked, i)
            w.add_controller(click)
            self.inner.append(w)
        if not self.items and empty is not None:
            self.inner.append(empty)
        if old is not None and old in self.items:
            self.sel = self.items.index(old)
        self.sel = max(0, min(self.sel, len(self.items) - 1))
        if self.vstart is not None and self.vstart >= len(self.items):
            self.vstart = None
        self._paint()

    def _clicked(self, gesture, n, x, y, i):
        self.select(i)
        if n == 2 and self.on_activate:
            self.on_activate(self.items[i])

    def range(self):
        if self.vstart is None:
            return [self.sel] if self.items else []
        lo, hi = sorted((self.vstart, self.sel))
        return list(range(lo, hi + 1))

    def _paint(self):
        rng = set(self.range()) if self.vstart is not None else set()
        for i, w in enumerate(self.widgets):
            (w.add_css_class if i == self.sel else w.remove_css_class)("sel")
            (w.add_css_class if i in rng else w.remove_css_class)("vis")

    def select(self, i, scroll=True):
        if not self.items:
            return
        self.sel = max(0, min(len(self.items) - 1, i))
        self._paint()
        if scroll:
            GLib.idle_add(self._scroll)
        if self.on_select:
            self.on_select(self.selected())

    def move(self, n):
        self.select(self.sel + n)

    def selected(self):
        return self.items[self.sel] if 0 <= self.sel < len(self.items) else None

    def page(self):
        h = self.get_height() or 400
        return max(1, int(h / self.row_height / 2))

    def _scroll(self):
        if not (0 <= self.sel < len(self.widgets)):
            return False
        w = self.widgets[self.sel]
        ok, rect = w.compute_bounds(self.inner)
        if not ok:
            return False
        adj = self.get_vadjustment()
        top, bot = rect.get_y(), rect.get_y() + rect.get_height()
        if top - 36 < adj.get_value():
            adj.set_value(max(0, top - 36))
        elif bot + 12 > adj.get_value() + adj.get_page_size():
            adj.set_value(bot + 12 - adj.get_page_size())
        return False

    def visual(self, on=None):
        on = (self.vstart is None) if on is None else on
        self.vstart = self.sel if on else None
        self._paint()
        return on


class VideoArea(Gtk.GLArea):
    """Where the video plays: mpv's OpenGL renderer draws into this area.
    Only one area holds the renderer at a time (the window's or the mini
    player's): attach() takes it, detach() lets it go."""

    def __init__(self, core, owner_wanted):
        super().__init__(hexpand=True, vexpand=True)
        self.core = core
        self.wanted = owner_wanted     # () -> True when this area should show the video
        self.set_auto_render(False)
        self.set_has_depth_buffer(False)
        self.set_has_stencil_buffer(False)
        self.add_css_class("video")
        self.connect("realize", lambda *_: self.wanted() and self.attach())
        self.connect("unrealize", lambda *_: self.detach())
        self.connect("render", self._render)

    def attach(self):
        if not self.get_realized():
            return False
        if self.core.surface is self:
            return True
        self.make_current()
        if self.get_error() is not None:
            log.error("OpenGL: %s", self.get_error().message)
            self.core.toast(f"Can't show video: {self.get_error().message}")
            return False
        ok = self.core.attach_surface(self)
        self.queue_render()
        return ok

    def detach(self):
        if self.core.surface is self:
            if self.get_realized():
                self.make_current()   # mpv frees its GL objects in this context
            self.core.detach_surface(self)

    def _render(self, area, _ctx):
        if self.core.surface is not self:
            return False   # GTK clears it: black until the video is here
        s = self.get_scale_factor()
        self.core.draw(mpv.current_fbo(), self.get_width() * s, self.get_height() * s)
        return True
