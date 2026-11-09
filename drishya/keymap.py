"""Every key of the window, as data (Vyom's keys.py, vendored as keys.py):
one table that the key engine (window.py), the which-key strip, the
palette, the key sheet, the `# keybind:` lines below and the README's key
tables are all made from. Pure Python: the tests read it without GTK.

Actions are strings the window runs:
  do:<key>     the old key engine's name for it (window.dispatch), e.g. do:dd
  tab:<±1|name> switch tabs        call:<method>[:arg] a Window method
  moved:<keys> a key that moved: say where (one release, then it goes)
A "|note:<text>" tail shows <text> once a session (a key with a new job).

Change a key here, then run `python3 scripts/keybinds.py` (it rewrites the
lines below and README.md; the tests fail until you do).

The Space grammar (the same in every Vayu tool): Space t tabs, u toggles,
y copy, f find, r refresh, a add, d delete, o open outside, g go to,
, settings, Space Space palette, Space ? keys, Space q close. drishya's
own groups use free letters: c captions, p playback, x downloads, i info.
In fullscreen (zen) Space still plays and pauses: there is no leader there.
"""
from .keys import Bind

SOURCE = "Drishya"
TABS = ["watch", "queue", "library", "history", "downloads"]   # YouTube's results: a page, from the search panel
TAB_TITLES = {"watch": "Watch", "queue": "Up next", "library": "Library", "history": "History",
              "downloads": "Downloads", "youtube": "YouTube"}
GROUPS = {" c": "captions", " p": "playback", " x": "downloads"}


def B(seq, action, desc="", hidden=False, mode="normal"):
    return Bind(seq, action, desc, mode=mode, hidden=hidden)


