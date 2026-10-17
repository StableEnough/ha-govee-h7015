"""Property-based tests for the Govee H7015 protocol using Hypothesis.

These fuzz the protocol with thousands of generated inputs to catch
edge cases that example-based tests miss.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hypothesis import given
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
    def test_segment_packet_always_20_bytes(self, bulb: int, rgb: tuple[int, int, int]) -> None:
        assert len(pkt_segment(bulb, *rgb)) == PACKET_LEN

    @given(st.lists(st_rgb, min_size=1, max_size=15))
    def test_multi_segment_packets_each_20_bytes(self, colors: list[tuple[int, int, int]]) -> None:
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
class TestBrightnessBoundaries:
    @given(st.integers(min_value=-1000, max_value=1000))
    def test_command_byte_is_percent_clamped_to_1_100(self, pct: int) -> None:
        assert pkt_brightness(pct)[2] == max(BRIGHTNESS_MIN_RAW, min(BRIGHTNESS_MAX_RAW, pct))

    @given(st.integers(min_value=0, max_value=255))
    def test_read_byte_never_exceeds_percent_range(self, raw: int) -> None:
        assert 0 <= raw_to_brightness(raw) <= 100

    @given(st.integers(min_value=BRIGHTNESS_MIN_RAW, max_value=BRIGHTNESS_MAX_RAW))
    def test_in_range_percent_is_identity(self, pct: int) -> None:
        assert brightness_to_raw(pct) == pct == raw_to_brightness(pct)


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

    @given(st_byte)
    def test_only_checksum_valid_aa_frames_decode_power(self, val: int) -> None:
        frame = bytes(build_packet(b"\xaa\x01", bytes([val])))
        assert decode_state(frame).power == bool(val)
        # The same bytes as a 0x33 command acknowledgment are never state.
        ack = bytes(build_packet(b"\x33\x01", bytes([val])))
        assert decode_state(ack).power is None


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
        # Scene code is a big-endian u16 at bytes 3..4
        assert int.from_bytes(pkt[3:5], "big") == scene.value
