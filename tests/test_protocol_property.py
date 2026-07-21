"""Property-based tests for the Govee H7015 protocol using Hypothesis.

These fuzz the protocol with thousands of generated inputs to catch
edge cases that example-based tests miss.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "standalone"))

from protocol import (  # type: ignore[import-not-found]
    BRIGHTNESS_MAX_RAW,
    BRIGHTNESS_MIN_RAW,
    BULB_COUNT,
    PACKET_LEN,
    Scene,
    brightness_to_raw,
    build_packet,
    checksum,
    decode_state,
    pkt_brightness,
    pkt_music,
    pkt_power,
    pkt_scene,
    pkt_segment,
    pkt_solid_color,
    raw_to_brightness,
    validate_packet,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------
st_rgb = st.tuples(
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
)
st_brightness = st.integers(min_value=0, max_value=100)
st_bulb = st.integers(min_value=0, max_value=BULB_COUNT - 1)
st_byte = st.integers(min_value=0, max_value=255)


# ---------------------------------------------------------------------------
# Packet structure invariants
# ---------------------------------------------------------------------------
class TestPacketInvariants:
    @given(st_brightness)
    def test_brightness_packet_always_20_bytes(self, b: int) -> None:
        assert len(pkt_brightness(b)) == PACKET_LEN

    @given(st_rgb)
    def test_color_packet_always_20_bytes(self, rgb: tuple[int, int, int]) -> None:
        assert len(pkt_solid_color(*rgb)) == PACKET_LEN

    @given(st_bulb, st_rgb)
    def test_segment_packet_always_20_bytes(
        self, bulb: int, rgb: tuple[int, int, int]
    ) -> None:
        assert len(pkt_segment(bulb, *rgb)) == PACKET_LEN

    @given(st.lists(st_rgb, min_size=1, max_size=15))
    def test_multi_segment_packets_each_20_bytes(
        self, colors: list[tuple[int, int, int]]
    ) -> None:
        pairs = [(i, *c) for i, c in enumerate(colors)]
        from protocol import pkt_multi_segment  # type: ignore[import-not-found]
        for pkt in pkt_multi_segment(pairs):
            assert len(pkt) == PACKET_LEN

    @given(st_rgb)
    def test_checksum_byte_is_xor_of_first_19(self, rgb: tuple[int, int, int]) -> None:
        pkt = pkt_solid_color(*rgb)
        body = pkt[:-1]
        assert pkt[-1] == checksum(body)


# ---------------------------------------------------------------------------
# Brightness round-trip property
# ---------------------------------------------------------------------------
class TestBrightnessRoundTrip:
    @given(st_brightness)
    def test_round_trip_within_1_percent(self, pct: int) -> None:
        """Send pct%, get raw byte, decode back — should be within 1."""
        raw = brightness_to_raw(pct)
        decoded = raw_to_brightness(raw)
        if pct == 0:
            assert decoded == 0
        else:
            assert abs(decoded - pct) <= 1

    @given(st.integers(min_value=BRIGHTNESS_MIN_RAW, max_value=BRIGHTNESS_MAX_RAW))
    def test_raw_to_brightness_to_raw_idempotent(self, raw: int) -> None:
        """raw -> percent -> raw should be the identity (within rounding)."""
        pct = raw_to_brightness(raw)
        raw2 = brightness_to_raw(pct)
        assert abs(raw2 - raw) <= 2  # rounding tolerance


# ---------------------------------------------------------------------------
# Validate_packet property
# ---------------------------------------------------------------------------
class TestValidatePacket:
    @given(st_rgb)
    def test_valid_packets_pass(self, rgb: tuple[int, int, int]) -> None:
        pkt = pkt_solid_color(*rgb)
        # Should not raise
        result = validate_packet(pkt)
        assert result == pkt

    @given(st_rgb)
    def test_corrupted_packets_fail(self, rgb: tuple[int, int, int]) -> None:
        from exceptions import GoveeChecksumError  # type: ignore[import-not-found]

        pkt = bytearray(pkt_solid_color(*rgb))
        # Flip a bit in the payload (not the checksum)
        pkt[5] ^= 0xFF
        with pytest.raises(GoveeChecksumError):
            validate_packet(bytes(pkt))


# ---------------------------------------------------------------------------
# Decode_state robustness (fuzz with arbitrary bytes)
# ---------------------------------------------------------------------------
class TestDecodeStateRobustness:
    @given(st.binary(min_size=0, max_size=40))
    def test_never_raises(self, raw: bytes) -> None:
        """decode_state must never raise, no matter what bytes it gets."""
        st = decode_state(raw)
        # And the raw should be preserved
        assert st.raw == raw if raw else st.raw in (None, raw)

    @given(st_byte, st_byte, st_byte)
    def test_power_decode_when_prefix_matches(
        self, cmd: int, val: int, _: int
    ) -> None:
        """If byte 0 is 0x33 and byte 1 is 0x01 (POWER), power should decode."""
        raw = bytes([0x33, 0x01, val]) + b"\x00" * 17
        st = decode_state(raw)
        assert st.power == bool(val)


# ---------------------------------------------------------------------------
# Enum coverage
# ---------------------------------------------------------------------------
class TestEnumCoverage:
    @given(st.sampled_from(list(Scene)))
    def test_every_scene_produces_valid_packet(self, scene: Scene) -> None:
        pkt = pkt_scene(scene)
        assert len(pkt) == PACKET_LEN
        assert pkt[0] == 0x33
        assert pkt[-1] == checksum(pkt[:-1])
        # The scene value should appear at byte 3
        assert pkt[3] == scene.value
