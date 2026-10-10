# Claude Code prompts

Copy each prompt into Claude Code from the repo root. Task ids match docs/STATUS.md.

## How to run these

- `cd pulse && claude`. CLAUDE.md loads automatically every session.
- **One task per session.** Run `/clear` before starting the next task so it starts fresh from CLAUDE.md
  instead of dragging the last task's context along.
- Tasks marked **PLAN**: switch to plan mode first (Shift+Tab until it says plan mode), paste the prompt,
  read the plan it proposes, fix anything wrong, then approve. Cheap insurance on the big ones.
- After each task, spend 60 seconds actually running it yourself before moving on.
- Lanes can run in parallel. UI (T3, T4) and sensors (T5, T6) only meet at the data contract, so once T2 is
  done you can run a second Claude Code session in a git worktree:
  `git worktree add ../pulse-sensors -b sensors && cd ../pulse-sensors && claude`
  Merge back with a normal PR or `git merge sensors` when it's green.
- If a task goes sideways: `Esc` to interrupt, tell it what's wrong in one sentence. If it's really lost,
  `git checkout .`, `/clear`, and rerun the prompt with one extra line about what went wrong.

Order for tonight: **T0, T1, T2, T3, T4**, with **T5, T6** in a second session once T2 is merged,
then **T7, T8, T9**. If you only get through T0 to T3 tonight, that's still a great night.

---

## Friday night

### T0. Create the repo (manual, ~5 min)

```bash
mkdir pulse && cd pulse
# copy the starter files in here (CLAUDE.md, README.md, docs/, .gitignore, .env.example)
mkdir -p recordings && touch recordings/.gitkeep
git init -b main
git add . && git commit -m "Pulse starter: context docs and data contract"
gh repo create pulse --private --source=. --remote=origin --push
```

Then:
- Add teammates: GitHub repo page, Settings, Collaborators.
- Put the Pi's real `user@host` into `docs/hardware.md` and `.env` (copy `.env.example` to `.env`).
- `ssh-copy-id <user@host>` so scripts and Claude Code can SSH in without a password.

### T1. Scaffold + data contract in code

```
Read CLAUDE.md and docs/data-contract.md.

Scaffold the repo layout from CLAUDE.md (empty placeholder modules are fine where later tasks fill them in).

Create pi/requirements.txt (runtime: fastapi, uvicorn[standard], pyserial) and pi/requirements-dev.txt
(pytest, httpx).

Implement pi/pulse/state.py: dataclasses Target, Vitals, Contact, Gate, Snapshot that match
docs/data-contract.md field for field, including the rounding rules (range 2 dp, angle 1 dp) and enums
(source, triage, sensor status). Give Snapshot a to_dict() that produces exactly the documented JSON shape.
Add validate_snapshot(d: dict) -> list[str] that returns a list of contract violations (types, enums,
ranges, max 3 targets, max 20 contacts, target ids 1 to 3, locked target matches vitals.target_id).

Create ui/contract.js exporting the same enums and constants (triage colors keys, sensor statuses, lock cone
20 deg and 0.4 to 1.5 m, default gate) as plain ES module constants so the UI never hardcodes them.

Tests in pi/tests/test_contract.py: the example JSON in the doc validates; a Snapshot built in code
round-trips to that shape; each kind of violation is caught.

Run the tests, update docs/STATUS.md, commit.
```

### T2. Server + sim mode + minimal fusion (PLAN)

