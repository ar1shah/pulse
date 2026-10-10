"""C1001 frame builder, parser, command definitions, reader and LiveSource integration tests."""
import threading
import time

import pytest

from pulse.sensors import c1001
from pulse.sensors.c1001 import (
    CMD_QUERY_BREATHE_VALUE,
    CMD_QUERY_HEART_RATE,
    CMD_QUERY_MOVEMENT,
    CMD_QUERY_PRESENCE,
    CMD_QUERY_SLEEP_COMPOSITE,
    CMD_SET_WORK_MODE,
    C1001Frame,
    C1001Parser,
    C1001Reader,
    C1001Reading,
    build_frame,
    cmd_query_sleep_composite,
    cmd_set_work_mode,
    decode_reading,
    sanitize_breath,
    sanitize_heart,
)
from pulse.sources import LiveSource


def make_composite_payload(presence: int = 1, sleep_state: int = 2,
                           breath: int = 16, heart: int = 72,
                           turnover: int = 0, large_move: int = 0,
                           minor_move: int = 0, apnea: int = 0) -> bytes:
    """8-byte payload matching sSleepComposite from DFRobot_HumanDetection.h:60-71."""
    return bytes([presence, sleep_state, breath, heart, turnover, large_move, minor_move, apnea])


# ---- command builder & checksum tests -------------------------------------------------------------------------

def test_cmd_set_work_mode_bytes():
    # Exactly matching DFRobot_HumanDetection.cpp:44 cmdBuf with mode = 0x02:
    # 53 59 02 08 00 01 02 B9 54 43
    frame = cmd_set_work_mode(0x02)
    assert frame == bytes.fromhex("53 59 02 08 00 01 02 b9 54 43")
    assert frame[:2] == c1001.FRAME_HEADER
    assert frame[-2:] == c1001.FRAME_TAIL
    assert frame[7] == (sum(frame[:7]) & 0xFF)


def test_cmd_query_sleep_composite_bytes():
    # 53 59 84 8D 00 01 0F CD 54 43
    frame = cmd_query_sleep_composite()
    assert frame == bytes.fromhex("53 59 84 8d 00 01 0f cd 54 43")
    assert frame[7] == (sum(frame[:7]) & 0xFF)


def test_checksum_calculation():
    # Build arbitrary frame and check formula sum(bytes[:6+len]) & 0xFF
    data = b"\x01\x02\x03\x04"
    frame = build_frame(0x84, 0x8D, data)
    assert len(frame) == 9 + len(data)
    assert frame[6 + len(data)] == (sum(frame[:6 + len(data)]) & 0xFF)


# ---- parser tests ---------------------------------------------------------------------------------------------

def test_parse_valid_composite_frame():
    p = C1001Parser()
    payload = make_composite_payload(presence=1, sleep_state=2, breath=16, heart=72)
    raw = build_frame(0x84, 0x8D, payload)
    frames = p.feed(raw, 10.0)
    assert len(frames) == 1
    f = frames[0]
    assert f.t == 10.0
    assert (f.con, f.cmd) == (0x84, 0x8D)
    assert f.data == payload
    assert (p.good, p.bad) == (1, 0)

    reading = decode_reading(f)
    assert reading is not None
    assert reading.t == 10.0
    assert reading.presence is True
    assert reading.moving is False
    assert reading.breath_rpm == 16
    assert reading.heart_bpm == 72


def test_parse_moving_and_still():
    p = C1001Parser()
    # Moving: large_move > 0
    raw_mov = build_frame(0x84, 0x8D, make_composite_payload(presence=1, breath=18, heart=75, large_move=10))
    (f_mov,) = p.feed(raw_mov, 1.0)
    r_mov = decode_reading(f_mov)
    assert r_mov is not None and r_mov.moving is True

    # Still: large_move = 0, minor_move = 0
    raw_still = build_frame(0x84, 0x8D, make_composite_payload(presence=1, breath=18, heart=75, large_move=0, minor_move=0))
    (f_still,) = p.feed(raw_still, 2.0)
    r_still = decode_reading(f_still)
    assert r_still is not None and r_still.moving is False

    # No one present: presence = 0 -> vitals and moving are None
    raw_empty = build_frame(0x84, 0x8D, make_composite_payload(presence=0, breath=18, heart=75))
    (f_empty,) = p.feed(raw_empty, 3.0)
    r_empty = decode_reading(f_empty)
    assert r_empty is not None
    assert r_empty.presence is False
    assert r_empty.moving is None
    assert r_empty.breath_rpm is None
    assert r_empty.heart_bpm is None