# (scope, the tabs it works on (None: everywhere), binds). Later sections
# win over earlier ones for the same keys, so a tab's own keys come last.
SECTIONS = [
    ("everywhere", None, [
        B("j", "do:j", "Move down (counts work: 5j)"),
        B("k", "do:k", "Move up"),
        B("<Down>", "do:j", hidden=True), B("<Up>", "do:k", hidden=True),
        B("gg", "do:gg", "Jump to the top (12gg: to the 12th)"),
        B("G", "do:G", "Jump to the bottom (12G: to the 12th)"),
        B("<C-d>", "do:C-d", "Scroll half a page down"),
        B("<C-u>", "do:C-u", "Scroll half a page up"),
        B("<PgDn>", "do:C-d", hidden=True), B("<PgUp>", "do:C-u", hidden=True),
        B("H", "tab:-1", "Switch to the previous tab (wraps around)"),
        B("L", "tab:+1", "Switch to the next tab (wraps around)"),
        B("<C-Tab>", "tab:+1", "Switch to the next tab (also from the search box)"),
        B("<C-S-Tab>", "tab:-1", "Switch to the previous tab (also from the search box)"),
        B("<C-0>", "tab:watch", "Switch to Watch at once (Ctrl+1 Up next, 2 Library, 3 History, 4 Downloads)"),
        B("<C-1>", "tab:queue", hidden=True), B("<C-2>", "tab:library", hidden=True),
        B("<C-3>", "tab:history", hidden=True), B("<C-4>", "tab:downloads", hidden=True),
        B("p", "call:toggle_play", "Toggle play / pause (in fullscreen, Space too)"),
        B("<CR>", "do:Return", "Play the selected video"),
        B(".", "do:.", "Seek forward 10 seconds (3. = 30 s)"),
        B(",", "do:,", "Seek back 10 seconds"),
        B(">", "do:>", "Play the next video"),
        B("<", "do:<", "Play the previous video"),
        B("=", "do:=", "Raise the system volume (back as it was when the window closes)"),
        B("+", "do:=", hidden=True),
        B("-", "do:-", "Lower the system volume"),
        B("<C-=>", "do:C-=", "Raise the screen brightness (back as it was when the window closes)"),
        B("<C-+>", "do:C-=", hidden=True),
        B("<C-->", "do:C--", "Lower the screen brightness"),
        B("m", "do:m", "Toggle mute"),
        B("f", "do:f", "Toggle fullscreen (zen: just the video; Esc leaves it too)"),
        B("t", "do:t", "Toggle theater mode (the video without the side panel)"),
        B("z", "call:mini", "Switch to the mini player (picture-in-picture)"),
        B("c", "do:c", "Cycle subtitles (off, then each language)"),
        B("#", "do:#", "Cycle the audio track"),
        B("[", "do:[", "Slow down playback (0.25× steps)"),
        B("]", "do:]", "Speed up playback (0.25× steps)"),
        B("\\", "do:\\", "Reset playback speed to normal"),
        B("{", "do:{", "Jump to the previous chapter"),
        B("}", "do:}", "Jump to the next chapter"),
        B("S", "do:S", "Start the video over from the beginning"),
        B("M", "do:M", "Toggle autoplay (related videos or the next episode after yours)"),
        B("D", "do:D", "Save the playing video to your disk with subtitles (download)"),
        B("V", "do:V", "Select several videos (visual mode)"),
        B("u", "do:u", "Restore the last queue change (undo)"),
        B("<C-r>", "do:C-r", "Restore an undone queue change (redo)"),
        B("Q", "do:Q", "Open the settings menu (quality, speed, subtitles, audio, download)"),
        B("r", "call:refresh", "Refresh the lists (Library: reload the folders)"),
        B("/", "do:/", "Open the search panel (YouTube, your videos, history, links, : commands)"),
        B("o", "do:o", "Open the search panel to paste a link or file path"),
        B(":", "do::", "Run a command (:seek 1:30, :speed 1.5…)"),
        B("?", "call:keysheet", "Show every key of this tab"),
        B("q", "do:q", "Close the window (pauses; z keeps a mini player)"),
        B("<Esc>", "do:Escape", "Leave fullscreen, go back, or close the window"),
        B("i", "moved:Space i", "Show where video info moved (Space i; for one release)"),
        B("0", "moved:H / L or Space t w", "Show where the tab numbers moved (H / L, Space t; for one release)"),
        # The leader
        B("  ", "call:palette", "Open the palette (every action of this tab, fuzzy)"),
        B(" ?", "call:keysheet", "Show every key of this tab"),
        B(" q", "do:q", "Close the window (pauses)"),
        B(" tw", "tab:watch", "Switch to Watch (the video)"),
        B(" tu", "tab:queue", "Switch to Up next (the queue)"),
        B(" tl", "tab:library", "Switch to your video library"),
        B(" th", "tab:history", "Switch to your history (continue watching)"),
        B(" td", "tab:downloads", "Switch to downloads"),
        B(" uf", "do:f", "Toggle fullscreen (zen)"),
        B(" ut", "do:t", "Toggle theater mode"),
        B(" um", "call:mini", "Switch to the mini player"),
        B(" cc", "do:c", "Cycle subtitles"),
        B(" ca", "do:#", "Cycle the audio track"),
        B(" pa", "do:M", "Toggle autoplay"),
        B(" ps", "do:S", "Start the video over from the beginning"),
        B(" pz", "call:sleep", "Toggle the sleep timer (pauses in 30 min)"),
        B(" ,", "do:Q", "Open the settings menu (quality, speed, subtitles, audio, download)"),
        B(" yy", "call:copy_title", "Copy the playing video's title"),
        B(" yl", "call:copy_link", "Copy the playing video's link (or file path)"),
        B(" ff", "call:search:0", "Search everything"),
        B(" fy", "call:search:1", "Search YouTube"),
        B(" fv", "call:search:2", "Search your videos"),
        B(" fh", "call:search:3", "Search your history"),
        B(" fc", "call:search:4", "Search the : commands"),
        B(" xd", "do:D", "Save the video to your disk (download)"),
        B(" i", "call:info", "Show the video's title and link"),
        B(" gp", "call:goto_playing", "Go to the video that's playing (in Up next)"),
        B(" ob", "call:open_browser", "Open the playing video's page in the browser"),
        B(" r", "call:refresh", "Refresh the lists (Library: reload the folders)"),
        B(" dc", "call:clear_queue", "Clear Up next (asks first; u brings it back)"),
    ]),
    ("watch", {"watch"}, [
        B("h", "do:h", "Seek back 5 seconds (3h = 15 s)"),
        B("l", "do:l", "Seek forward 5 seconds"),
        B("<Left>", "do:h", hidden=True), B("<Right>", "do:l", hidden=True),
        B("<Tab>", "do:Tab", "Switch the side panel (up next, chapters, info)"),
        B("<CR>", "do:Return", "Play the side panel's video, or jump to its chapter"),
    ]),
    ("up next", {"queue"}, [
        B("dd", "do:dd", "Remove the video from the queue (2dd: two; u undoes it)"),
        B("x", "do:x", "Remove the video from the queue (like dd; u undoes it)"),
        B("dG", "do:dG", "Remove every video from here to the end (u undoes it)"),
        B("yy", "do:yy", "Copy the video (yank)"),
        B("gp", "do:p", "Paste removed or copied videos below"),
        B("gP", "do:P", "Paste removed or copied videos above"),
        B("P", "do:P", hidden=True),
        B("J", "do:J", "Move the video down"),
        B("K", "do:K", "Move the video up"),
        B("A", "do:A", "Move the video to play next"),
        B("D", "do:D", "Save the video to your disk (download)"),
        B("n", "do:n", "Jump to the next match (after a search here)"),
        B("N", "do:N", "Jump to the previous match"),
        B(" dd", "do:dd", "Remove the video from the queue (u undoes it)"),
    ]),
    ("library", {"library"}, [
        B("h", "do:h", "Move left in the grid"),
        B("l", "do:l", "Move right in the grid"),
        B("<Left>", "do:h", hidden=True), B("<Right>", "do:l", hidden=True),
        B("<CR>", "do:Return", "Open the folder or play the video (the rest of the folder after it)"),
        B("<BS>", "do:BackSpace", "Go up a folder"),
        B("a", "do:a", "Add to the end of the queue"),
        B("A", "do:A", "Add to play next"),
        B("R", "do:R", "Reload the folders"),
        B(" aa", "do:a", "Add to the end of the queue"),
        B(" an", "do:A", "Add to play next"),
    ]),
    ("youtube", {"youtube"}, [
        B("<CR>", "do:Return", "Play the result"),
        B("a", "do:a", "Add the result to the end of the queue"),
        B("A", "do:A", "Add the result to play next"),
        B("D", "do:D", "Save the result to your disk (download)"),
        B(" aa", "do:a", "Add the result to the end of the queue"),
        B(" an", "do:A", "Add the result to play next"),
    ]),
    ("history", {"history"}, [
        B("<CR>", "do:Return", "Resume the video where you left it"),
        B("a", "do:a", "Add the video to the end of the queue"),
        B("A", "do:A", "Add the video to play next"),
        B("dd", "do:dd", "Forget the video (removes it from the history; asks first)"),
        B("x", "do:x", "Forget the video (like dd; asks first)"),
        B("D", "do:D", "Save the video to your disk (download)"),
        B("n", "do:n", "Jump to the next match (after a search here)"),
        B("N", "do:N", "Jump to the previous match"),
        B(" aa", "do:a", "Add the video to the end of the queue"),
        B(" an", "do:A", "Add the video to play next"),
        B(" dd", "do:dd", "Forget the video (asks first)"),
    ]),
    ("downloads", {"downloads"}, [
        B("<CR>", "do:Return", "Play the saved video"),
        B("R", "do:R", "Retry a failed download"),
        B("x", "do:x", "Cancel a download in progress"),
        B("dd", "do:dd", "Delete the saved file (asks first)"),
        B(" xr", "do:R", "Retry a failed download"),
        B(" xc", "do:x", "Cancel a download in progress"),
        B(" dd", "do:dd", "Delete the saved file (asks first)"),
    ]),
]

