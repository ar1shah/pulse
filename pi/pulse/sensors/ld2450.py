"""HLK-LD2450 frame parser, command frames and serial reader.

The parser is pure (bytes in, frames out) so it runs in tests and replay without hardware. The reader is a thin
pyserial loop around it in a daemon thread. Protocol notes: docs/hardware.md, "LD2450 protocol".
"""
import logging
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Protocol

from ..state import SensorStatus

log = logging.getLogger("pulse.ld2450")

# ---- sign conventions: flip these after the live test (docs/BRINGUP.md Phase 4) -----------------------------
# Decoded raw values are multiplied by these to reach the contract: x negative = holder's LEFT,
# speed negative = APPROACHING. Set to -1 if the live test shows the opposite.
X_SIGN = 1
SPEED_SIGN = 1

# ---- data frames ---------------------------------------------------------------------------------------------
DATA_HEADER = b"\xaa\xff\x03\x00"
DATA_TAIL = b"\x55\xcc"
FRAME_LEN = 30                  # header 4 + 3 targets x 8 + tail 2
TARGET_LEN = 8
EMPTY_SLOT = bytes(TARGET_LEN)

# ---- command frames (verify against datasheet) ---------------------------------------------------------------
CMD_HEADER = b"\xfd\xfc\xfb\xfa"
CMD_TAIL = b"\x04\x03\x02\x01"
CMD_ENABLE_CONFIG = 0x00FF      # value 0x0001
CMD_END_CONFIG = 0x00FE
CMD_SINGLE_TARGET = 0x0080
CMD_MULTI_TARGET = 0x0090
ACK_BIT = 0x0100                # an ACK echoes the command word with this bit set
MAX_CMD_BODY = 64               # longer "length" fields are corruption, not a real ACK

# ---- reader ---------------------------------------------------------------------------------------------------
DEFAULT_BAUD = 256000
STALE_S = 1.0                   # no frame for this long = stale
RETRY_S = 2.0                   # reconnect interval
READ_TIMEOUT_S = 0.1
CMD_GAP_S = 0.1                 # pause between config commands


@dataclass(frozen=True)
class Ld2450Target:
    """One radar detection, already in contract conventions: x negative = holder's left,
    y straight out (>= 0), speed negative = approaching. Units: mm and cm/s."""
    x_mm: int
    y_mm: int
    speed_cms: int
    resolution_mm: int = 0


@dataclass(frozen=True)
class Ld2450Frame:
    """One decoded frame: up to 3 targets (empty slots skipped), stamped with its arrival time.
    `slots` keeps the sensor's slot order with None for empty ones (real frames only; for LOG_RAW)."""
    t: float
    targets: list[Ld2450Target] = field(default_factory=list)
    slots: tuple[Ld2450Target | None, ...] = ()


@dataclass(frozen=True)
class Ld2450Ack:
    """Reply to a command frame. `command` is the word that was sent (ACK bit cleared)."""
    command: int
    ok: bool
    data: bytes = b""


# ---- decoding -------------------------------------------------------------------------------------------------

def decode_signed(raw: int) -> int:
    """LD2450 sign bit: top bit SET = positive, magnitude = low 15 bits."""
    v = raw & 0x7FFF
    return v if raw & 0x8000 else -v


def decode_target(chunk: bytes) -> Ld2450Target | None:
    """One 8-byte target slot to a contract-convention target, or None for an empty slot."""
    if chunk == EMPTY_SLOT:
        return None
    raw_x, raw_y, raw_speed, res = struct.unpack("<4H", chunk)
    x, y = decode_signed(raw_x), decode_signed(raw_y)
    if x == 0 and y == 0:
        return None             # no position: not a person
    return Ld2450Target(x_mm=X_SIGN * x, y_mm=y, speed_cms=SPEED_SIGN * decode_signed(raw_speed), resolution_mm=res)


def decode_frame(frame: bytes, t: float) -> Ld2450Frame:
    """A complete, already validated 30-byte data frame."""
    slots = tuple(decode_target(frame[len(DATA_HEADER) + i * TARGET_LEN:][:TARGET_LEN]) for i in range(3))
    return Ld2450Frame(t=t, targets=[s for s in slots if s is not None], slots=slots)


# ---- commands (verify against datasheet) ---------------------------------------------------------------------

def command_frame(command: int, value: bytes = b"") -> bytes:
    """FD FC FB FA | length (LE16, of command word + value) | command word (LE16) | value | 04 03 02 01."""
    body = struct.pack("<H", command) + value
    return CMD_HEADER + struct.pack("<H", len(body)) + body + CMD_TAIL


def cmd_enable_config() -> bytes:
    return command_frame(CMD_ENABLE_CONFIG, b"\x01\x00")


def cmd_end_config() -> bytes:
    return command_frame(CMD_END_CONFIG)


def cmd_multi_target() -> bytes:
    return command_frame(CMD_MULTI_TARGET)


def cmd_single_target() -> bytes:
    return command_frame(CMD_SINGLE_TARGET)


def mode_commands(multi: bool = True) -> list[bytes]:
    """The sequence that switches tracking mode: enable config, mode, end config."""
    return [cmd_enable_config(), cmd_multi_target() if multi else cmd_single_target(), cmd_end_config()]


