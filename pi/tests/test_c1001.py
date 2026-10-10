"""C1001 parser, frame builders and reader. Frames are built the way DFRobot_HumanDetection builds them
(getData()'s cmdBuf and sumData()), independently of the code under test."""
import threading
import time

import pytest

from pulse.sensors import c1001
from pulse.sensors.c1001 import C1001Frame, C1001Parser, C1001Reader, C1001Reading


def lib_sum(buf, n):
    """sumData(len, buf): DFRobot_HumanDetection.cpp L929-L938."""
    data = 0
    for i in range(n):
        data += buf[i]
    return data & 0xFF


def lib_frame(con: int, cmd: int, sen: bytes) -> bytes:
    """getData()'s cmdBuf, DFRobot_HumanDetection.cpp L791-L801, byte for byte."""
    n = len(sen)
    buf = bytearray(9 + n)       # the library uses a fixed uint8_t[20]; sized here so long test data fits
    buf[0], buf[1], buf[2], buf[3] = 0x53, 0x59, con, cmd
    buf[4], buf[5] = (n >> 8) & 0xFF, n & 0xFF
    buf[6:6 + n] = sen
    buf[6 + n] = lib_sum(buf, 6 + n)
    buf[7 + n], buf[8 + n] = 0x54, 0x43
    return bytes(buf[:9 + n])


# ---- builders -------------------------------------------------------------------------------------------------

def test_query_frames_match_the_library():
    for word in (c1001.PING, c1001.WORK_MODE_QUERY, c1001.RESET, c1001.PRESENCE, c1001.MOVEMENT,
                 c1001.BREATH, c1001.HEART):
        assert c1001.query(word) == lib_frame(*word, b"\x0f")
    assert c1001.cmd_hp_led(True) == lib_frame(0x01, 0x03, b"\x01")


def test_known_bytes():
    # heart rate query: 53+59+85+82+00+01+0F = 0x1C3 -> C3
    assert c1001.query(c1001.HEART) == bytes.fromhex("5359 8582 0001 0f c3 5443")
    # configWorkMode's hard-coded cmdBuf {53 59 02 08 00 01 mode sum 54 43} with mode = eSleepMode (2)
    assert c1001.cmd_set_work_mode(2) == bytes.fromhex("5359 0208 0001 02 b9 5443")
    assert c1001.cmd_set_work_mode(2) == lib_frame(0x02, 0x08, b"\x02")


def test_decoders():
    assert c1001.decode_moving(2) is True
    assert c1001.decode_moving(1) is False
    assert c1001.decode_moving(0) is None
    assert c1001.decode_moving(None) is None
    assert c1001.decode_vital(16) == 16
    assert c1001.decode_vital(0) is None
    assert c1001.decode_vital(0xFF) is None
    assert c1001.decode_vital(None) is None


# ---- parser ---------------------------------------------------------------------------------------------------

def test_parses_a_reply():
    p = C1001Parser()
    frames = p.feed(lib_frame(0x85, 0x82, bytes([72])))
    assert frames == [C1001Frame(0x85, 0x82, bytes([72]))]
    assert frames[0].value() == 72 and frames[0].word == c1001.HEART
    assert (p.good, p.bad, p.skipped_bytes) == (1, 0, 0)


def test_multi_byte_and_empty_data():
    p = C1001Parser()
    two = lib_frame(0x80, 0x84, b"\x01\x2c")             # 2-byte big-endian value (distance, 300)
    empty = lib_frame(0x01, 0x02, b"")
    frames = p.feed(two + empty)
    assert [f.data for f in frames] == [b"\x01\x2c", b""]
    assert frames[1].value() is None


def test_long_data_uses_big_endian_length():
    data = bytes(range(20))
    frame = lib_frame(0x84, 0x8F, data)
    assert frame[4:6] == b"\x00\x14"
    assert C1001Parser().feed(frame)[0].data == data


def test_bad_checksum_is_counted_and_skipped():
    p = C1001Parser()
    bad = bytearray(lib_frame(0x81, 0x82, bytes([16])))
    bad[7] ^= 0x01
    good = lib_frame(0x81, 0x82, bytes([17]))
    frames = p.feed(bytes(bad) + good)
    assert [f.value() for f in frames] == [17]
    assert p.bad == 1 and p.bad_checksum == 1 and p.good == 1


def test_corrupted_data_byte_fails_checksum():
    p = C1001Parser()
    bad = bytearray(lib_frame(0x85, 0x82, bytes([72])))
    bad[6] = 73
    assert p.feed(bytes(bad)) == []
    assert p.bad_checksum == 1


