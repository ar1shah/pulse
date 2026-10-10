"""UART loopback test: with the port's TX jumpered to its RX, every byte written must come straight back.

Run on the Pi, with the jumper in place and nothing else on the port (stop the pulse service if it is in live mode):
    python3 tools/uart_loopback.py /dev/ttyAMA0 256000      # pin 8 to pin 10
    python3 tools/uart_loopback.py /dev/ttyAMA3 115200      # pin 7 to pin 29 (UART3; check the device name)

Any pyserial URL works too, e.g. `loop://` to check the tool itself. Exit 0 = pass, 1 = fail, 2 = can't open.
"""
import argparse
import os
import sys
import time

import serial

TIMEOUT_S = 1.0


def patterns() -> list[tuple[str, bytes]]:
    return [
        ("all byte values", bytes(range(256))),
        ("LD2450-style frame", bytes.fromhex("AAFF0300 0E03B186 10004001") + bytes(16) + bytes.fromhex("55CC")),
        ("C1001-style frame", bytes.fromhex("5359 8081 0001 0F 3D 5443")),
        ("0x55 / 0xAA", b"\x55\xaa" * 64),
        ("random", os.urandom(512)),
    ]


def read_exactly(ser: serial.SerialBase, n: int) -> bytes:
    got = bytearray()
    deadline = time.monotonic() + TIMEOUT_S + n * 10 / max(ser.baudrate, 1)
    while len(got) < n and time.monotonic() < deadline:
        got += ser.read(n - len(got))
    return bytes(got)


def check(name: str, sent: bytes, got: bytes) -> bool:
    if got == sent:
        print(f"  ok    {name}: {len(sent)} bytes")
        return True
    if not got:
        print(f"  FAIL  {name}: nothing came back (jumper missing or on the wrong pins, or the UART isn't enabled)")
        return False
    first = next((i for i, (a, b) in enumerate(zip(sent, got)) if a != b), min(len(sent), len(got)))
    print(f"  FAIL  {name}: sent {len(sent)}, got {len(got)}, first difference at byte {first} "
          f"(garbled bytes usually mean a baud mismatch, e.g. the mini UART instead of the PL011)")
    print(f"        sent {sent[first:first + 8].hex(' ')}  got {got[first:first + 8].hex(' ')}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port", help="serial device (e.g. /dev/ttyAMA0) or pyserial URL (loop://)")
    ap.add_argument("baud", type=int)
    args = ap.parse_args()

    try:
        ser = serial.serial_for_url(args.port, args.baud, timeout=0.1)
    except Exception as e:
        print(f"can't open {args.port}: {e}", file=sys.stderr)
        return 2

    print(f"loopback on {args.port} at {args.baud} baud")
    with ser:
        time.sleep(0.05)
        ser.reset_input_buffer()
        results = []
        for name, data in patterns():
            ser.write(data)
            ser.flush()
            results.append(check(name, data, read_exactly(ser, len(data))))
        extra = ser.read(64)
        if extra:
            print(f"  FAIL  {len(extra)}+ unexpected extra bytes: {extra[:8].hex(' ')} (is something else on this port?)")
            results.append(False)

    passed = all(results)
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
