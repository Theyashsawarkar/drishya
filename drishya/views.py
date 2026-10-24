"""The tabs: Watch (the video), Up next (the queue), Library (a grid),
History, Downloads, and the YouTube results page (from the search panel).
Keys common to every list (j k gg G Ctrl+d/u V) are handled by the window;
each view handles its own."""
import os
import time

from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk

from . import config, library, store, youtube
from .util import fmt_time, track_name
from .widgets import G, RowList, Timeline, VideoArea, box, fmt_bytes, label, thumb_widget

TW, TH = 144, 81          # list thumbnails, 16:9
ROW_H = 95


def meta(it):
    """"Channel · 1.2M views · 3 years ago" (YouTube) or the folder (files)."""
    if it.get("yt"):
        parts = [it.get("channel") or "", youtube.views(it.get("views")), youtube.ago(it.get("uploaded"))]
    elif it.get("url"):
        import urllib.parse
        parts = [urllib.parse.urlparse(it["url"]).hostname or "", "live" if it.get("live") else "stream"]
    else:
        parts = [os.path.basename(os.path.dirname(it.get("file") or ""))]
    return " ".join(" · ".join(p for p in parts if p).split())


def section(text, right=None):
    b = box(label(text.upper(), hexpand=True), cls="sect", spacing=8)
    if right is not None:
        b.append(right)
    return b


def badge(text, kind):
    return label(text, f"badge {kind}", ellipsize=False, valign=Gtk.Align.CENTER)


def empty(glyph, text):
    return box(label(glyph, "glyph big", xalign=0.5, ellipsize=False),
               label(text, xalign=0.5, wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=60),
               vertical=True, spacing=12, cls="empty", valign=Gtk.Align.CENTER, vexpand=True)


class View:
    name = title = glyph = ""
    hints = []

    def __init__(self, win):
        self.win, self.core = win, win.core
        self.widget = None

    def list(self):
        return None

    def refresh(self, event=None):
        pass

    def key(self, k, n):
        return False

    def search(self, q):
        self.win.toast("Nothing to search here")

    def shown(self):
        pass

    def play(self, *items):
        """Plays items now (the rest after the first) and goes to the video."""
        self.core.add(list(items), "play")
        self.win.switch("watch")

    def progress(self, it):
        e = self.core.store.entry(it)
        if not e:
            return None
        if e.get("finished"):
            return 1.0
        d = e.get("duration") or it.get("duration") or 0
        return (e.get("pos") or 0) / d if d else None

    def row(self, it, right=(), cls=None, number=None, sub=None):
        """A video: thumbnail (with how much you watched), title, channel ·
        views · age, badges, length."""
        thumb = thumb_widget(self.win.thumb(it), TW, TH, G["yt"] if it.get("yt") else G["film"], self.progress(it))
        text = box(label(" ".join((it.get("title") or "?").split()), "title", wrap=True, max_width_chars=70, lines=2,
                         ellipsize=True), label(" ".join((meta(it) if sub is None else sub).split()), "sub", single_line_mode=True), vertical=True, spacing=3, hexpand=True,
                   valign=Gtk.Align.CENTER)
        text.get_first_child().set_ellipsize(3)   # Pango END, after two lines
        kids = [label(number, "no", xalign=1, ellipsize=False) if number is not None else None, thumb, text]
        kids += list(right)
        if it.get("duration"):
            kids.append(label(fmt_time(it["duration"]), "dur", xalign=1, ellipsize=False))
        w = box(*kids, spacing=12)
        for c in (cls or "").split():
            w.add_css_class(c)
        return w

    def badges(self, it):
        out = []
        c = self.core
        key = it.get("yt") or it.get("url")
        job = c.job_for(key) if key else None
        if job:
            out.append(badge(f"{G['dl']} {int(job['pct'])}%", "dl"))
        elif key and c.store.downloaded(key):
            out.append(badge("saved", "local"))
        elif it.get("file"):
            out.append(badge("file", "local"))
        if it.get("live"):
            out.append(badge("LIVE", "failed"))
        elif it.get("url"):
            out.append(badge("HLS" if ".m3u8" in it["url"].lower() else "link", "yt"))
        return out