```
Read CLAUDE.md and docs/data-contract.md (including the fusion rules).

Build three things:

1) pi/pulse/main.py: FastAPI app run by uvicorn on 0.0.0.0:8000 when you do `python -m pulse.main`.
   - Serves ui/ as static files: / is index.html, /command is command.html if it exists, /debug is debug.html.
   - WebSocket /ws broadcasts a Snapshot every 100 ms to all connected clients. A client disconnecting must
     never affect others or crash the loop.
   - Handles client messages set_gate and reset_contacts per the contract; ignores and logs anything else.
   - GET /api/snapshot returns the latest snapshot.
   - Data source chosen by env PULSE_SOURCE: sim (default on a Mac), live (for now a stub that reports both
     sensors offline and no targets; later tasks wire the real readers in), replay (stub for now).
   - Design the source interface so live and sim both just provide "latest LD2450 targets" and
     "latest C1001 reading" and fusion does the rest.

2) pi/pulse/sensors/sim.py: a fake LD2450 + fake C1001 that produce the same raw readings the real
   parsers will (LD2450-style targets in mm and cm/s; C1001-style presence/moving/breath/heart).
   - SIM_SCENARIO=demo: one person sitting still about 1.2 m away roughly straight ahead (the person
     behind the wall), plus one walker who crosses the room every 20 s or so.
   - SIM_SCENARIO=random: 1 to 3 people wandering inside +/-55 deg and 0.5 to 5 m with smooth motion
     (waypoints, 0.3 to 1.2 m/s), sometimes stopping for 5 to 20 s, occasionally entering/leaving.
   - Vitals only when someone is in the lock cone, with a 3 to 8 s settle delay before numbers appear;
     breathing 12 to 20 and heart 62 to 95 with slow drift and small jitter.
   - Seedable with SIM_SEED so runs are reproducible.

3) pi/pulse/fusion.py: a minimal but correct implementation of the contract's fusion rules (convert, gate,
   nearest-neighbor association, smoothing, moving, 3 s hold, lock cone, triage, vitals sanity, contacts).
   A later task hardens it, so keep it simple and readable.

Also ui/debug.html: connects to /ws and pretty-prints the latest snapshot plus message rate. Plain JS.

Tests: 300 ticks of each sim scenario all pass validate_snapshot; a FastAPI TestClient websocket test
receives valid snapshots; set_gate changes the gate in the next snapshot.

Run the server in sim mode, hit /api/snapshot to prove it, update docs/STATUS.md, commit.
```

### T3. Radar UI (PLAN, the wow)

```
Read CLAUDE.md, docs/data-contract.md and ui/contract.js. Build the handheld UI: ui/index.html,
ui/radar.js, ui/style.css.

Context: it runs full screen in Chromium kiosk mode on an 800x480 7-inch touchscreen held in one hand, and
judges look at it from about a meter away. Huge contrast, big type, nothing tiny.

Look: dark tactical radar. Phosphor green on near-black, amber for "still, breathing", gray for unassessed.
Subtle glow and scanlines, nothing that hurts readability. Original design: inspired by game heartbeat
sensors, but don't copy any game's actual UI, icons or logos. Fonts: system fonts or fonts bundled in
ui/fonts. No CDNs, no network requests besides our own server.

Layout:
- Top status bar (about 36 px): PULSE wordmark, SIM/LIVE/REPLAY badge, LD2450 and C1001 status pills
  (ok/warming/stale/offline/sim), contact count, clock.
- Main: a 120-degree sector radar (matches the LD2450's +/-60 deg FOV) with the device at bottom center,
  sized to fill the screen. Range rings every 1 m with labels, scaled to gate.max_range_m. Angle ticks every
  15 deg. The vitals lock cone (+/-20 deg, 0.4 to 1.5 m) drawn as a faint highlighted wedge.
- A sweep line panning side to side about 1.5 s per pass with a fading trail.
- Vitals readout area (side or bottom, your call for 800x480) with big BPM and breaths/min when locked,
  "settling..." when locked but null, and "aim at a contact within 1.5 m" when nothing is locked.

Dots:
- One per target at x_mm/y_mm, smoothly interpolated between 10 Hz snapshots at 60 fps.
- Color by triage, short motion trail, an expanding ping ring when the sweep passes over a dot.
- Held targets (last_seen_s > 0) fade out over the hold time.
- The locked target gets a lock reticle and a small ECG-style trace that beats at heart_bpm.

Connection: auto-connect to ws://<location.host>/ws, reconnect with backoff, and a clear full-screen
NO SIGNAL overlay while disconnected.

Touch/kiosk rules: no pinch zoom, no text selection, no context menu, no hover-only UI, cursor hidden.

Performance on a Pi 4 2GB: one canvas (plus a light DOM overlay for text if needed), requestAnimationFrame,
devicePixelRatio aware, no allocations in the per-frame hot path, no libraries.

When done: install Playwright as a dev-only tool, run the server with PULSE_SOURCE=sim SIM_SCENARIO=demo,
take screenshots of http://localhost:8000 at 800x480 at a few moments (including with a lock), look at them
critically, and fix anything ugly, cramped, misaligned or hard to read from a meter away. Save the final
screenshots to docs/screenshots/. Update docs/STATUS.md, commit.
```

### T4. Tap-a-dot card, contacts drawer, range buttons