def test_sanity_filtering():
    assert sanitize_breath(10) == 10
    assert sanitize_breath(25) == 25
    assert sanitize_breath(9) is None
    assert sanitize_breath(26) is None
    assert sanitize_breath(0) is None
    assert sanitize_breath(None) is None

    assert sanitize_heart(60) == 60
    assert sanitize_heart(100) == 100
    assert sanitize_heart(59) is None
    assert sanitize_heart(101) is None
    assert sanitize_heart(0) is None
    assert sanitize_heart(None) is None

    # Frame with out-of-range vitals
    f = C1001Frame(t=1.0, con=0x84, cmd=0x8D,
                   data=make_composite_payload(presence=1, breath=35, heart=45))
    r = decode_reading(f)
    assert r is not None
    assert r.presence is True
    assert r.breath_rpm is None
    assert r.heart_bpm is None


def test_checksum_failure():
    p = C1001Parser()
    valid = build_frame(0x84, 0x8D, make_composite_payload(presence=1))
    corrupt = bytearray(valid)
    corrupt[6 + 8] = (corrupt[6 + 8] + 1) & 0xFF  # alter checksum byte
    frames = p.feed(bytes(corrupt), 1.0)
    assert len(frames) == 0
    assert (p.good, p.bad) == (0, 1)

    # Subsequent valid frame parses cleanly
    frames = p.feed(valid, 2.0)
    assert len(frames) == 1
    assert (p.good, p.bad) == (1, 1)


def test_bad_tail():
    p = C1001Parser()
    valid = build_frame(0x84, 0x8D, make_composite_payload(presence=1))
    corrupt = bytearray(valid)
    corrupt[-1] = 0x00  # corrupt tail 'TC'
    frames = p.feed(bytes(corrupt), 1.0)
    assert len(frames) == 0
    assert (p.good, p.bad) == (0, 1)


def test_frame_split_across_reads():
    p = C1001Parser()
    raw = build_frame(0x84, 0x8D, make_composite_payload(presence=1, breath=15, heart=70))
    # Feed byte by byte
    got = []
    for b in raw:
        got.extend(p.feed(bytes([b]), 5.0))
    assert len(got) == 1
    assert got[0].t == 5.0
    assert (p.good, p.bad) == (1, 0)

    # Feed split in two chunks
    got2 = p.feed(raw[:5], 6.0) + p.feed(raw[5:], 7.0)
    assert len(got2) == 1
    assert got2[0].t == 7.0
    assert p.good == 2


def test_garbage_before_and_between_frames():
    p = C1001Parser()
    garbage = b"\x00\xff\x53\x12\xaa\xbb"  # includes a false 0x53 start
    valid = build_frame(0x84, 0x8D, make_composite_payload(presence=1, breath=20, heart=80))
    frames = p.feed(garbage + valid, 1.0)
    assert len(frames) == 1
    assert p.good == 1
    assert p.skipped_bytes == len(garbage)


def test_multiple_frames_in_one_chunk():
    p = C1001Parser()
    f1 = build_frame(0x84, 0x8D, make_composite_payload(presence=1, breath=14, heart=68))
    f2 = build_frame(0x84, 0x8D, make_composite_payload(presence=1, breath=18, heart=76))
    frames = p.feed(f1 + f2, 1.0)
    assert len(frames) == 2
    assert p.good == 2
    assert p.bad == 0


def test_discrete_query_frames():
    # Presence (0x80, 0x81)
    f_pres = C1001Frame(t=1.0, con=0x80, cmd=0x81, data=b"\x01")
    r1 = decode_reading(f_pres)
    assert r1 is not None and r1.presence is True

    # Movement (0x80, 0x82): 2 = moving
    f_mov = C1001Frame(t=2.0, con=0x80, cmd=0x82, data=b"\x02")
    r2 = decode_reading(f_mov, current=r1)
    assert r2 is not None and r2.presence is True and r2.moving is True

    # Breath (0x81, 0x82)
    f_br = C1001Frame(t=3.0, con=0x81, cmd=0x82, data=b"\x12")  # 18 rpm
    r3 = decode_reading(f_br, current=r2)
    assert r3 is not None and r3.breath_rpm == 18

    # Heart (0x85, 0x82)
    f_hr = C1001Frame(t=4.0, con=0x85, cmd=0x82, data=b"\x4b")  # 75 bpm
    r4 = decode_reading(f_hr, current=r3)
    assert r4 is not None and r4.heart_bpm == 75 and r4.breath_rpm == 18 and r4.moving is True


