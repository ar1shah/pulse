"""Data sources: anything that can hand fusion the latest LD2450 frame and C1001 reading."""
import logging
import os
import sys
from typing import Protocol

from .sensors.c1001 import C1001Reading
from .sensors.ld2450 import Ld2450Frame, Ld2450Reader
from .state import SensorStatus, Source as SourceName

log = logging.getLogger("pulse.sources")


class Source(Protocol):
    name: SourceName  # becomes Snapshot.source

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def ld2450(self, now: float) -> tuple[Ld2450Frame | None, SensorStatus]:
        """Latest LD2450 frame (None if there is none yet) and the sensor's health."""
        ...

    def c1001(self, now: float) -> tuple[C1001Reading | None, SensorStatus]:
        """Latest C1001 reading (None if there is none yet) and the sensor's health."""
        ...


DEFAULT_LD2450_PORT = "/dev/ttyAMA0"
C1001_BAUD = 115200


class LiveSource:
    """Both real sensors over serial. The C1001 reader is CS2's (sensors/c1001.py, C1001Reader); until it exists,
    or if C1001_PORT is unset, the C1001 side reports offline and the LD2450 side still works."""

    name: SourceName = "live"

    def __init__(self, ld2450_port: str | None = None, c1001_port: str | None = None) -> None:
        self.ld2450_port = ld2450_port or os.environ.get("LD2450_PORT", "").strip() or DEFAULT_LD2450_PORT
        self.c1001_port = (c1001_port if c1001_port is not None else os.environ.get("C1001_PORT", "")).strip()
        self._ld = Ld2450Reader(self.ld2450_port)
        self._c1 = None     # built in start(): its constructor may touch hardware

    def start(self) -> None:
        log.info("live source: LD2450 on %s, C1001 on %s", self.ld2450_port, self.c1001_port or "(C1001_PORT unset)")
        self._ld.start()
        self._c1 = _make_c1001_reader(self.c1001_port)
        if self._c1 is not None:
            try:
                self._c1.start()
            except Exception:
                log.exception("C1001 reader failed to start; C1001 offline")
                self._c1 = None

    def stop(self) -> None:
        self._ld.stop()
        if self._c1 is not None:
            try:
                self._c1.stop()
            except Exception:
                log.exception("C1001 reader failed to stop")

    def ld2450(self, now: float) -> tuple[Ld2450Frame | None, SensorStatus]:
        return self._ld.latest(now)

    def c1001(self, now: float) -> tuple[C1001Reading | None, SensorStatus]:
        if self._c1 is None:
            return None, "offline"
        try:
            return self._c1.latest(now)
        except Exception:
            log.exception("C1001 reader raised; reporting offline")
            return None, "offline"


def _make_c1001_reader(port: str):
    if not port:
        log.warning("C1001_PORT is not set: C1001 offline")
        return None
    try:
        from .sensors.c1001 import C1001Reader  # CS2's reader; may not exist yet
    except ImportError:
        log.warning("C1001Reader not available yet: C1001 offline")
        return None
    try:
        return C1001Reader(port, baud=C1001_BAUD)
    except Exception:
        log.exception("C1001Reader(%r) failed: C1001 offline", port)
        return None


class StubSource:
    """Placeholder for replay until B3 wires in the recordings: both sensors offline."""

    def __init__(self, name: SourceName) -> None:
        self.name = name

    def start(self) -> None:
        log.warning("source %r is a stub for now: both sensors report offline, no targets", self.name)

    def stop(self) -> None:
        pass

    def ld2450(self, now: float) -> tuple[Ld2450Frame | None, SensorStatus]:
        return None, "offline"

    def c1001(self, now: float) -> tuple[C1001Reading | None, SensorStatus]:
        return None, "offline"


def default_source_name() -> str:
    return "sim" if sys.platform == "darwin" else "live"


def make_source(name: str | None = None) -> Source:
    """Build the source named by `name`, else env PULSE_SOURCE, else sim on a Mac and live elsewhere."""
    name = (name or os.environ.get("PULSE_SOURCE") or default_source_name()).strip().lower()
    if name == "sim":
        from .sensors.sim import SimSource  # imported lazily: live on the Pi never needs the sim

        return SimSource.from_env()
    if name == "live":
        return LiveSource()
    if name == "replay":
        return StubSource("replay")
    raise ValueError(f"unknown PULSE_SOURCE {name!r}: expected sim, live or replay")
