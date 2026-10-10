"""HLK-LD2450 frame parser and serial reader (parser and reader filled in by T5)."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Ld2450Target:
    """One radar detection, already in contract conventions: x negative = holder's left,
    y straight out (>= 0), speed negative = approaching. Units: mm and cm/s."""
    x_mm: int
    y_mm: int
    speed_cms: int
    resolution_mm: int = 0


@dataclass(frozen=True)
class Ld2450Frame:
    """One decoded frame: up to 3 targets (empty slots skipped), stamped with its arrival time."""
    t: float
    targets: list[Ld2450Target] = field(default_factory=list)
