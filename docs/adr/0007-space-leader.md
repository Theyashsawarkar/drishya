# 7. The Space leader, from one keymap

**Status:** Accepted (refines ADR 4)  
**Date:** 2026-11-08

## Context

Every Vayu tool is moving to one key grammar: Normal mode keys you use all
the time are one key, and everything else sits under `Space` as the leader,
the same group letters meaning the same things in every tool (`Space t`
tabs, `u` toggles, `y` copy, `f` find, `d` delete, `o` open outside, `g`
go to, `,` settings, `Space Space` a palette, `Space ?` the keys). drishya had
its own engine (copied between nāda and drishya), with `Space` as play /
pause, a 650 ms timer on a lone digit (a tab, or a count?) and the keys
written three times: the engine, the help table and the `# keybind:` lines.

## Decision

- Keys are data: `drishya/keymap.py` lists every bind (sequence, action,
  description, the tabs it works on). The engine, the which-key strip, the
  palette, the key sheet, the `# keybind:` lines and the README tables are
  all made from it (`scripts/keybinds.py`; the tests fail when they drift).
- Sequences, counts and the leader come from Vyom's `keys.py`, vendored
  (`drishya/keys.py`, written by Vyom's `scripts/vendor-keys.sh`), the same
  module every Vayu tool uses. Visual mode, registers, `:` and `/` stay ours.
- `Space` is the leader; play / pause is `p` (the mini player and
  fullscreen keep `Space`). Paste is `gp` / `gP`. Tabs are `H` / `L`,
  `Space t` and `Ctrl+0..4`; digits are only counts, so no timer.
- A sequence never times out; the strip shows after 300 ms; `Esc` cancels.
  Confirmations take `y` only.
- Keys that moved say where for one release, then go.

## Consequences

- The same keys as every other Vayu tool, and nothing to keep in step by hand.
- `keys.py` reads `<` as the start of `<CR>`; the window runs `<` at once
  until Vyom fixes it.
- `leader.py` (the strip, the palette, the key sheet) is shared with the
  sibling player, like `search.py`: keep the two in step.
