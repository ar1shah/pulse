Update this when a phase changes or a prompt finishes. What to do is in docs/PLAYBOOK.md.

# Status

> # >>> WE ARE HERE: PHASE 4 (Sensors live) <<<
>
> - **Ari:** Phase 3 done: both loopbacks PASS (`/dev/ttyAMA0` at 256000, `/dev/ttyAMA3` at 115200), 61 fps on the
>   Pi, touch and 1 m readability checked on the real screen. ARI-4's code half is done against sim (gate
>   hysteresis, crossing-proof association, still-survivor grace, heart range 45 to 150); its live tuning is still
>   pending. Next: ARI-3 the moment EE has the LD2450 wired.
> - **Alex:** ALEX-1 is done. ALEX-2 (run by Ari) is mostly done: the walk-up bug is fixed (the reader puts the
>   C1001 in real-time reporting mode; lock in ~10 s instead of never), sample recording committed. Still open from
>   ALEX-2: operator test, cardboard, phone heart rate, live mode with the C1001 only (see the ALEX-2 notes).
>   ALEX-4 (command dashboard + sitrep) needs no hardware; ALEX-3 (replay) needs the Phase 4 recordings.
> - **EE:** Phase 4 sensor wiring, power-only voltage check first (TX must idle at 3.3 V). Still open: multimeter on
>   the Pi's 5 V pins (Phase 3) and the Phase 1 and 2 EE boxes in PLAYBOOK.

**Deadlines:** Devpost final Sun Oct 11 10:00 AM, commits stop 11:00 AM, repo public at submission.
**Gate:** live dots + live vitals on the screen by 10 PM Sat; no new features after it.

## Phases

Tick boxes live only in docs/PLAYBOOK.md; this table is the summary.

