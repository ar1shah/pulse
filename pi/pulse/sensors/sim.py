"""Fake LD2450 + C1001 for sim mode.

Emits the same raw readings the real parsers will: Ld2450Frame (targets in mm and cm/s, contract sign
conventions) and C1001Reading (presence / moving / breath / heart). Fusion cannot tell the difference.

Time is always passed in, so runs are reproducible for a given SIM_SEED and sequence of `now` values.
"""
import logging
import math
import os
import random
from dataclasses import dataclass, field, replace

from ..state import LOCK_CONE_DEG, LOCK_MAX_M, LOCK_MIN_M, SensorStatus
from .c1001 import C1001Reading
from .ld2450 import Ld2450Frame, Ld2450Target

log = logging.getLogger("pulse.sim")

SCENARIOS = ("demo", "random", "cross", "edge", "still")

FOV_DEG = 60.0              # LD2450 field of view, half angle
LD_MAX_RANGE_MM = 6000
C1001_FOV_DEG = 40.0        # the C1001 sees a narrower cone than the LD2450
C1001_MAX_RANGE_MM = 5000
C1001_PERIOD_S = 1.0        # one new C1001 reading per second
POS_JITTER_MM = 20
MOVING_CMS = 10             # same threshold fusion uses

SETTLE_S = (3.0, 8.0)       # delay before vitals numbers appear after someone enters the cone
BREATH_RANGE = (12, 20)
HEART_RANGE = (62, 95)

DEMO_SITTER_MM = (150.0, 1200.0)
DEMO_CYCLE_S = 20.0
DEMO_WALK_START_S = 4.0     # into each cycle
DEMO_WALK_HALF_WIDTH_MM = 5200.0   # wider than the FOV at 2.5 m, so the walker enters and leaves it
DEMO_WALK_SPEED_MMS = 1000.0
DEMO_WALK_Y_MM = (2300.0, 2800.0)

RAND_ANGLE_DEG = 55.0
RAND_RANGE_M = (0.5, 5.0)
RAND_SPEED_MS = (0.3, 1.2)
RAND_PAUSE_S = (5.0, 20.0)
RAND_PAUSE_P = 0.30
RAND_LEAVE_P = 0.10
RAND_DROPOUT_PER_S = 0.05   # chance per second that a still person vanishes from the LD2450
RAND_DROPOUT_S = (1.0, 2.5)
MAX_STEP_S = 0.5

# cross: two walkers pass each other shoulder to shoulder at about 2 m, stop at the ends, walk back
CROSS_LANES_MM = (1850.0, 2150.0)   # lane y of walker A and B: 0.3 m apart when they pass
CROSS_HALF_WIDTH_MM = 2400.0        # walk from x = -2.4 m to +2.4 m (about 50 deg, inside the default gate)
CROSS_SPEED_MMS = 900.0
CROSS_PAUSE_S = 2.0                 # standing at each end before turning round
CROSS_MERGE_MM = 450.0              # closer than this, the LD2450 reports the two as one target between them

# edge: one person drifting in and out across the default 4 m range gate
EDGE_ANGLE_DEG = 12.0
EDGE_RANGE_MM = 4000.0
EDGE_DRIFT_MM = 220.0               # range swings 3.78 to 4.22 m (starts outside, at the far end)
EDGE_PERIOD_S = 12.0

# still: a sitter in the lock cone the LD2450 keeps losing while the C1001 still sees them
STILL_SITTER_MM = (-100.0, 1100.0)
STILL_SEEN_S = (2.0, 5.0)           # visible to the LD2450 this long ...
STILL_DROPOUT_S = (5.0, 10.0)       # ... then missed for this long, repeat


def _polar(x: float, y: float) -> tuple[float, float]:
    """(range_mm, angle_deg) with 0 deg straight ahead, negative left."""
    return math.hypot(x, y), math.degrees(math.atan2(x, y))


@dataclass
class _Person:
    x: float
    y: float
    breath_base: float
    heart_base: float
    phase_b: float
    phase_h: float
    vx: float = 0.0                 # mm/s
    vy: float = 0.0
    active: bool = True             # False = not in the room right now
    waypoint: tuple[float, float] | None = None
    speed: float = 0.0              # walking speed, mm/s
    pause_until: float = 0.0
    leaving: bool = False
    dropout_until: float = 0.0      # invisible to the LD2450 until then (C1001 still sees them)
    slot_key: float = 0.0           # sort key that decides LD2450 slot order

    @property
    def radial_cms(self) -> float:
        """Radial speed in cm/s, negative = approaching (range shrinking)."""
        r = math.hypot(self.x, self.y)
        if r < 1.0:
            return 0.0
        return (self.x * self.vx + self.y * self.vy) / r / 10.0


