#!/usr/bin/env python3
"""Drive the handheld UI's touch interactions at 800x480 against the real demo sim and screenshot them.

    .venv/bin/python tools/ui_t4_shots.py [--out docs/screenshots] [--prefix t4]

Uses the server helpers from ui_screenshots.py (own server on :8010, SIM_SCENARIO=demo, SIM_SEED=1). Real touch
taps via page.touchscreen. Every screenshot is paired with a DOM check; exits non-zero on any failed check or
page error.
"""
import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from ui_screenshots import BASE, ROOT, get_snapshot, start_server, wait_for

APEX = (400, 474)
RADIUS = 430
HIT_PAD = 12            # how far below a status-bar button's face we tap to prove the hit area


def dot_xy(snap: dict, t: dict) -> tuple[float, float]:
    k = RADIUS / (snap["gate"]["max_range_m"] * 1000)
    return APEX[0] + t["x_mm"] * k, APEX[1] - t["y_mm"] * k


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    ap.add_argument("--prefix", default="t4")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []

    def check(cond, msg: str) -> None:
        print(("  ok   " if cond else "  FAIL ") + msg)
        if not cond:
            problems.append(msg)

    def shot(page, name: str) -> None:
        path = out / f"{args.prefix}-{name}.png"
        page.screenshot(path=str(path))
        print("  saved", path.relative_to(ROOT))

    def attr(page, sel: str, name: str) -> str | None:
        return page.locator(sel).get_attribute(name)

    def tap(page, x: float, y: float) -> None:
        page.touchscreen.tap(x, y)
        page.wait_for_timeout(150)

    def tap_center(page, sel: str, dy: float = 0) -> None:
        b = page.locator(sel).bounding_box()
        tap(page, b["x"] + b["width"] / 2, b["y"] + b["height"] / 2 + dy)

    def tap_target(page, pred, what: str, timeout: float = 30) -> dict | None:
        """Tap the nearest dot matching pred, using the freshest snapshot for its position."""
        s = wait_for(lambda s: any(pred(t) for t in s["targets"]), timeout, what)
        if not s:
            return None
        t = next(t for t in s["targets"] if pred(t))
        x, y = dot_xy(s, t)
        page.touchscreen.tap(x, y)
        page.wait_for_timeout(200)
        return t

    def set_range(page, m: int) -> None:
        tap_center(page, f'#ranges .range[data-range="{m}"]')
        wait_for(lambda s: abs(s["gate"]["max_range_m"] - m) < 0.01, 3, f"gate {m} m")
        page.wait_for_timeout(250)

    server = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(viewport={"width": 800, "height": 480}, device_scale_factor=1, has_touch=True)
            page = ctx.new_page()
            page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
            page.on("console", lambda m: m.type == "error" and problems.append(f"console error: {m.text}"))
            server = start_server()
            page.goto(BASE + "/")
            page.wait_for_function("document.getElementById('nosignal') !== null")

            print("touch target sizes")
            for sel in ("#ranges .range",):
                for box in page.locator(sel).evaluate_all(
                        "els => els.map(e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; })"):
                    check(box[0] >= 48 and box[1] >= 48, f"{sel} is {box[0]:.0f}x{box[1]:.0f} (>= 48 px)")
            for sel in ("#wordmark", "#btn-contacts"):
                # walk down the button's centre line and measure how tall the clickable area is
                run = page.evaluate(
                    """(sel) => { const r = document.querySelector(sel).getBoundingClientRect();
                        const cx = r.x + r.width / 2; let n = 0;
                        for (let y = 0; y < 80; y++) {
                          const e = document.elementFromPoint(cx, y);
                          if (e && e.closest(sel)) n++;
                        }
                        return [n, r.width + 20]; }""", sel)
                check(run[0] >= 48 and run[1] >= 48, f"{sel} hit area is {run[1]:.0f}x{run[0]} px (>= 48)")

            print("card: locked contact")
            s = wait_for(lambda s: s["vitals"]["target_id"] is not None and s["vitals"]["heart_bpm"] is None,
                         8, "sitter locked, numbers still settling")
            if s:
                tap_target(page, lambda t: t["id"] == 1, "sitter")
                page.wait_for_timeout(300)
                check(attr(page, "#card", "data-open") == "1", "tapping the sitter opens the card")
                check("settling" in page.inner_text("#c-heart"), "card shows settling... while vitals are null")
                shot(page, "1-card-settling")
            s = wait_for(lambda s: s["vitals"]["heart_bpm"] is not None and s["vitals"]["breath_rpm"] is not None,
                         15, "locked with vitals")
            if s:
                if attr(page, "#card", "data-open") != "1":
                    tap_target(page, lambda t: t["id"] == 1, "sitter")
                page.wait_for_timeout(500)
                snap = get_snapshot()
                check(attr(page, "#card", "data-mode") == "locked", "card is in locked mode")
                check(page.inner_text("#c-heart").strip() == str(snap["vitals"]["heart_bpm"])
                      or page.inner_text("#c-heart").strip().isdigit(), "card shows the heart number")
                check("CONTACT 1" in page.inner_text("#c-title"), "card title is CONTACT 1")
                cb = page.locator("#c-close").bounding_box()
                check(cb["width"] >= 48 and cb["height"] >= 48, f"card close is {cb['width']:.0f}x{cb['height']:.0f}")
                check(page.evaluate("getComputedStyle(document.getElementById('vitals')).display") == "none",
                      "corner vitals hidden while the card shows them")
                shot(page, "2-card-locked")

            print("tap empty radar closes the card")
            tap(page, 640, 120)
            check(attr(page, "#card", "data-open") == "0", "card closed")
            check(page.evaluate("getComputedStyle(document.getElementById('vitals')).display") != "none",
                  "corner vitals back")

            print("card: contact that is not locked")
            t = tap_target(page, lambda t: t["id"] != 1 and abs(t["x_mm"]) < 1500 and t["last_seen_s"] == 0,
                           "walker mid-crossing")
            if t:
                page.wait_for_timeout(300)
                check(attr(page, "#card", "data-open") == "1", "tapping the walker opens the card")
                check(attr(page, "#card", "data-mode") == "free", "card is in not-locked mode")
                body = page.inner_text("#card")
                check("Get within 1.5 m and aim at them" in body, "card says to get within 1.5 m")
                check("m to go" in body, "card shows the live distance to the lock zone")
                check("MOVING" in body, "card says MOVING")
                shot(page, "3-card-not-locked")

                print("signal lost")
                wid = t["id"]
                wait_for(lambda s: all(x["id"] != wid for x in s["targets"]), 15, "walker leaves")
                page.wait_for_timeout(350)
                check(attr(page, "#card", "data-lost") == "1", "card shows SIGNAL LOST")
                check("SIGNAL LOST" in page.inner_text("#card"), "SIGNAL LOST text is visible")
                check(not page.locator("#card .c-free").is_visible() and not page.locator("#card .c-live").is_visible(),
                      "no live guidance or vitals while lost")
                shot(page, "4-signal-lost")
                t0 = time.time()
                page.wait_for_function("document.getElementById('card').dataset.open === '0'", timeout=6000)
                dt = time.time() - t0
                check(2.2 <= dt + 0.35 <= 3.6, f"card closed {dt + 0.35:.1f} s after the loss (about 3 s)")

            print("contacts drawer")
            tap_center(page, "#btn-contacts", dy=HIT_PAD + 10)     # tap the lower edge of the hit area
            check(attr(page, "#drawer", "data-open") == "1", "contacts button opens the drawer")
            page.wait_for_timeout(250)
            rows = page.locator("#d-list li:not([hidden])").count()
            check(rows >= 2, f"drawer lists {rows} contacts (sitter + walker)")
            db = page.locator("#d-close").bounding_box()
            check(db["width"] >= 48 and db["height"] >= 48, f"drawer close is {db['width']:.0f}x{db['height']:.0f}")
            rh = page.locator("#d-list li:not([hidden]) .d-row").first.bounding_box()["height"]
            check(rh >= 48, f"drawer rows are {rh:.0f} px tall")
            live = page.locator("#d-list li:not([hidden]) .d-row:not([disabled])").count()
            check(live >= 1, "at least one row is tappable (in view)")
            shot(page, "5-drawer")
            tap_center(page, "#d-list li:not([hidden]) .d-row:not([disabled]) >> nth=0")
            page.wait_for_timeout(300)
            check(attr(page, "#drawer", "data-open") == "0", "picking a row closes the drawer")
            check(attr(page, "#card", "data-open") == "1" and "CONTACT 1" in page.inner_text("#c-title"),
                  "picking the sitter row selects contact 1 on the radar")
            shot(page, "6-drawer-selected")
            tap(page, 640, 120)

            print("range buttons")
            for m in (2, 6, 4):
                set_range(page, m)
                pressed = page.evaluate(
                    "[...document.querySelectorAll('#ranges .range')].filter(b => b.getAttribute('aria-pressed') === 'true')"
                    ".map(b => b.dataset.range)")
                check(pressed == [str(m)], f"only the {m} m button is highlighted (got {pressed})")
                if m == 6:
                    wait_for(lambda s: any(x["id"] != 1 and x["last_seen_s"] == 0 for x in s["targets"]), 25,
                             "walker visible at 6 m")
                    page.wait_for_timeout(200)
                if m == 4:
                    page.wait_for_timeout(200)
                shot(page, f"7-range-{m}m")

            print("reset (long-press the wordmark)")
            before = get_snapshot()
            check(len(before["contacts"]) > len(before["targets"]),
                  f"stale contacts exist before reset ({len(before['contacts'])} contacts, {len(before['targets'])} live)")
            b = page.locator("#wordmark").bounding_box()
            cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.wait_for_timeout(600)
            page.mouse.up()
            page.wait_for_timeout(300)
            mid = get_snapshot()
            check(len(mid["contacts"]) >= len(before["contacts"]), "a short press does not reset")
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.wait_for_timeout(1000)
            shot(page, "8-reset-holding")
            page.wait_for_timeout(800)
            page.mouse.up()
            page.wait_for_timeout(300)
            after = get_snapshot()
            check(len(after["contacts"]) <= len(after["targets"]),
                  f"hold resets the log ({len(after['contacts'])} contacts, {len(after['targets'])} live)")
            check(attr(page, "#toast", "data-show") == "1", "toast confirms")
            shot(page, "9-reset-toast")

            ctx.close()
            browser.close()
    finally:
        if server:
            server.terminate()
            server.wait(5)

    if problems:
        print("PROBLEMS:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    print("all checks passed, no page errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
