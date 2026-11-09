"""The player window: tabs, the controls, the vim status line, fullscreen
and theater modes, and the vim key engine: keymap.py's binds through
Vyom's keys.py (counts, sequences, the Space leader), plus visual mode,
registers, : and /. Laid out like nāda's, so the two feel like one app."""
import logging
import os
import re
import urllib.request

from gi.repository import Gdk, Gio, GLib, Gtk

from . import auth, config, keymap, keys, library, youtube
from .finder import Finder
from .leader import KeySheet, Palette, WhichKey
from .search import SearchPanel
from .util import fmt_time, track_name
from .views import Downloads, History, Library, Queue, Watch, YouTube
from .widgets import G, box, hint, label

# Every key is in keymap.py (data on Vyom's keys.py); its `# keybind:`
# lines are generated there. This file runs them.

log = logging.getLogger("drishya.window")

TABS = keymap.TABS
KEYNAMES = {"space": " ", "period": ".", "comma": ",", "greater": ">", "less": "<", "equal": "=", "plus": "+",
            "minus": "-", "slash": "/", "colon": ":", "question": "?", "KP_Enter": "Return", "Up": "k", "Down": "j",
            "KP_Add": "+", "KP_Subtract": "-", "bracketleft": "[", "bracketright": "]", "braceleft": "{",
            "braceright": "}", "numbersign": "#", "Left": "h", "Right": "l", "backslash": "\\"}
def login_reason(why):
    """The server's refusal in plain words (the raw error only when it's
    something else)."""
    w = why.lower()
    if "401" in w or "unauthorized" in w:
        return "the server asks for a username and password."
    if "403" in w or "forbidden" in w:
        return "the server refused it (403). It may need a login, or the link may have expired."
    why = re.sub(r"^(ERROR: )?(\[[^\]]+\] )?[^:]{0,40}: ", "", why)
    return re.sub(r"\s*\(caused by .*\)$", "", why)[:160]


