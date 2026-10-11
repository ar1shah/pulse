"""The x filter (tracker.py) and what it changes in fusion when on (live default; PULSE_XFILTER)."""
import random

import pytest

from pulse import tracker
from pulse.fusion import Fusion, xfilter_default
from pulse.sensors.ld2450 import Ld2450Frame, Ld2450Target
from pulse.tracker import DEADBAND_X_MM, XFilter


def frame(t: float, *targets: tuple[int, int, int]) -> Ld2450Frame:
    return Ld2450Frame(t=t, targets=[Ld2450Target(x, y, s) for x, y, s in targets])


def test_still_noise_inside_the_deadband_never_moves_the_dot():
    f = XFilter(0)
    for i in range(50):
        f.update((-60, 60)[i % 2])
        assert f.x == 0


def test_a_single_spike_is_eaten_by_the_median():
    f = XFilter(0)
    for _ in range(5):
        f.update(0)
    f.update(700)
    assert f.x == 0


def test_a_huge_jump_is_rejected_until_it_repeats():
    f = XFilter(0)
    assert f.update(1500) is False and f.x == 0
    assert f.update(1500) is False
    assert f.update(1500) is True and f.x == 1500       # OUTLIER_RESET in a row: the person really is there


def test_a_steady_walk_never_steps_backwards():
    rng = random.Random(1)
    f = XFilter(-1000)
    last = f.x
    for k in range(60):
        f.update(-1000 + 40 * k + rng.gauss(0, 40))
        assert f.x >= last
        last = f.x
    assert f.x > 1000                                   # and it does keep up


def walk(seed: int, f: Fusion, speed_mms: float = 400, ticks: int = 100):
    """A sideways walker at 2.5 m with LD2450-like faults: 15 cm x noise, 25 % missed frames, 8 % far returns."""
    rng = random.Random(seed)
    for k in range(ticks):
        t = 1000 + k * 0.1
        x = -1500 + speed_mms * k / 10
        dets = []
        if rng.random() > 0.25:
            x += rng.gauss(0, 75) + (rng.choice([-500, 500]) if rng.random() < 0.08 else 0)
            dets.append((int(x), 2500 + int(rng.gauss(0, 30)), rng.choice([0, 0, 5, -5])))
        yield f.update(t, frame(t, *dets), "ok", None, "offline")


@pytest.mark.parametrize("seed", range(5))
def test_sideways_walker_with_faults_never_goes_the_wrong_way(seed):
    last = None
    for snap in walk(seed, Fusion("live")):
        for t in snap.targets:
            assert t.id == 1, "a far return spawned a phantom dot"
            if last is not None:
                assert t.x_mm >= last - 30, "the dot stepped the wrong way"
            last = t.x_mm


def test_old_fusion_failed_the_same_walk():
    """Guard for the test above: without the filter the same faults do show (so the test can catch a regression)."""
    bad = 0
    for seed in range(5):
        last = None
        for snap in walk(seed, Fusion("live", xfilter=False)):
            xs = [t.x_mm for t in snap.targets if t.id == 1]
            if xs and last is not None and xs[0] < last - 30:
                bad += 1
            last = xs[0] if xs else last
    assert bad > 5


def test_a_short_ghost_is_never_shown_and_frees_its_id():
    f = Fusion("live")
    n = tracker.CONFIRM_FRAMES

    def step(i, *dets):
        return f.update(i / 10, frame(i / 10, *dets), "ok", None, "offline")

    for i in range(n - 1):
        assert step(i, (0, 2000, 0)).targets == []
    assert [t.id for t in step(n - 1, (0, 2000, 0)).targets] == [1]   # confirmed on its CONFIRM_FRAMES-th frame
    for i in range(n, 2 * n - 1):                                       # a ghost for one frame less than that
        assert [t.id for t in step(i, (0, 2000, 0), (1500, 1500, 0)).targets] == [1]
    for i in range(2 * n - 1, 2 * n + 4):
        s = step(i, (0, 2000, 0))
    assert sorted(f._tracks) == [1]                     # ...dropped after TENTATIVE_DROP_S, not held 3 s
    assert len(s.contacts) == 1


def test_still_then_walking_does_not_jump():
    """Velocity used to random-walk while still and fire when the track turned moving."""
    rng = random.Random(3)
    f = Fusion("live")
    last = None
    for k in range(200):
        t = k / 10
        x = 0 if k < 120 else 30 * (k - 120)
        s = f.update(t, frame(t, (int(x + rng.gauss(0, 75)), 2500, 0)), "ok", None, "offline")
        if s.targets and last is not None:
            assert abs(s.targets[0].x_mm - last) < 150
        last = s.targets[0].x_mm if s.targets else last


def test_filter_defaults_on_for_live_only_and_env_forces_it(monkeypatch):
    monkeypatch.delenv("PULSE_XFILTER", raising=False)
    assert xfilter_default("live") and not xfilter_default("sim") and not xfilter_default("replay")
    monkeypatch.setenv("PULSE_XFILTER", "0")
    assert not xfilter_default("live")
    monkeypatch.setenv("PULSE_XFILTER", "1")
    assert xfilter_default("sim")


def test_constants_are_sane():
    assert tracker.MEDIAN_N >= 1 and 0 < tracker.EMA_ALPHA <= 1 and DEADBAND_X_MM >= 0
    assert tracker.CONFIRM_FRAMES >= 1 and tracker.OUTLIER_RESET >= 1
