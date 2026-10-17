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
    parse_commands,
)
from pydantic import ValidationError


class TestParseCommands:
    """Test both HA-native and explicit command payloads."""

    def _parse(self, data: dict) -> object:
        return parse_commands(json.dumps(data).encode())[0]

    def test_power_on(self) -> None:
        cmd = self._parse({"state": "ON"})
        assert isinstance(cmd, PowerCommand)
        assert cmd.value is True

    def test_power_off(self) -> None:
        cmd = self._parse({"state": "OFF"})
        assert isinstance(cmd, PowerCommand)
        assert cmd.value is False

    def test_brightness_full_scale_matches_discovery(self) -> None:
        cmd = self._parse({"brightness": 100})
        assert isinstance(cmd, BrightnessCommand)
        assert cmd.value == 100

    def test_brightness_mid_scale_is_preserved(self) -> None:
        cmd = self._parse({"brightness": 50})
        assert isinstance(cmd, BrightnessCommand)
        assert cmd.value == 50

    def test_color_with_nested_rgb(self) -> None:
        cmd = self._parse({"color": {"r": 255, "g": 0, "b": 0}})
        assert isinstance(cmd, ColorCommand)
        assert (cmd.r, cmd.g, cmd.b) == (255, 0, 0)
        assert cmd.brightness is None

    def test_color_with_brightness(self) -> None:
        commands = parse_commands(b'{"color":{"r":100,"g":200,"b":50},"brightness":50}')
        assert commands == [
            ColorCommand(r=100, g=200, b=50),
            BrightnessCommand(value=50),
        ]

    def test_state_and_brightness_are_both_returned(self) -> None:
        commands = parse_commands(b'{"state":"ON","brightness":50}')
        assert len(commands) == 2
        assert isinstance(commands[0], PowerCommand)
        assert commands[0].value is True
        assert isinstance(commands[1], BrightnessCommand)
        assert commands[1].value == 50

    def test_scene_effect(self) -> None:
        cmd = self._parse({"effect": "rainbow"})
        assert isinstance(cmd, SceneCommand)
        assert cmd.name == "rainbow"

    def test_effect_retains_power_and_brightness(self) -> None:
        commands = parse_commands(b'{"state":"OFF","effect":"rainbow","brightness":50}')
        assert commands == [
            PowerCommand(value=False),
            SceneCommand(name="rainbow"),
            BrightnessCommand(value=50),
        ]

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

    def test_empty_payload_has_no_commands(self) -> None:
        assert parse_commands(b"{}") == []

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
            parse_commands(b"not json at all")


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
            HANativePayload(brightness=101)


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


async def test_bridge_disconnects_when_offline_publish_fails() -> None:
    from unittest.mock import patch

    from mqtt_bridge import BridgeSettings, DeviceBridge, StateCache
    from protocol import H7015State

    class FakeClient:
        def __init__(self) -> None:
            self.is_connected = True
            self.disconnect_calls = 0

        async def connect(self) -> None:
            pass

        async def poll_state(self) -> H7015State:
            self.is_connected = False
            return H7015State(power=True)

        async def disconnect(self) -> None:
            self.is_connected = False
            self.disconnect_calls += 1

    class FakeMqtt:
        async def publish(self, topic: str, payload: str, **kwargs: object) -> None:
            if payload == "offline":
                raise RuntimeError("simulated unavailable broker")

    client = FakeClient()
    bridge = DeviceBridge(
        DeviceConfig(mac="AA:BB:CC:DD:EE:FF", name="Review"),
        BridgeSettings(poll_interval=0, _env_file=None),
        FakeMqtt(),
        StateCache(None),
    )
    with (
        patch("mqtt_bridge.GoveeH7015Client", return_value=client),
        pytest.raises(RuntimeError, match="simulated unavailable broker"),
    ):
        await bridge.run()
    assert not client.is_connected
    assert client.disconnect_calls == 1


async def test_main_propagates_bridge_task_failure() -> None:
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from mqtt_bridge import BridgeSettings, DeviceBridge, main_async

    settings = BridgeSettings(devices_raw="AA:BB:CC:DD:EE:FF=Review", _env_file=None)
    mqtt = SimpleNamespace(publish=AsyncMock())

    async def fail_run(self: DeviceBridge) -> None:
        raise RuntimeError("simulated bridge task failure")

    async def wait_for_shutdown(client, bridges, settings, stop_event, task_done) -> None:
        for bridge in bridges:
            bridge.start().add_done_callback(task_done)
        await stop_event.wait()

    with (
        patch("mqtt_bridge.build_settings", return_value=settings),
        patch("mqtt_bridge.AioMqttClient", return_value=mqtt),
        patch("mqtt_bridge.mqtt_subscriber", wait_for_shutdown),
        patch.object(DeviceBridge, "run", fail_run),
        pytest.raises(RuntimeError, match="simulated bridge task failure"),
    ):
        await asyncio.wait_for(main_async(SimpleNamespace(env_file=None)), timeout=2)


