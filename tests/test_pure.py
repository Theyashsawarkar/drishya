"""The parts of drishya that don't need GTK or a player: config checks,
resume and history, the library's names and order, YouTube and link
helpers, signing in. (CI has no GTK: nothing here may import it.)"""
import base64
import os
import re
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from drishya import auth, config, library, store, util, youtube  # noqa: E402


class Config(unittest.TestCase):
    def load(self, text):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "config.toml")
        with open(p, "w") as f:
            f.write(text)
        return config.load(p)

    def test_defaults_without_a_file(self):
        c = config.load("/nonexistent/config.toml")
        self.assertEqual(c["quality"], 1080)
        self.assertTrue(c["autoplay"])

    def test_bad_values_fall_back(self):
        c = self.load('[drishya]\nquality = "high"\nautoplay = 1\nvideo_dirs = "~/V"\nopacity = "x"\n')
        self.assertEqual(c["quality"], 1080)
        self.assertIs(c["autoplay"], True)
        self.assertEqual(c["video_dirs"], [os.path.expanduser("~/V")])
        self.assertIsNone(c["opacity"])

    def test_quality_is_clamped(self):
        self.assertEqual(self.load("[drishya]\nquality = 5\n")["quality"], 144)

    def test_format_caps_height_and_skips_av1(self):
        f = config.ytdl_format(720)
        self.assertIn("height<=720", f)
        self.assertIn("vcodec!^=av01", f)


