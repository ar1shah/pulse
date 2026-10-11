"""Plot a LOG_RAW CSV: raw x per sensor slot (dots) vs the x fusion shows per dot id (lines), over time.

Pure Python, writes one self-contained HTML file (open it in any browser), and prints a few numbers:
    .venv/bin/python tools/plot_x.py recordings/xlog_20261011_073000.csv            # -> same name .html
    .venv/bin/python tools/plot_x.py recordings/xlog_20261011_073000.csv --from 10 --to 40

Reading it: if the raw dots themselves zigzag or flip sides, the sensor (or the mount) is the problem and the
filter is all we can do. If the raw dots are a clean line and the shown line is not, the problem is in our code.
"""
import argparse
import csv
import html
import statistics
import sys
from pathlib import Path

W, H, PAD = 1100, 300, 50
SLOT_COLORS = ("#e4572e", "#2e86de", "#17a589")     # raw slots s0, s1, s2
ID_COLORS = ("#111111", "#8e44ad", "#d68910")        # shown ids 1, 2, 3


def num(v: str) -> float | None:
    return float(v) if v not in ("", None) else None


def load(path: Path, t_from: float, t_to: float) -> list[dict[str, float | None]]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = [{k: num(v) for k, v in r.items()} for r in csv.DictReader(f)]
    if not rows:
        return []
    t0 = rows[0]["t"]
    for r in rows:
        r["t"] -= t0
    return [r for r in rows if t_from <= r["t"] <= t_to]


def panel(rows, axis: str, title: str) -> str:
    pts = [(r["t"], r[f"s{i}_{axis}"]) for r in rows for i in range(3) if r[f"s{i}_{axis}"] is not None]
    pts += [(r["t"], r[f"id{i}_{axis}"]) for r in rows for i in (1, 2, 3) if r[f"id{i}_{axis}"] is not None]
    if not pts:
        return f"<p>{title}: no data</p>"
    t_max = max(rows[-1]["t"], 1e-6)
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    lo, hi = (lo - 100, hi + 100) if hi - lo < 200 else (lo, hi)
    sx = lambda t: PAD + (W - 2 * PAD) * t / t_max
    sy = lambda v: H - PAD + (2 * PAD - H) * (v - lo) / (hi - lo)
    out = [f'<svg width="{W}" height="{H}" style="background:#fff;border:1px solid #ccc">',
           f'<text x="{PAD}" y="20" font-weight="bold">{html.escape(title)}</text>']
    step = 500 if hi - lo > 2000 else 200 if hi - lo > 600 else 100
    for g in range(int(lo // step) * step, int(hi) + step, step):
        if lo <= g <= hi:
            out.append(f'<line x1="{PAD}" x2="{W - PAD}" y1="{sy(g):.1f}" y2="{sy(g):.1f}" stroke="#eee"/>'
                       f'<text x="4" y="{sy(g) + 4:.1f}" font-size="11">{g}</text>')
    for s in range(0, int(t_max) + 1, max(1, int(t_max // 15))):
        out.append(f'<text x="{sx(s):.1f}" y="{H - PAD + 16}" font-size="11">{s}s</text>')
    for i in range(3):
        for r in rows:
            v = r[f"s{i}_{axis}"]
            if v is not None:
                out.append(f'<circle cx="{sx(r["t"]):.1f}" cy="{sy(v):.1f}" r="2.2" fill="{SLOT_COLORS[i]}"/>')
    for i in (1, 2, 3):
        seg: list[str] = []
        for r in rows + [None]:
            v = r[f"id{i}_{axis}"] if r else None
            if v is None:
                if len(seg) > 1:
                    out.append(f'<polyline fill="none" stroke="{ID_COLORS[i - 1]}" stroke-width="2" '
                               f'points="{" ".join(seg)}"/>')
                seg = []
            else:
                seg.append(f"{sx(r['t']):.1f},{sy(v):.1f}")
    out.append("</svg>")
    return "\n".join(out)


def reversals(xs: list[float], min_mm: float = 50) -> int:
    """Direction changes bigger than min_mm: zigzags."""
    n, direction, anchor = 0, 0, xs[0] if xs else 0
    for x in xs[1:]:
        if abs(x - anchor) < min_mm:
            continue
        d = 1 if x > anchor else -1
        n += direction != 0 and d != direction
        direction, anchor = d, x
    return n


def stats(rows) -> list[str]:
    lines = [f"{len(rows)} frames over {rows[-1]['t']:.1f} s ({len(rows) / max(rows[-1]['t'], 1e-6):.1f} /s)"]
    counts = [sum(1 for r in rows if sum(r[f's{i}_x'] is not None for i in range(3)) == n) for n in range(4)]
    lines.append("frames with 0/1/2/3 raw targets: " + " / ".join(map(str, counts)))
    for i in (1, 2, 3):
        shown = [r for r in rows if r[f"id{i}_x"] is not None]
        if len(shown) < 5:
            continue
        # the raw slot nearest each shown dot, so slot swaps don't count as jumps
        raw = []
        for r in shown:
            cands = [r[f"s{k}_x"] for k in range(3) if r[f"s{k}_x"] is not None]
            if cands:
                raw.append(min(cands, key=lambda x: abs(x - r[f"id{i}_x"])))
        steps = [abs(b - a) for a, b in zip(raw, raw[1:])]
        lines.append(f"id {i}: {len(shown)} frames shown; raw x frame-to-frame step median "
                     f"{statistics.median(steps) if steps else 0:.0f} mm, max {max(steps, default=0):.0f} mm; "
                     f"zigzags >50 mm: raw {reversals(raw)}, shown {reversals([r[f'id{i}_x'] for r in shown])}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="output .html (default: next to the csv)")
    ap.add_argument("--from", dest="t_from", type=float, default=0.0, help="start, seconds into the log")
    ap.add_argument("--to", dest="t_to", type=float, default=1e9, help="end, seconds into the log")
    args = ap.parse_args()
    rows = load(args.csv, args.t_from, args.t_to)
    if not rows:
        print("no rows in that range", file=sys.stderr)
        return 1
    info = stats(rows)
    print("\n".join(info))
    legend = " ".join(f'<span style="color:{c}">&#9679; raw slot {i}</span>' for i, c in enumerate(SLOT_COLORS))
    legend += " " + " ".join(f'<span style="color:{c}">&#9644; shown id {i + 1}</span>' for i, c in enumerate(ID_COLORS))
    page = (f"<!doctype html><meta charset=utf-8><title>{html.escape(args.csv.name)}</title>"
            f"<body style='font-family:sans-serif'><h3>{html.escape(args.csv.name)}</h3><p>{legend}</p>"
            + panel(rows, "x", "x (mm), negative = holder's left") + "<br>"
            + panel(rows, "y", "y (mm), straight out")
            + "<pre>" + html.escape("\n".join(info)) + "</pre></body>")
    out = args.out or args.csv.with_suffix(".html")
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