```
Read CLAUDE.md, docs/data-contract.md, and the current ui/ code. Add interactions to the handheld UI:

1) Tap a dot (hit radius at least 48 px, pick the nearest if overlapping) to open a card for that contact
   (bottom sheet or side panel, whatever fits 800x480 best). Card shows: contact number, range in m,
   bearing like "12 deg L", MOVING or STILL, triage in plain words ("MOVING", "BREATHING",
   "NOT ASSESSED"), time since first seen.
   - If this contact is locked: big heart bpm and breaths/min, "settling..." when null.
   - If not locked: an arrow and "Get within 1.5 m and aim at them", with the live distance to the lock zone.
   - The card follows the target id. If the target disappears: "SIGNAL LOST", close after 3 s.
   - Tap empty radar space to close.
2) A Contacts button in the status bar opens a drawer listing all contacts (number, triage, last vitals,
   last seen). Tapping one selects it on the radar.
3) Three big range buttons (2 m / 4 m / 6 m) that send set_gate. Highlight the active one from the
   snapshot's gate, not local state.
4) A small, deliberate "reset" (long-press on the wordmark) that sends reset_contacts, for between demos.

Selection state stays in the UI only. Keep everything touch-first.

Verify with Playwright at 800x480 in SIM_SCENARIO=demo: screenshot card-locked, card-not-locked,
signal-lost, contacts drawer, each range setting. Review them critically, fix, save to docs/screenshots/.
Update docs/STATUS.md, commit.
```

### T5. LD2450 parser, reader, bring-up tools (sensor lane)

```
Read CLAUDE.md and the LD2450 section of docs/hardware.md.

Implement pi/pulse/sensors/ld2450.py:
- A pure, incremental parser: feed arbitrary byte chunks (frames can split across reads, arrive with
  garbage, or be corrupted) and get back complete frames. Each frame = list of up to 3 targets
  (x_mm, y_mm, speed_cms, resolution_mm), empty slots skipped. Resync on header AA FF 03 00 and tail 55 CC.
  Count good and bad frames.
- Sign decoding exactly as documented. Keep the sign conventions (x left/right, speed approaching) in two
  clearly named constants so we can flip them in one place after Saturday's empirical check, and normalize
  output to the contract's conventions.
- Command frame builder for: enable config, multi-target tracking, single-target tracking, end config. Plus
  an ACK frame parser. Mark the byte values "verify against datasheet".
- A reader class: opens pyserial on env LD2450_PORT (default /dev/ttyAMA0) at 256000 8N1, reads in a daemon
  thread, keeps the latest frame + timestamp, status ok / stale (no frame for > 1 s) / offline, reconnects
  every 2 s, never raises into the caller. Optionally sends multi-target mode on connect.

Tests (no hardware): normal frame, 3 targets, negative x, empty slots, frame split across chunks, garbage
before header, bad tail, two frames in one chunk.

Tools:
- tools/ld2450_dump.py PORT: live table of targets (x, y, range, angle, speed), frames/sec, bad frame count.
  Flags: --multi (send multi-target on start), --record FILE.jsonl (timestamp, raw hex, parsed).
- tools/uart_loopback.py PORT BAUD: writes test bytes and checks they come back (for a jumpered TX to RX test).

Wire the reader into the live source in main.py (PULSE_SOURCE=live). Run tests, update docs/STATUS.md, commit.
```

### T6. C1001 parser (sensor lane)

```
Read CLAUDE.md and the C1001 section of docs/hardware.md.

The only official driver is DFRobot's Arduino library DFRobot_HumanDetection on GitHub (DFRobot org).
Fetch its source (.h and .cpp, plus examples) and the SEN0623 wiki. Port what we need to Python in
pi/pulse/sensors/c1001.py. The hints in docs/hardware.md may be wrong; the library source wins.

Needed:
- Incremental frame parser with resync and checksum verification.
- The init sequence the library uses, including switching to the sleep/vitals work mode.
- Presence, movement state, breathing rate, heart rate. Replicate whether the library queries the sensor or
  waits for pushed reports.
- Reader class like the LD2450 one: env C1001_PORT, 115200, statuses ok / warming (connected, no vitals yet) /
  stale / offline, reconnect every 2 s, never raises.
- Out-of-range or zero values (breath outside 10 to 25, heart outside 60 to 100) become None.

Tests: frames built exactly as the library expects them; checksum failures; split chunks; garbage.

Tool: tools/c1001_dump.py PORT: live presence/moving/breath/heart, frame rate, errors, --record FILE.jsonl.

Update the C1001 section of docs/hardware.md with the real frame format and the control/command words you
ported, with links to the library lines. Wire the reader into the live source. Run tests, update
docs/STATUS.md, commit.
```