def test_bad_tail_rejected():
    p = C1001Parser()
    bad = bytearray(lib_frame(0x80, 0x81, b"\x01"))
    bad[-1] = 0x00
    assert p.feed(bytes(bad) + lib_frame(0x80, 0x81, b"\x00")) == [C1001Frame(0x80, 0x81, b"\x00")]
    assert p.bad == 1 and p.bad_checksum == 0


def test_split_chunks_byte_by_byte():
    p = C1001Parser()
    stream = lib_frame(0x80, 0x81, b"\x01") + lib_frame(0x85, 0x82, bytes([66]))
    out = []
    for b in stream:
        out += p.feed(bytes([b]))
    assert [f.word for f in out] == [c1001.PRESENCE, c1001.HEART]
    assert p.skipped_bytes == 0


def test_split_at_every_offset():
    frame = lib_frame(0x81, 0x82, bytes([15]))
    for cut in range(1, len(frame)):
        p = C1001Parser()
        assert p.feed(frame[:cut]) == []
        assert p.feed(frame[cut:]) == [C1001Frame(0x81, 0x82, bytes([15]))], cut


def test_garbage_before_between_and_after():
    p = C1001Parser()
    garbage = b"\x00\xff\x53\x12\x59\x54\x43\xaa"
    stream = garbage + lib_frame(0x80, 0x81, b"\x01") + garbage + lib_frame(0x80, 0x82, b"\x02") + garbage
    frames = p.feed(stream)
    assert [f.word for f in frames] == [c1001.PRESENCE, c1001.MOVEMENT]
    assert p.good == 2 and p.skipped_bytes >= 2 * len(garbage)


def test_lone_header_byte_at_chunk_end_is_kept():
    p = C1001Parser()
    frame = lib_frame(0x80, 0x81, b"\x01")
    assert p.feed(b"\x00\x01" + frame[:1]) == []
    assert p.feed(frame[1:]) == [C1001Frame(0x80, 0x81, b"\x01")]
    assert p.skipped_bytes == 2


def test_impossible_length_does_not_stall():
    p = C1001Parser()
    false_header = b"\x53\x59\x80\x81\xff\xff"        # length 65535: corruption
    frames = p.feed(false_header + lib_frame(0x85, 0x82, bytes([70])))
    assert [f.value() for f in frames] == [70]
    assert p.bad == 1


def test_truncated_frame_then_real_frame():
    # a frame cut short (bytes lost on the wire) swallows the next frame's start; the parser must find it again
    p = C1001Parser()
    cut = lib_frame(0x81, 0x82, bytes([16]))[:-3]
    frames = p.feed(cut + lib_frame(0x85, 0x82, bytes([75])) + lib_frame(0x80, 0x81, b"\x01"))
    assert frames == [C1001Frame(0x85, 0x82, bytes([75])), C1001Frame(0x80, 0x81, b"\x01")]
    assert p.bad == 1


def test_random_garbage_never_raises():
    import random
    rng = random.Random(1)
    p = C1001Parser()
    for _ in range(200):
        p.feed(bytes(rng.randrange(256) for _ in range(rng.randrange(1, 40))))
    assert p.feed(b"\x00" * 80 + lib_frame(0x80, 0x81, b"\x01"))[-1].word == c1001.PRESENCE


def test_feed_with_raw_returns_frame_bytes():
    frame = lib_frame(0x81, 0x82, bytes([18]))
    [(f, raw)] = C1001Parser().feed_with_raw(b"\x00" + frame)
    assert raw == frame and f.value() == 18


# ---- reader ---------------------------------------------------------------------------------------------------

class FakeSensor:
    """A serial port with a C1001 behind it: answers each query frame the way the sensor does (same ctrl and
    cmd, value in data[0]). `values` maps (ctrl, cmd) to the reply data; a missing key means no reply."""

    def __init__(self, values: dict[tuple[int, int], bytes], push: list[bytes] | None = None) -> None:
        self.values = dict(values)
        self.out = bytearray(b"".join(push or []))
        self.written: list[bytes] = []
        self.parser = C1001Parser()
        self.closed = False
        self.lock = threading.Lock()
        self.silent = False

    @property
    def in_waiting(self) -> int:
        with self.lock:
            return len(self.out)

    def read(self, size: int = 1) -> bytes:
        with self.lock:
            if self.out:
                data = bytes(self.out[:size])
                del self.out[:size]
                return data
        time.sleep(0.002)
        return b""

    def write(self, data: bytes) -> int:
        with self.lock:
            self.written.append(bytes(data))
            for f in self.parser.feed(data):
                if f.word == c1001.WORK_MODE_SET:
                    self.values[c1001.WORK_MODE_QUERY] = f.data       # the switch takes effect
                    continue
                if f.word == c1001.HP_LED_SET:
                    self.values[c1001.PING] = f.data
                reply = self.values.get(f.word)
                if reply is not None and not self.silent:
                    self.out += lib_frame(f.ctrl, f.cmd, reply)
        return len(data)

    def close(self) -> None:
        self.closed = True

    def sent_words(self) -> list[tuple[int, int]]:
        return [(w[2], w[3]) for w in self.written]


