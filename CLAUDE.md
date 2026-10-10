# Pulse

Handheld radar for post-hurricane search and rescue, built at Knight Hacks IX (UCF, Oct 9 to 11 2026).
Inspired by the "Pulse" heartbeat sensor from Rainbow Six Siege: a Raspberry Pi 4 with a 7" touchscreen
shows a radar sweep with one dot per person. Walk up to a dot, aim, and it locks breathing and heart rate.

This is a hackathon. Submissions close Sunday morning. A working, good-looking demo beats clean
architecture. But never break the demo path: sim mode must always run.

## Team and deadlines

- Team of 3: Ari (Pi + LD2450), CS2 (C1001 + AI sitrep), EE (hardware: screen, wiring, power, body, demo panel).
- Devpost final Sun Oct 11, 10:00 AM. Commits stop 11:00 AM. The repo must be public at submission.
- **Gate: live dots + live vitals on the screen by 10 PM Saturday. No new features after the gate.**
- Work goes phase by phase: prompts in docs/PROMPTS.md, tick boxes and measured values in docs/BRINGUP.md.

## Hardware (details: docs/hardware.md, read it before touching pi/pulse/sensors/)

- Raspberry Pi 4 Model B 2GB, Raspberry Pi OS 64-bit (desktop). SSH target is env `PI_HOST`.
- Hosyond 7" DSI capacitive touchscreen, **800x480**. The UI is designed for exactly this size.
- **HLK-LD2450** 24 GHz radar: up to 3 targets, X/Y in mm + speed, ~6 m range, +/-60 deg FOV.
  UART0 `/dev/ttyAMA0` at **256000** baud, binary frames.
- **DFRobot C1001** 60 GHz radar: presence, breathing (10 to 25 /min), heart rate (60 to 100 bpm)
  at 0.4 to 1.5 m, chest facing the sensor. UART3 at **115200**. Gives NO positions.

The LD2450 is the scout (where are people), the C1001 is the medic (is this one breathing).

Hardware safety, always:
- Power the Pi off before connecting or disconnecting any wire or jumper.
- Measure a sensor's TX pin idles at 3.3 V (never 5 V) before connecting it to the Pi.

## Architecture

```
LD2450 --UART--> sensors/ld2450.py --+
                                      +--> fusion.py --> state.py Snapshot --> main.py /ws (10 Hz) --> ui/ (Chromium kiosk on the 7")
C1001  --UART--> sensors/c1001.py  --+                                                          \-> ui/command.html (laptop, reach goal)
sensors/sim.py (fake both sensors) --+   (PULSE_SOURCE=sim swaps in for the two readers)
```

- One Python process on the Pi: FastAPI + uvicorn on port 8000, serves `ui/` and WebSocket `/ws`.
- UI is plain HTML/CSS/JS on one canvas, shown full screen by Chromium in kiosk mode.
- Sim and live go through the SAME fusion code and emit IDENTICAL snapshots.

## The data contract

`docs/data-contract.md` is the single source of truth for the `/ws` message and the fusion rules.
`pi/pulse/state.py` implements it, `ui/contract.js` mirrors its enums. If you change one, change all
three plus the tests in the same commit, and bump `v`.

## Repo layout

```
CLAUDE.md
README.md
docs/            data-contract.md, hardware.md, BRINGUP.md, demo.md, STATUS.md, PROMPTS.md, screenshots/
pi/
  requirements.txt
  pulse/         main.py, state.py, fusion.py, sensors/{ld2450,c1001,sim}.py
  tests/
ui/              index.html, radar.js, style.css, contract.js, debug.html, command.html, fonts/
tools/           ld2450_dump.py, c1001_dump.py, uart_loopback.py
scripts/         setup_pi.sh, deploy.sh, pi_logs.sh, pulse.service
recordings/      captured sensor sessions (.jsonl), gitignored except small samples
hardware/        enclosure sketches, build photos
```

## Commands

Some of these are created by tasks in docs/PROMPTS.md; if one doesn't exist yet, that task hasn't run.

```bash
# Mac setup (once)
python3 -m venv .venv && source .venv/bin/activate && pip install -r pi/requirements-dev.txt

# Run with fake sensors, open http://localhost:8000
cd pi && PULSE_SOURCE=sim SIM_SCENARIO=demo python -m pulse.main

# Tests
cd pi && pytest -q

# Ship to the Pi and restart the service + kiosk
PI_HOST=pulse@pulse.local scripts/deploy.sh

# Pi logs
PI_HOST=pulse@pulse.local scripts/pi_logs.sh

# LD2450 live view on the Pi (sudo systemctl stop pulse first; it owns the port)
.venv/bin/python tools/ld2450_dump.py /dev/ttyAMA0 --multi
```

## Rules

- Python 3.11+. Type hints, dataclasses. Runtime deps allowed: fastapi, uvicorn[standard], pyserial.
  Dev deps: pytest, httpx, playwright. Ask before adding anything else.
- UI: plain HTML/CSS/JS, no frameworks, no build step, **no CDNs, no network at runtime** (venue Wi-Fi is
  unreliable and the Pi may be offline). Fonts and assets live in `ui/`.
- Every sensor module must be testable without hardware: pure parser functions + a thin serial reader.
- Sensor code never crashes the server. On error: mark that sensor `offline`, retry every 2 s.
- **Never fake vitals in live mode.** No reading means `null`, and the UI shows "settling".
- Keep files small and single-purpose. No speculative abstractions.
- Don't change Pi system config (`/boot`, systemd, autostart) except through `scripts/setup_pi.sh`.
- Ask before rebooting the Pi or running anything destructive over SSH.
- Never commit secrets. API keys come from env vars (`.env` is gitignored).
- When a task is done: run the tests, run sim and check it still works, update `docs/STATUS.md`,
  commit with a clear message.

## Honesty rules (judges will poke at these)

- Pulse sees through thin materials (drywall, wood, foam, cardboard), **not** concrete or rubble.
- C1001 heart rate is clamped to 60 to 100 bpm. Triage uses movement + breathing, never HR thresholds.
- No medical or diagnostic wording anywhere in UI copy. See docs/demo.md for claims we can make.

## Gotchas

- LD2450 values use a sign bit: top bit SET means POSITIVE, magnitude is the low 15 bits. Which way is the
  holder's left and which way is approaching is set by `X_SIGN` / `SPEED_SIGN` in `sensors/ld2450.py`, nowhere else.
- 256000 baud needs the PL011 UART (`dtoverlay=disable-bt`), not the mini UART.
- Pi GPIO is 3.3 V only.
- The LD2450 is built for moving people; a still person can drop out. Fusion holds tracks for 3 s and
  keeps a still track alive while the C1001 reports presence in the lock cone.
- LD2450 slot order is not identity; fusion associates detections to tracks by nearest neighbor.
- Chromium kiosk caches hard; deploy reloads the page.
- The 7" screen is judged from about 1 m away: big type, high contrast.
