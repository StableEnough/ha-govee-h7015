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

from protocol import (  # type: ignore[import-not-found]
    Command,
    build_packet,
    decode_state,
    pkt_brightness,
    pkt_power,
)


class TestStateDecoding:
    """Only checksum-valid AA read frames are state; the byte is the raw percent."""

    @staticmethod
    def _aa(cmd: int, value: int) -> bytes:
        return bytes(build_packet(bytes([0xAA, cmd]), bytes([value])))

    def test_aa_brightness_is_percent(self) -> None:
        assert decode_state(self._aa(Command.BRIGHTNESS, 37)).brightness == 37

    def test_aa_power(self) -> None:
        assert decode_state(self._aa(Command.POWER, 1)).power is True
        assert decode_state(self._aa(Command.POWER, 0)).power is False

    def test_command_acknowledgements_are_not_state(self) -> None:
        for ack in (pkt_power(True), pkt_brightness(37)):
            st = decode_state(bytes(ack))
            assert (st.power, st.brightness) == (None, None)


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

    def test_scene_segment_and_catalogue_match(self) -> None:
        standalone = self._load_standalone()
        integration = self._load_integration_protocol()
        assert [(s.name, s.value) for s in standalone.Scene] == [
            (s.name, s.value) for s in integration.Scene
        ]
        for s_scene, i_scene in zip(standalone.Scene, integration.Scene, strict=True):
            assert standalone.pkt_scene(s_scene) == integration.pkt_scene(i_scene)
        for bulb in range(standalone.BULB_COUNT):
            assert standalone.pkt_segment(bulb, 1, 2, 3) == integration.pkt_segment(bulb, 1, 2, 3)
        assert standalone.pkt_keepalive() == integration.pkt_keepalive()

    def test_decode_state_matches(self) -> None:
        standalone = self._load_standalone()
        integration = self._load_integration_protocol()
        frames = [
            bytes(standalone.build_packet(b"\xaa\x01", b"\x01")),
            bytes(standalone.build_packet(b"\xaa\x04", b"\x32")),
            bytes(standalone.pkt_power(True)),
            bytes(standalone.build_packet(b"\xab\x01", b"\x01")),
        ]
        for frame in frames:
            s, i = standalone.decode_state(frame), integration.decode_state(frame)
            assert (s.power, s.brightness, s.rgb, s.raw) == (i.power, i.brightness, i.rgb, i.raw)
