"""Live C1001 vitals view: presence, moving, breath, heart, frame rate, errors. Optional JSONL recording.

Run from the repo root with the venv python (stop the pulse service first, it owns the port):
    .venv/bin/python tools/c1001_dump.py /dev/ttyAMA3
    .venv/bin/python tools/c1001_dump.py /dev/ttyAMA3 --record recordings/c1001_session1.jsonl

Each recorded line: {"t": unix time, "raw": frame as hex, "reading": {"presence": ..., "moving": ..., "breath_rpm": ..., "heart_bpm": ...}}.
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
    ap.add_argument("--no-init", action="store_true", help="skip sending sleep work mode on start")
    ap.add_argument("--record", metavar="FILE.jsonl", help="append every good frame to this file")
    args = ap.parse_args()

    try:
        ser = c1001.open_serial(args.port, args.baud)
    except Exception as e:
        print(f"can't open {args.port}: {e}", file=sys.stderr)
        return 1

    if not args.no_init:
        init_cmd = c1001.cmd_set_work_mode(c1001.MODE_SLEEP)
        print("sent sleep mode switch:", init_cmd.hex(" "))
        ser.write(init_cmd)
        time.sleep(c1001.INIT_GAP_S)

    parser = c1001.C1001Parser()
    rec = open(args.record, "a", encoding="utf-8") if args.record else None
    recent: deque[float] = deque()
    last_reading: c1001.C1001Reading | None = None
    last_raw: bytes = b""
    started = time.time()
    next_draw = 0.0
    next_poll = 0.0

    try:
        while True:
            now = time.time()
            if now >= next_poll:
                ser.write(c1001.cmd_query_sleep_composite())
                next_poll = now + c1001.POLL_INTERVAL_S

            n = getattr(ser, "in_waiting", 0)
            data = ser.read(n if n > 0 else 1)
            if data:
                for frame, raw in parser.feed_with_raw(data, now):
                    recent.append(now)
                    last_raw = raw
                    r = c1001.decode_reading(frame, last_reading)
                    if r is not None:
                        last_reading = r
                    if rec:
                        rec.write(json.dumps({
                            "t": round(now, 3),
                            "raw": raw.hex(),
                            "con": f"0x{frame.con:02X}",
                            "cmd": f"0x{frame.cmd:02X}",
                            "reading": _reading_dict(last_reading),
                        }) + "\n")

            while recent and now - recent[0] > 1.0:
                recent.popleft()

            if now >= next_draw:
                next_draw = now + REDRAW_S
                _draw(args, parser, last_reading, last_raw, len(recent), now - started)
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        if rec:
            rec.close()

    print(f"\ngood {parser.good}  bad {parser.bad}  skipped bytes {parser.skipped_bytes}"
          + (f"  recorded to {args.record}" if args.record else ""))
    return 0


def _reading_dict(r: c1001.C1001Reading | None) -> dict:
    if r is None:
        return {"presence": False, "moving": None, "breath_rpm": None, "heart_bpm": None}
    return {
        "presence": r.presence,
        "moving": r.moving,
        "breath_rpm": r.breath_rpm,
        "heart_bpm": r.heart_bpm,
    }


def _draw(args, parser: c1001.C1001Parser, reading: c1001.C1001Reading | None,
          last_raw: bytes, fps: int, elapsed: float) -> None:
    lines = [
        f"C1001 {args.port} @ {args.baud}   {elapsed:6.1f} s" + ("   REC " + args.record if args.record else ""),
        f"frames/s {fps:3d}   good {parser.good}   bad {parser.bad}   skipped bytes {parser.skipped_bytes}",
        f"last raw: {last_raw.hex(' ') if last_raw else '(none)'}",
        "",
    ]
    if reading is None:
        lines.append("   (no reading yet: waiting for frames)")
    else:
        pres_str = "YES" if reading.presence else "NO"
        mov_str = "MOVING" if reading.moving is True else ("STILL" if reading.moving is False else "-")
        breath_str = f"{reading.breath_rpm} rpm" if reading.breath_rpm is not None else "(settling / none)"
        heart_str = f"{reading.heart_bpm} bpm" if reading.heart_bpm is not None else "(settling / none)"
        age = time.time() - reading.t

        lines.extend([
            f"  Presence:    {pres_str}",
            f"  Movement:    {mov_str}",
            f"  Breathing:   {breath_str}",
            f"  Heart rate:  {heart_str}",
            f"  Last frame:  {age:.1f} s ago",
        ])
        if age > c1001.STALE_S:
            lines.append("  STALE: no reading received recently")

    sys.stdout.write("\x1b[H\x1b[J" + "\n".join(lines) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
