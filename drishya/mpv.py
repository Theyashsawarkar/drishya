"""A small libmpv binding (ctypes): the client API (commands, properties,
events) and the OpenGL render API, so the video draws inside our GTK
window. Only what drishya needs; no package beyond libmpv itself (the mpv
package ships it).

Threads: libmpv calls the wakeup and update callbacks from its own
threads; they only schedule work on the GTK main loop, where every call
into here happens."""
import ctypes
import ctypes.util
import json
import logging

log = logging.getLogger("drishya.mpv")


class MPVError(Exception):
    pass


def _load(*names):
    for n in names:
        path = ctypes.util.find_library(n) or n
        try:
            return ctypes.CDLL(path)
        except OSError:
            continue
    return None


lib = _load("mpv", "libmpv.so.2", "libmpv.so.1")

# formats, events, end-file reasons (mpv/client.h)
FMT_NONE, FMT_STRING, FMT_FLAG, FMT_INT64, FMT_DOUBLE, FMT_NODE, FMT_ARRAY, FMT_MAP = 0, 1, 3, 4, 5, 6, 7, 8
EV_SHUTDOWN, EV_LOG, EV_START_FILE, EV_END_FILE, EV_FILE_LOADED, EV_IDLE = 1, 2, 6, 7, 8, 11
EV_VIDEO_RECONFIG, EV_SEEK, EV_RESTART, EV_PROPERTY = 17, 20, 21, 22
END_EOF, END_STOP, END_QUIT, END_ERROR, END_REDIRECT = 0, 2, 3, 4, 5


class _Node(ctypes.Structure):
    pass


class _NodeList(ctypes.Structure):
    _fields_ = [("num", ctypes.c_int), ("values", ctypes.POINTER(_Node)), ("keys", ctypes.POINTER(ctypes.c_char_p))]


class _NodeU(ctypes.Union):
    _fields_ = [("string", ctypes.c_char_p), ("flag", ctypes.c_int), ("int64", ctypes.c_int64),
                ("double_", ctypes.c_double), ("list", ctypes.POINTER(_NodeList))]


_Node._fields_ = [("u", _NodeU), ("format", ctypes.c_int)]


class _Event(ctypes.Structure):
    _fields_ = [("event_id", ctypes.c_int), ("error", ctypes.c_int), ("reply_userdata", ctypes.c_uint64),
                ("data", ctypes.c_void_p)]


class _EventProperty(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p), ("format", ctypes.c_int), ("data", ctypes.c_void_p)]


class _EventEndFile(ctypes.Structure):
    _fields_ = [("reason", ctypes.c_int), ("error", ctypes.c_int), ("playlist_entry_id", ctypes.c_int64),
                ("playlist_insert_id", ctypes.c_int64), ("playlist_insert_num_entries", ctypes.c_int)]


class _EventLog(ctypes.Structure):
    _fields_ = [("prefix", ctypes.c_char_p), ("level", ctypes.c_char_p), ("text", ctypes.c_char_p),
                ("log_level", ctypes.c_int)]


# render API (mpv/render.h, mpv/render_gl.h)
R_INVALID, R_API_TYPE, R_GL_INIT, R_GL_FBO, R_FLIP_Y = 0, 1, 2, 3, 4
_GetProc = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
_Wakeup = ctypes.CFUNCTYPE(None, ctypes.c_void_p)


class _RenderParam(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("data", ctypes.c_void_p)]


class _GLInit(ctypes.Structure):
    _fields_ = [("get_proc_address", _GetProc), ("get_proc_address_ctx", ctypes.c_void_p)]


class _GLFBO(ctypes.Structure):
    _fields_ = [("fbo", ctypes.c_int), ("w", ctypes.c_int), ("h", ctypes.c_int), ("internal_format", ctypes.c_int)]


