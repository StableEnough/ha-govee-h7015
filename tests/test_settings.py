"""Tests for the BridgeSettings env var mapping.

These verify that the env vars documented in .env.example actually map to
the right fields. This would have caught the GOVEE_DEVICES → devices_raw
alias bug.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "standalone"))

# Mock optional deps
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


class TestBridgeSettingsEnvVars:
    """Verify that every env var in .env.example maps to a settings field."""

    def test_devices_env_var_loads(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """GOVEE_DEVICES should populate settings.devices_raw."""
        monkeypatch.setenv("GOVEE_DEVICES", "AABBCCDDEEFF=Patio")
        monkeypatch.setenv("GOVEE_MQTT_HOST", "broker.local")
        monkeypatch.setenv("GOVEE_MQTT_PORT", "1883")

        # Clear any cached module so it picks up the env vars
        for mod in list(sys.modules):
            if "mqtt_bridge" in mod:
                del sys.modules[mod]

        from mqtt_bridge import BridgeSettings  # type: ignore[import-not-found]

        # Don't load from .env file — use env vars only
        settings = BridgeSettings(_env_file=None)
        assert settings.devices_raw == "AABBCCDDEEFF=Patio"
        assert len(settings.devices) == 1
        assert settings.devices[0].mac == "AA:BB:CC:DD:EE:FF"
        assert settings.devices[0].name == "Patio"

    def test_all_env_vars_from_example_file(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """Every env var in .env.example should map to a settings field."""
        monkeypatch.setenv("GOVEE_MQTT_HOST", "127.0.0.1")
        monkeypatch.setenv("GOVEE_MQTT_PORT", "1883")
        monkeypatch.setenv("GOVEE_MQTT_USER", "user")
        monkeypatch.setenv("GOVEE_MQTT_PASSWORD", "secret")
        monkeypatch.setenv("GOVEE_TOPIC_PREFIX", "govee/h7015")
        monkeypatch.setenv("GOVEE_DEVICES", "AABBCCDDEEFF=Patio")
        monkeypatch.setenv("GOVEE_POLL_INTERVAL", "30")
        monkeypatch.setenv("GOVEE_RECONNECT_BACKOFF", "10")
        monkeypatch.setenv("GOVEE_LOG_LEVEL", "DEBUG")

        for mod in list(sys.modules):
            if "mqtt_bridge" in mod:
                del sys.modules[mod]

        from mqtt_bridge import BridgeSettings  # type: ignore[import-not-found]

        settings = BridgeSettings(_env_file=None)
        assert settings.mqtt_host == "127.0.0.1"
        assert settings.mqtt_port == 1883
        assert settings.mqtt_user == "user"
        assert settings.mqtt_password == "secret"
        assert settings.topic_prefix == "govee/h7015"
        assert settings.devices_raw == "AABBCCDDEEFF=Patio"
        assert settings.poll_interval == 30
        assert settings.reconnect_backoff == 10
        assert settings.log_level == "DEBUG"

    def test_invalid_port_rejected(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """Port out of range should fail at startup, not at connect time."""
        monkeypatch.setenv("GOVEE_MQTT_PORT", "99999")

        for mod in list(sys.modules):
            if "mqtt_bridge" in mod:
                del sys.modules[mod]

        from mqtt_bridge import BridgeSettings  # type: ignore[import-not-found]
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BridgeSettings(_env_file=None)

    def test_negative_poll_interval_rejected(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """Negative poll interval should fail."""
        monkeypatch.setenv("GOVEE_POLL_INTERVAL", "-5")

        for mod in list(sys.modules):
            if "mqtt_bridge" in mod:
                del sys.modules[mod]

        from mqtt_bridge import BridgeSettings  # type: ignore[import-not-found]
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BridgeSettings(_env_file=None)


# Need pytest import for the raises tests
import pytest