# Visual mode (V in a list): the motions above, and these act on the selection.
VISUAL = [
    ("up next", {"queue"}, [
        B("d", "do:dd", "Remove the selected videos (u undoes it)", mode="visual"),
        B("x", "do:dd", "Remove the selected videos (like d; u undoes it)", mode="visual"),
        B("y", "do:yy", "Copy the selected videos (yank)", mode="visual"),
        B("V", "do:V", "Leave visual mode", mode="visual"),
        B("<Esc>", "do:Escape", "Leave visual mode", mode="visual"),
    ]),
    ("history", {"history"}, [
        B("d", "do:dd", "Forget the selected videos (asks first)", mode="visual"),
        B("x", "do:dd", "Forget the selected videos (like d; asks first)", mode="visual"),
        B("a", "do:a", "Add the selected videos to the end of the queue", mode="visual"),
        B("A", "do:A", "Add the selected videos to play next", mode="visual"),
        B("V", "do:V", "Leave visual mode", mode="visual"),
        B("<Esc>", "do:Escape", "Leave visual mode", mode="visual"),
    ]),
    ("youtube", {"youtube"}, [
        B("a", "do:a", "Add the selected results to the end of the queue", mode="visual"),
        B("A", "do:A", "Add the selected results to play next", mode="visual"),
        B("D", "do:D", "Save the selected results (download)", mode="visual"),
        B("V", "do:V", "Leave visual mode", mode="visual"),
        B("<Esc>", "do:Escape", "Leave visual mode", mode="visual"),
    ]),
]