| Phase | Name | Owner(s) | Status | Prompts |
| --- | --- | --- | --- | --- |
| 0 | Done so far (T0 to T4) | All | Done | T0 to T4 |
| 1 | Unbox + start the parsers | EE, Ari, Alex | Done except EE boxes | ARI-1 (done), ALEX-1 (done) |
| 2 | Pi + screen boot | EE, Ari, Alex | Done except EE boxes + Alex SSH | Manual only |
| 3 | Pi setup + serial ports | Ari, EE | Done except multimeter | ARI-2 (done) |
| 4 | Sensors live | EE, Ari, Alex | In progress | ARI-3, ALEX-2 |
| 5 | Full app live: the gate (10 PM latest) | Ari, Alex, EE | ARI-4 code half done (sim); live part not started | ARI-4, ALEX-3, ALEX-4 |
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
| 2 | `vcgencmd measure_temp` idle (C) | 42.3 |
| 2 | Pi IP (`hostname -I`) | 172.20.10.4 (hotspot), 10.4.245.18 (Velocity Wi-Fi) |
| 3 | UI fps on the Pi (`/?fps=1`) | 61 |
| 3 | UART3 device name | `/dev/ttyAMA3` (loopback PASS at 115200) |
| 3 | Pi 5 V pins (V, multimeter) | |
| 4 | LD2450 5 V pin / GND pin | |
| 4 | C1001 5 V pin / GND pin | 2 / 9 (TX to 29, RX to 7, `/dev/ttyAMA3`) |
| 4 | LD2450 TX idle (V) | |
| 4 | C1001 TX idle (V) | |
| 4 | LD2450 max range walking away (m) | |
| 4 | LD2450 left/right edge at 2 m (deg) | |
| 4 | LD2450 behind the panel: detected? | |
| 4 | LD2450 sitting still: drops out after (s, or never) | |
| 4 | C1001 presence after (s) | 0 (first poll after sitting down; walk-up, mode 0) |
| 4 | C1001 breathing after (s) / value (/min) | 7.3 to 7.6 first value, ~11 to 13 in the 10 to 25 range / ramps up, settles 22 to 23 after ~30 s |
| 4 | C1001 heart rate after (s) / value (bpm) | 10.2 to 10.8 / 64 to 85 seated |
| 4 | Phone/watch heart rate at the same time (bpm) | not done yet |
| 4 | C1001 behind the panel: works? | not done yet |
| 6 | Power bank 15 min: `vcgencmd get_throttled` | |
| 6 | Power bank 15 min: temp (C) | |
| extra (ARI-2) | Pi user@host / OS / session + compositor / Chromium binary | pulse@pulse.local / Debian 13 trixie arm64 / rpd-labwc, labwc 0.20.2 / `/usr/bin/chromium` 154 |
| extra (ARI-2) | UART0 loopback (pin 8 to 10, 256000) / UART3 loopback (pin 7 to 29, 115200) | PASS / PASS (all 5 patterns) |
| extra (ARI-3) | LD2450 x sign: holder's left is raw + or - (`X_SIGN`) | |
| extra (ARI-3) | LD2450 speed sign: approaching is raw + or - (`SPEED_SIGN`) | |
| extra (ARI-3) | LD2450 targets at once / frames/s / bad frames in 2 min | |
| extra (ALEX-2) | C1001 walk-up lock: reporting mode 1 (shipped) / mode 0 | never (125 s) / 10.2 and 10.8 s (2 runs) |
| extra (ALEX-2) | C1001 query reply time mode 1 / mode 0 | ~105 ms / ~350 ms median, none lost |
| extra (ALEX-2) | C1001 working distance range (m) | not measured; it reads vitals out to ~2 m, including from the operator side |
| extra (ARI-5) | Power bank model + capacity / `get_throttled` idle and under load / runtime | |
| extra (ARI-5) | Touch on the 7": drawer scrolls / taps at screen edges | yes (finger drag) / yes (all four corners) |
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
- ALEX-1: ported from DFRobot's Arduino library DFRobot_HumanDetection at commit `f98f64e` (docs/hardware.md "C1001
  protocol" links every line). The frame hint was right except the length is BIG-endian: `53 59 | ctrl | cmd | len BE16
  | data | sum8 | 54 43`. The library POLLS (query with data `0F`, reply has the same ctrl/cmd, value in `data[0]`,
  resend every 1 s, give up at 5 s); it never waits for pushed reports, so the reader polls too.
- ALEX-1: init = ping `01 83` (HP LED state), query mode `02 A8`, switch to sleep mode with `02 08 [02]` + 10 s wait if it
  isn't 2, HP LED on `01 03 [01]`, reset `01 02` + 10 s wait. Polls presence `80 81`, movement `80 82`, breath `81 82`,
  heart `85 82` once a second. Differences from the library, on purpose: no blind 10 s wait before the ping (the ping is
  retried instead); LED write + reset only if the mode or LED needed changing; vitals queries time out at 2 s, not 5 s.
  Fresh sensor: about 20 s from port open to the first reading. Already-configured sensor: about 1 s.
- ALEX-1: `C1001Reader(port, baud=115200)` status: `offline` (port closed, or no answer to the ping since it opened),
  `warming` (answering, no breath/heart value yet since connecting, includes the mode switch and reset waits), `stale`
  (no reading > 3 s, not the contract's 1 s, since it polls at 1 Hz), `ok`. 3 poll rounds with no reply = close the port
  and reconnect every 2 s. Fusion treats `warming` as usable, so C1001 presence still holds a still track while warming.
  Readings: moving True/False/None for movement 2/1/0; breath and heart raw (fusion applies the ranges) except 0 and
  0xFF become None.
- ALEX-1: `tools/c1001_dump.py PORT [--baud] [--record FILE.jsonl]` runs the real reader: status, init phase, presence /
  moving / breath / heart, frames/s, good/bad/checksum/skipped, timeouts, and frames nobody asked for (if this firmware
  also pushes reports, they show up there). Records every sensor frame (`kind: frame`, raw hex) and every poll round
  (`kind: reading`). Checked end to end over a macOS pty against a scripted fake sensor that started in fall mode with
  the LED off: full init with switch + reset, warming, then vitals; 101 frames, 0 bad, injected garbage all skipped;
  stale then offline when the fake exited; Ctrl-C exits cleanly mid-init. Not yet run against the real sensor.
- ALEX-1: things to check on Saturday (ALEX-2): does the sensor answer the ping right after power-up or need the
  library's 10 s; does the mode persist across power cycles (then later boots skip the 20 s); does it push any frames
  unprompted (dump tool's "unsolicited" line); what breath/heart read with nobody there (we map 0 and 0xFF to null).
- ALEX-1: 147 tests pass (`test_c1001.py` added, 30 tests: query bytes vs a byte-for-byte copy of the library's
  `getData()` frame builder, known vectors, checksum and tail failures, impossible length, split at every offset,
  byte-by-byte, garbage, random noise, reader init with and without mode switch, failed switch, warming to ok, missing
  replies, never-answering sensor, stale then reconnect, missing port, read errors, LiveSource with the real reader).
  Sim checked by hand; `PULSE_SOURCE=live` with no hardware shows both sensors offline and logs the C1001 retry.
- ARI-2: `tools/uart_loopback.py PORT BAUD` writes 5 patterns (all byte values, an LD2450-style frame, a C1001-style
  frame, 0x55/0xAA, random) and checks each comes back; exit 0 pass, 1 fail, 2 can't open. Says "nothing came back"
  (jumper / UART off) vs garbled (baud / mini UART). Accepts pyserial URLs: `loop://` passes on the Mac.
