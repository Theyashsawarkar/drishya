"""The system's volume and the screen's brightness, changed from drishya's
keys and put back as they were when the window closes. Volume through
pactl (else wpctl), brightness through brightnessctl; without them, the
keys say so instead of failing."""
import logging
import re
import shutil
import subprocess

log = logging.getLogger("drishya.system")


def _run(*args):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=2)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("%s: %s", args[0], e)
        return None


class Volume:
    """The default output's volume, 0..100 %."""
    name = "volume"

    @staticmethod
    def available():
        return shutil.which("pactl") or shutil.which("wpctl")

    def get(self):
        if shutil.which("pactl"):
            out = _run("pactl", "get-sink-volume", "@DEFAULT_SINK@") or ""
            m = re.search(r"(\d+)%", out)
            return int(m.group(1)) if m else None
        out = _run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@") or ""
        m = re.search(r"([\d.]+)", out)
        return round(float(m.group(1)) * 100) if m else None

    def set(self, pct):
        pct = max(0, min(100, int(pct)))
        if shutil.which("pactl"):
            _run("pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pct}%")
        else:
            _run("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{pct / 100:.2f}")
        return pct


class Brightness:
    """The screen's backlight, 1..100 % (never 0: a black screen)."""
    name = "brightness"

    @staticmethod
    def available():
        return shutil.which("brightnessctl") and (_run("brightnessctl", "-m") or "").strip()

    def get(self):
        out = (_run("brightnessctl", "-m") or "").split(",")
        try:
            return int(out[3].rstrip("%"))
        except (IndexError, ValueError):
            return None

    def set(self, pct):
        pct = max(1, min(100, int(pct)))
        _run("brightnessctl", "-q", "set", f"{pct}%")
        return pct


class Adjust:
    """Changes one of them, remembering where it was before the first
    change, so restore() can put it back."""

    def __init__(self, ctl):
        self.ctl = ctl
        self.before = None
        self.now = None

    def change(self, delta):
        """New value in %, or None when it can't be changed here."""
        if not self.ctl.available():
            return None
        cur = self.now if self.now is not None else self.ctl.get()
        if cur is None:
            return None
        if self.before is None:
            self.before = cur
        self.now = self.ctl.set(cur + delta)
        return self.now

    def restore(self):
        """Back to how it was; True when there was something to put back."""
        if self.before is None:
            return False
        before, self.before, self.now = self.before, None, None
        self.ctl.set(before)
        log.info("%s back to %s%%", self.ctl.name, before)
        return True
