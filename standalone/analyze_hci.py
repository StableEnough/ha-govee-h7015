#!/usr/bin/env python3
"""
Analyze a Bluetooth HCI snoop log and extract Govee H7015 packets.

This lets you find the exact packet bytes for H7015-specific operations that
aren't yet documented (notably the per-bulb segment commands). Pair this with
a screen recording of the Govee app while you set individual bulb colors, then
use the timestamps to correlate.

Requirements:
    pip install pyshark

Usage:
    # Pull the log from your phone first:
    #   adb bugreport govee.zip && unzip govee.zip -d govee_bugreport
    #   The HCI log is at govee_bugreport/FS/data/misc/bluetooth/logs/*.cfa
    #   (or govee_bugreport/FS/data/log/bt/btsnoop_hci.log on older Android)

    python analyze_hci.py govee_bugreport/FS/data/misc/bluetooth/logs/btsnoop_hci.log

    # Filter to writes only:
    python analyze_hci.py btsnoop_hci.log --writes-only

    # Filter to a specific MAC:
    python analyze_hci.py btsnoop_hci.log --mac AABBCCDDEEFF

    # Only show packets matching a known Govee prefix (33, AA, A1):
    python analyze_hci.py btsnoop_hci.log --govee-only

    # Save extracted packets as JSON for further analysis:
    python analyze_hci.py btsnoop_hci.log --json packets.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    import pyshark
except ImportError:
    raise SystemExit(
        "This tool requires pyshark. Install with:\n"
        "  pip install pyshark\n"
        "You also need tshark installed system-wide:\n"
        "  Debian/Ubuntu: sudo apt install tshark\n"
        "  macOS: brew install --cask wireshark\n"
    )


LOGGER = logging.getLogger("analyze_hci")

GOVEE_PREFIXES = (0x33, 0xAA, 0xA1)
WRITE_OPCODE = 0x52   # Write Request
READ_OPCODE = 0x0A    # Read Request
NOTIFY_OPCODE = 0x1B  # Handle-Value Notification


@dataclass
class GoveePacket:
    timestamp: str
    direction: str               # "tx" (phone -> device) or "rx"
    src: str
    dst: str
    handle: str | None
    opcode: str | None
    data_hex: str
    data_bytes: list[int]
    kind: str                    # "write", "read", "notify", "other"
    govee_kind: str | None       # "command", "keepalive", "diy", None


def classify_govee(data: bytes) -> str | None:
    if not data:
        return None
    if data[0] == 0x33:
        return "command"
    if data[0] == 0xAA:
        return "keepalive"
    if data[0] == 0xA1:
        return "diy"
    return None


def cmd_label(data: bytes) -> str:
    """Best-effort human-readable label for a Govee command packet."""
    if len(data) < 3:
        return "?"
    if data[0] != 0x33:
        return classify_govee(data) or "?"
    cmd = data[1]
    labels = {
        0x01: "power",
        0x04: "brightness",
        0x05: "color",
        0x0A: "diy",
        0x0B: "segment",
        0x14: "gradient",
    }
    label = labels.get(cmd, f"cmd_0x{cmd:02x}")
    if cmd == 0x01:
        label += ":ON" if data[2] == 1 else ":OFF"
    elif cmd == 0x04:
        label += f":{data[2]}"
    elif cmd == 0x05:
        sub = data[2]
        sublabel = {
            0x01: "music",
            0x02: "manual",
            0x04: "scene",
            0x0A: "diy",
            0x0B: "segment",
        }.get(sub, f"mode_0x{sub:02x}")
        label += f":{sublabel}"
        if sub == 0x02 and len(data) >= 6:
            label += f" rgb({data[3]},{data[4]},{data[5]})"
        elif sub == 0x0B and len(data) >= 8:
            label += f" rgb({data[3]},{data[4]},{data[5]}) left=0x{data[6]:02x} right=0x{data[7]:02x}"
        elif sub == 0x04 and len(data) >= 4:
            scenes = {
                0x00: "sunrise", 0x01: "sunset", 0x04: "movie", 0x05: "dating",
                0x07: "romantic", 0x08: "twinkle", 0x09: "candlelight",
                0x0F: "snowflake", 0x10: "energetic", 0x0A: "breathe",
                0x14: "crossing", 0x15: "rainbow",
            }
            label += f":{scenes.get(data[3], f'0x{data[3]:02x}')}"
    return label


def extract_packets(
    cap_path: Path,
    mac_filter: str | None = None,
    writes_only: bool = False,
    govee_only: bool = False,
) -> list[GoveePacket]:
    packets: list[GoveePacket] = []

    # pyshark is happiest with a display filter. We filter at the ATT layer.
    display_filter = "btatt"
    normalized_mac: str | None = None
    if mac_filter:
        # Bluetooth addresses are lower-case in the capture.
        normalized_mac = mac_filter.lower().replace("-", ":")
        display_filter += (
            f" && (bluetooth.src == {normalized_mac} "
            f"|| bluetooth.dst == {normalized_mac})"
        )

    LOGGER.info("opening %s with filter: %s", cap_path, display_filter)

    with pyshark.FileCapture(
        str(cap_path), display_filter=display_filter, use_json=True,
        include_raw=False, keep_packets=False,
    ) as cap:
        for pkt in cap:
            try:
                att = pkt.btatt
            except AttributeError:
                continue

            opcode = getattr(att, "opcode", None)
            handle = getattr(att, "handle", None)
            value = getattr(att, "value", None)

            if value is None:
                continue

            try:
                data = bytes.fromhex(str(value).replace(":", ""))
            except ValueError:
                LOGGER.debug("skipping non-hex ATT value: %s", value)
                continue
            if not data:
                continue

            try:
                src = str(pkt.bluetooth.src)
                dst = str(pkt.bluetooth.dst)
            except AttributeError:
                src = "?"
                dst = "?"

            # Determine direction: if the MAC filter matches the destination,
            # this is a TX (phone -> device). If it matches the source, RX.
            if normalized_mac:
                direction = "tx" if dst == normalized_mac else "rx"
            else:
                # No MAC filter — can't determine direction reliably
                direction = "?"

            # Determine opcode kind
            opcode_int = int(str(opcode), 0) if opcode else None
            kind = "other"
            if opcode_int == WRITE_OPCODE:
                kind = "write"
            elif opcode_int == READ_OPCODE:
                kind = "read"
            elif opcode_int == NOTIFY_OPCODE:
                kind = "notify"

            if writes_only and kind != "write":
                continue

            govee_kind = classify_govee(data)
            if govee_only and not govee_kind:
                continue

            packets.append(
                GoveePacket(
                    timestamp=str(pkt.frame_info.time),
                    direction=direction,
                    src=src,
                    dst=dst,
                    handle=str(handle) if handle else None,
                    opcode=str(opcode) if opcode else None,
                    data_hex=data.hex(),
                    data_bytes=list(data),
                    kind=kind,
                    govee_kind=govee_kind,
                )
            )

    return packets


def summarize(packets: list[GoveePacket]) -> None:
    print(f"\n=== Summary: {len(packets)} packet(s) ===")
    by_kind = Counter(p.kind for p in packets)
    for k, v in by_kind.most_common():
        print(f"  {k:8s} {v}")

    govee = [p for p in packets if p.govee_kind]
    print(f"\n=== Govee packets: {len(govee)} ===")
    by_gk = Counter(p.govee_kind for p in govee)
    for k, v in by_gk.most_common():
        print(f"  {k:10s} {v}")

    cmds = [p for p in govee if p.govee_kind == "command"]
    print(f"\n=== Distinct command payloads: {len(cmds)} ===")
    seen: dict[str, int] = {}
    for p in cmds:
        label = cmd_label(bytes(p.data_bytes))
        seen[label] = seen.get(label, 0) + 1
    for label, count in sorted(seen.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}x  {label}")

    print("\n=== Unique raw payloads (sorted by first occurrence) ===")
    printed: set[str] = set()
    for p in cmds:
        if p.data_hex in printed:
            continue
        printed.add(p.data_hex)
        print(f"  {p.timestamp}  {p.data_hex}  -> {cmd_label(bytes(p.data_bytes))}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="Path to btsnoop_hci.log / .cfa file")
    parser.add_argument("--mac", help="Filter to a Bluetooth MAC address")
    parser.add_argument("--writes-only", action="store_true")
    parser.add_argument("--govee-only", action="store_true",
                        help="Only show packets with a Govee prefix byte")
    parser.add_argument("--json", metavar="PATH",
                        help="Save extracted packets as JSON")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    cap_path = Path(args.capture)
    if not cap_path.exists():
        print(f"ERROR: file not found: {cap_path}", file=sys.stderr)
        return 2

    packets = extract_packets(
        cap_path,
        mac_filter=args.mac,
        writes_only=args.writes_only,
        govee_only=args.govee_only,
    )

    if not packets:
        print("No matching packets found. Try without --govee-only / --mac.")
        return 1

    summarize(packets)

    if args.json:
        out = [asdict(p) for p in packets]
        Path(args.json).write_text(json.dumps(out, indent=2))
        print(f"\nWrote {len(out)} packets to {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