# Panels with keys of their own (they take every key while open): listed
# for the key sheet, the README and the keybinding search only.
PANELS = [
    ("fullscreen", "normal", [
        B(" ", None, "Toggle play / pause (zen has no leader)"),
    ]),
    ("settings", "normal", [
        B("j", None, "Move down through the settings menu"),
        B("k", None, "Move up through the settings menu"),
        B("l", None, "Open the setting or choose it (Enter too)"),
        B("h", None, "Go back in the settings menu (Backspace too)"),
        B("<Esc>", None, "Close the settings menu (Q and q too)"),
    ]),
    ("search", "insert", [
        B("<Tab>", None, "Switch where to look (all, YouTube, your videos, history, commands)"),
        B("<S-Tab>", None, "Switch back where to look"),
        B("<C-j>", None, "Move down through the results while typing"),
        B("<C-k>", None, "Move up through the results while typing"),
        B("<CR>", None, "Play the result (a command: run it)"),
        B("<C-CR>", None, "Play the result next"),
        B("<S-CR>", None, "Add the result to Up next"),
        B("<C-d>", None, "Download the result"),
        B("<C-u>", None, "Clear the search box"),
        B("<C-x>", None, "Clear recent searches"),
        B("<Esc>", None, "Close the search panel"),
    ]),
    ("sign in", "insert", [
        B("<CR>", None, "Sign in and play (from the password field)"),
        B("<Tab>", None, "Move between the username and password fields"),
        B("<C-b>", None, "Sign in with your browser's login instead (sites yt-dlp plays)"),
        B("<C-s>", None, "Toggle remembering the login in your keyring"),
        B("<Esc>", None, "Cancel signing in"),
    ]),
    ("palette", "insert", [
        B("<C-j>", None, "Move down through the actions (Down too)"),
        B("<C-k>", None, "Move up through the actions (Up too)"),
        B("<CR>", None, "Run the action"),
        B("<Esc>", None, "Close the palette"),
    ]),
    ("leader", "normal", [
        B("<Esc>", None, "Cancel a pending key or count (Space, g, d…)"),
    ]),
]

COMMANDS = ":yt <search> · :open <file, folder or link> · :add <…> · :seek 1:30 · :speed 1.5 · :vol 80 · " \
           ":sub off · :quality 720 (or Q) · :sleep 30m · :shot · :logout · :autoplay on/off · :clear · :dl · :q · :qa"


def _with_when(sections):
    out = []
    for _scope, tabs, bs in sections:
        for b in bs:
            b.when = tabs
            out.append(b)
    return out


ALL = _with_when(SECTIONS)
ALL_VISUAL = _with_when(VISUAL)


def binds_for(tab, visual=False):
    """The binds that work on this tab right now (later ones win)."""
    out = [b for b in ALL if b.applies("normal", tab)]
    if visual:
        # d and y act at once on a selection: no dd / yy / dG waiting
        out = [b for b in out if not (len(b.seq) > 1 and b.seq[0] in "dy")]
        out += [b for b in ALL_VISUAL if b.applies("visual", tab)]
    return out


