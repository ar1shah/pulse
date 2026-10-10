# Status

Update this at the end of every task: tick the box, add a one-line note, keep "Next up" current.
Task ids match docs/PROMPTS.md.

## Next up
- T4 tap-a-dot card, contacts drawer, range buttons. T5/T6 (sensor lane) can run in a second worktree.

## Friday night
- [x] T0 repo created, pushed, teammates added, SSH key on Pi
- [x] T1 scaffold + data contract in code
- [x] T2 server + sim mode + minimal fusion
- [x] T3 radar UI
- [ ] T4 tap-a-dot card, contacts drawer, range buttons
- [ ] T5 LD2450 parser + dump/record tool + UART loopback tool
- [ ] T6 C1001 parser (port of DFRobot library) + dump tool
- [ ] T7 fusion hardening
- [ ] T8 Pi setup script, systemd service, kiosk, deploy script
- [ ] T9 UART loopback verified on Pi, UART3 device name recorded

## Saturday
- [ ] S1 LD2450 live bring-up, sign conventions confirmed, session recorded
- [ ] S2 C1001 live bring-up, vitals seen, session recorded
- [ ] S3 replay mode from recordings
- [ ] S4 live integration + tuning
- [ ] **6 PM gate: live dots + live vitals on the screen**
- [ ] S5 crowd test + robustness (unplug a sensor, power bank)
- [ ] S6 command dashboard + AI sitrep (reach)
- [ ] S7 buzzer (reach)

## Sunday
- [ ] Code freeze
- [ ] Devpost submitted
- [ ] Backup demo video recorded

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
- T3: `ui/index.html`, `radar.js`, `style.css`. Fixed 800x480 stage (scaled to fit other window sizes), one canvas plus
  DOM text for the bar and corner panels. Bundled font: Rajdhani SemiBold/Bold + OFL.txt in `ui/fonts/` (the TTFs are
  ~400 KB each because they include Devanagari; subset later if load time matters on the Pi). All colors are CSS
  custom properties in style.css; radar.js reads them once. Add `?fps=1` for an fps counter.
- T3: layout reserved for T4: bottom-left is the vitals panel, bottom-right is the legend (T4 can put the range
  buttons there or replace it). Both are clipped along the sector edge, so nothing overlaps the radar. Dot hit
  testing is not built yet; positions are `APEX_X + x_mm * pxPerMm`, `APEX_Y - y_mm * pxPerMm` in radar.js and the
  `tracks` array holds the render position (mm) per id.
- T3: behaviors worth knowing: held dots (last_seen_s > 0) fade toward a 0.3 alpha floor (0.7 if locked) rather than
  to zero, so a still survivor kept alive by C1001 presence stays visible; a track that leaves the snapshot fades out
  over 300 ms. The beat trace is a stylised beat drawn at the measured heart_bpm and goes flat gray when heart_bpm is
  null; it is not a waveform from the sensor, so don't describe it as an ECG in copy. NO SIGNAL shows when the socket
  closes, errors, or sends nothing for 2 s; reconnect backoff is 0.5, 1, 2, 4, then 5 s.
- T3: `tools/ui_screenshots.py` (needs `playwright`, now in requirements-dev.txt, plus `python -m playwright install
  chromium`) starts its own sim server on :8010 and writes `docs/screenshots/t3-*.png`: settling, locked, walker,
  held from the real server; idle, 2 m / 30 deg gate, sensors down, NO SIGNAL from a mocked /ws. It exits non-zero on
  any page error. The demo sitter locks immediately (before numbers), so "no lock" is only reachable via the mock.
- T3: not yet checked on the Pi itself: 61 fps in headless Chromium on the Mac says nothing about a Pi 4. Check
  `/?fps=1` on the device in T8/T9 and look at the sweep trail (16 translucent wedges per frame) first if it is slow.
- T3: 93 tests pass (one new: UI assets are served and contain no http(s) URLs).