class Window(Gtk.ApplicationWindow):
    def __init__(self, app, core):
        super().__init__(application=app, title="drishya")
        self.app, self.core = app, core
        self.add_css_class("drishya")
        self.set_default_size(1280, 760)
        self.register = []
        self.m = keys.Machine()   # a count and a pending sequence between keys
        self.mode = "NORMAL"
        self.notes_shown = set()
        self.confirm_cb = None
        self.tab = "watch"
        self.thumbs, self.thumb_wait = {}, set()
        self.thumb_timer = self.toast_timer = self.sleep_timer = None
        self.fullscreened = False
        self.theater = False

        overlay = Gtk.Overlay()
        self.set_child(overlay)
        self.root = box(vertical=True, cls="drishya-root", focusable=True)
        overlay.set_child(self.root)

        # top bar
        self.tabbtn = {}
        self.top = box(spacing=4, cls="topbar")
        self.top.append(box(label(G["eye"], "glyph", ellipsize=False), label("drishya", ellipsize=False), spacing=7,
                            cls="logo", margin_end=8))
        self.views = {}
        for i, cls in enumerate([Watch, Queue, Library, History, Downloads, YouTube]):
            v = cls(self)
            self.views[v.name] = v
            if v.name not in TABS:
                continue
            b = Gtk.Button()
            b.add_css_class("tab")
            # Just the name: digits are counts now (5j). H / L step through the
            # tabs, Space t picks one; the tooltip says which keys.
            b.set_child(label(v.title, ellipsize=False))
            b.set_tooltip_text(f"{v.title}: H / L step through the tabs, Ctrl+{i} jumps here")
            b.set_focusable(False)
            b.connect("clicked", lambda _b, n=v.name: self.switch(n))
            self.tabbtn[v.name] = b
            self.top.append(b)
        self.summary = label("", "mono dim", ellipsize=False, hexpand=True, xalign=1)
        self.modelab = label("NORMAL", "mode", ellipsize=False)
        self.top.append(self.summary)
        self.top.append(self.modelab)
        self.root.append(self.top)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120,
                               hexpand=True, vexpand=True)
        for name, v in self.views.items():
            self.stack.add_named(v.widget, name)
        self.root.append(self.stack)
        self.bar = self._controls()
        self.root.append(self.bar)

        self.cmdline = Gtk.Text(hexpand=True)
        self.cmdline.add_css_class("cmdline")
        self.cmdline.connect("activate", self._cmd_activate)
        self.prefix = label("", "cmdline", ellipsize=False)
        self.msg = label("", "cmdline", hexpand=True)
        self.hints = box(spacing=14)
        self.status = box(self.prefix, self.cmdline, self.msg, self.hints, spacing=2, cls="status")
        self.root.append(self.status)
        self.cmdline.set_visible(False)

        self.toast_lab = label("", wrap=True, max_width_chars=90)
        self.toast_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.CROSSFADE, halign=Gtk.Align.CENTER,
                                      valign=Gtk.Align.END, can_target=False)
        self.toast_rev.set_child(box(self.toast_lab, cls="toast"))
        overlay.add_overlay(self.toast_rev)
        self.help = KeySheet(keymap.COMMANDS)
        overlay.add_overlay(self.help)
        # the leader: what can come next, and every action (Space Space)
        self.which = WhichKey()
        overlay.add_overlay(self.which)
        self.palette = Palette(lambda b: self.run(b.action, 1, False))
        overlay.add_overlay(self.palette)
        self.menu = self._settings_menu()
        self.menu.set_visible(False)
        overlay.add_overlay(self.menu)
        # the search panel (/), over a dimmed window
        self.finder = Finder(self)
        self.scrim = Gtk.Box(hexpand=True, vexpand=True, visible=False, css_classes=["scrim"])
        g = Gtk.GestureClick()
        g.connect("pressed", lambda *_: self.close_search())
        self.scrim.add_controller(g)
        overlay.add_overlay(self.scrim)
        self.search = SearchPanel(self, self.finder, config.STATE,
                                  "Search YouTube and your videos, or paste a link…")
        self.search.set_margin_top(64)
        self.search.set_visible(False)
        overlay.add_overlay(self.search)
        # toasts above everything, the search panel included
        overlay.remove_overlay(self.toast_rev)
        overlay.add_overlay(self.toast_rev)
        GLib.timeout_add_seconds(2, lambda: (self.finder.refresh_index(), False)[1])
        self.login = self._login_panel()
        self.login.set_visible(False)
        overlay.add_overlay(self.login)
        self.login_req = None

        ctl = Gtk.EventControllerKey()
        ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        ctl.connect("key-pressed", self._key)
        self.add_controller(ctl)
        self.connect("close-request", lambda *_: (self.hide_window(), True)[1])
        self.connect("notify::fullscreened", lambda *_: self._fullscreen_changed())

        core.listen(self._core_event)
        for v in self.views.values():
            v.refresh(None)
        self._update_controls()
        self.switch("watch")
        GLib.timeout_add(250, self._tick)

    # ------------------------------------------------------------ building
    def _btn(self, glyph, tip, cb, big=False):
        b = Gtk.Button(tooltip_text=tip, valign=Gtk.Align.CENTER)
        b.set_child(label(glyph, ellipsize=False, xalign=0.5))
        b.add_css_class("ctl")
        if big:
            b.add_css_class("big")
        b.set_focusable(False)
        b.connect("clicked", lambda *_: cb())
        return b

    def _controls(self):
        c = self.core
        step = lambda: c.conf["seek_step"]
        self.pp = self._btn(G["play"], "Play / pause  (p)", c.toggle, big=True)
        ctl = box(self._btn(G["prev"], "Previous video  (<)", c.prev),
                  self._btn(G["back"], "Back 10 seconds  (,)", lambda: c.seek(-step())),
                  self.pp,
                  self._btn(G["fwd"], "Forward 10 seconds  (.)", lambda: c.seek(step())),
                  self._btn(G["next"], "Next video  (>)", c.next), spacing=2)
        self.tcur = label("0:00", "time", ellipsize=False)
        self.tlen = label("0:00", "time", ellipsize=False)
        self.progress = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.progress.set_draw_value(False)
        self.progress.set_hexpand(True)
        self.progress.add_css_class("progress")
        self.progress.set_focusable(False)
        self.progress.connect("change-value", lambda _s, _t, v: (c.seek_to(v), False)[1])
        self.cc = self._btn("CC", "Subtitles  (c)", c.cycle_subs)
        self.qbtn = self._btn("", "Settings: quality, speed, subtitles  (Q)", self.open_settings)
        self.qbtn.add_css_class("qbtn")
        self.dlbtn = self._btn(G["dl"], "Download this video  (D)", lambda: c.current and c.download(c.current))
        openbtn = self._btn(G["folder"], "Open a link or file  (o)", self.open_link)
        self.speedlab = label("", "time", ellipsize=False)
        self.theaterbtn = self._btn(G["theater"], "Theater mode  (t)", self.toggle_theater)
        self.fullbtn = self._btn(G["full"], "Fullscreen  (f)", self.toggle_fullscreen)
        pip = self._btn(G["pip"], "Mini player  (z)", self.app.show_mini)
        self.volglyph = self._btn(G["vol"], "Mute  (m)", c.mute)
        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
        self.vol.set_draw_value(False)
        self.vol.set_size_request(80, -1)
        self.vol.add_css_class("volume")
        self.vol.set_focusable(False)
        self.vol.connect("change-value", lambda _s, _t, v: (c.set_volume(v), False)[1])
        self.volv = label("", "time", ellipsize=False)
        self.volv.set_size_request(26, -1)
        side = box(self.speedlab, openbtn, self.dlbtn, self.qbtn, self.cc, self.theaterbtn, pip, self.fullbtn,
                   self.volglyph, self.vol, self.volv, spacing=4)
        return box(ctl, box(self.tcur, self.progress, self.tlen, spacing=10, hexpand=True, margin_start=10,
                            margin_end=10), side, cls="bar", spacing=8)

    def _settings_menu(self):
        self.menu_title = label("Settings", "menu-title")
        self.menu_list = box(vertical=True, spacing=2)
        self.menu_note = label("", "dim menu-note", wrap=True, max_width_chars=34)
        self.menu_page, self.menu_items, self.menu_sel = "root", [], 0
        foot = box(hint("j k", "move"), hint("l Enter", "choose"), hint("h", "back"), hint("Esc", "close"), spacing=12,
                   cls="menu-foot")
        return box(self.menu_title, self.menu_note, self.menu_list, foot, vertical=True, spacing=6, cls="menu",
                   valign=Gtk.Align.END, halign=Gtk.Align.END, margin_end=24, margin_bottom=96)

    def open_settings(self):
        if self.core.current is None:
            self.toast("Nothing playing · :quality 720 sets the quality for what plays next")
            return
        self.menu.set_visible(True)
        self.set_mode("SETTINGS")
        self._menu_root()

    def _menu_root(self, sel=0):
        c = self.core
        h = c.current_height()
        sub = next((t for t in c.tracks if t.get("type") == "sub" and t.get("selected")), None)
        aud = [t for t in c.tracks if t.get("type") == "audio"]
        cur_aud = next((t for t in aud if t.get("selected")), None)
        items = [("Quality", f"{h}p · up to {c.quality}p" if h else f"up to {c.quality}p", self._menu_quality),
                 ("Speed", f"{c.speed:g}×", self._menu_speed),
                 ("Subtitles", track_name(sub) if sub else ("off" if any(t.get("type") == "sub" for t in c.tracks) else "none"),
                  self._menu_subs)]
        if len(aud) > 1:
            items.append(("Audio", track_name(cur_aud) if cur_aud else "", self._menu_audio))
        if c.current and (c.current.get("yt") or c.current.get("url")) and not c.current.get("live") \
                and not c.downloaded(c.current):
            items.append((f"Download at {c.quality}p", "D", lambda: (self._menu_close(), c.download(c.current))))
        self._menu_show("root", "Settings", "", items, sel)

    def _menu_show(self, page, title, note, items, sel=0):
        """items: [(name, value, action)]: action() opens a page or does it."""
        self.menu_page, self.menu_items = page, items
        self.menu_title.set_text(title)
        self.menu_note.set_text(note)
        self.menu_note.set_visible(bool(note))
        child = self.menu_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.menu_list.remove(child)
            child = nxt
        for i, (name, value, _act) in enumerate(items):
            row = box(label(name, "menu-name", hexpand=True), label(value, "menu-value", ellipsize=False),
                      label("›" if page == "root" and not name.startswith("Download") else "", "menu-more", ellipsize=False),
                      spacing=10, cls="menu-row")
            g = Gtk.GestureClick()
            g.connect("pressed", lambda *_a, i=i: (setattr(self, "menu_sel", i), self._menu_choose()))
            row.add_controller(g)
            self.menu_list.append(row)
        self.menu_sel = max(0, min(sel, len(items) - 1))
        self._menu_paint()

    def _menu_paint(self):
        i, child = 0, self.menu_list.get_first_child()
        while child:
            (child.add_css_class if i == self.menu_sel else child.remove_css_class)("sel")
            i += 1
            child = child.get_next_sibling()

    def _menu_choose(self):
        if 0 <= self.menu_sel < len(self.menu_items):
            self.menu_items[self.menu_sel][2]()

    def _menu_close(self):
        self.menu.set_visible(False)
        self.root.grab_focus()
        self.set_mode("NORMAL")

    def _menu_back(self):
        if self.menu_page == "root":
            self._menu_close()
        else:
            self._menu_root(["quality", "speed", "subs", "audio"].index(self.menu_page)
                            if self.menu_page in ("quality", "speed", "subs", "audio") else 0)

    def _menu_quality(self):
        c = self.core
        self._menu_show("quality", "Quality", "Asking YouTube which qualities it has…", [])

        def got(kind, heights):
            if not self.menu.get_visible() or self.menu_page != "quality":
                return
            now = c.current_height()
            notes = {"youtube": "Reopens the video at the same second. Kept for the next videos and downloads.",
                     "stream": "This stream's qualities: switching is instant.",
                     "file": "A file plays at its own quality. Your pick is for YouTube, streams and downloads."}
            if kind in ("file", "none") or not heights:
                self._menu_show("quality", "Quality", notes.get(kind, ""),
                                [(f"{now}p" if now else "This file", "playing", self._menu_back)])
                return
            items = []
            for h in heights:
                name = {4320: "8K", 2160: "4K", 1440: "1440p"}.get(h, f"{h}p" + (" HD" if h >= 720 else ""))
                tags = " · ".join(t for t in ("playing" if h == now else "", "your pick" if h == c.quality else "") if t)
                items.append((name, tags, lambda h=h: (self._menu_close(), c.set_quality(h))))
            sel = next((i for i, h in enumerate(heights) if h == now), next((i for i, h in enumerate(heights)
                                                                            if h <= c.quality), 0))
            self._menu_show("quality", "Quality", notes.get(kind, ""), items, sel)
        c.qualities(got)

    def _menu_speed(self):
        c = self.core
        speeds = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
        items = [(f"{s:g}×" + (" normal" if s == 1 else ""), "playing" if abs(c.speed - s) < 0.01 else "",
                  lambda s=s: (self._menu_close(), c.set_speed(s))) for s in speeds]
        self._menu_show("speed", "Speed", "[ and ] change it from anywhere; \\ resets", items,
                        min(range(len(speeds)), key=lambda i: abs(speeds[i] - c.speed)))

    def _menu_subs(self):
        c = self.core
        subs = [t for t in c.tracks if t.get("type") == "sub"]
        cur = next((t for t in subs if t.get("selected")), None)

        def pick(t):
            self._menu_close()
            if t is None:
                c.player.set("sid", "no")
                self.toast("Subtitles off")
            else:
                c.player.set("sid", str(t["id"]))
                c.player.set("sub-visibility", True)
                self.toast(f"Subtitles: {track_name(t)}")
        items = [("Off", "" if cur else "playing", lambda: pick(None))]
        items += [(track_name(t), "playing" if t is cur else "", lambda t=t: pick(t)) for t in subs]
        self._menu_show("subs", "Subtitles", "" if subs else "This video has no subtitles in your languages "
                                                            "(subtitles in config.toml)", items,
                        (subs.index(cur) + 1) if cur in subs else 0)

    def _menu_audio(self):
        c = self.core
        auds = [t for t in c.tracks if t.get("type") == "audio"]

        def pick(t):
            self._menu_close()
            c.player.set("aid", str(t["id"]))
            self.toast(f"Audio: {track_name(t)}")
        items = [(track_name(t), "playing" if t.get("selected") else "", lambda t=t: pick(t)) for t in auds]
        self._menu_show("audio", "Audio track", "", items, next((i for i, t in enumerate(auds) if t.get("selected")), 0))

    def _menu_key(self, name):
        if name in ("Escape", "Q", "q"):
            self._menu_close()
        elif name in ("j", "Down"):
            self.menu_sel = min(len(self.menu_items) - 1, self.menu_sel + 1)
            self._menu_paint()
        elif name in ("k", "Up"):
            self.menu_sel = max(0, self.menu_sel - 1)
            self._menu_paint()
        elif name in ("l", "Return", "KP_Enter", "Right"):
            self._menu_choose()
        elif name in ("h", "BackSpace", "Left"):
            self._menu_back()
        return True


    def open_link(self):
        if self.fullscreened:
            self.unfullscreen()
        self._cmd_open(":")
        self.cmdline.set_text("open ")
        self.cmdline.set_position(-1)
        self.msg.set_text("")
        self.toast("A file path, a YouTube link, or any video link (HLS .m3u8, a file on a server, a site yt-dlp knows)")

    def _login_panel(self):
        self.login_title = label("", "signin-title", wrap=True, max_width_chars=60)
        self.login_why = label("", "signin-why", wrap=True, max_width_chars=60)
        self.login_user = Gtk.Entry(placeholder_text="Username", hexpand=True)
        self.login_pass = Gtk.PasswordEntry(placeholder_text="Password", show_peek_icon=True, hexpand=True)
        self.login_pass.connect("activate", lambda *_: self._login_submit())
        self.login_user.connect("activate", lambda *_: self.login_pass.grab_focus())
        self.login_keep = Gtk.CheckButton(label="Remember in my keyring", active=False)
        self.login_keep.set_focusable(False)
        self.login_hints = box(hint("Enter", "sign in"), hint("Tab", "next field"), hint("Ctrl+s", "remember"),
                               hint("Esc", "cancel"), spacing=14)
        self.login_browser = hint("Ctrl+b", "use my browser's login")
        self.login_hints.append(self.login_browser)
        return box(box(label(G["lock"], "glyph signin-glyph", ellipsize=False), self.login_title, spacing=10),
                   self.login_why, self.login_user, self.login_pass, self.login_keep, self.login_hints,
                   vertical=True, spacing=10, cls="signin", valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)

    def ask_login(self, req):
        """The server wants a login: the panel, with what we know."""
        self.login_req = req
        host = req["host"].split("://")[-1]
        site = req["kind"] == "site"
        self.login_title.set_text(f"Sign in to {host}" + (" (that login didn't work)" if req.get("tried") else ""))
        self.login_why.set_text(f"“{req['title'][:70]}”: {login_reason(req['why'])}"
                                + ("\nOr use your browser's login (its cookies): Ctrl+b." if site else ""))
        self.login_browser.set_visible(site)
        self.login_keep.set_sensitive(auth.keyring_available())
        self.login_user.set_text("")
        self.login_pass.set_text("")
        self.login.set_visible(True)
        if self.fullscreened:
            self.unfullscreen()
        self.show_window()
        self.set_mode("LOGIN")
        self.login_user.grab_focus()

    def _login_submit(self, browser=False):
        req = self.login_req
        if req is None:
            return
        user, pw = self.login_user.get_text(), self.login_pass.get_text()
        if not browser and not user and not pw:
            self.login_user.grab_focus()
            return
        self._login_close()
        self.login_pass.set_text("")   # never kept in the widget
        if browser:
            b = auth.default_browser()
            self.core.sign_in(req["host"], cookies=b)
            self.toast(f"Signing in with your {b} login…")
        else:
            self.core.sign_in(req["host"], user, pw, remember=self.login_keep.get_active())
            self.toast("Signing in…")

    def _login_close(self):
        self.login.set_visible(False)
        self.login_req = None
        self.root.grab_focus()
        self.set_mode("NORMAL")

    # ------------------------------------------------------------ tabs and modes
    def switch(self, name):
        if name not in self.views:
            return
        cur = self.views.get(self.tab)
        if cur and cur.list() is not None and cur.list().vstart is not None:
            cur.list().visual(False)
        if self.fullscreened and name != "watch":
            self.unfullscreen()
        self.tab = name
        self.stack.set_visible_child_name(name)
        # On Watch the controls are over the video; elsewhere, the bar below
        self.bar.set_visible(name != "watch" and not self.fullscreened)
        if name == "watch":
            self.views["watch"].poke()
        for n, b in self.tabbtn.items():
            (b.add_css_class if n == name else b.remove_css_class)("on")
        self.views[name].shown()
        self.drop_pending()
        self.set_mode("NORMAL")
        self._hints()
        if self.cmdline.get_visible():
            self._cmd_close()

    def drop_pending(self):
        """Another tab (or the window hidden): what was waiting goes. A key
        sequence or count, an unanswered question (else a y on the new tab
        would answer it), the palette and key sheet of the old tab."""
        self.m.reset()
        self.which.cancel()
        self.confirm_cb = None
        self._show_pending()
        self.palette.close()
        self.help.set_visible(False)

    def toggle_fullscreen(self):
        if self.fullscreened:
            self.unfullscreen()
        else:
            if self.tab != "watch":
                self.switch("watch")
            self.fullscreen()

    def _fullscreen_changed(self):
        self.fullscreened = bool(self.is_fullscreen())
        on = self.fullscreened
        for w in (self.top, self.status):
            w.set_visible(not on)
        self.bar.set_visible(not on and self.tab != "watch")
        (self.root.add_css_class if on else self.root.remove_css_class)("full")
        self.fullbtn.get_child().set_text(G["unfull"] if on else G["full"])
        self.views["watch"].enter_zen(on)   # fullscreen is zen: the video, nothing over it

    def toggle_theater(self):
        self.theater = not self.theater
        if self.tab != "watch":
            self.switch("watch")
        self.views["watch"].set_theater(self.theater or self.fullscreened)
        (self.theaterbtn.add_css_class if self.theater else self.theaterbtn.remove_css_class)("on")

    def set_mode(self, mode):
        log.debug("mode %s", mode)
        self.mode = mode
        self.modelab.set_text(mode)
        for m in ("visual", "search", "command", "confirm", "login", "settings"):
            (self.modelab.add_css_class if mode.lower() == m else self.modelab.remove_css_class)(m)

    def _hints(self):
        child = self.hints.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.hints.remove(child)
            child = nxt
        for k, w in self.views[self.tab].hints + [("?", "all keys")]:
            self.hints.append(hint(k, w))

    def _show_pending(self):
        self.msg.set_text(self.m.typed())

    def toast(self, text):
        if not text:
            return
        if self.fullscreened:
            self.views["watch"].zen_note(text, 2.2)   # zen: a small line in the corner
            return
        self.toast_lab.set_text(text)
        self.toast_rev.set_reveal_child(True)
        if self.toast_timer:
            GLib.source_remove(self.toast_timer)
        self.toast_timer = GLib.timeout_add(2600, self._toast_hide)

    def feedback(self, text):
        """After a seek or a volume change: on Watch the controls show it
        (in zen, a small readout); elsewhere a toast."""
        if self.tab == "watch":
            w = self.views["watch"]
            if self.fullscreened:
                c = self.core
                w.zen_note(f"{text}   {fmt_time(c.pos)} / {fmt_time(c.duration)}" if c.duration else text)
            else:
                w.poke()
        else:
            self.toast(text)

    # ------------------------------------------------------------ search panel (/)
    def open_search(self, text="", scope=0):
        if self.menu.get_visible():
            self._menu_close()
        self.finder.refresh_index()
        self.scrim.set_visible(True)
        self.search.open(text, scope)
        self.set_mode("SEARCH")

    def close_search(self):
        self.search.close()
        self.scrim.set_visible(False)
        self.root.grab_focus()
        self.set_mode("NORMAL")

    def _toast_hide(self):
        self.toast_rev.set_reveal_child(False)
        self.toast_timer = None
        return False

    def confirm(self, question, cb):
        self.confirm_cb = cb
        self.set_mode("CONFIRM")
        self.msg.set_text(f"{question}  y yes · any other key no")

    # ------------------------------------------------------------ core events
    def _core_event(self, e):
        if isinstance(e, tuple):
            if e[0] == "toast":
                self.toast(e[1])
            elif e[0] == "login":
                self.ask_login(e[1])
            return
        for v in self.views.values():
            v.refresh(e)
        if e in ("player", "video", "queue", "tracks", "options"):
            self._update_controls()
        if e == "video":
            cur = self.core.current
            self.set_title(f"{cur['title']} · drishya" if cur else "drishya")

    def _update_controls(self):
        c = self.core
        self.pp.get_child().set_text(G["play"] if c.paused or c.idle else G["pause"])
        v = c.volume
        self.vol.set_value(v)
        self.volv.set_text(f"{v:.0f}")
        self.volglyph.get_child().set_text(G["mute"] if c.muted or v == 0 else G["vol"])
        self.speedlab.set_text(f"{c.speed:g}×" if c.speed != 1 else "")
        h = c.current_height()
        self.qbtn.get_child().set_text(f"{h}p" if h else f"≤{c.quality}p")
        self.qbtn.set_tooltip_text(f"Quality: playing {h}p, your pick up to {c.quality}p  (Q)" if h
                                   else f"Quality: up to {c.quality}p  (Q)")
        self.dlbtn.set_sensitive(bool(c.current and (c.current.get("yt") or c.current.get("url"))
                                      and not c.current.get("live")))
        has_subs = any(t.get("type") == "sub" for t in c.tracks)
        sub_on = any(t.get("type") == "sub" and t.get("selected") for t in c.tracks)
        self.cc.set_sensitive(has_subs)
        (self.cc.add_css_class if sub_on else self.cc.remove_css_class)("on")
        mine = [x for x in c.queue[max(c.cur, 0):] if not x.get("auto")]
        left = sum(x.get("duration") or 0 for x in mine) - (c.pos if c.current else 0)
        self.summary.set_text(f"{len(mine)} to watch · {fmt_time(left)}" if mine and left > 0 else "")
        d = c.duration
        self.progress.set_range(0, max(1, d))
        self.tlen.set_text(fmt_time(d) if d else "–:––")
        self._tick()

    def _tick(self):
        c = self.core
        if not self.get_visible():
            return True
        t = c.pos if c.current else 0
        self.progress.set_value(t)
        self.tcur.set_text(fmt_time(t))
        self.views["watch"].tick(t)
        return True

    # ------------------------------------------------------------ thumbnails
    def thumb(self, it):
        """A cached thumbnail path for a video, or None (and fetch it)."""
        if it.get("yt"):
            key = "yt:" + it["yt"]
        elif it.get("file"):
            key = "file:" + it["file"]
        else:
            return None
        if key in self.thumbs:
            return self.thumbs[key]
        if key not in self.thumb_wait:
            self.thumb_wait.add(key)
            cache = os.path.join(config.CACHE, "thumbs")

            snap = dict(it)   # the item as it is now (the queue may change meanwhile)

            def work(it=snap):
                if it.get("yt"):
                    path = os.path.join(cache, it["yt"] + ".jpg")
                    if not os.path.exists(path):
                        url = it.get("thumb") or youtube.thumb(it["yt"])
                        req = urllib.request.Request(url, headers={"User-Agent": "drishya"})
                        with urllib.request.urlopen(req, timeout=15) as r, open(path + ".part", "wb") as f:
                            f.write(r.read())
                        os.replace(path + ".part", path)
                    return path
                return library.thumbnail(it["file"], cache, it.get("duration") or 0)

            def done(path, key=key):
                self.thumbs[key] = path
                self.thumb_wait.discard(key)
                if path and not self.thumb_timer:
                    self.thumb_timer = GLib.timeout_add(300, self._thumbs_ready)
            self.app.thumb_pool.submit(work).add_done_callback(
                lambda f: GLib.idle_add(lambda: (done(f.result() if not f.exception() else None), False)[1]))
        return None

    def _thumbs_ready(self):
        self.thumb_timer = None
        self.core.emit("thumbs")
        self.search.refresh_thumbs()
        return False

    # ------------------------------------------------------------ visibility
    def show_window(self):
        self.set_visible(True)
        self.present()
        self.root.grab_focus()
        self.core.window_visible = True
        GLib.idle_add(lambda: (self.views["watch"].area.attach(), False)[1])
        self._tick()

    def hide_window(self):
        self.drop_pending()
        if self.fullscreened:
            self.unfullscreen()
        self.set_visible(False)
        self.core.window_visible = False
        if not (self.app.mini and self.app.mini.get_visible()):
            self.core.restore_system()   # volume and brightness as they were before
            if self.core.conf["pause_on_hide"]:
                self.core.pause()

    def adjust(self, what, delta):
        """The system volume or the screen's brightness (put back when the
        window closes)."""
        c = self.core
        a = c.sys_volume if what == "volume" else c.sys_brightness
        v = a.change(delta)
        if v is None:
            self.toast(f"Can't change the {what} here (needs {'pactl' if what == 'volume' else 'brightnessctl'})")
            return
        glyph = G["vol"] if what == "volume" else G["sun"]
        self.feedback(f"{glyph} {v}%")

    # ------------------------------------------------------------ keys
    def _key(self, ctrl, keyval, code, state):
        name = Gdk.keyval_name(keyval) or ""
        log.debug("key %s state %s", name, int(state))
        ctrl_on = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl_on and name in ("Tab", "ISO_Left_Tab"):
            back = name == "ISO_Left_Tab" or bool(state & Gdk.ModifierType.SHIFT_MASK)
            self.step_tab(-1 if back else 1)
            return True
        if ctrl_on and re.fullmatch(r"[0-4]", name):
            self.switch(TABS[int(name)])
            return True
        if self.palette.get_visible():
            return self.palette.key(name, ctrl_on)
        if self.search.get_visible():
            return self.search.key(name, state)
        if self.menu.get_visible():
            return self._menu_key(name)
        if self.login.get_visible():
            if name == "Escape":
                self._login_close()
                self.toast("Not signed in")
                return True
            if ctrl_on and name == "b" and self.login_browser.get_visible():
                self._login_submit(browser=True)
                return True
            if ctrl_on and name == "s":
                self.login_keep.set_active(not self.login_keep.get_active())
                return True
            return False   # typing goes to the fields
        focus = self.get_focus()
        yt_entry = self.views["youtube"].entry
        if self.cmdline.get_visible() and (focus is self.cmdline or (focus is not None and focus.is_ancestor(self.cmdline))):
            if name == "Escape" or (name == "BackSpace" and not self.cmdline.get_text()):
                self._cmd_close()
                return True
            return False
        if focus is yt_entry or (focus is not None and focus.is_ancestor(yt_entry)):
            if name in ("Escape", "Down", "Tab"):
                self.root.grab_focus()
                self.set_mode("NORMAL")
                return True
            return False
        if self.confirm_cb:
            if keys.is_modifier(name):
                return True
            cb, self.confirm_cb = self.confirm_cb, None
            self.set_mode("NORMAL")
            self.msg.set_text("")
            if name == "y":
                cb()
            else:
                self.toast("Cancelled")
            return True
        if self.help.get_visible():
            return self.help.key(name)
        if keys.is_modifier(name):
            return False
        mods = {m for m, mask in (("ctrl", Gdk.ModifierType.CONTROL_MASK), ("shift", Gdk.ModifierType.SHIFT_MASK),
                                  ("alt", Gdk.ModifierType.ALT_MASK)) if state & mask}
        tok = keys.token(name, mods)
        if tok is None:
            return False
        # the old engine's name for the key: what dispatch() and the views know
        legacy = KEYNAMES.get(name, name)
        if ctrl_on:
            legacy = "C-" + legacy.lower()
        if self.tab == "watch" and not self.fullscreened:
            self.views["watch"].poke()   # a key shows the controls (zen shows nothing)
        if self.fullscreened and tok == " " and not self.m.busy():
            self.dispatch(" ")           # zen: Space plays and pauses, no leader
            return True
        km = self.keymap_now()
        had_count = bool(self.m.count)
        if tok == "<" and not self.m.pending:
            # keys.py reads "<" as the start of <CR>, <C-d>… and would wait:
            # run it at once (with its count)
            n = int(self.m.count or 1)
            self.m.reset()
            self._show_pending()
            self.which.cancel()
            self.run(km.table["<"].action, n, had_count)
            return True
        r = self.m.feed(km, tok)
        self._show_pending()
        if r.kind == "pending":
            if self.m.pending:
                self.which.schedule(km, self.m.pending)
            return True
        self.which.cancel()
        if r.kind == "cancel":
            return True
        if r.kind == "unknown":
            if len(keys.tokens(r.seq)) == 1:
                self.dispatch(legacy, r.count, had_count)   # a key the views know that the keymap doesn't list
            else:
                self.toast(f"{keys.spell(r.seq)} isn't a key here · Space ? shows them")
            return True
        self.run(r.bind.action, r.count, had_count)
        return True

    def keymap_now(self):
        lst = self.views[self.tab].list()
        visual = lst is not None and lst.vstart is not None
        return keys.Keymap(keymap.binds_for(self.tab, visual), keymap.GROUPS)

    def run(self, action, n=1, had_count=False):
        """Run a keymap action (see keymap.py): do:, tab:, call:, moved:."""
        if not isinstance(action, str):
            return
        action, _, note = action.partition("|note:")
        kind, _, arg = action.partition(":")
        if kind == "do":
            self.dispatch(arg, n, had_count)
        elif kind == "tab":
            if arg in ("+1", "-1"):
                self.step_tab(int(arg) * n)
            else:
                self.switch(arg)
        elif kind == "call":
            meth, _, extra = arg.partition(":")
            getattr(self, "k_" + meth)(*([extra] if extra else []))
        elif kind == "moved":
            self.toast(f"That key moved: it's {arg} now")
        if note and note not in self.notes_shown:
            self.notes_shown.add(note)
            self.toast(note)

    def step_tab(self, d):
        i = TABS.index(self.tab) if self.tab in TABS else 0
        self.switch(TABS[(i + d) % len(TABS)])

    # keymap actions (call:<name> runs k_<name>)
    def k_toggle_play(self):
        self.core.toggle()

    def k_palette(self):
        km = self.keymap_now()
        rows = [r for r in keys.palette_rows(km)
                if isinstance(r[2].action, str) and not r[2].action.startswith(("moved:", "call:palette"))]
        if self.fullscreened:
            self.unfullscreen()
        self.palette.open(rows)

    def k_keysheet(self):
        extra = [(f"{scope} (its own keys)", [(keys.spell(b.seq), b.desc) for b in bs])
                 for scope, _mode, bs in keymap.PANELS if scope != "leader"]
        if self.fullscreened:
            self.unfullscreen()
        self.help.open(self.keymap_now(), keymap.where(self.tab), extra)

    def k_mini(self):
        self.app.show_mini()

    def k_sleep(self):
        self.sleep("off" if self.sleep_timer else "30m")

    def _where(self, cur):
        """The video's link (never with a user:password@ in it) or file."""
        if cur.get("yt"):
            return youtube.watch_url(cur["yt"])
        if cur.get("url"):
            return auth.split_userinfo(cur["url"])[0]
        return cur.get("file") or ""

    def _copy(self, text, what):
        self.get_clipboard().set(text)
        self.toast(f"Copied {what}")

    def k_copy_title(self):
        cur = self.core.current
        if cur:
            self._copy(cur["title"], "the title")
        else:
            self.toast("Nothing playing")

    def k_copy_link(self):
        cur = self.core.current
        if cur:
            self._copy(self._where(cur), "the link" if cur.get("yt") or cur.get("url") else "the file path")
        else:
            self.toast("Nothing playing")

    def k_info(self):
        self.dispatch("i")

    def k_search(self, scope):
        self.open_search("", int(scope))

    def k_goto_playing(self):
        if self.tab != "queue":
            self.switch("queue")
        self.dispatch("zz")

    def k_open_browser(self):
        cur = self.core.current
        url = self._where(cur) if cur else ""
        if not url.startswith(("http://", "https://")):
            self.toast("The playing video has no web page" if cur else "Nothing playing")
            return
        try:
            Gio.AppInfo.launch_default_for_uri(url, None)
        except GLib.Error as e:
            self.toast(f"Couldn't open the browser: {e.message}")

    def k_refresh(self):
        if self.tab == "library":
            self.dispatch("R")
            return
        for v in self.views.values():
            v.refresh(None)
        self.toast("Refreshed")

    def k_clear_queue(self):
        self.confirm("Clear Up next?", lambda: (self.core.clear(), self.toast("Up next cleared · u brings it back")))

    def dispatch(self, k, n=1, had_count=False):
        c = self.core
        view = self.views[self.tab]
        lst = view.list()
        if lst is not None:
            if k == "j":
                lst.move(n)
                return True
            if k == "k":
                lst.move(-n)
                return True
            if k == "gg":
                lst.select(n - 1 if had_count else 0)
                return True
            if k == "G":
                lst.select(n - 1 if had_count else len(lst.items) - 1)
                return True
            if k in ("C-d", "Page_Down"):
                lst.move(lst.page() * n)
                return True
            if k in ("C-u", "Page_Up"):
                lst.move(-lst.page() * n)
                return True
            if k == "V" and self.tab != "watch":
                on = lst.visual()
                self.set_mode("VISUAL" if on else "NORMAL")
                return True
            if k == "Escape" and lst.vstart is not None:
                lst.visual(False)
                self.set_mode("NORMAL")
                return True
        if view.key(k, n):
            return True
        step = c.conf["seek_step"]
        if k == " ":
            c.toggle()
        elif k == "Return":
            c.toggle()
        elif k == ".":
            c.seek(step * n)
            self.feedback(f"{G['fwd']} {step * n} s")
        elif k == ",":
            c.seek(-step * n)
            self.feedback(f"{G['back']} {step * n} s")
        elif k == ">":
            c.next(n)
        elif k == "<":
            c.prev(n)
        elif k in ("=", "+", "-"):
            self.adjust("volume", (-1 if k == "-" else 1) * c.conf["volume_step"] * n)
        elif k in ("C-=", "C-+", "C--"):
            self.adjust("brightness", (-1 if k == "C--" else 1) * 5 * n)
        elif k == "m":
            c.mute()
        elif k == "f":
            self.toggle_fullscreen()
        elif k == "t":
            self.toggle_theater()
        elif k == "c":
            c.cycle_subs()
        elif k == "#":
            c.cycle_audio()
        elif k == "]":
            c.set_speed(c.speed + 0.25 * n)
        elif k == "[":
            c.set_speed(c.speed - 0.25 * n)
        elif k == "\\":
            c.set_speed(1.0)
        elif k == "}":
            c.chapter_step(n)
        elif k == "{":
            c.chapter_step(-n)
        elif k == "S":
            c.start_over()
        elif k == "M":
            c.set_autoplay(not c.autoplay)
        elif k == "u":
            c.undo()
        elif k == "C-r":
            c.redo()
        elif k == "D":
            if c.current:
                c.download(c.current)
        elif k == "i":
            cur = c.current
            if cur and self.fullscreened:
                self.views["watch"].zen_note(f"{cur['title']}   {fmt_time(c.pos)} / {fmt_time(c.duration)}", 3)
            elif cur:
                where = youtube.watch_url(cur["yt"]) if cur.get("yt") else cur.get("url") or cur.get("file")
                self.toast(f"{cur['title']} · {cur.get('channel', '')} · {where}")
        elif k == "/":
            self.open_search()
        elif k in ("n", "N"):
            v = self.views[self.tab]
            if hasattr(v, "next_match"):
                v.next_match(1 if k == "n" else -1)
        elif k == ":":
            self._cmd_open(":")
        elif k == "o":
            self.open_search()
            self.toast("Paste a link (YouTube, HLS, any video URL) or type a file path")
        elif k == "Q":
            self.open_settings()
        elif k == "?":
            self.k_keysheet()
        elif k == "Escape":
            if self.fullscreened:
                self.unfullscreen()
            else:
                self.hide_window()
        elif k == "q":
            self.hide_window()
        else:
            return False
        return True

    # ------------------------------------------------------------ command line
    def _cmd_open(self, prefix):
        if self.fullscreened:
            self.unfullscreen()
        self.prefix.set_text(prefix)
        self.msg.set_text("")
        self.cmdline.set_text("")
        self.cmdline.set_visible(True)
        self.msg.set_visible(False)
        self.cmdline.grab_focus()
        self.set_mode("SEARCH" if prefix == "/" else "COMMAND")

    def _cmd_close(self):
        self.prefix.set_text("")
        self.cmdline.set_visible(False)
        self.msg.set_visible(True)
        self.root.grab_focus()
        self.set_mode("NORMAL")

    def _cmd_activate(self, *_):
        text, prefix = self.cmdline.get_text().strip(), self.prefix.get_text()
        self._cmd_close()
        if prefix == "/":
            self.views[self.tab].search(text)
        elif text:
            self.command(text)

    def command(self, text):
        c = self.core
        cmd, _, arg = text.partition(" ")
        arg = arg.strip()
        if cmd in ("yt", "youtube"):
            if arg:
                self.switch("youtube")
                self.views["youtube"].search(arg)
            else:
                self.switch("youtube")
        elif cmd in ("open", "o", "e"):
            c.add_url(arg, "play")
        elif cmd == "add":
            c.add_url(arg, "end")
        elif cmd == "seek":
            m = re.fullmatch(r"([+-])?(?:(\d+):)?(?:(\d+):)?(\d+)", arg)
            if not m:
                self.toast(":seek 1:30  (or 1:02:03, +30, -30)")
            else:
                parts = [int(x) for x in (m.group(2), m.group(3), m.group(4)) if x is not None]
                secs = 0
                for x in parts:
                    secs = secs * 60 + x
                if m.group(1):
                    c.seek(secs if m.group(1) == "+" else -secs)
                else:
                    c.seek_to(secs)
        elif cmd == "speed":
            try:
                c.set_speed(float(arg or 1))
            except ValueError:
                self.toast(":speed 1.5")
        elif cmd in ("vol", "volume"):
            try:
                c.set_volume(c.volume + int(arg) if arg[:1] in "+-" else int(arg))
            except ValueError:
                self.toast(":vol 80  (or +10 / -10)")
        elif cmd in ("sub", "subs"):
            if arg in ("off", "no", ""):
                c.player and c.player.set("sid", "no")
                self.toast("Subtitles off")
            else:
                subs = [t for t in c.tracks if t.get("type") == "sub" and arg.lower() in
                        ((t.get("lang") or "") + " " + (t.get("title") or "")).lower()]
                if subs and c.player:
                    c.player.set("sid", str(subs[0]["id"]))
                    c.player.set("sub-visibility", True)
                else:
                    self.toast(f"No “{arg}” subtitles for this video")
        elif cmd == "quality":
            try:
                c.set_quality(max(144, min(4320, int(arg.rstrip("p")))))
            except ValueError:
                self.toast(":quality 720")
        elif cmd == "sleep":
            self.sleep(arg)
        elif cmd in ("logout", "signout"):
            cur = c.current
            target = arg or (cur.get("url") if cur else "")
            if not target:
                self.toast(":logout <server>  (or play something from it first)")
            else:
                host = auth.host_of(target if "://" in target else "https://" + target)
                c.forget_login(host)
                self.toast(f"Signed out of {host.split('://')[-1]} (and removed from your keyring)")
        elif cmd in ("shot", "screenshot"):
            c.screenshot()
        elif cmd == "clear":
            c.clear()
            self.toast("Queue cleared · u brings it back")
        elif cmd == "autoplay":
            c.set_autoplay(arg != "off" if arg else not c.autoplay)
        elif cmd in ("dl", "download"):
            if c.current:
                c.download(c.current)
        elif cmd in ("q", "hide"):
            self.hide_window()
        elif cmd in ("qa", "quit"):
            self.app.quit_all()
        elif cmd == "help":
            self.k_keysheet()
        else:
            self.toast(f"Not a command: {cmd} · ? lists them")

    def sleep(self, arg):
        if self.sleep_timer:
            GLib.source_remove(self.sleep_timer)
            self.sleep_timer = None
        if arg in ("off", "cancel", "0"):
            self.toast("Sleep timer off")
            return
        m = re.fullmatch(r"(\d+)\s*([hm]?)", arg or "30m")
        if not m:
            self.toast(":sleep 30m  (or 1h, or off)")
            return
        mins = int(m.group(1)) * (60 if m.group(2) == "h" else 1)
        self.sleep_timer = GLib.timeout_add_seconds(mins * 60, self._sleep_now)
        self.toast(f"Pausing in {mins} min · :sleep off cancels")

    def _sleep_now(self):
        self.sleep_timer = None
        self.core.pause()
        if self.fullscreened:
            self.unfullscreen()
        return False
