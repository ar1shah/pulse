"""Snapshot dataclasses and the contract validator. Mirrors docs/data-contract.md (v1).

If you change anything here, change docs/data-contract.md and ui/contract.js in the same commit and bump v.
"""
import math
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

CONTRACT_VERSION = 1

MAX_TARGETS = 3
MAX_CONTACTS = 20
TARGET_IDS = (1, 2, 3)

DEFAULT_MAX_RANGE_M = 4.0
DEFAULT_MAX_ANGLE_DEG = 60.0
GATE_RANGE_LIMITS = (1.0, 6.0)
GATE_ANGLE_LIMITS = (15.0, 60.0)

LOCK_CONE_DEG = 20.0
LOCK_MIN_M = 0.4
LOCK_MAX_M = 1.5

BREATH_RANGE = (10, 25)
HEART_RANGE = (45, 150)

HOLD_S = 3.0
STALE_S = 1.0

Source = Literal["sim", "live", "replay"]
Triage = Literal["green", "amber", "gray"]
SensorStatus = Literal["ok", "warming", "stale", "offline", "sim"]

SOURCES: tuple[str, ...] = get_args(Source)
TRIAGES: tuple[str, ...] = get_args(Triage)
SENSOR_STATUSES: tuple[str, ...] = get_args(SensorStatus)
SENSOR_NAMES = ("ld2450", "c1001")

# Tolerances for checking range_m / angle_deg against x_mm / y_mm after rounding (2 dp and 1 dp).
_RANGE_TOL_M = 0.01
_ANGLE_TOL_DEG = 0.1


@dataclass
class Gate:
    max_range_m: float = DEFAULT_MAX_RANGE_M
    max_angle_deg: float = DEFAULT_MAX_ANGLE_DEG

    def to_dict(self) -> dict[str, Any]:
        return {"max_range_m": self.max_range_m, "max_angle_deg": self.max_angle_deg}


@dataclass
class Target:
    id: int
    x_mm: int
    y_mm: int
    speed_cms: int
    moving: bool
    triage: Triage
    locked: bool = False
    last_seen_s: float = 0.0

    @property
    def range_m(self) -> float:
        return math.hypot(self.x_mm, self.y_mm) / 1000

    @property
    def angle_deg(self) -> float:
        return math.degrees(math.atan2(self.x_mm, self.y_mm))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "x_mm": int(round(self.x_mm)),
            "y_mm": int(round(self.y_mm)),
            "range_m": round(self.range_m, 2),
            "angle_deg": round(self.angle_deg, 1),
            "speed_cms": int(round(self.speed_cms)),
            "moving": self.moving,
            "triage": self.triage,
            "locked": self.locked,
            "last_seen_s": round(self.last_seen_s, 1),
        }


@dataclass
class Vitals:
    target_id: int | None = None
    presence: bool = False
    moving: bool | None = None
    breath_rpm: int | None = None
    heart_bpm: int | None = None
    settled: bool = False
    age_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "presence": self.presence,
            "moving": self.moving,
            "breath_rpm": self.breath_rpm,
            "heart_bpm": self.heart_bpm,
            "settled": self.settled,
            "age_s": None if self.age_s is None else round(self.age_s, 1),
        }


@dataclass
class Contact:
    id: int
    first_seen: float
    last_seen: float
    triage: Triage
    last_breath_rpm: int | None = None
    last_heart_bpm: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "first_seen": round(self.first_seen, 2),
            "last_seen": round(self.last_seen, 2),
            "triage": self.triage,
            "last_breath_rpm": self.last_breath_rpm,
            "last_heart_bpm": self.last_heart_bpm,
        }


def _offline_sensors() -> dict[str, SensorStatus]:
    return {name: "offline" for name in SENSOR_NAMES}


@dataclass
class Snapshot:
    t: float
    source: Source
    gate: Gate = field(default_factory=Gate)
    targets: list[Target] = field(default_factory=list)
    vitals: Vitals = field(default_factory=Vitals)
    sensors: dict[str, SensorStatus] = field(default_factory=_offline_sensors)
    contacts: list[Contact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "v": CONTRACT_VERSION,
            "t": round(self.t, 2),
            "source": self.source,
            "gate": self.gate.to_dict(),
            "targets": [t.to_dict() for t in self.targets],
            "vitals": self.vitals.to_dict(),
            "sensors": dict(self.sensors),
            "contacts": [c.to_dict() for c in self.contacts],
        }


# ---- validation -------------------------------------------------------------------------------

_SNAPSHOT_KEYS = ("type", "v", "t", "source", "gate", "targets", "vitals", "sensors", "contacts")
_GATE_KEYS = ("max_range_m", "max_angle_deg")
_TARGET_KEYS = ("id", "x_mm", "y_mm", "range_m", "angle_deg", "speed_cms", "moving", "triage",
                "locked", "last_seen_s")
