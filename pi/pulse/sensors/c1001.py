"""DFRobot C1001 frame parser and serial reader (parser and reader filled in by T6)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class C1001Reading:
    """Latest C1001 report. Raw values: fusion applies the sanity ranges, so a reader may pass through
    whatever it parsed. None means the sensor gave no reading (never a made-up number)."""
    t: float
    presence: bool
    moving: bool | None = None
    breath_rpm: int | None = None
    heart_bpm: int | None = None