@dataclass
class _ConeState:
    person: _Person | None = None
    since: float = 0.0
    settle_s: float = 0.0


@dataclass
class SimSource:
    scenario: str = "demo"
    seed: int | None = None
    name: str = "sim"
    _rng: random.Random = field(init=False, repr=False)
    _people: list[_Person] = field(init=False, default_factory=list, repr=False)
    _last: float | None = field(init=False, default=None, repr=False)
    _t0: float = field(init=False, default=0.0, repr=False)
    _want: int = field(init=False, default=1, repr=False)
    _spawn_at: float = field(init=False, default=0.0, repr=False)
    _reroll_at: float = field(init=False, default=0.0, repr=False)
    _cone: _ConeState = field(init=False, default_factory=_ConeState, repr=False)
    _c_reading: C1001Reading | None = field(init=False, default=None, repr=False)
    _toggle_at: float = field(init=False, default=0.0, repr=False)     # still: next LD2450 dropout

    def __post_init__(self) -> None:
        if self.scenario not in SCENARIOS:
            raise ValueError(f"unknown SIM_SCENARIO {self.scenario!r}: expected one of {list(SCENARIOS)}")
        if self.seed is None:
            self.seed = random.SystemRandom().randrange(1, 10**6)
        self._rng = random.Random(self.seed)
        log.info("sim scenario=%s seed=%s (set SIM_SEED=%s to reproduce)", self.scenario, self.seed, self.seed)

    @classmethod
    def from_env(cls) -> "SimSource":
        seed_env = os.environ.get("SIM_SEED", "").strip()
        return cls(scenario=os.environ.get("SIM_SCENARIO", "demo").strip().lower() or "demo",
                   seed=int(seed_env) if seed_env else None)

    # ---- Source interface ----------------------------------------------------------------------

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def ld2450(self, now: float) -> tuple[Ld2450Frame | None, SensorStatus]:
        self._advance(now)
        seen: list[tuple[float, Ld2450Target]] = []
        people = self._merge_close(self._people) if self.scenario == "cross" else self._people
        for p in people:
            if not p.active or p.dropout_until > now:
                continue
            rng_mm, ang = _polar(p.x, p.y)
            if p.y <= 0 or abs(ang) > FOV_DEG or rng_mm > LD_MAX_RANGE_MM:
                continue
            seen.append((p.slot_key, Ld2450Target(
                x_mm=round(p.x + self._rng.uniform(-POS_JITTER_MM, POS_JITTER_MM)),
                y_mm=max(0, round(p.y + self._rng.uniform(-POS_JITTER_MM, POS_JITTER_MM))),
                speed_cms=round(p.radial_cms),
            )))
        # LD2450 slot order is not identity: occasionally reshuffle so fusion has to associate by position.
        if self._rng.random() < 0.02:
            for p in self._people:
                p.slot_key = self._rng.random()
        seen.sort(key=lambda s: s[0])
        return Ld2450Frame(t=now, targets=[t for _, t in seen[:3]]), "sim"

    def c1001(self, now: float) -> tuple[C1001Reading | None, SensorStatus]:
        self._advance(now)
        self._update_cone(now)
        if self._c_reading is None or now - self._c_reading.t >= C1001_PERIOD_S:
            self._c_reading = self._sample_c1001(now)
        return self._c_reading, "sim"

    # ---- world ---------------------------------------------------------------------------------

    def _new_person(self, x: float, y: float) -> _Person:
        r = self._rng
        return _Person(x=x, y=y, breath_base=r.uniform(14, 18), heart_base=r.uniform(68, 88),
                       phase_b=r.uniform(0, math.tau), phase_h=r.uniform(0, math.tau), slot_key=r.random())

    def _advance(self, now: float) -> None:
        if self._last is None:
            self._t0 = self._last = now
            self._init_world(now)
            return
        dt = min(now - self._last, MAX_STEP_S)
        if now <= self._last:
            return
        self._last = now
        if self.scenario == "demo":
            self._advance_demo(now)
        elif self.scenario == "random":
            self._advance_random(now, dt)
        elif self.scenario == "cross":
            self._advance_cross(now)
        elif self.scenario == "edge":
            self._advance_edge(now)
        else:
            self._advance_still(now)

    # demo: one person sitting still in the lock cone + a walker crossing every 20 s

    def _init_world(self, now: float) -> None:
        if self.scenario == "demo":
            sitter = self._new_person(*DEMO_SITTER_MM)
            walker = self._new_person(0.0, DEMO_WALK_Y_MM[0])
            walker.active = False
            self._people = [sitter, walker]
        elif self.scenario == "cross":
            self._people = [self._new_person(0.0, y) for y in CROSS_LANES_MM]
            self._advance_cross(now)
        elif self.scenario == "edge":
            self._people = [self._new_person(0.0, EDGE_RANGE_MM)]
            self._advance_edge(now)
        elif self.scenario == "still":
            self._people = [self._new_person(*STILL_SITTER_MM)]
            self._toggle_at = now + self._rng.uniform(*STILL_SEEN_S)
        else:
            self._want = self._rng.randint(1, 3)
            self._reroll_at = now + self._rng.uniform(20, 45)
            self._spawn_at = now
            for _ in range(self._want):
                r_m = self._rng.uniform(*RAND_RANGE_M)
                a = math.radians(self._rng.uniform(-RAND_ANGLE_DEG, RAND_ANGLE_DEG))
                p = self._new_person(r_m * 1000 * math.sin(a), r_m * 1000 * math.cos(a))
                self._new_waypoint(p)
                self._people.append(p)

    def _advance_demo(self, now: float) -> None:
        walker = self._people[1]
        cycle, ct = divmod(now - self._t0, DEMO_CYCLE_S)
        length = 2 * DEMO_WALK_HALF_WIDTH_MM
        walk_s = length / DEMO_WALK_SPEED_MMS
        u = (ct - DEMO_WALK_START_S) / walk_s
        walker.active = 0.0 <= u <= 1.0
        if not walker.active:
            walker.vx = walker.vy = 0.0
            return
        direction = 1.0 if int(cycle) % 2 == 0 else -1.0     # alternate left-to-right and back
        dy = DEMO_WALK_Y_MM[1] - DEMO_WALK_Y_MM[0]
        walker.x = direction * (2 * u - 1) * DEMO_WALK_HALF_WIDTH_MM
        walker.y = DEMO_WALK_Y_MM[0] + dy * u
        walker.vx = direction * DEMO_WALK_SPEED_MMS
        walker.vy = dy / walk_s

    # cross, edge, still: the fusion rough edges from docs/STATUS.md (T2 notes), one scenario each

    def _advance_cross(self, now: float) -> None:
        walk_s = 2 * CROSS_HALF_WIDTH_MM / CROSS_SPEED_MMS
        leg_s = walk_s + CROSS_PAUSE_S
        leg, lt = divmod(now - self._t0, leg_s)
        direction = 1.0 if int(leg) % 2 == 0 else -1.0     # A walks left to right first, B the other way
        u = min(lt / walk_s, 1.0)
        walking = lt < walk_s
        for p, side in zip(self._people, (1.0, -1.0)):
            p.x = side * direction * (2 * u - 1) * CROSS_HALF_WIDTH_MM
            p.vx = side * direction * CROSS_SPEED_MMS if walking else 0.0
            p.vy = 0.0

    @staticmethod
    def _merge_close(people: list[_Person]) -> list[_Person]:
        """The LD2450 can't split two people this close: it reports one target between them."""
        a, b = people
        if math.hypot(a.x - b.x, a.y - b.y) >= CROSS_MERGE_MM:
            return people
        return [replace(a, x=(a.x + b.x) / 2, y=(a.y + b.y) / 2, vx=(a.vx + b.vx) / 2, vy=(a.vy + b.vy) / 2)]

    def _advance_edge(self, now: float) -> None:
        p = self._people[0]
        w = math.tau / EDGE_PERIOD_S
        r = EDGE_RANGE_MM + EDGE_DRIFT_MM * math.cos(w * (now - self._t0))
        dr = -EDGE_DRIFT_MM * w * math.sin(w * (now - self._t0))      # mm/s, outward positive
        a = math.radians(EDGE_ANGLE_DEG)
        p.x, p.y = r * math.sin(a), r * math.cos(a)
        p.vx, p.vy = dr * math.sin(a), dr * math.cos(a)

    def _advance_still(self, now: float) -> None:
        if now >= self._toggle_at:
            p = self._people[0]
            p.dropout_until = now + self._rng.uniform(*STILL_DROPOUT_S)
            self._toggle_at = p.dropout_until + self._rng.uniform(*STILL_SEEN_S)

    # random: wandering people with waypoints, pauses, arrivals and departures

    def _new_waypoint(self, p: _Person) -> None:
        r_m = self._rng.uniform(*RAND_RANGE_M)
        a = math.radians(self._rng.uniform(-RAND_ANGLE_DEG, RAND_ANGLE_DEG))
        p.waypoint = (r_m * 1000 * math.sin(a), r_m * 1000 * math.cos(a))
        p.speed = self._rng.uniform(*RAND_SPEED_MS) * 1000

    def _send_out(self, p: _Person) -> None:
        side = 1.0 if (p.x > 0 or (p.x == 0 and self._rng.random() < 0.5)) else -1.0
        a = math.radians(side * self._rng.uniform(63, 68))
        r_mm = self._rng.uniform(3000, 5500)
        p.waypoint = (r_mm * math.sin(a), r_mm * math.cos(a))
        p.speed = self._rng.uniform(*RAND_SPEED_MS) * 1000
        p.leaving = True

    def _arrive(self, p: _Person, now: float) -> None:
        if p.leaving:
            p.active = False
            return
        too_many = sum(q.active for q in self._people) > self._want
        roll = self._rng.random()
        if too_many or roll < RAND_LEAVE_P:
            self._send_out(p)
            return
        if roll < RAND_LEAVE_P + RAND_PAUSE_P:
            p.pause_until = now + self._rng.uniform(*RAND_PAUSE_S)
        self._new_waypoint(p)

    def _advance_random(self, now: float, dt: float) -> None:
        for p in self._people:
            if not p.active:
                continue
            if now < p.pause_until or p.waypoint is None:
                p.vx = p.vy = 0.0
                if p.dropout_until <= now and self._rng.random() < RAND_DROPOUT_PER_S * dt:
                    p.dropout_until = now + self._rng.uniform(*RAND_DROPOUT_S)
                continue
            wx, wy = p.waypoint
            dx, dy = wx - p.x, wy - p.y
            dist = math.hypot(dx, dy)
            step = p.speed * dt
            if dist <= max(step, 1.0):
                p.x, p.y, p.vx, p.vy = wx, wy, 0.0, 0.0
                self._arrive(p, now)
                continue
            p.vx, p.vy = dx / dist * p.speed, dy / dist * p.speed
            p.x += p.vx * dt
            p.y += p.vy * dt

        self._people = [p for p in self._people if p.active]
        if now >= self._reroll_at:
            self._want = self._rng.choices([1, 2, 3], [0.35, 0.4, 0.25])[0]
            self._reroll_at = now + self._rng.uniform(20, 45)
        if len(self._people) < self._want and now >= self._spawn_at:
            side = self._rng.choice((-1.0, 1.0))
            a = math.radians(side * self._rng.uniform(60.5, 64.0))
            r_mm = self._rng.uniform(1500, 5000)
            p = self._new_person(r_mm * math.sin(a), r_mm * math.cos(a))
            self._new_waypoint(p)
            self._people.append(p)
            self._spawn_at = now + self._rng.uniform(2, 8)

    # ---- C1001 ---------------------------------------------------------------------------------

    def _lock_candidate(self) -> _Person | None:
        """The person fusion would lock: in the lock cone, closest to straight ahead."""
        best: tuple[float, _Person] | None = None
        for p in self._people:
            if not p.active or p.y <= 0:
                continue
            r, a = _polar(p.x, p.y)
            if abs(a) <= LOCK_CONE_DEG and LOCK_MIN_M * 1000 <= r <= LOCK_MAX_M * 1000:
                if best is None or abs(a) < best[0]:
                    best = (abs(a), p)
        return best[1] if best else None

    def _update_cone(self, now: float) -> None:
        """Track who the C1001 is looking at; vitals are only eligible after the settle delay."""
        p = self._lock_candidate()
        if p is not None and abs(p.radial_cms) >= MOVING_CMS:
            p = None            # a walking person gives no vitals, and must settle again once still
        c = self._cone
        if p is not c.person:
            c.person = p
            c.since = now
            c.settle_s = self._rng.uniform(*SETTLE_S)

    def _sample_c1001(self, now: float) -> C1001Reading:
        c = self._cone
        breath = heart = None
        if c.person is not None and now - c.since >= c.settle_s:
            p = c.person
            breath = p.breath_base + 2.0 * math.sin(math.tau * now / 40 + p.phase_b) + self._rng.uniform(-0.5, 0.5)
            heart = p.heart_base + 5.0 * math.sin(math.tau * now / 55 + p.phase_h) + self._rng.uniform(-1.5, 1.5)
            breath = max(BREATH_RANGE[0], min(BREATH_RANGE[1], round(breath)))
            heart = max(HEART_RANGE[0], min(HEART_RANGE[1], round(heart)))

        # presence/moving describe whoever is nearest the sensor axis inside the C1001's cone
        seen: list[tuple[float, _Person]] = []
        for p in self._people:
            if not p.active or p.y <= 0:
                continue
            r, a = _polar(p.x, p.y)
            if abs(a) <= C1001_FOV_DEG and r <= C1001_MAX_RANGE_MM:
                seen.append((abs(a), p))
        if not seen:
            return C1001Reading(t=now, presence=False, moving=None)
        nearest = c.person or min(seen, key=lambda s: s[0])[1]
        return C1001Reading(t=now, presence=True, moving=abs(nearest.radial_cms) >= MOVING_CMS,
                            breath_rpm=breath, heart_bpm=heart)
