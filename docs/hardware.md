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

## C1001 protocol (confirmed from DFRobot_HumanDetection source)

- Driver ported from Arduino library [DFRobot_HumanDetection](https://github.com/DFRobot/DFRobot_HumanDetection) (`DFRobot_HumanDetection.h`, `.cpp`).
- The library **polls** the sensor via `getData()` by sending query frames (`data = 0x0F`) and receiving responses.
- Must be configured to **Sleep Mode** (`0x02`) on init; fall detection mode does not report vitals.
- Vitals need the chest facing the sensor at 0.4 to 1.5 m, person fairly still.
- Sanity ranges (Rule 9): breathing 10 to 25 /min, heart 60 to 100 bpm; 0 or out-of-range values become `None`.

### Frame format

Every command and response follows:

```
53 59 | con (1 B) | cmd (1 B) | len_H len_L (BE16) | data (len B) | checksum (1 B) | 54 43
```

- Header: `53 59` (`'SY'`), Tail: `54 43` (`'TC'`). Total frame length is `9 + len` bytes.
- Checksum: `sum(bytes[0 : 6+len]) & 0xFF` (sum of all preceding bytes modulo 256; confirmed in [DFRobot_HumanDetection.cpp:799, 929-935](https://github.com/DFRobot/DFRobot_HumanDetection/blob/master/DFRobot_HumanDetection.cpp#L799)).

### Confirmed control and command words

- **Set Sleep Mode:** `con = 0x02`, `cmd = 0x08`, `data = [0x02]`, checksum `0xB9` -> `53 59 02 08 00 01 02 B9 54 43` ([DFRobot_HumanDetection.cpp:44](https://github.com/DFRobot/DFRobot_HumanDetection/blob/master/DFRobot_HumanDetection.cpp#L44)). Modes: `0x01` Fall detection, `0x02` Sleep/vitals mode ([DFRobot_HumanDetection.h:100-101](https://github.com/DFRobot/DFRobot_HumanDetection/blob/master/DFRobot_HumanDetection.h#L100)).
- **Query Mode:** `con = 0x02`, `cmd = 0xA8`, `data = [0x0F]` ([DFRobot_HumanDetection.cpp:46](https://github.com/DFRobot/DFRobot_HumanDetection/blob/master/DFRobot_HumanDetection.cpp#L46)).
- **Query Sleep Composite (`sSleepComposite`):** `con = 0x84`, `cmd = 0x8D`, `data = [0x0F]`, checksum `0xCD` -> `53 59 84 8D 00 01 0F CD 54 43` ([DFRobot_HumanDetection.cpp:324](https://github.com/DFRobot/DFRobot_HumanDetection/blob/master/DFRobot_HumanDetection.cpp#L324)).
  Response payload (8 bytes): `[presence, sleepState, avgRespiration, avgHeartbeat, turnover, largeBodyMove, minorBodyMove, apneaEvents]` ([DFRobot_HumanDetection.h:60-71](https://github.com/DFRobot/DFRobot_HumanDetection/blob/master/DFRobot_HumanDetection.h#L60), [DFRobot_HumanDetection.cpp:314-327](https://github.com/DFRobot/DFRobot_HumanDetection/blob/master/DFRobot_HumanDetection.cpp#L314)).
- **Query Human Presence:** `con = 0x80`, `cmd = 0x81` (0 = none, 1 = present; [DFRobot_HumanDetection.cpp:143](https://github.com/DFRobot/DFRobot_HumanDetection/blob/master/DFRobot_HumanDetection.cpp#L143)).
- **Query Movement:** `con = 0x80`, `cmd = 0x82` (0 = none, 1 = still, 2 = moving; [DFRobot_HumanDetection.cpp:149](https://github.com/DFRobot/DFRobot_HumanDetection/blob/master/DFRobot_HumanDetection.cpp#L149)).
- **Query Respiration Value:** `con = 0x81`, `cmd = 0x82` ([DFRobot_HumanDetection.cpp:198](https://github.com/DFRobot/DFRobot_HumanDetection/blob/master/DFRobot_HumanDetection.cpp#L198)).
- **Query Heart Rate:** `con = 0x85`, `cmd = 0x82` ([DFRobot_HumanDetection.cpp:176](https://github.com/DFRobot/DFRobot_HumanDetection/blob/master/DFRobot_HumanDetection.cpp#L176)).

### Code and tools

- Code: `pi/pulse/sensors/c1001.py` implements pure `C1001Parser` (feed byte chunks, resync on `53 59`, verifies checksum and tail), command builders, contract sanity filters, and `C1001Reader(port, baud=115200)` (daemon thread, polls composite vitals, status ok / warming when connected without vitals / stale / offline, reconnects every 2 s, never raises).
- Dump tool: `.venv/bin/python tools/c1001_dump.py /dev/ttyAMA3 [--record recordings/c1001_session1.jsonl]`.

References: [DFRobot SEN0623 wiki](https://wiki.dfrobot.com/SKU_SEN0623_C1001_mmWave_Human_Detection_Sensor), [how2electronics C1001 + ESP32](https://how2electronics.com/esp32-c10).

Fallback if hardware UART issues arise: flash DFRobot's Arduino example onto an ESP32, print JSON over USB serial, read that on the Pi.

## Power

- Check undervoltage on the Pi: `vcgencmd get_throttled` (0x0 is good).
- Pi 4 + screen + both sensors needs a solid 5 V 3 A. Test the power bank early.
