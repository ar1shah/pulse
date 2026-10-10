# Pulse playbook

One phase at a time. Each phase says what every person does, whether it's a **[Claude Code]** prompt, a
**[Manual]** step, or **[Claude chat]** (the hackathon Project on claude.ai). Nothing here needs Cowork.

The tick boxes for every phase live in `docs/BRINGUP.md` with the same phase numbers. A phase is done when its
"Sync" box there is ticked; then everyone moves to the next phase together.

**People**
- **Ari (CS):** Pi setup + LD2450 lane
- **CS2:** C1001 lane + AI sitrep
- **EE:** everything physical: screen, wiring, power, multimeter, handheld body, demo panel

**Deadlines:** Devpost final Sun Oct 11 **10:00 AM**. Commits stop **11:00 AM**. Repo **public** at submission.
**Gate:** live dots + live vitals on the screen by **10 PM Sat** at the latest. After the gate: no new features.

---

## Phase 0. Done so far (T0 to T4)

Everything below works on a laptop with fake data.

- **Repo + docs:** CLAUDE.md, data contract, hardware notes, demo script.
- **Data contract in code:** `pi/pulse/state.py` + `ui/contract.js`, with tests that keep them matched.
- **Server + sim mode:** FastAPI on :8000, WebSocket `/ws` at 10 Hz, `/api/snapshot`, `/debug` page. Sim scenarios
  `demo` (one sitter behind the wall + a walker) and `random`. Basic fusion (tracking, lock cone, triage, contacts).
  Data sources plug in through `pi/pulse/sources.py`; `live` and `replay` are still stubs.
- **Radar UI:** flat dark 800x480 radar, sweep, dots by triage, held dots fade, vitals panel, NO SIGNAL overlay.
- **Interactions:** tap a dot for its card (range, bearing, status, vitals or "get within 1.5 m"), contacts drawer,
  2 / 4 / 6 m range buttons, hold the PULSE wordmark to reset.
- 93 tests pass. Screenshots in `docs/screenshots/`.

Run it: `cd pi && PULSE_SOURCE=sim SIM_SCENARIO=demo ../.venv/bin/python -m pulse.main`, open
http://localhost:8000 (or `/debug`). Tests: `cd pi && ../.venv/bin/pytest -q`.

### How to use Claude Code here

