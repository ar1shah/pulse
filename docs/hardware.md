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
| 5 V | Pin 2 | Pin 2 (as wired, ALEX-2) |
| GND | Pin 6 | Pin 9 |
| Sensor TX to Pi RX | Pin 10 (GPIO15, UART0 RX) | Pin 29 (GPIO5, UART3 RX) |
| Sensor RX to Pi TX | Pin 8 (GPIO14, UART0 TX) | Pin 7 (GPIO4, UART3 TX) |
| Linux device | `/dev/ttyAMA0` | `/dev/ttyAMA3` (UART3, seen after setup + reboot on our Pi) |
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

Our Pi (ARI-2): Raspberry Pi OS on Debian 13 trixie, arm64, desktop session `rpd-labwc` (labwc 0.20.2, started
with `-m` so user config merges with the system's), Chromium 154 at `/usr/bin/chromium`. After `setup_pi.sh` +
reboot: `/dev/ttyAMA0` (UART0, PL011) and `/dev/ttyAMA3` (UART3) both exist, owned by `dialout`.

What `setup_pi.sh` sets up besides the serial ports:
- `pulse.service` as a systemd user unit (`~/.config/systemd/user/`), linger on, so it runs at boot without sudo
  for restarts. Env: defaults `PULSE_SOURCE=sim`, overridden by the Pi's own `~/pulse/.env` (never deployed).
- Kiosk: `scripts/kiosk.sh` from `~/.config/labwc/autostart`; it waits for :8000, runs Chromium full screen and
  relaunches it if it dies. The UI's EXIT chip (hold 1.5 s) stops it; a desktop icon, Menu > Accessories > Pulse
  and a `pulse` shell alias (`scripts/pi_launchers.sh`) start it again.
- A blank cursor theme (`XCURSOR_THEME=pulse-blank` in `~/.config/labwc/environment`); delete that line to get the
  cursor back. Screen blanking was already off.
- Touch: Pi OS set `mouseEmulation="yes"` for the panel in `~/.config/labwc/rc.xml`. Untouched for now; if the
  drawer won't scroll with a finger in ARI-5, that is the first thing to try.

Loopback test before sensors are wired (Pi off while jumpering): pin 8 to pin 10 and pin 7 to pin 29, then on the Pi
from `~/pulse`: `.venv/bin/python tools/uart_loopback.py /dev/ttyAMA0 256000` and
`.venv/bin/python tools/uart_loopback.py /dev/ttyAMA3 115200`. Exit 0 = PASS. "Nothing came back" = jumper or
UART not enabled; garbled bytes = baud problem (mini UART instead of the PL011). Both PASS on our Pi (all 5 patterns).

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

Dump tool, from the repo root on the Pi (in live mode stop the service first, it owns the port: `systemctl --user stop pulse`):
`.venv/bin/python tools/ld2450_dump.py /dev/ttyAMA0 --multi [--record recordings/ld2450_session1.jsonl]`.
Each recorded line is `{"t", "raw" (30-byte frame as hex), "targets" (parsed)}`; replay should parse `raw`, since
`targets` bakes in whatever sign constants were set at the time.

A macOS pseudo-terminal can't be set to 256000 baud (`Inappropriate ioctl`), so a fake-serial test on the Mac has
to use `--baud 115200`. Real UARTs and CP2102-style USB adapters take 256000.

The sensor also has Bluetooth; Hi-Link's HLKRadarTool phone app can view targets and switch modes.

References: [ESPHome LD2450](https://new.esphome.io/components/sensor/ld2450),
[RBEGamer/HLK-LD2450](https://github.com/RBEGamer/HLK-LD2450), [espboards LD2450](https://www.espboards.dev/sensors/ld2450/).

## C1001 protocol (ported from DFRobot_HumanDetection)

Source of truth: DFRobot's Arduino library [DFRobot_HumanDetection](https://github.com/DFRobot/DFRobot_HumanDetection), pinned at commit
`f98f64e` (2025-10-24). Every link below points at that commit. The repo also has a Raspberry Pi Python port
(`python/raspberrypi/`), a looser copy of the same logic (no checksum check on replies); we ported the C++.
The [SEN0623 wiki](https://wiki.dfrobot.com/SKU_SEN0623_C1001_mmWave_Human_Detection_Sensor) has specs only, no
protocol: 5 V, max 100 mA, breathing and heart rate at 0.4 to 1.5 m with the chest facing the sensor, breathing 10 to
25 /min, heart rated accurate 60 to 100 bpm (it does report outside that), presence to 11 m, 100 x 100 deg beam.

UART 115200 8N1 ([basics.ino L28-L34](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/examples/basics/basics.ino#L28-L34)).

### Frame ([getData L791-L801](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L791-L801), [sumData L929-L938](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L929-L938))

```
53 59 | ctrl | cmd | len_hi len_lo | data (len bytes) | sum | 54 43
```

- Length is **big-endian** u16 (the old hint didn't say).
- `sum` = low byte of the sum of every byte before it (header through data).
- Requests and replies have the same layout. A reply carries the same ctrl and cmd as its request
  ([getData state machine L830-L921](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L830-L921)). The value is `data[0]` (`buf[6]` in the library); 2-byte
  values are big-endian (`buf[6] << 8 | buf[7]`, e.g. [L163](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L163)).
- Every query sends one data byte, `0x0F`.

Example, heart rate query: `53 59 85 82 00 01 0F C3 54 43`. Work mode set to sleep: `53 59 02 08 00 01 02 B9 54 43`.

### The library polls

It never waits for pushed reports. Each read is `getData()`: write the query, read until a frame with the same
ctrl/cmd arrives and its checksum matches, resend every 1 s, give up after 5 s
([`TIME_OUT` L37](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.h#L37), [resend L805-L814](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L805-L814), [timeout L824-L828](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L824-L828)). It flushes the
input buffer before each send and ignores any other frame. Our reader polls the same way; frames nobody asked for
are counted (`reader.unsolicited`, shown by the dump tool) so we learn on Saturday whether this firmware also pushes.

### Command words used

| ctrl cmd | Data sent | Reply `data[0]` | Library |
| --- | --- | --- | --- |
| `01 83` | `0F` | HP LED state (0 off, 1 on). `begin()` uses it as the "sensor is up" ping | [begin L19-L30](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L19-L30), [getLEDLightState L101-L121](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L101-L121) |
| `02 A8` | `0F` | work mode: 1 fall, 2 sleep | [configWorkMode L38](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L38), [getWorkMode L69-L78](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L69-L78) |
| `02 08` | mode | (not awaited: raw write, then 10 s wait) | [configWorkMode L36-L50](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L36-L50) |
| `01 03` | `01` | HP LED on | [configLEDLight L80-L99](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L80-L99) |
| `01 02` | `0F` | module reset, then 10 s wait | [sensorRet L123-L133](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L123-L133) |
| `80 81` | `0F` | presence: 0 nobody, 1 somebody | [smHumanData L142-L147](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L142-L147) |
| `80 82` | `0F` | movement: 0 none, 1 still, 2 active | [L148-L153](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L148-L153) |
| `81 82` | `0F` | breathing value (/min) | [getBreatheValue L194-L203](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L194-L203) |
| `85 82` | `0F` | heart rate (bpm) | [getHeartRate L172-L181](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L172-L181) |
| `84 8C` | `0F` | reporting mode (ours shipped as 1; we use 0, see "Measured" below) | `smSleepData(eReportingmode)` |
| `84 0F` | mode | sets the reporting mode; the sensor echoes the value back | `configSleep(eReportingmodeC, v)` |

Also in the library, not used by us: `80 83` body movement 0 to 100, `80 84` distance (2 bytes), `81 81` breathing
state (1 normal, 2 fast, 3 slow, 4 none), `84 8D` sleep composite (8 bytes incl. average breath/heart), fall-mode
words under ctrl `83`. Quirk: the header declares `eHPLed = 0x04`, but the code sends cmd `03` for the HP LED and
`04` for the fall LED ([L84-L97](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L84-L97)); we follow the code.

### Init sequence ([basics.ino setup L37-L63](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/examples/basics/basics.ino#L37-L63))

1. `begin()`: wait 10 s after power-up, then ping `01 83`.
2. `configWorkMode(eSleepMode)` ([`eSleepMode = 0x02`](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.h#L92)): query `02 A8`; if it isn't 2, write `02 08 [02]`,
   wait 10 s, query again to verify. Sleep mode is the one that reports breathing and heart rate.
3. `configLEDLight(eHPLed, 1)`: `01 03 [01]`.
4. `sensorRet()`: `01 02`, then wait 10 s. The example says the reset is required after setting anything.
5. `loop()` ([L81-L116](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/examples/basics/basics.ino#L81-L116)): presence, movement, body movement, breath, heart, then `delay(1000)`.

What `C1001Reader` does differently, on purpose:
- No blind 10 s wait before the ping: the ping is retried until the sensor answers (it can't answer before it boots).
- The LED write and the reset only happen if the mode or the LED actually needed changing. On a sensor that is
  already set up (the library queries the mode before switching, which suggests it persists; confirm on Saturday) the reader
  is polling within a second of opening the port; a fresh sensor takes about 20 s (two 10 s waits).
- Vitals queries give up after 2 s instead of 5 s, and a round stops early if presence gets no reply, so a dead
  sensor goes stale quickly. 3 silent rounds in a row: close the port, reconnect every 2 s.
- Not ported: the library's per-byte `delay(50)` and its `data == previous byte` guards in the length states
  ([L873-L891](https://github.com/DFRobot/DFRobot_HumanDetection/blob/f98f64ea8bc29a9bb0fbb1624401ce8db126f966/DFRobot_HumanDetection.cpp#L873-L891)), which only exist because its loop re-reads a stale `data` variable. We also check the
  `54 43` tail, which the library writes but never checks.

### Measured on our sensor (ALEX-2, Sat Oct 10)

Recordings: `recordings/c1001_session1.jsonl` (150 s, the server's reader: walk-up, 60 s seated, leave) and the
30 s slice `recordings/sample_c1001.jsonl` (seated, breath 18 to 23, heart 77 to 82). Probe runs `alex2_*.jsonl` are
on the Pi. Decode any of them with `tools/c1001_timeline.py` (per second around the arrival, or `--summary`).

**The walk-up problem was the reporting mode.** In reporting mode 1 (what `84 8C` read on our sensor) the firmware
only computes breath and heart while its own "in bed" state (`84 81`) is 1:
- Already in front when the sensor powered up: in-bed 1, vitals pushed every ~3 s. Moved to ~2 m: in-bed stayed 1
  for ~30 s, then it pushed in-bed 0 and stopped pushing everything (vitals, distance, position).
- Walked up after power-up: presence at once, in-bed stayed 0 for all 125 s seated, no breath or heart ever.
- A module reset (`01 02`) while seated didn't flip it either (95 s, in-bed 0).
- **And in mode 1 the breath/heart queries kept answering the last values (15 /min, 86 bpm) after it stopped
  measuring.** Passed through, that would be fake vitals. The reader now reports no breath/heart while presence is 0.

**Reporting mode 0 fixes it.** `84 0F 00`: vitals 6 s later while seated, in-bed still 0. Walk-ups in mode 0:

| Run | Tool | First breath | First heart | Breath in fusion's 10 to 25 |
| --- | --- | --- | --- | --- |
| 1 | probe | 7.6 s | 10.8 s | ~11 s |
| 2 | dump tool (the server's reader) | 7.3 s | 10.2 s | ~13 s |

Times are from presence no -> yes. Two runs, not three (the third was dropped for time). `C1001Reader._init`
queries `84 8C` and writes 0 only if it differs, then verifies (no reset needed). Checked on the sensor: it read
1, wrote 0, read back 0.

Other things we measured:
- **Settings persist across a power cycle**: after a Pi reboot the sensor still read work mode 2, reporting mode 1,
  HP LED on (all set before the reboot). Mode 0 surviving a power cycle is not checked yet; the reader sets it
  either way.
- **Breath ramps.** In mode 0 the first breath values start low (5, 7, 8) and climb ~1 /min every 3 s to the
  real rate (22 to 23 after ~30 s). Heart is plausible from its first value. So the first ~25 s of breath is the
  firmware converging, not the person's rate.
- **Query replies are slower in mode 0**: median ~350 ms (max 1.1 s) vs ~105 ms in mode 1, none lost. One
  4-query poll round takes ~1.5 s, inside the reader's 3 s stale limit.
- **It reads people outside the vitals zone and from the operator side.** With Ari ~2 m away on the operator side
  (behind the device), it kept presence 1, a distance of 131 to 178 and fresh breath 12 to 16 / heart 90 to 124. In
  mode 0 the numbers did NOT go null quickly when Ari moved away; they went null only when presence went 0.
  Not yet tested: the real handheld case (operator ~0.4 m behind, nobody in front). See STATUS for the open test.
- Empty room (before any of this): presence 0, breath/heart null, no phantom values. Frames: 0 bad in every run.
- Pushed frames (cmd top bit clear = sent unasked): `80 01` presence, `80 02` movement, `80 03` body movement
  (0 to 100), `80 04` distance, `80 05` position (3 x big-endian sign-magnitude: x, y, z), `81 02` breath,
  `85 02` heart, `84 01` in-bed, `81 05` / `85 05` (mode 0 only, ~1 per 3 s, probably waveform), `07 07` (0/1,
  not in the library), `01 01` (value 15, every ~60 s, looks like a heartbeat). After a reset it also pushes its
  settings: `84 00` 1 (sleep monitoring on), `81 00` 1, `85 00` 1, `84 13` 0, `84 14` 0, `84 0C`, `84 0D`, `02 A2..A4`.
- Distance (`80 04` / `80 84`) is not in metres we can trust: about 47 to 59 with Ari seated at ~1 m, 119 to 178 with
  Ari at ~2 m. Monotonic, units unclear.
- Work mode query `02 A8` = 2 and HP LED = 1 at every start, so the reader's mode switch and reset never ran.

### Code (ALEX-1)

`pi/pulse/sensors/c1001.py`:
- `C1001Parser`: pure, incremental. Feed any chunks; resyncs on `53 59`, verifies checksum and tail, rejects a length
  over 64 (a corrupted length can't stall it), counts `good` / `bad` / `bad_checksum` / `skipped_bytes`.
  `feed_with_raw` also returns each frame's bytes.
- `build_frame`, `query`, `cmd_set_work_mode`, `cmd_hp_led`, `cmd_reset`, `decode_moving`, `decode_vital`.
- ALEX-2: init also puts the sensor in real-time reporting mode (`84 0F 00`, only if `84 8C` isn't 0), and a
  reading with presence 0 never carries breath or heart. `describe(frame)` / `is_push(frame)` name any frame.
  `tools/c1001_probe.py` (poll + extra words + one-off sets + reset strategies, records what was sent too) and
  `tools/c1001_timeline.py` (decode a recording) are the experiment tools.
- `C1001Reader(port, baud=115200)`: `.start()`, `.stop()`, `.latest(now) -> (C1001Reading | None, status)`. Never
  raises. Status: `offline` (port not open, or the sensor hasn't answered the ping since it opened), `warming`
  (answering, but no breath or heart value seen yet since connecting; this includes the mode switch and reset
  waits), `stale` (no reading for > 3 s; the contract's 1 s is too tight for a 1 Hz poll), `ok`.
- Reading values: presence = reply 1; moving = True for 2 (active), False for 1 (still), None for 0; breath and heart
  pass through raw (fusion applies the 10 to 25 / 45 to 150 ranges), except 0 and 0xFF become None (no reading,
  never invented).
- `LiveSource` picks it up from env `C1001_PORT` (no edits to `sources.py`).

Dump tool, from the repo root on the Pi (in live mode stop the service first, it owns the port: `systemctl --user stop pulse`):
`.venv/bin/python tools/c1001_dump.py /dev/ttyAMA3 [--record recordings/c1001_session1.jsonl]`. It runs the real
reader, so it shows the init phase, status, presence / moving / breath / heart, frames/s, bad frames, timeouts and
any unsolicited frames. Recorded lines: `{"t", "kind": "frame", "raw", "ctrl", "cmd", "data"}` for every frame the
sensor sends and `{"t", "kind": "reading", "presence", "moving", "breath_rpm", "heart_bpm"}` per poll round.

Fallback if the port stalls: flash DFRobot's `basics.ino` onto an ESP32, print JSON over USB serial, read that on
the Pi.

## Power

- Check undervoltage on the Pi: `vcgencmd get_throttled` (0x0 is good).
- Pi 4 + screen + both sensors needs a solid 5 V 3 A. Test the power bank early.
