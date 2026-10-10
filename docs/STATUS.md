Update this when a phase changes or a prompt finishes. What to do is in docs/PLAYBOOK.md.

# Status

> # >>> WE ARE HERE: PHASE 1 (Unbox + start the parsers) <<<
>
> - **Ari:** SD card decided (a new card, being flashed with Raspberry Pi Imager). ARI-1 is done (on `main`).
>   Next: Phase 2 boot + SSH as soon as the card is ready.
> - **Alex:** ALEX-1 (done: C1001 parser, reader, dump tool, tests on `main`).
> - **EE:** Phase 1 checklist (inventory, photos, pin labels, cable connectors, power supply).

**Deadlines:** Devpost final Sun Oct 11 10:00 AM, commits stop 11:00 AM, repo public at submission.
**Gate:** live dots + live vitals on the screen by 10 PM Sat; no new features after it.

## Phases

Tick boxes live only in docs/PLAYBOOK.md; this table is the summary.

| Phase | Name | Owner(s) | Status | Prompts |
| --- | --- | --- | --- | --- |
| 0 | Done so far (T0 to T4) | All | Done | T0 to T4 |
| 1 | Unbox + start the parsers | EE, Ari, Alex | In progress | ARI-1 (done), ALEX-1 |
| 2 | Pi + screen boot | EE, Ari, Alex | Not started | Manual only |
| 3 | Pi setup + serial ports | Ari, EE | Not started | ARI-2 |
| 4 | Sensors live | EE, Ari, Alex | Not started | ARI-3, ALEX-2 |
| 5 | Full app live: the gate (10 PM latest) | Ari, Alex, EE | Not started | ARI-4, ALEX-3, ALEX-4 |
| 6 | Judge-proof | Ari, EE, Alex | Not started | ARI-5 |
| 7 | Saturday night: rehearse + rough submit | All | Not started | Devpost draft (Claude chat), S7 buzzer (optional) |
| 8 | Sunday | All | Not started | ARI-6 |

## Measured on hardware

One row per blank in the PLAYBOOK checklists, then a few extra values the prompts ask for. Copy the final numbers
into docs/hardware.md too.

| Phase | What | Value |
| --- | --- | --- |
| 1 | LD2450 pin order (labels) | |
| 1 | C1001 pin order (labels) | |
| 1 | Sensor cable connectors: plan if lab jumpers don't fit | |
| 2 | Screen power on GPIO: 5 V pin | |
| 2 | Screen power on GPIO: GND pin | |
| 2 | `vcgencmd measure_temp` idle (C) | |
| 2 | Pi IP (`hostname -I`) | |
| 3 | UI fps on the Pi (`/?fps=1`) | |
| 3 | UART3 device name | |
| 3 | Pi 5 V pins (V, multimeter) | |
| 4 | LD2450 5 V pin / GND pin | |
| 4 | C1001 5 V pin / GND pin | |
| 4 | LD2450 TX idle (V) | |
| 4 | C1001 TX idle (V) | |
| 4 | LD2450 max range walking away (m) | |
| 4 | LD2450 left/right edge at 2 m (deg) | |
| 4 | LD2450 behind the panel: detected? | |
| 4 | LD2450 sitting still: drops out after (s, or never) | |
| 4 | C1001 presence after (s) | |
| 4 | C1001 breathing after (s) / value (/min) | |
| 4 | C1001 heart rate after (s) / value (bpm) | |
| 4 | Phone/watch heart rate at the same time (bpm) | |
| 4 | C1001 behind the panel: works? | |
| 6 | Power bank 15 min: `vcgencmd get_throttled` | |
| 6 | Power bank 15 min: temp (C) | |
| extra (ARI-2) | Pi user@host / OS / session + compositor / Chromium binary | |
| extra (ARI-2) | UART0 loopback (pin 8 to 10, 256000) / UART3 loopback (pin 7 to 29, 115200) | |
| extra (ARI-3) | LD2450 x sign: holder's left is raw + or - (`X_SIGN`) | |
| extra (ARI-3) | LD2450 speed sign: approaching is raw + or - (`SPEED_SIGN`) | |
| extra (ARI-3) | LD2450 targets at once / frames/s / bad frames in 2 min | |
| extra (ALEX-2) | C1001 working distance range (m) | |
| extra (ARI-5) | Power bank model + capacity / `get_throttled` idle and under load / runtime | |
| extra (ARI-5) | Touch on the 7": drawer scrolls / taps at screen edges | |
| extra (ARI-4) | Live: lock acquired in (s) / dot jitter / ids swap | |

