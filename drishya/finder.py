"""What the search panel (/) finds in drishya: a link you paste, your
videos, your history, YouTube, and commands."""
import os
import re
import threading
import time

from . import library, store, youtube
from .util import fmt_time, is_stream_url
from .widgets import G, label, thumb_widget

SCOPES = ["All", "YouTube", "Your videos", "History", "Commands"]
YT, FILES, HISTORY, COMMANDS = 1, 2, 3, 4
# (command, what it needs, what it does): the Commands scope lists these
COMMANDS_LIST = [
    ("open", "<link or file>", "Play a link (HLS, a video file, a site yt-dlp knows) or a file"),
    ("add", "<link or file>", "Add to Up next"),
    ("yt", "<search>", "All YouTube results for a search"),
    ("seek", "<1:30 or +30>", "Jump to a time, or by an amount"),
    ("speed", "<1.5>", "Playback speed"),
    ("vol", "<80 or +10>", "Volume"),
    ("quality", "<720>", "Highest quality, from now on"),
    ("sub", "<en or off>", "Subtitles by language"),
    ("sleep", "<30m or off>", "Pause after a while"),
    ("shot", "", "Save a screenshot to ~/Pictures"),
    ("autoplay", "<on or off>", "More videos after yours"),
    ("dl", "", "Download what's playing"),
    ("clear", "", "Empty Up next (u brings it back)"),
    ("logout", "<server>", "Forget a server's login"),
    ("q", "", "Hide the window"),
    ("qa", "", "Quit drishya"),
]


def looks_like_link(q):
    q = q.strip()
    return is_stream_url(q) or q.startswith(("file://", "/", "~/")) and os.path.exists(os.path.expanduser(q[7:] if q.startswith("file://") else q))