# ===================================================================== watch
class Watch(View):
    """The video, with its controls over it (they fade while it plays), a
    timeline with chapters and preview frames, and on the side what's next,
    the chapters and the details. Fullscreen is zen: just the video."""
    name, title, glyph = "watch", "Watch", G["watch"]
    hints = [("space", "play"), ("h l", "±5 s"), ("Q", "settings"), ("Tab", "side"), ("f", "fullscreen")]
    SIDES = ["next", "chapters", "info"]

    def __init__(self, win):
        super().__init__(win)
        c = self.core
        self.area = VideoArea(c, lambda: not (win.app.mini and win.app.mini.get_visible()))
        self.over = Gtk.Overlay(hexpand=True, vexpand=True)
        self.over.add_css_class("stage")
        self.over.set_child(self.area)
        self.idle = empty(G["eye"], "Nothing playing.\n\n/ searches YouTube and your videos · 2 opens your library")
        self.idle.set_can_target(False)
        self.over.add_overlay(self.idle)
        self.center = label("", "glyph center-glyph", xalign=0.5, ellipsize=False, halign=Gtk.Align.CENTER,
                            valign=Gtk.Align.CENTER, can_target=False)
        self.over.add_overlay(self.center)

        # top: what it is
        self.v_title = label("", "v-title")
        self.v_meta = label("", "v-meta")
        self.v_chips = box(spacing=6, valign=Gtk.Align.START)
        self.top = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, valign=Gtk.Align.START,
                                transition_duration=180)
        self.top.set_child(box(box(self.v_title, self.v_meta, vertical=True, hexpand=True), self.v_chips,
                               spacing=12, cls="v-top"))
        self.over.add_overlay(self.top)

        # bottom: the timeline and the buttons
        self.timeline = Timeline(c.seek_to, self._hover)
        self.pp = self._btn(G["play"], "Play / pause  (space)", c.toggle, big=True)
        self.t_now = label("", "v-time", ellipsize=False)
        self.chap = label("", "v-chapter")
        self.volb = self._btn(G["vol"], "Mute  (m)", c.mute)
        self.ccb = self._btn("CC", "Subtitles  (c)", c.cycle_subs)
        self.fullb = self._btn(G["full"], "Fullscreen  (f)", win.toggle_fullscreen)
        row = box(self.pp, self._btn(G["next"], "Next video  (>)", c.next), self.volb, self.t_now, self.chap,
                  Gtk.Box(hexpand=True), self.ccb,
                  self._btn(G["speed"], "Settings: quality, speed, subtitles, audio  (Q)", win.open_settings),
                  self._btn(G["theater"], "Theater mode  (t)", win.toggle_theater),
                  self._btn(G["pip"], "Mini player  (z)", win.app.show_mini), self.fullb, spacing=4)
        self.bottom = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, valign=Gtk.Align.END,
                                   transition_duration=180)
        self.bottom.set_child(box(self.timeline, row, vertical=True, spacing=2, cls="v-bottom"))
        self.over.add_overlay(self.bottom)

        # the timeline's preview frame
        self.pv_pic = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.COVER)
        self.pv_pic.set_size_request(176, 99)
        self.pv_frame = box(self.pv_pic, cls="pv-frame")
        self.pv_chap = label("", "pv-chap", xalign=0.5)
        self.pv_time = label("", "pv-time", xalign=0.5, ellipsize=False)
        self.preview = box(self.pv_frame, self.pv_chap, self.pv_time, vertical=True, spacing=2, halign=Gtk.Align.START,
                           valign=Gtk.Align.END, can_target=False, visible=False, cls="pv")
        self.over.add_overlay(self.preview)
        self.pv_want = None

        # zen (fullscreen): a small corner readout, nothing else
        self.zen = label("", "zen", ellipsize=False, halign=Gtk.Align.END, valign=Gtk.Align.END, can_target=False)
        self.zen_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, halign=Gtk.Align.END,
                                    valign=Gtk.Align.END, can_target=False, transition_duration=200)
        self.zen_rev.set_child(self.zen)
        self.over.add_overlay(self.zen_rev)
        self.zen_timer = self.hide_timer = None
        self.hovering_controls = False

        for w in (self.top, self.bottom):
            m = Gtk.EventControllerMotion()
            m.connect("enter", lambda *_: setattr(self, "hovering_controls", True))
            m.connect("leave", lambda *_: setattr(self, "hovering_controls", False))
            w.add_controller(m)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda *_: self.poke())
        self.over.add_controller(motion)
        click = Gtk.GestureClick()
        click.connect("pressed", self._clicked)
        self.area.add_controller(click)

        # the side: Up next · Chapters · Info
        self.side_tab = "next"
        self.side_btns = {}
        tabs = box(spacing=4, cls="side-tabs")
        for name, text in (("next", "Up next"), ("chapters", "Chapters"), ("info", "Info")):
            b = label(text, "chip", ellipsize=False)
            g = Gtk.GestureClick()
            g.connect("pressed", lambda *_a, n=name: self.set_side(n))
            b.add_controller(g)
            self.side_btns[name] = b
            tabs.append(b)
        tabs.append(Gtk.Box(hexpand=True))
        self.auto_chip = label("", "chip", ellipsize=False)
        tabs.append(self.auto_chip)
        self.upnext = RowList(on_activate=lambda it: c.play_index(c.queue.index(it)), row_height=62)
        self.chapters = RowList(on_activate=lambda ch: c.seek_to(ch.get("time", 0)), row_height=40)
        self.info = label("", "info", wrap=True, width_chars=38, max_width_chars=44, selectable=True,
                          valign=Gtk.Align.START, hexpand=True)
        info_sc = Gtk.ScrolledWindow(vexpand=True)
        info_sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        info_sc.set_child(box(self.info, cls="info-box"))
        self.side_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        self.side_stack.add_named(self.upnext, "next")
        self.side_stack.add_named(self.chapters, "chapters")
        self.side_stack.add_named(info_sc, "info")
        self.side = box(tabs, self.side_stack, vertical=True, cls="side")
        self.side.set_size_request(360, -1)
        self.side.set_hexpand(False)
        self.widget = box(self.over, self.side)
        self.set_side("next")

    # ------------------------------------------------------------ building
    def _btn(self, glyph, tip, cb, big=False):
        b = Gtk.Button(tooltip_text=tip, valign=Gtk.Align.CENTER)
        b.set_child(label(glyph, ellipsize=False, xalign=0.5))
        b.add_css_class("vbtn")
        if big:
            b.add_css_class("big")
        b.set_focusable(False)
        b.connect("clicked", lambda *_: cb())
        return b

    def _clicked(self, _g, n, _x, _y):
        if n == 2:
            self.win.toggle_fullscreen()
        else:
            self.core.toggle()

    def list(self):
        if self.side_tab == "next":
            return self.upnext
        if self.side_tab == "chapters":
            return self.chapters
        return None

    def set_side(self, name):
        self.side_tab = name
        self.side_stack.set_visible_child_name(name)
        for n, b in self.side_btns.items():
            (b.add_css_class if n == name else b.remove_css_class)("act")
        if name == "info":
            self.core.details(lambda d: self._fill_info())
            self._fill_info()

    def set_theater(self, on):
        self.side.set_visible(not on)

    # ------------------------------------------------------------ showing the controls
    def poke(self, secs=2.5):
        """Something happened (a key, the mouse): show the controls, then let
        them fade while the video plays. Fullscreen shows none (zen)."""
        if self.win.fullscreened:
            return
        self.top.set_reveal_child(self.core.current is not None)
        self.bottom.set_reveal_child(True)
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
        self.hide_timer = GLib.timeout_add(int(secs * 1000), self._fade)

    def _fade(self):
        self.hide_timer = None
        c = self.core
        if self.win.fullscreened or (c.current is not None and not c.paused and not c.idle and not self.hovering_controls):
            self.top.set_reveal_child(False)
            self.bottom.set_reveal_child(False)
            self.preview.set_visible(False)
        elif self.hovering_controls:
            self.hide_timer = GLib.timeout_add(1500, self._fade)
        return False

    def zen_note(self, text, secs=1.2):
        """Fullscreen's only feedback: a small readout in the corner."""
        if not self.win.fullscreened:
            self.poke()
            return
        self.zen.set_text(text)
        self.zen_rev.set_reveal_child(True)
        if self.zen_timer:
            GLib.source_remove(self.zen_timer)
        self.zen_timer = GLib.timeout_add(int(secs * 1000), self._zen_hide)

    def _zen_hide(self):
        self.zen_timer = None
        self.zen_rev.set_reveal_child(False)
        return False

    def enter_zen(self, on):
        self.top.set_reveal_child(False if on else self.core.current is not None)
        self.bottom.set_reveal_child(not on)
        self.preview.set_visible(False)
        self.set_theater(on or self.win.theater)
        if not on:
            self.zen_rev.set_reveal_child(False)
            self.poke()

    # ------------------------------------------------------------ hover preview
    def _hover(self, t, x):
        if t is None:
            self.preview.set_visible(False)
            self.pv_want = None
            return
        self.poke()
        c = self.core
        ch = self._chapter_at(t)
        self.pv_chap.set_text(ch)
        self.pv_chap.set_visible(bool(ch))
        self.pv_time.set_text(fmt_time(t))
        ok, rect = self.timeline.compute_bounds(self.over)
        left = (rect.get_x() if ok else 0) + x - 90
        self.preview.set_margin_start(int(max(8, min(left, self.over.get_width() - 190))))
        self.preview.set_margin_bottom(int(self.over.get_height() - (rect.get_y() if ok else 0) + 6))
        self.preview.set_visible(True)
        want = round(t / 5)
        if want == self.pv_want:
            return
        self.pv_want = want

        def got(r, want=want):
            if r is None or want != self.pv_want:
                return
            path, x0, y0, w, h = r
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(path)
                if w and h:
                    pb = pb.new_subpixbuf(x0, y0, min(w, pb.get_width() - x0), min(h, pb.get_height() - y0))
                self.pv_pic.set_paintable(Gdk.Texture.new_for_pixbuf(pb))
                self.pv_frame.set_visible(True)
            except GLib.Error:
                pass
        self.pv_frame.set_visible(self.pv_pic.get_paintable() is not None)
        c.preview(t, got)

    def _chapter_at(self, t):
        name = ""
        for ch in self.core.chapters:
            if ch.get("time", 0) <= t + 0.1:
                name = ch.get("title") or ""
        return name

    # ------------------------------------------------------------ refreshing
    def tick(self, t):
        c = self.core
        self.timeline.update(c.duration, t, c.buffered, c.chapters)
        d = c.duration
        self.t_now.set_text(f"{fmt_time(t)} / {fmt_time(d)}" if d else (fmt_time(t) if c.current else ""))
        ch = self._chapter_at(t)
        self.chap.set_text(f"· {ch}" if ch else "")

    def refresh(self, event=None):
        c = self.core
        cur = c.current
        if event in (None, "video", "player", "buffering"):
            self.idle.set_visible(cur is None or (c.idle and not c.render_ready))
            if c.player_error:
                self.idle.get_last_child().set_text(f"Can't play video: {c.player_error}")
            glyph = ""
            if cur is not None and c.buffering:
                glyph = G["radio"]
            elif cur is not None and c.paused and not c.idle and not self.win.fullscreened:
                glyph = G["pause"]
            self.center.set_text(glyph)
            self.center.set_visible(bool(glyph))
            self.pp.get_child().set_text(G["play"] if c.paused or c.idle else G["pause"])
            self.volb.get_child().set_text(G["mute"] if c.muted or c.volume == 0 else G["vol"])
            self.fullb.get_child().set_text(G["unfull"] if self.win.fullscreened else G["full"])
            if event == "player" and c.paused:
                self.poke(30)   # paused: the controls stay
        if event in (None, "video", "history"):
            self.v_title.set_text(cur.get("title") or "" if cur else "")
            if cur is None:
                self.v_meta.set_text("")
            else:
                parts = [cur.get("channel") or (os.path.dirname(cur.get("file") or "").replace(os.path.expanduser("~"), "~")
                                                if cur.get("file") else meta(cur)),
                         youtube.views(cur.get("views")), youtube.ago(cur.get("uploaded"))]
                self.v_meta.set_text(" · ".join(p for p in parts if p))
            if self.side_tab == "info":
                self._fill_info()
        if event in (None, "video", "tracks", "player", "options"):
            self._chips()
            self._chapters()
            self.auto_chip.set_text(f"autoplay {'on' if c.autoplay else 'off'} · M")
            (self.auto_chip.add_css_class if c.autoplay else self.auto_chip.remove_css_class)("act")
            subs = any(t.get("type") == "sub" for t in c.tracks)
            self.ccb.set_sensitive(subs)
            (self.ccb.add_css_class if any(t.get("type") == "sub" and t.get("selected") for t in c.tracks)
             else self.ccb.remove_css_class)("on")
        if event in (None, "queue", "video", "thumbs", "options", "downloads"):
            rows = []
            nxt = c.queue[c.cur + 1:c.cur + 9] if c.cur >= 0 else c.queue[:8]
            for it in nxt:
                thumb = thumb_widget(self.win.thumb(it), 104, 58, G["yt"] if it.get("yt") else G["film"], self.progress(it))
                text = box(label(it.get("title") or "?", "t", wrap=True, max_width_chars=26, lines=2),
                           label(it.get("channel") or meta(it), "a"), vertical=True, spacing=2, hexpand=True,
                           valign=Gtk.Align.CENTER)
                text.get_first_child().set_ellipsize(3)
                w = box(thumb, text, spacing=10, cls="upnext-row")
                if it.get("auto"):
                    w.add_css_class("auto")
                rows.append(("item", it, w))
            msg = ("Autoplay finds more when this ends" if c.autoplay else "Nothing next · M turns autoplay on")
            self.upnext.set_rows(rows, empty=label(msg, "dim", xalign=0.5, wrap=True, margin_top=20))

    def _chips(self):
        c = self.core
        child = self.v_chips.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.v_chips.remove(child)
            child = nxt
        if c.current is None:
            return
        h = c.current_height()
        if h:
            self.v_chips.append(label(f"{h}p", "vchip", ellipsize=False))
        sub = next((t for t in c.tracks if t.get("type") == "sub" and t.get("selected")), None)
        if sub:
            self.v_chips.append(label(f"CC {track_name(sub)}", "vchip", ellipsize=False, max_width_chars=16))
        if c.speed != 1:
            self.v_chips.append(label(f"{c.speed:g}×", "vchip", ellipsize=False))
        if c.current.get("live"):
            self.v_chips.append(label("● LIVE", "vchip live", ellipsize=False))
        elif c.downloaded(c.current) and not c.current.get("file"):
            self.v_chips.append(label("from disk", "vchip", ellipsize=False))

    def _chapters(self):
        c = self.core
        rows = []
        for i, ch in enumerate(c.chapters):
            cur = i == c.chapter
            w = box(label(fmt_time(ch.get("time", 0)), "dur", ellipsize=False),
                    label(ch.get("title") or f"Chapter {i + 1}", "title", hexpand=True), spacing=12,
                    cls="chapter-row playing" if cur else "chapter-row")
            rows.append(("item", ch, w))
        self.side_btns["chapters"].set_text(f"Chapters · {len(c.chapters)}" if c.chapters else "Chapters")
        self.chapters.set_rows(rows, empty=label("This video has no chapters", "dim", xalign=0.5, margin_top=20))

    def _fill_info(self):
        c = self.core
        cur = c.current
        if cur is None:
            self.info.set_text("")
            return
        lines = [cur.get("title") or ""]
        if cur.get("yt"):
            lines.append(youtube.watch_url(cur["yt"]))
        elif cur.get("url"):
            lines.append(cur["url"])
        elif cur.get("file"):
            lines.append(cur["file"])
        facts = []
        if cur.get("views"):
            facts.append(f"{cur['views']:,} views")
        if cur.get("uploaded"):
            facts.append(time.strftime("%d %b %Y", time.localtime(cur["uploaded"])))
        h = c.current_height()
        if h:
            facts.append(f"{h}p")
        if facts:
            lines.append(" · ".join(facts))
        d = c._details.get(cur.get("yt")) if cur.get("yt") else None
        if d and d.get("description"):
            lines += ["", d["description"]]
        elif cur.get("yt"):
            lines += ["", "Loading the description…"]
        self.info.set_text("\n".join(lines))

    # ------------------------------------------------------------ keys
    def key(self, k, n):
        c = self.core
        step = c.conf["fine_step"]
        if k == "h":
            c.seek(-step * n)
            self.win.feedback(f"{G['back']} {step * n} s")
            return True
        if k == "l":
            c.seek(step * n)
            self.win.feedback(f"{G['fwd']} {step * n} s")
            return True
        if k == "Tab":
            self.set_side(self.SIDES[(self.SIDES.index(self.side_tab) + 1) % len(self.SIDES)])
            if self.win.theater:
                self.win.toggle_theater()
            return True
        if k == "Return":
            lst = self.list()
            sel = lst.selected() if lst else None
            if self.side_tab == "chapters" and sel is not None:
                c.seek_to(sel.get("time", 0))
            elif sel is not None and sel in c.queue:
                c.play_index(c.queue.index(sel))
            else:
                c.toggle()
            return True
        return False