## Notes
- T5 to T9 and S1 to S7 were folded into PLAYBOOK phases 1 to 8 (in the notes below, A1 = ARI-1 and CS2 = Alex).
- T1: contract is in `pi/pulse/state.py` + `ui/contract.js`; `pi/tests/test_contract.py` checks the doc
  example, the dataclass round trip, every violation kind, and that contract.js matches state.py.
  Keep each `export const` in contract.js on one line (the test parses it).
- T1: Mac venv is Python 3.12 (`.venv`, from Homebrew). `cd pi && ../.venv/bin/pytest -q` runs the tests.
- T1: rounding the doc doesn't specify: t and contact times 2 dp, last_seen_s and age_s 1 dp.
- T1: server isn't built yet (main.py is a placeholder), so there is no sim run to check until T2.
- T2: run it with `cd pi && PULSE_SOURCE=sim SIM_SCENARIO=demo ../.venv/bin/python -m pulse.main`, then open
  http://localhost:8000/debug (raw snapshot, msg rate, gate buttons) or `curl localhost:8000/api/snapshot`.
  Also `uvicorn pulse.main:create_app --factory`; there is no module-level `app` on purpose (importing
  `pulse.main` in tests must not build a source).
- T2: source interface is `pulse/sources.py`: a Source gives `ld2450(now) -> (Ld2450Frame | None, status)` and
  `c1001(now) -> (C1001Reading | None, status)`. Reading types live in `sensors/ld2450.py` and `sensors/c1001.py`
  (T5/T6 add the parsers and readers next to them). `live` and `replay` are `StubSource` for now: both sensors
  `offline`, no targets. `PULSE_SOURCE` defaults to `sim` on macOS, `live` elsewhere.
- T2: sim scenarios: `SIM_SCENARIO=demo|random`, `SIM_SEED=<int>` (the seed is logged at start when unset).
  Demo: sitter at about (150, 1200) mm locks ~3 to 8 s after start; a walker crosses every 20 s, alternating
  direction, mostly beyond the 4 m default gate at the edges. Random dropouts of still people (1 to 2.5 s) are
  random-scenario only, so the demo dot never flickers.
- T2: `contacts[].id` is the track id (decided with the user, matches the doc example). Ids repeat after reuse:
  a person who leaves and comes back is a new entry. The entry with the newest `last_seen` for an id is the live
  dot. T4's drawer should select by that rule. A contact's `last_seen` updates for every tick the track is in
  the snapshot (including the hold), and freezes when the track is dropped.
- T2: fusion rules known to be rough, for T7: gate is applied to smoothed position with no hysteresis (a person
  hovering at the range limit can drop and re-enter as a new contact); a held track counts as still after 1 s
  without a detection; association is greedy nearest-neighbour; `set_gate` needs `max_range_m` (angle alone is
  ignored); the C1001 reading is trusted when its status is not stale/offline.
- T2: 92 tests pass (`cd pi && ../.venv/bin/pytest -q`). Checked by hand: /ws at 10.0 msg/s, set_gate from the
  debug page, `PULSE_SOURCE=live` reports both sensors offline.
- T3: `ui/index.html`, `radar.js`, `style.css`. Fixed 800x480 stage (scaled to fit other window sizes), one canvas
  plus DOM text. Simplified after review (it first shipped with glow, scanlines, trails, pings, a beat trace and a
  game-style font, which read as a video game): flat near-black, a faded 40 px square grid (CSS `#stage::before`),
  thin 120 deg wedge, 1 m rings labelled at the left edge, a dashed lock zone, one thin sweep line, flat dots.
  System sans font (no bundled font files). All colors are CSS custom properties; radar.js reads them once.
  `?fps=1` adds an fps counter.
- T3: on screen, all small: a 24 px status line (PULSE, source, two sensor dots), the vitals panel bottom left
  (40 px numbers, `settling...` when null, "No lock / Aim at a contact within 1.5 m" when idle), a 12 px legend
  bottom right built from `TRIAGE_LABELS`. Deliberately cut: clock, contact count, id labels, trails, pings, beat
  trace, reticle brackets, angle ticks. Legend, vitals panel and status line are the first things to remove if the
  user wants it sparser. T4 will add the contacts button and range buttons.