if lib is not None:
    lib.mpv_create.restype = ctypes.c_void_p
    for name, args, res in [
        ("mpv_initialize", [ctypes.c_void_p], ctypes.c_int),
        ("mpv_terminate_destroy", [ctypes.c_void_p], None),
        ("mpv_set_option_string", [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p], ctypes.c_int),
        ("mpv_set_property_string", [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p], ctypes.c_int),
        ("mpv_set_property", [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p], ctypes.c_int),
        ("mpv_get_property", [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p], ctypes.c_int),
        ("mpv_command", [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)], ctypes.c_int),
        ("mpv_command_async", [ctypes.c_void_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)], ctypes.c_int),
        ("mpv_observe_property", [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_char_p, ctypes.c_int], ctypes.c_int),
        ("mpv_request_log_messages", [ctypes.c_void_p, ctypes.c_char_p], ctypes.c_int),
        ("mpv_wait_event", [ctypes.c_void_p, ctypes.c_double], ctypes.POINTER(_Event)),
        ("mpv_set_wakeup_callback", [ctypes.c_void_p, _Wakeup, ctypes.c_void_p], None),
        ("mpv_free_node_contents", [ctypes.POINTER(_Node)], None),
        ("mpv_error_string", [ctypes.c_int], ctypes.c_char_p),
        ("mpv_render_context_create", [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                       ctypes.POINTER(_RenderParam)], ctypes.c_int),
        ("mpv_render_context_render", [ctypes.c_void_p, ctypes.POINTER(_RenderParam)], ctypes.c_int),
        ("mpv_render_context_set_update_callback", [ctypes.c_void_p, _Wakeup, ctypes.c_void_p], None),
        ("mpv_render_context_update", [ctypes.c_void_p], ctypes.c_uint64),
        ("mpv_render_context_report_swap", [ctypes.c_void_p], None),
        ("mpv_render_context_free", [ctypes.c_void_p], None),
    ]:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, res


def available():
    """None if libmpv can be used, else why not."""
    return None if lib is not None else "libmpv isn't installed (it comes with the mpv package)"


def _node_value(n):
    f = n.format
    if f == FMT_STRING:
        return n.u.string.decode("utf-8", "replace") if n.u.string else ""
    if f == FMT_FLAG:
        return bool(n.u.flag)
    if f == FMT_INT64:
        return int(n.u.int64)
    if f == FMT_DOUBLE:
        return float(n.u.double_)
    if f in (FMT_ARRAY, FMT_MAP):
        lst = n.u.list.contents
        vals = [_node_value(lst.values[i]) for i in range(lst.num)]
        if f == FMT_ARRAY:
            return vals
        return {lst.keys[i].decode("utf-8", "replace"): vals[i] for i in range(lst.num)}
    return None


def _cstrs(args):
    arr = (ctypes.c_char_p * (len(args) + 1))()
    arr[:-1] = [str(a).encode() for a in args]
    arr[-1] = None
    return arr


