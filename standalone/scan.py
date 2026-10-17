#!/usr/bin/env python3
"""
Scan for nearby Govee BLE devices and print their MAC + advertised name.

The H7015 advertises as "H7015_XXXX" (last 4 of MAC). Run this once to find
the MAC address to feed into probe.py / mqtt_bridge.py.

Usage:
    python scan.py
    python scan.py --name H7015      # filter to Govee H7015 only
    python scan.py --timeout 15
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re

try:
    from bleak import BleakScanner
except ImportError:
    raise SystemExit("Please install bleak:  pip install bleak") from None


def looks_like_govee(name: str | None) -> bool:
    if not name:
        return False
    # Govee devices typically advertise as "Hxxxx_XXXX" or "Govee_xxxx".
    return bool(re.match(r"^(H\d{4}|Govee)", name, re.IGNORECASE))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name", default=None, help="Substring filter on advertised name (e.g. H7015)"
    )
    parser.add_argument(
        "--timeout", type=int, default=10, help="Scan duration in seconds (default 10)"
    )
    parser.add_argument("--all", action="store_true", help="Show all BLE devices, not just Govee")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    print(f"Scanning for {args.timeout}s... (Ctrl-C to stop early)\n")

    found: dict[str, str] = {}

    def detection_callback(device, advertisement_data):
        name = advertisement_data.local_name or device.name or ""
        if not args.all and not looks_like_govee(name):
            return
        if args.name and args.name.lower() not in name.lower():
            return
        found[device.address] = name
        # Print live as we discover
        print(f"  {device.address}  {name:30s}  RSSI={advertisement_data.rssi}dBm")

    async with BleakScanner(detection_callback=detection_callback):
        await asyncio.sleep(args.timeout)

    print(f"\nFound {len(found)} device(s):")
    for mac, name in sorted(found.items(), key=lambda kv: kv[1]):
        print(f"  {mac}  {name}")
    print("\nPass the MAC to probe.py or mqtt_bridge.py.")


def cli() -> None:
    """Run the asynchronous scanner as a console-script entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    cli()
