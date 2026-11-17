"""A head start for YouTube: most of the wait before a video plays is
yt-dlp asking YouTube about it (about 6 s). mpv's ytdl_hook asks through
bin/drishya-ytdl (script-opts ytdl_hook-ytdl_path), which answers from
this cache when drishya already asked the same question: it does while you
look at a search result, and for the next video in the queue.

The cache keeps yt-dlp's answer (stream links that YouTube lets live for
hours) for FRESH seconds. Nothing with a login in it is ever kept: the
shim passes those straight to yt-dlp. Pure Python, no GTK: the tests use it.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

from .config import CACHE

DIR = os.path.join(CACHE, "ytdl")
TEMPLATE = os.path.join(DIR, "args.json")   # how mpv last asked, without the link
FRESH = 45 * 60            # well inside the links' life (YouTube's last about 6 h)
LOCK_WAIT = 30             # a prefetch already running: wait for it this long at most
SECRET = ("--username", "--password", "--video-password", "--cookies", "--cookies-from-browser",
          "--netrc", "--netrc-location", "--ap-username", "--ap-password", "--add-header")


def split(argv):
    """(args, link) for the question mpv asks about one link (its command
    line ends with "--" and the link), else (None, None)."""
    if len(argv) >= 2 and argv[-2] == "--":
        return list(argv[:-2]), argv[-1]
    return None, None


def private(args):
    """Does this command line carry a login? (It's never cached.)"""
    return any(a == s or a.startswith(s + "=") for a in args for s in SECRET)


def _key(args, link):
    return hashlib.sha1(json.dumps([args, link]).encode()).hexdigest()


def _path(args, link):
    return os.path.join(DIR, _key(args, link) + ".json")


def fresh(path, now=None):
    try:
        return (now or time.time()) - os.path.getmtime(path) < FRESH and os.path.getsize(path) > 0
    except OSError:
        return False


def ytdlp():
    return shutil.which("yt-dlp")


def _write(path, data):
    os.makedirs(DIR, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _ask(args, link):
    """yt-dlp's answer (bytes) or None; its complaints go to our stderr."""
    exe = ytdlp()
    if exe is None:
        return None
    r = subprocess.run([exe, *args, "--", link], capture_output=True, timeout=90, check=False)
    if r.returncode != 0 or not r.stdout.strip():
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-2000:])
        return None
    return r.stdout


def prune(now=None):
    now = now or time.time()
    try:
        names = os.listdir(DIR)
    except OSError:
        return
    for n in names:
        p = os.path.join(DIR, n)
        try:
            if n != "args.json" and now - os.path.getmtime(p) > 2 * FRESH:
                os.remove(p)
        except OSError:
            pass


def prefetch(link):
    """Asks yt-dlp about link the way mpv will (from its last command line),
    and keeps the answer. True when an answer is ready. Blocks: a worker thread."""
    try:
        with open(TEMPLATE) as f:
            args = json.load(f)
    except (OSError, ValueError):
        return False            # mpv hasn't asked anything yet: nothing to copy
    if not isinstance(args, list) or private(args):
        return False
    path = _path(args, link)
    if fresh(path):
        return True
    lock = path + ".lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return False            # already on its way
    except OSError:
        return False
    try:
        prune()
        data = _ask(args, link)
        if data:
            _write(path, data)
        return bool(data)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def shim(argv, out=None):
    """What bin/drishya-ytdl does: the cached answer, else yt-dlp's (kept)."""
    out = out or sys.stdout.buffer
    args, link = split(argv)
    exe = ytdlp()
    if args is None or private(args):
        if exe is None:
            sys.stderr.write("yt-dlp isn't installed\n")
            return 1
        os.execv(exe, [exe, *argv])          # not one we keep: yt-dlp itself
    path = _path(args, link)
    lock = path + ".lock"
    deadline = time.monotonic() + LOCK_WAIT
    while not fresh(path) and os.path.exists(lock) and time.monotonic() < deadline:
        time.sleep(0.1)                      # drishya is asking right now: wait for that answer
    if fresh(path):
        with open(path, "rb") as f:
            out.write(f.read())
        out.flush()
        return 0
    try:
        _write(TEMPLATE, json.dumps(args).encode())
    except OSError:
        pass
    data = _ask(args, link)
    if data is None:
        return 1
    try:
        _write(path, data)
    except OSError:
        pass
    out.write(data)
    out.flush()
    return 0
