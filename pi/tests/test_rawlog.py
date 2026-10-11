"""LOG_RAW CSV: raw slots (with empty ones kept in place) next to the shown dots."""
import csv

from pulse.fusion import Fusion
from pulse.rawlog import HEADER, RawLog
from pulse.sensors.ld2450 import Ld2450Parser


def raw_frame(*slots: tuple[int, int, int] | None) -> bytes:
    def enc(v: int) -> bytes:
        return ((abs(v) | 0x8000) if v >= 0 else abs(v)).to_bytes(2, "little")
    body = b"".join(enc(s[0]) + enc(s[1]) + enc(s[2]) + b"\x00\x00" if s else bytes(8) for s in slots)
    return b"\xaa\xff\x03\x00" + body + b"\x55\xcc"


def test_off_unless_asked(monkeypatch):
    monkeypatch.delenv("LOG_RAW", raising=False)
    assert RawLog.from_env() is None
    monkeypatch.setenv("LOG_RAW", "0")
    assert RawLog.from_env() is None


def test_rows_keep_slot_positions_and_shown_dots(tmp_path, monkeypatch):
    path = tmp_path / "x.csv"
    monkeypatch.setenv("LOG_RAW", str(path))
    log = RawLog.from_env()
    parser, fusion = Ld2450Parser(), Fusion("live")
    for i in range(4):
        t = 100 + i / 10
        (fr,) = parser.feed(raw_frame(None, (-300, 2000, 0), None), t)
        assert fr.slots[0] is None and fr.slots[1].x_mm == -300
        log.write(fr, fusion.update(t, fr, "ok", None, "offline"))
        log.write(fr, fusion.update(t + 0.05, fr, "ok", None, "offline"))     # same frame again: no new row
    log.close()
    rows = list(csv.reader(open(path)))
    assert rows[0] == HEADER and len(rows) == 5
    last = dict(zip(HEADER, rows[-1]))
    assert last["s0_x"] == "" and last["s1_x"] == "-300" and last["s1_y"] == "2000"
    assert last["id1_x"] == "-300" and last["id2_x"] == ""