def where(tab):
    return TAB_TITLES.get(tab, tab)


# ------------------------------------------------------------- generated docs
def _spell_sections():
    from .keys import spell
    for scope, _tabs, bs in SECTIONS:
        yield scope, "normal", [(spell(b.seq), b.desc) for b in bs if not b.hidden and b.desc]
    for scope, _tabs, bs in VISUAL:
        yield f"{scope} visual", "visual", [(spell(b.seq), b.desc) for b in bs if not b.hidden and b.desc]
    for scope, mode, bs in PANELS:
        yield scope, mode, [(spell(b.seq), b.desc) for b in bs if not b.hidden and b.desc]


def annotation_lines():
    from .keys import spell
    lines = []
    for scope, mode, rows in _spell_sections():
        base = scope.replace(" visual", "")
        for k, d in rows:
            lines.append(f"# keybind: {SOURCE}/{base}:{mode} | {k} | {d}")
    for prefix, name in sorted(GROUPS.items()):
        lines.append(f"# keybind-group: {SOURCE}/everywhere | {spell(prefix)} | {name.capitalize()}")
    return lines


def readme_tables():
    titles = {"everywhere": "Everywhere", "watch": "Watch", "up next": "Up next", "library": "Library",
              "youtube": "YouTube results", "history": "History", "downloads": "Downloads",
              "up next visual": "Up next, visual mode (V)", "history visual": "History, visual mode (V)",
              "youtube visual": "YouTube results, visual mode (V)", "fullscreen": "Fullscreen (f)",
              "settings": "Settings menu (Q, Space ,)", "search": "Search panel (/)", "sign in": "Sign in",
              "palette": "Palette (Space Space)", "leader": "While a key waits"}
    out = []
    for scope, _mode, rows in _spell_sections():
        out += [f"**{titles.get(scope, scope)}**", "", "| Key | Action |", "|---|---|"]
        out += [f"| `{k}` | {d} |" for k, d in rows]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --- keybind lines: generated by scripts/keybinds.py from the tables above; don't edit ---
