"""Minimal fusion checks (T7 adds the table-driven suite). Time is explicit, so everything is deterministic."""
import pytest

from pulse.fusion import Fusion
from pulse.sensors.c1001 import C1001Reading
from pulse.sensors.ld2450 import Ld2450Frame, Ld2450Target
from pulse.state import validate_snapshot


def frame(t: float, *targets: tuple[int, int, int]) -> Ld2450Frame:
    return Ld2450Frame(t=t, targets=[Ld2450Target(x, y, s) for x, y, s in targets])


def vitals(t: float, presence=True, breath=16, heart=72, moving=False) -> C1001Reading:
    return C1001Reading(t=t, presence=presence, moving=moving, breath_rpm=breath, heart_bpm=heart)


def step(f: Fusion, t: float, fr=None, c1=None, ld="sim", c1s="sim"):
    snap = f.update(t, fr, ld, c1, c1s).to_dict()
    assert validate_snapshot(snap) == []
    return snap


def test_still_breathing_person_in_cone_is_locked_and_amber():
    f = Fusion("sim")
    s = step(f, 0.0, frame(0.0, (100, 1000, 0)), vitals(0.0))
    t = s["targets"][0]
    assert (t["locked"], t["moving"], t["triage"]) == (True, False, "amber")
    assert s["vitals"]["target_id"] == t["id"] and s["vitals"]["breath_rpm"] == 16
    assert s["contacts"][0]["last_breath_rpm"] == 16 and s["contacts"][0]["triage"] == "amber"


def test_out_of_range_vitals_become_null_and_never_amber():
    for breath, heart in [(30, 72), (0, 72), (16, 160), (16, 44), (16, 0), (None, None)]:
        f = Fusion("sim")
        s = step(f, 0.0, frame(0.0, (0, 1000, 0)), vitals(0.0, breath=breath, heart=heart))
        v = s["vitals"]
        assert v["breath_rpm"] is (16 if breath == 16 else None)
        assert v["heart_bpm"] is (72 if heart == 72 else None)
        if breath != 16:
            assert s["targets"][0]["triage"] == "gray"


@pytest.mark.parametrize("heart", [45, 59, 101, 120, 150])
def test_heart_outside_the_rated_60_to_100_still_counts(heart):
    f = Fusion("sim")
    s = step(f, 0.0, frame(0.0, (0, 1000, 0)), vitals(0.0, heart=heart))
    assert s["vitals"]["heart_bpm"] == heart and s["contacts"][0]["last_heart_bpm"] == heart


def test_no_vitals_when_nobody_is_in_the_cone():
    f = Fusion("sim")
    s = step(f, 0.0, frame(0.0, (1500, 2500, 0)), vitals(0.0))
    assert s["vitals"]["target_id"] is None
    assert s["vitals"]["breath_rpm"] is None and s["vitals"]["heart_bpm"] is None
    assert s["targets"][0]["triage"] == "gray"


def test_settled_after_three_seconds_of_both_readings():
    f = Fusion("sim")
    assert step(f, 0.0, frame(0.0, (0, 1000, 0)), vitals(0.0))["vitals"]["settled"] is False
    assert step(f, 2.9, frame(2.9, (0, 1000, 0)), vitals(2.9))["vitals"]["settled"] is False
    assert step(f, 3.1, frame(3.1, (0, 1000, 0)), vitals(3.1))["vitals"]["settled"] is True


def test_set_gate_drops_far_targets_on_next_tick():
    f = Fusion("sim")
    assert len(step(f, 0.0, frame(0.0, (0, 3500, 0)))["targets"]) == 1
    assert f.set_gate(2.0) is True
    s = step(f, 0.1, frame(0.1, (0, 3500, 0)))
    assert s["gate"]["max_range_m"] == 2.0 and s["targets"] == []


@pytest.mark.parametrize("bad", [0.5, 7.0, True, "2", None, float("nan")])
def test_set_gate_rejects_invalid_range(bad):
    f = Fusion("sim")
    assert f.set_gate(bad) is False
    assert f.gate.max_range_m == 4.0


