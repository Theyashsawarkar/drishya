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
    "speed": "\U000f04c5", "lock": "\U000f033e", "sun": "\U000f00e0", "theater": "\U000f0379", "pip": "\U000f0a2e", "chapter": "\U000f0c7f",
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
        _textures[key] = _textures.pop(key)   # the newest last: the oldest go first
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
    if len(_textures) >= 400:
        del _textures[next(iter(_textures))]
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

    def __init__(self, on_activate=None, on_select=None, row_height=54, horizontal=False):
        super().__init__(hexpand=True, vexpand=True)
        self.horizontal = horizontal   # a shelf of cards, side by side (j k still move)
        if horizontal:
            self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        else:
            self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.inner = box(vertical=not horizontal, spacing=10 if horizontal else 0, cls="list shelf" if horizontal else "list")
        self.set_child(self.inner)
        self.items, self.widgets = [], []
        self.sel, self.vstart = 0, None
        self.on_activate, self.on_select = on_activate, on_select
        self.placeholder = None
        self.row_height = row_height
        self.painted = {"sel": set(), "vis": set()}

    def set_rows(self, rows, keep=True, empty=None):
        """rows: [("header", widget) | ("item", data, widget)]."""
        old = self.items[self.sel] if keep and 0 <= self.sel < len(self.items) else None
        child = self.inner.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.inner.remove(child)
            child = nxt
        self.items, self.widgets = [], []
        self.painted = {"sel": set(), "vis": set()}
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
        """Touches only the rows that change: this runs on every j and k."""
        want = {"sel": {self.sel} if self.widgets else set(),
                "vis": set(self.range()) if self.vstart is not None else set()}
        for cls, rows in want.items():
            for i in self.painted[cls] - rows:
                self.widgets[i].remove_css_class(cls)
            for i in rows - self.painted[cls]:
                self.widgets[i].add_css_class(cls)
        self.painted = want

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
        if self.horizontal:
            adj, top, bot = self.get_hadjustment(), rect.get_x(), rect.get_x() + rect.get_width()
        else:
            adj, top, bot = self.get_vadjustment(), rect.get_y(), rect.get_y() + rect.get_height()
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


class Timeline(Gtk.DrawingArea):
    """The video's timeline: chapters as segments with small gaps, what's
    buffered, what's played; thicker with a knob under the pointer. on_seek(t)
    on click or drag; on_hover(t, x) while the pointer moves over it (None
    when it leaves)."""

    def __init__(self, on_seek, on_hover):
        super().__init__(hexpand=True, height_request=22)
        self.add_css_class("timeline")
        self.on_seek, self.on_hover = on_seek, on_hover
        self.duration = self.pos = self.buffered = 0.0
        self.chapters, self.raw_chapters = [], None
        self.hover_x = None
        self.colors = {"played": (0.92, 0.44, 0.57), "rest": (1, 1, 1, 0.30), "buf": (1, 1, 1, 0.50)}
        self.set_draw_func(self._draw)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("leave", self._leave)
        self.add_controller(motion)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda _g, _n, x, _y: self._seek(x))
        self.add_controller(click)
        drag = Gtk.GestureDrag()
        drag.connect("drag-update", self._drag)
        self.add_controller(drag)
        self.set_cursor(Gdk.Cursor.new_from_name("pointer"))

    def set_accent(self, rgb):
        self.colors["played"] = rgb

    def update(self, duration, pos, buffered, chapters):
        duration, pos, buffered = duration or 0.0, pos or 0.0, buffered or 0.0
        same = chapters is self.raw_chapters and duration == self.duration
        width = self.get_width()
        if same and width:   # a redraw only when something would move a pixel
            step = duration / width
            if abs(pos - self.pos) < step and abs(buffered - self.buffered) < step:
                return
        if chapters is not self.raw_chapters:
            self.raw_chapters = chapters
            self.chapters = [c.get("time", 0) for c in chapters or [] if c.get("time", 0) > 0.5]
        self.duration, self.pos, self.buffered = duration, pos, buffered
        self.queue_draw()

    def time_at(self, x):
        w = self.get_width() or 1
        return max(0.0, min(1.0, x / w)) * self.duration

    def _seek(self, x):
        if self.duration:
            self.on_seek(self.time_at(x))

    def _drag(self, g, dx, _dy):
        ok, sx, _sy = g.get_start_point()
        if ok:
            self._seek(sx + dx)
            self.hover_x = sx + dx
            self.on_hover(self.time_at(sx + dx), sx + dx)

    def _motion(self, _c, x, _y):
        self.hover_x = x
        self.queue_draw()
        if self.duration:
            self.on_hover(self.time_at(x), x)

    def _leave(self, *_):
        self.hover_x = None
        self.queue_draw()
        self.on_hover(None, None)

    def _draw(self, _area, cr, w, h):
        if not self.duration:
            cr.set_source_rgba(1, 1, 1, 0.18)
            cr.rectangle(0, h / 2 - 1.5, w, 3)
            cr.fill()
            return
        thick = 7 if self.hover_x is not None else 5
        y = h / 2 - thick / 2
        # a soft dark edge under the whole line, so it reads over any picture
        cr.set_source_rgba(0, 0, 0, 0.35)
        cr.rectangle(0, y - 1, w, thick + 2)
        cr.fill()
        cuts = [0.0] + [c / self.duration for c in self.chapters if c < self.duration] + [1.0]
        gap = 3 if len(cuts) > 2 else 0
        played = self.pos / self.duration
        buf = min(1.0, (self.pos + self.buffered) / self.duration) if self.buffered else played
        for a, b in zip(cuts, cuts[1:], strict=False):
            x0, x1 = a * w + (gap / 2 if a > 0 else 0), b * w - (gap / 2 if b < 1 else 0)
            if x1 <= x0:
                continue
            for upto, color in ((1.0, self.colors["rest"]), (buf, self.colors["buf"]), (played, self.colors["played"])):
                end = min(x1, upto * w)
                if end > x0:
                    cr.set_source_rgba(*color) if len(color) == 4 else cr.set_source_rgb(*color)
                    cr.rectangle(x0, y, end - x0, thick)
                    cr.fill()
        if self.hover_x is not None:
            import math
            cr.set_source_rgb(*self.colors["played"])
            cr.arc(played * w, h / 2, 7, 0, 2 * math.pi)
            cr.fill()


