# Changelog

Newest first. Releases are tags (`vX.Y.Z`) with `VERSION` in `drishya/__init__.py`.

## v0.1.0 -- 2026-10-24

- First release: a keyboard-driven video player, nāda's sibling for video.
- **The video in the window** (libmpv's OpenGL renderer in a GTK
  `GLArea`, bound with ctypes), hardware decoding; fullscreen (`f`),
  theater mode (`t`), and a mini player (`z`) that takes the video over.
- **YouTube**: search with thumbnails, views and length; related videos
  after yours (autoplay, `M`); streams up to your `quality`, never AV1.
- **Any link** (`o`, `drishya play <link>`, or pasted into the search box):
  HLS and DASH from any server, video files over HTTP, live streams, every
  site yt-dlp plays. A stream's qualities are capped like YouTube's.
- **Signing in**: a server that wants a login (401/403) gets a sign-in
  panel; HTTP authentication goes with every request, each HLS segment
  included. Sites that need an account can use your browser's login.
  Logins are kept in memory, or in your keyring if you ask; credentials
  in a link are taken out of it before it's saved anywhere.
- **Library**: video folders in columns, episodes in natural order, the
  next episode lined up, thumbnails and lengths (ffmpeg).
- **Resume and history**: every video starts where you stopped; History
  has *Continue watching* and a watched bar on every thumbnail.
- **Up next** edited with vim keys (`dd`, `J`/`K`, `yy`/`p`, `V`, `u`,
  `Ctrl+r`), undoable.
- **Downloads** (`D`) of YouTube videos and any link, with subtitles,
  chapters and thumbnail; a download then plays from disk. Subtitles are
  real captions in your languages, never YouTube's machine translations
  (they're slow and get rate-limited); if subtitles still fail, the video
  downloads without them.
- Subtitles (`c`), audio tracks (`#`), speed (`[` `]`), chapters (`{` `}`),
  start over (`S`), sleep timer, screenshots.
- **Quality** (`Q`, or the quality button): YouTube's qualities for the
  video (reopens it at the same second) or a stream's (instant); the pick
  is kept for the next videos and for downloads. Buttons for opening a
  link or file and for downloading sit next to it.
- A YouTube link opened directly gets its real title, channel and views
  (autoplay waits for them, so it finds videos like it).
- MPRIS, `drishya ctl`, `drishya status`; varna's theme and Vyom's glass.
- The timeline is a thin line, like YouTube's; its knob shows on hover.
- A desktop file (`data/`): launchers, and opening video files and HLS
  playlists with drishya.
