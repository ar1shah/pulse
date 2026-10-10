"""DFRobot C1001 (SEN0623) 60 GHz mmWave radar driver.

Protocol, frame parser, command builders, and serial reader ported from the official DFRobot Arduino library
(DFRobot_HumanDetection on GitHub: https://github.com/DFRobot/DFRobot_HumanDetection).

Protocol notes and confirmed command words: docs/hardware.md.
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from ..state import BREATH_RANGE, HEART_RANGE, SensorStatus

log = logging.getLogger("pulse.c1001")

# ---- wire protocol constants ---------------------------------------------------------------------------------
# Confirmed from DFRobot_HumanDetection.h and DFRobot_HumanDetection.cpp
FRAME_HEADER = b"\x53\x59"      # 'SY'
FRAME_TAIL = b"\x54\x43"        # 'TC'
MAX_PAYLOAD_LEN = 64

DEFAULT_BAUD = 115200
DEFAULT_PORT = "/dev/ttyAMA3"
STALE_S = 1.0                   # no frame for this long = stale
RETRY_S = 2.0                   # reconnect interval
READ_TIMEOUT_S = 0.1
POLL_INTERVAL_S = 0.5           # query interval in reader loop
INIT_GAP_S = 0.1

# ---- command / control words ---------------------------------------------------------------------------------
# Work mode configuration (DFRobot_HumanDetection.cpp:44, 46)
CMD_SET_WORK_MODE = (0x02, 0x08)
CMD_QUERY_WORK_MODE = (0x02, 0xA8)
CMD_RESET_SENSOR = (0x01, 0x02)

# Queries (DFRobot_HumanDetection.cpp:143, 149, 176, 198, 324)
CMD_QUERY_SLEEP_COMPOSITE = (0x84, 0x8D)
CMD_QUERY_PRESENCE = (0x80, 0x81)
CMD_QUERY_MOVEMENT = (0x80, 0x82)
CMD_QUERY_BREATHE_VALUE = (0x81, 0x82)
CMD_QUERY_HEART_RATE = (0x85, 0x82)

# Work modes (DFRobot_HumanDetection.h:100-101)
MODE_FALLING = 0x01
MODE_SLEEP = 0x02


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
    """One decoded protocol frame from the C1001."""
    t: float
    con: int
    cmd: int
    data: bytes


# ---- sanity helpers -------------------------------------------------------------------------------------------

def sanitize_breath(val: int | None) -> int | None:
    """Rule 9: breath outside 10 to 25 rpm or zero becomes None."""
    if val is not None and BREATH_RANGE[0] <= val <= BREATH_RANGE[1]:
        return val
    return None


def sanitize_heart(val: int | None) -> int | None:
    """Rule 9: heart rate outside 60 to 100 bpm or zero becomes None."""
    if val is not None and HEART_RANGE[0] <= val <= HEART_RANGE[1]:
        return val
    return None


# ---- frame building -------------------------------------------------------------------------------------------

def build_frame(con: int, cmd: int, data: bytes = b"\x0f") -> bytes:
    """Build a C1001 frame: 53 59 | con | cmd | len (BE16) | data | checksum | 54 43.
    Checksum is sum of all preceding bytes modulo 256 (DFRobot_HumanDetection.cpp:799, 929)."""
    length = len(data)
    frame = bytearray()
    frame.extend(FRAME_HEADER)
    frame.append(con)
    frame.append(cmd)
    frame.append((length >> 8) & 0xFF)
    frame.append(length & 0xFF)
    frame.extend(data)
    checksum = sum(frame) & 0xFF
    frame.append(checksum)
    frame.extend(FRAME_TAIL)
    return bytes(frame)


def cmd_set_work_mode(mode: int = MODE_SLEEP) -> bytes:
    """Switch work mode (0x02 = sleep/vitals mode, 0x01 = fall detection)."""
    return build_frame(CMD_SET_WORK_MODE[0], CMD_SET_WORK_MODE[1], bytes([mode]))


def cmd_query_work_mode() -> bytes:
    """Query current work mode."""
    return build_frame(CMD_QUERY_WORK_MODE[0], CMD_QUERY_WORK_MODE[1], b"\x0f")


def cmd_query_sleep_composite() -> bytes:
    """Query sleep composite vitals (presence, respiration, heartbeat, movement)."""
    return build_frame(CMD_QUERY_SLEEP_COMPOSITE[0], CMD_QUERY_SLEEP_COMPOSITE[1], b"\x0f")


def cmd_query_presence() -> bytes:
    return build_frame(CMD_QUERY_PRESENCE[0], CMD_QUERY_PRESENCE[1], b"\x0f")


def cmd_query_movement() -> bytes:
    return build_frame(CMD_QUERY_MOVEMENT[0], CMD_QUERY_MOVEMENT[1], b"\x0f")


def cmd_query_breath() -> bytes:
    return build_frame(CMD_QUERY_BREATHE_VALUE[0], CMD_QUERY_BREATHE_VALUE[1], b"\x0f")


def cmd_query_heart() -> bytes:
    return build_frame(CMD_QUERY_HEART_RATE[0], CMD_QUERY_HEART_RATE[1], b"\x0f")


# ---- frame decoding -------------------------------------------------------------------------------------------

def decode_reading(frame: C1001Frame, current: C1001Reading | None = None) -> C1001Reading | None:
    """Convert a decoded frame to a C1001Reading with contract sanity filtering."""
    # Sleep composite response (0x84, 0x8D) - DFRobot_HumanDetection.cpp:310-328
    if (frame.con, frame.cmd) == CMD_QUERY_SLEEP_COMPOSITE and len(frame.data) >= 8:
        presence = bool(frame.data[0])
        if not presence:
            return C1001Reading(t=frame.t, presence=False, moving=None, breath_rpm=None, heart_bpm=None)
        # payload: [presence, sleepState, avgRespiration, avgHeartbeat, turnover, largeBodyMove, minorBodyMove, apnea]
        large_move = frame.data[5]
        minor_move = frame.data[6]
        moving = bool(large_move > 0 or minor_move > 0)
        breath = sanitize_breath(frame.data[2])
        heart = sanitize_heart(frame.data[3])
        return C1001Reading(t=frame.t, presence=True, moving=moving, breath_rpm=breath, heart_bpm=heart)

    # Human presence query (0x80, 0x81)
    if (frame.con, frame.cmd) == CMD_QUERY_PRESENCE and len(frame.data) >= 1:
        presence = bool(frame.data[0])
        moving = current.moving if (current and presence) else None
        breath = current.breath_rpm if (current and presence) else None
        heart = current.heart_bpm if (current and presence) else None
        return C1001Reading(t=frame.t, presence=presence, moving=moving, breath_rpm=breath, heart_bpm=heart)

    # Human movement query (0x80, 0x82): 0=none, 1=still, 2=moving
    if (frame.con, frame.cmd) == CMD_QUERY_MOVEMENT and len(frame.data) >= 1:
        mov_val = frame.data[0]
        moving = True if mov_val == 2 else (False if mov_val == 1 else None)
        presence = current.presence if current else (mov_val in (1, 2))
        return C1001Reading(t=frame.t, presence=presence, moving=moving,
                            breath_rpm=current.breath_rpm if (current and presence) else None,
                            heart_bpm=current.heart_bpm if (current and presence) else None)

    # Respiration value query (0x81, 0x82)
    if (frame.con, frame.cmd) == CMD_QUERY_BREATHE_VALUE and len(frame.data) >= 1:
        breath = sanitize_breath(frame.data[0])
        presence = current.presence if current else (breath is not None)
        return C1001Reading(t=frame.t, presence=presence,
                            moving=current.moving if (current and presence) else None,
                            breath_rpm=breath if presence else None,
                            heart_bpm=current.heart_bpm if (current and presence) else None)

    # Heart rate query (0x85, 0x82)
    if (frame.con, frame.cmd) == CMD_QUERY_HEART_RATE and len(frame.data) >= 1:
        heart = sanitize_heart(frame.data[0])
        presence = current.presence if current else (heart is not None)
        return C1001Reading(t=frame.t, presence=presence,
                            moving=current.moving if (current and presence) else None,
                            breath_rpm=current.breath_rpm if (current and presence) else None,
                            heart_bpm=heart if presence else None)

    return None


# ---- incremental parser ---------------------------------------------------------------------------------------

class C1001Parser:
    """Incremental byte-stream parser for C1001 frames.
    Feed arbitrary chunks; get back valid frames. Resyncs on 0x53 0x59 header, checks length,
    validates 0x54 0x43 tail and checksum. Never raises on bad input."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.good = 0
        self.bad = 0
        self.skipped_bytes = 0

    def feed(self, data: bytes, t: float) -> list[C1001Frame]:
        return [f for f, _ in self.feed_with_raw(data, t)]

    def feed_with_raw(self, data: bytes, t: float) -> list[tuple[C1001Frame, bytes]]:
        buf = self._buf
        buf += data
        out: list[tuple[C1001Frame, bytes]] = []

        while True:
            start = buf.find(FRAME_HEADER)
            if start < 0:
                keep = len(FRAME_HEADER) - 1
                if len(buf) > keep:
                    self.skipped_bytes += len(buf) - keep
                    del buf[:-keep]
                break

            if start > 0:
                self.skipped_bytes += start
                del buf[:start]

            if len(buf) < 6:
                break

            payload_len = (buf[4] << 8) | buf[5]
            if payload_len > MAX_PAYLOAD_LEN:
                self.bad += 1
                del buf[:1]
                continue

            total_len = 9 + payload_len
            if len(buf) < total_len:
                break

            # Check tail
            if buf[total_len - 2:total_len] != FRAME_TAIL:
                self.bad += 1
                del buf[:1]
                continue

            # Verify checksum: sum of bytes 0..(6+payload_len-1) & 0xFF
            expected_sum = sum(buf[:6 + payload_len]) & 0xFF
            actual_sum = buf[6 + payload_len]
            if actual_sum != expected_sum:
                self.bad += 1
                del buf[:1]
                continue

            # Frame is valid
            raw = bytes(buf[:total_len])
            con = buf[2]
            cmd = buf[3]
            payload = bytes(buf[6:6 + payload_len])
            out.append((C1001Frame(t=t, con=con, cmd=cmd, data=payload), raw))
            self.good += 1
            del buf[:total_len]

        return out