# ===================================================================== up next (the queue)
class Queue(View):
    name, title, glyph = "queue", "Up next", G["queue"]
    hints = [("Enter", "play"), ("dd", "remove"), ("J K", "move"), ("A", "play next"), ("D", "download")]

    def __init__(self, win):
        super().__init__(win)
        self.rows = RowList(on_activate=lambda it: self.core.play_index(self.core.queue.index(it)), row_height=ROW_H)
        self.widget = self.rows
        self.matches, self.mi = [], 0
        self._placed = False

    def list(self):
        return self.rows

    def _item(self, it, i):
        c = self.core
        playing, past = i == c.cur, 0 <= i < c.cur
        no = G["pause"] if playing and c.paused else ("▶" if playing else str(i + 1))
        grip = label("⠿", "grip", ellipsize=False)
        x = Gtk.Button(label="×", valign=Gtk.Align.CENTER, tooltip_text="Remove (dd)")
        x.add_css_class("x")
        x.connect("clicked", lambda *_: c.delete([c.queue.index(it)] if it in c.queue else []))
        w = self.row(it, self.badges(it) + [x], number=no)
        w.prepend(grip)
        if playing:
            w.add_css_class("playing")
        if past:
            w.add_css_class("past")
        src = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        src.connect("prepare", lambda *_: Gdk.ContentProvider.new_for_value(GObject.Value(GObject.TYPE_INT, i)))
        w.add_controller(src)
        dst = Gtk.DropTarget.new(GObject.TYPE_INT, Gdk.DragAction.MOVE)
        dst.connect("enter", lambda *_: (w.add_css_class("drop"), Gdk.DragAction.MOVE)[1])
        dst.connect("leave", lambda *_: w.remove_css_class("drop"))
        dst.connect("drop", lambda _t, frm, *_: self._dropped(frm, i))
        w.add_controller(dst)
        return w

    def _dropped(self, frm, to):
        if self.core.move(frm, to):
            self.win.toast("It's in your queue now: autoplay won't replace it")
        self.rows.sel = to
        return True

    def refresh(self, event=None):
        if event not in (None, "queue", "video", "player", "downloads", "options", "thumbs", "history"):
            return
        c = self.core
        q, p = c.queue, c.cur
        rows = []
        for i, it in enumerate(q):
            if i == 0 and p > 0:
                rows.append(("header", section("Watched", label(str(p), ellipsize=False))))
            if i == p:
                rows.append(("header", section("Now playing")))
            if i == max(p + 1, 0) and not it.get("auto") and (p >= 0 or i == 0):
                mine = sum(1 for x in q[max(p + 1, 0):] if not x.get("auto"))
                rows.append(("header", section("Up next · added by you", label(str(mine), ellipsize=False))))
            if it.get("auto") and i > p and (i == p + 1 or not q[i - 1].get("auto")):
                seed = (c.current or {}).get("title", "")
                chip = label(f"{G['radio']} autoplay · M turns it off", "sect-chip", ellipsize=False)
                rows.append(("header", section(f"More like “{seed[:40]}”", chip)))
            rows.append(("item", it, self._item(it, i)))
        if q and not c.autoplay:
            rows.append(("header", section("Autoplay is off · stops after your videos",
                                           label("M turns it on", "sect-chip off", ellipsize=False))))
        self.rows.set_rows(rows, empty=empty(G["queue"], "Nothing lined up.\n\n3 searches YouTube · 2 opens your videos\n"
                                                         "a adds a video here, Enter plays it now"))

    def shown(self):
        if self.core.cur >= 0 and not self._placed:
            self._placed = True
            self.rows.select(self.core.cur)

    def selected_idx(self):
        q = self.core.queue
        return [q.index(self.rows.items[i]) for i in self.rows.range()
                if i < len(self.rows.items) and self.rows.items[i] in q]

    def key(self, k, n):
        c, w = self.core, self.win
        it = self.rows.selected()
        i = c.queue.index(it) if it in c.queue else -1
        if k == "Return" and i >= 0:
            c.play_index(i)
        elif k in ("dd", "x"):
            idx = self.selected_idx() if self.rows.vstart is not None else list(range(i, min(i + n, len(c.queue))))
            removed = c.delete(idx)
            if removed:
                w.register = [dict(r) for r in removed]
                w.toast(f"Removed {len(removed)} · p puts it back, u undoes")
            self.rows.visual(False)
            w.set_mode("NORMAL")
        elif k == "dG" and i >= 0:
            w.register = [dict(r) for r in c.delete(list(range(i, len(c.queue))))]
        elif k == "yy":
            idx = self.selected_idx() if self.rows.vstart is not None else [i]
            w.register = [dict(c.queue[j]) for j in idx if j >= 0]
            w.toast(f"Copied {len(w.register)}")
            self.rows.visual(False)
            w.set_mode("NORMAL")
        elif k in ("p", "P"):
            if not w.register:
                w.toast("Nothing copied · yy copies, dd cuts")
            else:
                c.insert(w.register, i + 1 if k == "p" else max(0, i))
        elif k in ("J", "K") and i >= 0:
            to = i + (1 if k == "J" else -1)
            if 0 <= to < len(c.queue):
                c.move(i, to)
                self.rows.select(self.rows.sel + (1 if k == "J" else -1))
        elif k == "A" and i >= 0:
            c.play_next(i)
            w.toast("Plays next")
        elif k == "D" and it:
            for j in (self.selected_idx() if self.rows.vstart is not None else [i]):
                c.download(c.queue[j])
            self.rows.visual(False)
            w.set_mode("NORMAL")
        elif k == "zz":
            if c.cur >= 0:
                self.rows.select(c.cur)
        else:
            return False
        return True

    def search(self, q):
        words = q.lower().split()
        self.matches = [i for i, it in enumerate(self.rows.items)
                        if all(wd in (it.get("title", "") + " " + it.get("channel", "")).lower() for wd in words)]
        self.mi = 0
        if self.matches:
            self.rows.select(self.matches[0])
        self.win.toast(f"{len(self.matches)} match{'es' if len(self.matches) != 1 else ''} · n N for the next")

    def next_match(self, d):
        if self.matches:
            self.mi = (self.mi + d) % len(self.matches)
            self.rows.select(self.matches[self.mi])


