# Data contract (v1)

Single source of truth for what the server sends the UI and the rules fusion follows to build it.
Implemented by `pi/pulse/state.py` (Python) and mirrored by `ui/contract.js` (enums).
Change all three together, with tests, and bump `v`.

## Transport

- WebSocket at `/ws` on port 8000. Server sends one `snapshot` message every **100 ms** (10 Hz).
- `GET /api/snapshot` returns the latest snapshot as JSON (debugging).
- All messages are JSON objects with a `type` field.

## Server to client: `snapshot`

```json
{
  "type": "snapshot",
  "v": 1,
  "t": 1791600000.12,
  "source": "sim",
  "gate": {"max_range_m": 4.0, "max_angle_deg": 60},
  "targets": [
    {
      "id": 1,
      "x_mm": -420,
      "y_mm": 1830,
      "range_m": 1.88,
      "angle_deg": -12.9,
      "speed_cms": -12,
      "moving": true,
      "triage": "green",
      "locked": false,
      "last_seen_s": 0.0
    },
    {
      "id": 2,
      "x_mm": 150,
      "y_mm": 1150,
      "range_m": 1.16,
      "angle_deg": 7.4,
      "speed_cms": 0,
      "moving": false,
      "triage": "amber",
      "locked": true,
      "last_seen_s": 0.0
    }
  ],
  "vitals": {
    "target_id": 2,
    "presence": true,
    "moving": false,
    "breath_rpm": 16,
    "heart_bpm": 72,
    "settled": true,
    "age_s": 0.4
  },
  "sensors": {"ld2450": "sim", "c1001": "sim"},
  "contacts": [
    {"id": 1, "first_seen": 1791599950.0, "last_seen": 1791600000.1, "triage": "green",
     "last_breath_rpm": null, "last_heart_bpm": null},
    {"id": 2, "first_seen": 1791599961.5, "last_seen": 1791600000.1, "triage": "amber",
     "last_breath_rpm": 16, "last_heart_bpm": 72}
  ]
}
```

### Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `v` | int | Contract version. Currently 1. |
| `t` | float | Unix time (s) the snapshot was built. |
| `source` | `"sim"` \| `"live"` \| `"replay"` | Where the data came from. UI shows a badge; otherwise UI treats all the same. |
| `gate.max_range_m` | float | Targets farther than this are dropped. Default 4.0. UI scales the radar to it. |
| `gate.max_angle_deg` | float | Targets with \|angle\| above this are dropped. Default 60. |
| `targets` | list, 0 to 3 | People currently tracked. |
| `targets[].id` | int 1 to 3 | Stable track id (not the LD2450 slot). Freed ids are reused. |
| `targets[].x_mm` | int | Left/right of the sensor. **Negative = left** (from the holder's view). |
| `targets[].y_mm` | int | Straight out from the sensor. Always >= 0. |
| `targets[].range_m` | float, 2 dp | `hypot(x, y) / 1000`. |
| `targets[].angle_deg` | float, 1 dp | `degrees(atan2(x, y))`. 0 = straight ahead, negative = left. |
| `targets[].speed_cms` | int | Radial speed. **Negative = approaching** the sensor (parser normalizes). |
| `targets[].moving` | bool | See fusion rules. |
| `targets[].triage` | `"green"` \| `"amber"` \| `"gray"` | See fusion rules. |
| `targets[].locked` | bool | True for the one target the vitals belong to. |
| `targets[].last_seen_s` | float | 0 when detected this frame; grows while the track is held after dropping out. |
| `vitals.target_id` | int \| null | Locked target, or null if nobody is in the lock cone. |
| `vitals.presence` | bool | C1001 says a person is present. |
| `vitals.moving` | bool \| null | C1001 movement state (null if unknown). |
| `vitals.breath_rpm` | int \| null | Breaths/min, 10 to 25, else null. |
| `vitals.heart_bpm` | int \| null | Beats/min, 45 to 150, else null. The C1001 is rated accurate 60 to 100 but reports outside it. |
| `vitals.settled` | bool | True once both readings have been non-null for 3 s. |
| `vitals.age_s` | float \| null | Seconds since the last C1001 vitals frame. |
| `sensors.*` | `"ok"` \| `"warming"` \| `"stale"` \| `"offline"` \| `"sim"` | Per-sensor health. `stale` = no frame for > 1 s. |
| `contacts` | list | Everyone seen this session, most recent first, max 20. |

## Client to server

| Message | Effect |
| --- | --- |
| `{"type": "set_gate", "max_range_m": 2.0}` | Change range gate. Allowed: 1.0 to 6.0. `max_angle_deg` optional, 15 to 60. |
| `{"type": "reset_contacts"}` | Clear the contact log (between demo runs). |

Unknown or invalid messages are ignored and logged. Selection of a dot is UI-only state, not sent.

## Fusion rules

1. **Convert**: LD2450 target to `range_m`, `angle_deg`.
2. **Gate, with hysteresis**: a new track starts only from a detection inside the gate
   (`range_m <= gate.max_range_m` and `|angle_deg| <= gate.max_angle_deg`). An existing track keeps taking
   detections out to gate + 0.3 m / + 5 deg and is dropped once it is beyond that. A track between the gate and
   gate + margin stays alive (same id, same contact) but is **not** in `targets` and cannot lock, so `targets`
   never holds anything beyond the gate.
3. **Associate**: each track predicts where it is now from its velocity (a moving track coasts on that
   prediction for up to 1 s undetected; a still track does not coast). Detections are matched one to one to the
   predicted positions: the matching with the most pairs, then the least total distance. A pair farther than
   0.6 m is never made. Unmatched detections inside the gate start new tracks with the lowest free id (1 to 3).
4. **Smooth**: alpha-beta filter on position and velocity (alpha 0.3, beta 0.15).
   **Live x filter** (`pi/pulse/tracker.py`, on for live, off for sim, env `PULSE_XFILTER=1/0` forces it): the
   shown `x_mm` goes through an outlier gate (1 m from the recent median, 3 in a row restarts), a median of 5,
   an EMA (0.35) and an 80 mm deadband; association keeps using the alpha-beta position. The velocity residual is
   taken against the velocity's own prediction and clipped to 250 mm. A new track is shown (and held) only from
   its 3rd detection; until then it is dropped after 0.3 s undetected.
5. **Moving**: `|speed_cms| >= 10` or the track moved more than 0.25 m in the last 1 s.
6. **Hold**: a track not detected is kept for 3 s (`last_seen_s` counts up), then dropped. If the C1001
   reported `presence` within the last 2 s and the held track is inside the lock cone, keep holding it (still
   survivor case; the 2 s grace rides out one false or missed 1 Hz poll). `vitals.presence` is always the raw
   latest reading.
7. **Lock cone**: `|angle_deg| <= 20` and `0.4 <= range_m <= 1.5`. If several tracks qualify, lock the one
   closest to 0 deg. That track gets `locked: true` and `vitals.target_id`.
8. **Triage**:
   - `green`: moving.
   - `amber`: not moving, locked, C1001 presence, and `breath_rpm` not null. Label: "breathing".
   - `gray`: anything else (not assessed yet).
9. **Vitals sanity**: values outside 10 to 25 (breath) or 45 to 150 (heart), or 0, become null.
10. **Contacts**: one entry per track id per appearance; update `last_seen`, `triage`, and the last
    non-null vitals while locked.
