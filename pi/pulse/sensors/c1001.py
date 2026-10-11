"""DFRobot C1001 (SEN0623) frame parser, query frames and serial reader.

Ported from DFRobot's official Arduino driver, DFRobot_HumanDetection (commit f98f64e); docs/hardware.md,
"C1001 protocol", links the exact lines. The library POLLS: every value is a query frame and the sensor answers
with a frame carrying the same control and command words. This reader does the same.

The parser is pure (bytes in, frames out) so it runs in tests and replay without hardware. The reader is a thin
pyserial loop around it in a daemon thread.
"""
import logging
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Protocol

from ..state import SensorStatus

log = logging.getLogger("pulse.c1001")

# ---- frames: 53 59 | ctrl | cmd | len (BIG-endian u16) | data | sum8 | 54 43 -------------------------------
HEADER = b"\x53\x59"
TAIL = b"\x54\x43"
MIN_FRAME = 9                   # header 2 + ctrl + cmd + len 2 + checksum + tail 2, with no data
MAX_DATA = 64                   # the longest reply the library reads is ~12 bytes; longer = corrupted length
QUERY = b"\x0f"                 # the library sends this one data byte with every query

# ---- control / command words (DFRobot_HumanDetection.cpp) -----------------------------------------------------
PING = (0x01, 0x83)             # HP LED state query; begin() uses it as the "is the sensor up" check
HP_LED_SET = (0x01, 0x03)       # data 1 = HP LED on (configLEDLight(eHPLed, 1))
RESET = (0x01, 0x02)            # sensorRet(): module reset, then 10 s before it answers properly
WORK_MODE_QUERY = (0x02, 0xA8)
WORK_MODE_SET = (0x02, 0x08)    # written raw, the library does not wait for a reply
SLEEP_MODE = 0x02               # eSleepMode: presence + breathing + heart rate. 0x01 is fall mode.
REPORTING_MODE_QUERY = (0x84, 0x8C)
REPORTING_MODE_SET = (0x84, 0x0F)   # configSleep(eReportingmodeC, v); the sensor echoes v back
REALTIME_REPORTING = 0x00       # measured (ALEX-2): in mode 1 (our sensor's default) breath and heart are only
                                # computed while the firmware thinks someone is "in bed" (84 81), which a person
                                # walking up never triggers; mode 0 locks in about 10 s. Persists on the sensor.
PRESENCE = (0x80, 0x81)         # 0 nobody, 1 somebody
MOVEMENT = (0x80, 0x82)         # 0 none, 1 still, 2 active
BREATH = (0x81, 0x82)           # breaths per minute
HEART = (0x85, 0x82)            # beats per minute

# Every word we know a name for, for recordings and the probe tools. Queries have the top bit of cmd set; the
# sensor also pushes reports on its own with the same ctrl and the top bit clear (80 01 = pushed presence).
# Words marked "seen" are not in the library: decoded from what our sensor pushed.
WORDS: dict[tuple[int, int], str] = {
    (0x01, 0x02): "reset", (0x01, 0x03): "hp led set", (0x01, 0x83): "hp led",
    (0x02, 0x08): "work mode set", (0x02, 0xA8): "work mode",
    (0x07, 0x07): "07 07 (seen)",
    (0x80, 0x01): "presence", (0x80, 0x02): "movement", (0x80, 0x03): "body movement",
    (0x80, 0x04): "distance", (0x80, 0x05): "position",
    (0x80, 0x81): "presence", (0x80, 0x82): "movement", (0x80, 0x83): "body movement",
    (0x80, 0x84): "distance", (0x80, 0x85): "position",
    (0x81, 0x01): "breath state", (0x81, 0x02): "breath",
    (0x81, 0x81): "breath state", (0x81, 0x82): "breath",
    (0x84, 0x01): "in bed", (0x84, 0x02): "sleep state", (0x84, 0x0F): "reporting mode set",
    (0x84, 0x81): "in bed", (0x84, 0x82): "sleep state", (0x84, 0x8C): "reporting mode",
    (0x84, 0x8D): "sleep composite",
    (0x85, 0x02): "heart", (0x85, 0x82): "heart",
}
_U16_NAMES = {"distance"}       # library: buf[6] << 8 | buf[7]