class MPV:
    """One mpv player. on_event(name, data) receives, on the main loop:
    ("property", (name, value)), ("start-file", None), ("file-loaded",
    None), ("end-file", reason), ("seek", None), ("restart", None),
    ("idle", None), ("log", (level, text))."""

    def __init__(self, schedule, on_event, **options):
        if lib is None:
            raise MPVError(available())
        self.schedule, self.on_event = schedule, on_event
        # libmpv refuses to start under a locale whose decimal point isn't
        # "." (GTK sets the user's locale); numbers are all it changes.
        libc = ctypes.CDLL(None)
        libc.setlocale.argtypes, libc.setlocale.restype = [ctypes.c_int, ctypes.c_char_p], ctypes.c_char_p
        libc.setlocale(1, b"C")   # LC_NUMERIC
        self.h = lib.mpv_create()
        if not self.h:
            raise MPVError("mpv_create failed")
        for k, v in options.items():
            self._check(lib.mpv_set_option_string(self.h, k.replace("_", "-").encode(), str(v).encode()),
                        f"option {k}")
        self._check(lib.mpv_initialize(self.h), "initialize")
        lib.mpv_request_log_messages(self.h, b"warn")
        self._pending = False
        self._wake = _Wakeup(self._wakeup)   # kept: ctypes frees an unreferenced callback
        lib.mpv_set_wakeup_callback(self.h, self._wake, None)
        self._observed = {}
        self.render = None

    def _check(self, rc, what):
        if rc < 0:
            raise MPVError(f"{what}: {lib.mpv_error_string(rc).decode()}")
        return rc

    # -------------------------------------------------------------- events
    def _wakeup(self, _ctx):
        if not self._pending:   # one drain per burst of events
            self._pending = True
            self.schedule(self._drain)

    def _drain(self):
        self._pending = False
        while self.h:
            ev = lib.mpv_wait_event(self.h, 0).contents
            eid = ev.event_id
            if eid == 0:
                break
            try:
                self._dispatch(eid, ev)
            except Exception:
                log.exception("handling mpv event %s", eid)
        return False

    def _dispatch(self, eid, ev):
        if eid == EV_PROPERTY:
            p = ctypes.cast(ev.data, ctypes.POINTER(_EventProperty)).contents
            name = p.name.decode()
            val = None
            if p.format == FMT_DOUBLE:
                val = ctypes.cast(p.data, ctypes.POINTER(ctypes.c_double)).contents.value
            elif p.format == FMT_FLAG:
                val = bool(ctypes.cast(p.data, ctypes.POINTER(ctypes.c_int)).contents.value)
            elif p.format == FMT_INT64:
                val = ctypes.cast(p.data, ctypes.POINTER(ctypes.c_int64)).contents.value
            elif p.format == FMT_STRING:
                s = ctypes.cast(p.data, ctypes.POINTER(ctypes.c_char_p)).contents.value
                val = s.decode("utf-8", "replace") if s is not None else None
            elif p.format == FMT_NODE:
                val = _node_value(ctypes.cast(p.data, ctypes.POINTER(_Node)).contents)
            self.on_event("property", (name, val))
        elif eid == EV_END_FILE:
            e = ctypes.cast(ev.data, ctypes.POINTER(_EventEndFile)).contents
            self.on_event("end-file", (e.reason, e.error))
        elif eid == EV_LOG:
            m = ctypes.cast(ev.data, ctypes.POINTER(_EventLog)).contents
            self.on_event("log", (m.level.decode(), f"{m.prefix.decode()}: {m.text.decode('utf-8', 'replace').rstrip()}"))
        elif eid == EV_SHUTDOWN:
            self.on_event("shutdown", None)
        else:
            name = {EV_START_FILE: "start-file", EV_FILE_LOADED: "file-loaded", EV_IDLE: "idle", EV_SEEK: "seek",
                    EV_RESTART: "restart", EV_VIDEO_RECONFIG: "video-reconfig"}.get(eid)
            if name:
                self.on_event(name, None)

    # -------------------------------------------------------------- API
    def command(self, *args):
        """Runs an mpv command; returns False (and logs) if mpv refused it."""
        rc = lib.mpv_command(self.h, _cstrs(args))
        if rc < 0:
            log.warning("mpv %s: %s", args[0], lib.mpv_error_string(rc).decode())
            return False
        return True

    def command_async(self, *args):
        lib.mpv_command_async(self.h, 0, _cstrs(args))

    def set(self, name, value):
        if isinstance(value, bool):
            value = "yes" if value else "no"
        rc = lib.mpv_set_property_string(self.h, name.encode(), str(value).encode())
        if rc < 0:
            log.debug("mpv set %s=%s: %s", name, value, lib.mpv_error_string(rc).decode())
        return rc >= 0

    def get(self, name, default=None):
        n = _Node()
        if lib.mpv_get_property(self.h, name.encode(), FMT_NODE, ctypes.byref(n)) < 0:
            return default
        try:
            return _node_value(n)
        finally:
            lib.mpv_free_node_contents(ctypes.byref(n))

    def observe(self, name, fmt=FMT_NODE):
        if name not in self._observed:
            self._observed[name] = len(self._observed) + 1
            lib.mpv_observe_property(self.h, self._observed[name], name.encode(), fmt)

    def loadfile(self, url, mode="replace", options=None):
        """options: per-file options, any characters (each value is quoted
        the way mpv's lists allow, so a comma or = in a title or a password
        can't break out of it)."""
        args = ["loadfile", url, mode]
        if options:
            args += ["-1", ",".join(f"{k}={quote(v)}" for k, v in options.items())]
        return self.command(*args)

    def terminate(self):
        if self.render is not None:
            self.render.free()
        if self.h:
            h, self.h = self.h, None
            lib.mpv_terminate_destroy(h)


