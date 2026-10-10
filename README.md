# Pulse

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

## Docs

- `CLAUDE.md`: project context and rules (read by Claude Code every session)
- `docs/data-contract.md`: the WebSocket message and fusion rules
- `docs/hardware.md`: parts, wiring, Pi config, sensor protocols
- `docs/demo.md`: demo script and pitch claims
- `docs/STATUS.md`: what's done and what's next
- `docs/PROMPTS.md`: the Claude Code prompts we build from
