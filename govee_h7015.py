"""
Govee H7015 BLE protocol library.

This module implements the Govee RGBIC BLE protocol used by the H7015 Outdoor
String Lights (and other Govee RGBIC BLE devices: H6054, H6113, H6127, H617A,
H7020, etc.). The H7015 is Bluetooth-only -- there is no WiFi chip and no
support for Govee's LAN API.

Protocol summary (already documented by the community for sibling devices):
  - Service:           00010203-0405-0607-0809-0a0b0c0d1910
  - Write char:        00010203-0405-0607-0809-0a0b0c0d2b11
  - Read  char:        00010203-0405-0607-0809-0a0b0c0d2b10
  - Packet length:     20 bytes (zero-padded)
  - byte[0]:           0x33 command | 0xAA keepalive | 0xA1 DIY write
  - byte[1]:           command type (0x01 power, 0x04 brightness,
                                  0x05 color, 0x0a DIY, 0x0b segments)
  - byte[2..18]:       payload
  - byte[19]:          XOR checksum of bytes[0..18]

Reference: BeauJBurroughs/Govee-H6127-Reverse-Engineering,
           blog.coding.kiwi/reverse-engineering-govee-smart-lights,
           community.home-assistant.io Govee H617A reverse-engineering thread.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Awaitable, Callable, Optional

try:
    from bleak import BleakClient
    from bleak.exc import BleakError
except ImportError:  # pragma: no cover - bleak only required for live use
    BleakClient = None  # type: ignore
    BleakError = Exception  # type: ignore

LOGGER = logging.getLogger("govee_h7015")

# ---------------------------------------------------------------------------
# GATT endpoints (shared across the Govee RGBIC BLE family)
# ---------------------------------------------------------------------------
SERVICE_UUID = "00010203-0405-0607-0809-0a0b0c0d1910"
WRITE_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"
READ_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b10"

PACKET_LEN = 20
KEEPALIVE_INTERVAL = 2.0  # seconds; Govee app sends one every ~2s


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class Command(IntEnum):
    POWER = 0x01
    BRIGHTNESS = 0x04
    COLOR = 0x05
    DIY = 0x0A
    SEGMENTS = 0x0B
    GRADIENT = 0x14


class ColorMode(IntEnum):
    MANUAL = 0x02
    MUSIC = 0x01
    SCENE = 0x04
    DIY = 0x0A
    SEGMENTS = 0x0B


class MusicMode(IntEnum):
    ENERGIC = 0x00
    SPECTRUM = 0x01
    ROLLING = 0x02
    RHYTHM = 0x03


class Scene(IntEnum):
    SUNRISE = 0x00
    SUNSET = 0x01
    MOVIE = 0x04
    DATING = 0x05
    ROMANTIC = 0x07
    TWINKLE = 0x08
    CANDLELIGHT = 0x09
    SNOWFLAKE = 0x0F
    ENERGETIC = 0x10
    BREATHE = 0x0A
    CROSSING = 0x14
    RAINBOW = 0x15


# ---------------------------------------------------------------------------
# Packet builders
# ---------------------------------------------------------------------------
def checksum(payload: bytes) -> int:
    """XOR all bytes together. Used as the 20th byte of every packet."""
    c = 0
    for b in payload:
        c ^= b
    return c & 0xFF


def build_packet(prefix: bytes, payload: bytes = b"") -> bytes:
    """
    Build a 20-byte packet.

    prefix:  typically 2 bytes (indicator + command), e.g. b"\\x33\\x01"
    payload: up to 17 bytes of data; the rest is zero-padded
    """
    body = (prefix + payload)[: PACKET_LEN - 1].ljust(PACKET_LEN - 1, b"\x00")
    return body + bytes([checksum(body)])


# --- Specific commands ----------------------------------------------------
def pkt_keepalive() -> bytes:
    return build_packet(b"\xaa\x01")


def pkt_power(on: bool) -> bytes:
    return build_packet(b"\x33\x01", bytes([0x01 if on else 0x00]))


def pkt_brightness(value: int) -> bytes:
    """value: 0..100 -> 0x00..0xFE (0x14 = 1%, 0xFE = 100%)."""
    value = max(0, min(100, int(value)))
    # Map 1..100 onto 0x14..0xFE linearly; 0 stays 0.
    if value == 0:
        raw = 0x00
    else:
        raw = int(0x14 + (0xFE - 0x14) * (value - 1) / 99)
    return build_packet(b"\x33\x04", bytes([raw]))


def pkt_solid_color(r: int, g: int, b: int) -> bytes:
    r, g, b = (max(0, min(255, int(c))) for c in (r, g, b))
    return build_packet(b"\x33\x05", bytes([ColorMode.MANUAL, r, g, b]))


def pkt_warm_white(value: int) -> bytes:
    """
    Warm-white-only LED. Govee uses a fixed warm-white palette; sending a
    manual color with the warm-white flag set is the usual approach. The
    exact palette byte for the H7015 should be confirmed via HCI capture,
    but the H6127 family uses 0xFF 0xAE 0x54 in the second RGB slot.
    """
    value = max(0, min(255, int(value)))
    # Placeholder: 0x02 manual, 0xFF 0xFF 0xFF RGB set to max for warm,
    # followed by warm-white palette bytes captured from H6127.
    return build_packet(
        b"\x33\x05",
        bytes([ColorMode.MANUAL, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0xAE, 0x54]),
    )


def pkt_scene(scene: Scene) -> bytes:
    return build_packet(b"\x33\x05", bytes([ColorMode.SCENE, scene.value]))


def pkt_music(mode: MusicMode, r: int = 0, g: int = 0, b: int = 0) -> bytes:
    r, g, b = (max(0, min(255, int(c))) for c in (r, g, b))
    return build_packet(
        b"\x33\x05",
        bytes([ColorMode.MUSIC, mode.value, r, g, b]),
    )


def pkt_gradient(on: bool) -> bytes:
    return build_packet(b"\x33\x14", bytes([0x01 if on else 0x00]))


def pkt_segment(bulb_index: int, r: int, g: int, b: int) -> bytes:
    """
    Set the color of a single bulb on the H7015.

    The H7015 has 15 individually-addressable bulbs. The exact segment
    encoding on the H7015 differs from the H6127 strip (which splits
    segments into left-half / right-half bitmasks). Until you capture the
    H7015-specific segment packet via HCI snoop, this builder uses the
    H6127-style encoding as a starting guess and may need adjustment.

    bulb_index: 0..14
    """
    if not 0 <= bulb_index < 15:
        raise ValueError("bulb_index must be 0..14")
    r, g, b = (max(0, min(255, int(c))) for c in (r, g, b))
    # H6127 layout: left byte covers segments 1-8, right byte covers 9-15.
    # We approximate by setting only one bit at a time. This is a starting
    # point and must be confirmed against a real H7015 capture.
    left = 0x00
    right = 0x00
    if bulb_index < 8:
        left = 1 << bulb_index
    else:
        right = 1 << (bulb_index - 8)
    return build_packet(
        b"\x33\x05",
        bytes([ColorMode.SEGMENTS, r, g, b, left, right]),
    )


def pkt_multi_segment(pairs: list[tuple[int, int, int, int]]) -> list[bytes]:
    """
    Set multiple bulbs in one logical operation. The Govee protocol may
    require several writes to address all 15 bulbs; this helper just emits
    one packet per pair. Returns a list ready to send sequentially.
    """
    return [pkt_segment(i, r, g, b) for (i, r, g, b) in pairs]


# ---------------------------------------------------------------------------
# BLE client with keepalive
# ---------------------------------------------------------------------------
@dataclass
class H7015State:
    """Last-known device state (read from the read characteristic)."""

    power: Optional[bool] = None
    brightness: Optional[int] = None
    rgb: Optional[tuple[int, int, int]] = None
    mode: Optional[str] = None
    raw: Optional[bytes] = field(default=None, repr=False)


class GoveeH7015Client:
    """
    Async BLE client for the H7015.

    Keeps a keepalive task running while connected. Reconnects on drop.

    Usage:
        async with GoveeH7015Client("AA:BB:CC:DD:EE:FF") as c:
            await c.power_on()
            await asyncio.sleep(1)
            await c.set_color(255, 0, 0)
            await asyncio.sleep(1)
            await c.set_brightness(50)
    """

    def __init__(
        self,
        address: str,
        keepalive: bool = True,
        reconnect: bool = True,
        state_callback: Optional[Callable[[H7015State], Awaitable[None]]] = None,
    ) -> None:
        if BleakClient is None:
            raise RuntimeError(
                "bleak is not installed. Run: pip install bleak"
            )
        self.address = address
        self.keepalive_enabled = keepalive
        self.reconnect_enabled = reconnect
        self.state_callback = state_callback
        self._client: Optional[BleakClient] = None
        self._keepalive_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._state = H7015State()

    @property
    def state(self) -> H7015State:
        return self._state

    async def __aenter__(self) -> "GoveeH7015Client":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.disconnect()

    async def connect(self, timeout: float = 20.0) -> None:
        LOGGER.info("Connecting to %s", self.address)
        self._client = BleakClient(
            self.address, timeout=timeout, disconnected_callback=self._on_disconnect
        )
        await self._client.connect()
        # Wait a beat before service discovery (community-known quirk).
        await asyncio.sleep(0.2)
        if self.keepalive_enabled:
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        LOGGER.info("Connected to %s", self.address)

    async def disconnect(self) -> None:
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None
        LOGGER.info("Disconnected")

    def _on_disconnect(self, client: BleakClient) -> None:
        LOGGER.warning("Device disconnected: %s", self.address)
        if self.reconnect_enabled:
            asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        for attempt in range(1, 11):
            LOGGER.info("Reconnect attempt %d/10", attempt)
            try:
                await self.connect()
                return
            except Exception as exc:  # pragma: no cover
                LOGGER.warning("Reconnect failed: %s", exc)
                await asyncio.sleep(2 ** min(attempt, 5))
        LOGGER.error("Giving up reconnect after 10 attempts")

    async def _keepalive_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                try:
                    await self._write(pkt_keepalive(), response=False)
                except Exception as exc:  # pragma: no cover
                    LOGGER.debug("keepalive write failed: %s", exc)
        except asyncio.CancelledError:
            raise

    async def _write(self, data: bytes, response: bool = True) -> None:
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected")
        async with self._lock:
            LOGGER.debug("TX %s", data.hex())
            await self._client.write_gatt_char(WRITE_CHAR_UUID, data, response=response)

    # --- High-level commands ------------------------------------------------
    async def power_on(self) -> None:
        await self._write(pkt_power(True))
        self._state.power = True

    async def power_off(self) -> None:
        await self._write(pkt_power(False))
        self._state.power = False

    async def set_power(self, on: bool) -> None:
        await self.power_on() if on else await self.power_off()

    async def set_brightness(self, value: int) -> None:
        await self._write(pkt_brightness(value))
        self._state.brightness = value

    async def set_color(self, r: int, g: int, b: int) -> None:
        await self._write(pkt_solid_color(r, g, b))
        self._state.rgb = (r, g, b)
        self._state.mode = "manual"

    async def set_warm_white(self, value: int = 255) -> None:
        await self._write(pkt_warm_white(value))

    async def set_scene(self, scene: Scene) -> None:
        await self._write(pkt_scene(scene))
        self._state.mode = f"scene:{scene.name.lower()}"

    async def set_music_mode(
        self, mode: MusicMode, r: int = 0, g: int = 0, b: int = 0
    ) -> None:
        await self._write(pkt_music(mode, r, g, b))
        self._state.mode = f"music:{mode.name.lower()}"

    async def set_gradient(self, on: bool) -> None:
        await self._write(pkt_gradient(on))

    async def set_segment(self, bulb: int, r: int, g: int, b: int) -> None:
        for pkt in pkt_multi_segment([(bulb, r, g, b)]):
            await self._write(pkt)

    async def set_segments(self, pairs: list[tuple[int, int, int, int]]) -> None:
        for pkt in pkt_multi_segment(pairs):
            await self._write(pkt)
            await asyncio.sleep(0.05)  # pacing

    async def poll_state(self) -> H7015State:
        """Read the read characteristic and best-effort decode state."""
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected")
        raw = await self._client.read_gatt_char(READ_CHAR_UUID)
        self._state.raw = raw
        # Best-effort decode. The exact state-format on the H7015 is not
        # publicly documented; this is a placeholder until a capture is
        # available.
        if raw and raw[0] == 0x33:
            cmd = raw[1]
            if cmd == Command.POWER:
                self._state.power = bool(raw[2])
            elif cmd == Command.BRIGHTNESS:
                self._state.brightness = raw[2]
            elif cmd == Command.COLOR and len(raw) >= 6:
                self._state.rgb = (raw[3], raw[4], raw[5])
        if self.state_callback:
            await self.state_callback(self._state)
        return self._state


# ---------------------------------------------------------------------------
# CLI for quick manual testing
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Govee H7015 BLE CLI")
    parser.add_argument("address", help="MAC address of the H7015")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("on")
    sub.add_parser("off")
    p_br = sub.add_parser("brightness")
    p_br.add_argument("value", type=int)
    p_col = sub.add_parser("color")
    p_col.add_argument("r", type=int)
    p_col.add_argument("g", type=int)
    p_col.add_argument("b", type=int)
    p_scene = sub.add_parser("scene")
    p_scene.add_argument("name", choices=[s.name.lower() for s in Scene])
    p_seg = sub.add_parser("segment")
    p_seg.add_argument("bulb", type=int)
    p_seg.add_argument("r", type=int)
    p_seg.add_argument("g", type=int)
    p_seg.add_argument("b", type=int)
    sub.add_parser("state")

    args = parser.parse_args()

    async def run() -> None:
        async with GoveeH7015Client(args.address) as c:
            if args.cmd == "on":
                await c.power_on()
            elif args.cmd == "off":
                await c.power_off()
            elif args.cmd == "brightness":
                await c.set_brightness(args.value)
            elif args.cmd == "color":
                await c.set_color(args.r, args.g, args.b)
            elif args.cmd == "scene":
                await c.set_scene(Scene[args.name.upper()])
            elif args.cmd == "segment":
                await c.set_segment(args.bulb, args.r, args.g, args.b)
            elif args.cmd == "state":
                st = await c.poll_state()
                print(st)
            await asyncio.sleep(0.5)

    try:
        asyncio.run(run())
    except BleakError as exc:
        print(f"BLE error: {exc}", file=sys.stderr)
        sys.exit(1)