### T7. Fusion hardening (after T2 and T5)

```
Read CLAUDE.md, the fusion rules in docs/data-contract.md, and pi/pulse/fusion.py.

Harden fusion and test it hard:
- Nearest-neighbor association with a 0.6 m gate, stable ids 1 to 3, freed ids reused. LD2450 slot order
  is not identity.
- Light position smoothing, moving detection per the rules, 3 s hold with last_seen_s, and the still-survivor
  rule (keep holding a track in the lock cone while the C1001 reports presence).
- Lock cone, triage, vitals sanity, contacts exactly per the contract.
- set_gate applies on the next tick.
- Fusion takes time as a parameter (no hidden time.time() calls) so tests are deterministic.

Table-driven tests: walker crossing the room; person stops and fades from the LD2450 but C1001 presence keeps
them; two people swap LD2450 slots; lock acquired and lost; two people in the cone (closest to 0 deg wins);
vitals null and out-of-range handling; gate change drops a far target.

Run tests, run sim to confirm nothing regressed visually, update docs/STATUS.md, commit.
```

### T8. Pi setup, service, kiosk, deploy (needs the Pi on the network)

```
Read CLAUDE.md and docs/hardware.md. The Pi is reachable at $PI_HOST with key auth.

Write scripts/setup_pi.sh: idempotent, safe to re-run, prints what it changed, never reboots on its own.
First detect and print: /etc/os-release, 64-bit or not, desktop or Lite, the session type and compositor
(labwc, wayfire, or X11), and the Chromium binary name. Stop with a clear message if it's Lite.
Then:
1) /boot/firmware/config.txt: back it up, then ensure enable_uart=1, dtoverlay=disable-bt, dtoverlay=uart3
   each appear exactly once.
2) Serial login console off, serial hardware on (raspi-config nonint).
3) Add the user to dialout.
4) apt: python3-venv, chromium if missing, and cursor hiding appropriate to the compositor.
5) ~/pulse/.venv with pi/requirements.txt installed.
6) Install scripts/pulse.service (systemd, uvicorn from the venv, PULSE_SOURCE from /home/<user>/pulse/.env
   defaulting to live, Restart=always, journal logging) and enable it.
7) Kiosk autostart for the detected compositor: Chromium --kiosk to http://localhost:8000 with flags to skip
   restore bubbles, error dialogs, update checks, translate prompts and pinch zoom. Disable screen blanking.

Write scripts/deploy.sh (run from the Mac): rsync the repo to ~/pulse on $PI_HOST excluding .git, .venv,
recordings and __pycache__; reinstall requirements only if they changed; restart pulse.service; reload the
kiosk page. Write scripts/pi_logs.sh to tail the service journal.

Then do it for real: SSH in, run setup_pi.sh, deploy with PULSE_SOURCE=sim, and show me the output.
Ask me before rebooting. After my OK and the reboot, confirm the UI comes up full screen by itself.
Update docs/STATUS.md, commit.
```

### T9. UART loopback check (after T5 and T8, ~5 min)

Do this first: jumper Pi pin 8 to pin 10.

```
I've jumpered Pi pin 8 to pin 10. Over SSH: stop pulse.service, run tools/uart_loopback.py /dev/ttyAMA0
256000 and report the result. Then tell me to move the jumper to pins 7 and 29, find the UART3 device name
(ls -l /dev/ttyAMA* and /proc/device-tree or dmesg), run the loopback on it at 115200, write the confirmed
device name into docs/hardware.md and .env.example, and restart pulse.service. Update docs/STATUS.md, commit.
```

---

## Saturday (parts arrive)

### S1. LD2450 live bring-up

```
The LD2450 is wired per docs/hardware.md and I've checked its TX idles at 3.3 V. Over SSH: stop
pulse.service and run tools/ld2450_dump.py /dev/ttyAMA0 --multi. Walk me through a test: I'll stand
straight ahead at about 1 m, then step to MY left, then walk toward the sensor, then bring two friends in.
From what you see, confirm or flip the x and speed sign constants so the output matches the contract
(negative x = holder's left, negative speed = approaching), confirm we get 3 targets, and fix the parser
if anything disagrees with the datasheet. Record a 2-minute session to recordings/ld2450_session1.jsonl
and copy a 20-second slice to recordings/sample_ld2450.jsonl (committed). Update docs/hardware.md
with what we confirmed, docs/STATUS.md, commit.
```

