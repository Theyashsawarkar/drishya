# Changelog

Newest first. Releases are tags (`vX.Y.Z`) with `VERSION` in `drishya/__init__.py`.

## v0.2.1 -- 2026-10-24

- **Volume and brightness keys**: `=`/`-` change the system volume (what
  you hear, not only drishya's), `Ctrl+=`/`Ctrl+-` the screen's brightness;
  in the mini player too. When the window closes (or the mini player, or
  drishya quits) both go back to how they were before. Through pactl or
  wpctl and brightnessctl; without them the keys say what's missing.
- A tab number followed by a key that takes no count (`V`, `Esc`, `/`…),
  or a lone `1`, goes to that tab first: `1 V` selected on the wrong tab,
  and `Esc` then closed the window.
- In the library, `Backspace` from one of your folders goes back to the
  top (Continue watching); it showed the folder's plain listing. `-` is the
  volume everywhere now (it went up a folder in the library).
- Switching the search panel to Commands clears the box and lists every
  command (it kept the words you'd searched for).
- Toasts show above the search panel, not under its shade.
- `DRISHYA_DEBUG=1` logs each key and mode change, for bug reports.

## v0.2.0 -- 2026-10-24

- **Video first.** The controls float over the video and fade after
  2.5 s while it plays (a key or the mouse brings them back); the window's
  bottom bar is gone on Watch. The title, channel and quality sit at the top.
- **A timeline with chapters** as segments, what's buffered, and a preview
  frame where you hover (YouTube's storyboards; ffmpeg for your files),
  with the time and chapter name. Readable over any picture.
- **Zen fullscreen** (`f`): just the video, no bar, no controls. Seeking or
  changing the volume shows a small readout in the corner for a second;
  `i` shows the title and time.
- **Search from anywhere** (`/`): a floating panel for YouTube, your videos
  (indexed in the background), your history, links and commands; results
  as you type, the best match on top, `Tab` for where to look, `yt `,
  `lib `, `h `, `:` to narrow, actions without leaving it. Paste a link
  and the first row plays it. The YouTube tab is gone (its full results
  open from the panel); tabs are now Watch · Up next · Library · History ·
  Downloads (`0`–`4`). `o` opens the panel too.
- **One settings menu** (`Q`): quality, speed, subtitles, audio track and
  download, `j`/`k` to move, `l`/`Enter` in, `h` back.
- **The side panel** has Up next, Chapters (jump with `Enter`) and Info
  (link, views, date, description); `Tab` switches.
- **The library is a grid**: Continue watching, then your folders and
  videos with thumbnails, lengths and how much you've seen; `h j k l` move,
  `Enter` opens or plays (with the rest of the folder after it),
  `Backspace` goes up.
- Speed reset moved from Backspace to `\` (Backspace means back, everywhere).

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