# ===================================================================== library
class Library(View):
    """Your videos as a grid: Continue watching first, then folders and
    videos; inside a folder, its episodes in order with how much you've
    seen. h j k l move, Enter opens or plays, Backspace goes up."""
    name, title, glyph = "library", "Library", G["lib"]
    hints = [("h j k l", "move"), ("Enter", "open / play"), ("Backspace", "up"), ("a", "add"), ("/", "search")]
    CW, CH = 208, 117

    def __init__(self, win):
        super().__init__(win)
        self.path = None          # None: the top (Continue watching + your folders)
        self.cards = []           # [(data, widget)]
        self.sel = 0
        self.inner = box(vertical=True, cls="grid-page")
        self.scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_child(self.inner)
        self.crumb = label("", "crumb")
        self.widget = box(box(self.crumb, cls="grid-head"), self.scroll, vertical=True)
        self.loaded = False
        self.data = None          # what the last scan found, for repainting

    def shown(self):
        if not self.loaded:
            self.loaded = True
            self.open(None)

    def refresh(self, event=None):
        if event in ("thumbs", "history", "downloads") and self.data is not None:
            self._paint(*self.data, keep=True)

    # ------------------------------------------------------------ loading
    def open(self, path, select=None):
        self.path = path
        dirs = [d for d in self.core.conf["video_dirs"] if os.path.isdir(d)]
        cache = os.path.join(config.CACHE, "thumbs")
        home = os.path.expanduser("~")
        self.crumb.set_text(("Library" if path is None else path.replace(home, "~")) +
                            ("" if path is None else "   ·   Backspace goes up"))

        def work():
            sections = []
            if path is None:
                cont = [dict(e) for _k, e in self.core.store.unfinished()][:8]
                if cont:
                    sections.append(("Continue watching", cont))
                for d in dirs:
                    folders, videos = library.listdir(d)
                    for f in folders:
                        f["n"] = library.count_videos(f["path"], 99)
                    items = [f for f in folders if f["n"]] + videos
                    if items:
                        sections.append((d.replace(home, "~"), items))
            else:
                folders, videos = library.listdir(path)
                for f in folders:
                    f["n"] = library.count_videos(f["path"], 99)
                folders = [f for f in folders if f["n"]]
                if folders:
                    sections.append(("Folders", folders))
                if videos:
                    eps = sum(1 for v in videos if library.episode(v["file"]))
                    sections.append(("Episodes" if eps > len(videos) / 2 else "Videos", videos))
            for _t, items in sections:
                for v in items:
                    if "file" in v and not v.get("duration"):
                        v["duration"] = library.probe(v["file"], cache).get("duration", 0)
            return sections

        def then(sections):
            if self.path == path:
                self.data = (sections,)
                self._paint(sections, select=select)
        self.core.bg(work, then)

    # ------------------------------------------------------------ drawing
    def _card(self, d):
        if "path" in d:   # a folder
            tile = box(label(G["folder"], "glyph folder-big", xalign=0.5, ellipsize=False, hexpand=True,
                             valign=Gtk.Align.CENTER), cls="thumb folder-tile")
            tile.set_size_request(self.CW, self.CH)
            return box(tile, label(d["name"], "card-title"), label(f"{d['n']} video{'s' if d['n'] != 1 else ''}",
                                                                     "card-sub"), vertical=True, spacing=3, cls="card")
        e = self.core.store.entry(d)
        sub = os.path.basename(os.path.dirname(d.get("file") or "")) if d.get("file") else meta(d)
        if e and e.get("finished"):
            sub = "watched"
        elif e and store.resume_at(e) > 0 and e.get("duration"):
            sub = f"{fmt_time(e['duration'] - e['pos'])} left"
        thumb = thumb_widget(self.win.thumb(d), self.CW, self.CH, G["yt"] if d.get("yt") else G["film"], self.progress(d))
        if d.get("duration"):
            over = thumb
            over.add_overlay(label(fmt_time(d["duration"]), "card-dur", ellipsize=False, halign=Gtk.Align.END,
                                   valign=Gtk.Align.END))
        t = label(" ".join((d.get("title") or "?").split()), "card-title", wrap=True, lines=2, max_width_chars=26)
        t.set_ellipsize(3)
        return box(thumb, t, label(sub, "card-sub"), vertical=True, spacing=3, cls="card")

    def _paint(self, sections, select=None, keep=False):
        old = self.cards[self.sel][0] if keep and 0 <= self.sel < len(self.cards) else None
        child = self.inner.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.inner.remove(child)
            child = nxt
        self.cards = []
        for title, items in sections:
            self.inner.append(label(title, "grid-title"))
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=2,
                               max_children_per_line=12, column_spacing=16, row_spacing=18, valign=Gtk.Align.START)
            flow.add_css_class("grid")
            for d in items:
                w = self._card(d)
                i = len(self.cards)
                g = Gtk.GestureClick()
                g.connect("pressed", lambda _g, n, *_a, i=i: self._clicked(i, n))
                w.add_controller(g)
                flow.append(w)
                self.cards.append((d, w))
            self.inner.append(flow)
        if not self.cards:
            dirs = ", ".join(self.core.conf["video_dirs"])
            self.inner.append(empty(G["folder"], "No videos here.\n\nYour folders are video_dirs in "
                                                 f"~/.config/drishya/config.toml (now: {dirs})."))
        target = old if old is not None else select
        self.sel = 0
        if target is not None:
            for i, (d, _w) in enumerate(self.cards):
                if d == target or ("path" in d and isinstance(target, str) and d["path"] == target):
                    self.sel = i
        self._select(self.sel)

    def _clicked(self, i, n):
        self._select(i)
        if n == 2:
            self._enter()

    def _select(self, i):
        if not self.cards:
            return
        self.sel = max(0, min(len(self.cards) - 1, i))
        for j, (_d, w) in enumerate(self.cards):
            (w.add_css_class if j == self.sel else w.remove_css_class)("sel")
        GLib.idle_add(self._scroll_to)

    def _scroll_to(self):
        if not (0 <= self.sel < len(self.cards)):
            return False
        ok, r = self.cards[self.sel][1].compute_bounds(self.inner)
        if ok:
            adj = self.scroll.get_vadjustment()
            if r.get_y() - 40 < adj.get_value():
                adj.set_value(max(0, r.get_y() - 40))
            elif r.get_y() + r.get_height() + 16 > adj.get_value() + adj.get_page_size():
                adj.set_value(r.get_y() + r.get_height() + 16 - adj.get_page_size())
        return False

    def _vertical(self, d):
        """The card above (d=-1) or below (1): the nearest by position."""
        if not self.cards:
            return
        ok, cur = self.cards[self.sel][1].compute_bounds(self.inner)
        if not ok:
            return
        cx, cy = cur.get_x() + cur.get_width() / 2, cur.get_y()
        best = None
        for i, (_d, w) in enumerate(self.cards):
            ok, r = w.compute_bounds(self.inner)
            if not ok:
                continue
            dy = r.get_y() - cy
            if (d > 0 and dy <= 4) or (d < 0 and dy >= -4):
                continue
            score = (abs(dy), abs(r.get_x() + r.get_width() / 2 - cx))
            if best is None or score < best[0]:
                best = (score, i)
        if best:
            self._select(best[1])

    # ------------------------------------------------------------ doing
    def _enter(self):
        if not self.cards:
            return
        d = self.cards[self.sel][0]
        if "path" in d:
            self.open(d["path"])
            return
        vids = [x for x, _w in self.cards if "file" in x and "path" not in x]
        if d in vids and self.path is not None:
            self.play(*vids[vids.index(d):])   # this one, then the rest of the folder (the next episodes)
        else:
            self.play({k: v for k, v in d.items() if k in ("yt", "file", "url", "title", "channel", "thumb", "duration")})

    def _up(self):
        if self.path is None:
            return
        dirs = [d.rstrip("/") for d in self.core.conf["video_dirs"]]
        parent = os.path.dirname(self.path.rstrip("/"))
        if self.path.rstrip("/") in dirs or parent in dirs:
            parent = None   # one of your video folders: that's the top (with Continue watching)
        self.open(parent, select=self.path)

    def key(self, k, n):
        if k == "h":
            self._select(self.sel - n)
        elif k == "l":
            self._select(self.sel + n)
        elif k == "j":
            for _ in range(n):
                self._vertical(1)
        elif k == "k":
            for _ in range(n):
                self._vertical(-1)
        elif k in ("gg",):
            self._select(0)
        elif k == "G":
            self._select(len(self.cards) - 1)
        elif k == "Return":
            self._enter()
        elif k == "BackSpace":
            self._up()
        elif k in ("a", "A") and self.cards:
            d = self.cards[self.sel][0]
            items = library.listdir(d["path"])[1] if "path" in d else [d]
            self.core.add(items, "end" if k == "a" else "next")
        elif k == "R":
            self.open(self.path)
            self.win.finder.refresh_index(force=True)
            self.win.toast("Library reloaded")
        else:
            return False
        return True