class Finder:
    scopes = SCOPES

    def __init__(self, win):
        self.win, self.core = win, win.core
        self.index, self.index_at = [], 0
        self.index_lock = threading.Lock()
        self.had_local = False

    # ------------------------------------------------------------ the index of your videos
    def refresh_index(self, force=False):
        if not force and time.monotonic() - self.index_at < 60:
            return
        self.index_at = time.monotonic()
        dirs = [d for d in self.core.conf["video_dirs"] if os.path.isdir(d)]

        def work():
            return library.search(dirs, "", limit=20000)

        def then(found):
            with self.index_lock:
                self.index = found
            self.win.search.refresh_thumbs()
        self.core.bg(work, then, lambda e: None)

    # ------------------------------------------------------------ panel API
    def prefix(self, text):
        if text.startswith(":"):
            return COMMANDS, text[1:]
        m = re.match(r"^(yt|lib|h)\s+(.*)$", text, re.S)
        if m:
            return {"yt": YT, "lib": FILES, "h": HISTORY}[m.group(1)], m.group(2)
        return None, text

    def wants_remote(self, q, scope):
        return scope in (0, YT) and len(q.strip()) >= 2 and not looks_like_link(q) and youtube.available()

    def _lead(self, it, w=96, h=54):
        path = self.win.thumb(it)
        progress = None
        e = self.core.store.entry(it)
        if e and e.get("duration"):
            progress = 1.0 if e.get("finished") else (e.get("pos") or 0) / e["duration"]
        glyph = G["yt"] if it.get("yt") else G["film"]
        return lambda: thumb_widget(path, w, h, glyph, progress)

    def _video(self, it, top=False):
        sub = []
        if it.get("yt"):
            sub = [it.get("channel") or "", youtube.views(it.get("views")), youtube.ago(it.get("uploaded"))]
        elif it.get("file"):
            sub = [os.path.dirname(it["file"]).replace(os.path.expanduser("~"), "~")]
        elif it.get("url"):
            sub = [it["url"][:70]]
        e = self.core.store.entry(it)
        if e and store.resume_at(e) > 0 and e.get("duration"):
            sub.append(f"{fmt_time(e['duration'] - e['pos'])} left")
        badge = ("YouTube", "yt") if it.get("yt") and not self.core.downloaded(it) else ("file", "local") \
            if it.get("file") or self.core.downloaded(it) else ("link", "yt")
        return dict(it, sub=" · ".join(s for s in sub if s), badge=badge,
                    dur=fmt_time(it["duration"]) if it.get("duration") else "",
                    lead=self._lead(it, 160 if top else 96, 90 if top else 54))

    @staticmethod
    def _match(words, *texts):
        hay = " ".join(t or "" for t in texts).lower()
        return all(w in hay for w in words)

    def instant(self, q, scope):
        words = q.lower().split()
        secs = []
        if scope == COMMANDS:
            name = q.split(" ", 1)[0].lower()
            hits = [c for c in COMMANDS_LIST if c[0].startswith(name)] if name else COMMANDS_LIST
            return [{"title": "Commands", "right": "Enter runs · one that needs more fills the box",
                     "items": [{"kind": "command", "cmd": c[0], "typed": q, "needs": c[1],
                                "title": f":{c[0]} {c[1]}".strip(), "sub": c[2],
                                "lead": lambda: label(":", "glyph search-lead-glyph", ellipsize=False)} for c in hits]}]
        if looks_like_link(q):
            url = q.strip()
            kind = "an HLS stream" if ".m3u8" in url else "a YouTube video" if youtube.video_id(url) else \
                "a video link" if "://" in url else "a file on your disk"
            secs.append({"title": "Link", "top": True, "items": [
                {"kind": "link", "url": url, "title": "Play this link", "sub": f"{kind} · {url[:80]}",
                 "lead": lambda: label(G["play"], "glyph search-link-glyph", ellipsize=False),
                 "acts": [("Enter", "play"), ("Ctrl+Enter", "next"), ("Ctrl+d", "save")]}]})
            return secs
        local = []
        if scope in (0, FILES) and words:
            with self.index_lock:
                local = [v for v in self.index if self._match(words, v["title"], v["file"])][:8 if scope else 5]
        hist = []
        if scope in (0, HISTORY) and words:
            hist = [dict(e) for k, e in self.core.store.recent()
                    if self._match(words, e.get("title"), e.get("channel"))][:8 if scope else 4]
        self.had_local = bool(local or hist)
        if scope == 0 and (local or hist):
            first = (local or hist)[0]
            secs.append({"title": "Top result", "top": True, "items": [self._video(first, top=True)]})
            if local:
                local = local[1:]
            else:
                hist = hist[1:]
        if local:
            secs.append({"title": "Your videos", "right": f"{len(local)}", "items": [self._video(v) for v in local]})
        if hist:
            secs.append({"title": "History", "items": [self._video(e) for e in hist]})
        return secs

    def remote(self, q, scope):
        results = youtube.search(q, 10 if scope == 0 else 20)
        items = [self._video(r) for r in results]
        secs = []
        if items and scope == 0 and not self.had_local:
            secs.append({"title": "Top result", "top": True, "items": [self._video(results[0], top=True)]})
            items = items[1:]
        if items:
            items.append({"kind": "more", "query": q, "title": f"All YouTube results for “{q}”",
                          "sub": "opens them as a page, with more", "lead": lambda: label(G["yt"], "glyph search-lead-glyph",
                                                                                          ellipsize=False)})
            secs.append({"title": "YouTube", "right": "Ctrl+d downloads", "items": items})
        return secs

    def home(self):
        cont = [dict(e) for _k, e in self.core.store.unfinished()][:4]
        recent = [dict(e) for _k, e in self.core.store.recent() if store.resume_at(e) == 0][:4]
        out = []
        if cont:
            out.append({"title": "Continue watching", "items": [self._video(e) for e in cont]})
        if recent:
            out.append({"title": "Watched lately", "items": [self._video(e) for e in recent]})
        if not out:
            out.append({"title": "Try", "items": [], "note": "Type to search YouTube and your videos, or paste any link. "
                                                          "Tab picks where to look; : lists commands."})
        return out

    def act(self, it, how):
        """Does it; True keeps the panel open."""
        c, w = self.core, self.win
        kind = it.get("kind")
        if kind == "command":
            typed = it.get("typed", "").strip()
            name = typed.split(" ", 1)[0]
            if it["needs"] and not (name == it["cmd"] and " " in typed):
                w.search.entry.set_text(f":{it['cmd']} ")   # needs more: type it
                w.search.entry.set_position(-1)
                return True
            w.command(typed if name == it["cmd"] else it["cmd"])
            return False
        if kind == "more":
            w.switch("youtube")
            w.views["youtube"].search(it["query"])
            return False
        where = {"play": "play", "next": "next", "add": "end"}.get(how)
        if kind == "link":
            if how == "download":
                c.download({"url": it["url"], "title": it["url"]})
                return False
            c.add_url(it["url"], where or "play")
        else:
            item = {k: v for k, v in it.items() if k in ("yt", "file", "url", "title", "channel", "thumb", "duration",
                                                         "views", "uploaded", "live")}
            if how == "download":
                c.download(item)
                return False
            c.add([item], where or "play")
            if where in ("next", "end"):
                c.toast(f"“{item.get('title', '')[:50]}” {'plays next' if where == 'next' else 'added to Up next'}")
        if how == "play":
            w.switch("watch")
        return False
