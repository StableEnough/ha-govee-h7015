#!/usr/bin/env python3
"""
Interactive probe for the Govee H7015.

Connects to the device and runs through a sequence of commands so you can
confirm the protocol matches your unit before wiring up the MQTT bridge.

Usage:
    python probe.py AA:BB:CC:DD:EE:FF            # run full self-test
    python probe.py AA:BB:CC:DD:EE:FF --repl      # interactive shell
    python probe.py AA:BB:CC:DD:EE:FF --on
    python probe.py AA:BB:CC:DD:EE:FF --color 255 0 0
    python probe.py AA:BB:CC:DD:EE:FF --brightness 50
    python probe.py AA:BB:CC:DD:EE:FF --scene sunrise
    python probe.py AA:BB:CC:DD:EE:FF --segment 0 255 0 0   # bulb 0 = red
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shlex
import sys

from govee_h7015 import (
    GoveeH7015Client,
    H7015State,
    MusicMode,
    Scene,
)


def print_state(state: H7015State) -> None:
    print(f"  power      = {state.power}")
    print(f"  brightness = {state.brightness}")
    print(f"  rgb        = {state.rgb}")
    print(f"  mode       = {state.mode}")
    if state.raw:
        print(f"  raw        = {state.raw.hex()}")


async def self_test(client: GoveeH7015Client) -> None:
    print("\n--- Self-test sequence ---")
    print("Power ON...")
    await client.power_on()
    await asyncio.sleep(1)

    print("Brightness 100%...")
    await client.set_brightness(100)
    await asyncio.sleep(1)

    print("Brightness 25%...")
    await client.set_brightness(25)
    await asyncio.sleep(1)

    for color in [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]:
        print(f"Color RGB{color}...")
        await client.set_color(*color)
        await asyncio.sleep(1.5)

    print("Scene: Sunrise...")
    await client.set_scene(Scene.SUNRISE)
    await asyncio.sleep(3)

    print("Scene: Rainbow...")
    await client.set_scene(Scene.RAINBOW)
    await asyncio.sleep(3)

    print("Music mode: Rhythm...")
    await client.set_music_mode(MusicMode.RHYTHM)
    await asyncio.sleep(3)

    print("Solid white...")
    await client.set_color(255, 255, 255)
    await asyncio.sleep(1)

    print("Power OFF...")
    await client.power_off()

    print("\n--- Polling state ---")
    try:
        st = await client.poll_state()
        print_state(st)
    except Exception as exc:
        print(f"  (state poll failed: {exc})")

    print("\nSelf-test complete.")


HELP_REPL = """
REPL commands:
  on, off
  brightness <0-100>
  color <r> <g> <b>           (0-255 each)
  warm
  scene <name>                (sunrise, sunset, movie, dating, romantic,
                               twinkle, candlelight, snowflake, energetic,
                               breathe, crossing, rainbow)
  music <mode> [r g b]        (energic, spectrum, rolling, rhythm)
  segment <bulb 0-14> <r> <g> <b>
  gradient <on|off>
  state                       (poll current state)
  keepalive <on|off>          (toggle keepalive task)
  quit
"""


async def repl(client: GoveeH7015Client) -> None:
    print(HELP_REPL)
    loop = asyncio.get_running_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, input, "h7015> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        line = line.strip()
        if not line:
            continue
        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            print(f"  parse error: {exc}")
            continue
        cmd, *rest = tokens
        try:
            if cmd == "quit":
                return
            elif cmd == "on":
                await client.power_on()
            elif cmd == "off":
                await client.power_off()
            elif cmd == "brightness":
                await client.set_brightness(int(rest[0]))
            elif cmd == "color":
                await client.set_color(int(rest[0]), int(rest[1]), int(rest[2]))
            elif cmd == "warm":
                await client.set_warm_white()
            elif cmd == "scene":
                await client.set_scene(Scene[rest[0].upper()])
            elif cmd == "music":
                mode = MusicMode[rest[0].upper()]
                r, g, b = (int(rest[i]) for i in (1, 2, 3)) if len(rest) >= 4 else (0, 0, 0)
                await client.set_music_mode(mode, r, g, b)
            elif cmd == "segment":
                await client.set_segment(int(rest[0]), int(rest[1]), int(rest[2]), int(rest[3]))
            elif cmd == "gradient":
                await client.set_gradient(rest[0].lower() in ("on", "true", "1"))
            elif cmd == "state":
                st = await client.poll_state()
                print_state(st)
            elif cmd == "keepalive":
                # Access the keepalive task via the public state property
                print(f"  keepalive running: {client.keepalive_running}")
            else:
                print(f"  unknown command: {cmd}")
        except (IndexError, ValueError, KeyError) as exc:
            print(f"  error: {exc}")
        except Exception as exc:
            print(f"  error: {exc!r}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", help="H7015 MAC address")
    parser.add_argument("--repl", action="store_true", help="Interactive REPL")
    parser.add_argument("--on", action="store_true")
    parser.add_argument("--off", action="store_true")
    parser.add_argument("--brightness", type=int)
    parser.add_argument("--color", nargs=3, type=int, metavar=("R", "G", "B"))
    parser.add_argument("--warm", action="store_true")
    parser.add_argument("--scene", choices=[s.name.lower() for s in Scene])
    parser.add_argument("--segment", nargs=4, type=int, metavar=("BULB", "R", "G", "B"))
    parser.add_argument("--no-keepalive", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    client = GoveeH7015Client(args.address, keepalive=not args.no_keepalive)
    await client.connect()
    try:
        if args.repl:
            await repl(client)
            return

        if args.on:
            await client.power_on()
        if args.off:
            await client.power_off()
        if args.brightness is not None:
            await client.set_brightness(args.brightness)
        if args.color:
            await client.set_color(*args.color)
        if args.warm:
            await client.set_warm_white()
        if args.scene:
            await client.set_scene(Scene[args.scene.upper()])
        if args.segment:
            bulb, r, g, b = args.segment
            await client.set_segment(bulb, r, g, b)

        # If no specific command was given, run the self-test.
        if not any(
            [
                args.on,
                args.off,
                args.brightness is not None,
                args.color,
                args.warm,
                args.scene,
                args.segment,
            ]
        ):
            await self_test(client)

        # Hold connection briefly so the final command lands.
        await asyncio.sleep(0.5)
    finally:
        await client.disconnect()


def cli() -> int:
    """Run the asynchronous probe as a console-script entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(cli())
