# Hardware

## Parts

| Part | Notes |
| --- | --- |
| Raspberry Pi 4 Model B, 2GB | Raspberry Pi OS 64-bit, desktop version (needed for Chromium kiosk). |
| Hosyond 7" DSI capacitive touchscreen, 800x480 | Connected via DSI ribbon. May also take 5 V from a GPIO pin. |
| HLK-LD2450, 24 GHz | Tracking radar. 5 V supply, 3.3 V UART. 256000 baud. |
| DFRobot C1001 (SEN0623), 60 GHz | Vitals radar. 5 V, max 100 mA, 3.3 V UART. 115200 baud. |
| microSD, jumpers, breadboard | New microSD, flashed fresh with Raspberry Pi Imager (not the loaner's card). Jumpers and breadboard from the senior design lab. |
| Power bank, 5 V at 3 A | For handheld. Bench: use a proper 5 V 3 A supply. |

## Pi access

- SSH: `PI_HOST` env var, set to `pulse@pulse.local` (also in `.env`).
- Set up key auth from your Mac once so scripts and Claude Code can SSH without a password:
  `ssh-copy-id $PI_HOST`
- Network: venue Wi-Fi with a login page (captive portal or university login) won't work for the Pi. Put the Pi
  and every laptop that needs to SSH in on the same phone hotspot.

## Wiring

Sensor TX goes to Pi RX. Sensor RX goes to Pi TX.

| Wire | LD2450 | C1001 |
| --- | --- | --- |
| 5 V | Pin 2 | Pin 4 |
| GND | Pin 6 | Pin 9 |
| Sensor TX to Pi RX | Pin 10 (GPIO15, UART0 RX) | Pin 29 (GPIO5, UART3 RX) |
| Sensor RX to Pi TX | Pin 8 (GPIO14, UART0 TX) | Pin 7 (GPIO4, UART3 TX) |
| Linux device | `/dev/ttyAMA0` | Check with `ls -l /dev/ttyAMA*` after reboot (often ttyAMA3 or ttyAMA1) |
| Baud | 256000 | 115200 |

If the screen takes a GPIO 5 V pin, run both sensors off the other 5 V pin via a breadboard rail and use any free
GND (6, 9, 14, 20, 25, 30, 34, 39). Record the actual pins in the Phase 4 checklist in docs/PLAYBOOK.md.

Before connecting a sensor: multimeter its TX pin, it should idle near 3.3 V, never 5 V.

## Pi config

`/boot/firmware/config.txt` (managed by `scripts/setup_pi.sh`):

```
enable_uart=1
dtoverlay=disable-bt
dtoverlay=uart3
```

Plus: serial login console OFF, serial hardware ON (`raspi-config`), user in `dialout` group.

Loopback test before sensors arrive: jumper pin 8 to pin 10, run `tools/uart_loopback.py /dev/ttyAMA0 256000`.
Same with pins 7 and 29 for UART3.

Plan B: USB to serial adapter (CP2102 or similar that supports 256000) shows up as `/dev/ttyUSB0`.
Works on the Pi and on a Mac (`/dev/tty.usbserial-*`).

## LD2450 protocol (verify against the datasheet when the sensor arrives)

Data frame, 30 bytes, pushed continuously:

```
AA FF 03 00 | target1 (8 bytes) | target2 (8 bytes) | target3 (8 bytes) | 55 CC
```

Each target, 4 little-endian uint16 values:

| Bytes | Value | Unit | Encoding |
| --- | --- | --- | --- |
| 0 to 1 | X | mm | sign bit: top bit SET = positive, magnitude = low 15 bits |
| 2 to 3 | Y | mm | same |
| 4 to 5 | speed | cm/s | same |
| 6 to 7 | distance resolution | mm | plain uint16 |

All 8 bytes zero = empty slot. Decode: `v = raw & 0x7FFF; v = v if raw & 0x8000 else -v`.

Datasheet example (used as a test vector): `AA FF 03 00 0E 03 B1 86 10 00 40 01` + 16 zero bytes + `55 CC` is one
target at x -782 mm, y 1713 mm, speed -16 cm/s, resolution 320 mm.

Conventions to confirm empirically on Saturday:
- X sign vs the holder's left/right (contract wants negative = left).
- Speed sign vs approaching/receding (contract wants negative = approaching).

Both are one constant each at the top of `pi/pulse/sensors/ld2450.py`: `X_SIGN` and `SPEED_SIGN` (both `+1` until the
live test). Decoded values are multiplied by them, so a flip is a one-character change.

Config commands (frames start `FD FC FB FA`, end `04 03 02 01`, little-endian length then command word).
Hints, verify against the datasheet:
- Enable config: `FD FC FB FA 04 00 FF 00 01 00 04 03 02 01`
- Multi-target tracking: `FD FC FB FA 02 00 90 00 04 03 02 01`
- Single-target tracking: `FD FC FB FA 02 00 80 00 04 03 02 01`
- End config: `FD FC FB FA 02 00 FE 00 04 03 02 01`
- ACK (assumed, verify): same header/tail, length, command word with `0x0100` set (e.g. `FF 01`), LE16 status
  (0 = success), then any data. The enable-config ACK carries protocol version and buffer size.

The length field counts the command word plus its value. `ld2450.command_frame()` builds these, `parse_ack()` reads
the replies; the parser picks ACKs out of the data stream so they never count as bad frames.

Code (A1): `pi/pulse/sensors/ld2450.py` has the pure `Ld2450Parser` (feed any byte chunks, resyncs on the header,
checks the tail, counts good/bad frames), the command builders, and `Ld2450Reader` (pyserial 8N1 in a daemon thread,
sends enable config + multi-target + end config on connect, status ok / stale after 1 s without a frame / offline,
reconnects every 2 s). `PULSE_SOURCE=live` reads it from env `LD2450_PORT` (default `/dev/ttyAMA0`).

Dump tool, from the repo root on the Pi (stop the service first, it owns the port):
`.venv/bin/python tools/ld2450_dump.py /dev/ttyAMA0 --multi [--record recordings/ld2450_session1.jsonl]`.
Each recorded line is `{"t", "raw" (30-byte frame as hex), "targets" (parsed)}`; replay should parse `raw`, since
`targets` bakes in whatever sign constants were set at the time.

A macOS pseudo-terminal can't be set to 256000 baud (`Inappropriate ioctl`), so a fake-serial test on the Mac has
to use `--baud 115200`. Real UARTs and CP2102-style USB adapters take 256000.

The sensor also has Bluetooth; Hi-Link's HLKRadarTool phone app can view targets and switch modes.

References: [ESPHome LD2450](https://new.esphome.io/components/sensor/ld2450),
[RBEGamer/HLK-LD2450](https://github.com/RBEGamer/HLK-LD2450), [espboards LD2450](https://www.espboards.dev/sensors/ld2450/).

## C1001 protocol (hints only; DFRobot_HumanDetection source is the truth)

- Official driver: Arduino library **DFRobot_HumanDetection** (GitHub, DFRobot org). Port it.
- Vitals only in sleep/vitals work mode; the library has a call to set the work mode.
- Vitals need the chest facing the sensor at 0.4 to 1.5 m, person fairly still. Expect a settle delay.
- Ranges: breathing 10 to 25 /min, heart 60 to 100 bpm. Presence detection to about 11 m.
- Frame format is believed to be: header `53 59`, control word, command word, 2-byte length,
  data, 1-byte checksum (sum of preceding bytes & 0xFF), tail `54 43`. **Confirm from the library.**
- Fill in the real control/command words here after porting, with links to the library lines.

References: [DFRobot SEN0623 wiki](https://wiki.dfrobot.com/SKU_SEN0623_C1001_mmWave_Human_Detection_Sensor),
[how2electronics C1001 + ESP32](https://how2electronics.com/esp32-c10).

Fallback if the port stalls: flash DFRobot's Arduino example onto an ESP32, print JSON over USB serial,
read that on the Pi.

## Power

- Check undervoltage on the Pi: `vcgencmd get_throttled` (0x0 is good).
- Pi 4 + screen + both sensors needs a solid 5 V 3 A. Test the power bank early.
