"""
Govee H7015 BLE protocol — type-safe, immutable, modern Python 3.12+.

Implements the Govee RGBIC BLE protocol used by the H7015 Outdoor String
Lights (and other Govee RGBIC BLE devices: H6054, H6113, H6127, H617A,
H7020, etc.). The H7015 is Bluetooth-only — no WiFi chip, no Govee LAN API.

Protocol summary (H7015 field report; items marked UNVERIFIED are not covered):
  - Service:           00010203-0405-0607-0809-0a0b0c0d1910
  - Write/notify char: 00010203-0405-0607-0809-0a0b0c0d2b11
  - Packet length:     20 bytes (zero-padded)
  - byte[0]:           0x33 command | 0xAA read/heartbeat | 0xA1 DIY write (UNVERIFIED)
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

from exceptions import GoveeChecksumError, GoveeInvalidArgumentError
from govee_types import RGB, BulbIndex, RawPacket

# ---------------------------------------------------------------------------
# GATT endpoints (shared across the Govee RGBIC BLE family)
# ---------------------------------------------------------------------------
SERVICE_UUID = "00010203-0405-0607-0809-0a0b0c0d1910"
WRITE_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"  # write + notify

PACKET_LEN: Final = 20
READ_PREFIX: Final = 0xAA  # read/heartbeat frames; only AA frames carry decodable state
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
    """Sub-command byte for COLOR (0x05) commands (byte[2])."""

    MUSIC = 0x01
    MANUAL = 0x02  # legacy; unverified on H7015
    SCENE = 0x04
    DIY = 0x0A
    SEGMENTS = 0x0B  # V1 color (r g b maskLo maskHi); fallback for old firmware, unused
    COLOR_V2 = 0x15  # field-validated, firmware >= 1.06


@final
class Scene(enum.IntEnum):
    """Classic scene codes, sent big-endian as 33 05 04 <hi> <lo>.

    Names and codes follow the app's built-in RGBIC catalogue. Wire order
    follows the user-reported H7015 field vectors; individual scene coverage
    in that report is partial.
    """

    SUNRISE = 0
    SUNSET = 1
    MOVIE = 4
    DATING = 5
    ROMANTIC = 7
    TWINKLE = 8
    CANDLELIGHT = 9
    BREATHE = 10
    SNOWFLAKE = 15
    ENERGETIC = 16
    CROSSING = 21
    RAINBOW = 22


@final
class MusicMode(enum.IntEnum):
    """Music mode IDs (byte[3] of a COLOR/MUSIC packet)."""

    ENERGIC = 0x00
    SPECTRUM = 0x01
    ROLLING = 0x02
    RHYTHM = 0x03


# ---------------------------------------------------------------------------
# Brightness: the H7015 byte is the raw percent 1..100 (field-validated)
# ---------------------------------------------------------------------------
BRIGHTNESS_MIN_RAW: Final = 1
BRIGHTNESS_MAX_RAW: Final = 100


def brightness_to_raw(percent: int) -> int:
    """Clamp percent to the device byte 1..100 (the byte IS the percent)."""
    return max(BRIGHTNESS_MIN_RAW, min(BRIGHTNESS_MAX_RAW, int(percent)))


def raw_to_brightness(raw: int) -> int:
    """Read-side inverse: the byte is the percent, clamped to 0..100."""
    return max(0, min(BRIGHTNESS_MAX_RAW, raw))


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
    """Brightness packet; percent is clamped to 1..100 (use pkt_power for off)."""
    return build_packet(b"\x33\x04", bytes([brightness_to_raw(percent)]))


def _color_v2(rgb: RGB, mask: tuple[int, int]) -> RawPacket:
    return build_packet(b"\x33\x05", bytes([ColorMode.COLOR_V2, 0x01, *rgb, 0, 0, 0, 0, 0, *mask]))


def pkt_solid_color(r: int, g: int, b: int) -> RawPacket:
    """Solid RGB matching H7015 app captures; selection bytes are at offsets 12-13."""
    return _color_v2(_clamp_rgb((r, g, b)), _segment_mask(tuple(range(BULB_COUNT))))


def pkt_warm_white() -> RawPacket:
    """Build a warm-white packet.

    The H7015 has dedicated warm-white LEDs (2700K). The encoding uses
    fixed palette bytes (0xFF 0xAE 0x54) inherited from the H6127 capture.
    Intensity is controlled by the brightness command, not this packet.

    NOTE: UNVERIFIED. Legacy 0x02 manual sub-command with palette bytes from an
    H6127 capture; the H7015 field report does not cover white.
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

    NOTE: UNVERIFIED. Not covered by the H7015 field report; the legacy 0x02
    manual sub-command and the kelvin -> warm/cold encoding come from H6127
    docs and the interpolation is a best-effort guess.
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

    # Byte layout: 0x33, 0x05, 0x02 (legacy manual), 0x00 0x00 0x00 (RGB ignored),
    # 0x01 (white LED flag), warm, cold
    return build_packet(
        b"\x33\x05",
        bytes([ColorMode.MANUAL, 0x00, 0x00, 0x00, 0x01, warm, cold]),
    )


