"""LD2450 parser, command frames, reader and LiveSource, all without hardware."""
import struct
import threading
import time

import pytest

from pulse.sensors import c1001, ld2450
from pulse.sensors.ld2450 import Ld2450Parser, Ld2450Reader, Ld2450Target
from pulse.sources import LiveSource, StubSource, make_source

# Example frame from the LD2450 datasheet: one target at x -782 mm, y 1713 mm, speed -16 cm/s, resolution 320 mm.
DATASHEET_FRAME = bytes.fromhex("aaff0300 0e03b186 10004001" + "00" * 16 + "55cc")


def enc(v: int) -> int:
    """Inverse of the LD2450 sign encoding: top bit set = positive."""
    return (0x8000 | v) if v >= 0 else -v


def slot(x: int, y: int, speed: int = 0, res: int = 360) -> bytes:
    return struct.pack("<4H", enc(x), enc(y), enc(speed), res)


def frame_bytes(*slots: bytes) -> bytes:
    body = b"".join(slots) + ld2450.EMPTY_SLOT * (3 - len(slots))
    return ld2450.DATA_HEADER + body + ld2450.DATA_TAIL


# ---- parser ---------------------------------------------------------------------------------------------------

def test_datasheet_frame():
    p = Ld2450Parser()
    frames = p.feed(DATASHEET_FRAME, 5.0)
    assert len(frames) == 1 and frames[0].t == 5.0
    assert frames[0].targets == [Ld2450Target(x_mm=-782, y_mm=1713, speed_cms=-16, resolution_mm=320)]
    assert (p.good, p.bad) == (1, 0)


def test_three_targets_in_slot_order():
    p = Ld2450Parser()
    (f,) = p.feed(frame_bytes(slot(-500, 1000, -20), slot(0, 2500, 0), slot(1200, 3000, 35)), 1.0)
    assert [(t.x_mm, t.y_mm, t.speed_cms) for t in f.targets] == [(-500, 1000, -20), (0, 2500, 0), (1200, 3000, 35)]


def test_negative_and_positive_x():
    p = Ld2450Parser()
    (f,) = p.feed(frame_bytes(slot(-300, 1500), slot(300, 1500)), 1.0)
    assert [t.x_mm for t in f.targets] == [-300, 300]


def test_empty_slots_are_skipped():
    p = Ld2450Parser()
    (f,) = p.feed(frame_bytes(ld2450.EMPTY_SLOT, slot(100, 900), ld2450.EMPTY_SLOT), 1.0)
    assert [(t.x_mm, t.y_mm) for t in f.targets] == [(100, 900)]
    (f,) = p.feed(frame_bytes(), 2.0)
    assert f.targets == []


def test_frame_split_across_reads():
    p = Ld2450Parser()
    data = frame_bytes(slot(-250, 1200, -5))
    got = [f for b in data for f in p.feed(bytes([b]), 1.0)]     # one byte per read
    assert len(got) == 1 and got[0].targets[0].x_mm == -250
    got = p.feed(data[:7], 2.0) + p.feed(data[7:29], 2.0) + p.feed(data[29:], 3.0)
    assert len(got) == 1 and got[0].t == 3.0                      # stamped when it completes
    assert (p.good, p.bad) == (2, 0)


def test_garbage_before_header():
    p = Ld2450Parser()
    junk = b"\x00\x13\xaa\xff\x55\xcc\xaa\xff\x03"                # includes a partial header
    (f,) = p.feed(junk + frame_bytes(slot(10, 800)), 1.0)
    assert f.targets[0].y_mm == 800
    assert p.bad == 0 and p.skipped_bytes == len(junk)


def test_bad_tail_is_counted_and_parser_resyncs():
    p = Ld2450Parser()
    broken = frame_bytes(slot(1, 1000))[:-2] + b"\x00\x00"
    frames = p.feed(broken + frame_bytes(slot(2, 2000)), 1.0)
    assert [f.targets[0].y_mm for f in frames] == [2000]
    assert (p.good, p.bad) == (1, 1)


def test_header_inside_a_truncated_frame():
    p = Ld2450Parser()
    truncated = frame_bytes(slot(1, 1000))[:17]                   # a frame cut off mid-way by a dropped read
    frames = p.feed(truncated + frame_bytes(slot(3, 3000)), 1.0)
    assert [f.targets[0].y_mm for f in frames] == [3000]
    assert p.bad == 1


