"""MPRIS (org.mpris.MediaPlayer2.drishya): media keys through playerctl, the
phone's media controls through KDE Connect, anything else that speaks it."""
from gi.repository import Gio, GLib

from . import youtube

XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/><method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/><method name="Previous"/><method name="Pause"/>
    <method name="PlayPause"/><method name="Stop"/><method name="Play"/>
    <method name="Seek"><arg direction="in" name="Offset" type="x"/></method>
    <method name="SetPosition"><arg direction="in" name="TrackId" type="o"/><arg direction="in" name="Position" type="x"/></method>
    <method name="OpenUri"><arg direction="in" name="Uri" type="s"/></method>
    <signal name="Seeked"><arg name="Position" type="x"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>"""
ROOT, PLAYER = "org.mpris.MediaPlayer2", "org.mpris.MediaPlayer2.Player"
PATH = "/org/mpris/MediaPlayer2"


class MPRIS:
    def __init__(self, core, raise_cb, quit_cb):
        self.core, self.raise_cb, self.quit_cb = core, raise_cb, quit_cb
        self.conn = None
        self.last = {}
        self.node = Gio.DBusNodeInfo.new_for_xml(XML)
        Gio.bus_own_name(Gio.BusType.SESSION, "org.mpris.MediaPlayer2.drishya", Gio.BusNameOwnerFlags.NONE,
                         self._acquired, None, None)
        core.listen(self._changed)

    def _acquired(self, conn, name):
        self.conn = conn
        for iface in self.node.interfaces:
            conn.register_object(PATH, iface, self._call, self._get, self._set)

    # ------------------------------------------------------------ values
    def _metadata(self):
        it = self.core.current
        if not it:
            return {"mpris:trackid": GLib.Variant("o", "/org/mpris/MediaPlayer2/TrackList/NoTrack")}
        url = youtube.watch_url(it["yt"]) if it.get("yt") else it.get("url") or "file://" + it.get("file", "")
        md = {
            "mpris:trackid": GLib.Variant("o", f"/dev/vayu/Drishya/video/{it['id']}"),
            "mpris:length": GLib.Variant("x", int((self.core.duration or 0) * 1e6)),
            "xesam:title": GLib.Variant("s", it.get("title") or ""),
            "xesam:artist": GLib.Variant("as", [a for a in [it.get("channel")] if a]),
            "xesam:url": GLib.Variant("s", url),
        }
        if it.get("thumb", "").startswith("http"):
            md["mpris:artUrl"] = GLib.Variant("s", it["thumb"])
        return md

    def _status(self):
        c = self.core
        if c.current is None or c.idle:
            return "Stopped"
        return "Paused" if c.paused else "Playing"

    def _props(self, iface):
        c = self.core
        if iface == ROOT:
            return {"CanQuit": GLib.Variant("b", True), "CanRaise": GLib.Variant("b", True),
                    "HasTrackList": GLib.Variant("b", False), "Identity": GLib.Variant("s", "drishya"),
                    "DesktopEntry": GLib.Variant("s", "drishya"),
                    "SupportedUriSchemes": GLib.Variant("as", ["file", "http", "https"]),
                    "SupportedMimeTypes": GLib.Variant("as", ["video/mp4", "video/x-matroska", "video/webm"])}
        p = c.cur
        return {"PlaybackStatus": GLib.Variant("s", self._status()), "LoopStatus": GLib.Variant("s", "None"),
                "Rate": GLib.Variant("d", c.speed), "MinimumRate": GLib.Variant("d", 0.25),
                "MaximumRate": GLib.Variant("d", 4.0), "Shuffle": GLib.Variant("b", False),
                "Metadata": GLib.Variant("a{sv}", self._metadata()),
                "Volume": GLib.Variant("d", max(0, c.volume) / 100), "Position": GLib.Variant("x", int(c.pos * 1e6)),
                "CanGoNext": GLib.Variant("b", 0 <= p < len(c.queue) - 1 or c.autoplay),
                "CanGoPrevious": GLib.Variant("b", p > 0 or c.pos > 4),
                "CanPlay": GLib.Variant("b", bool(c.queue)), "CanPause": GLib.Variant("b", bool(c.queue)),
                "CanSeek": GLib.Variant("b", c.current is not None), "CanControl": GLib.Variant("b", True)}

    # ------------------------------------------------------------ D-Bus
    def _get(self, conn, sender, path, iface, prop):
        return self._props(iface).get(prop)

    def _set(self, conn, sender, path, iface, prop, value):
        c, v = self.core, value.unpack()
        if prop == "Volume":
            c.set_volume(v * 100)
        elif prop == "Rate":
            c.set_speed(v)
        return True

    def _call(self, conn, sender, path, iface, method, params, inv):
        c = self.core
        args = params.unpack()
        if method == "Raise":
            self.raise_cb()
        elif method == "Quit":
            self.quit_cb()
        elif method == "PlayPause":
            c.toggle()
        elif method == "Play":
            if c.paused or c.idle:
                c.toggle()
        elif method in ("Pause", "Stop"):
            c.pause()
        elif method == "Next":
            c.next()
        elif method == "Previous":
            c.prev()
        elif method == "Seek":
            c.seek(args[0] / 1e6)
        elif method == "SetPosition":
            c.seek_to(args[1] / 1e6)
        elif method == "OpenUri":
            c.add_url(args[0], "play")
        inv.return_value(None)

    def _changed(self, event):
        if self.conn is None or isinstance(event, tuple):
            return
        if event not in ("player", "video", "options", "queue"):
            return
        props = self._props(PLAYER)
        props.pop("Position")
        changed = {k: v for k, v in props.items() if self.last.get(k) != v.print_(False)}
        self.last.update({k: v.print_(False) for k, v in changed.items()})
        if changed:
            self.conn.emit_signal(None, PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                  GLib.Variant("(sa{sv}as)", (PLAYER, changed, [])))
        if event == "player":
            self.conn.emit_signal(None, PATH, PLAYER, "Seeked", GLib.Variant("(x)", (int(self.core.pos * 1e6),)))
