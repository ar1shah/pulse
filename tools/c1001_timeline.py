"""Decode C1001 recordings (tools/c1001_probe.py or tools/c1001_dump.py --record) second by second.

    .venv/bin/python tools/c1001_timeline.py recordings/alex2_a1.jsonl            one row per second
    .venv/bin/python tools/c1001_timeline.py --summary recordings/alex2_*.jsonl   one row per file

Time 0 is the arrival: the first presence no -> yes (pushed 80 01 or queried 80 81). A recording with no such
transition (person already there at the start) uses its first line instead and says so. Columns show the last
value seen in that second; "q" = reply to our query, "p" = pushed by the sensor on its own. Lock = first round
whose queried breath AND heart are both non-null (what the reader reports), relative to time 0.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from pulse.sensors import c1001  # noqa: E402
from pulse.sensors.c1001 import C1001Frame  # noqa: E402

# (column, name from c1001.describe, pushed?)  None = either
COLUMNS = [
    ("pres q", "presence", False), ("pres p", "presence", True), ("move", "movement", None),
    ("body", "body movement", None), ("dist", "distance", None), ("bed", "in bed", None),
    ("sleep", "sleep state", None), ("rmode", "reporting mode", None),
    ("br q", "breath", False), ("br p", "breath", True), ("hr q", "heart", False), ("hr p", "heart", True),
]
KNOWN = {name for _, name, _ in COLUMNS}


def load(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def frame_of(rec: dict) -> tuple[str, object, bool]:
    f = C1001Frame(rec["ctrl"], rec["cmd"], bytes.fromhex(rec.get("data", "")))
    name, value = c1001.describe(f)
    return name, value, c1001.is_push(f)


def arrival(recs: list[dict]) -> tuple[float, bool]:
    """(time 0, True if it is a real no -> yes transition)."""
    last: bool | None = None
    for r in recs:
        if r.get("kind") != "frame":
            continue
        name, value, _ = frame_of(r)
        if name != "presence":
            continue
        now = value == 1
        if now and last is False:
            return r["t"], True
        last = now
    return recs[0]["t"], False


def first_after(recs: list[dict], t0: float, pred) -> float | None:
    for r in recs:
        if r["t"] >= t0 and pred(r):
            return round(r["t"] - t0, 1)
    return None


def stats(recs: list[dict]) -> dict:
    t0, real = arrival(recs)
    readings = [r for r in recs if r.get("kind") == "reading"]

    def pushed(name: str):
        def pred(r):
            if r.get("kind") != "frame":
                return False
            n, v, push = frame_of(r)
            return push and n == name and c1001.decode_vital(v if isinstance(v, int) else None) is not None
        return pred

    return {
        "arrival": "walk-up" if real else "at start",
        "breath": first_after(readings, t0, lambda r: r["breath_rpm"] is not None),
        "heart": first_after(readings, t0, lambda r: r["heart_bpm"] is not None),
        "lock": first_after(readings, t0, lambda r: r["breath_rpm"] is not None and r["heart_bpm"] is not None),
        "br push": first_after(recs, t0, pushed("breath")),
        "hr push": first_after(recs, t0, pushed("heart")),
        "resets": [round(r["t"] - t0, 1) for r in recs if r.get("kind") == "event" and "reset sent" in r["what"]],
        "length": round(recs[-1]["t"] - t0, 1),
    }


def timeline(recs: list[dict], before_s: int) -> None:
    t0, real = arrival(recs)
    print(f"time 0 = {'arrival (presence no -> yes)' if real else 'first line (no arrival in this recording)'}")
    print(" sec | " + " ".join(f"{c:>6}" for c, _, _ in COLUMNS) + " | events, other pushes")
    rows: dict[int, dict] = {}
    for r in recs:
        sec = int((r["t"] - t0) // 1)
        if sec < -before_s:
            continue
        row = rows.setdefault(sec, {"notes": []})
        if r.get("kind") == "event":
            row["notes"].append(r["what"])
        elif r.get("kind") == "frame":
            name, value, push = frame_of(r)
            for col, cname, cpush in COLUMNS:
                if cname == name and (cpush is None or cpush == push):
                    row[col] = value
            if name not in KNOWN and push:
                row["notes"].append(f"{name}={value}")
    for sec in range(min(rows), max(rows) + 1):
        row = rows.get(sec, {"notes": []})
        cells = " ".join(f"{_fmt(row.get(c)):>6}" for c, _, _ in COLUMNS)
        notes = sorted(set(row["notes"]), key=row["notes"].index)
        print(f"{sec:4d} | {cells} | {', '.join(notes)}")
    print(stats(recs))


def _fmt(v: object) -> str:
    if v is None:
        return "."
    if isinstance(v, (tuple, list)):
        return "/".join(str(x) for x in v)
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--summary", action="store_true", help="one row per file instead of the per-second table")
    ap.add_argument("--before", type=int, default=10, help="seconds before time 0 to show (default 10)")
    args = ap.parse_args()
    for path in args.files:
        recs = load(path)
        if not recs:
            print(f"{path}: empty")
            continue
        if args.summary:
            print(f"{path.name}: {stats(recs)}")
        else:
            print(f"== {path}")
            timeline(recs, args.before)
    return 0


if __name__ == "__main__":
    sys.exit(main())
