"""Live C1001 view: presence, moving, breath, heart, frames/sec, errors. Optional JSONL recording.

Runs the real C1001Reader (same init + polling as the server), so it also shows the init phase.
Run from the repo root with the venv python (stop the pulse service first, it owns the port):
    .venv/bin/python tools/c1001_dump.py /dev/ttyAMA3
    .venv/bin/python tools/c1001_dump.py /dev/ttyAMA3 --record recordings/c1001_session1.jsonl

Recorded lines, two kinds:
    {"t", "kind": "frame", "raw": frame hex, "ctrl", "cmd", "data": hex}     every frame the sensor sends
    {"t", "kind": "reading", "presence", "moving", "breath_rpm", "heart_bpm"} every completed poll round
Replay should parse "raw" (or use the readings); frames are what the sensor actually said.
"""
import argparse
import json
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from pulse.sensors import c1001  # noqa: E402

REDRAW_S = 0.2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port", help="serial port, e.g. /dev/ttyAMA3 or /dev/tty.usbserial-*")
    ap.add_argument("--baud", type=int, default=c1001.DEFAULT_BAUD)
    ap.add_argument("--record", metavar="FILE.jsonl", help="append every frame and reading to this file")
    args = ap.parse_args()

    rec = open(args.record, "a", encoding="utf-8") if args.record else None
    recent: deque[float] = deque()          # frame times in the last second, for frames/sec

    def on_frame(f: c1001.C1001Frame, raw: bytes, t: float) -> None:
        recent.append(t)
        if rec:
            rec.write(json.dumps({"t": round(t, 3), "kind": "frame", "raw": raw.hex(),
                                  "ctrl": f.ctrl, "cmd": f.cmd, "data": f.data.hex()}) + "\n")

    reader = c1001.C1001Reader(args.port, args.baud)
    reader.on_frame = on_frame
    reader.start()
    started = time.time()
    last_t = None
    readings = 0
    try:
        while True:
            now = time.time()
            reading, status = reader.latest(now)
            if reading is not None and reading.t != last_t:
                last_t = reading.t
                readings += 1
                if rec:
                    rec.write(json.dumps({"t": round(reading.t, 3), "kind": "reading", "presence": reading.presence,
                                          "moving": reading.moving, "breath_rpm": reading.breath_rpm,
                                          "heart_bpm": reading.heart_bpm}) + "\n")
                    rec.flush()
            while recent and now - recent[0] > 1.0:
                recent.popleft()
            _draw(args, reader, reading, status, len(recent), readings, now - started)
            time.sleep(REDRAW_S)
    except KeyboardInterrupt:
        pass
    finally:
        reader.stop()
        if rec:
            rec.close()
    p = reader.parser
    print(f"\ngood {p.good}  bad {p.bad} (checksum {p.bad_checksum})  skipped bytes {p.skipped_bytes}"
          f"  timeouts {reader.timeouts}  readings {readings}"
          + (f"  recorded to {args.record}" if args.record else ""))
    return 0


def _fmt(v: object, unit: str = "") -> str:
    return "-" if v is None else f"{v}{unit}"


def _draw(args, reader: c1001.C1001Reader, r: c1001.C1001Reading | None, status: str, fps: int,
          readings: int, elapsed: float) -> None:
    p = reader.parser
    unsolicited = ", ".join(f"{c:02X} {d:02X} x{n}" for (c, d), n in reader.unsolicited.most_common(6)) or "-"
    lines = [
        f"C1001 {args.port} @ {args.baud}   {elapsed:6.1f} s" + ("   REC " + args.record if args.record else ""),
        f"status {status:<8} phase {reader.phase}",
        f"frames/s {fps:3d}   good {p.good}   bad {p.bad} (checksum {p.bad_checksum})   "
        f"skipped bytes {p.skipped_bytes}   timeouts {reader.timeouts}   readings {readings}",
        f"unsolicited frames: {unsolicited}",
        "",
    ]
    if r is None:
        hint = {"offline": "no answer: check wiring (sensor TX to Pi RX), port, and that the service is stopped",
                "warming": "sensor answering, setting up (mode switch / reset can take 10 to 20 s)"}
        lines.append("   (no reading yet: " + hint.get(status, status) + ")")
    else:
        age = time.time() - r.t
        lines += [
            f"   presence  {'YES' if r.presence else 'no'}",
            f"   moving    {_fmt(r.moving)}",
            f"   breath    {_fmt(r.breath_rpm, ' /min')}",
            f"   heart     {_fmt(r.heart_bpm, ' bpm')}",
            f"   age       {age:.1f} s" + ("   STALE" if age > c1001.STALE_S else ""),
        ]
    sys.stdout.write("\x1b[H\x1b[J" + "\n".join(lines) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