- `claude` from the repo root. CLAUDE.md loads automatically. One prompt per session, `/clear` between them.
- Two sessions at once (Ari runs two in Phase 1 to 3): use a worktree so they don't collide. The worktree has no
  `.venv` (it's gitignored), so link the main one in:
  `git worktree add ../pulse-ld2450 -b ld2450 && ln -s "$PWD/.venv" ../pulse-ld2450/.venv && cd ../pulse-ld2450 && claude`.
  Merge back when it's green: `git checkout main && git merge ld2450`.
- If it goes sideways: `Esc`, say what's wrong in one sentence. Really lost: `git checkout .`, `/clear`, rerun.

---

## Phase 1. Unbox + start the parsers (about 15 min)

| Who | Does |
| --- | --- |
| EE | [Manual] BRINGUP Phase 1: inventory, photos, pin labels, cable connectors, pick the power supply |
| Ari | [Manual] Decide the SD card (BRINGUP Phase 1). [Claude Code] start **A1** in a worktree, let it run |
| CS2 | [Claude Code] start **B1**, let it run |

The parser prompts need no hardware. They run in the background through Phases 2 and 3.

### A1. LD2450 parser, reader, dump tool [Claude Code, Ari, worktree `ld2450`]

```
Read CLAUDE.md, docs/hardware.md (LD2450 section), pi/pulse/sources.py and pi/pulse/sensors/ld2450.py.

1) In pi/pulse/sensors/ld2450.py, keep the existing Ld2450Target/Ld2450Frame dataclasses and add:
   - A pure incremental parser: feed arbitrary byte chunks (frames split across reads, garbage, corruption) and
     get back complete Ld2450Frame objects. Resync on header AA FF 03 00 and tail 55 CC. Count good/bad frames.
   - Sign decoding as documented (top bit set = positive, magnitude = low 15 bits), normalized to the contract
     conventions. Put the X and speed sign conventions in two clearly named constants so we can flip them in one
     place after the live test.
   - Command frame builders (enable config, multi-target, single-target, end config) and an ACK parser. Mark the
     bytes "verify against datasheet".
   - Ld2450Reader(port, baud=256000): pyserial 8N1 in a daemon thread, keeps the latest frame,
     latest(now) -> (Ld2450Frame | None, status) with ok / stale (no frame > 1 s) / offline, reconnects every 2 s,
     never raises into the caller. Sends multi-target mode on connect.
2) In pi/pulse/sources.py add LiveSource (name "live"), implementing the existing Source protocol (start, stop,
   ld2450(now), c1001(now)): an Ld2450Reader on env LD2450_PORT (default /dev/ttyAMA0), and a C1001 reader on env
   C1001_PORT that is imported lazily
   (`from .sensors.c1001 import C1001Reader`). If that import fails or the class doesn't exist yet, the C1001 side
   reports offline. CS2 is writing C1001Reader in parallel with this interface:
   C1001Reader(port, baud=115200), .start(), .stop(), .latest(now) -> (C1001Reading | None, status).
   PULSE_SOURCE=live uses LiveSource (make_source); replay stays a stub.
3) tools/ld2450_dump.py PORT: live table (x, y, range, angle, speed per target), frames/sec, bad frame count.
   Flags --multi and --record FILE.jsonl (timestamp, raw hex, parsed). It runs from the repo root with the venv
   python (`.venv/bin/python tools/ld2450_dump.py ...`), so put pi/ on sys.path to import pulse.
4) Tests without hardware: normal frame, 3 targets, negative x, empty slots, split chunks, garbage before header,
   bad tail, two frames in one chunk, LiveSource with C1001Reader missing.

Run all tests, update docs/STATUS.md, commit on this branch.
```

### B1. C1001 parser, reader, dump tool [Claude Code, CS2]

```
Read CLAUDE.md, docs/hardware.md (C1001 section) and pi/pulse/sensors/c1001.py.

The only official driver is DFRobot's Arduino library DFRobot_HumanDetection (GitHub, DFRobot org). Fetch its .h,
.cpp and examples plus the SEN0623 wiki, and port what we need to Python in pi/pulse/sensors/c1001.py. The hints in
docs/hardware.md may be wrong; the library source wins.

Keep the existing C1001Reading dataclass and add:
- An incremental frame parser with resync and checksum verification.
- The init sequence the library uses, including switching to the sleep/vitals work mode. Replicate whether the
  library polls the sensor or waits for pushed reports.
- C1001Reader(port, baud=115200) with .start(), .stop(), .latest(now) -> (C1001Reading | None, status):
  ok / warming (connected, no vitals yet) / stale / offline, daemon thread, reconnect every 2 s, never raises.
  This exact interface is what Ari's LiveSource imports. Don't edit sources.py.
- tools/c1001_dump.py PORT: live presence / moving / breath / heart, frame rate, errors, --record FILE.jsonl.
  It runs from the repo root with the venv python, so put pi/ on sys.path to import pulse.
- Tests: frames built exactly as the library expects, checksum failures, split chunks, garbage.

Update the C1001 section of docs/hardware.md with the real frame format and command words, linking the library
lines you ported. Run all tests, update docs/STATUS.md, commit.
```

---

## Phase 2. Pi + screen boot (about 30 min)

| Who | Does |
| --- | --- |
| EE | [Manual] Screen onto the Pi (below), SD card in, bench power on |
| Ari | [Manual] Pi Imager if needed, SSH from the Mac (below) |
| CS2 | Keep B1 going. [Manual] once the Pi is up: `ssh-copy-id pulse@pulse.local` from your laptop |

### EE: screen hookup [Manual]

1. Pi unplugged. Lift the latch on the Pi's **DISPLAY** port (the one between the HDMI ports and the audio jack,
   not the CAMERA port by the USB ports).
2. Ribbon in with the contacts facing the way the screen's instructions show, push the latch down. Same at the
   screen end.
3. If the screen also has 5V/GND jumper wires, they go to GPIO header pins. **Write down which pins they use** in
   BRINGUP Phase 2; the sensor wiring adapts around them.
4. Screw on standoffs if included, SD card in, plug in the 5 V 3 A supply.

### Ari: SD card + SSH [Manual]

Only if you're flashing a new card (the loaner's card isn't ours):
1. On the Mac, open Raspberry Pi Imager. Device: **Raspberry Pi 4**. OS: **Raspberry Pi OS (64-bit)**, the
   desktop one (not Lite). Storage: the SD card.
