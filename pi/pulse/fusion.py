"""Fusion of LD2450 targets and C1001 vitals into snapshots, per docs/data-contract.md.

Time is always a parameter, so tests and the sim are deterministic. The sim scenarios cross, edge and still
(sensors/sim.py) reproduce the rough edges the constants below are tuned against; tests/test_scenarios.py runs them.
"""
import itertools
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .sensors.c1001 import C1001Reading
from .sensors.ld2450 import Ld2450Frame
from .state import (BREATH_RANGE, GATE_ANGLE_LIMITS, GATE_RANGE_LIMITS, HOLD_S, LOCK_CONE_DEG,
                    LOCK_MAX_M, LOCK_MIN_M, MAX_CONTACTS, TARGET_IDS, Contact, Gate, SensorStatus, Snapshot,
                    Source, Target, Triage, Vitals)

ASSOCIATE_M = 0.6           # max match distance from a track's predicted spot: a walker covers 0.15 m per tick
SMOOTH_ALPHA = 0.5          # weight of the new detection in position smoothing
VEL_BETA = 0.15             # weight of the residual in the velocity estimate (alpha-beta pair for 0.5 is ~0.17)
COAST_S = 1.0               # a moving track's prediction runs on this long undetected (two people merging)
GATE_MARGIN_M = 0.3         # a track lives to gate + this (less than a step); new tracks start inside the gate
GATE_MARGIN_DEG = 5.0       # same for the angle gate: about 0.35 m sideways at 4 m
PRESENCE_GRACE_S = 2.0      # C1001 presence holds a still survivor this long after it was last true (2 polls)
HEART_MIN_BPM = 45          # accepted heart range: wider than the C1001's rated 60 to 100, which it does exceed
HEART_MAX_BPM = 150
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
    vx: float = 0.0         # velocity estimate, mm/s
    vy: float = 0.0
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

    def predict(self, now: float) -> tuple[float, float]:
        """Where the track should be now. A still track never coasts, so a held survivor can't drift."""
        if not self.moving:
            return self.x, self.y
        dt = min(now - self.last_seen, COAST_S)
        return self.x + self.vx * dt, self.y + self.vy * dt


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
        self._presence_t: float | None = None       # time of the last C1001 reading with presence

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
        if presence:
            self._presence_t = c1.t
        recent = self._presence_t is not None and now - self._presence_t <= PRESENCE_GRACE_S

        self._ingest(now, ld_frame)
        self._update_moving(now)
        self._gate_and_hold(now, recent)

        # tracks in the gate margin stay alive (same id, same contact) but are not shown
        shown = [t for t in sorted(self._tracks.values(), key=lambda t: t.id) if self._inside(t, 0.0, 0.0)]
        locked = self._lock(shown)
        vitals = self._vitals(now, c1, locked)
        targets = [self._target(now, t, locked, presence, vitals) for t in shown]
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
            if rng > self.gate.max_range_m + GATE_MARGIN_M or abs(ang) > self.gate.max_angle_deg + GATE_MARGIN_DEG:
                continue
            dets.append((d.x_mm, d.y_mm, d.speed_cms))

        matched = self._associate(now, dets)
        for tid, i in matched.items():
            x, y, speed = dets[i]
            t = self._tracks[tid]
            px, py = t.predict(now)
            rx, ry = x - px, y - py
            t.x, t.y = px + SMOOTH_ALPHA * rx, py + SMOOTH_ALPHA * ry
            dt = now - t.last_seen
            if 0 < dt <= COAST_S:
                t.vx += VEL_BETA * rx / dt
                t.vy += VEL_BETA * ry / dt
            else:
                t.vx = t.vy = 0.0       # lost too long: start the velocity estimate over
            t.speed_cms = speed
            t.last_seen = now
            self._detected.add(tid)

        used = set(matched.values())
        for i, (x, y, speed) in enumerate(dets):
            if i in used or not self._inside_gate(x, y):
                continue                # a detection in the gate margin can only continue a track
            free = [tid for tid in TARGET_IDS if tid not in self._tracks]
            if not free:
                continue                # already tracking the maximum number of people
            tid = free[0]
            self._tracks[tid] = _Track(id=tid, x=x, y=y, speed_cms=speed, last_seen=now)
            self._detected.add(tid)

    def _associate(self, now: float, dets: list[tuple[float, float, float]]) -> dict[int, int]:
        """Rule 3: track id -> detection index. Of all one-to-one matchings (at most 3 x 3, so try them all),
        take the one with the most pairs, then the least total distance to the predicted positions. A pair
        farther than ASSOCIATE_M is never made, so ids never swap by jumping."""
        tids = list(self._tracks)
        pred = {tid: self._tracks[tid].predict(now) for tid in tids}
        dist = {(tid, i): math.hypot(x - pred[tid][0], y - pred[tid][1])
                for tid in tids for i, (x, y, _) in enumerate(dets)}
        best: tuple[int, float, dict[int, int]] = (0, 0.0, {})
        choices: list[int | None] = [*range(len(dets)), *([None] * len(tids))]
        for perm in itertools.permutations(choices, len(tids)):
            pairs = {tid: i for tid, i in zip(tids, perm) if i is not None}
            cost = [dist[tid, i] for tid, i in pairs.items()]
            if any(d > ASSOCIATE_M * 1000 for d in cost):
                continue
            if (len(pairs), -sum(cost)) > (best[0], -best[1]):
                best = (len(pairs), sum(cost), pairs)
        return best[2]

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
        """Rule 2's leave side: a track past gate + margin is dropped (so set_gate acts on the next tick).
        Then rule 6, hold. `presence` here includes PRESENCE_GRACE_S."""
        for tid in list(self._tracks):
            t = self._tracks[tid]
            held_s = now - t.last_seen
            outside = not self._inside(t, GATE_MARGIN_M, GATE_MARGIN_DEG)
            expired = held_s > HOLD_S and not (presence and t.in_cone)   # still survivor stays held
            if outside or expired:
                del self._tracks[tid]
                self._live.pop(tid, None)

    def _inside_gate(self, x: float, y: float) -> bool:
        rng, ang = _polar(x, y)
        return rng <= self.gate.max_range_m and abs(ang) <= self.gate.max_angle_deg

    def _inside(self, t: _Track, margin_m: float, margin_deg: float) -> bool:
        return (t.range_m <= self.gate.max_range_m + margin_m
                and abs(t.angle_deg) <= self.gate.max_angle_deg + margin_deg)

    def _lock(self, shown: list[_Track]) -> _Track | None:
        """Rule 7: of the shown tracks in the lock cone, the one closest to straight ahead."""
        in_cone = [t for t in shown if t.in_cone]
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
            v.heart_bpm = _sanitize(c1.heart_bpm, HEART_MIN_BPM, HEART_MAX_BPM)

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
