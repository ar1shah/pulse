# Pulse

Teammates: open docs/PLAYBOOK.md and find the phase marked WE ARE HERE.

A handheld radar that finds people through thin walls and reads their breathing and heart rate from arm's length,
built for rescuers searching homes after a hurricane. Knight Hacks IX, UCF, October 2026.

Raspberry Pi 4 + 7" touchscreen + HLK-LD2450 (24 GHz, tracks up to 3 people) + DFRobot C1001 (60 GHz, vitals at 1.5 m).

## Run it without hardware

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r pi/requirements.txt
cd pi && PULSE_SOURCE=sim SIM_SCENARIO=demo python -m pulse.main
# open http://localhost:8000
```

## On the Pi

`PULSE_SOURCE=live` reads the LD2450 on `LD2450_PORT` (default `/dev/ttyAMA0`) and the C1001 on `C1001_PORT`
(see `.env.example`). A sensor that isn't connected shows as offline; the app keeps running.
`tools/ld2450_dump.py PORT --multi` shows raw LD2450 targets, frame rate and bad frames, and can `--record` a session.

## Docs

- `docs/PLAYBOOK.md`: what to do, phase by phase. **Start here.**
- `docs/STATUS.md`: where we are
- `docs/data-contract.md`: the WebSocket message and fusion rules
- `docs/hardware.md`: parts, wiring, Pi config, sensor protocols
- `docs/demo.md`: demo script and pitch claims
