# 5. Video first, and fullscreen is zen

**Status:** Accepted  
**Date:** 2026-10-24

## Context

The first version put the controls in a bar under the video, always visible, as in a music player. Video players people like (YouTube, IINA, mpv with uosc) keep the picture clear: controls appear when you need them and leave. In fullscreen the user asked for nothing at all over the video, not even a progress bar.

## Decision

On Watch the controls float over the video and fade 2.5 s after the last key or mouse move while it plays (they stay while it's paused). The timeline is drawn by drishya: chapters as segments, the buffer, and a preview frame under the pointer (YouTube's storyboards, ffmpeg frames for files). Fullscreen is zen: no controls or bar ever; a seek, a volume change or `i` shows a small readout in the corner for about a second.

## Consequences

- Keys work the same in every mode; only what's drawn changes.
- Preview frames need YouTube's storyboard (from the yt-dlp call that fetches the video's details) or ffmpeg; without them the preview shows only the time and chapter.
