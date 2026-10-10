# Status

Update this at the end of every task: tick the box, add a one-line note, keep "Next up" current.
Phase numbers and prompt ids (A1 to A6, B1 to B4) match docs/PROMPTS.md; the detailed boxes and measured values
for each phase are in docs/BRINGUP.md.

T5 to T9 and S1 to S7 were folded into the phases: T5 is A1, T6 is B1, T8 + T9 are A2, S1 is A3, S2 is B2,
T7 + S4 are A4, S3 is B3, S6 is B4, S5 is A5, S7 is the optional buzzer in Phase 7.

## Next up
Phase 1: EE does BRINGUP Phase 1 (inventory, photos, pin labels, connectors). Ari decides the SD card and starts
A1 in the `ld2450` worktree. CS2 starts B1.

## Phase 0. Done (T0 to T4)
- [x] T0 repo created, pushed, teammates added, SSH key on Pi
- [x] T1 scaffold + data contract in code
- [x] T2 server + sim mode + minimal fusion
- [x] T3 radar UI
- [x] T4 tap-a-dot card, contacts drawer, range buttons

## Phase 1. Unbox + start the parsers
- [ ] EE (manual): inventory, photos, pin labels, cable connectors, power supply
- [ ] Ari (manual): SD card decision
- [ ] A1 LD2450 parser, reader, LiveSource, dump tool (Ari, worktree `ld2450`)
- [ ] B1 C1001 parser, reader, dump tool (CS2)

## Phase 2. Pi + screen boot
- [ ] EE (manual): screen on the DISPLAY port, screen power pins recorded, Pi boots to the desktop, touch works
- [ ] Ari (manual): SD card flashed or moved, `ssh pulse@pulse.local` from the Mac with no password
- [ ] CS2 (manual): `ssh-copy-id pulse@pulse.local` from CS2's laptop

## Phase 3. Pi setup + serial ports
- [ ] A2 Pi setup, kiosk, deploy, both UART loopbacks, UART3 device recorded (Ari)
- [ ] EE (manual): loopback jumpers on and off, Pi 5 V pins measured
- [ ] Ari (manual): A1 merged, B1 pulled, `scripts/deploy.sh` run

## Phase 4. Sensors live
- [ ] EE (manual): power-only check, both sensor TX idle at about 3.3 V, then data wires
- [ ] A3 LD2450 live: sign constants confirmed, session recorded, sample committed (Ari)
- [ ] B2 C1001 live: vitals timed, HR compared, session recorded, sample committed (CS2)

## Phase 5. Full app live: the gate (10 PM latest)
- [ ] EE (manual): both sensors mounted side by side, same direction, same height
- [ ] A4 live integration + fusion tuning (Ari)
- [ ] B3 replay mode (CS2)
- [ ] B4 command dashboard + Gemini sitrep + ElevenLabs read-aloud (CS2, separate files only)
- [ ] **Gate: live dots + live vitals on the screen.** After the gate: no new features.

## Phase 6. Judge-proof
- [ ] A5 break tests (Ari)
- [ ] EE (manual): handheld body, cables secured, 15 min power bank test
- [ ] All (manual): rough demo video on battery

## Phase 7. Saturday night
- [ ] All (manual): demo script 3 times behind the panel
- [ ] CS2 (Claude chat): Devpost draft
- [ ] Ari (manual): Devpost project, team invited, rough submit by midnight, repo public
- [ ] EE (manual): gallery photos
- [ ] S7 buzzer (optional, only if everything else is done)

## Phase 8. Sunday (Oct 11)
- [ ] Final demo video by 7:30 AM (YouTube, unlisted)
- [ ] Code freeze 8:30 AM, A6 pre-demo check (Ari)
- [ ] Devpost final 9:30 AM (closes 10:00 AM): video, public repo, all members
- [ ] Last commit before 11:00 AM

## Measured on hardware
Fill in as BRINGUP.md asks for each value, and copy the final ones into docs/hardware.md. Fields were taken
from PROMPTS.md and hardware.md; add any BRINGUP.md asks to record that are missing here.

- Pi: user@host ____ / OS ____ / session + compositor ____ / Chromium binary ____
- UART0 loopback (pin 8 to 10, 256000): ____
- UART3 device name ____ / loopback (pin 7 to 29, 115200): ____
- LD2450 TX idle voltage ____ V / 5 V pin used ____
- LD2450 x sign (holder's left is raw +/-) ____ / speed sign (approaching is raw +/-) ____
- LD2450 targets seen at once (max 3?) ____ / frames/s ____ / bad frames in 2 min ____
- C1001 TX idle voltage ____ V / 5 V pin used ____
- C1001 time to presence ____ s / breathing ____ s / heart ____ s
- C1001 vs phone/watch HR: sensor ____ bpm, watch ____ bpm, distance ____ m
- C1001 working distance range ____ m
- Power bank (model, capacity): ____ / `vcgencmd get_throttled` idle ____, under load ____ / runtime ____
- UI fps on the Pi (`/?fps=1`) ____ / touch: drawer scrolls ____, taps at screen edges ____
- Live: lock acquired in ____ s / dot jitter ____ / ids swap ____

## Notes
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
