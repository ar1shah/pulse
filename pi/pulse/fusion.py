"""Fusion of LD2450 targets and C1001 vitals into snapshots, per docs/data-contract.md.

Minimal but correct (T2); T7 hardens it and adds table-driven tests. Time is always a parameter, so tests
and the sim are deterministic.
"""
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .sensors.c1001 import C1001Reading
from .sensors.ld2450 import Ld2450Frame
from .state import (BREATH_RANGE, GATE_ANGLE_LIMITS, GATE_RANGE_LIMITS, HEART_RANGE, HOLD_S, LOCK_CONE_DEG,
                    LOCK_MAX_M, LOCK_MIN_M, MAX_CONTACTS, TARGET_IDS, Contact, Gate, SensorStatus, Snapshot,
                    Source, Target, Triage, Vitals)

ASSOCIATE_M = 0.6           # a detection joins a track only if within this distance
SMOOTH_ALPHA = 0.5          # weight of the new detection in position smoothing
MOVING_SPEED_CMS = 10       # |speed| at or above this means moving
MOVING_DIST_M = 0.15        # ... or moved more than this over the last MOVING_WINDOW_S
MOVING_WINDOW_S = 1.0
SETTLE_S = 3.0              # vitals.settled once breath and heart have both been non-null this long
_UNUSABLE = ("stale", "offline")


@dataclass
class _Track:
    id: int
    x: float                # smoothed position, mm
    y: float
    speed_cms: float
    last_seen: float        # time of the last detection
    moving: bool = False
    history: deque = field(default_factory=deque)   # (t, x, y) over the last MOVING_WINDOW_S

    @property
    def range_m(self) -> float:
        return math.hypot(self.x, self.y) / 1000

    @property
    def angle_deg(self) -> float:
        return math.degrees(math.atan2(self.x, self.y))

    @property
    def in_cone(self) -> bool:
        return abs(self.angle_deg) <= LOCK_CONE_DEG and LOCK_MIN_M <= self.range_m <= LOCK_MAX_M


def _polar(x_mm: float, y_mm: float) -> tuple[float, float]:
    return math.hypot(x_mm, y_mm) / 1000, math.degrees(math.atan2(x_mm, y_mm))


