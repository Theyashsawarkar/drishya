"""What drishya remembers between runs: where you stopped in every video
(resume), what you watched (history), the queue, and which YouTube videos
you downloaded. JSON files in ~/.local/state/drishya, written atomically."""
import json
import logging
import os
import time

log = logging.getLogger("drishya.store")

RESUME_MIN = 15        # seconds in before a position is worth resuming
FINISHED_TAIL = 0.95   # watched this much (or within END_SLACK of the end): finished
END_SLACK = 20
HISTORY_MAX = 2000


def key(item):
    """One id per video, whatever plays it: "yt:<id>" for YouTube (also
    after it's downloaded), "file:<path>" for your files."""
    if item.get("yt"):
        return "yt:" + item["yt"]
    if item.get("url"):
        return "url:" + item["url"]
    return "file:" + os.path.realpath(item.get("file") or "")


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        log.warning("%s unreadable (%s): starting fresh", path, e)
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def is_finished(pos, duration):
    if not duration:
        return False
    return pos >= duration * FINISHED_TAIL or pos >= duration - END_SLACK


def resume_at(entry, duration=None):
    """Where to start a video from its history entry (0: the beginning)."""
    if not entry:
        return 0
    pos = float(entry.get("pos") or 0)
    dur = float(duration or entry.get("duration") or 0)
    if entry.get("finished") or pos < RESUME_MIN or (dur and is_finished(pos, dur)):
        return 0
    return pos


class Store:
    FIELDS = ("title", "channel", "thumb", "duration", "yt", "file", "url", "views", "uploaded", "live")

    def __init__(self, folder):
        self.folder = folder
        self.history = load_json(os.path.join(folder, "history.json"), {})
        self.downloads = load_json(os.path.join(folder, "downloads.json"), {})   # yt id or link -> file
        self._dirty = False

    # ---------------------------------------------------------- history
    def entry(self, item):
        return self.history.get(key(item))

    def touch(self, item, pos=None, duration=None, finished=None):
        """Records that item was watched (now), with its position."""
        k = key(item)
        e = self.history.get(k) or {}
        for f in self.FIELDS:
            if item.get(f):
                e[f] = item[f]
        if duration:
            e["duration"] = duration
        if pos is not None:
            e["pos"] = round(float(pos), 1)
            e["finished"] = is_finished(pos, e.get("duration") or 0) if finished is None else finished
        elif finished is not None:
            e["finished"] = finished
        e["at"] = time.time()
        self.history[k] = e
        self._dirty = True
        if len(self.history) > HISTORY_MAX:
            for old in sorted(self.history, key=lambda x: self.history[x].get("at", 0))[:len(self.history) - HISTORY_MAX]:
                del self.history[old]
        return e

    def forget(self, k):
        if self.history.pop(k, None) is not None:
            self._dirty = True

    def recent(self):
        """[(key, entry)], newest first."""
        return sorted(self.history.items(), key=lambda kv: kv[1].get("at", 0), reverse=True)

    def unfinished(self):
        return [(k, e) for k, e in self.recent() if resume_at(e) > 0]

    # ---------------------------------------------------------- downloads
    def downloaded(self, key):
        path = self.downloads.get(key) if key else None
        return path if path and os.path.exists(path) else None

    def add_download(self, yt, path):
        self.downloads[yt] = path
        save_json(os.path.join(self.folder, "downloads.json"), self.downloads)

    def remove_download(self, yt):
        if self.downloads.pop(yt, None):
            save_json(os.path.join(self.folder, "downloads.json"), self.downloads)

    # ---------------------------------------------------------- saving
    def flush(self):
        if self._dirty:
            self._dirty = False
            try:
                save_json(os.path.join(self.folder, "history.json"), self.history)
            except OSError as e:
                log.warning("can't save the history: %s", e)
