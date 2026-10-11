"""C1001 experiment harness (ALEX-2): poll like the reader, plus extra query words, one-off set commands and
reset strategies, recording everything that goes over the wire. The server's C1001Reader is not used or changed.

Run from the repo root with the venv python (stop the pulse service first if it is in live mode):
    .venv/bin/python tools/c1001_probe.py /dev/ttyAMA3 --record recordings/alex2_a1.jsonl --seconds 120 \
        --extra 84:81,84:8C,84:82,80:84
    ... --send 84:0F:01             write reporting mode 1 once after the ping (repeatable)
    ... --reset-on-arrival          reset (01 02) when presence goes no -> yes, then 10 s blind
    ... --reset-if-stuck 15         reset once per arrival if presence is yes for 15 s with no breath or heart

Prints one line per poll round. Recorded lines (decode with tools/c1001_timeline.py):
    {"t", "kind": "sent", "raw", "ctrl", "cmd", "data"}                       every frame we write
    {"t", "kind": "frame", "raw", "ctrl", "cmd", "data", "name", "value", "push"}   every frame the sensor sends
    {"t", "kind": "reading", "presence", "moving", "breath_rpm", "heart_bpm"} every completed poll round
    {"t", "kind": "event", "what"}                                            resets, arrivals, start, stop
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi"))

from pulse.sensors import c1001  # noqa: E402
from pulse.sensors.c1001 import C1001Frame  # noqa: E402

REPLY_TIMEOUT_S = 1.5
RESET_BLIND_S = c1001.RESET_WAIT_S


def word(s: str) -> tuple[int, int]:
    ctrl, cmd = s.split(":")[:2]
    return int(ctrl, 16), int(cmd, 16)


class Probe:
    def __init__(self, port: str, baud: int, rec_path: str | None) -> None:
        self.ser = c1001.open_serial(port, baud)
        self.parser = c1001.C1001Parser()
        self.rec = open(rec_path, "a", encoding="utf-8") if rec_path else None
        self.pushes: list[str] = []         # pushed frames since the last printed line
        self.last_push: dict[str, object] = {}

    def log(self, obj: dict) -> None:
        if self.rec:
            self.rec.write(json.dumps({"t": round(time.time(), 3), **obj}) + "\n")
            self.rec.flush()

    def event(self, what: str) -> None:
        self.log({"kind": "event", "what": what})
        print(f"--- {what}", flush=True)

    def send(self, ctrl: int, cmd: int, data: bytes = c1001.QUERY) -> None:
        raw = c1001.build_frame(ctrl, cmd, data)
        self.ser.write(raw)
        self.log({"kind": "sent", "raw": raw.hex(), "ctrl": ctrl, "cmd": cmd, "data": data.hex()})

    def read(self) -> list[C1001Frame]:
        data = self.ser.read(self.ser.in_waiting or 1)
        out = []
        for f, raw in self.parser.feed_with_raw(data):
            name, value = c1001.describe(f)
            push = c1001.is_push(f)
            self.log({"kind": "frame", "raw": raw.hex(), "ctrl": f.ctrl, "cmd": f.cmd, "data": f.data.hex(),
                      "name": name, "value": value, "push": push})
            if push:
                self.pushes.append(f"{name}={value}")
                self.last_push[name] = value
            out.append(f)
        return out

    def request(self, ctrl: int, cmd: int, data: bytes = c1001.QUERY,
                timeout_s: float = REPLY_TIMEOUT_S) -> C1001Frame | None:
        self.send(ctrl, cmd, data)
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            for f in self.read():
                if f.word == (ctrl, cmd):
                    return f
        return None

    def drain(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port")
    ap.add_argument("--baud", type=int, default=c1001.DEFAULT_BAUD)
    ap.add_argument("--record", metavar="FILE.jsonl")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long (0 = until Ctrl-C)")
    ap.add_argument("--extra", default="", help="comma-separated CTRL:CMD words (hex) to query every round")
    ap.add_argument("--send", action="append", default=[], metavar="CTRL:CMD:HEX",
                    help="write this frame once after the ping and print the reply (repeatable)")
    ap.add_argument("--reset-on-arrival", action="store_true")
    ap.add_argument("--reset-if-stuck", type=float, default=0, metavar="S")
    args = ap.parse_args()
    extras = [word(w) for w in args.extra.split(",") if w]

    p = Probe(args.port, args.baud, args.record)
    p.event(f"start {' '.join(sys.argv[1:])}")
    started = time.monotonic()
    try:
        if p.request(*c1001.PING, timeout_s=5.0) is None:
            p.event("no answer to the ping")
            return 1
        for s in args.send:
            ctrl, cmd, hexdata = s.split(":")
            r = p.request(int(ctrl, 16), int(cmd, 16), bytes.fromhex(hexdata), timeout_s=3.0)
            p.event(f"sent {s}: reply {r.data.hex() if r else 'none'}")
        prev_presence = None
        arrived_at = None           # monotonic time presence went yes
        vitals_since_arrival = False
        stuck_reset_done = False
        while not args.seconds or time.monotonic() - started < args.seconds:
            round_start = time.monotonic()
            pres = p.request(*c1001.PRESENCE)
            if pres is None:
                print("no presence reply", flush=True)
                continue
            mov, br, hr = (p.request(*w) for w in (c1001.MOVEMENT, c1001.BREATH, c1001.HEART))
            ex = {f"{c:02X}{d:02X}": c1001.describe(f)[1] if f else None
                  for (c, d), f in ((w, p.request(*w)) for w in extras)}
            presence = pres.value() == 1
            breath = c1001.decode_vital(br.value() if br else None)
            heart = c1001.decode_vital(hr.value() if hr else None)
            p.log({"kind": "reading", "presence": presence,
                   "moving": c1001.decode_moving(mov.value() if mov else None),
                   "breath_rpm": breath, "heart_bpm": heart})
            el = time.monotonic() - started
            print(f"{el:6.1f}s pres {int(presence)} mov {mov.value() if mov else '-'} "
                  f"br {breath if breath is not None else '-':>3} hr {heart if heart is not None else '-':>3} "
                  f"{' '.join(f'{k}={v}' for k, v in ex.items())}  push: {' '.join(p.pushes) or '-'}", flush=True)
            p.pushes.clear()

            if presence and prev_presence is False:
                arrived_at, vitals_since_arrival, stuck_reset_done = time.monotonic(), False, False
                p.event("arrival (presence no -> yes)")
                if args.reset_on_arrival:
                    p.request(*c1001.RESET, timeout_s=3.0)
                    p.event("reset sent (arrival); blind 10 s")
                    p.drain(RESET_BLIND_S)
            if not presence:
                arrived_at = None
            if breath is not None or heart is not None:
                vitals_since_arrival = True
            if (args.reset_if_stuck and arrived_at is not None and not vitals_since_arrival
                    and not stuck_reset_done and time.monotonic() - arrived_at >= args.reset_if_stuck):
                p.request(*c1001.RESET, timeout_s=3.0)
                p.event(f"reset sent (stuck {args.reset_if_stuck:.0f} s); blind 10 s")
                stuck_reset_done = True
                p.drain(RESET_BLIND_S)
            prev_presence = presence
            p.drain(max(0.0, c1001.POLL_S - (time.monotonic() - round_start)))
    except KeyboardInterrupt:
        pass
    finally:
        p.event(f"stop good {p.parser.good} bad {p.parser.bad}")
        p.ser.close()
        if p.rec:
            p.rec.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