def pkt_scene(scene: Scene) -> RawPacket:
    """Classic scene: 33 05 04 <code high> <code low> (big-endian u16)."""
    return build_packet(b"\x33\x05", bytes([ColorMode.SCENE, *scene.value.to_bytes(2, "big")]))


def pkt_music(mode: MusicMode, r: int = 0, g: int = 0, b: int = 0) -> RawPacket:
    rgb = _clamp_rgb((r, g, b))
    return build_packet(b"\x33\x05", bytes([ColorMode.MUSIC, mode.value, *rgb]))


def pkt_gradient(on: bool) -> RawPacket:
    return build_packet(b"\x33\x14", bytes([0x01 if on else 0x00]))


def pkt_segment(bulb: BulbIndex, r: int, g: int, b: int) -> RawPacket:
    """Set one bulb using the V2 layout; individual selection remains unverified."""
    if not 0 <= bulb < BULB_COUNT:
        raise GoveeInvalidArgumentError(f"bulb index must be 0..{BULB_COUNT - 1}, got {bulb}")
    return _color_v2(_clamp_rgb((r, g, b)), _segment_mask((bulb,)))


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


def _segment_mask(bulbs: tuple[int, ...]) -> tuple[int, int]:
    """Return (maskLo, maskHi) for 0-based bulb indices; maskHi keeps bit 15 clear."""
    mask = 0
    for bulb in bulbs:
        mask |= 1 << bulb
    return (mask & 0xFF, (mask >> 8) & 0x7F)


# ---------------------------------------------------------------------------
# State — immutable, frozen, slots for memory + speed
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class H7015State:
    """Last-known device state (decoded from AA read frames)."""

    power: bool | None = None
    brightness: int | None = None  # 0..100 percent
    rgb: RGB | None = None
    mode: str | None = None
    raw: bytes | None = field(default=None, repr=False)


def decode_state(raw: bytes) -> H7015State:
    """Decode a checksum-valid 20-byte AA read frame (power / brightness only).

    Command acknowledgments (0x33 ...), AB responses and anything malformed
    are never state: they come back as an empty state carrying only ``raw``.
    The AB layout is unverified, so it is deliberately not decoded.
    """
    if len(raw) != PACKET_LEN or raw[0] != READ_PREFIX or checksum(raw[:-1]) != raw[-1]:
        return H7015State(raw=raw)
    match raw[1]:
        case Command.POWER:
            return H7015State(power=bool(raw[2]), raw=raw)
        case Command.BRIGHTNESS:
            return H7015State(brightness=raw_to_brightness(raw[2]), raw=raw)
        case _:
            return H7015State(raw=raw)


__all__ = [
    "BRIGHTNESS_MAX_RAW",
    "BRIGHTNESS_MIN_RAW",
    "BULB_COUNT",
    "KEEPALIVE_INTERVAL",
    "PACKET_LEN",
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
