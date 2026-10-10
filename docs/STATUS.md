# Status

Update this at the end of every task: tick the box, add a one-line note, keep "Next up" current.
Task ids match docs/PROMPTS.md.

## Next up
- T2 server + sim mode + minimal fusion (PLAN)

## Friday night
- [ ] T0 repo created, pushed, teammates added, SSH key on Pi
- [x] T1 scaffold + data contract in code
- [ ] T2 server + sim mode + minimal fusion
- [ ] T3 radar UI
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
