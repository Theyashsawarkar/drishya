"""Your videos: folders under video_dirs, browsed like yazi (a column per
folder). Episode-aware sorting (S01E02, "Episode 10" after "Episode 9"),
durations from ffprobe and thumbnails from ffmpeg, cached. The scans and
ffmpeg calls block: call them from a worker thread."""
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess

log = logging.getLogger("drishya.library")

VIDEO_EXT = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".wmv", ".flv", ".ts", ".mpg", ".mpeg", ".3gp", ".ogv", ".m3u8", ".m3u"}   # .m3u8: a saved HLS playlist plays too


def is_video(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXT


def natural(s):
    """Sort key: numbers as numbers, so "Episode 10" comes after "Episode 9"."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def nice_title(filename):
    """"The.Show.S01E02.1080p.WEB-DL.x264.mkv" -> "The Show S01E02"."""
    name = os.path.splitext(os.path.basename(filename))[0]
    if name.count(".") >= 2 and " " not in name:
        name = name.replace(".", " ")
    name = name.replace("_", " ")
    name = re.sub(r"(?i)\b(2160p|1080p|720p|480p|4k|uhd|web[- ]?(dl|rip)|blu[- ]?ray|brrip|hdrip|x26[45]|h ?26[45]|hevc|"
                  r"aac\d?(\.\d)?|ddp?\d?(\.\d)?|10bit|hdr|yify|rarbg)\b.*$", "", name)
    return re.sub(r"\s{2,}", " ", name).strip(" -[](") or os.path.basename(filename)


def episode(filename):
    """(season, episode) from a file name, or None."""
    m = re.search(r"(?i)s(\d{1,2})[ ._-]?e(\d{1,3})", filename) or re.search(r"(?i)\b(\d{1,2})x(\d{2,3})\b", filename)
    return (int(m.group(1)), int(m.group(2))) if m else None


def listdir(path):
    """(folders, videos) in path: [{"name", "path"}], [{"file", "title"}],
    hidden ones left out, both in natural order."""
    folders, videos = [], []
    try:
        entries = list(os.scandir(path))
    except OSError as e:
        log.warning("can't read %s: %s", path, e)
        return [], []
    for d in entries:
        if d.name.startswith("."):
            continue
        try:
            if d.is_dir():
                folders.append({"name": d.name, "path": d.path})
            elif d.is_file() and is_video(d.name):
                videos.append({"file": d.path, "title": nice_title(d.name), "size": d.stat().st_size})
        except OSError:
            continue
    folders.sort(key=lambda f: natural(f["name"]))
    videos.sort(key=lambda v: natural(os.path.basename(v["file"])))
    return folders, videos


def count_videos(path, limit=999):
    n = 0
    for _root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        n += sum(1 for f in files if is_video(f))
        if n >= limit:
            break
    return n


def next_in_folder(path):
    """The video after this one in its folder (the next episode), or None."""
    _, videos = listdir(os.path.dirname(path))
    files = [v["file"] for v in videos]
    try:
        i = files.index(path)
    except ValueError:
        return None
    return videos[i + 1] if i + 1 < len(videos) else None


def search(dirs, query, limit=200):
    """Every video under dirs whose name has all the words of query."""
    words = query.lower().split()
    out = []
    for top in dirs:
        for root, ds, files in os.walk(top):
            ds[:] = [d for d in ds if not d.startswith(".")]
            for f in files:
                if is_video(f) and all(w in os.path.join(root, f).lower() for w in words):
                    out.append({"file": os.path.join(root, f), "title": nice_title(f)})
                    if len(out) >= limit:
                        return out
    return sorted(out, key=lambda v: natural(v["file"]))


def _cache_name(path, cache, ext):
    try:
        st = os.stat(path)
    except OSError:
        return None
    h = hashlib.sha1(f"{path}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:20]
    return os.path.join(cache, h + ext)


def probe(path, cache):
    """{"duration"} from ffprobe, cached next to the thumbnails."""
    out = _cache_name(path, cache, ".json")
    if out and os.path.exists(out):
        try:
            return json.load(open(out))
        except ValueError:
            pass
    info = {"duration": 0}
    if shutil.which("ffprobe"):
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                               capture_output=True, text=True, timeout=20)
            info["duration"] = float(json.loads(r.stdout or "{}").get("format", {}).get("duration") or 0)
        except (subprocess.TimeoutExpired, ValueError, OSError) as e:
            log.debug("ffprobe %s: %s", path, e)
    if out:
        try:
            json.dump(info, open(out, "w"))
        except OSError:
            pass
    return info


def thumbnail(path, cache, duration=0):
    """A 320 px wide frame from a tenth of the way in (past the intro),
    cached; None without ffmpeg or when it fails."""
    out = _cache_name(path, cache, ".jpg")
    if not out:
        return None
    if os.path.exists(out):
        return out
    if not shutil.which("ffmpeg"):
        return None
    at = max(1.0, min(120.0, (duration or 60) / 10))
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.1f}", "-i", path, "-frames:v", "1",
                        "-vf", "scale=320:-2", "-q:v", "5", out], capture_output=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError) as e:
        log.debug("thumbnail %s: %s", path, e)
    return out if os.path.exists(out) and os.path.getsize(out) > 0 else None
