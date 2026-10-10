"""Live LD2450 view: targets (x, y, range, angle, speed), frames/sec, bad frames. Optional JSONL recording.

Run from the repo root with the venv python (stop the pulse service first, it owns the port):
    .venv/bin/python tools/ld2450_dump.py /dev/ttyAMA0 --multi
    .venv/bin/python tools/ld2450_dump.py /dev/ttyAMA0 --record recordings/ld2450_session1.jsonl

Each recorded line: {"t": unix time, "raw": 30-byte frame as hex, "targets": [parsed, contract conventions]}.
"""
import argparse
import json
import math
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from pulse.sensors import ld2450  # noqa: E402

REDRAW_S = 0.2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port", help="serial port, e.g. /dev/ttyAMA0 or /dev/tty.usbserial-*")
    ap.add_argument("--baud", type=int, default=ld2450.DEFAULT_BAUD)
    ap.add_argument("--multi", action="store_true", help="send enable config, multi-target, end config first")
    ap.add_argument("--record", metavar="FILE.jsonl", help="append every good frame to this file")
    args = ap.parse_args()

    try:
        ser = ld2450.open_serial(args.port, args.baud)
    except Exception as e:
        print(f"can't open {args.port}: {e}", file=sys.stderr)
        return 1

    parser = ld2450.Ld2450Parser()
    if args.multi:
        for cmd in ld2450.mode_commands(multi=True):
            print("sent", cmd.hex(" "))
            ser.write(cmd)
            time.sleep(ld2450.CMD_GAP_S)

    rec = open(args.record, "a", encoding="utf-8") if args.record else None
    recent: deque[float] = deque()          # frame times in the last second, for frames/sec
    last: ld2450.Ld2450Frame | None = None
    acks: list[str] = []
    started = time.time()
    next_draw = 0.0
    try:
        while True:
            data = ser.read(ser.in_waiting or 1)
            now = time.time()
            for frame, raw in parser.feed_with_raw(data, now) if data else []:
                last = frame
                recent.append(now)
                if rec:
                    rec.write(json.dumps({"t": round(now, 3), "raw": raw.hex(),
                                          "targets": [_target_dict(t) for t in frame.targets]}) + "\n")
            while parser.acks:
                a = parser.acks.popleft()
                acks.append(f"0x{a.command:04X} {'ok' if a.ok else 'FAIL'}")
            while recent and now - recent[0] > 1.0:
                recent.popleft()
            if now >= next_draw:
                next_draw = now + REDRAW_S
                _draw(args, parser, last, len(recent), acks, now - started)
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        if rec:
            rec.close()
    print(f"\ngood {parser.good}  bad {parser.bad}  skipped bytes {parser.skipped_bytes}"
          + (f"  recorded to {args.record}" if args.record else ""))
    return 0


def _target_dict(t: ld2450.Ld2450Target) -> dict[str, int]:
    return {"x_mm": t.x_mm, "y_mm": t.y_mm, "speed_cms": t.speed_cms, "resolution_mm": t.resolution_mm}


def _draw(args, parser: ld2450.Ld2450Parser, frame: ld2450.Ld2450Frame | None, fps: int,
          acks: list[str], elapsed: float) -> None:
    lines = [
        f"LD2450 {args.port} @ {args.baud}   {elapsed:6.1f} s" + ("   REC " + args.record if args.record else ""),
        f"frames/s {fps:3d}   good {parser.good}   bad {parser.bad}   skipped bytes {parser.skipped_bytes}",
        f"signs: X_SIGN={ld2450.X_SIGN:+d} (want holder's left = x < 0)   "
        f"SPEED_SIGN={ld2450.SPEED_SIGN:+d} (want approaching = speed < 0)",
        "acks: " + (", ".join(acks[-4:]) if acks else "-"),
        "",
        f"{'#':>2} {'x mm':>7} {'y mm':>7} {'range m':>8} {'angle':>7} {'speed cm/s':>11} {'res mm':>7}",
    ]
    targets = frame.targets if frame else []
    age = time.time() - frame.t if frame else None
    for i, t in enumerate(targets, 1):
        rng = math.hypot(t.x_mm, t.y_mm) / 1000
        ang = math.degrees(math.atan2(t.x_mm, t.y_mm))
        side = "L" if ang < -0.5 else "R" if ang > 0.5 else " "
        lines.append(f"{i:>2} {t.x_mm:>7d} {t.y_mm:>7d} {rng:>8.2f} {abs(ang):>5.1f} {side} {t.speed_cms:>11d}"
                     f" {t.resolution_mm:>7d}")
    if not targets:
        lines.append("   (no targets)" if frame else "   (no frames yet: check wiring, baud, and that the service is stopped)")
    if age is not None and age > ld2450.STALE_S:
        lines.append(f"   STALE: last frame {age:.1f} s ago")
    sys.stdout.write("\x1b[H\x1b[J" + "\n".join(lines) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
