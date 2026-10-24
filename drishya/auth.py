"""Signing in to what you play: servers that want a username and password
(HTTP auth, for a video file or an HLS/DASH stream), and sites yt-dlp
plays that need an account (your browser's login, or a username and
password). Logins you ask to remember go to your keyring through libsecret
(secret-tool), never to a file of drishya's; the rest live only in memory
until drishya quits."""
import base64
import configparser
import logging
import os
import shutil
import subprocess
import urllib.parse

log = logging.getLogger("drishya.auth")
SERVICE = "drishya"


def host_of(url):
    """"https://cdn.example.com:8443" for any URL on that server."""
    u = urllib.parse.urlparse(url)
    port = f":{u.port}" if u.port else ""
    return f"{u.scheme}://{u.hostname or ''}{port}"


def split_userinfo(url):
    """(url without user:pass@, user, password): credentials typed into a
    link are taken out of it, so they never reach the history or the queue."""
    u = urllib.parse.urlparse(url)
    if not u.username and not u.password:
        return url, None, None
    netloc = u.hostname or ""
    if u.port:
        netloc += f":{u.port}"
    clean = urllib.parse.urlunparse(u._replace(netloc=netloc))
    return clean, urllib.parse.unquote(u.username or ""), urllib.parse.unquote(u.password or "")


def with_userinfo(url, user, password):
    u = urllib.parse.urlparse(url)
    netloc = f"{urllib.parse.quote(user, safe='')}:{urllib.parse.quote(password, safe='')}@{u.hostname or ''}"
    if u.port:
        netloc += f":{u.port}"
    return urllib.parse.urlunparse(u._replace(netloc=netloc))


def basic_header(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Authorization: Basic {token}"


def keyring_available():
    return shutil.which("secret-tool") is not None


def lookup(host):
    """(user, password) remembered for host in the keyring, or None."""
    if not keyring_available():
        return None
    try:
        r = subprocess.run(["secret-tool", "search", "--unlock", "service", SERVICE, "host", host],
                           capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError) as e:
        log.warning("keyring: %s", e)
        return None
    user = secret = None
    for line in (r.stdout + r.stderr).splitlines():
        k, _, v = line.partition(" = ")
        if k.strip() == "attribute.user":
            user = v
        elif k.strip() == "secret":
            secret = v
    return (user or "", secret) if secret is not None else None


def remember(host, user, password):
    if not keyring_available():
        return False
    try:
        r = subprocess.run(["secret-tool", "store", "--label", f"drishya: {host}", "service", SERVICE,
                            "host", host, "user", user], input=password, text=True, capture_output=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError) as e:
        log.warning("keyring: %s", e)
        return False
    if r.returncode != 0:
        log.warning("keyring: %s", r.stderr.strip())
    return r.returncode == 0


def forget(host):
    if keyring_available():
        subprocess.run(["secret-tool", "clear", "service", SERVICE, "host", host], capture_output=True, timeout=10)


def default_browser():
    """The browser whose login yt-dlp borrows (its cookies): your default
    one, if yt-dlp can read it."""
    known = {"chrome": "chrome", "chromium": "chromium", "brave": "brave", "firefox": "firefox", "zen": "firefox",
             "librewolf": "firefox", "vivaldi": "vivaldi", "opera": "opera", "edge": "edge"}
    desktop = ""
    try:
        desktop = subprocess.run(["xdg-settings", "get", "default-web-browser"], capture_output=True, text=True,
                                 timeout=5).stdout.strip().lower()
    except (OSError, subprocess.TimeoutExpired):
        pass
    if not desktop:
        cfg = configparser.ConfigParser(strict=False, interpolation=None)
        cfg.read(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "mimeapps.list"))
        desktop = cfg.get("Default Applications", "x-scheme-handler/https", fallback="").lower()
    for name, ytdl in known.items():
        if name in desktop:
            return ytdl
    return "firefox"


def needs_login(text):
    """Does an mpv/yt-dlp error say the server wants a login? Returns
    "http" (a username and password for the server), "site" (an account
    on a site yt-dlp plays) or None."""
    t = text.lower()
    if "401" in t or "unauthorized" in t or "403 forbidden" in t or "http error 403" in t:
        # yt-dlp's [generic] extractor is a plain server too: its login is the server's
        site = ("ytdl" in t or "youtube-dl" in t or "yt-dlp" in t) and "[generic]" not in t
        return "site" if site else "http"
    if any(w in t for w in ("sign in to confirm", "login required", "requires authentication", "use --cookies",
                            "account", "members-only", "private video", "--username")) and ("ytdl" in t or "error" in t):
        return "site"
    return None
