"""~/.config/drishya/config.toml (everything optional):

  [drishya]
  quality = 1080           # highest YouTube resolution to stream or download
  autoplay = true          # line up more after your videos (related, or the next episode)
  resume = true            # start where you stopped
  seek_step = 10           # seconds for , and .
  fine_step = 5            # seconds for h and l on the Watch tab
  volume_step = 5
  subtitles = "en"         # preferred subtitle languages (c shows them)
  video_dirs = ["~/Videos"]
  download_dir = "~/Videos/YouTube"
  hwdec = "auto-copy-safe" # mpv's hardware decoding; "no" to turn it off
  pause_on_hide = true     # q pauses (z keeps a small window playing)
  # opacity = 0.62         # window background (unset: the theme's panel glass)
"""
import os
import tomllib

CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "drishya", "config.toml")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "drishya")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "drishya")

DEFAULTS = {
    "quality": 1080,
    "autoplay": True,
    "resume": True,
    "seek_step": 10,
    "fine_step": 5,
    "volume_step": 5,
    "subtitles": "en",
    "video_dirs": ["~/Videos"],
    "download_dir": "~/Videos/YouTube",
    "hwdec": "auto-copy-safe",
    "pause_on_hide": True,
    "opacity": None,
}


def load(path=CONFIG):
    conf = dict(DEFAULTS)
    try:
        with open(path, "rb") as f:
            conf.update(tomllib.load(f).get("drishya", {}))
    except FileNotFoundError:
        pass
    except tomllib.TOMLDecodeError as e:
        import logging
        logging.getLogger("drishya").warning("%s: %s; using defaults", path, e)
    # Types the rest of the code relies on: a bad value falls back, never crashes.
    for k, default in DEFAULTS.items():
        v = conf[k]
        if isinstance(default, bool):
            ok = isinstance(v, bool)
        elif isinstance(default, int):
            ok = isinstance(v, int) and not isinstance(v, bool)
        elif isinstance(default, list):
            if isinstance(v, str):
                conf[k] = v = [v]
            ok = isinstance(v, list) and all(isinstance(x, str) for x in v)
        elif isinstance(default, str):
            ok = isinstance(v, str)
        else:   # opacity: None or a number
            ok = v is None or isinstance(v, (int, float)) and not isinstance(v, bool)
        if not ok:
            import logging
            logging.getLogger("drishya").warning("%s: %s = %r isn't valid; using %r", path, k, v, default)
            conf[k] = default
    conf["quality"] = max(144, min(4320, conf["quality"]))
    conf["video_dirs"] = [os.path.expanduser(d) for d in conf["video_dirs"]]
    conf["download_dir"] = os.path.expanduser(conf["download_dir"])
    return conf


def ytdl_format(quality):
    """yt-dlp's format for a height cap: the best video up to it (not AV1,
    which few laptops decode in hardware; it'd play on the CPU) with the
    best audio, else the best single file up to it."""
    q = int(quality)
    return f"bv*[height<={q}][vcodec!^=av01]+ba/bv*[height<={q}]+ba/b[height<={q}]/b"


def ensure_dirs():
    for d in (STATE, CACHE, os.path.join(CACHE, "thumbs")):
        os.makedirs(d, exist_ok=True)
