"""The mini player (picture-in-picture): a small window with just the
video, for watching while you work. sway floats it in a corner, above
everything (a window rule on its app id)."""
from gi.repository import Gdk, GLib, Gtk

from .util import fmt_time
from .widgets import G, VideoArea, box, label

# keybind: Drishya/mini player | Space | Toggle play / pause
# keybind: Drishya/mini player | . / , | Seek forward / back 10 seconds
# keybind: Drishya/mini player | > / < | Play the next / previous video
# keybind: Drishya/mini player | = / - | Raise / lower the system volume
# keybind: Drishya/mini player | Ctrl+= / Ctrl+- | Raise / lower the screen brightness
# keybind: Drishya/mini player | z / Enter | Switch back to the full player
# keybind: Drishya/mini player | q / Esc | Close the mini player (pauses)


class Mini(Gtk.Window):
    def __init__(self, app, core):
        super().__init__(application=app, title="drishya mini")
        self.app, self.core = app, core
        self.add_css_class("drishya-mini")
        self.set_default_size(480, 270)
        self.area = VideoArea(core, lambda: self.get_visible())
        over = Gtk.Overlay()
        over.set_child(self.area)
        self.title = label("", "osd-title mini-title")
        self.bar = Gtk.ProgressBar(hexpand=True)
        self.bar.add_css_class("osd-bar")
        self.time = label("", "time", ellipsize=False)
        self.osd = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, valign=Gtk.Align.END,
                                can_target=False, reveal_child=True)
        self.osd.set_child(box(self.title, box(self.bar, self.time, spacing=8), vertical=True, spacing=4,
                               cls="osd mini-osd"))
        over.add_overlay(self.osd)
        self.set_child(box(over, cls="mini-root"))
        self.osd_timer = None
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda *_: self.show_osd())
        over.add_controller(motion)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda _g, n, *_: self.app.show_full() if n == 2 else core.toggle())
        over.add_controller(click)
        self.connect("close-request", lambda *_: (self.close_mini(), True)[1])
        self.connect("notify::visible", lambda *_: self._visible())
        GLib.timeout_add(300, self._tick)

    def _visible(self):
        if self.get_visible():
            GLib.idle_add(lambda: (self.area.attach(), False)[1])
            self.show_osd()

    def show_osd(self):
        self.osd.set_reveal_child(True)
        if self.osd_timer:
            GLib.source_remove(self.osd_timer)
        self.osd_timer = GLib.timeout_add(2200, self._hide_osd)

    def _hide_osd(self):
        self.osd_timer = None
        if not self.core.paused:
            self.osd.set_reveal_child(False)
        return False

    def _tick(self):
        if self.get_visible():
            c = self.core
            cur = c.current
            self.title.set_text((G["pause"] + "  " if c.paused else "") + (cur["title"] if cur else "Nothing playing"))
            self.bar.set_fraction(c.pos / c.duration if c.duration else 0)
            self.time.set_text(f"{fmt_time(c.pos)} / {fmt_time(c.duration)}" if c.duration else "")
        return True

    def close_mini(self):
        self.set_visible(False)
        self.area.detach()
        self.core.pause()
        self.core.restore_system()   # volume and brightness as they were before

    def _key(self, _c, keyval, _code, state):
        name = Gdk.keyval_name(keyval) or ""
        c = self.core
        self.show_osd()
        step = c.conf["seek_step"]
        if name == "space":
            c.toggle()
        elif name == "period":
            c.seek(step)
        elif name == "comma":
            c.seek(-step)
        elif name == "greater":
            c.next()
        elif name == "less":
            c.prev()
        elif name in ("equal", "plus", "minus"):
            ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
            a = c.sys_brightness if ctrl else c.sys_volume
            v = a.change((-5 if name == "minus" else 5) if ctrl else (-1 if name == "minus" else 1) * c.conf["volume_step"])
            if v is not None:
                self.title.set_text(f"{G['sun'] if ctrl else G['vol']} {v}%")
        elif name in ("z", "Return"):
            self.app.show_full()
        elif name in ("q", "Escape"):
            self.close_mini()
        else:
            return False
        return True
