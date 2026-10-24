# 2. libmpv draws into the window

**Status:** Accepted  
**Date:** 2026-10-24

## Context

A video player can either drive a separate player window (mpv over its IPC socket) or draw the video inside its own window. Two windows are simpler to build but feel like two programs: the list in one, the video in another, focus and fullscreen handled by each. GTK 4 on Wayland can't embed another program's window.

## Decision

drishya uses libmpv's render API: mpv decodes (with hardware decoding) and draws with OpenGL into a GTK `GLArea` in drishya's window. The binding is drishya's own, with ctypes (`drishya/mpv.py`), so the only dependency is libmpv, which ships with mpv. One area holds the renderer at a time; the mini player takes it over and gives it back.

## Consequences

- One window: the video, Up next and the controls together; fullscreen and theater mode are drishya's.
- A video only loads once a renderer exists (mpv's video output fails without one), and moving the renderer rebuilds the video output.
- mpv's own key bindings and on-screen controller are off: every key is drishya's.