# ---- serial reader --------------------------------------------------------------------------------------------

class SerialLike(Protocol):
    in_waiting: int

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


def open_serial(port: str, baud: int = DEFAULT_BAUD) -> SerialLike:
    import serial  # pyserial; imported here so sim mode never requires it

    return serial.Serial(port, baud, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                         stopbits=serial.STOPBITS_ONE, timeout=READ_TIMEOUT_S)


class C1001Reader:
    """Reads C1001 in a daemon thread, sends init mode commands, and polls composite vitals.
    `latest(now)` never raises: (C1001Reading | None, "ok" | "warming" | "stale" | "offline")."""

    def __init__(self, port: str, baud: int = DEFAULT_BAUD,
                 opener: Callable[[str, int], SerialLike] = open_serial,
                 clock: Callable[[], float] = time.time,
                 retry_s: float = RETRY_S,
                 poll_interval_s: float = POLL_INTERVAL_S,
                 init_gap_s: float = INIT_GAP_S) -> None:
        self.port = port
        self.baud = baud
        self.parser = C1001Parser()
        self._opener = opener
        self._clock = clock
        self._retry_s = retry_s
        self._poll_interval_s = poll_interval_s
        self._init_gap_s = init_gap_s

        self._latest: C1001Reading | None = None
        self._last_frame_t: float | None = None
        self._connected = False
        self._connected_at: float = 0.0
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
        reading = self._latest
        if not self._connected:
            return reading, "offline"
        if self._last_frame_t is None:
            if now - self._connected_at > STALE_S:
                return reading, "stale"
            return reading, "warming"
        if now - self._last_frame_t > STALE_S:
            return reading, "stale"
        if reading is None or (reading.breath_rpm is None and reading.heart_bpm is None):
            return reading, "warming"
        return reading, "ok"

    # ---- worker thread ----

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                self._ser = self._opener(self.port, self.baud)
            except Exception as e:
                log.log(logging.WARNING if failures == 0 else logging.DEBUG,
                        "C1001 %s not available (%s); retrying every %.0f s", self.port, e, self._retry_s)
                failures += 1
                self._stop.wait(self._retry_s)
                continue

            failures = 0
            self._connected = True
            self._connected_at = self._clock()
            log.info("C1001 connected on %s at %d baud", self.port, self.baud)
            try:
                self._send_init()
                self._poll_loop()
            except Exception as e:
                if not self._stop.is_set():
                    log.warning("C1001 %s read failed (%s); reconnecting", self.port, e)
            finally:
                self._connected = False
                self._close()
            self._stop.wait(self._retry_s)

    def _send_init(self) -> None:
        if self._ser is None:
            return
        mode_cmd = cmd_set_work_mode(MODE_SLEEP)
        self._ser.write(mode_cmd)
        log.info("C1001 sleep work mode requested")
        self._stop.wait(self._init_gap_s)

    def _poll_loop(self) -> None:
        next_poll = 0.0
        while not self._stop.is_set():
            ser = self._ser
            if ser is None:
                return
            now = self._clock()
            if now >= next_poll:
                ser.write(cmd_query_sleep_composite())
                next_poll = now + self._poll_interval_s

            n = getattr(ser, "in_waiting", 0)
            data = ser.read(n if n > 0 else 1)
            if data:
                now_rx = self._clock()
                frames = self.parser.feed(data, now_rx)
                for f in frames:
                    self._last_frame_t = f.t
                    reading = decode_reading(f, self._latest)
                    if reading is not None:
                        self._latest = reading
            else:
                self._stop.wait(0.02)

    def _close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
