"""The Chromium kiosk on the Pi (scripts/kiosk.sh): is it running, and closing it for the UI's EXIT button.

kiosk.sh writes Chromium's pid to $XDG_RUNTIME_DIR/pulse-kiosk.pid and relaunches Chromium whenever it exits,
unless pulse-kiosk.exit exists: then it stops for good (until the next login, or the Pulse menu entry).
"""
import logging
import os
import signal
from pathlib import Path

log = logging.getLogger("pulse.kiosk")


def run_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")


def _pid(d: Path) -> int | None:
    try:
        pid = int((d / "pulse-kiosk.pid").read_text().strip())
        os.kill(pid, 0)         # alive and ours?
        return pid
    except (OSError, ValueError):
        return None


def running(d: Path | None = None) -> bool:
    return _pid(d or run_dir()) is not None


def exit_kiosk(d: Path | None = None) -> bool:
    """Close Chromium and tell kiosk.sh not to relaunch it. False if no kiosk is running."""
    d = d or run_dir()
    pid = _pid(d)
    if pid is None:
        return False
    (d / "pulse-kiosk.exit").touch()
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        log.exception("couldn't stop the kiosk (pid %d)", pid)
        return False
    log.info("kiosk exit requested from the UI")
    return True
