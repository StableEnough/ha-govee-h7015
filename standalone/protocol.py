"""
Govee H7015 BLE protocol — type-safe, immutable, modern Python 3.12+.

Implements the Govee RGBIC BLE protocol used by the H7015 Outdoor String
Lights (and other Govee RGBIC BLE devices: H6054, H6113, H6127, H617A,
H7020, etc.). The H7015 is Bluetooth-only — no WiFi chip, no Govee LAN API.

Protocol summary (community-documented for sibling devices):
  - Service:           00010203-0405-0607-0809-0a0b0c0d1910
  - Write char:        00010203-0405-0607-0809-0a0b0c0d2b11
  - Read  char:        00010203-0405-0607-0809-0a0b0c0d2b10
  - Packet length:     20 bytes (zero-padded)
  - byte[0]:           0x33 command | 0xAA keepalive | 0xA1 DIY write
  - byte[1]:           command type
  - byte[2..18]:       payload
  - byte[19]:          XOR checksum of bytes[0..18]

References:
  - BeauJBurroughs/Govee-H6127-Reverse-Engineering
  - blog.coding.kiwi/reverse-engineering-govee-smart-lights
  - community.home-assistant.io Govee H617A reverse-engineering thread
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Final, final

from exceptions import GoveeChecksumError, GoveeInvalidArgumentError, GoveeProtocolError
from govee_types import RGB, BulbIndex, RawPacket

# ---------------------------------------------------------------------------
# GATT endpoints (shared across the Govee RGBIC BLE family)
# ---------------------------------------------------------------------------
SERVICE_UUID = "00010203-0405-0607-0809-0a0b0c0d1910"
WRITE_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"
READ_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b10"

PACKET_LEN: Final = 20
KEEPALIVE_INTERVAL: Final = 2.0  # seconds; Govee app sends one every ~2s
BULB_COUNT: Final = 15


# ---------------------------------------------------------------------------
# Enumerations — IntEnum for clean int values + readable repr
# ---------------------------------------------------------------------------
@final
class Command(enum.IntEnum):
    """Command type byte (byte[1] of a 0x33-prefix packet)."""

    POWER = 0x01
    BRIGHTNESS = 0x04
    COLOR = 0x05
    DIY = 0x0A
    SEGMENTS = 0x0B
    GRADIENT = 0x14


@final
class ColorMode(enum.IntEnum):
    """Sub-mode byte for COLOR commands (byte[2])."""

    MUSIC = 0x01
    MANUAL = 0x02
    SCENE = 0x04
    DIY = 0x0A
    SEGMENTS = 0x0B


@final
class Scene(enum.IntEnum):
    """Scene effect IDs (byte[3] of a COLOR/SCENE packet).

    The H7015 supports 47 scene modes. These IDs are inherited from the
    H6127 reverse engineering work and may not all be valid on the H7015 —
    confirm via HCI capture if a specific scene doesn't work.
    """

    # Original 12 scenes (confirmed working on H6127)
    SUNRISE = 0x00
    SUNSET = 0x01
    MOVIE = 0x04
    DATING = 0x05
    ROMANTIC = 0x07
    TWINKLE = 0x08
    CANDLELIGHT = 0x09
    BREATHE = 0x0A
    SNOWFLAKE = 0x0F
    ENERGETIC = 0x10
    CROSSING = 0x14
    RAINBOW = 0x15

    # Additional scenes from H6127 protocol docs (may work on H7015)
    SNOWING = 0x02
    CLOUD = 0x03
    GORGEOUS = 0x06
    BLINKING = 0x0B
    STARRY = 0x0C
    FLOW = 0x0D
    DREAM = 0x0E
    JUMPING = 0x11
    VOLCANO = 0x12
    RIPPLE = 0x13
    SHADOW = 0x16
    WIND = 0x17
    OCEAN = 0x18
    AURORA = 0x19
    FOREST = 0x1A
    WATERFALL = 0x1B
    FIREFLY = 0x1C
    SPARKLE = 0x1D
    METEOR = 0x1E
    GALAXY = 0x1F
    SUNNY = 0x20
    NIGHT = 0x21
    DAWN = 0x22
    DUSK = 0x23
    SPRING = 0x24
    SUMMER = 0x25
    AUTUMN = 0x26
    WINTER = 0x27
    CHRISTMAS = 0x28
    HALLOWEEN = 0x29
    THANKSGIVING = 0x2A
    VALENTINE = 0x2B
    NEW_YEAR = 0x2C
    BIRTHDAY = 0x2D
    PARTY = 0x2E
    RELAX = 0x2F
    ENERGIZE = 0x30
    FOCUS = 0x31
    READING = 0x32
    NIGHT_LIGHT = 0x33
    CELEBRATE = 0x34
    FESTIVE = 0x35
    GRADIENT = 0x36
    PULSE = 0x37
    WAVE = 0x38
    CHASE = 0x39
    STACK = 0x3A


@final
class MusicMode(enum.IntEnum):
    """Music mode IDs (byte[3] of a COLOR/MUSIC packet)."""

    ENERGIC = 0x00
    SPECTRUM = 0x01
    ROLLING = 0x02
    RHYTHM = 0x03


# ---------------------------------------------------------------------------
# Brightness mapping (0x00 = off, 0x14 = 1%, 0xFE = 100%)
# ---------------------------------------------------------------------------
BRIGHTNESS_MIN_RAW: Final = 0x14
BRIGHTNESS_MAX_RAW: Final = 0xFE


def brightness_to_raw(percent: int) -> int:
    """Map 0..100 percent to the device's raw byte (0x00 / 0x14..0xFE)."""
    if percent <= 0:
        return 0x00
    if percent >= 100:
        return BRIGHTNESS_MAX_RAW
    return int(BRIGHTNESS_MIN_RAW + (BRIGHTNESS_MAX_RAW - BRIGHTNESS_MIN_RAW) * (percent - 1) / 99)


