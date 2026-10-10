// Mirrors docs/data-contract.md (v1) and pi/pulse/state.py. Change all three together, with tests, and bump v.
// Keep every export on ONE line as a JSON literal: pi/tests/test_contract.py parses this file to check it
// has not drifted from state.py. No colors here; style.css owns those, keyed by the TRIAGE values.

export const CONTRACT_VERSION = 1;

export const SOURCES = ["sim", "live", "replay"];
export const TRIAGE = {"GREEN": "green", "AMBER": "amber", "GRAY": "gray"};
export const TRIAGE_LABELS = {"green": "MOVING", "amber": "BREATHING", "gray": "NOT ASSESSED"};

export const SENSOR_NAMES = ["ld2450", "c1001"];
export const SENSOR_STATUSES = ["ok", "warming", "stale", "offline", "sim"];

export const MAX_TARGETS = 3;
export const MAX_CONTACTS = 20;
export const TARGET_IDS = [1, 2, 3];

export const LOCK_CONE = {"maxAngleDeg": 20, "minRangeM": 0.4, "maxRangeM": 1.5};
export const DEFAULT_GATE = {"max_range_m": 4.0, "max_angle_deg": 60};
export const GATE_LIMITS = {"range_m": [1.0, 6.0], "angle_deg": [15, 60]};

export const BREATH_RANGE = [10, 25];
export const HEART_RANGE = [60, 100];
export const HOLD_S = 3.0;
export const STALE_S = 1.0;