# keybind: Drishya/everywhere:normal | j | Move down (counts work: 5j)
# keybind: Drishya/everywhere:normal | k | Move up
# keybind: Drishya/everywhere:normal | g g | Jump to the top (12gg: to the 12th)
# keybind: Drishya/everywhere:normal | G | Jump to the bottom (12G: to the 12th)
# keybind: Drishya/everywhere:normal | Ctrl+d | Scroll half a page down
# keybind: Drishya/everywhere:normal | Ctrl+u | Scroll half a page up
# keybind: Drishya/everywhere:normal | H | Switch to the previous tab (wraps around)
# keybind: Drishya/everywhere:normal | L | Switch to the next tab (wraps around)
# keybind: Drishya/everywhere:normal | Ctrl+Tab | Switch to the next tab (also from the search box)
# keybind: Drishya/everywhere:normal | Ctrl+Shift+Tab | Switch to the previous tab (also from the search box)
# keybind: Drishya/everywhere:normal | Ctrl+0 | Switch to Watch at once (Ctrl+1 Up next, 2 Library, 3 History, 4 Downloads)
# keybind: Drishya/everywhere:normal | p | Toggle play / pause (in fullscreen, Space too)
# keybind: Drishya/everywhere:normal | Enter | Play the selected video
# keybind: Drishya/everywhere:normal | . | Seek forward 10 seconds (3. = 30 s)
# keybind: Drishya/everywhere:normal | , | Seek back 10 seconds
# keybind: Drishya/everywhere:normal | > | Play the next video
# keybind: Drishya/everywhere:normal | < | Play the previous video
# keybind: Drishya/everywhere:normal | = | Raise the system volume (back as it was when the window closes)
# keybind: Drishya/everywhere:normal | - | Lower the system volume
# keybind: Drishya/everywhere:normal | Ctrl+= | Raise the screen brightness (back as it was when the window closes)
# keybind: Drishya/everywhere:normal | Ctrl+- | Lower the screen brightness
# keybind: Drishya/everywhere:normal | m | Toggle mute
# keybind: Drishya/everywhere:normal | f | Toggle fullscreen (zen: just the video; Esc leaves it too)
# keybind: Drishya/everywhere:normal | t | Toggle theater mode (the video without the side panel)
# keybind: Drishya/everywhere:normal | z | Switch to the mini player (picture-in-picture)
# keybind: Drishya/everywhere:normal | c | Cycle subtitles (off, then each language)
# keybind: Drishya/everywhere:normal | # | Cycle the audio track
# keybind: Drishya/everywhere:normal | [ | Slow down playback (0.25× steps)
# keybind: Drishya/everywhere:normal | ] | Speed up playback (0.25× steps)
# keybind: Drishya/everywhere:normal | \ | Reset playback speed to normal
# keybind: Drishya/everywhere:normal | { | Jump to the previous chapter
# keybind: Drishya/everywhere:normal | } | Jump to the next chapter
# keybind: Drishya/everywhere:normal | S | Start the video over from the beginning
# keybind: Drishya/everywhere:normal | M | Toggle autoplay (related videos or the next episode after yours)
# keybind: Drishya/everywhere:normal | D | Save the playing video to your disk with subtitles (download)
# keybind: Drishya/everywhere:normal | V | Select several videos (visual mode)
# keybind: Drishya/everywhere:normal | u | Restore the last queue change (undo)
# keybind: Drishya/everywhere:normal | Ctrl+r | Restore an undone queue change (redo)
# keybind: Drishya/everywhere:normal | Q | Open the settings menu (quality, speed, subtitles, audio, download)
# keybind: Drishya/everywhere:normal | r | Refresh the lists (Library: reload the folders)
# keybind: Drishya/everywhere:normal | / | Open the search panel (YouTube, your videos, history, links, : commands)
# keybind: Drishya/everywhere:normal | o | Open the search panel to paste a link or file path
# keybind: Drishya/everywhere:normal | : | Run a command (:seek 1:30, :speed 1.5…)
# keybind: Drishya/everywhere:normal | ? | Show every key of this tab
# keybind: Drishya/everywhere:normal | q | Close the window (pauses; z keeps a mini player)
# keybind: Drishya/everywhere:normal | Esc | Leave fullscreen, go back, or close the window
# keybind: Drishya/everywhere:normal | i | Show where video info moved (Space i; for one release)
# keybind: Drishya/everywhere:normal | 0 | Show where the tab numbers moved (H / L, Space t; for one release)
# keybind: Drishya/everywhere:normal | Space Space | Open the palette (every action of this tab, fuzzy)
# keybind: Drishya/everywhere:normal | Space ? | Show every key of this tab
# keybind: Drishya/everywhere:normal | Space q | Close the window (pauses)
# keybind: Drishya/everywhere:normal | Space t w | Switch to Watch (the video)
# keybind: Drishya/everywhere:normal | Space t u | Switch to Up next (the queue)
# keybind: Drishya/everywhere:normal | Space t l | Switch to your video library
# keybind: Drishya/everywhere:normal | Space t h | Switch to your history (continue watching)
# keybind: Drishya/everywhere:normal | Space t d | Switch to downloads
# keybind: Drishya/everywhere:normal | Space u f | Toggle fullscreen (zen)
# keybind: Drishya/everywhere:normal | Space u t | Toggle theater mode
# keybind: Drishya/everywhere:normal | Space u m | Switch to the mini player
# keybind: Drishya/everywhere:normal | Space c c | Cycle subtitles
# keybind: Drishya/everywhere:normal | Space c a | Cycle the audio track
# keybind: Drishya/everywhere:normal | Space p a | Toggle autoplay
# keybind: Drishya/everywhere:normal | Space p s | Start the video over from the beginning
# keybind: Drishya/everywhere:normal | Space p z | Toggle the sleep timer (pauses in 30 min)
# keybind: Drishya/everywhere:normal | Space , | Open the settings menu (quality, speed, subtitles, audio, download)
# keybind: Drishya/everywhere:normal | Space y y | Copy the playing video's title
# keybind: Drishya/everywhere:normal | Space y l | Copy the playing video's link (or file path)
# keybind: Drishya/everywhere:normal | Space f f | Search everything
# keybind: Drishya/everywhere:normal | Space f y | Search YouTube
# keybind: Drishya/everywhere:normal | Space f v | Search your videos
# keybind: Drishya/everywhere:normal | Space f h | Search your history
# keybind: Drishya/everywhere:normal | Space f c | Search the : commands
# keybind: Drishya/everywhere:normal | Space x d | Save the video to your disk (download)
# keybind: Drishya/everywhere:normal | Space i | Show the video's title and link
# keybind: Drishya/everywhere:normal | Space g p | Go to the video that's playing (in Up next)
# keybind: Drishya/everywhere:normal | Space o b | Open the playing video's page in the browser
# keybind: Drishya/everywhere:normal | Space r | Refresh the lists (Library: reload the folders)
# keybind: Drishya/everywhere:normal | Space d c | Clear Up next (asks first; u brings it back)
# keybind: Drishya/watch:normal | h | Seek back 5 seconds (3h = 15 s)
# keybind: Drishya/watch:normal | l | Seek forward 5 seconds
# keybind: Drishya/watch:normal | Tab | Switch the side panel (up next, chapters, info)
# keybind: Drishya/watch:normal | Enter | Play the side panel's video, or jump to its chapter
# keybind: Drishya/up next:normal | d d | Remove the video from the queue (2dd: two; u undoes it)
# keybind: Drishya/up next:normal | x | Remove the video from the queue (like dd; u undoes it)
# keybind: Drishya/up next:normal | d G | Remove every video from here to the end (u undoes it)
# keybind: Drishya/up next:normal | y y | Copy the video (yank)
# keybind: Drishya/up next:normal | g p | Paste removed or copied videos below
# keybind: Drishya/up next:normal | g P | Paste removed or copied videos above
# keybind: Drishya/up next:normal | J | Move the video down
# keybind: Drishya/up next:normal | K | Move the video up
# keybind: Drishya/up next:normal | A | Move the video to play next
# keybind: Drishya/up next:normal | D | Save the video to your disk (download)
# keybind: Drishya/up next:normal | n | Jump to the next match (after a search here)
# keybind: Drishya/up next:normal | N | Jump to the previous match
# keybind: Drishya/up next:normal | Space d d | Remove the video from the queue (u undoes it)
# keybind: Drishya/library:normal | h | Move left in the grid
# keybind: Drishya/library:normal | l | Move right in the grid
# keybind: Drishya/library:normal | Enter | Open the folder or play the video (the rest of the folder after it)
# keybind: Drishya/library:normal | Backspace | Go up a folder
# keybind: Drishya/library:normal | a | Add to the end of the queue
# keybind: Drishya/library:normal | A | Add to play next
# keybind: Drishya/library:normal | R | Reload the folders
# keybind: Drishya/library:normal | Space a a | Add to the end of the queue
# keybind: Drishya/library:normal | Space a n | Add to play next
# keybind: Drishya/youtube:normal | Enter | Play the result
# keybind: Drishya/youtube:normal | a | Add the result to the end of the queue
# keybind: Drishya/youtube:normal | A | Add the result to play next
# keybind: Drishya/youtube:normal | D | Save the result to your disk (download)
# keybind: Drishya/youtube:normal | Space a a | Add the result to the end of the queue
# keybind: Drishya/youtube:normal | Space a n | Add the result to play next
# keybind: Drishya/history:normal | Enter | Resume the video where you left it
# keybind: Drishya/history:normal | a | Add the video to the end of the queue
# keybind: Drishya/history:normal | A | Add the video to play next
# keybind: Drishya/history:normal | d d | Forget the video (removes it from the history; asks first)
# keybind: Drishya/history:normal | x | Forget the video (like dd; asks first)
# keybind: Drishya/history:normal | D | Save the video to your disk (download)
# keybind: Drishya/history:normal | n | Jump to the next match (after a search here)
# keybind: Drishya/history:normal | N | Jump to the previous match
# keybind: Drishya/history:normal | Space a a | Add the video to the end of the queue
# keybind: Drishya/history:normal | Space a n | Add the video to play next
# keybind: Drishya/history:normal | Space d d | Forget the video (asks first)
# keybind: Drishya/downloads:normal | Enter | Play the saved video
# keybind: Drishya/downloads:normal | R | Retry a failed download
# keybind: Drishya/downloads:normal | x | Cancel a download in progress
# keybind: Drishya/downloads:normal | d d | Delete the saved file (asks first)
# keybind: Drishya/downloads:normal | Space x r | Retry a failed download
# keybind: Drishya/downloads:normal | Space x c | Cancel a download in progress
# keybind: Drishya/downloads:normal | Space d d | Delete the saved file (asks first)
# keybind: Drishya/up next:visual | d | Remove the selected videos (u undoes it)
# keybind: Drishya/up next:visual | x | Remove the selected videos (like d; u undoes it)
# keybind: Drishya/up next:visual | y | Copy the selected videos (yank)
# keybind: Drishya/up next:visual | V | Leave visual mode
# keybind: Drishya/up next:visual | Esc | Leave visual mode
# keybind: Drishya/history:visual | d | Forget the selected videos (asks first)
# keybind: Drishya/history:visual | x | Forget the selected videos (like d; asks first)
# keybind: Drishya/history:visual | a | Add the selected videos to the end of the queue
# keybind: Drishya/history:visual | A | Add the selected videos to play next
# keybind: Drishya/history:visual | V | Leave visual mode
# keybind: Drishya/history:visual | Esc | Leave visual mode
# keybind: Drishya/youtube:visual | a | Add the selected results to the end of the queue
# keybind: Drishya/youtube:visual | A | Add the selected results to play next
# keybind: Drishya/youtube:visual | D | Save the selected results (download)
# keybind: Drishya/youtube:visual | V | Leave visual mode
# keybind: Drishya/youtube:visual | Esc | Leave visual mode
# keybind: Drishya/fullscreen:normal | Space | Toggle play / pause (zen has no leader)
# keybind: Drishya/settings:normal | j | Move down through the settings menu
# keybind: Drishya/settings:normal | k | Move up through the settings menu
# keybind: Drishya/settings:normal | l | Open the setting or choose it (Enter too)
# keybind: Drishya/settings:normal | h | Go back in the settings menu (Backspace too)
# keybind: Drishya/settings:normal | Esc | Close the settings menu (Q and q too)
# keybind: Drishya/search:insert | Tab | Switch where to look (all, YouTube, your videos, history, commands)
# keybind: Drishya/search:insert | Shift+Tab | Switch back where to look
# keybind: Drishya/search:insert | Ctrl+j | Move down through the results while typing
# keybind: Drishya/search:insert | Ctrl+k | Move up through the results while typing
# keybind: Drishya/search:insert | Enter | Play the result (a command: run it)
# keybind: Drishya/search:insert | Ctrl+Enter | Play the result next
# keybind: Drishya/search:insert | Shift+Enter | Add the result to Up next
# keybind: Drishya/search:insert | Ctrl+d | Download the result
# keybind: Drishya/search:insert | Ctrl+u | Clear the search box
# keybind: Drishya/search:insert | Ctrl+x | Clear recent searches
# keybind: Drishya/search:insert | Esc | Close the search panel
# keybind: Drishya/sign in:insert | Enter | Sign in and play (from the password field)
# keybind: Drishya/sign in:insert | Tab | Move between the username and password fields
# keybind: Drishya/sign in:insert | Ctrl+b | Sign in with your browser's login instead (sites yt-dlp plays)
# keybind: Drishya/sign in:insert | Ctrl+s | Toggle remembering the login in your keyring
# keybind: Drishya/sign in:insert | Esc | Cancel signing in
# keybind: Drishya/palette:insert | Ctrl+j | Move down through the actions (Down too)
# keybind: Drishya/palette:insert | Ctrl+k | Move up through the actions (Up too)
# keybind: Drishya/palette:insert | Enter | Run the action
# keybind: Drishya/palette:insert | Esc | Close the palette
# keybind: Drishya/leader:normal | Esc | Cancel a pending key or count (Space, g, d…)
# keybind-group: Drishya/everywhere | Space c | Captions
# keybind-group: Drishya/everywhere | Space p | Playback
# keybind-group: Drishya/everywhere | Space x | Downloads
# --- end of keybind lines ---