class Ring(Gtk.DrawingArea):
    """The loading animation: an arc that turns while there's nothing to
    measure (asking YouTube), then a ring that fills as the first seconds of
    video come in. Its colour is the CSS colour of .ring (the theme's
    accent). It animates only while it's on screen."""

    def __init__(self, size=72):
        super().__init__(content_width=size, content_height=size, halign=Gtk.Align.CENTER,
                         valign=Gtk.Align.CENTER, can_target=False)
        self.add_css_class("ring")
        self.fill = None          # None: turning; 0..1: how full
        self.shown = 0.0          # the fill as drawn, easing towards fill
        self.tick = None
        self.t0 = GLib.get_monotonic_time()
        self.set_draw_func(self._draw)
        self.connect("map", lambda *_: self._start())
        self.connect("unmap", lambda *_: self._stop())

    def set_fill(self, fill):
        if fill is not None and self.fill is None:
            self.shown = 0.0
        self.fill = fill

    def _start(self):
        if self.tick is None:
            self.tick = self.add_tick_callback(self._frame)

    def _stop(self):
        if self.tick is not None:
            self.remove_tick_callback(self.tick)
            self.tick = None

    def _frame(self, *_):
        if self.fill is not None:
            self.shown += (self.fill - self.shown) * 0.12
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _draw(self, _area, cr, w, h):
        import math
        t = (GLib.get_monotonic_time() - self.t0) / 1e6
        cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 4
        cr.set_line_width(4.5)
        cr.set_line_cap(1)        # round
        cr.set_source_rgba(1, 1, 1, 0.14)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        c = self.get_color()
        cr.set_source_rgba(c.red, c.green, c.blue, 1)
        if self.fill is None:     # turning, the arc breathing in and out
            start = t * 2 * math.pi / 1.3
            span = math.pi * (0.55 + 0.4 * math.sin(t * 2.4))
        else:                     # filling from the top, with a slow glint going round
            start = -math.pi / 2
            span = max(0.04, min(1.0, self.shown)) * 2 * math.pi
        cr.arc(cx, cy, r, start, start + span)
        cr.stroke()
        if self.fill is not None:
            a = t * 2 * math.pi / 2.2
            cr.set_source_rgba(1, 1, 1, 0.55)
            cr.arc(cx + r * math.cos(a), cy + r * math.sin(a), 2.2, 0, 2 * math.pi)
            cr.fill()


class Loader(Gtk.Overlay):
    """The loading screen over the video, from pressing play until the
    picture moves: the video's thumbnail dimmed behind a Ring, its title,
    and what it's waiting for. A stall while playing shows only the ring
    over the paused picture."""

    def __init__(self):
        super().__init__(hexpand=True, vexpand=True, can_target=False, visible=False)
        self.add_css_class("loader")
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.backdrop = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.COVER)
        self.backdrop.add_css_class("loader-backdrop")
        self.set_child(self.backdrop)
        scrim = Gtk.Box(hexpand=True, vexpand=True)
        scrim.add_css_class("loader-scrim")
        self.add_overlay(scrim)
        self.ring = Ring()
        self.title = label("", "loader-title", xalign=0.5, wrap=True, lines=2, max_width_chars=52,
                           justify=Gtk.Justification.CENTER)
        self.note = label("", "loader-note", xalign=0.5, ellipsize=False)
        self.add_overlay(box(self.ring, self.title, self.note, vertical=True, spacing=10, halign=Gtk.Align.CENTER,
                             valign=Gtk.Align.CENTER))
        self.thumb_path = None

    def show_stage(self, stage, title, note, thumb_path, fill):
        stalled = stage == "stalled"
        (self.add_css_class if stalled else self.remove_css_class)("stalled")
        self.backdrop.set_visible(not stalled)
        if thumb_path != self.thumb_path:
            self.thumb_path = thumb_path
            self.backdrop.set_paintable(texture(thumb_path, 640, 360) if thumb_path else None)
        if self.title.get_text() != (title or ""):
            self.title.set_text(title or "")
        self.title.set_visible(bool(title) and not stalled)
        self.note.set_text(note)
        self.ring.set_fill(fill)
