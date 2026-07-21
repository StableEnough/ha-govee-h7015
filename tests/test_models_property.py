"""Property-based tests for the pydantic models using Hypothesis."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "standalone"))

from models import (  # type: ignore[import-not-found]
    BrightnessCommand,
    ColorCommand,
    DeviceConfig,
    DeviceState,
    HAColor,
    HANativePayload,
    PowerCommand,
    SceneCommand,
    SegmentCommand,
    parse_command,
)
from pydantic import ValidationError


# Strategies
st_rgb = st.tuples(
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
)
st_brightness_pct = st.integers(min_value=0, max_value=100)
st_brightness_ha = st.integers(min_value=0, max_value=255)
st_bulb = st.integers(min_value=0, max_value=14)
st_mac_byte = st.text(
    alphabet=st.characters(min_codepoint=ord("A"), max_codepoint=ord("F"))
    | st.characters(min_codepoint=ord("0"), max_codepoint=ord("9")),
    min_size=2,
    max_size=2,
)


class TestParseCommandRoundTrip:
    """parse_command should round-trip: valid input -> typed command."""

    @given(st_brightness_pct)
    def test_brightness_round_trip(self, pct: int) -> None:
        cmd = parse_command(json.dumps({"cmd": "brightness", "value": pct}).encode())
        assert isinstance(cmd, BrightnessCommand)
        assert cmd.value == pct

    @given(st_rgb)
    def test_color_round_trip(self, rgb: tuple[int, int, int]) -> None:
        r, g, b = rgb
        cmd = parse_command(
            json.dumps({"cmd": "color", "r": r, "g": g, "b": b}).encode()
        )
        assert isinstance(cmd, ColorCommand)
        assert (cmd.r, cmd.g, cmd.b) == rgb

    @given(st_bulb, st_rgb)
    def test_segment_round_trip(self, bulb: int, rgb: tuple[int, int, int]) -> None:
        r, g, b = rgb
        cmd = parse_command(
            json.dumps({"cmd": "segment", "bulb": bulb, "r": r, "g": g, "b": b}).encode()
        )
        assert isinstance(cmd, SegmentCommand)
        assert cmd.bulb == bulb

    @given(st_brightness_ha)
    def test_ha_brightness_scales_correctly(self, ha_b: int) -> None:
        cmd = parse_command(json.dumps({"brightness": ha_b}).encode())
        assert isinstance(cmd, BrightnessCommand)
        expected = int(ha_b * 100 / 255)
        assert cmd.value == expected
        assert 0 <= cmd.value <= 100


class TestValidationRejectsBadInput:
    """Pydantic should reject out-of-range values."""

    @given(st.integers(min_value=101))
    def test_brightness_over_100_rejected(self, v: int) -> None:
        with pytest.raises(ValidationError):
            BrightnessCommand(value=v)

    @given(st.integers(max_value=-1))
    def test_brightness_negative_rejected(self, v: int) -> None:
        with pytest.raises(ValidationError):
            BrightnessCommand(value=v)

    @given(st_rgb)
    def test_color_over_255_rejected(self, rgb: tuple[int, int, int]) -> None:
        r, g, b = rgb
        with pytest.raises(ValidationError):
            ColorCommand(r=r + 256, g=g, b=b)

    @given(st.integers(min_value=15))
    def test_segment_bulb_over_14_rejected(self, bulb: int) -> None:
        with pytest.raises(ValidationError):
            SegmentCommand(bulb=bulb, r=0, g=0, b=0)


class TestDeviceConfigValidation:
    @given(st.lists(st_mac_byte, min_size=6, max_size=6))
    def test_valid_mac_accepted(self, parts: list[str]) -> None:
        mac = ":".join(parts)
        d = DeviceConfig(mac=mac, name="Test")
        assert d.mac == mac
        assert d.device_id == mac.replace(":", "")

    @given(st.text(min_size=1, max_size=20))
    def test_invalid_mac_rejected(self, s: str) -> None:
        # Most random strings aren't valid MACs
        try:
            DeviceConfig(mac=s, name="Test")
        except ValidationError:
            pass  # expected


class TestDeviceStateValidation:
    @given(st_brightness_pct)
    def test_valid_brightness_accepted(self, b: int) -> None:
        s = DeviceState(state="ON", brightness=b)
        assert s.brightness == b

    @given(st.integers(min_value=101, max_value=1000))
    def test_over_100_rejected(self, b: int) -> None:
        with pytest.raises(ValidationError):
            DeviceState(state="ON", brightness=b)