def raw_to_brightness(raw: int) -> int:
    """Map the device's raw byte back to 0..100 percent.

    Inverse of brightness_to_raw. Uses the same linear mapping so the
    round-trip is exact (no off-by-one at the top end).
    """
    if raw <= 0:
        return 0
    if raw >= BRIGHTNESS_MAX_RAW:
        return 100
    if raw < BRIGHTNESS_MIN_RAW:
        # Between 0 and 0x14 — treat as 1% (device's minimum non-off)
        return 1
    # Inverse of: raw = 0x14 + (0xFE - 0x14) * (percent - 1) / 99
    # So: percent = (raw - 0x14) / (0xFE - 0x14) * 99 + 1
    percent = round((raw - BRIGHTNESS_MIN_RAW) / (BRIGHTNESS_MAX_RAW - BRIGHTNESS_MIN_RAW) * 99) + 1
    return max(1, min(100, percent))


# ---------------------------------------------------------------------------
# Packet construction — pure functions, immutable outputs
# ---------------------------------------------------------------------------
def checksum(payload: bytes) -> int:
    """XOR all bytes together; returns 0..255."""
    c = 0
    for b in payload:
        c ^= b
    return c & 0xFF


def build_packet(prefix: bytes, payload: bytes = b"") -> RawPacket:
    """Build a 20-byte packet with zero-padding and XOR checksum.

    Args:
        prefix:  Typically 2 bytes (indicator + command), e.g. b"\\x33\\x01".
        payload: Up to 17 bytes of data; the rest is zero-padded.

    Returns:
        A 20-byte RawPacket (NewType over bytes).
    """
    body = (prefix + payload)[: PACKET_LEN - 1].ljust(PACKET_LEN - 1, b"\x00")
    return RawPacket(body + bytes([checksum(body)]))


def validate_packet(packet: bytes) -> RawPacket:
    """Verify a 20-byte packet's checksum and return it as a RawPacket.

    Raises GoveeChecksumError if the checksum doesn't match.
    """
    if len(packet) != PACKET_LEN:
        raise GoveeChecksumError(f"packet must be {PACKET_LEN} bytes, got {len(packet)}")
    expected = checksum(packet[:-1])
    if packet[-1] != expected:
        raise GoveeChecksumError(
            f"checksum mismatch: expected 0x{expected:02x}, got 0x{packet[-1]:02x}"
        )
    return RawPacket(packet)


# --- Specific commands ----------------------------------------------------
def pkt_keepalive() -> RawPacket:
    return build_packet(b"\xaa\x01")


