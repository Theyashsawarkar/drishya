# drishya -- notes for AI agents (same as CLAUDE.md)

A keyboard-driven video player (Python + GTK 4 + libmpv): YouTube, your
files, any stream (HLS, links, yt-dlp sites) with sign-in, resume,
history, downloads. nāda's sibling for video. Its own repo, pulled into
Vayu (github.com/Theyashsawarkar/vayu, whose CLAUDE.md "Plugins" rules
apply); it must work on any Linux desktop without Vayu.

- `bin/drishya` is the CLI: it sends D-Bus actions (org.gtk.Actions on
  dev.vayu.Drishya: toggle show hide mini quit add tab ctl); `status`
  reads MPRIS.
- `drishya/mpv.py`: the libmpv binding (ctypes; client API + OpenGL render
  API). `drishya/core.py`: the model (queue, playback, resume, autoplay,
  undo, logins, downloads). `drishya/window.py`: the window and the vim key
  engine; `drishya/views.py`: the six tabs; `drishya/mini.py`: the mini
  player; `drishya/auth.py`: sign-in and the keyring; `drishya/youtube.py`,
  `drishya/library.py`: blocking helpers, only from worker threads
  (`core.bg`). `drishya/util.py`, `store.py`, `config.py`: pure, tested.
- One renderer at a time: a `VideoArea` attaches (takes mpv's render
  context) and detaches; never draw from two. Load only once a renderer
  exists (mpv's VO fails otherwise).
- Never block the GTK main loop; never log or save a password; links are
  saved without their credentials.
- Every key has a `# keybind: Drishya/<scope> | <keys> | <Verb> ...` line
  (Vayu's keybinding search reads them) and a row in the README (CI checks).
- Every change: a CHANGELOG.md entry; releases are tags with `VERSION`
  bumped. `python -m py_compile drishya/*.py bin/drishya` and
  `python -m unittest discover -s tests` must pass (tests import no GTK).
- Test without touching the user's screen or speakers: a headless sway
  (WLR_BACKENDS=headless) with its own D-Bus session and XDG_RUNTIME_DIR,
  XDG_CONFIG/STATE/CACHE_HOME in a scratch dir with
  `{"volume": 0}` in state's settings.json, `grim` and `wtype -s 250`.
- The website (docs/, GitHub Pages) is generated: after changing README.md, CHANGELOG.md or docs/adr/, run `python3 scripts/build-site.py` and commit docs/ (CI checks it). A significant design decision gets a new ADR in docs/adr/ (next number; supersede, never rewrite).
