"""Sim source through fusion: every snapshot must satisfy the contract, and runs must be reproducible."""
import pytest

from pulse.fusion import Fusion
from pulse.sensors.sim import SimSource
from pulse.state import validate_snapshot

T0 = 1_791_600_000.0
TICKS = 300


def run(scenario: str, seed: int, ticks: int = TICKS) -> list[dict]:
    src = SimSource(scenario, seed=seed)
    fusion = Fusion("sim")
    out = []
    for i in range(ticks):
        now = T0 + i * 0.1
        frame, ld = src.ld2450(now)
        reading, c1 = src.c1001(now)
        out.append(fusion.update(now, frame, ld, reading, c1).to_dict())
    return out


@pytest.mark.parametrize("scenario", ["demo", "random"])
@pytest.mark.parametrize("seed", [1, 2, 3, 42])
def test_300_ticks_validate(scenario, seed):
    for i, snap in enumerate(run(scenario, seed)):
        assert validate_snapshot(snap) == [], f"{scenario} seed {seed} tick {i}"
        assert snap["source"] == "sim"
        assert snap["sensors"] == {"ld2450": "sim", "c1001": "sim"}


def test_demo_has_still_person_locked_with_vitals_then_a_walker():
    snaps = run("demo", seed=1)
    assert snaps[0]["vitals"]["breath_rpm"] is None        # settle delay: no numbers yet
    assert snaps[0]["targets"][0]["locked"] is True
    amber = [s for s in snaps if any(t["triage"] == "amber" for t in s["targets"])]
    assert amber, "the sitter never became amber"
    first = next(i for i, s in enumerate(snaps) if s in amber)
    assert 30 <= first <= 90                                # 3 to 8 s settle delay (10 ticks per s)
    v = amber[-1]["vitals"]
    assert 12 <= v["breath_rpm"] <= 20 and 62 <= v["heart_bpm"] <= 95
    assert any(len(s["targets"]) == 2 for s in snaps), "the walker never crossed"
    assert any(t["moving"] and t["triage"] == "green" for s in snaps for t in s["targets"])


def test_random_stays_inside_the_sensor_envelope():
    for snap in run("random", seed=7, ticks=1500):
        assert len(snap["targets"]) <= 3
        for t in snap["targets"]:
            assert abs(t["angle_deg"]) <= 60.0 and t["range_m"] <= 4.0   # default gate


def test_same_seed_same_run_different_seed_differs():
    assert run("random", seed=5) == run("random", seed=5)
    assert run("random", seed=5) != run("random", seed=6)


def test_vitals_only_when_someone_is_locked():
    for snap in run("random", seed=3, ticks=1500):
        v = snap["vitals"]
        if v["target_id"] is None:
            assert v["breath_rpm"] is None and v["heart_bpm"] is None


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValueError):
        SimSource("nope", seed=1)


def test_from_env(monkeypatch):
    monkeypatch.setenv("SIM_SCENARIO", "random")
    monkeypatch.setenv("SIM_SEED", "9")
    src = SimSource.from_env()
    assert (src.scenario, src.seed) == ("random", 9)