# ===================================================================== youtube
class YouTube(View):
    name, title, glyph = "youtube", "YouTube", G["yt"]
    hints = [("/", "search"), ("Enter", "play"), ("a", "add"), ("A", "play next"), ("D", "download")]

    def __init__(self, win):
        super().__init__(win)
        self.entry = Gtk.Text(hexpand=True, placeholder_text="Search YouTube, or paste any link to play it…   (/ to type, Enter, Esc back to the results)")
        self.entry.connect("activate", lambda *_: self._go())
        self.spin = label("", "dim", ellipsize=False)
        sb = box(label(G["search"] + "  ", "glyph dim", ellipsize=False), self.entry, self.spin, cls="searchbox")
        self.rows = RowList(on_activate=lambda e: self.play(e), row_height=ROW_H)
        self.widget = box(sb, self.rows, vertical=True, hexpand=True)
        self.results = []
        self._fill()

    def list(self):
        return self.rows

    def shown(self):
        if not self.results:
            GLib.idle_add(lambda: (self.focus_entry(), False)[1])

    def focus_entry(self):
        self.entry.grab_focus()
        self.win.set_mode("SEARCH")

    def _go(self):
        q = self.entry.get_text().strip()
        self.win.root.grab_focus()
        self.win.set_mode("NORMAL")
        if "://" in q or os.path.exists(os.path.expanduser(q)):
            # a link or a path: play it, whatever server it's on
            self.entry.set_text("")
            self.core.add_url(q, "play")
            self.win.switch("watch")
        elif q:
            self.search(q)

    def search(self, q):
        self.entry.set_text(q)
        self.spin.set_text("searching…")

        def then(results):
            self.spin.set_text(f"{len(results)} results")
            self.results = results
            self._fill()
            self.rows.select(0)

        def fail(e):
            self.spin.set_text("")
            self.win.toast(str(e))
        self.core.bg(lambda: youtube.search(q, 30), then, fail)

    def _fill(self):
        queued = {s.get("yt") for s in self.core.queue}
        rows = []
        for e in self.results:
            right = self.badges(e)
            if e["yt"] in queued:
                right.append(badge("queued", "yt"))
            if e.get("live"):
                right.append(badge("LIVE", "failed"))
            rows.append(("item", e, self.row(e, right)))
        self.rows.set_rows(rows, empty=empty(G["yt"], "Search YouTube: press / and type.\n"
                                                      "Enter plays it (and related videos after it),\n"
                                                      "a adds it to Up next, D downloads it."))

    def refresh(self, event=None):
        if event in ("thumbs", "queue", "downloads", "history") and self.results:
            self._fill()

    def key(self, k, n):
        e = self.rows.selected()
        sel = [self.rows.items[i] for i in self.rows.range()] if self.rows.items else []
        if k == "Return" and e:
            self.play(e)
            return True
        if k in ("a", "A") and sel:
            self.core.add(sel, "end" if k == "a" else "next")
            self.rows.visual(False)
            self.win.set_mode("NORMAL")
            return True
        if k == "D" and sel:
            for x in sel:
                self.core.download(x)
            self.rows.visual(False)
            self.win.set_mode("NORMAL")
            return True
        return False