2. Edit settings: hostname `pulse`; username `pulse` + a password; Wi-Fi SSID/password; country US; time zone
   America/New_York. Services tab: enable SSH, **public-key auth**, paste the output of
   `cat ~/.ssh/id_ed25519.pub`.
   - Venue Wi-Fi with a login page or university login won't work for the Pi. Use a **phone hotspot** for the Pi
     and every laptop that needs to SSH in.
3. Write, put the card in the Pi, boot (first boot takes a few minutes).

Then, either way:
```bash
ssh-keygen -R pulse.local        # clears the old Pi's fingerprint; avoids "REMOTE HOST IDENTIFICATION HAS CHANGED"
ssh pulse@pulse.local            # should log in without a password
ssh-copy-id pulse@pulse.local    # only if it asked for a password
hostname -I                      # on the Pi: note the IP as a backup for PI_HOST
```

---

## Phase 3. Pi setup + serial ports (about 30 min)

| Who | Does |
| --- | --- |
| Ari | [Claude Code] **A2** (main checkout, separate session from A1) |
| EE | [Manual] Loopback jumpers when A2 asks; multimeter the Pi's 5 V pins; start the demo panel |
| CS2 | Keep B1 going |

### A2. Pi setup, kiosk, deploy, loopback [Claude Code, Ari]

```
Read CLAUDE.md and docs/hardware.md. The Pi is reachable at $PI_HOST (pulse@pulse.local) with key auth.

Write:
- tools/uart_loopback.py PORT BAUD: writes test bytes, checks they come back (for a jumpered TX to RX test).
- scripts/setup_pi.sh: idempotent, prints what it changed, never reboots on its own. First detect and print the
  OS, 64-bit or not, desktop or Lite (stop with a clear message on Lite), compositor (labwc, wayfire or X11) and
  the Chromium binary. Then: back up and edit /boot/firmware/config.txt so enable_uart=1, dtoverlay=disable-bt and
  dtoverlay=uart3 each appear once; serial login console off, serial hardware on (raspi-config nonint); user in
  dialout; apt python3-venv and cursor hiding for the compositor; ~/pulse/.venv with pi/requirements.txt;
  scripts/pulse.service (systemd, uvicorn from the venv, reads ~/pulse/.env, PULSE_SOURCE default sim until the
  sensors are live, Restart=always) enabled; Chromium kiosk autostart to http://localhost:8000 with no restore
  bubbles, error dialogs, translate prompts or pinch zoom; screen blanking off.
- scripts/deploy.sh (from a Mac): rsync to ~/pulse on $PI_HOST excluding .git, .venv, .env, recordings,
  __pycache__ (the Pi keeps its own .env); reinstall requirements only if they changed; restart pulse.service;
  reload the kiosk page. It must also work on a fresh Pi where the venv and service don't exist yet.
- scripts/pi_logs.sh: tail the service journal.

Then do it for real: deploy, run setup_pi.sh, show me the output, and ask before rebooting.
After the reboot, walk me through docs/BRINGUP.md Phase 3 one item at a time:
- Tell me to shut the Pi down (sudo shutdown now), have EE jumper pin 8 to 10 AND pin 7 to 29 with the power
  off, then boot.
- Find the UART3 device (ls -l /dev/ttyAMA*, dmesg), run the loopback on /dev/ttyAMA0 at 256000 and on the UART3
  device at 115200, report both.
- Tell me to shut down and remove the jumpers.
- Confirm the radar comes up full screen by itself in sim mode, and check /?fps=1 on the Pi.
Write the UART3 device into docs/hardware.md and .env.example (C1001_PORT), tick the boxes in docs/BRINGUP.md,
update docs/STATUS.md, commit.
```

**Before Phase 4:** Ari merges A1 (`git merge ld2450`), CS2 pushes B1, Ari pulls and runs
`scripts/deploy.sh` so the Pi has both readers and both dump tools.

---

## Phase 4. Sensors live, both at once (about 45 min)

