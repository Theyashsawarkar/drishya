# 6. One floating search panel instead of a YouTube tab

**Status:** Accepted  
**Date:** 2026-10-24

## Context

Searching meant going to the YouTube tab and pressing Enter; the library and the history each searched differently, and links went through a separate `o` prompt. Command palettes and music apps converge on one box that searches everything as you type and puts the best match first.

## Decision

`/` opens a floating panel over any tab: a link you typed, your videos (from a background index of video_dirs), your history, then YouTube after a 350 ms pause; `Tab` switches scope and prefixes narrow it. Actions run on the selected row without leaving the box. The panel (`drishya/search.py`) is the same module as nāda's.

## Consequences

- The YouTube tab is gone; its full results open as a page from the panel. Tabs renumber: Watch 0, Up next 1, Library 2, History 3, Downloads 4.
- The same search, keys and look in drishya and nāda.