- T3: behaviors worth knowing: held dots (last_seen_s > 0) are hollow rings fading toward a 0.3 alpha floor (0.7 if
  locked) so a still survivor kept alive by C1001 presence stays visible; a track that leaves the snapshot fades out
  over 300 ms; the locked dot gets one thin ring. If `set_gate` narrows `max_angle_deg`, the wedge narrows with it.
  Heart and breath show only snapshot values, never invented. NO SIGNAL shows when the socket closes, errors, or
  sends nothing for 2 s; reconnect backoff is 0.5, 1, 2, 4, then 5 s.
- T3: `tools/ui_screenshots.py` (needs `playwright`, now in requirements-dev.txt, plus `python -m playwright install
  chromium`) starts its own sim server on :8010 and writes `docs/screenshots/t3-*.png`: settling, locked, walker,
  held from the real server; idle, 2 m / 30 deg gate, sensors down, NO SIGNAL from a mocked /ws. It exits non-zero on
  any page error. The demo sitter locks immediately (before numbers), so "no lock" is only reachable via the mock.
- T3: not yet checked on the Pi itself: 61 fps in headless Chromium on the Mac says nothing about a Pi 4. Check
  `/?fps=1` on the device in T8/T9. The frame loop is now just a sweep line and up to 3 dots.
- T3: type is now smaller than CLAUDE.md's "judged from about 1 m: big type, high contrast" gotcha assumes (numbers
  40 px, labels 12 to 13 px). Decide on the Pi at 1 m whether to bump the vitals numbers back up.
- T3: 93 tests pass.
- T4: new modules `ui/fmt.js` (text helpers), `card.js` (selection + card), `drawer.js`, `controls.js` (range buttons,
  wordmark long-press); `radar.js` owns the socket (`send`), hit-tests taps and draws the selection brackets.
  No contract change, no `v` bump: selection is UI-only. Screenshots in `docs/screenshots/t4-*.png`, made by
  `.venv/bin/python tools/ui_t4_shots.py` (real demo sim, real touch taps, a DOM check per shot, non-zero exit on a
  failed check or page error).
- T4: card is a 260 px side panel on the side away from its dot (swaps with a 370 to 430 px dead band if the dot
  crosses the middle), so the selected dot and the lock zone stay visible. Tap = nearest dot within 48 px. It shows
  range, bearing (`12 deg L`), MOVING/STILL, status word, time since first seen; locked: 64 px heart and breath
  (`settling...` on null); not locked: arrow + "Get within 1.5 m and aim at them" + live `m to go` / `Turn N deg` line.
- T4: the card follows the track id AND that contact's `first_seen`. If the id vanishes from `targets`, or comes back
  with a different `first_seen` (id reuse, or someone pressed reset), it reads SIGNAL LOST for 3 s and closes. A lost
  card shows only the last known position, never stale guidance or vitals.
