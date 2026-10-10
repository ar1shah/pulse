# Bring-up checklist

Same phase numbers as `docs/PROMPTS.md`, which has the how-to and the prompts for every box here.
Owner tags: **[EE]**, **[Ari]**, **[CS2]**, **[All]**. Fill in every blank; the numbers go into
`docs/hardware.md` and the Devpost.

**Two rules the whole time:**
- Power OFF before plugging or unplugging any wire (Pi: `sudo shutdown now`, wait for the green LED to stop, unplug).
- Pi GPIO pins are 3.3 V only. A sensor TX at 5 V into a Pi pin can kill the Pi. Always measure first.

---

## Phase 1. Unbox + start the parsers

- [ ] [EE] Inventory: Pi 4, LD2450 + cable, C1001 + cable, screen + ribbon, 5 V 3 A supply, microSD
- [ ] [EE] Photo every part on the table (Devpost gallery)
- [ ] [EE] Pin labels on each sensor. LD2450 order: ______ C1001 order: ______
- [ ] [EE] Sensor cable connectors: do lab female jumpers fit? If not, plan: ______
- [ ] [Ari] SD card decision: loaner card is ours (move it) / not ours (flash new)
- [ ] [Ari] A1 started in worktree `ld2450`
- [ ] [CS2] B1 started
- [ ] **Sync:** parts accounted for, both parser sessions running

## Phase 2. Pi + screen boot

- [ ] [EE] Ribbon in the DISPLAY port (not CAMERA), both latches closed
- [ ] [EE] Screen power wires on GPIO pins (if any): 5 V pin ______ GND pin ______
- [ ] [Ari] SD card flashed (64-bit desktop, hostname `pulse`, user `pulse`, SSH key, hotspot Wi-Fi) or moved
- [ ] [EE] Pi boots, desktop shows on the 7" screen
- [ ] [EE] Tap the screen, including the corners: touch registers
- [ ] [Ari] `ssh pulse@pulse.local` works from the Mac with no password
- [ ] [CS2] `ssh pulse@pulse.local` works from CS2's laptop with no password
- [ ] [Ari] `vcgencmd get_throttled` = `0x0` on the bench supply
- [ ] [Ari] `vcgencmd measure_temp` under 70 C idle: ______ C
- [ ] [Ari] Pi IP from `hostname -I`: ______
- [ ] **Sync:** Pi on the screen and reachable over SSH from both CS laptops

## Phase 3. Pi setup + serial ports

- [ ] [Ari] A2: setup_pi.sh ran clean, Pi rebooted
- [ ] [Ari] Radar comes up full screen by itself after the reboot (sim mode)
- [ ] [Ari] `/?fps=1` on the Pi: ______ fps
- [ ] [EE] Pi off. Jumper pin 8 to pin 10 and pin 7 to pin 29. Pi on
- [ ] [Ari] Loopback `/dev/ttyAMA0` at 256000: pass
- [ ] [Ari] UART3 device name: ______ ; loopback at 115200: pass
- [ ] [EE] Pi off. Jumpers removed
- [ ] [EE] Multimeter: Pi 5 V pins read ______ V
- [ ] [Ari] A1 merged, B1 pushed, `scripts/deploy.sh` run so the Pi has both readers and dump tools
- [ ] **Sync:** both serial ports proven, Pi boots into the radar, both readers deployed

If a loopback fails, it's the Pi config, not a sensor. Fix it before Phase 4.

## Phase 4. Sensors live

Power check, both sensors (EE):
- [ ] Pi off. Sensor power only: LD2450 5V to pin ______ GND to pin ______; C1001 5V to pin ______ GND to pin ______
      (default 2/6 and 4/9; if the screen uses a 5 V pin, run both sensors off the other 5 V pin via a breadboard rail)
- [ ] Pi on. LD2450 TX pin to GND: ______ V (about 3.3 V is OK. **5 V: stop**)
- [ ] C1001 TX pin to GND: ______ V (about 3.3 V is OK. **5 V: stop**)
- [ ] Pi off. Data wires: LD2450 TX to pin 10, RX to pin 8; C1001 TX to pin 29, RX to pin 7. Pi on

