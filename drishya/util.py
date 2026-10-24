"""Small pure helpers (no GTK), shared by the core and the views, and
tested on their own."""
import os
import urllib.parse

from . import youtube
from .mpv import quote


def fmt_time(s):
    s = int(max(0, s or 0))
    h, m, sec = s // 3600, s // 60 % 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def dl_key(it):
    """What a download is known by: the YouTube id, or the link."""
    return it.get("yt") or it.get("url")


def ytdl_raw_options(langs):
    """yt-dlp's options for playing: subtitles in your languages as real
    captions (en, en-US, en-orig), never YouTube's machine translations
    (en-de), which are slow and rate-limited."""
    return "sub-langs=" + quote(youtube.sub_patterns(langs or "en")) + ",write-subs=,write-auto-subs="


STREAM_SCHEMES = ("http://", "https://", "rtmp://", "rtmps://", "rtsp://", "srt://", "udp://", "mms://")


def is_stream_url(text):
    return text.lower().startswith(STREAM_SCHEMES) and " " not in text.strip()


def stream_title(url):
    """A readable name for a link until mpv knows its real title:
    "live.example.com · index.m3u8"."""
    u = urllib.parse.urlparse(url)
    name = os.path.basename(u.path.rstrip("/")) or ""
    host = (u.hostname or url) + (f":{u.port}" if u.port else "")
    return f"{host} · {urllib.parse.unquote(name)}" if name else host


def track_name(t):
    """'English (auto)', 'Hindi', 'Track 2'."""
    lang = t.get("lang") or ""
    title = t.get("title") or ""
    name = title or lang or f"Track {t.get('id')}"
    if lang and title and lang.lower() not in title.lower():
        name = f"{title} ({lang})"
    return name
