"""Tests for the HA integration's protocol module.

Same as test_protocol.py but imports from the integration's protocol.py
to make sure the duplicated copy stays in sync.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add standalone/ to sys.path so we can `import protocol` directly.
# The standalone copy uses absolute imports; the integration copy uses
# relative imports and must be loaded via importlib to avoid triggering
# __init__.py (which imports HA deps).
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "standalone"))

import pytest

from protocol import (  # type: ignore[import-not-found]
    Command,
    Scene,
    decode_state,
    pkt_brightness,
    pkt_power,
    pkt_solid_color,
)


class TestBrightnessRoundTrip:
    """The bug we fixed: brightness unit must be consistent between
    command (0..100 percent) and polled state (raw byte 0x14..0xFE)."""

    @pytest.mark.parametrize("pct", [1, 25, 50, 75, 100])
    def test_round_trip_brightness(self, pct: int) -> None:
        """Send brightness X%, poll raw byte, decode back to X%."""
        # Build the command packet to find out what raw byte gets sent
        pkt = pkt_brightness(pct)
        raw_byte = pkt[2]

        # Simulate the device echoing back a state packet with that raw byte
        state_pkt = bytes([0x33, Command.BRIGHTNESS, raw_byte]) + b"\x00" * 16
        state_pkt += bytes([0])  # checksum doesn't matter for decode_state

        st = decode_state(state_pkt)
        assert st.brightness is not None
        # Should be within 1 percentage point (rounding)
        assert abs(st.brightness - pct) <= 1, (
            f"round-trip failed: sent {pct}%, raw=0x{raw_byte:02x}, "
            f"decoded={st.brightness}%"
        )

    def test_brightness_zero_round_trip(self) -> None:
        """0% (off) should round-trip to 0%."""
        pkt = pkt_brightness(0)
        assert pkt[2] == 0x00
        state_pkt = bytes([0x33, Command.BRIGHTNESS, 0x00]) + b"\x00" * 17
        st = decode_state(state_pkt)
        assert st.brightness == 0


class TestPowerDecoding:
    def test_power_on_state(self) -> None:
        raw = bytes([0x33, Command.POWER, 0x01]) + b"\x00" * 17
        st = decode_state(raw)
        assert st.power is True

    def test_power_off_state(self) -> None:
        raw = bytes([0x33, Command.POWER, 0x00]) + b"\x00" * 17
        st = decode_state(raw)
        assert st.power is False


class TestColorDecoding:
    def test_color_state(self) -> None:
        raw = bytes([0x33, Command.COLOR, 0x02, 0xFF, 0x80, 0x00]) + b"\x00" * 14
        st = decode_state(raw)
        assert st.rgb == (0xFF, 0x80, 0x00)


class TestStandaloneAndIntegrationInSync:
    """Verify the standalone and integration protocol modules produce
    identical packets. Catches drift between the two copies."""

    @staticmethod
    def _load_integration_protocol():
        """Load the integration's protocol.py without triggering __init__.py.

        The integration's protocol.py uses relative imports (from .exceptions,
        from .govee_types). We rewrite those to absolute imports on the fly
        and exec the module directly. This is hacky but lets us verify the
        protocol logic matches without needing Home Assistant installed.
        """
        import importlib.util
        import re

        path = ROOT / "custom_components" / "govee_h7015_ble" / "protocol.py"
        source = path.read_text()
        # Rewrite relative imports to absolute
        source = re.sub(
            r"from \.exceptions import",
            "from exceptions import",
            source,
        )
        source = re.sub(
            r"from \.govee_types import",
            "from govee_types import",
            source,
        )

        spec = importlib.util.spec_from_loader("intg_protocol", loader=None)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["intg_protocol"] = mod
        exec(compile(source, str(path), "exec"), mod.__dict__)
        return mod

    @staticmethod
    def _load_standalone():
        if "protocol" in sys.modules:
            del sys.modules["protocol"]
        import protocol as standalone  # type: ignore[import-not-found]
        return standalone

    def test_power_packets_match(self) -> None:
        standalone = self._load_standalone()
        integration = self._load_integration_protocol()
        assert standalone.pkt_power(True) == integration.pkt_power(True)
        assert standalone.pkt_power(False) == integration.pkt_power(False)

    def test_brightness_packets_match(self) -> None:
        standalone = self._load_standalone()
        integration = self._load_integration_protocol()
        for v in [0, 1, 25, 50, 75, 100]:
            assert standalone.pkt_brightness(v) == integration.pkt_brightness(v), (
                f"brightness {v}% diverges"
            )

    def test_color_packets_match(self) -> None:
        standalone = self._load_standalone()
        integration = self._load_integration_protocol()
        for rgb in [(0, 0, 0), (255, 255, 255), (128, 64, 32)]:
            assert standalone.pkt_solid_color(*rgb) == integration.pkt_solid_color(*rgb)
