"""The six tabs: Watch (the video), Up next (the queue), Library, YouTube,
History, Downloads. Keys common to every list (j k gg G Ctrl+d/u V) are
handled by the window; each view handles its own."""
import os
import time

from gi.repository import Gdk, GLib, GObject, Gtk

from . import config, library, store, youtube
from .util import fmt_time, track_name
from .widgets import G, RowList, VideoArea, box, fmt_bytes, label, thumb_widget

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
    name, title, glyph = "watch", "Watch", G["watch"]
    hints = [("space", "play"), ("h l", "±5 s"), ("f", "fullscreen"), ("t", "theater"), ("c", "subtitles")]

    def __init__(self, win):
        super().__init__(win)
        self.area = VideoArea(self.core, lambda: not (win.app.mini and win.app.mini.get_visible()))
        self.over = Gtk.Overlay(hexpand=True, vexpand=True)
        self.over.add_css_class("stage")
        self.over.set_child(self.area)
        # what shows over the video: the idle message, a pause/buffering glyph, the OSD
        self.idle = empty(G["eye"], "Nothing playing.\n\n3 searches YouTube · 2 opens your videos · 4 your history")
        self.idle.set_can_target(False)
        self.over.add_overlay(self.idle)
        self.center = label("", "glyph center-glyph", xalign=0.5, ellipsize=False, halign=Gtk.Align.CENTER,
                            valign=Gtk.Align.CENTER, can_target=False)
        self.over.add_overlay(self.center)
        self.osd_title = label("", "osd-title")
        self.osd_bar = Gtk.ProgressBar(hexpand=True, valign=Gtk.Align.CENTER)
        self.osd_bar.add_css_class("osd-bar")
        self.osd_time = label("", "time", ellipsize=False)
        self.osd = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, valign=Gtk.Align.END,
                                can_target=False)
        self.osd.set_child(box(self.osd_title, box(self.osd_bar, self.osd_time, spacing=12), vertical=True,
                               spacing=8, cls="osd"))
        self.over.add_overlay(self.osd)
        self.osd_timer = None

        # the side: what's playing, then what's next
        self.t = label("", "now-title", wrap=True, max_width_chars=34, lines=3)
        self.t.set_ellipsize(3)
        self.ch = label("", "now-sub", wrap=True, max_width_chars=34)
        self.stats = label("", "now-stats", wrap=True, max_width_chars=34)
        self.chips = box(spacing=6, cls="chips")
        self.upnext = RowList(on_activate=lambda it: self.core.play_index(self.core.queue.index(it)), row_height=62)
        self.upnext.add_css_class("upnext")
        self.side = box(box(self.t, self.ch, self.stats, self.chips, vertical=True, spacing=5, cls="now"),
                        section("Up next", label("1 for all", ellipsize=False)), self.upnext,
                        vertical=True, cls="side")
        self.side.set_size_request(360, -1)
        self.side.set_hexpand(False)   # the video takes the width, not the list
        self.widget = box(self.over, self.side)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda *_: self.win.fullscreened and self.show_osd())
        self.over.add_controller(motion)
        click = Gtk.GestureClick()
        click.connect("pressed", self._clicked)
        self.over.add_controller(click)

    def _clicked(self, _g, n, _x, _y):
        if n == 2:
            self.win.toggle_fullscreen()
        else:
            self.core.toggle()

    def list(self):
        return self.upnext

    def set_theater(self, on):
        self.side.set_visible(not on)

    def show_osd(self, secs=2.6):
        self.osd.set_reveal_child(True)
        if self.osd_timer:
            GLib.source_remove(self.osd_timer)
        self.osd_timer = GLib.timeout_add(int(secs * 1000), self._osd_hide)

    def _osd_hide(self):
        self.osd_timer = None
        if not self.core.paused or not self.win.fullscreened:
            self.osd.set_reveal_child(False)
        return False

    def tick(self, t):
        d = self.core.duration
        if self.osd.get_reveal_child():
            self.osd_bar.set_fraction(t / d if d else 0)
            self.osd_time.set_text(f"{fmt_time(t)} / {fmt_time(d)}" if d else fmt_time(t))

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
            elif cur is not None and c.paused and not c.idle:
                glyph = G["pause"]
            self.center.set_text(glyph)
            self.center.set_visible(bool(glyph))
            self.osd_title.set_text(cur["title"] if cur else "")
        if event in (None, "video", "history"):
            if cur is None:
                self.t.set_text("Nothing playing")
                self.ch.set_text("")
                self.stats.set_text("")
            else:
                self.t.set_text(cur.get("title") or "")
                self.ch.set_text(cur.get("channel") or meta(cur) if cur.get("url") else
                                 cur.get("channel") or os.path.dirname(cur.get("file") or ""))
                self.stats.set_text(" · ".join(p for p in (youtube.views(cur.get("views")),
                                                           youtube.ago(cur.get("uploaded"))) if p))
        if event in (None, "video", "tracks", "player", "options"):
            self._chips()
        if event in (None, "queue", "video", "thumbs", "options", "downloads"):
            rows = []
            nxt = c.queue[c.cur + 1:c.cur + 9] if c.cur >= 0 else c.queue[:8]
            for it in nxt:
                thumb = thumb_widget(self.win.thumb(it), 96, 54, G["yt"] if it.get("yt") else G["film"],
                                     self.progress(it))
                text = box(label(it.get("title") or "?", "t", wrap=True, max_width_chars=26, lines=2),
                           label(it.get("channel") or meta(it), "a"), vertical=True, spacing=2, hexpand=True,
                           valign=Gtk.Align.CENTER)
                text.get_first_child().set_ellipsize(3)
                w = box(thumb, text, spacing=10, cls="upnext-row")
                if it.get("auto"):
                    w.add_css_class("auto")
                rows.append(("item", it, w))
            msg = ("Autoplay will find more when this ends" if c.autoplay else "Nothing next · M turns autoplay on")
            self.upnext.set_rows(rows, empty=label(msg, "dim", xalign=0.5, wrap=True, margin_top=20))

    def _chips(self):
        c = self.core
        child = self.chips.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.chips.remove(child)
            child = nxt
        if c.current is None:
            return
        vt = next((t for t in c.tracks if t.get("type") == "video" and t.get("selected")), None)
        if vt and vt.get("demux-h"):
            self.chips.append(label(f"{vt['demux-h']}p", "chip", ellipsize=False))
        sub = next((t for t in c.tracks if t.get("type") == "sub" and t.get("selected")), None)
        nsubs = sum(1 for t in c.tracks if t.get("type") == "sub")
        if nsubs:
            self.chips.append(label(f"CC {track_name(sub) if sub else 'off'}", "chip act" if sub else "chip",
                                    ellipsize=False, max_width_chars=18))
        if c.speed != 1:
            self.chips.append(label(f"{c.speed:g}×", "chip act", ellipsize=False))
        if c.chapters and c.chapter >= 0:
            ch = c.chapters[c.chapter].get("title") or f"Chapter {c.chapter + 1}"
            self.chips.append(label(f"{c.chapter + 1}/{len(c.chapters)} · {ch}", "chip", max_width_chars=26))
        if c.current.get("live"):
            self.chips.append(label("● LIVE", "chip live", ellipsize=False))
        if (c.current.get("yt") or c.current.get("url")) and c.downloaded(c.current) and not c.current.get("file"):
            self.chips.append(label("from disk", "chip", ellipsize=False))

    def key(self, k, n):
        c = self.core
        step = c.conf["fine_step"]
        if k == "h":
            c.seek(-step * n)
            self.win.osd_or_toast(f"Back {step * n} s")
            return True
        if k == "l":
            c.seek(step * n)
            self.win.osd_or_toast(f"Forward {step * n} s")
            return True
        if k == "Return":
            it = self.upnext.selected()
            if it is not None and it in c.queue:
                c.play_index(c.queue.index(it))
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
    """Your folders as columns, like yazi: h/l move between them."""
    name, title, glyph = "library", "Library", G["lib"]
    hints = [("h l", "folders"), ("Enter", "play"), ("a", "add"), ("A", "play next"), ("/", "search")]

    def __init__(self, win):
        super().__init__(win)
        self.cols = []        # [(path, RowList)]
        self.focus = 0
        self.searching = None
        self.inner = box(hexpand=True, vexpand=True)
        self.widget = self.inner
        self.loaded = False

    def list(self):
        return self.cols[self.focus][1] if self.cols else None

    def shown(self):
        if not self.loaded:
            self.loaded = True
            self.reload()

    def reload(self):
        dirs = [d for d in self.core.conf["video_dirs"] if os.path.isdir(d)]
        for _p, col in self.cols:
            self.inner.remove(col.get_parent())
        self.cols = []
        if not dirs:
            col = RowList()
            col.set_rows([], empty=empty(G["folder"], "No video folders.\n\nSet video_dirs in ~/.config/drishya/config.toml\n"
                                                     f"(now: {', '.join(self.core.conf['video_dirs'])})"))
            self._add_col("", col, "Library")
            return
        roots = [{"name": os.path.basename(d.rstrip("/")) or d, "path": d, "root": True} for d in dirs]
        if len(roots) == 1:
            self._open(0, roots[0]["path"], roots[0]["name"])
        else:
            col = RowList(on_select=lambda d: self._preview(0, d), row_height=40)
            col.set_rows([("item", r, self._folder_row(r)) for r in roots])
            self._add_col("", col, "Folders")

    def _add_col(self, path, col, title):
        frame = box(section(title), col, vertical=True, cls="col")
        self.inner.append(frame)
        self.cols.append((path, col))
        self._widths()
        self._paint_focus()

    def _widths(self):
        """Folder columns stay narrow; the last one (the videos) takes the rest."""
        for j, (_p, col) in enumerate(self.cols):
            frame = col.get_parent()
            last = j == len(self.cols) - 1
            frame.set_hexpand(last)
            frame.set_size_request(-1 if last else 280, -1)

    def _fill_col(self, col, folders, videos, keep=True):
        col.data = (folders, videos)
        rows = [("item", f, self._folder_row(f)) for f in folders if f["n"]]
        rows += [("item", v, self._video_row(v)) for v in videos]
        col.set_rows(rows, keep=keep, empty=label("No videos here", "dim", xalign=0.5, margin_top=30))

    def refresh(self, event=None):
        if event in ("thumbs", "history", "downloads"):
            for _p, col in self.cols:
                if getattr(col, "data", None):
                    self._fill_col(col, *col.data)

    def _folder_row(self, d):
        return box(label(G["folder"], "glyph folder-glyph", ellipsize=False), label(d["name"], "title", hexpand=True),
                   label(str(d["n"]) if d.get("n") else "", "dim", ellipsize=False), spacing=10, cls="folder-row")

    def _video_row(self, v):
        return self.row(v, self.badges(v))

    def _open(self, at, path, title):
        """Shows path's contents as column `at` (dropping the ones after it)."""
        while len(self.cols) > at:
            p, col = self.cols.pop()
            self.inner.remove(col.get_parent())
        def work():
            folders, videos = library.listdir(path)
            for f in folders:
                f["n"] = library.count_videos(f["path"], 99)
            for v in videos[:300]:
                v["duration"] = library.probe(v["file"], os.path.join(config.CACHE, "thumbs")).get("duration", 0)
            return folders, videos

        col = RowList(on_activate=lambda d: self._enter(d), on_select=lambda d: self._preview(at, d), row_height=ROW_H)
        col.set_rows([], empty=label("Reading…", "dim", xalign=0.5, margin_top=30))
        self._add_col(path, col, title)

        self.core.bg(work, lambda r: self._fill_col(col, *r, keep=False))

    def _preview(self, at, d):
        # Selecting a folder doesn't open it (that's l / Enter): keeps j/k quick.
        pass

    def _enter(self, d):
        if d is None:
            return
        if "path" in d:
            i = next((j for j, (_p, col) in enumerate(self.cols) if col.selected() is d), self.focus)
            self._open(i + 1, d["path"], d["name"])
            self.focus = i + 1
            self._paint_focus()
        else:
            self._play_from(d, "play")

    def _play_from(self, v, where):
        """Plays v, with the rest of its folder after it (the next episodes)."""
        col = self.list()
        vids = [x for x in col.items if "file" in x] if col else [v]
        rest = vids[vids.index(v):] if v in vids and where == "play" else [v]
        if where == "play":
            self.play(*rest)
        else:
            self.core.add(rest, where)

    def _paint_focus(self):
        for j, (_p, col) in enumerate(self.cols):
            (col.get_parent().add_css_class if j == self.focus else col.get_parent().remove_css_class)("focus")

    def key(self, k, n):
        col = self.list()
        d = col.selected() if col else None
        if k == "l" or (k == "Return" and d is not None and "path" in d):
            if d is not None and "path" in d:
                self._enter(d)
            elif d is not None:
                self._play_from(d, "play")
            return True
        if k == "h":
            if self.focus > 0:
                self.focus -= 1
                while len(self.cols) > self.focus + 2:
                    _p, c = self.cols.pop()
                    self.inner.remove(c.get_parent())
                self._widths()
                self._paint_focus()
            return True
        if k == "Return" and d is not None:
            self._play_from(d, "play")
            return True
        if k in ("a", "A") and col is not None:
            sel = [col.items[i] for i in col.range() if "file" in col.items[i]]
            if d is not None and "path" in d and not sel:
                _, vids = library.listdir(d["path"])
                sel = vids
            self.core.add(sel, "end" if k == "a" else "next")
            col.visual(False)
            self.win.set_mode("NORMAL")
            return True
        if k == "R":
            self.reload()
            self.win.toast("Library reloaded")
            return True
        return False

    def search(self, q):
        dirs = [d for d in self.core.conf["video_dirs"] if os.path.isdir(d)]

        def then(found):
            while len(self.cols) > 0:
                _p, c = self.cols.pop()
                self.inner.remove(c.get_parent())
            col = RowList(on_activate=lambda v: self._play_from(v, "play"), row_height=ROW_H)
            self._add_col("", col, f"Search: {q} · R for the folders")
            if found:
                self._fill_col(col, [], found)
            else:
                col.set_rows([], empty=empty(G["search"], f"No video matches “{q}”"))
            self.focus = 0
            self._paint_focus()
        self.core.bg(lambda: library.search(dirs, q), then)


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