| Who | Does |
| --- | --- |
| EE | [Manual] Wire both sensors: power-only voltage check first, then data wires (BRINGUP Phase 4) |
| Ari | [Claude Code] **A3**, LD2450 live (after EE's voltage check) |
| CS2 | [Claude Code] **B2**, C1001 live, at the same time on its own UART |

Two people can do this at once: separate UARTs, separate SSH sessions. The app service must be stopped.

### A3. LD2450 live [Claude Code, Ari]

```
The LD2450 is wired per docs/hardware.md and EE confirmed its TX idles at 3.3 V. Over SSH on $PI_HOST:
sudo systemctl stop pulse, then from ~/pulse run .venv/bin/python tools/ld2450_dump.py /dev/ttyAMA0 --multi.
Walk me through docs/BRINGUP.md
Phase 4 LD2450 items one at a time: straight ahead at 1 m, step to MY left, walk toward the sensor, 3 people, max
range, left/right edges, behind the panel, sitting still for 30 s. From what you see, confirm or flip the X and
speed sign constants so output matches the contract (negative x = holder's left, negative speed = approaching),
and fix the parser if anything disagrees with the datasheet. Record 2 minutes to recordings/ld2450_session1.jsonl
on the Pi, copy it to the Mac, and commit a 20-second slice as recordings/sample_ld2450.jsonl. Write every measured
value into docs/hardware.md and BRINGUP.md, update docs/STATUS.md, commit.
```

### B2. C1001 live [Claude Code, CS2]

```
The C1001 is wired per docs/hardware.md and EE confirmed its TX idles at 3.3 V. Over SSH on $PI_HOST (Ari has
already stopped the pulse service; don't start it): from ~/pulse run .venv/bin/python tools/c1001_dump.py on the
C1001_PORT device. Walk me
through docs/BRINGUP.md Phase 4 C1001 items one at a time: someone sits still 1 m away chest facing it; time
presence, breathing and heart rate appearing; compare with a phone or watch heart rate; stand up and walk (numbers
must go null, never fake); repeat behind the panel. If nothing arrives, check TX/RX, then debug the init sequence
against the DFRobot library. If it's still not working after 1.5 hours total on the C1001, stop and tell me so we
can switch to the ESP32 fallback in docs/hardware.md. Record 3 minutes to recordings/c1001_session1.jsonl, commit
a 30-second sample as recordings/sample_c1001.jsonl. Write measured values into docs/hardware.md and BRINGUP.md,
update docs/STATUS.md, commit.
```

---

## Phase 5. Full app live, the GATE (about 1.5 hours, 10 PM at the latest)

| Who | Does |
| --- | --- |
| Ari | [Claude Code] **A4**, live integration + fusion tuning |
| CS2 | [Claude Code] **B3**, replay mode, then **B4** sitrep (separate files only) |
| EE | [Manual] Mount both sensors side by side, same direction, same height; be the test subject; start the body |

### A4. Live integration + fusion tuning [Claude Code, Ari]

```
Read CLAUDE.md, the fusion rules in docs/data-contract.md, the T2 fusion notes in docs/STATUS.md and
pi/pulse/fusion.py. Set PULSE_SOURCE=live in ~/pulse/.env on the Pi, deploy, start the service.
While I run the demo from docs/demo.md behind the panel, watch /api/snapshot over SSH and tell me what's wrong:
jitter, ids swapping, the hidden person fading, lock not acquiring, vitals on the wrong dot.
Fix the known rough edges from STATUS: gate hysteresis so someone at the range edge doesn't flicker into a new
contact, association that survives two people crossing, the still-survivor hold. Propose threshold changes
(smoothing, association gate, hold time, lock cone) with reasoning, apply the ones I approve as named constants.
Fusion takes time as a parameter. Add regression tests from recordings/sample_*.jsonl.
Acceptance = every item in docs/BRINGUP.md Phase 5. Tick them, update docs/STATUS.md, commit.
```

### B3. Replay mode [Claude Code, CS2]

```
Implement PULSE_SOURCE=replay in pi/pulse/sources.py: env REPLAY_LD2450 and REPLAY_C1001 point at recorded .jsonl
files (default recordings/sample_*.jsonl, resolved from the repo root since the server runs from pi/). Feed the raw
bytes through the real parsers at the original timing,
looping, so fusion and the UI see exactly what the sensors sent. Add a test that replays both samples and every
snapshot passes validate_snapshot. Add a README line on running replay. Update docs/STATUS.md, commit.
```

### B4. Command dashboard + AI sitrep [Claude Code, CS2]

Only in new files (`ui/command.html`, a sitrep module) plus the new sitrep endpoints in `main.py`. Never touch the
handheld UI or fusion.

```
Build ui/command.html for a laptop on the same network: a larger radar plus a contacts table, live from /ws.
Add POST /api/sitrep: send the current contacts and targets (no raw frames) to the Gemini API (env GEMINI_API_KEY)
with a strict system prompt: a short radio-style situation report (number of contacts, status, range and bearing
from the operator), no medical claims, nothing beyond the data. Add a "Read aloud" button that sends the text to
ElevenLabs text-to-speech (env ELEVENLABS_API_KEY) and plays it like a radio call; call ElevenLabs from the server
so the key never reaches the browser. If either key is missing or a
call fails, fall back to a deterministic template sitrep and the browser's built-in speech, so the buttons always
work. Standard-library HTTP only (no new dependencies), off the server loop with a short timeout. Keys never logged
or committed. Tests for the fallback path. Update docs/STATUS.md, commit.
```

**Gate check (everyone):** BRINGUP Phase 5 sync box. If it isn't ticked by 10 PM, stop new features and polish
what works.

---

## Phase 6. Judge-proof (about 1 hour)

| Who | Does |
| --- | --- |
| Ari | [Claude Code] **A5**, break tests |
| EE | [Manual] Finish the handheld body, 15 min power bank test, tape/glue cables (BRINGUP Phase 6) |
| CS2 | Finish B4, or help EE and shoot photos |
| Everyone | [Manual] Shoot a rough demo video the moment it works on battery |

### A5. Break tests [Claude Code, Ari]

```
Make Pulse survive a judging table. With me at the Pi, test and fix: unplugging each sensor mid-run (pill goes
offline, UI keeps working, recovers on replug), restarting the server (NO SIGNAL, then recovers by itself),
rebooting the Pi (radar full screen with nobody touching it), a busy room (pick the default demo gate), power bank
(vcgencmd get_throttled under load). Also check on the real screen at 1 m whether the vitals numbers are big enough;
bump them if not. Tick docs/BRINGUP.md Phase 6, update docs/STATUS.md, commit.
```

---

## Phase 7. Saturday night: rehearse + rough submit

| Who | Does |
| --- | --- |
| Everyone | [Manual] Full 3-minute demo from docs/demo.md behind the panel, 3 times (BRINGUP Phase 7) |
| CS2 | [Claude chat] Devpost draft: paste docs/STATUS.md, docs/demo.md and the measured values into the hackathon Project and ask for the Devpost fields filled with real results |
| Ari | [Manual] Create the Devpost project, invite the team (registration emails), paste the draft, submit rough by midnight. Make the repo public |
| EE | [Manual] Gallery photos: device in hand with dots, wiring close-up, demo setup |
| Optional | **S7 buzzer**, only if everything above is done. EE wires a buzzer to a free GPIO, then [Claude Code]: |

```
I've wired a buzzer to GPIO <pin>. Beep faster as the selected or nearest target approaches the lock zone, a steady
double-beep while locked with vitals, and a mute toggle in the UI. It must not block the server loop. Update
docs/hardware.md and docs/STATUS.md, commit.
```

---

## Phase 8. Sunday

| Time | What |
| --- | --- |
| by 7:30 AM | Final demo video (about 2 min: problem, live demo, how it works, limits). Upload to YouTube, unlisted |
| 8:30 AM | Code freeze. Run **A6** |
| 9:30 AM | Devpost final: video link, public repo link, prizes selected, all members listed |
| 10:00 AM | Devpost closes |
| 11:00 AM | Last commit allowed |

### A6. Pre-demo check [Claude Code, Ari]

```
Pre-demo check: run all tests, run sim and replay, deploy to the Pi, and walk the demo script in docs/demo.md
against the code. Confirm the repo is public, the README explains how to run sim mode, and no keys or .env are
committed. List anything that could break in front of a judge, ranked, and fix the top items only with my OK.
```

---

## Any time

**Catch up (new session or a teammate joining) [Claude Code]:**
```
Read CLAUDE.md, docs/STATUS.md and docs/BRINGUP.md and tell me in 5 lines: which phase we're in, what works, what's
in progress, what's next for <Ari | CS2 | EE>, and any open risks.
```

**Debug [Claude Code]:**
```
Bug: <what I did> -> <what I expected> -> <what happened>. Reproduce it first (sim, replay or a test), find the
root cause, fix it, add a regression test, and tell me in two sentences what was wrong.
```

**Judge Q&A practice [Claude chat]:** in the hackathon Project, ask it to grill you as a judge on how it sees
through walls, why two sensors, the heart-rate range, and what a real rescue unit would need.