def test_set_gate_angle_limits():
    f = Fusion("sim")
    assert f.set_gate(3.0, 10) is False and f.gate.max_range_m == 4.0   # invalid angle changes nothing
    assert f.set_gate(3.0, 30) is True and (f.gate.max_range_m, f.gate.max_angle_deg) == (3.0, 30.0)


def test_dropped_target_is_held_three_seconds_then_removed():
    f = Fusion("sim")
    step(f, 0.0, frame(0.0, (1500, 2500, 0)))
    s = step(f, 2.0, frame(2.0))
    assert [t["last_seen_s"] for t in s["targets"]] == [2.0]
    assert step(f, 3.2, frame(3.2))["targets"] == []


def test_still_survivor_in_cone_is_held_while_c1001_reports_presence():
    f = Fusion("sim")
    step(f, 0.0, frame(0.0, (0, 1000, 0)), vitals(0.0))
    for i in range(1, 100):                                  # 10 s of empty LD2450 frames
        s = step(f, i * 0.1, frame(i * 0.1), vitals(i * 0.1))
    t = s["targets"][0]
    assert t["last_seen_s"] > 3.0 and t["locked"] and t["triage"] == "amber"
    # presence gone: one false poll is within the grace, so the survivor is still held
    s = step(f, 10.1, frame(10.1), vitals(10.1, presence=False, breath=None, heart=None))
    assert len(s["targets"]) == 1 and s["targets"][0]["triage"] == "gray"   # held, but no longer amber
    s = step(f, 11.5, frame(11.5), vitals(11.5, presence=False, breath=None, heart=None))
    assert len(s["targets"]) == 1
    # false for longer than PRESENCE_GRACE_S (2 s) after the last true reading at 9.9: the track expires
    s = step(f, 12.0, frame(12.0), vitals(12.0, presence=False, breath=None, heart=None))
    assert s["targets"] == []


def test_ids_are_stable_across_slot_swaps_and_reused_when_free():
    f = Fusion("sim")
    s = step(f, 0.0, frame(0.0, (-1000, 2000, 0), (1000, 2000, 0)))
    ids = {t["x_mm"] < 0: t["id"] for t in s["targets"]}
    s = step(f, 0.1, frame(0.1, (1010, 2000, 0), (-990, 2000, 0)))     # slot order swapped
    assert {t["x_mm"] < 0: t["id"] for t in s["targets"]} == ids
    step(f, 5.0, frame(5.0))                                            # both expire
    s = step(f, 5.1, frame(5.1, (0, 2500, 0)))
    assert [t["id"] for t in s["targets"]] == [1]


def test_moving_by_speed_or_displacement():
    f = Fusion("sim")
    assert step(f, 0.0, frame(0.0, (0, 2000, 15)))["targets"][0]["moving"] is True
    f = Fusion("sim")
    step(f, 0.0, frame(0.0, (0, 2000, 0)))
    s = step(f, 0.9, frame(0.9, (0, 2000, 0)))
    assert s["targets"][0]["moving"] is False
    f = Fusion("sim")
    for i in range(10):                                      # drifting 40 mm per tick with speed 0
        s = step(f, i * 0.1, frame(i * 0.1, (0, 2000 + 40 * i, 0)))
    assert s["targets"][0]["moving"] is True


def test_closest_to_axis_wins_the_lock():
    f = Fusion("sim")
    s = step(f, 0.0, frame(0.0, (300, 1000, 0), (50, 1100, 0)), vitals(0.0))
    locked = [t for t in s["targets"] if t["locked"]]
    assert len(locked) == 1 and locked[0]["x_mm"] == 50