class Resume(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(store.key({"yt": "abcdefghijk"}), "yt:abcdefghijk")
        self.assertEqual(store.key({"url": "https://x/a.m3u8"}), "url:https://x/a.m3u8")
        self.assertTrue(store.key({"file": "/tmp/a.mkv"}).startswith("file:/"))

    def test_resume_only_in_the_middle(self):
        self.assertEqual(store.resume_at(None), 0)
        self.assertEqual(store.resume_at({"pos": 5, "duration": 600}), 0)        # barely started
        self.assertEqual(store.resume_at({"pos": 300, "duration": 600}), 300)
        self.assertEqual(store.resume_at({"pos": 590, "duration": 600}), 0)      # the credits: finished
        self.assertEqual(store.resume_at({"pos": 300, "duration": 600, "finished": True}), 0)

    def test_history_round_trip(self):
        d = tempfile.mkdtemp()
        s = store.Store(d)
        it = {"yt": "abcdefghijk", "title": "A video", "channel": "C"}
        s.touch(it, pos=120, duration=600)
        s.flush()
        s2 = store.Store(d)
        e = s2.entry(it)
        self.assertEqual(e["pos"], 120)
        self.assertFalse(e["finished"])
        self.assertEqual([k for k, _ in s2.unfinished()], ["yt:abcdefghijk"])
        s2.forget("yt:abcdefghijk")
        self.assertIsNone(s2.entry(it))

    def test_downloads_need_the_file(self):
        d = tempfile.mkdtemp()
        s = store.Store(d)
        path = os.path.join(d, "v.mkv")
        open(path, "w").close()
        s.add_download("https://x/a.m3u8", path)
        self.assertEqual(s.downloaded("https://x/a.m3u8"), path)
        os.remove(path)
        self.assertIsNone(s.downloaded("https://x/a.m3u8"))
        self.assertIsNone(s.downloaded(None))


class Library(unittest.TestCase):
    def test_names(self):
        self.assertEqual(library.nice_title("The.Show.S01E02.1080p.WEB-DL.x264.mkv"), "The Show S01E02")
        self.assertEqual(library.nice_title("Holiday video.mp4"), "Holiday video")
        self.assertEqual(library.episode("show.s02e10.mkv"), (2, 10))
        self.assertEqual(library.episode("Show 1x05.avi"), (1, 5))
        self.assertIsNone(library.episode("film.mkv"))

    def test_natural_order_and_next_episode(self):
        d = tempfile.mkdtemp()
        for n in (1, 2, 10, 9):
            open(os.path.join(d, f"Episode {n}.mkv"), "w").close()
        open(os.path.join(d, "notes.txt"), "w").close()
        os.mkdir(os.path.join(d, ".hidden"))
        folders, videos = library.listdir(d)
        self.assertEqual(folders, [])
        self.assertEqual([os.path.basename(v["file"]) for v in videos],
                         ["Episode 1.mkv", "Episode 2.mkv", "Episode 9.mkv", "Episode 10.mkv"])
        self.assertEqual(os.path.basename(library.next_in_folder(os.path.join(d, "Episode 9.mkv"))["file"]),
                         "Episode 10.mkv")
        self.assertIsNone(library.next_in_folder(os.path.join(d, "Episode 10.mkv")))

    def test_hls_playlists_are_videos(self):
        self.assertTrue(library.is_video("stream.m3u8"))


class YouTube(unittest.TestCase):
    def test_video_ids(self):
        for url in ("https://www.youtube.com/watch?v=jNQXAC9IVRw&t=3", "https://youtu.be/jNQXAC9IVRw",
                    "https://youtube.com/shorts/jNQXAC9IVRw", "jNQXAC9IVRw"):
            self.assertEqual(youtube.video_id(url), "jNQXAC9IVRw", url)
        self.assertIsNone(youtube.video_id("https://example.com/video.mp4"))

    def test_one_line(self):
        self.assertEqual(youtube.one_line("TopX English • 6.5B views\n\n\n..."), "TopX English • 6.5B views ...")

    def test_subtitles_are_real_captions_not_translations(self):
        # yt-dlp matches each pattern with re.I and fullmatch
        pats = [p for p in youtube.sub_patterns("en,hi").split(",") if not p.startswith("-")]

        def wanted(lang):
            return any(re.compile(p, re.I).fullmatch(lang) for p in pats)
        for ok in ("en", "en-US", "en-GB", "en-orig", "hi", "hi-IN"):
            self.assertTrue(wanted(ok), ok)
        es = [p for p in youtube.sub_patterns("es").split(",") if not p.startswith("-")]
        self.assertTrue(any(re.compile(p, re.I).fullmatch("es-419") for p in es))   # Latin American Spanish
        for bad in ("en-de", "en-en", "en-zh-Hans", "fr", "hi-en"):
            self.assertFalse(wanted(bad), bad)

    def test_counts(self):
        self.assertEqual(youtube.views(1_234_567), "1.2M views")
        self.assertEqual(youtube.views(1), "1 view")
        self.assertEqual(youtube.ago(time.time() - 3 * 86400), "3 days ago")


class Links(unittest.TestCase):
    def test_streams(self):
        self.assertTrue(util.is_stream_url("https://cdn.example.com/live/master.m3u8"))
        self.assertTrue(util.is_stream_url("rtmp://example.com/live"))
        self.assertFalse(util.is_stream_url("lofi beats to study"))
        self.assertEqual(util.stream_title("https://cdn.example.com:8443/live/index.m3u8"),
                         "cdn.example.com:8443 · index.m3u8")
        self.assertEqual(util.dl_key({"url": "https://x/a.m3u8"}), "https://x/a.m3u8")
        self.assertEqual(util.fmt_time(3725), "1:02:05")

    def test_mpv_quoting_survives_commas_and_equals(self):
        from drishya.mpv import quote
        self.assertEqual(quote("p,a=ss"), "%6%p,a=ss")
        self.assertEqual(quote("ü"), "%2%ü")   # bytes, not characters


class SignIn(unittest.TestCase):
    def test_credentials_leave_the_link(self):
        url, user, pw = auth.split_userinfo("https://bob:p%40ss@cdn.example.com:8443/a.m3u8")
        self.assertEqual((url, user, pw), ("https://cdn.example.com:8443/a.m3u8", "bob", "p@ss"))
        self.assertEqual(auth.split_userinfo("https://x/a.m3u8"), ("https://x/a.m3u8", None, None))
        back = auth.with_userinfo(url, user, pw)
        self.assertEqual(auth.split_userinfo(back), (url, user, pw))

    def test_basic_header(self):
        h = auth.basic_header("demo", "p,a=ss")
        self.assertEqual(base64.b64decode(h.split()[-1]).decode(), "demo:p,a=ss")

    def test_what_needs_a_login(self):
        self.assertEqual(auth.needs_login("ffmpeg: http: HTTP error 401 Unauthorized"), "http")
        self.assertEqual(auth.needs_login("ytdl_hook: ERROR: [generic] master: HTTP Error 401: Unauthorized"), "http")
        self.assertEqual(auth.needs_login("ytdl_hook: ERROR: [vimeo] 1: This video requires authentication"), "site")
        self.assertIsNone(auth.needs_login("ffmpeg: h264: Missing reference picture"))

    def test_host(self):
        self.assertEqual(auth.host_of("https://cdn.example.com:8443/a/b.m3u8"), "https://cdn.example.com:8443")


if __name__ == "__main__":
    unittest.main()
