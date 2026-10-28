"""Mock BLE client for testing without real hardware.

Provides a fake BLE client for integration tests without a radio. Its state
model is a test convenience, not independently verified hardware behavior.

Usage in tests:
    from tests.mock_h7015 import MockH7015Client

    # Patch the coordinator's _build_client to return a mock
    with patch.object(H7015Coordinator, "_build_client", return_value=MockH7015Client()):
        ...
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# GATT endpoints (same as real device)
WRITE_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"


class MockH7015Client:
    """Model command handling and notification delivery for software tests.

    The mock does not establish which responses physical H7015 firmware emits.
    """

    def __init__(self, _ble_device: Any = None) -> None:
        self._connected = False
        self._power = False
        self._brightness_raw = 0x00
        self._rgb: tuple[int, int, int] = (255, 255, 255)
        self._mode = 0x02  # manual
        self._write_count = 0
        self._notify_callback: Any = None
        self.events: list[str] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        _LOGGER.debug("MockH7015: connect()")
        self._connected = True
        await asyncio.sleep(0.01)  # simulate connect latency

    async def disconnect(self) -> None:
        _LOGGER.debug("MockH7015: disconnect()")
        self._connected = False

    async def write_gatt_char(self, char_uuid: str, data: bytes, *, response: bool = True) -> None:
        """Model supported command fields without generating hardware readback."""
        if not self._connected:
            raise ConnectionError("not connected")
        if char_uuid != WRITE_CHAR_UUID:
            return

        self._write_count += 1
        self.events.append("write")
        _LOGGER.debug("MockH7015: RX %s (write #%d)", data.hex(), self._write_count)

        if len(data) < 3:
            return

        prefix = data[0]

        if prefix == 0xAA:
            # Keepalive — just acknowledge
            return

        if prefix != 0x33:
            return

        cmd = data[1]

        if cmd == 0x01:  # Power
            self._power = bool(data[2])
            _LOGGER.debug("MockH7015: power=%s", self._power)

        elif cmd == 0x04:  # Brightness
            self._brightness_raw = data[2]
            _LOGGER.debug("MockH7015: brightness=0x%02x", self._brightness_raw)

        elif cmd == 0x05:  # Color
            sub_mode = data[2]
            if sub_mode == 0x15 and len(data) == 20 and data[3] == 0x01:
                self._mode = 0x15
                if data[12:14] == b"\xff\x7f":
                    self._rgb = (data[4], data[5], data[6])
            elif sub_mode == 0x02 and len(data) >= 6:  # Legacy, unverified
                self._mode = 0x02
                self._rgb = (data[3], data[4], data[5])
                _LOGGER.debug("MockH7015: color=rgb(%d,%d,%d)", *self._rgb)
            elif sub_mode == 0x04:  # Scene
                self._mode = 0x04
                _LOGGER.debug("MockH7015: scene=%d", int.from_bytes(data[3:5], "big"))
            elif sub_mode == 0x01:  # Music
                self._mode = 0x01
                _LOGGER.debug("MockH7015: music=0x%02x", data[3])
            elif sub_mode == 0x0B:  # Segments
                self._mode = 0x0B
                _LOGGER.debug("MockH7015: segment rgb(%d,%d,%d)", data[3], data[4], data[5])

        elif cmd == 0x14:  # Gradient
            _LOGGER.debug("MockH7015: gradient=%s", bool(data[2]))

    async def start_notify(self, char_uuid: str, callback: Any) -> None:
        """Record a notification subscription (only the write/notify char exists)."""
        if not self._connected:
            raise ConnectionError("not connected")
        if char_uuid != WRITE_CHAR_UUID:
            raise ValueError(f"no notify characteristic {char_uuid}")
        self._notify_callback = callback
        self.events.append("start_notify")

    def notify(self, data: bytes) -> None:
        """Deliver a device-originated notification frame to the subscriber."""
        assert self._notify_callback is not None, "not subscribed"
        self._notify_callback(None, bytearray(data))

    @property
    def mock_power(self) -> bool:
        """Get the mock device's power state (for test assertions)."""
        return self._power

    @property
    def mock_brightness_raw(self) -> int:
        """Get the mock device's raw brightness byte."""
        return self._brightness_raw

    @property
    def mock_rgb(self) -> tuple[int, int, int]:
        """Get the mock device's RGB color."""
        return self._rgb

    @property
    def mock_write_count(self) -> int:
        """Get the total number of GATT writes received."""
        return self._write_count


async def build_mock_client(ble_device: Any = None) -> MockH7015Client:
    """Factory that creates and connects a mock client.

    Use as a drop-in replacement for the coordinator's _build_client:
        with patch.object(H7015Coordinator, "_build_client", side_effect=build_mock_client):
            ...
    """
    client = MockH7015Client(ble_device)
    await client.connect()
    return client