def test_two_frames_in_one_chunk():
    p = Ld2450Parser()
    frames = p.feed(frame_bytes(slot(-1, 1000)) + frame_bytes(slot(1, 1100)), 4.0)
    assert [f.targets[0].y_mm for f in frames] == [1000, 1100]
    assert p.good == 2


def test_feed_with_raw_returns_the_frame_bytes():
    p = Ld2450Parser()
    ((frame, raw),) = p.feed_with_raw(b"\x01\x02" + DATASHEET_FRAME, 1.0)
    assert raw == DATASHEET_FRAME and frame.targets[0].x_mm == -782


def test_sign_constants_flip_x_and_speed(monkeypatch):
    monkeypatch.setattr(ld2450, "X_SIGN", -1)
    monkeypatch.setattr(ld2450, "SPEED_SIGN", -1)
    (f,) = Ld2450Parser().feed(DATASHEET_FRAME, 1.0)
    assert (f.targets[0].x_mm, f.targets[0].y_mm, f.targets[0].speed_cms) == (782, 1713, 16)


def test_decode_signed():
    assert ld2450.decode_signed(0x8000 | 1713) == 1713
    assert ld2450.decode_signed(782) == -782
    assert ld2450.decode_signed(0x8000) == 0 and ld2450.decode_signed(0) == 0


# ---- commands -------------------------------------------------------------------------------------------------

def test_command_frames_match_the_documented_bytes():
    assert ld2450.cmd_enable_config() == bytes.fromhex("FDFCFBFA 0400 FF00 0100 04030201")
    assert ld2450.cmd_multi_target() == bytes.fromhex("FDFCFBFA 0200 9000 04030201")
    assert ld2450.cmd_single_target() == bytes.fromhex("FDFCFBFA 0200 8000 04030201")
    assert ld2450.cmd_end_config() == bytes.fromhex("FDFCFBFA 0200 FE00 04030201")
    assert ld2450.mode_commands(multi=True)[1] == ld2450.cmd_multi_target()


ENABLE_ACK = bytes.fromhex("FDFCFBFA 0800 FF01 0000 0100 4000 04030201")
MULTI_ACK = bytes.fromhex("FDFCFBFA 0400 9001 0000 04030201")
FAILED_ACK = bytes.fromhex("FDFCFBFA 0400 FE01 0100 04030201")


def test_parse_ack():
    assert ld2450.parse_ack(ENABLE_ACK) == ld2450.Ld2450Ack(command=0x00FF, ok=True, data=bytes.fromhex("01004000"))
    assert ld2450.parse_ack(MULTI_ACK) == ld2450.Ld2450Ack(command=0x0090, ok=True)
    assert ld2450.parse_ack(FAILED_ACK).ok is False
    assert ld2450.parse_ack(ld2450.cmd_multi_target()) is None     # a command, not a reply
    assert ld2450.parse_ack(MULTI_ACK[:-1]) is None


def test_acks_interleaved_with_data_frames():
    p = Ld2450Parser()
    stream = frame_bytes(slot(1, 1000)) + ENABLE_ACK + MULTI_ACK + frame_bytes(slot(2, 2000))
    frames = [f for i in range(0, len(stream), 5) for f in p.feed(stream[i:i + 5], 1.0)]
    assert [f.targets[0].y_mm for f in frames] == [1000, 2000]
    assert [a.command for a in p.acks] == [0x00FF, 0x0090] and p.ack_count == 2
    assert p.bad == 0


# ---- reader ---------------------------------------------------------------------------------------------------

class FakeSerial:
    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self.chunks = list(chunks or [])
        self.written: list[bytes] = []
        self.closed = False
        self.lock = threading.Lock()

    @property
    def in_waiting(self) -> int:
        with self.lock:
            return len(self.chunks[0]) if self.chunks else 0

    def read(self, size: int = 1) -> bytes:
        with self.lock:
            if self.chunks:
                return self.chunks.pop(0)
        time.sleep(0.005)
        return b""

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def close(self) -> None:
        self.closed = True


