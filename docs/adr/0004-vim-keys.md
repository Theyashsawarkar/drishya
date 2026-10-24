# 4. nāda's vim keys

**Status:** Accepted  
**Date:** 2026-10-24

## Context

drishya sits next to nāda (music) on the same desktop. Two players with different keys would mean learning both.

## Decision

drishya takes nāda's key engine and keys wherever they mean the same thing (tabs by number, `j`/`k`, `gg`/`G`, `Space`, `,`/`.`, `<`/`>`, `dd`/`yy`/`p`, `V`, `u`, `/`, `:`, `?`, `z`, `q`), and adds video keys where common players have them: `f` fullscreen, `c` captions, `[`/`]` speed, `{`/`}` chapters, `#` audio track (mpv's), `h`/`l` fine seeking on the Watch tab.

## Consequences

- Knowing one player means knowing the other.
- Every key is listed in the README and Vayu's keybinding search (CI checks the README).
