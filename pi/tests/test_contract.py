"""Contract tests: docs/data-contract.md, pulse/state.py and ui/contract.js must agree."""
import copy
import json
import re
from pathlib import Path

import pytest

from pulse import state
from pulse.state import Contact, Gate, Snapshot, Target, Vitals, validate_snapshot

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "data-contract.md"
CONTRACT_JS = ROOT / "ui" / "contract.js"


def doc_example() -> dict:
    """The first ```json block in the contract doc is the canonical example snapshot."""
    m = re.search(r"```json\n(.*?)\n```", DOC.read_text(), re.S)
    assert m, "no json block found in docs/data-contract.md"
    return json.loads(m.group(1))


def example_snapshot() -> Snapshot:
    """The doc example built from dataclasses, from raw x/y so the rounding rules are exercised."""
    return Snapshot(
        t=1791600000.12,
        source="sim",
        gate=Gate(max_range_m=4.0, max_angle_deg=60),
        targets=[
            Target(id=1, x_mm=-420, y_mm=1830, speed_cms=-12, moving=True, triage="green", locked=False),
            Target(id=2, x_mm=150, y_mm=1150, speed_cms=0, moving=False, triage="amber", locked=True),
        ],
        vitals=Vitals(target_id=2, presence=True, moving=False, breath_rpm=16, heart_bpm=72,
                      settled=True, age_s=0.4),
        sensors={"ld2450": "sim", "c1001": "sim"},
        contacts=[
            Contact(id=1, first_seen=1791599950.0, last_seen=1791600000.1, triage="green"),
            Contact(id=2, first_seen=1791599961.5, last_seen=1791600000.1, triage="amber",
                    last_breath_rpm=16, last_heart_bpm=72),
        ],
    )


# ---- the doc example and round trip ------------------------------------------------------------

def test_doc_example_validates():
    assert validate_snapshot(doc_example()) == []


def test_snapshot_round_trips_to_doc_shape():
    d = example_snapshot().to_dict()
    assert d == doc_example()
    assert list(d) == list(doc_example())  # same key order as the doc
    assert json.loads(json.dumps(d)) == d
    assert validate_snapshot(d) == []


def test_target_rounding_rules():
    t = Target(id=1, x_mm=-1234, y_mm=2345, speed_cms=3, moving=True, triage="green").to_dict()
    assert t["range_m"] == 2.65 and t["angle_deg"] == -27.8
    assert isinstance(t["x_mm"], int) and isinstance(t["speed_cms"], int)


def test_default_snapshot_is_valid_and_empty():
    d = Snapshot(t=1.0, source="live").to_dict()
    assert validate_snapshot(d) == []
    assert d["targets"] == [] and d["contacts"] == []
    assert d["sensors"] == {"ld2450": "offline", "c1001": "offline"}
    assert d["vitals"]["target_id"] is None


def test_unlocked_with_null_vitals_is_valid():
    d = doc_example()
    d["targets"][1]["locked"] = False
    d["vitals"].update(target_id=None, moving=None, breath_rpm=None, heart_bpm=None, settled=False, age_s=None)
    assert validate_snapshot(d) == []


# ---- every kind of violation is caught ---------------------------------------------------------

def _extra_target(d):
    d["targets"].append({**d["targets"][0], "id": 3})
    d["targets"].append({**d["targets"][0], "id": 3})  # 4 targets, one duplicate id


def _set(path, value):
    """Mutation that sets d[path[0]][path[1]]... to value."""
    def mutate(d):
        node = d
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
    return mutate


def _delete(path):
    def mutate(d):
        node = d
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]
    return mutate


def _many_contacts(d):
    d["contacts"] = [{**d["contacts"][0]} for _ in range(21)]