LD2450 (Ari, A3):
- [ ] Frames about 10/s, bad frames near 0
- [ ] Straight ahead at 1 m: y about 1000 mm, x about 0
- [ ] Step to the holder's left: x negative (else flip the X constant)
- [ ] Walk toward it: speed negative (else flip the speed constant)
- [ ] 3 people show at once
- [ ] Max range walking away: ______ m
- [ ] Left/right edge at 2 m: ______ deg
- [ ] Behind the panel: detected? ______
- [ ] Sitting still: drops out after ______ s (or never)
- [ ] 2-minute session recorded, 20 s sample committed

C1001 (CS2, B2):
- [ ] Frames arriving, checksum errors not climbing
- [ ] Person still at 1 m, chest facing: presence after ______ s
- [ ] Breathing after ______ s, value ______ /min
- [ ] Heart rate after ______ s, value ______ bpm; phone/watch says ______ bpm
- [ ] Person walks around: numbers go null (no fake values)
- [ ] Behind the panel: works? ______
- [ ] 3-minute session recorded, 30 s sample committed
- [ ] **Sync:** both sensors give sane data, recordings committed

If the C1001 is still silent after 1.5 hours: ESP32 fallback (docs/hardware.md).

## Phase 5. Full app live: THE GATE (10 PM latest)

- [ ] [EE] Both sensors mounted side by side, same direction, same height
- [ ] [Ari] `PULSE_SOURCE=live`, both status dots ok
- [ ] [EE] Person at 1 m straight ahead shows in both sensors
- [ ] [Ari] Dots move the right way: holder's left is screen left, walking closer moves the dot down
- [ ] [Ari] Sit at 1 m straight ahead: lock-on, vitals on **that** dot, amber when still
- [ ] [Ari] Two people cross paths: ids don't swap
- [ ] [Ari] Person at the range edge doesn't flicker into new contacts
- [ ] [Ari] Tap a dot: card shows sensible range and bearing
- [ ] [Ari] 2 / 4 / 6 m buttons work; at 2 m far people disappear
- [ ] [CS2] Replay mode runs the recordings on a laptop
- [ ] **Sync / GATE:** live dots + live vitals on the screen. Rough demo video shot right now

## Phase 6. Judge-proof

- [ ] [Ari] Unplug LD2450 (Pi off first, or pull just its TX wire): pill offline, app keeps going, recovers
- [ ] [Ari] Same for the C1001
- [ ] [Ari] Restart the server: NO SIGNAL, then recovers by itself
- [ ] [Ari] Reboot the Pi: radar full screen with nobody touching it
- [ ] [Ari] Vitals readable from 1 m away on the real screen
- [ ] [EE] Everything mounted in the body; cables taped or glued so a judge can't pull them
- [ ] [EE] 15 minutes on the power bank: `get_throttled` ______ , temp ______ C (want 0x0 and under 80 C)
- [ ] [All] Someone who didn't build it can use it with no explanation
- [ ] [CS2] Sitrep works with keys and without (fallback), if built
- [ ] **Sync:** handheld runs on battery and survives being handed to a stranger

## Phase 7. Saturday night

- [ ] [All] Demo script from docs/demo.md behind the panel, 3 times in a row
- [ ] [All] Someone walks around at 3 m during the demo; the demo gate hides them
- [ ] [All] Rough demo video saved
- [ ] [EE] Gallery photos: in hand with dots, wiring close-up, demo setup
- [ ] [Ari] Devpost project created, team invited with registration emails, rough version submitted
- [ ] [Ari] Repo public
- [ ] **Sync:** rough submission in by midnight

## Phase 8. Sunday

- [ ] [All] Final video uploaded (YouTube, unlisted) by 7:30 AM
- [ ] [Ari] Code freeze 8:30 AM, A6 pre-demo check clean
- [ ] [Ari] Devpost final by 9:30 AM: video, public repo, prizes (Embedded, Useful, AI/Gemini/ElevenLabs if built)
- [ ] [All] Last commit before 11:00 AM
- [ ] [All] Demo kit packed: device, charged power bank, bench supply, panel, chair, laptop, spare jumpers