def _sanitize(value: Any, lo: int, hi: int) -> int | None:
    """Rule 9: anything outside lo..hi (including 0, NaN, non-numbers) becomes None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not lo <= value <= hi:
        return None
    return int(round(value))


def _valid_number(v: Any, lo: float, hi: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi


class Fusion:
    def __init__(self, source_name: Source) -> None:
        self.source_name = source_name
        self.gate = Gate()
        self._tracks: dict[int, _Track] = {}
        self._detected: set[int] = set()
        self._last_frame_t: float | None = None
        self._contacts: list[Contact] = []
        self._live: dict[int, Contact] = {}         # track id -> its current-appearance contact
        self._ok_since: float | None = None         # when breath and heart both became non-null
        self._ok_target: int | None = None

    # ---- client commands -----------------------------------------------------------------------

    def set_gate(self, max_range_m: Any, max_angle_deg: Any = None) -> bool:
        """Apply a set_gate command. False (and no change) if a value is missing or out of limits."""
        if not _valid_number(max_range_m, *GATE_RANGE_LIMITS):
            return False
        if max_angle_deg is not None and not _valid_number(max_angle_deg, *GATE_ANGLE_LIMITS):
            return False
        self.gate = Gate(float(max_range_m),
                         self.gate.max_angle_deg if max_angle_deg is None else float(max_angle_deg))
        return True

    def reset_contacts(self) -> None:
        self._contacts.clear()
        self._live.clear()      # live tracks get a fresh contact on the next update

    # ---- the tick ------------------------------------------------------------------------------

    def update(self, now: float, ld_frame: Ld2450Frame | None, ld_status: SensorStatus,
               c1_reading: C1001Reading | None, c1_status: SensorStatus) -> Snapshot:
        c1 = c1_reading if c1_reading is not None and c1_status not in _UNUSABLE else None
        presence = c1 is not None and c1.presence

        self._ingest(now, ld_frame)
        self._update_moving(now)
        self._gate_and_hold(now, presence)

        locked = self._lock()
        vitals = self._vitals(now, c1, locked)
        targets = [self._target(now, t, locked, presence, vitals) for t in sorted(self._tracks.values(),
                                                                                  key=lambda t: t.id)]
        self._update_contacts(now, targets, vitals)
        return Snapshot(t=now, source=self.source_name, gate=Gate(self.gate.max_range_m, self.gate.max_angle_deg),
                        targets=targets, vitals=vitals,
                        sensors={"ld2450": ld_status, "c1001": c1_status},
                        contacts=list(self._contacts))

    # ---- rules ---------------------------------------------------------------------------------

    def _ingest(self, now: float, frame: Ld2450Frame | None) -> None:
        """Rules 1 to 4: convert, gate, associate and smooth. Only runs for a frame not seen before."""
        self._detected = set()
        if frame is None or frame.t == self._last_frame_t:
            return
        self._last_frame_t = frame.t

        dets: list[tuple[float, float, float]] = []
        for d in frame.targets:
            if d.y_mm < 0:
                continue
            rng, ang = _polar(d.x_mm, d.y_mm)
            if rng > self.gate.max_range_m or abs(ang) > self.gate.max_angle_deg:
                continue
            dets.append((d.x_mm, d.y_mm, d.speed_cms))

        pairs = sorted((math.hypot(x - t.x, y - t.y), tid, i)
                       for tid, t in self._tracks.items() for i, (x, y, _) in enumerate(dets))
        used_tracks: set[int] = set()
        used_dets: set[int] = set()
        for dist, tid, i in pairs:
            if dist > ASSOCIATE_M * 1000:
                break
            if tid in used_tracks or i in used_dets:
                continue
            used_tracks.add(tid)
            used_dets.add(i)
            x, y, speed = dets[i]
            t = self._tracks[tid]
            t.x += SMOOTH_ALPHA * (x - t.x)
            t.y += SMOOTH_ALPHA * (y - t.y)
            t.speed_cms = speed
            t.last_seen = now
            self._detected.add(tid)

        for i, (x, y, speed) in enumerate(dets):
            if i in used_dets:
                continue
            free = [tid for tid in TARGET_IDS if tid not in self._tracks]
            if not free:
                continue                # already tracking the maximum number of people
            tid = free[0]
            self._tracks[tid] = _Track(id=tid, x=x, y=y, speed_cms=speed, last_seen=now)
            self._detected.add(tid)

    def _update_moving(self, now: float) -> None:
        """Rule 5. A track that dropped out keeps its flag for 1 s, then counts as still."""
        for tid, t in self._tracks.items():
            if tid not in self._detected:
                if now - t.last_seen >= MOVING_WINDOW_S:
                    t.moving = False
                continue
            t.history.append((now, t.x, t.y))
            while t.history and t.history[0][0] < now - MOVING_WINDOW_S:
                t.history.popleft()
            _, ox, oy = t.history[0]
            moved = math.hypot(t.x - ox, t.y - oy) / 1000 > MOVING_DIST_M
            t.moving = abs(t.speed_cms) >= MOVING_SPEED_CMS or moved

    def _gate_and_hold(self, now: float, presence: bool) -> None:
        """Gate applies to existing tracks too (so set_gate acts on the next tick); then rule 6, hold."""
        for tid in list(self._tracks):
            t = self._tracks[tid]
            held_s = now - t.last_seen
            outside = t.range_m > self.gate.max_range_m or abs(t.angle_deg) > self.gate.max_angle_deg
            expired = held_s > HOLD_S and not (presence and t.in_cone)   # still survivor stays held
            if outside or expired:
                del self._tracks[tid]
                self._live.pop(tid, None)

    def _lock(self) -> _Track | None:
        """Rule 7: of the tracks in the lock cone, the one closest to straight ahead."""
        in_cone = [t for t in self._tracks.values() if t.in_cone]
        return min(in_cone, key=lambda t: abs(t.angle_deg)) if in_cone else None

    def _vitals(self, now: float, c1: C1001Reading | None, locked: _Track | None) -> Vitals:
        """Rule 9 plus settle tracking. Numbers are only ever attached to the locked target."""
        v = Vitals(target_id=locked.id if locked else None)
        if c1 is not None:
            v.presence = c1.presence
            v.moving = c1.moving
            v.age_s = max(0.0, now - c1.t)
        if locked is not None and c1 is not None and c1.presence:
            v.breath_rpm = _sanitize(c1.breath_rpm, *BREATH_RANGE)
            v.heart_bpm = _sanitize(c1.heart_bpm, *HEART_RANGE)

        if v.breath_rpm is not None and v.heart_bpm is not None and v.target_id is not None:
            if self._ok_since is None or self._ok_target != v.target_id:
                self._ok_since, self._ok_target = now, v.target_id
            v.settled = now - self._ok_since >= SETTLE_S
        else:
            self._ok_since = self._ok_target = None
        return v

    def _target(self, now: float, t: _Track, locked: _Track | None, presence: bool, v: Vitals) -> Target:
        """Rule 8: green if moving; amber if still, locked, present and breathing; else gray."""
        is_locked = locked is not None and t.id == locked.id
        triage: Triage = "gray"
        if t.moving:
            triage = "green"
        elif is_locked and presence and v.breath_rpm is not None:
            triage = "amber"
        return Target(id=t.id, x_mm=int(round(t.x)), y_mm=max(0, int(round(t.y))),
                      speed_cms=int(round(t.speed_cms)), moving=t.moving, triage=triage,
                      locked=is_locked, last_seen_s=max(0.0, now - t.last_seen))

    def _update_contacts(self, now: float, targets: list[Target], v: Vitals) -> None:
        """Rule 10: one contact per track appearance; id is the track id, so ids repeat after reuse."""
        for tgt in targets:
            c = self._live.get(tgt.id)
            if c is None:
                c = Contact(id=tgt.id, first_seen=now, last_seen=now, triage=tgt.triage)
                self._live[tgt.id] = c
                self._contacts.append(c)
            c.last_seen = now
            c.triage = tgt.triage
            if tgt.locked:
                if v.breath_rpm is not None:
                    c.last_breath_rpm = v.breath_rpm
                if v.heart_bpm is not None:
                    c.last_heart_bpm = v.heart_bpm
        self._contacts.sort(key=lambda c: -c.last_seen)     # stable: ties keep insertion order
        del self._contacts[MAX_CONTACTS:]