# ===================================================================== history
class History(View):
    name, title, glyph = "history", "History", G["history"]
    hints = [("Enter", "resume"), ("a", "add"), ("dd", "forget"), ("/", "search")]

    def __init__(self, win):
        super().__init__(win)
        self.rows = RowList(on_activate=lambda e: self._play(e), row_height=ROW_H)
        self.widget = self.rows
        self.filter = ""

    def list(self):
        return self.rows

    def shown(self):
        self.refresh(None)

    def _play(self, e):
        self.play({k: v for k, v in e.items() if k != "_key"})

    def refresh(self, event=None):
        if event not in (None, "history", "thumbs", "downloads") or self.win.tab != "history" and event is not None:
            return
        rows = []
        words = self.filter.lower().split()
        cont, rest = [], []
        for k, e in self.core.store.recent():
            if words and not all(w in (e.get("title", "") + " " + e.get("channel", "")).lower() for w in words):
                continue
            e = dict(e, _key=k)
            (cont if store.resume_at(e) > 0 else rest).append(e)
        if cont:
            rows.append(("header", section("Continue watching", label(str(len(cont)), ellipsize=False))))
            for e in cont[:30]:
                left = (e.get("duration") or 0) - (e.get("pos") or 0)
                rows.append(("item", e, self.row(e, [badge(f"{fmt_time(left)} left", "dl")])))
        last_day = None
        today = time.strftime("%A, %d %B")
        for e in rest[:400]:
            day = time.strftime("%A, %d %B", time.localtime(e.get("at", 0)))
            day = "Today" if day == today else day
            if day != last_day:
                rows.append(("header", section(day)))
                last_day = day
            rows.append(("item", e, self.row(e, self.badges(e))))
        msg = f"Nothing in your history matches “{self.filter}”" if self.filter else \
            "Nothing watched yet.\n\nWhat you watch shows here, and where you stopped:\nEnter picks it up from there."
        self.rows.set_rows(rows, empty=empty(G["history"], msg))

    def key(self, k, n):
        e = self.rows.selected()
        if k == "Return" and e:
            self._play(e)
            return True
        if k in ("a", "A") and e:
            sel = [{kk: vv for kk, vv in self.rows.items[i].items() if kk != "_key"} for i in self.rows.range()]
            self.core.add(sel, "end" if k == "a" else "next")
            self.rows.visual(False)
            self.win.set_mode("NORMAL")
            return True
        if k in ("dd", "x") and e:
            for i in self.rows.range():
                self.core.store.forget(self.rows.items[i]["_key"])
            self.core.store.flush()
            self.rows.visual(False)
            self.win.set_mode("NORMAL")
            self.refresh(None)
            self.win.toast("Forgotten")
            return True
        if k == "D" and e:
            self.core.download(e)
            return True
        return False

    def search(self, q):
        self.filter = q
        self.refresh(None)
        self.win.toast("Esc then / with nothing clears the filter" if q else "")