- T4: drawer is the server's `contacts` list, newest first; a row is tappable only if it is the newest entry for its id
  and that id is in `targets` (T2's rule), others are dimmed "N s ago". Opening the drawer closes the card.
- T4: range buttons send `set_gate {max_range_m}` only (the angle gate is left alone) and highlight from
  `snapshot.gate`, so a gate changed from /debug lights the right button (or none, for e.g. 3 m).
- T4: reset = hold the PULSE wordmark 1.5 s (underline fills, toast "Contacts cleared"); lifting early does nothing.
  Status-bar buttons are small to look at but have a 48 px tall hit area that grows downward from the top edge.
- T4: things to know: a held track reads STILL with "Not detected for N s" (fusion's rule, see T2 notes); the toast sits
  over the device apex on purpose (nothing can be there); `tools/ui_screenshots.py` now prints paths outside the repo.
  Not tried on the real 7" DSI touch panel: Chromium kiosk touch + `touch-action: none` + the scrolling drawer need a
  check on the Pi in T8/T9 (does a finger drag scroll the drawer list, do taps register at the screen edges).
- T4: 93 tests pass (`test_server.py` now also checks the four new JS files are served with no external URLs).
- A1: `pi/pulse/sensors/ld2450.py` now has `Ld2450Parser` (pure, incremental: feed any chunks, resyncs on
  `AA FF 03 00`, checks `55 CC`, counts `good` / `bad` / `skipped_bytes`; `feed_with_raw` also returns each frame's
  30 bytes for recordings), command builders + `parse_ack` (bytes marked "verify against datasheet"; ACKs in the data
  stream are collected in `parser.acks`, never counted as bad), and `Ld2450Reader(port, baud=256000)`.
- A1: sign conventions are `X_SIGN` and `SPEED_SIGN` at the top of `ld2450.py`, both `+1` until A3's live test.
  The datasheet's example frame (x -782, y 1713, speed -16) is a test vector. A slot with all 8 bytes zero, or x = y = 0,
  is skipped. y is not clamped (fusion already drops y < 0).
- A1: reader status: `offline` when the port isn't open, `stale` when open but no frame for > 1 s (including no frame
  yet), else `ok`. When stale it still returns the last frame; fusion only ingests a frame whose `t` is new, so a
  repeat adds nothing. Frames are stamped with `time.time()` on arrival. Sends enable config, multi-target, end config
  on every (re)connect and logs the ACKs. Retry is every 2 s; only the first failed open is a warning.
- A1: `LiveSource` (in `sources.py`): LD2450 on env `LD2450_PORT` (default `/dev/ttyAMA0`), C1001 on env `C1001_PORT`.
  The C1001 side is offline when `C1001_PORT` is empty, when `from .sensors.c1001 import C1001Reader` fails, or when
  the reader raises; it is built in `start()`, not at `make_source` time. `PULSE_SOURCE=live` now uses it; replay is
  still `StubSource`. On a Mac with no sensors, live mode serves with both sensors offline (checked by hand).
- A1: `tools/ld2450_dump.py PORT [--baud] [--multi] [--record FILE.jsonl]`: table of x, y, range, angle (L/R), speed,
  resolution; frames/s over the last second; good/bad/skipped; ACKs; current sign constants; summary on Ctrl-C.
  Without `--multi` it only listens. Checked end to end over a pseudo-terminal at 115200 (macOS ptys reject 256000:
  `Inappropriate ioctl`; real UARTs and USB adapters are fine): 20 frames in, 20 recorded, 0 bad, ACK decoded.
- A1: 117 tests pass (`test_ld2450.py` added: datasheet frame, 3 targets, negative x, empty slots, split chunks,
  garbage before the header, bad tail, header inside a truncated frame, two frames in one chunk, sign flips, command
  bytes, ACKs mixed into the stream, reader ok/stale/offline/retry/reconnect with a fake serial port, LiveSource with
  `C1001Reader` missing, unset, present and raising). `test_server.py`'s live check now runs a real `LiveSource` on a
  missing port.
- A1 for CS2: `LiveSource` calls `C1001Reader(port, baud=115200)`, `.start()`, `.stop()`, `.latest(now)`. No edits to
  `sources.py` needed; once `C1001Reader` exists in `sensors/c1001.py` it gets picked up.
- ALEX-1: `pi/pulse/sensors/c1001.py` implements pure `C1001Parser` (feed byte chunks, resyncs on `53 59`, checks
  checksum `sum(...) & 0xFF` and tail `54 43`, counts `good` / `bad` / `skipped_bytes`; `feed_with_raw` returns raw
  bytes for recordings), command builders (`cmd_set_work_mode(0x02)` -> `53 59 02 08 00 01 02 B9 54 43`,
  `cmd_query_sleep_composite` -> `53 59 84 8D 00 01 0F CD 54 43`), contract sanity filtering (`sanitize_breath`,
  `sanitize_heart`), and `C1001Reader(port, baud=115200)` (daemon thread, requests sleep mode on connect, polls sleep
  composite vitals every 0.5 s, status ok / warming when connected without vitals / stale / offline, reconnects every
  2 s, never raises).
- ALEX-1: `tools/c1001_dump.py PORT [--baud] [--no-init] [--record FILE.jsonl]`: live presence, movement, breathing
  rate, heart rate, frames/s, good/bad/skipped, last frame age, JSONL logging.
- ALEX-1: 134 tests pass (`tests/test_c1001.py` added with 17 tests: work mode bytes matching library line 44, query
  sleep composite bytes matching line 324, checksum verification matching lines 799/929, composite frame parsing,
  movement and still handling, contract sanity filtering for breath and heart, checksum failures, bad tail, split
  chunks across reads, garbage before and between frames, multiple frames in one chunk, discrete query frames, reader
  offline / warming / ok / stale statuses with FakeSerial, reader reconnects on error, LiveSource integration).
- ALEX-1: Updated `docs/hardware.md` C1001 protocol section with confirmed wire protocol, command words, checksum
  formula, and links to official DFRobot library lines.