# ---- reader ---------------------------------------------------------------------------------------------------
DEFAULT_BAUD = 115200
READ_TIMEOUT_S = 0.05
RESEND_S = 1.0                  # library: resend a query that has had no reply for 1 s
INIT_TIMEOUT_S = 5.0            # library: TIME_OUT, give up on a query after 5 s
POLL_TIMEOUT_S = 2.0            # vitals queries give up sooner so a dead sensor goes stale fast
MODE_SWITCH_WAIT_S = 10.0       # library: delay(10000) after writing the work mode
RESET_WAIT_S = 10.0             # library: delay(10000) after sensorRet()
POLL_S = 1.0                    # library example: one round of queries per second
STALE_S = 3.0                   # no reading for this long = stale (one reading per ~1 s poll)
LOST_AFTER = 3                  # this many poll rounds in a row with no reply at all = reconnect
RETRY_S = 2.0                   # reconnect interval


@dataclass(frozen=True)
class C1001Reading:
    """Latest C1001 report. Raw values: fusion applies the sanity ranges, so a reader may pass through
    whatever it parsed. None means the sensor gave no reading (never a made-up number)."""
    t: float
    presence: bool
    moving: bool | None = None
    breath_rpm: int | None = None
    heart_bpm: int | None = None


@dataclass(frozen=True)
class C1001Frame:
    """One checksum-verified frame, request or reply."""
    ctrl: int
    cmd: int
    data: bytes = b""

    @property
    def word(self) -> tuple[int, int]:
        return self.ctrl, self.cmd

    def value(self) -> int | None:
        """First data byte (buf[6] in the library), or None for an empty frame."""
        return self.data[0] if self.data else None


# ---- building -------------------------------------------------------------------------------------------------

def checksum(buf: bytes) -> int:
    """sumData(): low byte of the sum of every byte before the checksum."""
    return sum(buf) & 0xFF


def build_frame(ctrl: int, cmd: int, data: bytes = QUERY) -> bytes:
    """getData()'s cmdBuf: header, ctrl, cmd, big-endian length, data, checksum, tail."""
    body = HEADER + bytes((ctrl, cmd, (len(data) >> 8) & 0xFF, len(data) & 0xFF)) + data
    return body + bytes((checksum(body),)) + TAIL


def query(word: tuple[int, int]) -> bytes:
    return build_frame(word[0], word[1], QUERY)


def cmd_set_work_mode(mode: int = SLEEP_MODE) -> bytes:
    """configWorkMode()'s raw write, 53 59 02 08 00 01 <mode> <sum> 54 43."""
    return build_frame(*WORK_MODE_SET, bytes((mode,)))


def cmd_hp_led(on: bool = True) -> bytes:
    return build_frame(*HP_LED_SET, b"\x01" if on else b"\x00")


def cmd_reset() -> bytes:
    return query(RESET)


# ---- decoding -------------------------------------------------------------------------------------------------

def decode_moving(raw: int | None) -> bool | None:
    """Movement query: 2 active = moving, 1 still = not moving, 0 none (or no reply) = unknown."""
    if raw == 2:
        return True
    if raw == 1:
        return False
    return None


def decode_vital(raw: int | None) -> int | None:
    """Breath or heart value. 0 (nothing measured) and 0xFF (the library's read-error value) are no reading."""
    if raw is None or raw == 0 or raw == 0xFF:
        return None
    return raw