VIOLATIONS = [
    # top level
    ("wrong type", _set(["type"], "telemetry"), "type: expected 'snapshot'"),
    ("wrong version", _set(["v"], 2), "v: expected 1"),
    ("version as string", _set(["v"], "1"), "v: expected 1"),
    ("bad source", _set(["source"], "hardware"), "source: expected one of"),
    ("missing key", _delete(["gate"]), "snapshot.gate: missing key"),
    ("extra key", _set(["debug"], True), "snapshot.debug: unexpected key"),
    ("t not a number", _set(["t"], "now"), "t: expected number"),
    # gate
    ("gate range too big", _set(["gate", "max_range_m"], 9.0), "gate.max_range_m"),
    ("gate angle too small", _set(["gate", "max_angle_deg"], 5), "gate.max_angle_deg"),
    ("gate range as string", _set(["gate", "max_range_m"], "4"), "gate.max_range_m: expected number"),
    # targets
    ("four targets", _extra_target, "expected at most 3"),
    ("duplicate target ids", _set(["targets", 1, "id"], 1), "duplicate ids"),
    ("target id 0", _set(["targets", 0, "id"], 0), "targets[0].id"),
    ("target id 4", _set(["targets", 0, "id"], 4), "targets[0].id"),
    ("bad triage", _set(["targets", 0, "triage"], "red"), "targets[0].triage"),
    ("x_mm is a bool", _set(["targets", 0, "x_mm"], True), "targets[0].x_mm: expected int"),
    ("negative y_mm", _set(["targets", 0, "y_mm"], -5), "targets[0].y_mm"),
    ("range disagrees with x/y", _set(["targets", 0, "range_m"], 3.0), "targets[0].range_m"),
    ("angle sign flipped", _set(["targets", 0, "angle_deg"], 12.9), "targets[0].angle_deg"),
    ("moving not a bool", _set(["targets", 0, "moving"], "yes"), "targets[0].moving"),
    ("negative last_seen_s", _set(["targets", 0, "last_seen_s"], -1.0), "targets[0].last_seen_s"),
    ("target missing key", _delete(["targets", 0, "speed_cms"]), "targets[0].speed_cms: missing key"),
    # lock / vitals consistency
    ("two locked targets", _set(["targets", 0, "locked"], True), "at most 1 allowed"),
    ("locked id differs from vitals.target_id", _set(["vitals", "target_id"], 1),
     "does not match vitals.target_id"),
    ("vitals.target_id points at nothing", _set(["vitals", "target_id"], 3), "does not match any target"),
    ("vitals.target_id points at unlocked target", _set(["targets", 1, "locked"], False),
     "target 2 is not locked"),
    ("locked target but null vitals.target_id", _set(["vitals", "target_id"], None),
     "does not match vitals.target_id"),
    # vitals
    ("breath too high", _set(["vitals", "breath_rpm"], 30), "vitals.breath_rpm"),
    ("breath is a float", _set(["vitals", "breath_rpm"], 16.5), "vitals.breath_rpm: expected int"),
    ("heart is zero", _set(["vitals", "heart_bpm"], 0), "vitals.heart_bpm"),
    ("presence as string", _set(["vitals", "presence"], "yes"), "vitals.presence: expected bool"),
    ("negative age_s", _set(["vitals", "age_s"], -0.1), "vitals.age_s"),
    ("vitals missing key", _delete(["vitals", "settled"]), "vitals.settled: missing key"),
    # sensors
    ("bad sensor status", _set(["sensors", "ld2450"], "broken"), "sensors.ld2450"),
    ("missing sensor", _delete(["sensors", "c1001"]), "sensors.c1001: missing key"),
    ("unknown sensor", _set(["sensors", "gps"], "ok"), "sensors.gps: unexpected key"),
    # contacts
    ("21 contacts", _many_contacts, "expected at most 20"),
    ("bad contact triage", _set(["contacts", 0, "triage"], "blue"), "contacts[0].triage"),
    ("contact breath out of range", _set(["contacts", 1, "last_breath_rpm"], 4), "contacts[1].last_breath_rpm"),
    ("contacts out of order", _set(["contacts", 0, "last_seen"], 1791599970.0), "not ordered by last_seen"),
    ("last_seen before first_seen", _set(["contacts", 1, "last_seen"], 1791599900.0), "is before first_seen"),
]


@pytest.mark.parametrize("mutate,expected", [(m, e) for _, m, e in VIOLATIONS],
                         ids=[name for name, _, _ in VIOLATIONS])
def test_violation_is_caught(mutate, expected):
    d = copy.deepcopy(doc_example())
    mutate(d)
    errors = validate_snapshot(d)
    assert any(expected in e for e in errors), f"expected {expected!r} in {errors}"


def test_not_a_dict_is_a_violation():
    assert validate_snapshot([]) != []  # type: ignore[arg-type]


# ---- ui/contract.js stays in sync with state.py ------------------------------------------------

def js_exports() -> dict:
    out = {}
    for line in CONTRACT_JS.read_text().splitlines():
        m = re.match(r"^export const (\w+) = (.+);$", line)
        if m:
            out[m.group(1)] = json.loads(m.group(2))
    return out


def test_contract_js_matches_state_py():
    js = js_exports()
    assert js["CONTRACT_VERSION"] == state.CONTRACT_VERSION
    assert js["SOURCES"] == list(state.SOURCES)
    assert sorted(js["TRIAGE"].values()) == sorted(state.TRIAGES)
    assert sorted(js["TRIAGE_LABELS"]) == sorted(state.TRIAGES)
    assert js["SENSOR_NAMES"] == list(state.SENSOR_NAMES)
    assert js["SENSOR_STATUSES"] == list(state.SENSOR_STATUSES)
    assert js["MAX_TARGETS"] == state.MAX_TARGETS
    assert js["MAX_CONTACTS"] == state.MAX_CONTACTS
    assert js["TARGET_IDS"] == list(state.TARGET_IDS)
    assert js["LOCK_CONE"] == {"maxAngleDeg": state.LOCK_CONE_DEG, "minRangeM": state.LOCK_MIN_M,
                               "maxRangeM": state.LOCK_MAX_M}
    assert js["DEFAULT_GATE"] == Gate().to_dict()
    assert js["GATE_LIMITS"] == {"range_m": list(state.GATE_RANGE_LIMITS),
                                 "angle_deg": list(state.GATE_ANGLE_LIMITS)}
    assert js["BREATH_RANGE"] == list(state.BREATH_RANGE)
    assert js["HEART_RANGE"] == list(state.HEART_RANGE)
    assert js["HOLD_S"] == state.HOLD_S
    assert js["STALE_S"] == state.STALE_S


def test_contract_version_matches_doc():
    assert f"# Data contract (v{state.CONTRACT_VERSION})" in DOC.read_text()