# ---- fake serial & reader tests -------------------------------------------------------------------------------

class FakeSerial:
    def __init__(self, incoming: bytes = b"", fail_open: bool = False, fail_read: bool = False) -> None:
        self.buf = bytearray(incoming)
        self.written: list[bytes] = []
        self.closed = False
        self.fail_open = fail_open
        self.fail_read = fail_read

    @property
    def in_waiting(self) -> int:
        return len(self.buf)

    def read(self, size: int = 1) -> bytes:
        if self.fail_read:
            raise OSError("simulated read error")
        data = bytes(self.buf[:size])
        del self.buf[:size]
        return data

    def write(self, data: bytes) -> int:
        self.written.append(bytes(data))
        return len(data)

    def close(self) -> None:
        self.closed = True


def wait_for(pred, timeout=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return
        time.sleep(0.005)
    raise TimeoutError("timed out waiting for condition")


def test_reader_offline_when_port_cannot_open():
    def bad_opener(port, baud):
        raise OSError("device not found")

    r = C1001Reader(port="/dev/null", opener=bad_opener, retry_s=0.01)
    r.start()
    try:
        reading, status = r.latest(now=10.0)
        assert reading is None
        assert status == "offline"
    finally:
        r.stop()


def test_reader_warming_then_ok():
    # When connected but no vitals yet, status is 'warming'
    # When vitals frame arrives, status is 'ok'
    valid_frame = build_frame(0x84, 0x8D, make_composite_payload(presence=1, breath=16, heart=72))
    fake = FakeSerial(valid_frame)

    now_ref = [100.0]

    def fake_clock():
        return now_ref[0]

    r = C1001Reader(port="fake", opener=lambda p, b: fake, clock=fake_clock, retry_s=0.01,
                    poll_interval_s=0.02, init_gap_s=0.001)
    r.start()
    try:
        wait_for(lambda: r.latest(100.0)[0] is not None)
        reading, status = r.latest(now=100.0)
        assert reading is not None
        assert reading.breath_rpm == 16
        assert reading.heart_bpm == 72
        assert status == "ok"

        # Now simulate time advancing > STALE_S without new frames
        reading, status = r.latest(now=101.5)
        assert status == "stale"
    finally:
        r.stop()


def test_reader_warming_status():
    # Frame with presence but no vitals yet (e.g. breath=0, heart=0)
    warming_frame = build_frame(0x84, 0x8D, make_composite_payload(presence=1, breath=0, heart=0))
    fake = FakeSerial(warming_frame)

    r = C1001Reader(port="fake", opener=lambda p, b: fake, clock=lambda: 50.0, retry_s=0.01,
                    poll_interval_s=0.02, init_gap_s=0.001)
    r.start()
    try:
        wait_for(lambda: r.latest(50.0)[0] is not None)
        reading, status = r.latest(now=50.0)
        assert reading is not None
        assert reading.presence is True
        assert reading.breath_rpm is None
        assert reading.heart_bpm is None
        assert status == "warming"
    finally:
        r.stop()


def test_reader_reconnects_on_read_failure():
    # First attempt fails during read, second attempt succeeds
    attempts = [0]
    valid_frame = build_frame(0x84, 0x8D, make_composite_payload(presence=1, breath=15, heart=70))

    def alternating_opener(port, baud):
        attempts[0] += 1
        if attempts[0] == 1:
            return FakeSerial(fail_read=True)
        return FakeSerial(valid_frame)

    r = C1001Reader(port="fake", opener=alternating_opener, retry_s=0.01, poll_interval_s=0.02, init_gap_s=0.001)
    r.start()
    try:
        wait_for(lambda: r.latest(time.time())[0] is not None)
        reading, status = r.latest(now=time.time())
        assert reading is not None
        assert reading.breath_rpm == 15
        assert status == "ok"
    finally:
        r.stop()


def test_live_source_imports_c1001_reader():
    # LiveSource with C1001_PORT specified builds and manages C1001Reader
    src = LiveSource(ld2450_port="/dev/null", c1001_port="/dev/null")
    src.start()
    time.sleep(0.02)
    # With non-existent ports, both report offline and never raise
    ld_frame, ld_status = src.ld2450(10.0)
    c1_reading, c1_status = src.c1001(10.0)
    assert ld_status == "offline"
    assert c1_status == "offline"
    src.stop()
