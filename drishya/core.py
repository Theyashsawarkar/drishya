"""The model: the queue, playback (libmpv), resume and history, autoplay,
undo, downloads. The window and the mini player only read from here and
call its methods; they hear about changes through listen().

Events (strings unless noted): "queue", "video" (what's playing changed),
"player" (play/pause/seek/volume/speed), "tracks", "options", "history",
"downloads", "buffering", "thumbs", and ("toast", text)."""
import concurrent.futures
import copy
import itertools
import logging
import os
import threading
import time

from gi.repository import GLib

from . import auth, config, library, mpv, store, system, youtube
from .util import dl_key, fmt_time, is_stream_url, stream_title, track_name, ytdl_raw_options  # noqa: F401

log = logging.getLogger("drishya.core")
UNDO_MAX = 50
_ids = itertools.count(1)


def item_from(d, auto=False):
    """A queue item from a search result, a history entry or a file."""
    it = {k: d.get(k) for k in ("yt", "file", "url", "title", "channel", "thumb", "duration", "views", "uploaded",
                                "live", "pending") if d.get(k)}
    if not it.get("title"):
        if it.get("file"):
            it["title"] = library.nice_title(it["file"])
        elif it.get("url"):
            it["title"] = stream_title(it["url"])
        else:
            it["title"] = it.get("yt", "?")
    it["id"] = next(_ids)
    it["auto"] = auto
    return it