- ARI-2: `scripts/setup_pi.sh` (on the Pi, `ssh -t pulse@pulse.local bash pulse/scripts/setup_pi.sh`): detects OS /
  64-bit / desktop vs Lite (stops on Lite) / compositor / Chromium, then raspi-config serial console off + hardware on,
  `enable_uart=1`, `dtoverlay=disable-bt`, `dtoverlay=uart3` exactly once in `[all]` (backups `*.bak-<time>` in
  /boot/firmware), dialout, apt, venv, `.env` from .env.example if missing, `pulse.service`, kiosk autostart, blank
  cursor, launchers, blanking off. Prints `CHANGED:`/`ok:` lines and a reboot list; never reboots. Ran once at 17:33.
- ARI-2: sudo on the Pi asks for a password, so `pulse.service` is a systemd USER unit with linger
  (`systemctl --user`, `journalctl --user -u pulse`); `deploy.sh` and `pi_logs.sh` never need sudo. ExecStart is
  `.venv/bin/python -m pulse.main` (uvicorn from the venv, with Pulse's logging set up). Default sim; the Pi's own
  `~/pulse/.env` overrides. Its `C1001_PORT` is still blank (created from the old .env.example): set
  `C1001_PORT=/dev/ttyAMA3` there when going live.
- ARI-2: `scripts/deploy.sh`: rsync (excludes .git, .venv, .env, recordings, __pycache__; `--delete` leaves those
  alone on the Pi), `scripts/pi_venv.sh` (creates the venv, reinstalls only when requirements.txt's sha256 changes),
  restarts the service, reloads the kiosk by killing Chromium. Checked on the fresh Pi (no venv, no service) and after.
- ARI-2: kiosk = `scripts/kiosk.sh` from `~/.config/labwc/autostart` (Pi OS runs `labwc -m`, so this adds to the
  desktop's autostart instead of replacing it). Waits for :8000, flock so one loop only, marks the profile's last exit
  clean (no restore bubble), relaunches Chromium when it exits. Flags: kiosk, no error dialogs/infobars/first run,
  no translate, no pinch, no swipe-back, basic password store (no keyring prompt), `--ozone-platform=wayland` when
  `WAYLAND_DISPLAY` is set (started over ssh, Chromium otherwise tries X11 and exits).
- ARI-2: EXIT chip in the status bar (top right, only when `GET /api/kiosk` says a kiosk is running, so never on a
  laptop). Hold 1.5 s (short tap = toast "Hold EXIT to close Pulse"); `POST /api/kiosk/exit` only from 127.0.0.1/::1,
  writes `$XDG_RUNTIME_DIR/pulse-kiosk.exit` and SIGTERMs Chromium; kiosk.sh sees the flag and stops. Reopen: desktop
  icon (`ui/icon.svg`), Menu > Accessories > Pulse, or `pulse` in the Pi's Terminal (`scripts/pi_launchers.sh`, no
  sudo). Not a contract change (REST only), no `v` bump. Checked on the Pi by hand: EXIT works, the icon works.
- ARI-2: cursor hidden with a generated blank Xcursor theme (labwc has no hide-cursor option); the UI's own
  `cursor: none` on coarse pointers stays as well. Touch is `mouseEmulation="yes"` (Pi OS default): check drawer
  scrolling in ARI-5.
- ARI-2: 151 tests pass (`test_kiosk.py` added: pidfile/flag handshake with a real child process, 403 for
  non-local exit).
- Phase 3 on the Pi: loopback `/dev/ttyAMA0` at 256000 and `/dev/ttyAMA3` at 115200 both PASS, all 5 patterns
  (jumpers placed and removed with the Pi off). `/?fps=1`: 61 fps. Still open: multimeter on the Pi's 5 V pins (EE).
- ARI-5's touch and readability checks passed early (Phase 3, real 7" screen): all four corners register, range
  buttons and dot taps work, the contacts drawer scrolls with a finger drag (so `mouseEmulation="yes"` +
  `touch-action: none` is fine), and the vitals numbers read from about 1 m, so T3's 40 px / card 64 px stay as
  they are. Phase 6's "vitals readable" box is ticked; the rest of ARI-5 (unplug, restart, reboot, power bank)
  is still to do.
- ARI-4 (code half, against sim; sensors were away being soldered): new `SIM_SCENARIO`s reproduce the T2 rough edges.
  `cross`: two walkers pass 0.3 m apart at about 2 m, 0.9 m/s, stop 2 s at each end and walk back; when they are
  closer than 0.45 m the sim LD2450 reports ONE target halfway between them. `edge`: one person at 12 deg, range
  3.78 to 4.22 m over 12 s (built around the default 4 m gate). `still`: a sitter at (-100, 1100) the LD2450 sees
  for 2 to 5 s then misses for 5 to 10 s, C1001 presence true throughout. `demo` and `random` are byte-identical
  to before (checked 3000 ticks x 5 seeds each). Old fusion: cross swapped ids at every crossing, edge made a new
  contact every cycle (10 in 2 min), still already held.
- ARI-4 fusion changes (constants at the top of `fusion.py`, each with its why; rules in docs/data-contract.md):
  gate hysteresis (new tracks start only inside the gate; a track lives to gate + `GATE_MARGIN_M` 0.3 m /
  `GATE_MARGIN_DEG` 5 deg; in the margin it is kept but NOT in `targets` and can't lock, so `targets` never goes
  past the gate and `v` stays 1); alpha-beta filter (`SMOOTH_ALPHA` 0.5, `VEL_BETA` 0.15); association against
  predicted positions, a moving track coasts up to `COAST_S` 1 s, a still one never coasts; best one-to-one
  matching (most pairs, then least total distance), never a pair beyond `ASSOCIATE_M` 0.6 m; still-survivor hold
  counts C1001 presence for `PRESENCE_GRACE_S` 2 s after the last true reading (`vitals.presence` stays raw).
- ARI-4 visible change in demo: the walker no longer leaves a hollow ghost dot at about 3.9 m for up to 3 s when
  it walks out past 4 m (old smoothing lag held the track just inside the gate). The walker's dot is also up to
  0.1 m closer to the truth (no smoothing lag). Sitter, lock, vitals, triage and contacts unchanged. Checked by eye
  on the real sim server: lock, amber, vitals, walker crossing, no console errors.
- ARI-4 heart range: fusion accepts 45 to 150 bpm (`HEART_MIN_BPM` / `HEART_MAX_BPM` in fusion.py; `HEART_RANGE`
  in state.py and contract.js widened to match so the validator accepts it). The C1001 is rated accurate 60 to 100,
  not clamped: values above 100 were seen on real hardware. Breath stays 10 to 25. Contract doc, CLAUDE.md,
  hardware.md and demo.md reworded. `v` stays 1 by decision (the JSON shape is unchanged).
- ARI-4 tests: `tests/test_scenarios.py` runs cross / edge / still through fusion for 120 s x 5 seeds at 10 Hz
  fake time: no id swap in cross (judged only on ticks where the walkers are clearly apart), exactly one contact
  and no dot past the gate in edge, the sitter never drops (and shows amber while the LD2450 has lost them) in
  still, every snapshot passes `validate_snapshot`, runs reproducible. cross and edge fail on the old fusion.
  `test_fusion.py` adds gate margin, no start in the margin, no lock in the margin, no jump past 0.6 m, a
  merged-frame crossing, heart 45 to 150; the presence test now expects the hold to last 2 s past presence false.
  180 tests pass.
- ARI-4 still pending (live tuning, Phase 5 boxes left unticked): whether 0.6 m `ASSOCIATE_M` suits the real
  LD2450's jitter; how far off the LD2450's first position is when it re-acquires a still person; the real distance
  at which it merges two people (the sim uses 0.45 m). Also fill the "Live: lock acquired in / dot jitter / ids
  swap" row above.
- ARI-4a (noise tuning from the live LD2450 test, no new features): still people wandered, got flagged moving and
  spawned phantom second tracks. A still person with ~15 cm of x jitter run through Fusion confirmed the 0.15 m
  moving threshold sat inside the sensor noise, so the tracker coasted on noise. `SMOOTH_ALPHA` 0.5 -> 0.3,
  `MOVING_DIST_M` 0.15 -> 0.25 (`VEL_BETA` stays 0.15: 0 breaks the crossing-walker id tests). In sim: phantom
  tracks 1.40 -> 1.13 per still person, dot swing ~500 -> ~370 mm. Contract rules 4 and 5 updated; the /ws shape
  is unchanged, so `v` stays 1. Still open for ARI-4 once check 1 gives real noise numbers: lock hysteresis, and
  new-track confirmation (3 hits before a dot shows). `tools/ld2450_analyze.py` (per-slot spread vs what fusion
  shows, from a `--record` file) was meant to land with this but was not in the repo; add it with its doc lines
  when found. Deployed and checked live on the Pi: noticeably steadier dots. Known-good point tagged
  `v0.5-working-beta` ("v0.5: WORKING BETA"): `git checkout v0.5-working-beta -- pi/pulse/fusion.py` to get back to it if later tuning makes it worse.
- fix-x-jitter (branch, Sun morning; main untouched): left/right was unreliable live (dot stalls, small jumps,
  sometimes the wrong way). Parser checked and correct (sign bit, header/tail, resync, partial reads). Root causes
  found in fusion with a fault model (15 cm x noise, 25 % missed frames, 8 % returns 0.5 m off): a far return
  inside the 0.6 m gate kicked the velocity ~750 mm/s, often the wrong way, so the track lost its person and a new
  id spawned; and a still track's velocity random-walked on noise and fired as a jump when it turned moving. New
  `pi/pulse/tracker.py` (knobs at its top): shown x = outlier gate, median 5, EMA 0.35, 80 mm deadband;
  velocity residual clipped to 250 mm; new tracks shown from their 3rd detection, ghosts dropped after 0.3 s.
  y and association unchanged. On for live, off for sim (`PULSE_XFILTER=1/0` forces). Same fault model, 40 runs
  at 0.4 m/s: wrong-way steps 133 -> 0, runs with a phantom/new id 33 -> 4. Cost: x lags ~0.3 m at 0.4 m/s.
  `LOG_RAW=1` logs raw slots vs shown dots to `recordings/xlog_*.csv`, `tools/plot_x.py` plots it. Contract rule 4
  updated; /ws shape unchanged, `v` stays 1. 203 tests pass. Deployed to the Pi (live, filter on) and walked: good
  enough for the demo. Kill switch: `PULSE_XFILTER=0` in the Pi's `.env`, then `systemctl --user restart pulse`.
- ALEX-2 (run by Ari, Sat evening; full write-up in docs/hardware.md "Measured on our sensor"): wired VIN pin 2, GND
  9, TX 29, RX 7, `/dev/ttyAMA3`, mounted on the back of the screen. Walk-up bug found and fixed: the sensor shipped
  in reporting mode 1, where vitals are only computed while its "in bed" state is 1, which walking up never sets
  (and a reset doesn't either). `C1001Reader` now writes reporting mode 0 in init when it isn't 0 (no reset); walk-up
  lock 10.8 s and 10.2 s. Mode 1 also kept answering frozen breath/heart after it stopped measuring, so readings
  with presence 0 now never carry breath or heart. New tools: `tools/c1001_probe.py` (experiments, records what was
  sent too) and `tools/c1001_timeline.py` (decode recordings). `c1001.describe()` names pushed frames. 187 tests.
- ALEX-2 recordings: `recordings/c1001_session1.jsonl` (150 s, the server's reader; gitignored, on the Mac and the
  Pi) and `recordings/sample_c1001.jsonl` (30 s seated slice, committed, for ALEX-3). Not the 3 minutes the prompt
  asked for: walk-up run 2 doubled as the session.
- ALEX-2 open (stopped when the LD2450 came back): (1) **operator test**: hold the device normally, nobody in front,
  60 s with `tools/c1001_dump.py --record`. The sensor kept reading Ari from ~2 m on the operator side, so it may
  read the holder at ~0.4 m and fusion would put the holder's vitals on the locked dot. If it does: foil-on-cardboard
  shield between sensor and screen (insulated, never over the antenna face), retest, retest seated at 1 m, and
  propose a fusion cross-check (C1001 distance vs the locked dot's range; distance units still unclear). (2)
  cardboard in front, seated at 1 m, plus a phone heart rate at the same time. (3) walking around: numbers don't
  go null while the sensor still sees someone (only when presence goes 0); the box stays unticked. (4) mode 0 after
  a power cycle (the reader sets it anyway). (5) live mode with the C1001 only: from the code, with no LD2450 there is
  no dot, so no lock, so `vitals` has presence/moving but breath/heart stay null and the panel says "No lock"; not
  checked on the screen yet, and `~/pulse/.env` still has `C1001_PORT=` blank and `PULSE_SOURCE=sim`. (6) breath
  ramps for ~25 s after a lock (5, 8, 11 ... 22): fusion shows those as real numbers; maybe hold "settling" until
  breath stops climbing. Ask before changing fusion.
- Sonar ring radar (Sun morning, `ui/radar.js` only, post-gate polish): the side-to-side sweep line is gone. A ring
  pulses out from the device every 2 s (1.4 s out, then quiet). Dots stay live (same positions and motion as
  before); the ring only sets their brightness: full when it passes, fading to a 15% floor (35% if locked) until the
  next ring. New contacts start bright. Lock ring and selection brackets stay solid. Knobs at the top of radar.js:
  `PING_PERIOD_MS`, `PING_TRAVEL_MS`, `LIT_FADE_MS`, `LIT_FLOOR`. (A first version also froze each dot's position
  between rings like real sonar; dropped, dots lagged the person.) Touch checks pass, screenshots refreshed, 61 fps
  headless. `tools/ui_screenshots.py` times out on "a held target" (waits on the sim's snapshots, not this change).
- C1001 back on (Sun morning): `~/pulse/.env` on the Pi had `C1001_PORT=` blank, so live mode never opened it. Now
  `C1001_PORT=/dev/ttyAMA3`; after a service restart /ws reports `ld2450: ok, c1001: ok`, presence true.
