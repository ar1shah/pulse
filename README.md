# Pulse

**A handheld radar that finds people through thin walls and reads their breathing and heart rate from arm's
length, built for rescuers searching homes after a hurricane.**

Built at Knight Hacks IX (UCF, October 2026). Inspired by the "Pulse"
heartbeat sensor from Rainbow Six Siege, except this one is real.

<p align="center">
  <img src="docs/screenshots/t3-3-walker.png" width="640" alt="Pulse radar screen: a breathing contact locked at 1.2 m with heart and breath rate, and a second moving contact further out">
</p>

## The problem

After a hurricane, rescuers go house to house through damaged homes. Finding someone who is trapped, unconscious
or too weak to call out still mostly comes down to shouting and listening. Search radars exist (NASA JPL's FINDER
helped find four men under rubble after the 2015 Nepal earthquake), but they are big, expensive and rare.

We wanted something a rescuer can hold in one hand: point it at a wall and see who is behind it.

## How it works

Pulse fuses two cheap mmWave radars on a Raspberry Pi with a 7" touchscreen:

| | Job | Sensor |
| --- | --- | --- |
| **The scout** | Where are people? Up to 3 at once, about 6 m out, 120 degree field of view | HLK-LD2450, 24 GHz |
| **The medic** | Is this one breathing? Breathing and heart rate, no contact, 0.4 to 1.5 m | DFRobot C1001, 60 GHz |

1. **Find.** The radar screen shows one dot per person, through drywall, wood or foam.
2. **Lock on.** Walk toward a dot and aim. Once it's in the lock zone, breathing and heart rate fill in.
3. **Triage.** Green = moving. Amber = still but breathing: the person to reach first. Gray = not assessed yet.

```
LD2450 --UART 256000--> parser --+
                                 +--> fusion (tracking, smoothing, lock, triage) --> WebSocket 10 Hz --> touchscreen UI
C1001  --UART 115200--> parser --+
```

One Python process (FastAPI) reads both sensors, fuses them and streams snapshots to a plain HTML canvas UI
running full screen in Chromium on the Pi. No cloud and no network needed: it works in a dead zone.

<p align="center">
  <img src="docs/screenshots/t3-2-locked.png" width="400" alt="A still, breathing contact locked in the lock zone">
  <img src="docs/screenshots/t4-5-drawer.png" width="400" alt="Contacts drawer listing a breathing contact and a moving contact">
</p>

## What was hard

- **Two radars that disagree.** The LD2450 gives positions but no vitals; the C1001 gives vitals but no position.
  Fusion only gives vitals to the one tracked person inside the C1001's lock cone.
- **Still people vanish.** The LD2450 is built for moving targets, so a still person drops out, and still people
  are the ones that matter most. Fusion holds a track while the C1001 still senses presence in the lock zone.
- **Noisy left/right.** The LD2450 measures distance well but left/right poorly. One bad return could send a dot
  the wrong way. A small filter (outlier gate, median, smoothing, deadband, 3-frame confirmation) fixed it.
- **Two binary serial protocols**, one using a sign bit instead of two's complement, written from datasheets
  and tested without hardware.
- **Identity.** The sensor's 3 slots reorder between frames, so tracks are matched by nearest neighbor and
  survive two people crossing paths.

## Try it without hardware

Sim mode fakes both sensors and runs the exact same fusion code as the real device.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r pi/requirements.txt
cd pi && PULSE_SOURCE=sim SIM_SCENARIO=demo python -m pulse.main
```

Open http://localhost:8000. The UI is built for an 800x480 screen. Other scenarios: `random`, `cross` (two
people crossing), `edge` (someone at the range limit), `still` (a person the radar keeps losing).

Tests (sensor parsers, fusion rules, scenarios, server):

```bash
pip install -r pi/requirements-dev.txt
cd pi && pytest -q
```

## Build one

| Part | Notes |
| --- | --- |
| Raspberry Pi 4 (2 GB) | Raspberry Pi OS 64-bit, desktop |
| 7" DSI touchscreen, 800x480 | |
| HLK-LD2450 | UART0 (`/dev/ttyAMA0`), 256000 baud |
| DFRobot C1001 (SEN0623) | UART3 (`/dev/ttyAMA3`), 115200 baud |
| 5 V 3 A power bank | |

Both sensors run on 5 V with 3.3 V logic. Wiring, Pi config and protocol notes are in
[docs/hardware.md](docs/hardware.md). Then:

```bash
ssh -t pulse@pulse.local bash pulse/scripts/setup_pi.sh    # once: UARTs, service, kiosk
PI_HOST=pulse@pulse.local scripts/deploy.sh                # ship code, restart, reload the screen
```

Set `PULSE_SOURCE=live` in `~/pulse/.env` on the Pi (see [.env.example](.env.example)). A sensor that isn't
connected shows as offline and the app keeps running.

## Honest limits

- Sees through thin materials (drywall, wood, foam, cardboard), **not** concrete or rubble. A field unit would
  need a lower-frequency radar.
- Not a medical device. The C1001 is rated for heart rate between 60 and 100 bpm, and triage never uses heart rate
  thresholds, only movement and breathing.
- Vitals need about 10 seconds of aiming at someone's chest from within 1.5 m.
- Live mode never fakes a reading: no data means the screen says "settling".

## Repo

```
pi/pulse/     server (main.py), fusion.py, tracker.py, sensors/ (ld2450, c1001, sim)
pi/tests/     pytest suite, runs without hardware
ui/           radar UI: plain HTML/CSS/JS, no build step, no CDNs
tools/        sensor dump and debug tools
scripts/      Pi setup, deploy, kiosk
docs/         hardware, data contract, demo script, team playbook
```

[docs/data-contract.md](docs/data-contract.md) defines the WebSocket message and every fusion rule.
Team working docs: [docs/PLAYBOOK.md](docs/PLAYBOOK.md) and [docs/STATUS.md](docs/STATUS.md).

## Team

Built by Ari Shah, Ananya Varde, Dominic Scarpitta and Alex Weninski.
