"""Data sources: anything that can hand fusion the latest LD2450 frame and C1001 reading."""
import logging
import os
import sys
from typing import Protocol

from .sensors.c1001 import C1001Reading
from .sensors.ld2450 import Ld2450Frame
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


class StubSource:
    """Placeholder for live and replay until later tasks wire in the real readers: both sensors offline."""

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
    if name in ("live", "replay"):
        return StubSource(name)  # type: ignore[arg-type]
    raise ValueError(f"unknown PULSE_SOURCE {name!r}: expected sim, live or replay")
