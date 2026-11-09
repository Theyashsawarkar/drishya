"""The keymap: generated docs up to date, every key reachable, the Space
grammar kept, every action runnable. No GTK."""
import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = next(p.name for p in ROOT.iterdir() if (p / "keymap.py").exists())
sys.path.insert(0, str(ROOT))
keymap = __import__(f"{PKG}.keymap", fromlist=["x"])
keys = __import__(f"{PKG}.keys", fromlist=["x"])
WINDOW = (ROOT / PKG / "window.py").read_text()


class Keys(unittest.TestCase):
    def test_generated_docs_are_up_to_date(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "keybinds.py"), "--check"], capture_output=True, check=False,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_vendored_keys_has_its_header(self):
        first = (ROOT / PKG / "keys.py").read_text().splitlines()[0]
        self.assertRegex(first, r"^# Vendored from Vyom's vyom/keys\.py v[\d.]+ \(sha256 [0-9a-f]{16}\)")
        self.assertIn(f"v{keys.KEYS_VERSION} ", first)

    def every_keymap(self):
        tabs = list(keymap.TABS) + ["youtube"]
        for tab in tabs:
            for visual in (False, True):
                yield tab, visual, keys.Keymap(keymap.binds_for(tab, visual), keymap.GROUPS)

    def test_no_key_hides_behind_a_longer_one(self):
        # a bind that is also the start of a longer one would wait forever
        for tab, visual, km in self.every_keymap():
            for seq in km.table:
                if seq == "<":   # keys.py's own "<" vs <CR> problem: window.py runs "<" at once
                    continue
                _exact, longer = km.lookup(seq)
                self.assertFalse(longer, f"{keys.spell(seq)!r} on {tab} (visual={visual}) starts a longer key")

    def test_own_groups_use_free_letters(self):
        for prefix in keymap.GROUPS:
            self.assertEqual(len(prefix), 2)
            self.assertIn(prefix[1], keys.FREE, f"Space {prefix[1]} is reserved")

    def test_reserved_groups_keep_their_meaning(self):
        # Space t tabs, y copy, f find, d delete… : spot-check the verb of each leader key
        verbs = {"t": ("Switch",), "y": ("Copy",), "f": ("Search",), "d": ("Remove", "Delete", "Clear", "Forget"),
                 "a": ("Add", "Move"), "u": ("Toggle", "Switch"), "o": ("Open",), "g": ("Go",), "q": ("Close",),
                 "r": ("Refresh",), ",": ("Open",), " ": ("Open",), "?": ("Show",)}
        for b in keymap.ALL:
            if b.seq.startswith(" ") and len(b.seq) > 1 and b.desc and b.seq[1] in verbs:
                self.assertTrue(b.desc.startswith(verbs[b.seq[1]]), f"{keys.spell(b.seq)}: {b.desc}")

    def test_descriptions_start_with_a_verb(self):
        for b in keymap.ALL + keymap.ALL_VISUAL + [b for _s, _m, bs in keymap.PANELS for b in bs]:
            if b.desc and not b.hidden:
                self.assertTrue(b.desc[0].isupper() and " " in b.desc, b.desc)

    def test_every_action_runs(self):
        for b in keymap.ALL + keymap.ALL_VISUAL:
            kind, _, arg = b.action.partition("|note:")[0].partition(":")
            self.assertIn(kind, ("do", "tab", "call", "moved"), b.action)
            if kind == "call":
                self.assertRegex(WINDOW, rf"def k_{re.escape(arg.split(':')[0])}\(", b.action)
            if kind == "tab" and arg not in ("+1", "-1"):
                self.assertIn(arg, keymap.TABS)

    def test_space_is_never_play(self):
        km = keys.Keymap(keymap.binds_for("queue"), keymap.GROUPS)
        exact, longer = km.lookup(" ")
        self.assertIsNone(exact)
        self.assertTrue(longer)
        self.assertEqual(km.table["p"].action, "call:toggle_play")

    def test_counts_and_sequences(self):
        km = keys.Keymap(keymap.binds_for("queue"), keymap.GROUPS)
        m = keys.Machine()
        for t in "12":
            self.assertEqual(m.feed(km, t).kind, "pending")
        self.assertEqual(m.feed(km, "d").kind, "pending")
        r = m.feed(km, "d")
        self.assertEqual((r.kind, r.bind.action, r.count), ("run", "do:dd", 12))
        for t in " p":
            self.assertEqual(m.feed(km, t).kind, "pending")
        self.assertEqual(m.feed(km, "<Esc>").kind, "cancel")
        self.assertFalse(m.busy())

    def test_visual_d_acts_at_once(self):
        km = keys.Keymap(keymap.binds_for("queue", visual=True), keymap.GROUPS)
        r = keys.Machine().feed(km, "d")
        self.assertEqual((r.kind, r.bind.action), ("run", "do:dd"))


if __name__ == "__main__":
    unittest.main()


class TabSwitchDropsWhatWaits(unittest.TestCase):
    """Space then Ctrl+Tab, or a question (Space d c) then Ctrl+Tab: the new
    tab must not finish the old sequence, nor take a y as the answer."""

    def body(self, name):
        m = re.search(rf"\n    def {name}\(self.*?(?=\n    def |\Z)", WINDOW, re.DOTALL)
        self.assertIsNotNone(m, name)
        return m.group(0)

    def test_switch_and_hide_drop_pending(self):
        self.assertIn("self.drop_pending()", self.body("switch"))
        self.assertIn("self.drop_pending()", self.body("hide_window"))

    def test_drop_pending_clears_everything(self):
        b = self.body("drop_pending")
        for what in ("self.m.reset()", "self.which.cancel()", "self.confirm_cb = None", "self.palette.close()",
                     "self.help.set_visible(False)"):
            self.assertIn(what, b)