def sensor(mode=2, led=1, presence=1, movement=1, breath=16, heart=72, **extra) -> FakeSensor:
    values = {c1001.PING: bytes([led]), c1001.WORK_MODE_QUERY: bytes([mode]), c1001.HP_LED_SET: bytes([1]),
              c1001.RESET: b"\x0f", c1001.PRESENCE: bytes([presence]), c1001.MOVEMENT: bytes([movement]),
              c1001.BREATH: bytes([breath]), c1001.HEART: bytes([heart])}
    values.update(extra)
    return FakeSensor(values)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(c1001, "RESEND_S", 0.05)
    monkeypatch.setattr(c1001, "INIT_TIMEOUT_S", 0.3)
    monkeypatch.setattr(c1001, "POLL_TIMEOUT_S", 0.15)
    monkeypatch.setattr(c1001, "MODE_SWITCH_WAIT_S", 0.05)
    monkeypatch.setattr(c1001, "RESET_WAIT_S", 0.05)
    monkeypatch.setattr(c1001, "POLL_S", 0.05)


def wait_for(cond, timeout: float = 3.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def make_reader(fake, **kw) -> C1001Reader:
    return C1001Reader("/dev/fake", opener=lambda port, baud: fake, retry_s=0.05, **kw)


def test_reader_init_already_in_sleep_mode_skips_switch_and_reset():
    fake = sensor()
    r = make_reader(fake)
    r.start()
    try:
        wait_for(lambda: r.latest(time.time())[1] == "ok")
        reading, status = r.latest(time.time())
        assert reading == C1001Reading(t=reading.t, presence=True, moving=False, breath_rpm=16, heart_bpm=72)
        words = fake.sent_words()
        assert words[:2] == [c1001.PING, c1001.WORK_MODE_QUERY]
        assert c1001.WORK_MODE_SET not in words and c1001.RESET not in words and c1001.HP_LED_SET not in words
        assert {c1001.PRESENCE, c1001.MOVEMENT, c1001.BREATH, c1001.HEART} <= set(words)
        assert fake.written[0] == lib_frame(0x01, 0x83, b"\x0f")
    finally:
        r.stop()


def test_reader_switches_to_sleep_mode_sets_led_and_resets():
    fake = sensor(mode=1, led=0)
    r = make_reader(fake)
    r.start()
    try:
        wait_for(lambda: r.latest(time.time())[1] == "ok")
        assert lib_frame(0x02, 0x08, b"\x02") in fake.written      # configWorkMode's raw write
        assert lib_frame(0x01, 0x03, b"\x01") in fake.written      # configLEDLight(eHPLed, 1)
        words = fake.sent_words()
        assert words.index(c1001.WORK_MODE_SET) < words.index(c1001.HP_LED_SET) < words.index(c1001.RESET)
        assert words.index(c1001.RESET) < words.index(c1001.PRESENCE)
        assert fake.values[c1001.WORK_MODE_QUERY] == b"\x02"
    finally:
        r.stop()


def test_reader_mode_switch_that_does_not_take_reconnects():
    fake = sensor(mode=1)
    fake_write = fake.write

    def stubborn(data: bytes) -> int:
        if data[2:4] == b"\x02\x08":
            return len(data)            # sensor ignores the switch
        return fake_write(data)
    fake.write = stubborn
    opens = []
    r = C1001Reader("/dev/fake", opener=lambda p, b: opens.append(1) or fake, retry_s=0.05)
    r.start()
    try:
        wait_for(lambda: len(opens) >= 2)
        assert r.latest(time.time())[1] in ("offline", "warming")
        assert r.latest(time.time())[0] is None
    finally:
        r.stop()


def test_reader_warming_until_vitals():
    fake = sensor(presence=0, movement=0, breath=0, heart=0)
    r = make_reader(fake)
    r.start()
    try:
        wait_for(lambda: r.latest(time.time())[0] is not None)
        reading, status = r.latest(time.time())
        assert status == "warming"
        assert reading.presence is False and reading.moving is None
        assert reading.breath_rpm is None and reading.heart_bpm is None
        fake.values.update({c1001.PRESENCE: b"\x01", c1001.BREATH: bytes([14]), c1001.HEART: bytes([0])})
        wait_for(lambda: r.latest(time.time())[1] == "ok")
        reading, _ = r.latest(time.time())
        assert reading.breath_rpm == 14 and reading.heart_bpm is None      # 0 = no reading, never invented
    finally:
        r.stop()


def test_reader_passes_raw_values_through():
    fake = sensor(movement=2, breath=40, heart=130)     # out of range: fusion sanitizes, not the reader
    r = make_reader(fake)
    r.start()
    try:
        wait_for(lambda: r.latest(time.time())[1] == "ok")
        reading, _ = r.latest(time.time())
        assert reading.moving is True and reading.breath_rpm == 40 and reading.heart_bpm == 130
    finally:
        r.stop()


def test_reader_missing_heart_reply_is_none():
    fake = sensor()
    del fake.values[c1001.HEART]
    r = make_reader(fake)
    r.start()
    try:
        wait_for(lambda: r.latest(time.time())[1] == "ok")
        assert r.latest(time.time())[0].heart_bpm is None
        assert r.timeouts >= 1
    finally:
        r.stop()


def test_reader_offline_when_sensor_never_answers():
    fake = FakeSensor({})
    r = make_reader(fake)
    r.start()
    try:
        time.sleep(0.5)
        assert r.latest(time.time()) == (None, "offline")
        assert r.timeouts >= 1
        assert fake.sent_words()[0] == c1001.PING
    finally:
        r.stop()


def test_reader_stale_then_reconnects_when_sensor_goes_quiet(monkeypatch):
    monkeypatch.setattr(c1001, "STALE_S", 0.2)
    fake = sensor()
    opens = []
    r = C1001Reader("/dev/fake", opener=lambda p, b: opens.append(1) or fake, retry_s=0.05)
    r.start()
    try:
        wait_for(lambda: r.latest(time.time())[1] == "ok")
        fake.silent = True
        wait_for(lambda: r.latest(time.time())[1] == "stale")
        wait_for(lambda: len(opens) >= 2)                  # LOST_AFTER silent rounds -> reconnect
        assert fake.closed
        fake.silent = False
        wait_for(lambda: r.latest(time.time())[1] == "ok")
    finally:
        r.stop()


def test_reader_offline_and_retries_when_port_missing():
    calls = []

    def opener(port, baud):
        calls.append((port, baud))
        raise OSError("no such port")
    r = C1001Reader("/dev/nope", opener=opener, retry_s=0.05)
    r.start()
    try:
        wait_for(lambda: len(calls) >= 3)
        assert r.latest(time.time()) == (None, "offline")
        assert calls[0] == ("/dev/nope", 115200)
    finally:
        r.stop()


def test_reader_survives_garbage_and_counts_unsolicited_frames():
    fake = sensor()
    fake.out += b"\xde\xad" + lib_frame(0x80, 0x01, b"\x01") + b"\x53\x59\x00"    # a pushed report + junk
    r = make_reader(fake)
    r.start()
    try:
        wait_for(lambda: r.latest(time.time())[1] == "ok")
        assert r.unsolicited[(0x80, 0x01)] == 1
        assert r.parser.skipped_bytes >= 2
    finally:
        r.stop()


def test_reader_survives_a_read_error():
    fake = sensor()
    real_read = fake.read
    state = {"n": 0}

    def flaky(size: int = 1) -> bytes:
        state["n"] += 1
        if state["n"] == 5:
            raise OSError("device reports readiness to read but returned no data")
        return real_read(size)
    fake.read = flaky
    r = make_reader(fake)
    r.start()
    try:
        wait_for(lambda: r.latest(time.time())[1] == "ok")
    finally:
        r.stop()


def test_latest_never_raises_before_start():
    r = make_reader(sensor())
    assert r.latest(0.0) == (None, "offline")
    r.stop()                                            # stop without start is fine


def test_live_source_uses_the_reader(monkeypatch):
    from pulse import sources
    fake = sensor()
    opened = []
    monkeypatch.setattr(c1001, "open_serial", lambda port, baud: opened.append((port, baud)) or fake)
    src = sources.LiveSource(ld2450_port="/dev/does-not-exist", c1001_port="/dev/fake-c1001")
    src.start()
    try:
        wait_for(lambda: src.c1001(time.time())[1] == "ok")
        reading, _ = src.c1001(time.time())
        assert reading.heart_bpm == 72
        assert opened[0] == ("/dev/fake-c1001", 115200)
    finally:
        src.stop()