# ===================================================================== downloads
class Downloads(View):
    name, title, glyph = "downloads", "Downloads", G["dl"]
    hints = [("Enter", "play"), ("R", "retry"), ("dd", "delete"), ("x", "cancel")]

    def __init__(self, win):
        super().__init__(win)
        self.rows = RowList(on_activate=lambda d: self._play(d), row_height=ROW_H)
        self.widget = self.rows

    def list(self):
        return self.rows

    def shown(self):
        self.refresh(None)

    def _play(self, d):
        if d.get("state") in (None, "done"):
            self.play({k: d[k] for k in ("yt", "url", "title", "channel", "thumb", "duration") if d.get(k)})

    def refresh(self, event=None):
        if event not in (None, "downloads", "thumbs"):
            return
        c = self.core
        rows = []
        active = [j for j in c.jobs if j["state"] != "done"]
        if active:
            rows.append(("header", section("Downloading")))
            for j in active:
                if j["state"] == "failed":
                    right = [badge("failed", "failed")]
                    sub = j["error"][:80]
                else:
                    right = [badge(f"{G['dl']} {int(j['pct'])}%" if j["state"] == "running" else "waiting", "dl")]
                    sub = j.get("channel", "")
                rows.append(("item", j, self.row(j, right, sub=sub)))
        saved = []
        for key, path in c.store.downloads.items():
            if not os.path.exists(path):
                continue
            is_yt = youtube.video_id(key) == key
            e = c.store.history.get(("yt:" if is_yt else "url:") + key) or {}
            saved.append({"key": key, "yt": key if is_yt else None, "url": None if is_yt else key,
                          "path": path, "title": e.get("title") or library.nice_title(path),
                          "channel": e.get("channel") or os.path.basename(os.path.dirname(path)),
                          "thumb": e.get("thumb") or (youtube.thumb(key) if is_yt else None),
                          "duration": e.get("duration", 0), "size": os.path.getsize(path), "state": "done",
                          "mtime": os.path.getmtime(path)})
        saved.sort(key=lambda d: d["mtime"], reverse=True)
        if saved:
            total = sum(d["size"] for d in saved)
            rows.append(("header", section(f"Saved in {self.core.conf['download_dir']}",
                                           label(f"{len(saved)} · {fmt_bytes(total)}", ellipsize=False))))
            for d in saved:
                rows.append(("item", d, self.row(d, [label(fmt_bytes(d["size"]), "dim", ellipsize=False)])))
        self.rows.set_rows(rows, empty=empty(G["dl"], "No downloads.\n\nD saves the video you're on (or the selected one)\n"
                                                      "with its subtitles; it then plays from your disk."))

    def key(self, k, n):
        d = self.rows.selected()
        if d is None:
            return False
        c = self.core
        if k == "Return":
            self._play(d)
        elif k == "R" and d.get("state") == "failed":
            c.retry(d)
        elif k == "x" and d.get("state") in ("queued", "running"):
            c.cancel(d)
            self.win.toast("Cancelling")
        elif k == "dd" and d.get("state") == "done":
            self.win.confirm(f"Delete “{d['title'][:50]}” from your disk?", lambda: c.delete_download(d["key"]))
        elif k == "dd" and d.get("state") == "failed":
            c.jobs.remove(d)
            self.refresh(None)
        else:
            return False
        return True
