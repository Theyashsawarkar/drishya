"""The head start (ytcache): answers from the cache, never keeps a login."""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drishya import ytcache

LINK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
ARGS = ["--no-warnings", "-J", "--flat-playlist", "--format", "bv*+ba/b"]


class YtCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.patches = [mock.patch.object(ytcache, "DIR", d), mock.patch.object(ytcache, "TEMPLATE", os.path.join(d, "args.json"))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_split(self):
        self.assertEqual(ytcache.split([*ARGS, "--", LINK]), (ARGS, LINK))
        self.assertEqual(ytcache.split(["--version"]), (None, None))

    def test_logins_are_private(self):
        self.assertTrue(ytcache.private([*ARGS, "--username", "me", "--password", "x"]))
        self.assertTrue(ytcache.private([*ARGS, "--cookies-from-browser=firefox"]))
        self.assertFalse(ytcache.private(ARGS))

    def test_hit_answers_without_ytdlp(self):
        path = ytcache._path(ARGS, LINK)
        ytcache._write(path, b'{"id": "dQw4w9WgXcQ"}')
        out = io.BytesIO()
        with mock.patch.object(ytcache, "_ask", side_effect=AssertionError("asked yt-dlp")):
            self.assertEqual(ytcache.shim([*ARGS, "--", LINK], out), 0)
        self.assertEqual(out.getvalue(), b'{"id": "dQw4w9WgXcQ"}')

    def test_miss_asks_keeps_it_and_the_way_it_was_asked(self):
        out = io.BytesIO()
        with mock.patch.object(ytcache, "_ask", return_value=b'{"id": "x"}') as ask:
            self.assertEqual(ytcache.shim([*ARGS, "--", LINK], out), 0)
            ask.assert_called_once_with(ARGS, LINK)
        self.assertTrue(ytcache.fresh(ytcache._path(ARGS, LINK)))
        with open(ytcache.TEMPLATE) as f:
            self.assertEqual(json.load(f), ARGS)

    def test_a_login_is_neither_kept_nor_remembered(self):
        argv = [*ARGS, "--username", "me", "--password", "x", "--", LINK]
        with mock.patch.object(ytcache, "ytdlp", return_value="/usr/bin/yt-dlp"), \
                mock.patch.object(ytcache.os, "execv", side_effect=SystemExit(0)) as ex:
            with self.assertRaises(SystemExit):
                ytcache.shim(argv, io.BytesIO())
            ex.assert_called_once()
        self.assertEqual([n for n in os.listdir(self.tmp.name)], [])

    def test_stale_answers_are_not_used(self):
        path = ytcache._path(ARGS, LINK)
        ytcache._write(path, b"{}")
        old = time.time() - ytcache.FRESH - 5
        os.utime(path, (old, old))
        self.assertFalse(ytcache.fresh(path))

    def test_prefetch_copies_how_mpv_asked(self):
        self.assertFalse(ytcache.prefetch(LINK))          # mpv hasn't asked yet: nothing to copy
        ytcache._write(ytcache.TEMPLATE, json.dumps(ARGS).encode())
        with mock.patch.object(ytcache, "_ask", return_value=b'{"id": "y"}') as ask:
            self.assertTrue(ytcache.prefetch(LINK))
            self.assertTrue(ytcache.prefetch(LINK))       # the second time: already there
            ask.assert_called_once_with(ARGS, LINK)


if __name__ == "__main__":
    unittest.main()
