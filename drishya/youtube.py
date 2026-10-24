"""YouTube through yt-dlp: search, what to watch next, and downloads.
Playback itself goes through mpv's own yt-dlp support (it picks the
streams and renews them). Everything here blocks: call it from a worker
thread (core.bg)."""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse

from . import auth

YTDLP = ["yt-dlp", "--no-warnings", "--ignore-config", "--extractor-args", "youtube:lang=en"]


class YTError(Exception):
    pass


def available():
    return shutil.which("yt-dlp") is not None


def video_id(s):
    """The video id in a YouTube URL (or s itself if it is one)."""
    if re.fullmatch(r"[\w-]{11}", s or ""):
        return s
    u = urllib.parse.urlparse(s or "")
    host = u.hostname or ""
    if "youtu.be" in host:
        return u.path.strip("/")[:11] or None
    if "youtube" in host:
        q = urllib.parse.parse_qs(u.query)
        if "v" in q:
            return q["v"][0][:11]
        m = re.search(r"/(?:shorts|embed|live)/([\w-]{11})", u.path)
        if m:
            return m.group(1)
    return None


def watch_url(vid):
    return f"https://www.youtube.com/watch?v={vid}"


def thumb(vid):
    return f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"   # 320x180, 16:9


def _run(args, timeout=60):
    try:
        r = subprocess.run(YTDLP + args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise YTError("yt-dlp isn't installed") from None
    except subprocess.TimeoutExpired:
        raise YTError("YouTube took too long to answer") from None
    if r.returncode != 0:
        err = (r.stderr.strip().splitlines() or ["yt-dlp failed"])[-1]
        raise YTError(err.replace("ERROR: ", ""))
    return r.stdout


def uploaded(d):
    """When the video came out, as a unix time (or 0)."""
    for k in ("release_timestamp", "timestamp"):
        if d.get(k):
            return int(d[k])
    for k in ("release_date", "upload_date"):
        v = d.get(k)
        if v and re.fullmatch(r"\d{8}", str(v)):
            return int(time.mktime(time.strptime(str(v), "%Y%m%d")))
    return 0


def entry(d):
    """A search or related result as a plain dict (an item drishya can play)."""
    vid = d.get("id")
    return {"yt": vid, "title": one_line(d.get("title")) or vid, "channel": one_line(d.get("channel") or d.get("uploader")),
            "duration": d.get("duration") or 0, "thumb": thumb(vid), "views": d.get("view_count") or 0,
            "uploaded": uploaded(d), "live": d.get("live_status") == "is_live"}


def one_line(s):
    """Titles and channel names as one line: some carry newlines and runs
    of spaces (spam that would stretch a row)."""
    return " ".join((s or "").split())


def _playable(e):
    # Shorts without a length, upcoming premieres, channels in the results: skip.
    return bool(e.get("id")) and len(e["id"]) == 11 and (e.get("duration") or e.get("live_status") == "is_live")


def search(query, n=25):
    out = _run(["--flat-playlist", "-J", f"ytsearch{n}:{query}"], timeout=40)
    return [entry(e) for e in json.loads(out).get("entries") or [] if _playable(e)]


def related(vid, title="", channel="", n=20):
    """What YouTube would play after this video: its mix when it has one,
    else a search for more like it (same channel first)."""
    try:
        out = _run(["--flat-playlist", "-J", "--playlist-end", str(n + 1), f"{watch_url(vid)}&list=RD{vid}"], timeout=40)
        got = [entry(e) for e in json.loads(out).get("entries") or [] if _playable(e) and e.get("id") != vid]
        if got:
            return got
    except YTError:
        pass
    if title in ("", "YouTube video"):
        title = ""   # not known yet: a search on it would find anything
    words = " ".join(re.sub(r"[\(\[].*?[\)\]]|[|#].*", " ", title).split()[:6])
    got = search(f"{channel} {words}".strip(), n + 1) if (channel or words) else []
    return [e for e in got if e["yt"] != vid]


def info(vid):
    """A video's details (an item drishya can show), the heights it's
    offered in, and its storyboard (the timeline's preview frames), from
    one yt-dlp call: (item, heights, storyboard or None)."""
    d = json.loads(_run(["-J", "--no-playlist", watch_url(vid)], timeout=45))
    it = entry(d)
    it["description"] = (d.get("description") or "")[:2000]
    if d.get("thumbnail"):
        it["thumb"] = thumb(vid)
    return it, _heights(d), storyboard(d)


def storyboard(d):
    """YouTube's preview frames: images that are grids of small frames.
    The 160x90 one (sb1) when there is one: {"w", "h", "rows", "cols",
    "fps", "frags": [{"url", "duration"}]}."""
    boards = [f for f in d.get("formats") or [] if f.get("format_note") == "storyboard" and f.get("fragments")]
    if not boards:
        return None
    b = min(boards, key=lambda f: abs((f.get("width") or 0) - 160))
    return {"w": b.get("width"), "h": b.get("height"), "rows": b.get("rows") or 1, "cols": b.get("columns") or 1,
            "fps": b.get("fps") or 0, "frags": [{"url": f["url"], "duration": f.get("duration") or 0}
                                                 for f in b["fragments"] if f.get("url")]}


def storyboard_cell(sb, t):
    """(fragment index, x, y) of the frame nearest t seconds, or None."""
    if not sb or not sb.get("fps") or not sb.get("frags"):
        return None
    per = sb["rows"] * sb["cols"]
    frame = int(max(0, t) * sb["fps"])
    frag, cell = divmod(frame, per)
    if frag >= len(sb["frags"]):
        frag, cell = len(sb["frags"]) - 1, per - 1
    return frag, (cell % sb["cols"]) * sb["w"], (cell // sb["cols"]) * sb["h"]


def qualities(vid):
    """The video heights YouTube offers for a video, highest first
    (2160, 1440, 1080, 720…)."""
    return _heights(json.loads(_run(["-J", "--no-playlist", watch_url(vid)], timeout=45)))


def _heights(d):
    hs = {f.get("height") for f in d.get("formats") or []
          if f.get("vcodec") not in (None, "none") and f.get("height") and f.get("format_note") != "storyboard"
          and "storyboard" not in (f.get("format_id") or "")}
    return sorted((h for h in hs if h), reverse=True)


def ago(ts):
    """'3 days ago', '1 month ago', '13 years ago' (or '')."""
    if not ts:
        return ""
    s = max(0, time.time() - ts)
    for unit, n in (("year", 365 * 86400), ("month", 30 * 86400), ("week", 7 * 86400), ("day", 86400),
                    ("hour", 3600), ("minute", 60)):
        if s >= n:
            k = int(s // n)
            return f"{k} {unit}{'s' if k > 1 else ''} ago"
    return "just now"


def views(n):
    """'1.2M views'."""
    if not n:
        return ""
    for unit, k in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= k:
            return f"{n / k:.1f}".rstrip("0").rstrip(".") + f"{unit} views"
    return f"{n} view{'s' if n != 1 else ''}"


def safe(name):
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]', " ", name or "").strip(" .")
    return re.sub(r"\s{2,}", " ", name)[:120] or "Unknown"


def sub_patterns(langs):
    """Your languages as real captions (en, en-US, en-orig), not YouTube's
    machine translations (en-de: English from German), which are slow and
    get rate-limited. yt-dlp matches these case-insensitively (re.I), so
    the region part switches that off: regions are upper case (US, GB) or
    digits (419), translations' source languages lower case."""
    pats = []
    for l in (x.strip() for x in (langs or "").split(",")):
        if l:
            pats += [l, f"{l}-orig", f"{l}-(?-i:[A-Z0-9][A-Za-z0-9]*)"]
    return ",".join(pats + ["-live_chat"])


def download(target, folder, title, channel, fmt, subs="en", progress=None, should_stop=None, login=None):
    """Downloads a video (a YouTube id, or any link yt-dlp can save: an
    HLS stream, a file on a server, another site) into
    folder/<channel>/<title>.mkv with its subtitles, chapters, thumbnail and
    tags, and returns the file's path. progress(percent) is called as it
    goes. login: {"user", "password"} or {"cookies": browser}. When only
    the subtitles fail (YouTube limits them), it downloads without them."""
    try:
        return _download(target, folder, title, channel, fmt, subs, progress, should_stop, login)
    except YTError as e:
        if subs and "subtitle" in str(e).lower():
            # the subtitles failed, not the video: drop what they left, try without
            import glob
            for f in glob.glob(os.path.join(glob.escape(os.path.join(folder, safe(channel))), glob.escape(safe(title)) + ".*.vtt")):
                os.remove(f)
            return _download(target, folder, title, channel, fmt, None, progress, should_stop, login)
        raise


def _download(target, folder, title, channel, fmt, subs, progress, should_stop, login):
    url = watch_url(target) if re.fullmatch(r"[\w-]{11}", target) else target
    out_dir = os.path.join(folder, safe(channel))
    os.makedirs(out_dir, exist_ok=True)
    template = os.path.join(out_dir, safe(title) + ".%(ext)s")
    args = YTDLP + ["-f", fmt, "--merge-output-format", "mkv", "--embed-metadata", "--embed-chapters",
                    "--embed-thumbnail", "--newline", "--no-playlist",
                    "--progress-template", "download:%(progress._percent_str)s",
                    "--print", "after_move:filepath", "-o", template]
    if subs:
        args += ["--write-subs", "--write-auto-subs", "--sub-langs", sub_patterns(subs), "--embed-subs"]
    if login and login.get("cookies"):
        args += ["--cookies-from-browser", login["cookies"]]
    elif login:
        user, password = login.get("user", ""), login.get("password", "")
        args += ["--username", user, "--password", password,
                 "--add-header", auth.basic_header(user, password).replace(": ", ":", 1)]
    p = subprocess.Popen(args + [url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    path = None
    for line in p.stdout:
        line = line.strip()
        m = re.match(r"^\s*([\d.]+)%$", line)
        if m:
            if progress:
                progress(min(99.0, float(m.group(1))))
        elif line.startswith("/") and os.path.exists(line):
            path = line
        if should_stop and should_stop():
            p.kill()
            raise YTError("cancelled")
    err = p.stderr.read()
    p.wait()
    if p.returncode != 0:
        raise YTError((err.strip().splitlines() or ["download failed"])[-1].replace("ERROR: ", ""))
    if not path:
        cand = os.path.join(out_dir, safe(title) + ".mkv")
        if not os.path.exists(cand):
            raise YTError("yt-dlp finished but the file isn't there")
        path = cand
    if subs:   # they're inside the .mkv now: no copies beside it
        import glob
        for f in glob.glob(os.path.join(glob.escape(out_dir), glob.escape(safe(title)) + ".*")):
            if f.endswith((".vtt", ".srt", ".ass")):
                os.remove(f)
    return path