def pkt_power(on: bool) -> RawPacket:
    return build_packet(b"\x33\x01", bytes([0x01 if on else 0x00]))


def pkt_brightness(percent: int) -> RawPacket:
    """Build a brightness packet. percent is 0..100."""
    return build_packet(b"\x33\x04", bytes([brightness_to_raw(percent)]))


def pkt_solid_color(r: int, g: int, b: int) -> RawPacket:
    """Build a solid-color packet. r, g, b are 0..255 (clamped)."""
    rgb = _clamp_rgb((r, g, b))
    return build_packet(b"\x33\x05", bytes([ColorMode.MANUAL, *rgb]))


def pkt_warm_white() -> RawPacket:
    """Build a warm-white packet.

    The H7015 has dedicated warm-white LEDs (2700K). The encoding uses
    fixed palette bytes (0xFF 0xAE 0x54) inherited from the H6127 capture.
    Intensity is controlled by the brightness command, not this packet.

    NOTE: The warm-white palette bytes should be confirmed via HCI capture
    for the H7015 specifically.
    """
    return build_packet(
        b"\x33\x05",
        bytes([ColorMode.MANUAL, 0xFF, 0xFF, 0xFF, 0x00, 0xFF, 0xAE, 0x54]),
    )


def pkt_color_temperature(kelvin: int) -> RawPacket:
    """Build a color-temperature packet for warm/cold white.

    The H7015 has dedicated white LEDs. The Govee app uses a slider from
    2000K (warm) to 6500K (cold). The protocol uses a flag byte (0x01 at
    byte[6]) to switch from RGB to white LEDs, then encodes the warm/cold
    mix in bytes 7-8.

    NOTE: The exact encoding of kelvin → warm/cold bytes is inherited from
    the H6127 protocol docs ("the slider within the app UI uses a list of
    hardcoded color codes"). This is a best-effort linear interpolation.
    Confirm via HCI capture for the H7015.
    """
    # Clamp to the H7015's supported range (2700K-6500K per Amazon listing)
    k = max(2000, min(6500, int(kelvin)))

    # Linear interpolation: 2000K = warmest (0xFF, 0x00), 6500K = coldest (0x00, 0xFF)
    # Warm white LEDs at max, cold white at 0 → 2000K
    # Warm white at 0, cold white at max → 6500K
    if k <= 2000:
        warm = 0xFF
        cold = 0x00
    elif k >= 6500:
        warm = 0x00
        cold = 0xFF
    else:
        # Linear interpolation between 2000K and 6500K
        ratio = (k - 2000) / (6500 - 2000)
        warm = int(0xFF * (1 - ratio))
        cold = int(0xFF * ratio)

    # Byte layout: 0x33, 0x05, 0x02 (manual), 0x00 0x00 0x00 (RGB ignored),
    # 0x01 (white LED flag), warm, cold
    return build_packet(
        b"\x33\x05",
        bytes([ColorMode.MANUAL, 0x00, 0x00, 0x00, 0x01, warm, cold]),
    )


def pkt_scene(scene: Scene) -> RawPacket:
    return build_packet(b"\x33\x05", bytes([ColorMode.SCENE, scene.value]))


def pkt_music(mode: MusicMode, r: int = 0, g: int = 0, b: int = 0) -> RawPacket:
    rgb = _clamp_rgb((r, g, b))
    return build_packet(b"\x33\x05", bytes([ColorMode.MUSIC, mode.value, *rgb]))


def pkt_gradient(on: bool) -> RawPacket:
    return build_packet(b"\x33\x14", bytes([0x01 if on else 0x00]))


def pkt_segment(bulb: BulbIndex, r: int, g: int, b: int) -> RawPacket:
    """Set a single bulb's color.

    The H7015's per-bulb encoding may differ from the H6127 bitmask layout
    used here — confirm via HCI capture and patch this function.
    """
    if not 0 <= bulb < BULB_COUNT:
        raise GoveeInvalidArgumentError(f"bulb index must be 0..{BULB_COUNT - 1}, got {bulb}")
    rgb = _clamp_rgb((r, g, b))
    left, right = _bulb_to_bitmask(bulb)
    return build_packet(
        b"\x33\x05",
        bytes([ColorMode.SEGMENTS, *rgb, left, right]),
    )