def _gl_proc_lookup():
    """A get_proc_address for the current GL context: EGL (Wayland, and X11
    with GTK's default), else GLX."""
    egl = _load("EGL", "libEGL.so.1")
    if egl is not None:
        egl.eglGetProcAddress.restype = ctypes.c_void_p
        egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
        fn = egl.eglGetProcAddress
    else:
        glx = _load("GLX", "libGLX.so.0", "GL")
        glx.glXGetProcAddressARB.restype = ctypes.c_void_p
        glx.glXGetProcAddressARB.argtypes = [ctypes.c_char_p]
        fn = glx.glXGetProcAddressARB
    return _GetProc(lambda _ctx, name: fn(name) or 0)


_gl = None


def current_fbo():
    """The framebuffer GTK bound for this GLArea frame."""
    global _gl
    if _gl is None:
        _gl = _load("OpenGL", "libOpenGL.so.0", "GL", "libGL.so.1")
        _gl.glGetIntegerv.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
    v = ctypes.c_int(0)
    _gl.glGetIntegerv(0x8CA6, ctypes.byref(v))   # GL_DRAW_FRAMEBUFFER_BINDING
    return v.value


class GLRender:
    """mpv's OpenGL renderer for the GL context that's current when it's
    made (a GtkGLArea's, in its realize handler). on_update() is scheduled
    on the main loop whenever mpv has a new frame."""

    def __init__(self, player, schedule, on_update):
        self.player = player
        self.ctx = ctypes.c_void_p()
        self._proc = _gl_proc_lookup()
        init = _GLInit(self._proc, None)
        api = ctypes.c_char_p(b"opengl")
        params = (_RenderParam * 3)(_RenderParam(R_API_TYPE, ctypes.cast(api, ctypes.c_void_p)),
                                    _RenderParam(R_GL_INIT, ctypes.cast(ctypes.pointer(init), ctypes.c_void_p)),
                                    _RenderParam(R_INVALID, None))
        rc = lib.mpv_render_context_create(ctypes.byref(self.ctx), player.h, params)
        if rc < 0:
            raise MPVError(f"render context: {lib.mpv_error_string(rc).decode()}")
        self._scheduled = False

        def update(_c):
            if not self._scheduled:
                self._scheduled = True
                schedule(self._fire)
        self._fire_cb = on_update
        self._upd = _Wakeup(update)
        lib.mpv_render_context_set_update_callback(self.ctx, self._upd, None)
        player.render = self

    def _fire(self):
        self._scheduled = False
        if self.ctx:
            self._fire_cb()
        return False

    def draw(self, fbo, w, h):
        if not self.ctx:
            return
        lib.mpv_render_context_update(self.ctx)
        f = _GLFBO(fbo, w, h, 0)
        flip = ctypes.c_int(1)
        params = (_RenderParam * 3)(_RenderParam(R_GL_FBO, ctypes.cast(ctypes.pointer(f), ctypes.c_void_p)),
                                    _RenderParam(R_FLIP_Y, ctypes.cast(ctypes.pointer(flip), ctypes.c_void_p)),
                                    _RenderParam(R_INVALID, None))
        lib.mpv_render_context_render(self.ctx, params)

    def free(self):
        if self.ctx:
            ctx, self.ctx = self.ctx, ctypes.c_void_p()
            lib.mpv_render_context_free(ctx)
        if self.player.render is self:
            self.player.render = None


def quote(v):
    """A value for an mpv key=value list: %bytes%text quoting."""
    v = str(v)
    return f"%{len(v.encode())}%{v}"


def as_json(v):
    return json.dumps(v, ensure_ascii=False)
