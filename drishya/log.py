"""Logging for drishya: plain lines on stderr, nothing else.

Whatever starts the daemon decides where stderr goes: a systemd unit or
`systemd-run` sends it to the journal (`journalctl --user -u drishya`), a
terminal shows it. So there's no log file to find or rotate. When stderr
is the journal, each line carries its syslog level (`<3>` error...), so
`journalctl -p warning` finds real problems.

Any module logs with the standard library, no import from here needed:

    import logging
    log = logging.getLogger("drishya.lyrics")
    log.warning("cliphist failed: %s", err)      # or log.exception(...)

DRISHYA_DEBUG=1 shows debug messages too.
"""
import logging
import os
import sys
import threading

LEVELS = {logging.CRITICAL: 2, logging.ERROR: 3, logging.WARNING: 4, logging.INFO: 6, logging.DEBUG: 7}


def to_journal():
    """Is stderr the journal? JOURNAL_STREAM alone isn't enough: children
    inherit it after their stderr went elsewhere."""
    stream = os.environ.get("JOURNAL_STREAM", "")
    try:
        st = os.fstat(2)
    except OSError:
        return False
    return stream == f"{st.st_dev}:{st.st_ino}"


class _Format(logging.Formatter):
    def __init__(self, journal):
        super().__init__("%(name)s: %(message)s" if journal else
                         "%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
        self.journal = journal

    def format(self, record):
        text = super().format(record)
        if not self.journal:
            return text
        # The journal already says which tool: drop the name when it's that.
        if record.name == logging.getLogger().name or "." not in record.name:
            text = text.split(": ", 1)[1] if ": " in text else text
        # The level on every line, so a traceback's lines stay an error too.
        level = f"<{LEVELS.get(record.levelno, 6)}>"
        return "\n".join(level + line for line in text.splitlines())


def setup(name="drishya", debug=None):
    """Logs to stderr, and catches what nobody caught: an exception in a
    GTK callback or a thread is logged with its traceback instead of being
    printed bare (or, in a thread, lost)."""
    if debug is None:
        debug = os.environ.get("DRISHYA_DEBUG", "") not in ("", "0")
    root = logging.getLogger()
    if not any(getattr(h, "_drishya", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_Format(to_journal()))
        handler._drishya = True
        root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    log = logging.getLogger(name)

    def unhandled(kind, value, tb):
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, value, tb)
            return
        log.error("unhandled %s: %s", kind.__name__, value, exc_info=(kind, value, tb))

    def unhandled_thread(args):
        if args.exc_type is SystemExit:
            return
        log.error("thread %s died: %s", getattr(args.thread, "name", "?"), args.exc_value,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = unhandled
    threading.excepthook = unhandled_thread
    return log