def pkt_multi_segment(pairs: list[tuple[BulbIndex, int, int, int]]) -> list[RawPacket]:
    """Build one packet per (bulb, r, g, b) pair."""
    return [pkt_segment(bulb, r, g, b) for bulb, r, g, b in pairs]


# ---------------------------------------------------------------------------
# DIY Mode — multi-packet 0xA1 sequence
# ---------------------------------------------------------------------------
@final
class DIYStyle(enum.IntEnum):
    """Animation style for DIY mode (byte 4 of DIY data packets)."""

    FADE = 0x00
    JUMPING = 0x01
    FLICKER = 0x02
    MARQUEE = 0x03
    MUSIC = 0x04
    COMBO = 0xFF


@final
class DIYStyleMode(enum.IntEnum):
    """Sub-mode for each DIY style (byte 5)."""

    WHOLE = 0x00
    SUBSECTION = 0x01
    CIRCULATION = 0x02


def pkt_diy(
    name: int,
    style: DIYStyle,
    style_mode: DIYStyleMode,
    speed: int,
    colors: list[tuple[int, int, int]],
) -> list[RawPacket]:
    """Build the multi-packet DIY mode sequence.

    The Govee DIY protocol uses a 0xA1 prefix with a multi-packet sequence:
      1. Start packet (0xA1 0x02 0x00 <total> ...)
      2. Data packet(s) — style, speed, colors
      3. End packet (0xA1 0x02 0xFF ...)
      4. DIY activate command (0x33 0x05 0x0A ...)

    Args:
        name: DIY slot name byte (0x00-0xFF, used by the Govee app)
        style: Animation style (fade, jumping, flicker, marquee, music, combo)
        style_mode: Sub-mode (whole, subsection, circulation)
        speed: Animation speed (0=stopped, 100=fastest)
        colors: List of RGB colors (up to 8, each 0-255)

    Returns:
        List of RawPackets to send sequentially.

    NOTE: This is based on the H6127 reverse engineering. Confirm via HCI
    capture for the H7015 before relying on it.
    """
    if not 0 <= speed <= 100:
        raise GoveeInvalidArgumentError(f"speed must be 0..100, got {speed}")
    if not colors:
        raise GoveeInvalidArgumentError("at least one color required")
    if len(colors) > 8:
        raise GoveeInvalidArgumentError(f"max 8 colors, got {len(colors)}")

    # Scale speed: 0..100 → 0..0x64
    speed_byte = int(speed * 0x64 / 100)

    # Clamp colors
    clamped = [_clamp_rgb(c) for c in colors]

    packets: list[RawPacket] = []

    # Determine how many data packets we need (1-3 based on color count)
    # Each data packet can hold ~4-5 colors (3 bytes each + header)
    total_data_packets = 1
    if len(clamped) > 2:
        total_data_packets = 2
    if len(clamped) > 5:
        total_data_packets = 3

    # Start packet: A1 02 00 <total_data_packets> <padding> <checksum>
    start_payload = bytes([0xA1, 0x02, 0x00, total_data_packets])
    start_pkt = build_packet(start_payload)
    packets.append(start_pkt)

    # Data packet 1: style, mode, speed, colors[0:2]
    data1 = bytearray([0xA1, 0x02, 0x01, name, style.value, style_mode.value, speed_byte, 0x18])
    for r, g, b in clamped[:2]:
        data1.extend([r, g, b])
    # Pad to 19 bytes (before checksum)
    while len(data1) < 19:
        data1.append(0x00)
    data1.append(checksum(bytes(data1)))
    packets.append(RawPacket(bytes(data1)))

    # Data packet 2 (if needed): remaining colors
    if len(clamped) > 2:
        data2 = bytearray([0xA1, 0x02, 0x02])
        # First byte is blue of last color from packet 1 (if odd count)
        remaining = clamped[2:]
        for r, g, b in remaining:
            data2.extend([r, g, b])
        while len(data2) < 19:
            data2.append(0x00)
        data2.append(checksum(bytes(data2)))
        packets.append(RawPacket(bytes(data2)))

    # Data packet 3 (combo mode only): style/mode data
    if style == DIYStyle.COMBO:
        data3 = bytearray([0xA1, 0x02, 0x03, 0x01, 0x00, 0x02, 0x00, 0x03, 0x03])
        while len(data3) < 19:
            data3.append(0x00)
        data3.append(checksum(bytes(data3)))
        packets.append(RawPacket(bytes(data3)))

    # End packet: A1 02 FF <padding> <checksum>
    end_pkt = build_packet(bytes([0xA1, 0x02, 0xFF]))
    packets.append(end_pkt)

    # DIY activate command: 33 05 0A 00..00 <checksum>
    activate_pkt = build_packet(b"\x33\x05", bytes([ColorMode.DIY]))
    packets.append(activate_pkt)

    return packets


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _clamp_rgb(rgb: tuple[int, int, int]) -> RGB:
    """Clamp each channel to 0..255."""
    r, g, b = rgb
    return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def _bulb_to_bitmask(bulb: int) -> tuple[int, int]:
    """Map bulb index 0..14 to (left_byte, right_byte) per H6127 layout.

    H6127 splits 15 segments into left byte (segments 1-8) and right byte
    (segments 9-15). One bit set per bulb.
    """
    if bulb < 8:
        return (1 << bulb, 0x00)
    return (0x00, 1 << (bulb - 8))