class Core:
    def __init__(self):
        config.ensure_dirs()
        self.conf = config.load()
        self.store = store.Store(config.STATE)
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.listeners = []
        settings = store.load_json(os.path.join(config.STATE, "settings.json"), {})
        self.autoplay = settings.get("autoplay", self.conf["autoplay"])
        # The quality you picked (Q) wins over the config's, and stays picked.
        q = settings.get("quality")
        self.quality = q if isinstance(q, int) and 144 <= q <= 4320 else self.conf["quality"]
        self._qualities = {}          # yt id -> heights YouTube offers (asked once)
        self._boards = {}             # yt id -> its storyboard (preview frames), None when it has none
        self._details = {}            # yt id -> description etc. (asked once, for Info)
        self._asking = set()
        self.queue = [dict(it, id=next(_ids)) for it in store.load_json(os.path.join(config.STATE, "queue.json"), [])
                      if isinstance(it, dict) and (it.get("yt") or it.get("file"))]
        self.cur = -1
        self.undo_stack, self.redo_stack = [], []
        self.window_visible = False
        # playback state, from mpv's properties
        self.pos = 0.0
        self.duration = 0.0
        self.paused = True
        self.idle = True
        self.buffering = False
        self.buffered = 0.0
        self.volume = float(settings.get("volume", 100))
        self.muted = False
        self.speed = 1.0
        self.tracks = []
        self.chapters = []
        self.chapter = -1
        self.error = ""
        self.related_for = None
        self.jobs = []                # downloads: dicts with yt title channel pct state path error
        self._job_lock = threading.Lock()
        self._job_thread = None
        # the system's volume and the screen's brightness, as drishya's keys
        # change them; put back as they were when the window closes
        self.sys_volume = system.Adjust(system.Volume())
        self.sys_brightness = system.Adjust(system.Brightness())
        self.surface = None           # the VideoArea that holds mpv's renderer
        self.render_ready = False
        self._pending = None          # a load waiting for the renderer
        self._last_save = 0
        self.player = None
        self._resume_vid = None
        self.logins = {}              # host -> {"user", "password"} or {"cookies": browser}; memory only
        self._login_needed = None     # (kind, message) seen in mpv's log for the video being opened
        self._login_quiet_until = 0.0
        self.player_error = mpv.available()
        if self.player_error is None:
            try:
                self._start_mpv()
            except mpv.MPVError as e:
                self.player_error = str(e)
        if self.player_error:
            log.error("no player: %s", self.player_error)
        GLib.timeout_add_seconds(5, self._save_tick)
        for vid in {it["yt"] for it in self.queue if it.get("yt") and it.get("title") == "YouTube video"}:
            self._fill_in(vid)   # opened by link before its details came

    # ------------------------------------------------------------ plumbing
    def listen(self, fn):
        self.listeners.append(fn)

    def emit(self, *events):
        for e in events:
            for fn in list(self.listeners):
                try:
                    fn(e)
                except Exception:   # a broken listener mustn't break playback
                    log.exception("listener failed on %s", e)

    def toast(self, text):
        self.emit(("toast", text))

    def bg(self, work, then=None, fail=None):
        """Runs work() on a worker thread, then then(result) or
        fail(exception) on the main loop."""
        def done(fut):
            try:
                r = fut.result()
            except Exception as e:
                log.debug("background work failed: %r", e)
                GLib.idle_add(lambda e=e: ((fail or (lambda x: self.toast(str(x))))(e), False)[1])
                return
            if then:
                GLib.idle_add(lambda: (then(r), False)[1])
        self.pool.submit(work).add_done_callback(done)

    def _start_mpv(self):
        c = self.conf
        self._ytdl_raw = ytdl_raw_options(c["subtitles"])
        self.player = mpv.MPV(
            lambda fn: GLib.idle_add(fn), self._mpv_event,
            vo="libmpv", hwdec=c["hwdec"], keep_open="yes", idle="yes", terminal="no",
            input_default_bindings="no", input_vo_keyboard="no", osc="no", ytdl="yes",
            ytdl_format=config.ytdl_format(self.quality),
            ytdl_raw_options=self._ytdl_raw,
            slang=c["subtitles"], sid="no", sub_auto="fuzzy", audio_display="no",
            cache="yes", demuxer_max_bytes="150MiB", demuxer_max_back_bytes="50MiB",
            volume=str(int(self.volume)), volume_max="150", user_agent="drishya",
            screenshot_directory=os.path.expanduser("~/Pictures"))
        p = self.player
        for name, fmt in (("time-pos", mpv.FMT_DOUBLE), ("duration", mpv.FMT_DOUBLE), ("pause", mpv.FMT_FLAG),
                          ("idle-active", mpv.FMT_FLAG), ("eof-reached", mpv.FMT_FLAG),
                          ("paused-for-cache", mpv.FMT_FLAG), ("volume", mpv.FMT_DOUBLE), ("mute", mpv.FMT_FLAG),
                          ("speed", mpv.FMT_DOUBLE), ("track-list", mpv.FMT_NODE), ("chapter-list", mpv.FMT_NODE),
                          ("chapter", mpv.FMT_INT64), ("sid", mpv.FMT_NODE), ("aid", mpv.FMT_NODE),
                          ("sub-visibility", mpv.FMT_FLAG), ("media-title", mpv.FMT_STRING),
                          ("seekable", mpv.FMT_FLAG), ("demuxer-cache-time", mpv.FMT_DOUBLE)):
            p.observe(name, fmt)

    # ------------------------------------------------------------ mpv events
    def _mpv_event(self, name, data):
        if name == "property":
            prop, v = data
            if prop == "time-pos":
                self.pos = v or 0.0
                return
            if prop == "duration":
                self.duration = v or 0.0
                cur = self.current
                if cur and self.duration and not cur.get("duration"):
                    cur["duration"] = self.duration
                self.emit("player")
            elif prop == "pause":
                self.paused = bool(v)
                self._save_position()
                self.emit("player")
            elif prop == "idle-active":
                self.idle = bool(v)
                self.emit("player")
            elif prop == "eof-reached":
                if v:
                    self._ended()
            elif prop == "paused-for-cache":
                self.buffering = bool(v)
                self.emit("buffering")
            elif prop == "volume":
                if v is not None:
                    self.volume = v
                    self.emit("player")
            elif prop == "mute":
                self.muted = bool(v)
                self.emit("player")
            elif prop == "demuxer-cache-time":
                self.buffered = v or 0.0
                return
            elif prop == "media-title":
                cur = self.current
                # a link's real name, once mpv read it (an HLS playlist's, a page's title)
                if cur and cur.get("url") and v and not v.startswith(("http", "index", "playlist", "master")) \
                        and cur.get("title") == stream_title(cur["url"]):
                    cur["title"] = v
                    self.emit("video", "queue")
            elif prop == "seekable":
                cur = self.current
                # a live stream: no length, can't resume it later
                if cur is not None and v is False and not self.duration:
                    cur["live"] = True
                    self.emit("video")
            elif prop == "speed":
                self.speed = v or 1.0
                self.emit("player")
            elif prop in ("track-list", "sid", "aid", "sub-visibility"):
                if prop == "track-list":
                    self.tracks = v or []
                self.emit("tracks")
            elif prop == "chapter-list":
                self.chapters = v or []
                self.emit("tracks")
            elif prop == "chapter":
                self.chapter = -1 if v is None else v
                self.emit("tracks")
        elif name == "file-loaded":
            self.error = ""
            self._pick_variant()
            self.emit("player", "tracks")
        elif name == "end-file":
            reason, err = data
            if reason == mpv.END_ERROR and self._login_needed and self.current is not None:
                kind, why = self._login_needed
                self._login_needed = None
                cur = self.current
                url = cur.get("url") or youtube.watch_url(cur.get("yt", ""))
                host = auth.host_of(url)
                tried = host in self.logins
                log.info("%s wants a login (%s)", host, kind)
                self._login_quiet_until = time.monotonic() + 3
                self.emit(("login", {"host": host, "kind": kind, "why": why, "tried": tried,
                                     "title": cur.get("title", "")}))
                return
            if reason == mpv.END_ERROR:
                cur = self.current
                self.error = f"Couldn't play “{(cur or {}).get('title', '?')}”"
                log.warning("%s (mpv error %s)", self.error, err)
                self.toast(self.error + " · > skips it")
                self.emit("player")
        elif name == "restart":
            self.buffering = False
            self.emit("buffering", "player")
        elif name == "log":
            level, text = data
            if level in ("error", "fatal", "warn") and self.current is not None:
                kind = auth.needs_login(text)
                if kind:
                    # the first, most specific reason wins (the server's own 401 over yt-dlp's fallback)
                    if not (self._login_needed and self._login_needed[0] == "http"):
                        self._login_needed = (kind, text.split(": ", 1)[-1][:200])
                    log.info("mpv %s", text)   # expected: the sign-in panel follows
                    return
                if self._login_needed or time.monotonic() < self._login_quiet_until:
                    log.info("mpv %s", text)   # what failed because of it
                    return
            if level != "fatal" and (text.startswith(("ffmpeg/video:", "ffmpeg:", "vd:")) or "hwaccel" in text.lower()
                                     or "VK_KHR" in text or "CUDA" in text or "underrun" in text):
                log.debug("mpv %s", text)   # decoder chatter and hardware-decoding probes that fell back
                return
            if "desynchronisation" in text or text.endswith("cplayer: ") or "A-V status" in text \
                    or "--profile=fast" in text or "hardware, temporary CPU" in text or "position will not match" in text:
                log.debug("mpv %s", text)
                return
            (log.error if level in ("fatal", "error") else log.warning)("mpv %s", text)

    # ------------------------------------------------------------ the video surface
    def attach_surface(self, area):
        """area (a VideoArea, its GL context current) now shows the video."""
        if self.player is None:
            return False
        if self.surface is not None and self.surface is not area:
            self.surface.detach()
        try:
            mpv.GLRender(self.player, lambda fn: GLib.idle_add(fn), area.queue_render)
        except mpv.MPVError as e:
            self.player_error = str(e)
            log.error("video output: %s", e)
            self.toast(f"Can't show video: {e}")
            return False
        was_ready = self.render_ready
        self.surface, self.render_ready = area, True
        if self._pending is not None:
            pending, self._pending = self._pending, None
            self._load(*pending)
        elif not was_ready and self.current is not None and not self.idle:
            self._reinit_video()
        return True

    def detach_surface(self, area):
        if self.surface is area:
            if self.player is not None and self.player.render is not None:
                # Freeing the renderer drops the video track: remember it.
                vid = self.player.get("vid")
                if vid not in (None, False, "no"):
                    self._resume_vid = vid
                self.player.render.free()
            self.surface, self.render_ready = None, False

    def _reinit_video(self):
        """After the renderer moved (to the mini player and back), mpv's
        video output is gone and the track with it: selecting the track
        again rebuilds the output on the new renderer."""
        vid = getattr(self, "_resume_vid", None) or self.player.get("vid")
        self._resume_vid = None
        if vid in (None, False, "no"):
            vid = "auto"
        self.player.set("vid", "no")
        GLib.timeout_add(60, lambda: (self.player is not None and self.player.set("vid", str(vid)), False)[1])

    def _pick_variant(self):
        """An HLS or DASH stream offers each quality as a video track (mpv
        takes the highest): the best one up to the quality cap instead."""
        it = self.current
        if it is None or not it.get("url"):
            return
        vids = [t for t in (self.player.get("track-list") or []) if t.get("type") == "video" and t.get("demux-h")]
        if len(vids) < 2:
            return
        cap = self.quality
        ok = [t for t in vids if t["demux-h"] <= cap] or [min(vids, key=lambda t: t["demux-h"])]
        best = max(ok, key=lambda t: (t["demux-h"], t.get("demux-bitrate") or t.get("hls-bitrate") or 0))
        if not best.get("selected"):
            self.player.set("vid", str(best["id"]))
            log.info("stream: %sp of %s", best["demux-h"], sorted({t["demux-h"] for t in vids}))

    # ------------------------------------------------------------ quality
    def current_height(self):
        vt = next((t for t in self.tracks if t.get("type") == "video" and t.get("selected")), None)
        return (vt or {}).get("demux-h") or 0

    def qualities(self, then):
        """then(kind, heights): what the playing video offers. kind:
        "youtube" (reloads to switch), "stream" (an HLS/DASH variant, instant),
        "file" (one: the file's own), or "none"."""
        it = self.current
        if it is None:
            then("none", [])
            return
        local = self.downloaded(it)
        if it.get("yt") and not local:
            vid = it["yt"]
            if vid in self._qualities:
                then("youtube", self._qualities[vid])
                return

            def got(hs):
                self._qualities[vid] = hs
                then("youtube", hs)
            self.bg(lambda: youtube.qualities(vid), got, lambda e: (self.toast(f"Couldn't ask YouTube: {e}"),
                                                                    then("youtube", [])))
            return
        vids = sorted({t["demux-h"] for t in self.tracks if t.get("type") == "video" and t.get("demux-h")},
                      reverse=True)
        if it.get("url") and len(vids) > 1:
            then("stream", vids)
        else:
            then("file", vids)

    def set_quality(self, h):
        """Plays the current video at h (or the best up to it) and keeps h
        for the next videos and downloads."""
        self.quality = int(h)
        self._save_settings()
        if self.player is not None:
            self.player.set("ytdl-format", config.ytdl_format(self.quality))
        it = self.current
        if it is None:
            return
        if it.get("url") and not self.downloaded(it):
            self._pick_variant()   # a stream's variants: switch at once
        elif it.get("yt") and not self.downloaded(it) and not self.idle:
            # YouTube: the streams are picked when it opens, so reopen at the same second
            pos = self.pos
            self._load(it, pos if pos > 1 else None)
        self.toast(f"Quality: up to {self.quality}p" + (" · downloads use it too" if it.get("yt") or it.get("url") else ""))
        self.emit("tracks", "options")

    # ------------------------------------------------------------ preview frames (timeline hover)
    def details(self, then):
        """then(details or None): a YouTube video's description and storyboard
        (asked once per video, in the background)."""
        it = self.current
        if not it or not it.get("yt"):
            then(None)
            return
        vid = it["yt"]
        if vid in self._details:
            then(self._details[vid])
            return
        if vid in self._asking:
            return
        self._asking.add(vid)

        def got(r):
            self._asking.discard(vid)
            d, heights, board = r
            self._details[vid], self._qualities[vid], self._boards[vid] = d, heights, board
            then(d)
        self.bg(lambda: youtube.info(vid), got, lambda e: self._asking.discard(vid))

    def preview(self, t, then):
        """then((path, x, y, w, h) or None): a frame near t seconds of what's
        playing, for the timeline's hover. YouTube: its storyboard;
        files: ffmpeg, a frame per 5 s, cached."""
        it = self.current
        if it is None:
            return
        cache = os.path.join(config.CACHE, "thumbs")
        local = self.downloaded(it)
        if local:
            bucket = int(t // 5) * 5

            def grab():
                import hashlib
                import subprocess
                key = hashlib.sha1(f"{local}|{bucket}".encode()).hexdigest()[:20]
                out = os.path.join(cache, f"pv-{key}.jpg")
                if not os.path.exists(out):
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(bucket + 2), "-i", local, "-frames:v", "1",
                                    "-vf", "scale=192:-2", "-q:v", "6", out], capture_output=True, timeout=10)
                return (out, 0, 0, 0, 0) if os.path.exists(out) else None
            self.bg(grab, then, lambda e: None)
            return
        if not it.get("yt"):
            return
        vid = it["yt"]
        if vid not in self._boards:
            self.details(lambda d: None)
            return
        cell = youtube.storyboard_cell(self._boards[vid], t)
        if cell is None:
            return
        frag, x, y = cell
        board = self._boards[vid]
        path = os.path.join(cache, f"sb-{vid}-{frag}.jpg")
        if os.path.exists(path):
            then((path, x, y, board["w"], board["h"]))
            return

        def fetch():
            import urllib.request
            req = urllib.request.Request(board["frags"][frag]["url"], headers={"User-Agent": "drishya"})
            with urllib.request.urlopen(req, timeout=15) as r, open(path + ".part", "wb") as f:
                f.write(r.read())
            os.replace(path + ".part", path)
            return (path, x, y, board["w"], board["h"])
        self.bg(fetch, then, lambda e: None)

    def draw(self, fbo, w, h):
        r = self.player.render if self.player else None
        if r is not None:
            r.draw(fbo, w, h)

    # ------------------------------------------------------------ queue
    @property
    def current(self):
        return self.queue[self.cur] if 0 <= self.cur < len(self.queue) else None

    def _snapshot(self):
        cur = self.current
        return (copy.deepcopy(self.queue), cur["id"] if cur else None)

    def _changed(self, undoable=True, before=None):
        if undoable and before is not None:
            self.undo_stack.append(before)
            del self.undo_stack[:-UNDO_MAX]
            self.redo_stack.clear()
        self._save_queue()
        self.emit("queue")

    def _restore(self, snap):
        q, cur_id = snap
        self.queue = q
        self.cur = next((i for i, it in enumerate(q) if it["id"] == cur_id), -1)

    def undo(self):
        if not self.undo_stack:
            self.toast("Nothing to undo")
            return
        self.redo_stack.append(self._snapshot())
        self._restore(self.undo_stack.pop())
        self._changed(undoable=False)
        self.toast("Undone · Ctrl+r redoes")

    def redo(self):
        if not self.redo_stack:
            self.toast("Nothing to redo")
            return
        self.undo_stack.append(self._snapshot())
        self._restore(self.redo_stack.pop())
        self._changed(undoable=False)

    def _save_queue(self):
        keep = [{k: v for k, v in it.items() if k not in ("id", "pending")} for it in self.queue
                if not it.get("auto")][-500:]
        try:
            store.save_json(os.path.join(config.STATE, "queue.json"), keep)
        except OSError as e:
            log.warning("can't save the queue: %s", e)

    def _save_settings(self):
        try:
            store.save_json(os.path.join(config.STATE, "settings.json"),
                            {"autoplay": self.autoplay, "volume": round(self.volume), "quality": self.quality})
        except OSError as e:
            log.warning("can't save settings: %s", e)

    def add(self, items, where="end"):
        """where: end | next | play (play the first one now)."""
        if not items:
            return
        before = self._snapshot()
        new = [item_from(d) for d in items]
        # what you add goes before autoplay's suggestions
        if where in ("next", "play") and self.cur >= 0:
            at = self.cur + 1
        else:
            at = next((i for i in range(max(0, self.cur + 1), len(self.queue)) if self.queue[i].get("auto")),
                      len(self.queue))
        self.queue[at:at] = new
        if self.cur >= at:
            self.cur += len(new)
        self._changed(before=before)
        if where == "play" or self.cur < 0 or self.idle:
            self.play_index(at)
        else:
            self.toast(f"Added {len(new)} to {'play next' if where == 'next' else 'the queue'}"
                       if len(new) > 1 else f"Added “{new[0]['title'][:60]}”" + (" to play next" if where == "next" else ""))

    def add_url(self, text, where="play"):
        """A YouTube URL, a file, or search words (plays the top result)."""
        text = (text or "").strip()
        if not text:
            return
        path = os.path.expanduser(text[7:] if text.startswith("file://") else text)
        if os.path.isfile(path):
            self.add([{"file": os.path.realpath(path)}], where)
            return
        if os.path.isdir(path):
            _, vids = library.listdir(path)
            self.add(vids, where) if vids else self.toast(f"No videos in {path}")
            return
        vid = youtube.video_id(text)
        if vid:
            # A link says nothing about the video: its details come next
            # (autoplay waits for them, or it would look for "YouTube video").
            self.add([{"yt": vid, "title": "YouTube video", "thumb": youtube.thumb(vid), "pending": True}], where)
            self._fill_in(vid)
            return
        if is_stream_url(text):
            # HLS (.m3u8), DASH (.mpd), a direct file, or any site yt-dlp
            # knows: mpv opens it (ffmpeg for the streams, yt-dlp for the rest).
            url, user, password = auth.split_userinfo(text)
            if user or password:
                self.logins[auth.host_of(url)] = {"user": user or "", "password": password or ""}
            self.add([{"url": url}], where)
            return
        self.toast(f"Searching YouTube for “{text}”…")
        self.bg(lambda: youtube.search(text, 5), lambda r: self.add(r[:1], where) if r else self.toast("Nothing found"))

    def _fill_in(self, vid):
        def then(r):
            details, heights, board = r
            self._qualities[vid] = heights
            self._boards[vid] = board
            self._details[vid] = details
            for it in self.queue:
                if it.get("yt") == vid and it.get("pending"):
                    it.pop("pending", None)
                    it.update({k: v for k, v in details.items() if v and k != "yt"})
            if self.current and self.current.get("yt") == vid:
                self.store.touch(self.current)
                self._line_up_more()
            self._save_queue()
            self.emit("video", "queue", "history")

        def fail(e):
            log.warning("details of %s: %s", vid, e)
            for it in self.queue:
                if it.get("yt") == vid:
                    it.pop("pending", None)
        self.bg(lambda: youtube.info(vid), then, fail)

    def delete(self, idxs):
        idxs = sorted({i for i in idxs if 0 <= i < len(self.queue)})
        if not idxs:
            return []
        before = self._snapshot()
        removed = [self.queue[i] for i in idxs]
        playing_removed = self.cur in idxs
        if playing_removed:
            self._save_position()
        first = idxs[0]
        for i in reversed(idxs):
            del self.queue[i]
            if i < self.cur:
                self.cur -= 1
        self._changed(before=before)
        if playing_removed:
            # what came after the removed video plays in its place, if anything did
            if first < len(self.queue):
                self.play_index(first)
            else:
                self.cur = -1
                if self.player:
                    self.player.command("stop")
                self.emit("video", "player")
        return removed

    def insert(self, items, at):
        if not items:
            return
        before = self._snapshot()
        at = max(0, min(at, len(self.queue)))
        new = [dict(copy.deepcopy(it), id=next(_ids), auto=False) for it in items]
        self.queue[at:at] = new
        if self.cur >= at:
            self.cur += len(new)
        self._changed(before=before)

    def move(self, frm, to):
        """Moves one item; an autoplay suggestion moved becomes yours."""
        if not (0 <= frm < len(self.queue)) or not (0 <= to < len(self.queue)) or frm == to:
            return False
        before = self._snapshot()
        cur_id = self.current["id"] if self.current else None
        it = self.queue.pop(frm)
        was_auto = it.get("auto")
        it["auto"] = False
        self.queue.insert(to, it)
        self.cur = next((i for i, x in enumerate(self.queue) if x["id"] == cur_id), -1)
        self._changed(before=before)
        return was_auto

    def play_next(self, i):
        if 0 <= i < len(self.queue) and i != self.cur:
            target = self.cur + 1 if i > self.cur else self.cur
            self.move(i, target)

    def clear(self):
        if not self.queue:
            return
        before = self._snapshot()
        self._save_position()
        if self.player:
            self.player.command("stop")
        self.queue, self.cur = [], -1
        self._changed(before=before)
        self.emit("video", "player")

    # ------------------------------------------------------------ playback
    def source(self, it):
        """What mpv opens for an item: the downloaded copy if there is one."""
        if it.get("file"):
            return it["file"]
        local = self.store.downloaded(dl_key(it))
        if local:
            return local
        if it.get("url"):
            return it["url"]
        return youtube.watch_url(it["yt"])

    def play_index(self, i, start=None):
        if self.player is None:
            self.toast(f"Can't play: {self.player_error}")
            return
        if not (0 <= i < len(self.queue)):
            return
        self._save_position()
        self.cur = i
        it = self.queue[i]
        if start is None and self.conf["resume"] and not it.get("live"):
            start = store.resume_at(self.store.entry(it), it.get("duration"))
            if start:
                self.toast(f"Resuming at {fmt_time(start)} · S starts over")
        self.pos, self.duration, self.error = float(start or 0), float(it.get("duration") or 0), ""
        self.chapters, self.chapter, self.tracks = [], -1, []
        self.store.touch(it)
        if self.render_ready:
            self._load(it, start)
        else:
            self._pending = (it, start)
        self.emit("video", "queue", "history", "player")
        self._line_up_more()

    def _load(self, it, start):
        opts = {"force-media-title": it.get("title", "")}
        if start:
            opts["start"] = f"{start:.1f}"
        src = self.source(it)
        self._login_needed = None
        if src.startswith(("http://", "https://")):
            src = self._with_login(src, opts)
        self.player.loadfile(src, "replace", opts)
        self.player.set("pause", False)

    def _with_login(self, url, opts):
        """Adds what this server needs to sign in, if we know it: the user
        and password in the link (Digest) and a Basic header (also sent for
        every HLS segment), and for sites yt-dlp plays, the same login or
        your browser's cookies."""
        host = auth.host_of(url)
        login = self.logins.get(host)
        if login is None:
            found = auth.lookup(host)
            if found:
                login = self.logins[host] = {"user": found[0], "password": found[1]}
        if not login:
            return url
        raw = self._ytdl_raw
        if login.get("cookies"):
            opts["ytdl-raw-options"] = f"{raw},cookies-from-browser={mpv.quote(login['cookies'])}"
            return url
        user, password = login.get("user", ""), login.get("password", "")
        opts["http-header-fields"] = auth.basic_header(user, password)
        opts["ytdl-raw-options"] = f"{raw},username={mpv.quote(user)},password={mpv.quote(password)}"
        return auth.with_userinfo(url, user, password)

    def sign_in(self, host, user="", password="", remember=False, cookies=None):
        """Retries the current video with a login (from the sign-in panel)."""
        self.logins[host] = {"cookies": cookies} if cookies else {"user": user, "password": password}
        if remember and not cookies:
            self.bg(lambda: auth.remember(host, user, password),
                    lambda ok: self.toast("Saved in your keyring" if ok else "Couldn't save it in your keyring"))
        if self.current is not None:
            self.play_index(self.cur, start=self.pos or None)

    def forget_login(self, host):
        self.logins.pop(host, None)
        self.bg(lambda: auth.forget(host))

    def toggle(self):
        if self.player is None:
            return
        if self.current is None:
            if self.queue:
                self.play_index(0)
            return
        if self.idle:
            self.play_index(self.cur)
            return
        if self.duration and self.pos >= self.duration - 0.5 and self.paused:
            self.seek_to(0)
        self.player.set("pause", not self.paused)

    def pause(self):
        if self.player is not None and not self.paused:
            self.player.set("pause", True)

    def seek(self, secs):
        if self.player is not None and self.current is not None:
            self.player.command("seek", f"{secs:+.2f}", "relative+exact" if abs(secs) < 10 else "relative")

    def seek_to(self, secs):
        if self.player is not None and self.current is not None:
            self.player.command("seek", f"{max(0, secs):.2f}", "absolute")

    def next(self, n=1):
        if self.cur + n < len(self.queue):
            self.play_index(self.cur + n)
        elif self.autoplay and self.current is not None:
            self.toast("Finding something to watch next…")
            self._line_up_more(then_play=True)
        else:
            self.toast("That was the last one · M turns autoplay on" if not self.autoplay else "Nothing after this")

    def prev(self, n=1):
        if self.pos > 5 and n == 1:
            self.seek_to(0)
        elif self.cur - n >= 0:
            self.play_index(self.cur - n, start=0)
        else:
            self.seek_to(0)

    def set_volume(self, v):
        if self.player is not None:
            self.player.set("volume", f"{max(0, min(150, v)):.0f}")
            self.volume = max(0, min(150, v))
            self._save_settings()

    def change_volume(self, d):
        self.set_volume(self.volume + d)

    def mute(self):
        if self.player is not None:
            self.player.set("mute", not self.muted)

    def set_speed(self, s):
        if self.player is not None:
            s = max(0.25, min(4.0, round(s * 4) / 4 if s >= 0.25 else s))
            self.player.set("speed", f"{s:g}")
            self.toast(f"Speed {s:g}×" + ("" if s == 1 else " · \\ resets"))

    def cycle_subs(self):
        """Off, then each subtitle track, then off again."""
        subs = [t for t in self.tracks if t.get("type") == "sub"]
        if not subs:
            self.toast("This video has no subtitles")
            return
        cur = next((t for t in subs if t.get("selected")), None)
        i = subs.index(cur) + 1 if cur else 0
        if i >= len(subs):
            self.player.set("sid", "no")
            self.toast("Subtitles off")
            return
        t = subs[i]
        self.player.set("sid", str(t["id"]))
        self.player.set("sub-visibility", True)
        self.toast(f"Subtitles: {track_name(t)}  ({i + 1}/{len(subs)} · c for the next)")

    def cycle_audio(self):
        auds = [t for t in self.tracks if t.get("type") == "audio"]
        if len(auds) < 2:
            self.toast("This video has one audio track")
            return
        cur = next((i for i, t in enumerate(auds) if t.get("selected")), -1)
        t = auds[(cur + 1) % len(auds)]
        self.player.set("aid", str(t["id"]))
        self.toast(f"Audio: {track_name(t)}")

    def chapter_step(self, d):
        if not self.chapters:
            self.toast("This video has no chapters")
            return
        target = max(0, min(len(self.chapters) - 1, (self.chapter if self.chapter >= 0 else 0) + d))
        if d < 0 and self.chapter >= 0 and self.pos - self.chapters[self.chapter].get("time", 0) > 3:
            target = self.chapter   # back to the start of this chapter first, like any player
        self.seek_to(self.chapters[target].get("time", 0))
        self.toast(f"Chapter {target + 1}/{len(self.chapters)}: {self.chapters[target].get('title', '')}")

    def set_autoplay(self, on):
        self.autoplay = on
        self._save_settings()
        if not on:
            before = self._snapshot()
            self.queue = [it for i, it in enumerate(self.queue) if not (it.get("auto") and i > self.cur)]
            self._changed(before=before)
        else:
            self._line_up_more()
        self.toast("Autoplay on: more like this after your videos" if on else "Autoplay off: stops after your videos")
        self.emit("options")

    def screenshot(self):
        if self.player is not None and self.current is not None:
            self.player.command("screenshot")
            self.toast("Saved a screenshot to ~/Pictures")

    # ------------------------------------------------------------ ends, autoplay
    def _ended(self):
        it = self.current
        if it is None:
            return
        self.store.touch(it, pos=self.duration or self.pos, duration=self.duration, finished=True)
        self.store.flush()
        self.emit("history")
        if self.cur + 1 < len(self.queue):
            self.play_index(self.cur + 1, start=None)
        elif self.autoplay:
            self._line_up_more(then_play=True)

    def _line_up_more(self, then_play=False):
        """Autoplay: when nothing of yours is left after the current video,
        line up more like it (YouTube's related videos, or the next file in
        the folder: the next episode)."""
        it = self.current
        if not self.autoplay or it is None or it.get("pending"):
            return
        if any(not x.get("auto") for x in self.queue[self.cur + 1:]) and not then_play:
            return
        if any(x.get("auto") for x in self.queue[self.cur + 1:]):
            if then_play:
                self.play_index(self.cur + 1)
            return
        if it.get("file") and not it.get("yt"):
            nxt = library.next_in_folder(it["file"])
            if nxt:
                self.queue.append(item_from(nxt, auto=True))
                self._changed(undoable=False)
                if then_play:
                    self.play_index(len(self.queue) - 1)
            elif then_play:
                self.toast("That was the last video in this folder")
            return
        if not it.get("yt") or self.related_for == it["yt"]:
            return
        self.related_for = vid = it["yt"]
        seen = {x.get("yt") for x in self.queue}

        def then(results):
            self.related_for = None
            cur = self.current
            if cur is None or cur.get("yt") != vid:
                return
            fresh = [r for r in results if r["yt"] not in seen][:12]
            if not fresh:
                return
            self.queue.extend(item_from(r, auto=True) for r in fresh)
            self._changed(undoable=False)
            if then_play:
                self.play_index(self.cur + 1)

        def fail(e):
            self.related_for = None
            log.warning("related videos for %s: %s", vid, e)
            if then_play:
                self.toast(f"Couldn't find what to watch next: {e}")
        self.bg(lambda: youtube.related(vid, it.get("title", ""), it.get("channel", "")), then, fail)

    # ------------------------------------------------------------ history
    def _save_position(self):
        it = self.current
        if it is None or self.idle or not self.duration or it.get("live"):
            return
        self.store.touch(it, pos=self.pos, duration=self.duration)
        self.store.flush()

    def _save_tick(self):
        if self.current is not None and not self.paused and not self.idle and self.duration \
                and not self.current.get("live"):
            self.store.touch(self.current, pos=self.pos, duration=self.duration)
            if time.monotonic() - self._last_save > 30:
                self._last_save = time.monotonic()
                self.store.flush()
                self.emit("history")
        return True

    def forget(self, k):
        self.store.forget(k)
        self.store.flush()
        self.emit("history")

    def start_over(self):
        if self.current is not None:
            self.seek_to(0)
            self.store.touch(self.current, pos=0, finished=False)
            self.toast("From the beginning")

    # ------------------------------------------------------------ downloads
    # A download is known by its key: the YouTube id, or the link.
    def downloaded(self, it):
        key = dl_key(it)
        return it.get("file") or (self.store.downloaded(key) if key else None)

    def job_for(self, key):
        return next((j for j in self.jobs if j["key"] == key and j["state"] in ("queued", "running")), None)

    def download(self, it):
        key = dl_key(it)
        if not key:
            self.toast("That's already a file on your disk")
            return
        if it.get("live"):
            self.toast("A live stream can't be saved while it's live")
            return
        if self.store.downloaded(key):
            self.toast(f"Already downloaded: {self.store.downloaded(key)}")
            return
        if self.job_for(key):
            self.toast("Already downloading it · 5 shows downloads")
            return
        channel = it.get("channel") or (auth.host_of(it["url"]).split("://")[-1] if it.get("url") else "")
        with self._job_lock:
            self.jobs.append({"key": key, "yt": it.get("yt"), "url": it.get("url"), "title": it.get("title", key),
                              "channel": channel, "thumb": it.get("thumb"), "duration": it.get("duration", 0),
                              "pct": 0.0, "state": "queued", "path": None, "error": "", "stop": False,
                              "quality": self.quality})
        self.toast(f"Downloading “{it.get('title', '')[:50]}” · 5 shows progress")
        self.emit("downloads", "queue")
        self._start_downloads()

    def _start_downloads(self):
        if self._job_thread is None or not self._job_thread.is_alive():
            self._job_thread = threading.Thread(target=self._download_loop, name="downloads", daemon=True)
            self._job_thread.start()

    def retry(self, job):
        if job["state"] == "failed":
            job.update(state="queued", pct=0.0, error="", stop=False)
            self.emit("downloads")
            self._start_downloads()

    def cancel(self, job):
        job["stop"] = True
        if job["state"] == "queued":
            job.update(state="failed", error="cancelled")
            self.emit("downloads")

    def _download_loop(self):
        while True:
            with self._job_lock:
                job = next((j for j in self.jobs if j["state"] == "queued"), None)
                if job is None:
                    return
                job["state"] = "running"
            GLib.idle_add(lambda: (self.emit("downloads"), False)[1])
            last = [0.0]

            def progress(p, job=job, last=last):
                job["pct"] = p
                if p - last[0] >= 1:
                    last[0] = p
                    GLib.idle_add(lambda: (self.emit("downloads", "queue"), False)[1])
            login = self.logins.get(auth.host_of(job["url"])) if job.get("url") else None
            try:
                path = youtube.download(job["yt"] or job["url"], self.conf["download_dir"], job["title"],
                                        job["channel"], config.ytdl_format(job.get("quality") or self.quality),
                                        self.conf["subtitles"], progress, lambda job=job: job["stop"], login)
                job.update(state="done", pct=100.0, path=path)
                GLib.idle_add(lambda job=job: (self._downloaded(job), False)[1])
            except Exception as e:
                log.warning("download %s failed: %s", job["key"], e)
                job.update(state="failed", error=str(e))
                GLib.idle_add(lambda job=job: (self.toast(f"Download failed: {job['error']} · R retries"),
                                               self.emit("downloads", "queue"), False)[-1])

    def _downloaded(self, job):
        self.store.add_download(job["key"], job["path"])
        self.toast(f"Saved “{job['title'][:50]}” · it plays from your disk now")
        self.emit("downloads", "queue")

    def delete_download(self, key):
        path = self.store.downloaded(key)
        if path:
            try:
                os.remove(path)
            except OSError as e:
                self.toast(f"Couldn't delete it: {e}")
                return
        self.store.remove_download(key)
        self.jobs = [j for j in self.jobs if j["key"] != key]
        self.emit("downloads", "queue")

    # ------------------------------------------------------------ volume and brightness
    def restore_system(self):
        """The volume and brightness back to how they were before drishya
        changed them (the window closed, or drishya quit)."""
        changed = [a.ctl.name for a in (self.sys_volume, self.sys_brightness) if a.restore()]
        return changed

    # ------------------------------------------------------------ the end
    def shutdown(self):
        self.restore_system()
        self._save_position()
        self.store.flush()
        self._save_queue()
        for j in self.jobs:
            j["stop"] = True
        if self.player is not None:
            self.player.terminate()
            self.player = None