def describe(frame: C1001Frame) -> tuple[str, int | tuple[int, ...] | None]:
    """(name, value) for any frame, for the probe and timeline tools. Distance is a big-endian u16, position
    is three big-endian 16-bit sign-magnitude values (x, y, z) when 6 bytes long (top bit = sign, seen as
    0x800B for a person near the axis; which side is negative is not confirmed), the rest is data[0]. Unknown words are
    named by their hex and valued by data[0]. Never raises."""
    name = WORDS.get(frame.word, f"{frame.ctrl:02X} {frame.cmd:02X}")
    d = frame.data
    if name in _U16_NAMES and len(d) >= 2:
        return name, d[0] << 8 | d[1]
    if name == "position" and len(d) == 6:
        raw = [d[i] << 8 | d[i + 1] for i in (0, 2, 4)]
        return name, tuple(-(v & 0x7FFF) if v & 0x8000 else v for v in raw)
    return name, frame.value()


def is_push(frame: C1001Frame) -> bool:
    """cmd top bit clear: a report the sensor sent on its own, or the echo of one of our set commands
    (reset 01 02, reporting mode 84 0F). Replies to queries have it set."""
    return not frame.cmd & 0x80


# ---- incremental parser ---------------------------------------------------------------------------------------

class C1001Parser:
    """Feed arbitrary byte chunks; get back checksum-verified frames. Resyncs on 53 59, checks the checksum and
    the 54 43 tail, and bounds the length field so a corrupted one can't stall it. Never raises on bad input."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.good = 0               # frames that passed checksum and tail
        self.bad = 0                # bad checksum, bad tail or impossible length
        self.bad_checksum = 0
        self.skipped_bytes = 0      # garbage between frames

    def feed(self, data: bytes) -> list[C1001Frame]:
        return [f for f, _ in self.feed_with_raw(data)]

    def feed_with_raw(self, data: bytes) -> list[tuple[C1001Frame, bytes]]:
        """Like feed, but also returns each frame's raw bytes (for recordings)."""
        buf = self._buf
        buf += data
        out: list[tuple[C1001Frame, bytes]] = []
        while True:
            start = buf.find(HEADER)
            if start < 0:
                keep = 1 if buf.endswith(HEADER[:1]) else 0     # a lone 0x53 could be half a header
                self.skipped_bytes += len(buf) - keep
                del buf[:len(buf) - keep]
                break
            if start:
                self.skipped_bytes += start
                del buf[:start]
            if len(buf) < 6:
                break
            n = buf[4] << 8 | buf[5]
            if n > MAX_DATA:
                self.bad += 1
                del buf[:1]                     # false header: look for the next one
                continue
            total = 6 + n + 3
            if len(buf) < total:
                break
            if buf[6 + n] != checksum(buf[:6 + n]):
                self.bad += 1
                self.bad_checksum += 1
                del buf[:1]
                continue
            if buf[7 + n:total] != TAIL:
                self.bad += 1
                del buf[:1]
                continue
            raw = bytes(buf[:total])
            out.append((C1001Frame(ctrl=raw[2], cmd=raw[3], data=raw[6:6 + n]), raw))
            self.good += 1
            del buf[:total]
        return out


# ---- serial reader --------------------------------------------------------------------------------------------

class SerialLike(Protocol):
    in_waiting: int

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


def open_serial(port: str, baud: int) -> SerialLike:
    import serial  # pyserial; imported here so sim mode on a Mac never needs it

    return serial.Serial(port, baud, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                         stopbits=serial.STOPBITS_ONE, timeout=READ_TIMEOUT_S)


class _Lost(Exception):
    """The sensor stopped answering: close the port and reconnect."""