async def test_bridge_dispatches_combined_power_and_brightness() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from mqtt_bridge import BridgeSettings, DeviceBridge, StateCache
    from protocol import H7015State

    client = SimpleNamespace(
        set_power=AsyncMock(),
        set_brightness=AsyncMock(),
        poll_state=AsyncMock(return_value=H7015State(power=True, brightness=50)),
    )
    bridge = DeviceBridge(
        DeviceConfig(mac="AA:BB:CC:DD:EE:FF", name="Review"),
        BridgeSettings(poll_interval=0, _env_file=None),
        SimpleNamespace(publish=AsyncMock()),
        StateCache(None),
    )
    bridge._client = client

    await bridge.handle_command(b'{"state":"ON","brightness":50}')

    client.set_power.assert_awaited_once_with(True)
    client.set_brightness.assert_awaited_once_with(50)


async def test_discovery_brightness_scale_round_trips_to_full_brightness() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from mqtt_bridge import BridgeSettings, DeviceBridge, StateCache

    mqtt = SimpleNamespace(publish=AsyncMock())
    bridge = DeviceBridge(
        DeviceConfig(mac="AA:BB:CC:DD:EE:FF", name="Review"),
        BridgeSettings(_env_file=None),
        mqtt,
        StateCache(None),
    )

    await bridge.publish_discovery()

    discovery = json.loads(mqtt.publish.await_args.args[1])
    command = parse_commands(json.dumps({"brightness": discovery["brightness_scale"]}).encode())[0]
    assert discovery["brightness_scale"] == 100
    assert isinstance(command, BrightnessCommand)
    assert command.value == 100


@pytest.mark.parametrize("connected", [False, True])
async def test_broker_reconnect_publishes_current_ble_availability(connected: bool) -> None:
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from mqtt_bridge import BridgeSettings, DeviceBridge, StateCache, mqtt_subscriber

    stop = asyncio.Event()

    class Broker:
        publish = AsyncMock()
        subscribe = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        @property
        def messages(self):
            async def messages():
                stop.set()
                yield SimpleNamespace(topic="unrelated", payload=b"{}")

            return messages()

    broker = Broker()
    bridge = DeviceBridge(
        DeviceConfig(mac="AA:BB:CC:DD:EE:FF", name="Review"),
        BridgeSettings(_env_file=None),
        broker,
        StateCache(None),
    )
    bridge._client = SimpleNamespace(is_connected=connected)
    bridge._task = asyncio.get_running_loop().create_future()
    await mqtt_subscriber(broker, [bridge], bridge.settings, stop, lambda task: None)
    availability = [
        call.args[1]
        for call in broker.publish.await_args_list
        if call.args[0] == bridge.avail_topic
    ]
    assert availability == ["online" if connected else "offline"]
    bridge._task.cancel()


async def test_state_publish_failure_remains_retryable() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from mqtt_bridge import BridgeSettings, DeviceBridge, StateCache
    from protocol import H7015State

    mqtt = SimpleNamespace(publish=AsyncMock(side_effect=[RuntimeError("broker down"), None, None]))
    bridge = DeviceBridge(
        DeviceConfig(mac="AA:BB:CC:DD:EE:FF", name="Review"),
        BridgeSettings(_env_file=None),
        mqtt,
        StateCache(None),
    )
    state = H7015State(power=True, brightness=50)
    with pytest.raises(RuntimeError, match="broker down"):
        await bridge.publish_state(state)
    await bridge.publish_state(state)
    await bridge.publish_state(state)
    calls = mqtt.publish.await_args_list
    assert [call.args[0] for call in calls] == [
        bridge.state_topic,
        bridge.state_topic,
        bridge.attributes_topic,
    ]
    assert json.loads(calls[1].args[1])["brightness"] == 50


@pytest.mark.parametrize("mireds", [154, 370, 500])
async def test_color_temperature_command_survives_readback_and_publication(mireds: int) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from govee_h7015 import GoveeH7015Client
    from mqtt_bridge import BridgeSettings, DeviceBridge, StateCache

    client = GoveeH7015Client("AA:BB:CC:DD:EE:FF", keepalive=False)
    client._client = SimpleNamespace(
        is_connected=True,
        write_gatt_char=AsyncMock(),
    )
    mqtt = SimpleNamespace(publish=AsyncMock())
    bridge = DeviceBridge(
        DeviceConfig(mac="AA:BB:CC:DD:EE:FF", name="Review"),
        BridgeSettings(_env_file=None),
        mqtt,
        StateCache(None),
    )
    bridge._client = client
    await bridge.handle_command(
        json.dumps({"state": "ON", "color_temp": mireds, "brightness": 50}).encode()
    )
    published = json.loads(mqtt.publish.await_args_list[0].args[1])
    assert published["state"] == "ON"
    assert published["brightness"] == 50
    assert published["color_mode"] == "color_temp"
    assert published["color_temp"] == mireds
    assert client.state.mode == f"color_temp:{round(1000000 / mireds)}"


@pytest.mark.parametrize("mireds", [0, 153, 501])
def test_color_temperature_rejects_out_of_range_input(mireds: int) -> None:
    with pytest.raises(ValidationError):
        parse_commands(json.dumps({"state": "ON", "color_temp": mireds}).encode())
