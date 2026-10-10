#!/usr/bin/env python3
"""Screenshot the handheld UI at 800x480 for review and docs. Dev tool: needs playwright (pi/requirements-dev.txt).

    .venv/bin/python tools/ui_screenshots.py [--out docs/screenshots] [--prefix t3]

Starts its own sim server on port 8010 (SIM_SCENARIO=demo, SIM_SEED=1), so it never clashes with a dev server
on 8000. The real-server shots (settling, locked, walker, held) follow the demo timeline. States the demo
never reaches (no lock, a narrow gate, NO SIGNAL) come from a mocked /ws. Exits non-zero on any page error.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = 8010
BASE = f"http://localhost:{PORT}"


def get_snapshot() -> dict:
    with urllib.request.urlopen(f"{BASE}/api/snapshot", timeout=2) as r:
        return json.load(r)


def wait_for(pred, timeout: float, what: str) -> dict | None:
    end = time.time() + timeout
    while time.time() < end:
        s = get_snapshot()
        if pred(s):
            return s
        time.sleep(0.05)
    print(f"  ! timed out waiting for {what}", file=sys.stderr)
    return None


def start_server() -> subprocess.Popen:
    env = dict(os.environ, PULSE_SOURCE="sim", SIM_SCENARIO="demo", SIM_SEED="1")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "pulse.main:create_app", "--factory",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT / "pi", env=env)
    end = time.time() + 15
    while time.time() < end:
        try:
            get_snapshot()
            return proc
        except Exception:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit("server did not come up")


def target(i, x, y, triage="gray", locked=False, last_seen=0.0, moving=False):
    import math
    return {"id": i, "x_mm": x, "y_mm": y, "range_m": round(math.hypot(x, y) / 1000, 2),
            "angle_deg": round(math.degrees(math.atan2(x, y)), 1), "speed_cms": 0, "moving": moving,
            "triage": triage, "locked": locked, "last_seen_s": last_seen}


def mock_snapshot(t, targets, vitals=None, gate=None, contacts=3, sensors=None):
    return {
        "type": "snapshot", "v": 1, "t": t, "source": "sim",
        "gate": gate or {"max_range_m": 4.0, "max_angle_deg": 60},
        "targets": targets,
        "vitals": vitals or {"target_id": None, "presence": False, "moving": None, "breath_rpm": None,
                             "heart_bpm": None, "settled": False, "age_s": None},
        "sensors": sensors or {"ld2450": "sim", "c1001": "sim"},
        "contacts": [{"id": i, "first_seen": t - 30, "last_seen": t, "triage": "gray",
                      "last_breath_rpm": None, "last_heart_bpm": None} for i in range(contacts)],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    ap.add_argument("--prefix", default="t3")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []

    def shot(page, name):
        path = out / f"{args.prefix}-{name}.png"
        page.screenshot(path=str(path))
        print("  saved", path.relative_to(ROOT))

    def new_page(browser):
        ctx = browser.new_context(viewport={"width": 800, "height": 480}, device_scale_factor=1)
        page = ctx.new_page()
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
        page.on("console", lambda m: m.type == "error" and problems.append(f"console error: {m.text}"))
        return ctx, page

    def play_mock(page, route, frames):
        for _ in range(60):             # the page opens its socket right after load
            if route:
                break
            page.wait_for_timeout(50)
        for i, f in enumerate(frames):
            route[0].send(json.dumps(f))
            page.wait_for_timeout(100)

    server = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()

            # --- real server, demo timeline ---
            print("real server shots", flush=True)
            ctx, page = new_page(browser)
            server = start_server()          # started after the browser so the settling window is not missed
            page.goto(BASE + "/")
            page.wait_for_function("document.getElementById('nosignal') !== null")
            s = wait_for(lambda s: s["vitals"]["target_id"] is not None and s["vitals"]["heart_bpm"] is None,
                         6, "settling")
            if s:
                page.wait_for_timeout(500)
                shot(page, "1-settling")
            s = wait_for(lambda s: s["vitals"]["heart_bpm"] is not None and s["vitals"]["breath_rpm"] is not None,
                         15, "locked with vitals")
            if s:
                page.wait_for_timeout(2200)         # let the trace fill
                shot(page, "2-locked")
            s = wait_for(lambda s: any(t["id"] != 1 and abs(t["x_mm"]) < 700 and t["last_seen_s"] == 0
                                       for t in s["targets"]), 30, "walker mid-crossing")
            if s:
                shot(page, "3-walker")
            s = wait_for(lambda s: any(t["last_seen_s"] > 1.5 for t in s["targets"]), 30, "a held target")
            if s:
                shot(page, "4-held")
            fps = page.evaluate("""new Promise((res) => { let n = 0; const t0 = performance.now();
                const tick = () => { n++; performance.now() - t0 < 1000 ? requestAnimationFrame(tick) : res(n); };
                requestAnimationFrame(tick); })""")
            print(f"  headless fps: {fps} (software rendering, not a Pi number)")
            ctx.close()

            # --- mocked /ws: states the demo never reaches ---
            print("mocked shots", flush=True)
            ctx, page = new_page(browser)
            route: list = []
            page.route_web_socket("**/ws", lambda ws: route.append(ws))
            page.goto(BASE + "/")
            page.wait_for_function("document.getElementById('nosignal') !== null")
            t = 1_800_000_000.0

            # no lock: a mover and a held, not-assessed track; nothing in the cone
            frames = [mock_snapshot(t + i / 10, [
                target(1, -1300 + i * 3, 2300, "green", moving=True),
                target(2, 1700, 1900, "gray", last_seen=1.0 + i / 10),
            ]) for i in range(30)]
            play_mock(page, route, frames)
            shot(page, "5-idle")

            # tight gate (2 m, 30 deg) with a lock and a locked dot near the right edge of the cone
            frames = [mock_snapshot(t + 5 + i / 10, [
                target(1, 520, 1050, "amber", locked=True),
                target(2, -450, 1500, "green", moving=True),
            ], vitals={"target_id": 1, "presence": True, "moving": False, "breath_rpm": 18,
                       "heart_bpm": 74, "settled": True, "age_s": 0.3},
                gate={"max_range_m": 2.0, "max_angle_deg": 30}) for i in range(40)]
            play_mock(page, route, frames)
            shot(page, "6-gate-2m")

            # offline sensors in the status bar
            frames = [mock_snapshot(t + 10 + i / 10, [], sensors={"ld2450": "offline", "c1001": "warming"})
                      for i in range(10)]
            play_mock(page, route, frames)
            shot(page, "7-sensors-down")
            ctx.close()

            # --- NO SIGNAL: no socket can be opened ---
            ctx, page = new_page(browser)
            page.add_init_script("window.WebSocket = class { constructor() { throw new Error('blocked'); } };")
            page.goto(BASE + "/")
            page.wait_for_function("document.getElementById('nosignal') !== null")
            page.wait_for_timeout(800)
            shot(page, "8-no-signal")
            ctx.close()
            browser.close()
    finally:
        if server:
            server.terminate()
            server.wait(5)

    if problems:
        print("PAGE PROBLEMS:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    print("no page errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