class C1001Reader:
    """Talks to the C1001 in a daemon thread, the way DFRobot's library does: init (ping, sleep/vitals work mode,
    real-time reporting mode, HP LED, reset if the work mode or LED changed), then poll presence, movement, breath and heart once a second.
    Reconnects every 2 s. `latest(now)` never raises: (reading | None, status) where status is
    "offline" (port closed or sensor not answering), "warming" (answering, no breath or heart value yet),
    "stale" (no reading for > 3 s) or "ok"."""

    def __init__(self, port: str, baud: int = DEFAULT_BAUD,
                 opener: Callable[[str, int], SerialLike] | None = None,
                 clock: Callable[[], float] = time.time, retry_s: float = RETRY_S) -> None:
        self.port = port
        self.baud = baud
        self.parser = C1001Parser()
        self.timeouts = 0           # queries that got no reply in time
        self.unsolicited: Counter[tuple[int, int]] = Counter()   # frames nobody asked for, by (ctrl, cmd)
        self.on_frame: Callable[[C1001Frame, bytes, float], None] | None = None   # dump tool's recorder hook
        self.phase = "offline"      # offline / init / mode switch / reset wait / polling (for the dump tool)
        self._opener = opener or open_serial
        self._clock = clock
        self._retry_s = retry_s
        self._latest: C1001Reading | None = None
        self._handshake = False     # sensor answered since the port opened
        self._had_vitals = False    # a breath or heart value has been seen since the port opened
        self._ser: SerialLike | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="c1001", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def latest(self, now: float) -> tuple[C1001Reading | None, SensorStatus]:
        r = self._latest
        if not self._handshake:
            return r, "offline"
        if not self._had_vitals:
            return r, "warming"
        if r is None or now - r.t > STALE_S:
            return r, "stale"
        return r, "ok"

    # ---- thread ----

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                self._ser = self._opener(self.port, self.baud)
            except Exception as e:
                # first failure is a warning, the retries every 2 s are not worth a log line each
                log.log(logging.WARNING if failures == 0 else logging.DEBUG,
                        "C1001 %s not available (%s); retrying every %.0f s", self.port, e, self._retry_s)
                failures += 1
                self._stop.wait(self._retry_s)
                continue
            failures = 0
            log.info("C1001 port %s open at %d baud", self.port, self.baud)
            try:
                self._init()
                self._poll_loop()
            except _Lost as e:
                if not self._stop.is_set():
                    log.warning("C1001 %s: %s; reconnecting", self.port, e)
            except Exception as e:
                if not self._stop.is_set():
                    log.warning("C1001 %s read failed (%s); reconnecting", self.port, e)
            finally:
                self._handshake = self._had_vitals = False
                self.phase = "offline"
                self._close()
            self._stop.wait(self._retry_s)

    def _init(self) -> None:
        """begin() + configWorkMode(eSleepMode) + configLEDLight(eHPLed, 1) + sensorRet(), as basics.ino does.
        Two deliberate differences: no blind 10 s wait before the ping (the ping is retried until the sensor
        answers instead), and the LED write and reset only happen if something actually needs changing."""
        self.phase = "init"
        led = self._request(PING, QUERY, INIT_TIMEOUT_S)
        if led is None:
            raise _Lost("no answer to the ping (01 83)")
        self._handshake = True
        log.info("C1001 answering (HP LED %s)", led.value())

        changed = False
        mode = self._request(WORK_MODE_QUERY, QUERY, INIT_TIMEOUT_S)
        if mode is None:
            raise _Lost("no answer to the work mode query (02 A8)")
        if mode.value() != SLEEP_MODE:
            log.info("C1001 work mode %s, switching to sleep/vitals mode", mode.value())
            self.phase = "mode switch"
            self._write(cmd_set_work_mode(SLEEP_MODE))
            self._wait(MODE_SWITCH_WAIT_S)
            mode = self._request(WORK_MODE_QUERY, QUERY, INIT_TIMEOUT_S)
            if mode is None or mode.value() != SLEEP_MODE:
                raise _Lost(f"work mode switch failed (reads {mode.value() if mode else 'nothing'})")
            changed = True
        log.info("C1001 in sleep/vitals work mode")

        rmode = self._request(REPORTING_MODE_QUERY, QUERY, INIT_TIMEOUT_S)
        if rmode is None:
            log.warning("C1001 reporting mode query (84 8C) got no reply; leaving it as it is")
        elif rmode.value() != REALTIME_REPORTING:
            # no reset needed: vitals started about 6 s after this write on the real sensor
            log.info("C1001 reporting mode %s, switching to real-time (%d)", rmode.value(), REALTIME_REPORTING)
            self._request(REPORTING_MODE_SET, bytes((REALTIME_REPORTING,)), INIT_TIMEOUT_S)
            rmode = self._request(REPORTING_MODE_QUERY, QUERY, INIT_TIMEOUT_S)
            if rmode is None or rmode.value() != REALTIME_REPORTING:
                raise _Lost(f"reporting mode switch failed (reads {rmode.value() if rmode else 'nothing'})")
        log.info("C1001 in real-time reporting mode")

        if led.value() != 1:
            if self._request(HP_LED_SET, b"\x01", INIT_TIMEOUT_S) is None:
                log.warning("C1001 HP LED set got no reply")
            changed = True

        if changed:
            # library: "must perform sensorRet after setting data, otherwise the sensor may not be usable"
            self.phase = "reset wait"
            if self._request(RESET, QUERY, INIT_TIMEOUT_S) is None:
                log.warning("C1001 reset got no reply")
            self._wait(RESET_WAIT_S)
            log.info("C1001 reset done")

    def _poll_loop(self) -> None:
        self.phase = "polling"
        silent = 0
        while not self._stop.is_set():
            started = time.monotonic()
            reading = self._poll_once()
            if reading is None:
                silent += 1
                if silent >= LOST_AFTER:
                    raise _Lost(f"no reply for {silent} poll rounds")
            else:
                silent = 0
                if reading.breath_rpm is not None or reading.heart_bpm is not None:
                    self._had_vitals = True
                self._latest = reading
            self._wait(max(0.0, POLL_S - (time.monotonic() - started)))

    def _poll_once(self) -> C1001Reading | None:
        """One round of basics.ino's loop(). No presence reply = no reading this round."""
        presence = self._request(PRESENCE, QUERY, POLL_TIMEOUT_S)
        if presence is None:
            return None
        values = [self._request(w, QUERY, POLL_TIMEOUT_S) for w in (MOVEMENT, BREATH, HEART)]
        movement, breath, heart = (f.value() if f else None for f in values)
        present = presence.value() == 1
        if not present:
            # the sensor can keep answering with its last breath/heart after it stopped measuring (seen in
            # reporting mode 1): with nobody there, there is no reading
            breath = heart = None
        return C1001Reading(t=self._clock(), presence=present, moving=decode_moving(movement),
                            breath_rpm=decode_vital(breath), heart_bpm=decode_vital(heart))

    def _request(self, word: tuple[int, int], data: bytes, timeout_s: float) -> C1001Frame | None:
        """getData(): send, wait for a reply with the same ctrl and cmd, resend every 1 s, give up after
        timeout_s. Other frames that arrive meanwhile are counted, not treated as errors."""
        frame = build_frame(word[0], word[1], data)
        start = time.monotonic()
        sent = None
        while not self._stop.is_set():
            now = time.monotonic()
            if now - start > timeout_s:
                self.timeouts += 1
                return None
            if sent is None or now - sent >= RESEND_S:
                self._write(frame)
                sent = now
            for f in self._read():
                if f.word == word:
                    return f
                self.unsolicited[f.word] += 1
        return None

    def _read(self) -> list[C1001Frame]:
        ser = self._ser
        if ser is None:
            raise _Lost("port closed")
        data = ser.read(ser.in_waiting or 1)
        if not data:
            return []
        t = self._clock()
        frames = []
        for f, raw in self.parser.feed_with_raw(data):
            if self.on_frame is not None:
                self.on_frame(f, raw, t)
            frames.append(f)
        return frames

    def _write(self, data: bytes) -> None:
        ser = self._ser
        if ser is None:
            raise _Lost("port closed")
        ser.write(data)

    def _wait(self, seconds: float) -> None:
        """Sleep that keeps draining the port (so nothing piles up) and returns early on stop()."""
        end = time.monotonic() + seconds
        while not self._stop.is_set() and time.monotonic() < end:
            for f in self._read():
                self.unsolicited[f.word] += 1

    def _close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
