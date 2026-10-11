"""LOG_RAW: one CSV row per new LD2450 frame, the raw slots next to what fusion shows. Plot: tools/plot_x.py.

LOG_RAW=1 writes recordings/xlog_<time>.csv, LOG_RAW=<path> writes there, unset or 0 is off.
Raw x/y/speed are per sensor slot (s0..s2, blank = empty slot), already in contract signs (X_SIGN applied).
Shown x/y are per track id (id1..id3, blank = no dot), with held_s > 0 while the dot is held undetected.
"""
import csv
import logging
import os
import time
from pathlib import Path

from .sensors.ld2450 import Ld2450Frame
from .state import TARGET_IDS, Snapshot

log = logging.getLogger("pulse.rawlog")

REC_DIR = Path(__file__).resolve().parents[2] / "recordings"
HEADER = (["t", "frame_t"] + [f"s{i}_{k}" for i in range(3) for k in ("x", "y", "v")]
          + [f"id{i}_{k}" for i in TARGET_IDS for k in ("x", "y", "held_s")] + ["locked"])


class RawLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._f = open(path, "a", newline="", buffering=1, encoding="utf-8")     # line buffered: survives a kill
        self._w = csv.writer(self._f)
        if self._f.tell() == 0:
            self._w.writerow(HEADER)
        self._last_t: float | None = None
        self._failed = False

    @classmethod
    def from_env(cls) -> "RawLog | None":
        v = os.environ.get("LOG_RAW", "").strip()
        if v in ("", "0"):
            return None
        path = REC_DIR / time.strftime("xlog_%Y%m%d_%H%M%S.csv") if v == "1" else Path(v)
        try:
            raw = cls(path)
        except OSError:
            log.exception("LOG_RAW: can't open %s; not logging", path)
            return None
        log.info("LOG_RAW: writing %s", path)
        return raw

    def write(self, frame: Ld2450Frame | None, snap: Snapshot) -> None:
        """Never raises: a full disk must not stop the radar."""
        if frame is None or frame.t == self._last_t or self._failed:
            return
        self._last_t = frame.t
        slots = frame.slots or tuple(frame.targets)
        row: list[object] = [f"{snap.t:.3f}", f"{frame.t:.3f}"]
        for i in range(3):
            d = slots[i] if i < len(slots) else None
            row += [d.x_mm, d.y_mm, d.speed_cms] if d is not None else ["", "", ""]
        shown = {t.id: t for t in snap.targets}
        for i in TARGET_IDS:
            t = shown.get(i)
            row += [t.x_mm, t.y_mm, f"{t.last_seen_s:.1f}"] if t is not None else ["", "", ""]
        row.append(snap.vitals.target_id or "")
        try:
            self._w.writerow(row)
        except OSError:
            log.exception("LOG_RAW: write to %s failed; logging stopped", self.path)
            self._failed = True

    def close(self) -> None:
        self._f.close()