### S2. C1001 live bring-up

```
The C1001 is wired per docs/hardware.md. Over SSH: stop pulse.service and run tools/c1001_dump.py on the
UART3 device. I'll sit still about 1 m in front of it, chest facing it. Tell me how long until presence,
breathing and heart rate appear, and whether the values look sane. If nothing arrives, debug the init
sequence against the DFRobot library. Record a 3-minute session to recordings/c1001_session1.jsonl and a
30-second sample to recordings/sample_c1001.jsonl (committed). Write the measured settle time into
docs/hardware.md, update docs/STATUS.md, commit.
```

### S3. Replay mode

```
Implement PULSE_SOURCE=replay: REPLAY_LD2450 and REPLAY_C1001 point at recorded .jsonl files; replay feeds
the raw bytes through the real parsers and fusion at the original timing, looping. Default to the committed
sample_*.jsonl files. Add a test that replays the samples and every snapshot validates. This lets anyone
develop against real sensor data on a laptop. Update docs/STATUS.md and README, commit.
```

### S4. Live integration and tuning

```
Deploy with PULSE_SOURCE=live and both sensors connected. Watch the snapshots (debug page or /api/snapshot
over SSH) while I run the demo script from docs/demo.md behind a panel. Tell me what's wrong: dot jitter,
ids swapping, the hidden person fading, lock not acquiring, vitals attaching to the wrong dot. Propose
threshold changes (smoothing, association gate, hold time, lock cone) with your reasoning, apply the ones I
approve as named constants, and add regression tests using the recordings. Update docs/STATUS.md, commit.
```

### S5. Crowd test and robustness

```
Make Pulse survive a judging table. Test and fix: unplugging either sensor mid-run (status pill goes
offline, UI keeps working, reconnects when replugged); the server restarting (UI shows NO SIGNAL then
recovers by itself); a busy room (tune default gate for the demo, maybe a "demo mode" preset); power bank
(check vcgencmd get_throttled under load). Report results, update docs/STATUS.md, commit.
```

### S6. Command dashboard + AI sitrep (reach, only after the 6 PM gate)

```
Build ui/command.html for a laptop on the same network: a larger radar view plus a contacts table, live from
/ws. Add POST /api/sitrep: send the current contacts and targets (no raw frames) to an LLM with a strict system
prompt: write a short radio-style situation report (number of contacts, their status, range and bearing from
the operator), no medical claims, no guessing beyond the data. API key from env LLM_API_KEY, never logged or
committed. If the call fails or there's no key, return a deterministic template-based sitrep from the same
data so the button always works. A big "Generate sitrep" button on command.html shows the text.
Update docs/STATUS.md, commit.
```

### S7. Buzzer (reach)

```
I've wired a buzzer to GPIO <pin>. Beep faster as the selected or nearest target gets closer to the lock
zone, and a steady double-beep while locked with vitals. Mute toggle in the UI. Must not block the server
loop. Update docs/hardware.md and docs/STATUS.md, commit.
```

---

## Any time

**Catch up a teammate (or yourself after /clear):**
```
Read CLAUDE.md and docs/STATUS.md and give me a 5-line summary: what works, what's in progress, what's next
for the <UI | sensors | hardware | story> lane, and any open risks.
```

**Debug something:**
```
Bug: <what I did> -> <what I expected> -> <what happened>. Reproduce it first (sim, replay or a test),
find the root cause, fix it, add a regression test, and tell me in two sentences what was wrong.
```

**Before the code freeze:**
```
Pre-demo check: run all tests, run sim and replay, deploy to the Pi, and walk the demo script in docs/demo.md
against the code. List anything that could break in front of a judge, ranked, and fix the top items with my OK.
```

---

## Not for Claude Code

Do these in a regular Claude chat inside the hackathon Project (it already has the context):
- Devpost write-up from docs/demo.md, STATUS.md and screenshots.
- Pitch slides if judging is on a stage.
- Rehearsing judge Q&A ("how does it see through walls?", "why two sensors?", "what's the HR range?").