# ---------------------------------------------------------------------------
# State — immutable, frozen, slots for memory + speed
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class H7015State:
    """Last-known device state (read from the read characteristic)."""

    power: bool | None = None
    brightness: int | None = None  # 0..100 percent
    rgb: RGB | None = None
    mode: str | None = None
    raw: bytes | None = field(default=None, repr=False)


def decode_state(raw: bytes) -> H7015State:
    """Best-effort decode of the read characteristic.

    The H7015's exact state format isn't publicly documented; this is a
    placeholder based on the H6127 format. Update after capturing real
    H7015 state frames.
    """
    if not raw or len(raw) < 3 or raw[0] != 0x33:
        return H7015State(raw=raw)

    cmd = raw[1]
    return _decode_by_command(cmd, raw)


def _decode_by_command(cmd: int, raw: bytes) -> H7015State:
    """Dispatch on command byte using match.

    Raises GoveeProtocolError if the packet is too short for its command type.
    """
    match cmd:
        case Command.POWER:
            if len(raw) < 3:
                raise GoveeProtocolError(f"power packet too short: {len(raw)} bytes")
            return H7015State(power=bool(raw[2]), raw=raw)
        case Command.BRIGHTNESS:
            if len(raw) < 3:
                raise GoveeProtocolError(f"brightness packet too short: {len(raw)} bytes")
            return H7015State(brightness=raw_to_brightness(raw[2]), raw=raw)
        case Command.COLOR:
            if len(raw) < 6:
                raise GoveeProtocolError(f"color packet too short: {len(raw)} bytes")
            # Only extract RGB for manual mode (0x02). For scene/music/segment
            # modes, byte 3 is a scene ID or music mode, not red.
            sub_mode = raw[2]
            if sub_mode == ColorMode.MANUAL:
                return H7015State(rgb=(raw[3], raw[4], raw[5]), raw=raw)
            # For scene/music/segment modes, don't report bogus RGB
            return H7015State(raw=raw)
        case _:
            return H7015State(raw=raw)


__all__ = [
    "BRIGHTNESS_MAX_RAW",
    "BRIGHTNESS_MIN_RAW",
    "BULB_COUNT",
    "KEEPALIVE_INTERVAL",
    "PACKET_LEN",
    "READ_CHAR_UUID",
    "SERVICE_UUID",
    "WRITE_CHAR_UUID",
    "ColorMode",
    "Command",
    "DIYStyle",
    "DIYStyleMode",
    "H7015State",
    "MusicMode",
    "RawPacket",
    "Scene",
    "brightness_to_raw",
    "build_packet",
    "checksum",
    "decode_state",
    "pkt_brightness",
    "pkt_color_temperature",
    "pkt_diy",
    "pkt_gradient",
    "pkt_keepalive",
    "pkt_multi_segment",
    "pkt_music",
    "pkt_power",
    "pkt_scene",
    "pkt_segment",
    "pkt_solid_color",
    "pkt_warm_white",
    "raw_to_brightness",
    "validate_packet",
]