def wait_for(cond, timeout: float = 2.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


@pytest.fixture(autouse=True)
def fast_commands(monkeypatch):
    monkeypatch.setattr(ld2450, "CMD_GAP_S", 0.0)


def test_reader_ok_then_stale_and_sends_multi_target():
    ser = FakeSerial([frame_bytes(slot(-100, 1000))[:10], frame_bytes(slot(-100, 1000))[10:]])
    clock = [100.0]
    r = Ld2450Reader("/dev/fake", opener=lambda port, baud: ser, clock=lambda: clock[0])
    assert r.latest(100.0) == (None, "offline")
    r.start()
    try:
        wait_for(lambda: r.latest(100.0)[0] is not None)
        frame, status = r.latest(100.5)
        assert status == "ok" and frame.targets[0].x_mm == -100
        assert r.latest(101.2) == (frame, "stale")              # keeps the last frame, fusion ignores repeats
        assert ser.written == ld2450.mode_commands(multi=True)
    finally:
        r.stop()
    assert ser.closed and r.latest(100.5)[1] == "offline"


def test_reader_connected_without_frames_is_stale():
    ser = FakeSerial()
    r = Ld2450Reader("/dev/fake", multi_target=False, opener=lambda port, baud: ser)
    r.start()
    try:
        wait_for(lambda: r.latest(0.0)[1] != "offline")
        assert r.latest(0.0) == (None, "stale")
        assert ser.written == []
    finally:
        r.stop()


def test_reader_offline_and_retries_until_the_port_opens():
    attempts = []
    ser = FakeSerial([DATASHEET_FRAME])

    def opener(port, baud):
        attempts.append((port, baud))
        if len(attempts) < 3:
            raise OSError("no such port")
        return ser

    r = Ld2450Reader("/dev/fake", opener=opener, retry_s=0.01)
    r.start()
    try:
        wait_for(lambda: r.latest(time.time())[1] == "ok")
    finally:
        r.stop()
    assert len(attempts) == 3 and attempts[0] == ("/dev/fake", 256000)


def test_reader_reconnects_after_a_read_error():
    class Breaks(FakeSerial):
        def read(self, size=1):
            raise OSError("device disconnected")

    good = FakeSerial([DATASHEET_FRAME])
    sers = [Breaks(), good]
    r = Ld2450Reader("/dev/fake", opener=lambda p, b: sers.pop(0) if sers else good, retry_s=0.01)
    r.start()
    try:
        wait_for(lambda: r.latest(time.time())[1] == "ok")
    finally:
        r.stop()


# ---- LiveSource -----------------------------------------------------------------------------------------------

def test_make_source_live_and_replay(monkeypatch):
    monkeypatch.setenv("LD2450_PORT", "/dev/ttyTEST")
    src = make_source("live")
    assert isinstance(src, LiveSource) and src.name == "live" and src.ld2450_port == "/dev/ttyTEST"
    assert isinstance(make_source("replay"), StubSource)
    monkeypatch.delenv("LD2450_PORT")
    assert LiveSource().ld2450_port == "/dev/ttyAMA0"


def test_live_source_with_c1001_reader_missing(monkeypatch):
    monkeypatch.delattr(c1001, "C1001Reader", raising=False)
    src = LiveSource(ld2450_port="/nonexistent/ld2450", c1001_port="/nonexistent/c1001")
    src.start()
    try:
        assert src.c1001(time.time()) == (None, "offline")
        assert src.ld2450(time.time()) == (None, "offline")
    finally:
        src.stop()


def test_live_source_c1001_port_unset_is_offline(monkeypatch):
    monkeypatch.delenv("C1001_PORT", raising=False)
    src = LiveSource(ld2450_port="/nonexistent/ld2450")
    src.start()
    try:
        assert src.c1001(time.time()) == (None, "offline")
    finally:
        src.stop()


def test_live_source_uses_c1001_reader_when_present(monkeypatch):
    calls = []

    class FakeC1001Reader:
        def __init__(self, port, baud=115200):
            calls.append(("init", port, baud))

        def start(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")

        def latest(self, now):
            return c1001.C1001Reading(t=now, presence=True, breath_rpm=15), "ok"

    monkeypatch.setattr(c1001, "C1001Reader", FakeC1001Reader, raising=False)
    src = LiveSource(ld2450_port="/nonexistent/ld2450", c1001_port="/dev/ttyAMA3")
    src.start()
    try:
        reading, status = src.c1001(5.0)
        assert status == "ok" and reading.breath_rpm == 15
    finally:
        src.stop()
    assert calls == [("init", "/dev/ttyAMA3", 115200), "start", "stop"]


def test_live_source_survives_a_c1001_reader_that_raises(monkeypatch):
    class Broken:
        def __init__(self, port, baud=115200):
            pass

        def start(self):
            pass

        def stop(self):
            raise RuntimeError("boom")

        def latest(self, now):
            raise RuntimeError("boom")

    monkeypatch.setattr(c1001, "C1001Reader", Broken, raising=False)
    src = LiveSource(ld2450_port="/nonexistent/ld2450", c1001_port="/dev/x")
    src.start()
    assert src.c1001(1.0) == (None, "offline")
    src.stop()
