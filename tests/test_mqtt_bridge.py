"""Tests for the MQTT bridge's pydantic models and command parsing.

These tests don't require a running MQTT broker or BLE device — they
exercise the pure pydantic models in models.py.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "standalone"))

# Mock out aiomqtt and dotenv so the bridge module imports cleanly.
if "aiomqtt" not in sys.modules:
    aiomqtt = types.ModuleType("aiomqtt")

    class _DummyMqttError(Exception):
        pass

    class _DummyClient:
        pass

    aiomqtt.Client = _DummyClient
    aiomqtt.MqttError = _DummyMqttError
    sys.modules["aiomqtt"] = aiomqtt

if "dotenv" not in sys.modules:
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *a, **kw: False
    dotenv.dotenv_values = lambda *a, **kw: {}
    sys.modules["dotenv"] = dotenv

import pytest
from pydantic import ValidationError

from models import (
    BrightnessCommand,
    ColorCommand,
    DeviceConfig,
    DeviceState,
    HANativePayload,
    MusicCommand,
    PowerCommand,
    SceneCommand,
    SegmentCommand,
    parse_command,
)


class TestParseCommand:
    """Test the parse_command entry point with both HA-native and explicit formats."""

    def _parse(self, data: dict) -> object:
        return parse_command(json.dumps(data).encode())

    def test_power_on(self) -> None:
        cmd = self._parse({"state": "ON"})
        assert isinstance(cmd, PowerCommand)
        assert cmd.value is True

    def test_power_off(self) -> None:
        cmd = self._parse({"state": "OFF"})
        assert isinstance(cmd, PowerCommand)
        assert cmd.value is False

    def test_brightness_scales_255_to_100(self) -> None:
        cmd = self._parse({"brightness": 255})
        assert isinstance(cmd, BrightnessCommand)
        assert cmd.value == 100

    def test_brightness_128_scales_to_50(self) -> None:
        cmd = self._parse({"brightness": 128})
        assert isinstance(cmd, BrightnessCommand)
        assert cmd.value == 50

    def test_color_with_nested_rgb(self) -> None:
        cmd = self._parse({"color": {"r": 255, "g": 0, "b": 0}})
        assert isinstance(cmd, ColorCommand)
        assert (cmd.r, cmd.g, cmd.b) == (255, 0, 0)
        assert cmd.brightness is None

    def test_color_with_brightness(self) -> None:
        cmd = self._parse(
            {"color": {"r": 100, "g": 200, "b": 50}, "brightness": 128}
        )
        assert isinstance(cmd, ColorCommand)
        assert (cmd.r, cmd.g, cmd.b) == (100, 200, 50)
        assert cmd.brightness == 50

    def test_scene_effect(self) -> None:
        cmd = self._parse({"effect": "rainbow"})
        assert isinstance(cmd, SceneCommand)
        assert cmd.name == "rainbow"

    def test_music_effect(self) -> None:
        cmd = self._parse({"effect": "music_rhythm"})
        assert isinstance(cmd, MusicCommand)
        assert cmd.name == "rhythm"

    def test_explicit_power_command(self) -> None:
        cmd = self._parse({"cmd": "power", "value": False})
        assert isinstance(cmd, PowerCommand)
        assert cmd.value is False

    def test_explicit_segment_command(self) -> None:
        cmd = self._parse({"cmd": "segment", "bulb": 0, "r": 255, "g": 0, "b": 0})
        assert isinstance(cmd, SegmentCommand)
        assert cmd.bulb == 0

    def test_empty_payload_returns_none(self) -> None:
        assert self._parse({}) is None

    def test_invalid_brightness_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._parse({"cmd": "brightness", "value": 200})

    def test_invalid_color_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._parse({"cmd": "color", "r": 300, "g": 0, "b": 0})

    def test_invalid_bulb_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._parse({"cmd": "segment", "bulb": 15, "r": 0, "g": 0, "b": 0})

    def test_unknown_cmd_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown cmd"):
            self._parse({"cmd": "frobnicate"})

    def test_bad_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            parse_command(b"not json at all")


class TestHANativePayload:
    """Test the HANativePayload model directly."""

    def test_extra_fields_ignored(self) -> None:
        p = HANativePayload(state="ON", extra_field="ignored")
        assert p.state == "ON"

    def test_invalid_state_raises(self) -> None:
        with pytest.raises(ValidationError):
            HANativePayload(state="MAYBE")

    def test_brightness_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            HANativePayload(brightness=300)


class TestDeviceConfig:
    def test_valid_mac_uppercase(self) -> None:
        d = DeviceConfig(mac="AA:BB:CC:DD:EE:FF", name="Patio")
        assert d.mac == "AA:BB:CC:DD:EE:FF"
        assert d.device_id == "AABBCCDDEEFF"

    def test_valid_mac_lowercase_normalized(self) -> None:
        d = DeviceConfig(mac="aabbccddeeff", name="Patio")
        assert d.mac == "AA:BB:CC:DD:EE:FF"

    def test_valid_mac_with_dashes(self) -> None:
        d = DeviceConfig(mac="AA-BB-CC-DD-EE-FF", name="Patio")
        assert d.mac == "AA:BB:CC:DD:EE:FF"

    def test_invalid_mac_raises(self) -> None:
        with pytest.raises(ValidationError):
            DeviceConfig(mac="not-a-mac", name="Patio")

    def test_frozen(self) -> None:
        d = DeviceConfig(mac="AA:BB:CC:DD:EE:FF", name="Patio")
        with pytest.raises(ValidationError):
            d.mac = "11:22:33:44:55:66"  # type: ignore[misc]


class TestDeviceState:
    def test_valid_state(self) -> None:
        s = DeviceState(state="ON", brightness=50)
        assert s.state == "ON"
        assert s.brightness == 50

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            DeviceState(state="ON", unexpected="field")

    def test_brightness_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            DeviceState(state="ON", brightness=200)


class TestStateCacheDedup:
    """State cache should not write when the state hasn't changed."""

    def test_state_cache_skips_unchanged(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "state.json"
        cache_file.write_text(json.dumps({"AABBCCDDEEFF": {"state": "ON"}}))

        # Import here so the aiomqtt mock doesn't interfere
        from mqtt_bridge import StateCache  # type: ignore[import-not-found]

        cache = StateCache(cache_file)
        before = cache_file.read_text()
        cache.save("AABBCCDDEEFF", {"state": "ON"})
        after = cache_file.read_text()
        assert before == after

    def test_state_cache_writes_on_change(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "state.json"
        cache_file.write_text(json.dumps({"AABBCCDDEEFF": {"state": "ON"}}))

        from mqtt_bridge import StateCache  # type: ignore[import-not-found]

        cache = StateCache(cache_file)
        cache.save("AABBCCDDEEFF", {"state": "OFF"})
        data = json.loads(cache_file.read_text())
        assert data["AABBCCDDEEFF"]["state"] == "OFF"