def test_reset_contacts_and_cap():
    f = Fusion("sim")
    step(f, 0.0, frame(0.0, (0, 2000, 0)))
    assert len(step(f, 0.1, frame(0.1, (0, 2000, 0)))["contacts"]) == 1
    f.reset_contacts()
    s = step(f, 0.2, frame(0.2, (0, 2000, 0)))
    assert len(s["contacts"]) == 1 and s["contacts"][0]["first_seen"] == 0.2


def test_sensor_status_is_passed_through_and_offline_gives_no_targets():
    f = Fusion("live")
    s = step(f, 0.0, None, None, ld="offline", c1s="offline")
    assert s["source"] == "live" and s["sensors"] == {"ld2450": "offline", "c1001": "offline"}
    assert s["targets"] == [] and s["vitals"]["presence"] is False


def test_gate_hysteresis_hides_but_keeps_the_track_in_the_margin():
    f = Fusion("sim")
    s = step(f, 0.0, frame(0.0, (0, 3900, 0)))
    first = s["contacts"][0]["first_seen"]
    s = step(f, 0.1, frame(0.1, (0, 4150, 0)))                 # in the margin (4.0 to 4.3 m): hidden, kept
    s = step(f, 0.2, frame(0.2, (0, 4200, 0)))
    assert s["targets"] == [] and len(s["contacts"]) == 1
    s = step(f, 0.3, frame(0.3, (0, 3950, 0)))                 # back inside: the same id and contact
    s = step(f, 0.4, frame(0.4, (0, 3900, 0)))
    assert [t["id"] for t in s["targets"]] == [1]
    assert len(s["contacts"]) == 1 and s["contacts"][0]["first_seen"] == first
    for i in range(5, 12):                                      # walks out: 4.0 to 4.6 m, never shown again
        s = step(f, i * 0.1, frame(i * 0.1, (0, 3500 + 100 * i, 0)))
        if i > 5:
            assert s["targets"] == []
    s = step(f, 4.5, frame(4.5))                                # gone: dropped after the hold, never shown
    assert s["targets"] == [] and f._tracks == {} and len(s["contacts"]) == 1


def test_a_new_track_never_starts_in_the_gate_margin():
    f = Fusion("sim")
    s = step(f, 0.0, frame(0.0, (0, 4200, 0)))
    assert s["targets"] == [] and s["contacts"] == [] and f._tracks == {}


def test_hidden_track_in_the_margin_cannot_lock():
    f = Fusion("sim")
    assert f.set_gate(1.0)
    s = step(f, 0.0, frame(0.0, (0, 950, 0)), vitals(0.0))
    assert s["targets"][0]["locked"]
    s = step(f, 0.1, frame(0.1, (0, 1250, 0)), vitals(0.1))   # 1.1 m smoothed: in the cone, past the 1 m gate
    assert s["targets"] == [] and s["vitals"]["target_id"] is None and s["vitals"]["breath_rpm"] is None


def test_a_track_never_jumps_further_than_associate_m():
    f = Fusion("sim")
    step(f, 0.0, frame(0.0, (-1000, 2000, 0)))
    s = step(f, 0.1, frame(0.1, (0, 2000, 0)))                  # 1 m away: a new person, not a jump
    assert sorted((t["id"], t["x_mm"], t["last_seen_s"]) for t in s["targets"]) == [(1, -1000, 0.1), (2, 0, 0.0)]


def test_crossing_walkers_keep_their_ids_through_a_merged_frame():
    f = Fusion("sim")
    ids = {}
    for i in range(20):                                         # A goes right at y 1850, B left at y 2150
        t = i * 0.1
        ax, bx = -1000 + 100 * i, 1000 - 100 * i
        dets = [(ax, 1850, 0), (bx, 2150, 0)] if abs(ax - bx) > 400 else [((ax + bx) // 2, 2000, 0)]
        s = step(f, t, frame(t, *dets))
        if i < 5:
            ids = {"A" if tg["y_mm"] < 2000 else "B": tg["id"] for tg in s["targets"]}
    assert {"A" if tg["x_mm"] > 0 else "B": tg["id"] for tg in s["targets"]} == ids