def parse_ack(frame: bytes) -> Ld2450Ack | None:
    """A complete command-reply frame to an Ld2450Ack, or None if it isn't a well-formed ACK.
    Layout (verify against datasheet): header, LE16 length, LE16 command|0x0100, LE16 status (0 = ok), data, tail."""
    if len(frame) < 14 or not frame.startswith(CMD_HEADER) or not frame.endswith(CMD_TAIL):
        return None
    (n,) = struct.unpack_from("<H", frame, 4)
    if n < 4 or len(frame) != 4 + 2 + n + 4:
        return None
    cmd, status = struct.unpack_from("<2H", frame, 6)
    if not cmd & ACK_BIT:
        return None
    return Ld2450Ack(command=cmd & ~ACK_BIT, ok=status == 0, data=bytes(frame[10:6 + n]))


# ---- incremental parser ---------------------------------------------------------------------------------------

class Ld2450Parser:
    """Feed arbitrary byte chunks; get back complete frames. Resyncs on the data header and checks the tail.
    Command ACKs in the same stream are collected in `acks`. Never raises on bad input."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.good = 0               # data frames decoded
        self.bad = 0                # data frames with a bad tail (or a false header)
        self.skipped_bytes = 0      # garbage between frames
        self.acks: deque[Ld2450Ack] = deque(maxlen=16)
        self.ack_count = 0

    def feed(self, data: bytes, t: float) -> list[Ld2450Frame]:
        return [f for f, _ in self.feed_with_raw(data, t)]

    def feed_with_raw(self, data: bytes, t: float) -> list[tuple[Ld2450Frame, bytes]]:
        """Like feed, but also returns each frame's 30 raw bytes (for recordings)."""
        buf = self._buf
        buf += data
        out: list[tuple[Ld2450Frame, bytes]] = []
        while True:
            start = _first_header(buf)
            if start < 0:
                keep = len(DATA_HEADER) - 1     # the tail of buf could be the start of a header
                if len(buf) > keep:
                    self.skipped_bytes += len(buf) - keep
                    del buf[:-keep]
                break
            if start:
                self.skipped_bytes += start
                del buf[:start]
            if buf.startswith(DATA_HEADER):
                if len(buf) < FRAME_LEN:
                    break
                if buf[FRAME_LEN - 2:FRAME_LEN] == DATA_TAIL:
                    raw = bytes(buf[:FRAME_LEN])
                    out.append((decode_frame(raw, t), raw))
                    self.good += 1
                    del buf[:FRAME_LEN]
                else:
                    self.bad += 1
                    del buf[:1]                 # resync: look for the next header
            else:                               # command ACK
                if len(buf) < 6:
                    break
                (n,) = struct.unpack_from("<H", buf, 4)
                total = 4 + 2 + n + 4
                if n > MAX_CMD_BODY:
                    del buf[:1]
                    continue
                if len(buf) < total:
                    break
                ack = parse_ack(bytes(buf[:total]))
                if ack is None:
                    del buf[:1]
                    continue
                self.acks.append(ack)
                self.ack_count += 1
                del buf[:total]
        return out


def _first_header(buf: bytearray) -> int:
    hits = [i for i in (buf.find(DATA_HEADER), buf.find(CMD_HEADER)) if i >= 0]
    return min(hits) if hits else -1


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


class Ld2450Reader:
    """Reads the LD2450 in a daemon thread and keeps the latest frame. Reconnects every 2 s.
    `latest(now)` never raises: (frame | None, "ok" | "stale" | "offline")."""

    def __init__(self, port: str, baud: int = DEFAULT_BAUD, multi_target: bool = True,
                 opener: Callable[[str, int], SerialLike] = open_serial,
                 clock: Callable[[], float] = time.time, retry_s: float = RETRY_S) -> None:
        self.port = port
        self.baud = baud
        self.multi_target = multi_target
        self.parser = Ld2450Parser()
        self._opener = opener
        self._clock = clock
        self._retry_s = retry_s
        self._latest: Ld2450Frame | None = None
        self._connected = False
        self._ser: SerialLike | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ld2450", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def latest(self, now: float) -> tuple[Ld2450Frame | None, SensorStatus]:
        frame = self._latest
        if not self._connected:
            return frame, "offline"
        if frame is None or now - frame.t > STALE_S:
            return frame, "stale"
        return frame, "ok"

    # ---- thread ----

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                self._ser = self._opener(self.port, self.baud)
            except Exception as e:
                # first failure is a warning, the retries every 2 s are not worth a log line each
                log.log(logging.WARNING if failures == 0 else logging.DEBUG,
                        "LD2450 %s not available (%s); retrying every %.0f s", self.port, e, self._retry_s)
                failures += 1
                self._stop.wait(self._retry_s)
                continue
            failures = 0
            self._connected = True
            log.info("LD2450 connected on %s at %d baud", self.port, self.baud)
            try:
                if self.multi_target:
                    self._send_mode()
                self._read_loop()
            except Exception as e:
                if not self._stop.is_set():
                    log.warning("LD2450 %s read failed (%s); reconnecting", self.port, e)
            finally:
                self._connected = False
                self._close()
            self._stop.wait(self._retry_s)

    def _send_mode(self) -> None:
        for cmd in mode_commands(multi=True):
            if self._ser is None:
                return
            self._ser.write(cmd)
            self._stop.wait(CMD_GAP_S)
        log.info("LD2450 multi-target mode requested")

    def _read_loop(self) -> None:
        acks_seen = self.parser.ack_count
        while not self._stop.is_set():
            ser = self._ser
            if ser is None:
                return
            data = ser.read(ser.in_waiting or 1)
            if not data:
                continue
            frames = self.parser.feed(data, self._clock())
            if frames:
                self._latest = frames[-1]
            if len(self.parser.acks) != acks_seen:
                acks_seen = self.parser.ack_count
                ack = self.parser.acks[-1]
                log.info("LD2450 ack cmd=0x%04X ok=%s", ack.command, ack.ok)

    def _close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
