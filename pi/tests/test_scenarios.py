"""The fusion rough edges, driven end to end: sim scenario -> fusion, fixed seeds, fake time (10 Hz).

cross: two walkers pass at about 2 m, briefly merged into one LD2450 target; ids must not swap.
edge:  one person drifting across the 4 m gate; must stay one contact.
still: a sitter the LD2450 keeps losing for 5 to 10 s while C1001 presence stays true; must never drop.
"""
import math

import pytest

from pulse.fusion import Fusion
from pulse.sensors.sim import CROSS_MERGE_MM, SimSource
from pulse.state import validate_snapshot

T0 = 1_791_600_000.0
SEEDS = [1, 2, 3, 4, 5]
SECONDS = 120


def run(scenario: str, seed: int, seconds: float = SECONDS):
    """Yield (snapshot dict, LD2450 frame, true (x, y) of each sim person) for every tick."""
    src = SimSource(scenario, seed=seed)
    fusion = Fusion("sim")
    for i in range(int(seconds * 10)):
        now = T0 + i * 0.1
        frame, ld = src.ld2450(now)
        reading, c1 = src.c1001(now)
        snap = fusion.update(now, frame, ld, reading, c1).to_dict()
        assert validate_snapshot(snap) == [], f"{scenario} seed {seed} tick {i}"
        yield snap, frame, [(p.x, p.y) for p in src._people]     # ground truth, test-only peek


@pytest.mark.parametrize("seed", SEEDS)
def test_cross_no_id_swap(seed):
    owner: dict[int, int] = {}          # track id -> index of the walker it follows
    judged = merged = 0
    for snap, frame, truth in run("cross", seed):
        merged += len(frame.targets) == 1
        assert len(snap["targets"]) == 2, "a walker's dot dropped while they crossed"
        for t in snap["targets"]:
            d = [math.hypot(t["x_mm"] - x, t["y_mm"] - y) for x, y in truth]
            if min(d) > 150 or max(d) < 400:
                continue                # ambiguous while the two are side by side: judge only clear ticks
            who = d.index(min(d))
            assert owner.setdefault(t["id"], who) == who, f"id {t['id']} swapped walkers"
            judged += 1
    assert len(snap["contacts"]) == 2
    assert merged > 0, "the scenario never merged the two walkers into one LD2450 target"
    assert judged > 1000


def test_cross_walkers_really_merge():
    src = SimSource("cross", seed=1)
    gaps = []
    for i in range(80):                 # the first crossing is a little under 3 s in
        src.ld2450(T0 + i * 0.1)
        (ax, ay), (bx, by) = [(p.x, p.y) for p in src._people]
        gaps.append(math.hypot(ax - bx, ay - by))
    assert min(gaps) < CROSS_MERGE_MM and abs(min(gaps) - 300) < 100   # they pass 0.3 m apart


@pytest.mark.parametrize("seed", SEEDS)
def test_edge_is_exactly_one_contact(seed):
    shown = hidden = 0
    for snap, frame, truth in run("edge", seed):
        gate = snap["gate"]["max_range_m"]
        assert all(t["range_m"] <= gate for t in snap["targets"]), "a dot was shown past the gate"
        (x, y), = truth
        if math.hypot(x, y) / 1000 < gate - 0.05:
            shown += len(snap["targets"]) == 1
        elif math.hypot(x, y) / 1000 > gate + 0.05:
            hidden += snap["targets"] == []
    assert len(snap["contacts"]) == 1 and snap["contacts"][0]["id"] == 1
    assert shown > 400 and hidden > 400    # it really went in and out, about half the time each


@pytest.mark.parametrize("seed", SEEDS)
def test_still_sitter_never_drops(seed):
    longest_gap = 0.0
    amber_while_lost = 0
    for snap, frame, truth in run("still", seed):
        assert len(snap["targets"]) == 1, "the sitter's dot dropped"
        t = snap["targets"][0]
        assert t["id"] == 1 and t["locked"] and not t["moving"]
        assert snap["vitals"]["target_id"] == 1
        longest_gap = max(longest_gap, t["last_seen_s"])
        amber_while_lost += t["last_seen_s"] > 3.0 and t["triage"] == "amber"
    assert len(snap["contacts"]) == 1
    assert longest_gap > 5.0, "the LD2450 never lost the sitter for long"
    assert amber_while_lost > 100, "vitals should keep coming while only the C1001 sees the sitter"


@pytest.mark.parametrize("scenario", ["cross", "edge", "still"])
def test_scenarios_are_reproducible(scenario):
    a = [s for s, _, _ in run(scenario, seed=9, seconds=30)]
    assert a == [s for s, _, _ in run(scenario, seed=9, seconds=30)]