_VITALS_KEYS = ("target_id", "presence", "moving", "breath_rpm", "heart_bpm", "settled", "age_s")
_CONTACT_KEYS = ("id", "first_seen", "last_seen", "triage", "last_breath_rpm", "last_heart_bpm")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _span(lo: float, hi: float | None) -> str:
    if hi is None and lo == -math.inf:
        return "any"
    if hi is None:
        return f">= {lo:g}"
    if lo == -math.inf:
        return f"<= {hi:g}"
    return f"{lo:g}..{hi:g}"


class _Checker:
    """Collects violations as 'path: message' strings."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def err(self, path: str, msg: str) -> None:
        self.errors.append(f"{path}: {msg}")

    def obj(self, v: Any, path: str, keys: tuple[str, ...]) -> bool:
        """True if v is a dict with exactly `keys`; records missing/unexpected keys either way."""
        if not isinstance(v, dict):
            self.err(path, f"expected object, got {type(v).__name__}")
            return False
        for k in keys:
            if k not in v:
                self.err(f"{path}.{k}", "missing key")
        for k in v:
            if k not in keys:
                self.err(f"{path}.{k}", "unexpected key")
        return True

    def int_in(self, v: Any, path: str, lo: float, hi: float | None = None, nullable: bool = False) -> bool:
        if v is None and nullable:
            return False
        if not _is_int(v):
            self.err(path, f"expected int, got {v!r}")
            return False
        if v < lo or (hi is not None and v > hi):
            self.err(path, f"expected int {_span(lo, hi)}, got {v}")
            return False
        return True

    def num_in(self, v: Any, path: str, lo: float, hi: float | None = None, nullable: bool = False) -> bool:
        if v is None and nullable:
            return False
        if not _is_num(v):
            self.err(path, f"expected number, got {v!r}")
            return False
        if v < lo or (hi is not None and v > hi):
            self.err(path, f"expected number {_span(lo, hi)}, got {v}")
            return False
        return True

    def boolean(self, v: Any, path: str, nullable: bool = False) -> None:
        if v is None and nullable:
            return
        if not isinstance(v, bool):
            self.err(path, f"expected bool, got {v!r}")

    def enum(self, v: Any, path: str, allowed: tuple[str, ...]) -> None:
        if not isinstance(v, str) or v not in allowed:
            self.err(path, f"expected one of {list(allowed)}, got {v!r}")


def _check_gate(c: _Checker, g: Any) -> None:
    if not c.obj(g, "gate", _GATE_KEYS):
        return
    if "max_range_m" in g:
        c.num_in(g["max_range_m"], "gate.max_range_m", *GATE_RANGE_LIMITS)
    if "max_angle_deg" in g:
        c.num_in(g["max_angle_deg"], "gate.max_angle_deg", *GATE_ANGLE_LIMITS)


def _check_target(c: _Checker, t: Any, path: str) -> None:
    if not c.obj(t, path, _TARGET_KEYS):
        return
    pos_ok = True
    if "id" in t:
        c.int_in(t["id"], f"{path}.id", TARGET_IDS[0], TARGET_IDS[-1])
    if "x_mm" in t:
        pos_ok &= c.int_in(t["x_mm"], f"{path}.x_mm", -math.inf)
    if "y_mm" in t:
        pos_ok &= c.int_in(t["y_mm"], f"{path}.y_mm", 0)
    if "range_m" in t:
        pos_ok &= c.num_in(t["range_m"], f"{path}.range_m", 0)
    if "angle_deg" in t:
        pos_ok &= c.num_in(t["angle_deg"], f"{path}.angle_deg", -180, 180)
    if "speed_cms" in t:
        c.int_in(t["speed_cms"], f"{path}.speed_cms", -math.inf)
    if "moving" in t:
        c.boolean(t["moving"], f"{path}.moving")
    if "triage" in t:
        c.enum(t["triage"], f"{path}.triage", TRIAGES)
    if "locked" in t:
        c.boolean(t["locked"], f"{path}.locked")
    if "last_seen_s" in t:
        c.num_in(t["last_seen_s"], f"{path}.last_seen_s", 0)

    # range_m / angle_deg must agree with the position; catches sign-convention and unit bugs.
    if pos_ok and all(k in t for k in ("x_mm", "y_mm", "range_m", "angle_deg")):
        want_range = math.hypot(t["x_mm"], t["y_mm"]) / 1000
        want_angle = math.degrees(math.atan2(t["x_mm"], t["y_mm"]))
        if abs(t["range_m"] - want_range) > _RANGE_TOL_M:
            c.err(f"{path}.range_m", f"{t['range_m']} does not match x_mm/y_mm (expected {want_range:.2f})")
        if abs(t["angle_deg"] - want_angle) > _ANGLE_TOL_DEG:
            c.err(f"{path}.angle_deg", f"{t['angle_deg']} does not match x_mm/y_mm (expected {want_angle:.1f})")


def _check_vitals(c: _Checker, v: Any) -> None:
    if not c.obj(v, "vitals", _VITALS_KEYS):
        return
    if "target_id" in v:
        c.int_in(v["target_id"], "vitals.target_id", TARGET_IDS[0], TARGET_IDS[-1], nullable=True)
    if "presence" in v:
        c.boolean(v["presence"], "vitals.presence")
    if "moving" in v:
        c.boolean(v["moving"], "vitals.moving", nullable=True)
    if "breath_rpm" in v:
        c.int_in(v["breath_rpm"], "vitals.breath_rpm", *BREATH_RANGE, nullable=True)
    if "heart_bpm" in v:
        c.int_in(v["heart_bpm"], "vitals.heart_bpm", *HEART_RANGE, nullable=True)
    if "settled" in v:
        c.boolean(v["settled"], "vitals.settled")
    if "age_s" in v:
        c.num_in(v["age_s"], "vitals.age_s", 0, nullable=True)


def _check_contact(c: _Checker, ct: Any, path: str) -> None:
    if not c.obj(ct, path, _CONTACT_KEYS):
        return
    if "id" in ct:
        c.int_in(ct["id"], f"{path}.id", 1)
    first_ok = c.num_in(ct["first_seen"], f"{path}.first_seen", 0) if "first_seen" in ct else False
    last_ok = c.num_in(ct["last_seen"], f"{path}.last_seen", 0) if "last_seen" in ct else False
    if first_ok and last_ok and ct["last_seen"] < ct["first_seen"]:
        c.err(f"{path}.last_seen", f"{ct['last_seen']} is before first_seen {ct['first_seen']}")
    if "triage" in ct:
        c.enum(ct["triage"], f"{path}.triage", TRIAGES)
    if "last_breath_rpm" in ct:
        c.int_in(ct["last_breath_rpm"], f"{path}.last_breath_rpm", *BREATH_RANGE, nullable=True)
    if "last_heart_bpm" in ct:
        c.int_in(ct["last_heart_bpm"], f"{path}.last_heart_bpm", *HEART_RANGE, nullable=True)


def _check_lock(c: _Checker, d: dict) -> None:
    """Locked target and vitals.target_id must agree. Only runs once the shapes are sane."""
    targets, vitals = d.get("targets"), d.get("vitals")
    if not isinstance(targets, list) or not isinstance(vitals, dict):
        return
    ts = [t for t in targets if isinstance(t, dict)]
    locked = [t for t in ts if t.get("locked") is True]
    if len(locked) > 1:
        c.err("targets", f"{len(locked)} targets are locked, at most 1 allowed")
    vid = vitals.get("target_id")
    if _is_int(vid):
        match = [t for t in ts if t.get("id") == vid]
        if not match:
            c.err("vitals.target_id", f"{vid} does not match any target")
        elif match[0].get("locked") is not True:
            c.err("vitals.target_id", f"target {vid} is not locked")
    for t in locked:
        if t.get("id") != vid:
            c.err("targets", f"locked target {t.get('id')} does not match vitals.target_id {vid!r}")


def validate_snapshot(d: dict) -> list[str]:
    """Return a list of contract violations for a snapshot dict. Empty list means valid."""
    c = _Checker()
    if not c.obj(d, "snapshot", _SNAPSHOT_KEYS):
        return c.errors
    if d.get("type") != "snapshot":
        c.err("type", f"expected 'snapshot', got {d.get('type')!r}")
    if "v" in d and (not _is_int(d["v"]) or d["v"] != CONTRACT_VERSION):
        c.err("v", f"expected {CONTRACT_VERSION}, got {d['v']!r}")
    if "t" in d:
        c.num_in(d["t"], "t", 0)
    if "source" in d:
        c.enum(d["source"], "source", SOURCES)
    if "gate" in d:
        _check_gate(c, d["gate"])

    if "targets" in d:
        targets = d["targets"]
        if not isinstance(targets, list):
            c.err("targets", f"expected list, got {type(targets).__name__}")
        else:
            if len(targets) > MAX_TARGETS:
                c.err("targets", f"expected at most {MAX_TARGETS}, got {len(targets)}")
            for i, t in enumerate(targets):
                _check_target(c, t, f"targets[{i}]")
            ids = [t.get("id") for t in targets if isinstance(t, dict) and _is_int(t.get("id"))]
            if len(set(ids)) != len(ids):
                c.err("targets", f"duplicate ids {ids}")

    if "vitals" in d:
        _check_vitals(c, d["vitals"])

    if "sensors" in d:
        s = d["sensors"]
        if c.obj(s, "sensors", SENSOR_NAMES):
            for name in SENSOR_NAMES:
                if name in s:
                    c.enum(s[name], f"sensors.{name}", SENSOR_STATUSES)

    if "contacts" in d:
        contacts = d["contacts"]
        if not isinstance(contacts, list):
            c.err("contacts", f"expected list, got {type(contacts).__name__}")
        else:
            if len(contacts) > MAX_CONTACTS:
                c.err("contacts", f"expected at most {MAX_CONTACTS}, got {len(contacts)}")
            for i, ct in enumerate(contacts):
                _check_contact(c, ct, f"contacts[{i}]")
            seen = [ct["last_seen"] for ct in contacts
                    if isinstance(ct, dict) and _is_num(ct.get("last_seen"))]
            if any(a < b for a, b in zip(seen, seen[1:])):
                c.err("contacts", "not ordered by last_seen, most recent first")

    _check_lock(c, d)
    return c.errors
