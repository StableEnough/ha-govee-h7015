"""Mock BLE client for testing without real hardware.

Provides a fake BLE client that simulates the H7015's behavior, so the
integration can be tested without owning the device. Useful for:
- Testing the Lovelace card UI
- CI testing of the full integration
- Demoing the integration to potential users
- Developing new features without BLE access

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
READ_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b10"


class MockH7015Client:
    """Simulates the H7015 BLE device for testing.

    Tracks internal state (power, brightness, color) and responds to
    read/write GATT characteristic operations just like the real device.
    """

    def __init__(self, _ble_device: Any = None) -> None:
        self._connected = False
        self._power = False
        self._brightness_raw = 0x00
        self._rgb: tuple[int, int, int] = (255, 255, 255)
        self._mode = 0x02  # manual
        self._write_count = 0

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

    async def write_gatt_char(
        self, char_uuid: str, data: bytes, *, response: bool = True
    ) -> None:
        """Process a write just like the real H7015 would."""
        if not self._connected:
            raise ConnectionError("not connected")
        if char_uuid != WRITE_CHAR_UUID:
            return

        self._write_count += 1
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
            if sub_mode == 0x02 and len(data) >= 6:  # Manual
                self._mode = 0x02
                self._rgb = (data[3], data[4], data[5])
                _LOGGER.debug("MockH7015: color=rgb(%d,%d,%d)", *self._rgb)
            elif sub_mode == 0x04:  # Scene
                self._mode = 0x04
                _LOGGER.debug("MockH7015: scene=0x%02x", data[3])
            elif sub_mode == 0x01:  # Music
                self._mode = 0x01
                _LOGGER.debug("MockH7015: music=0x%02x", data[3])
            elif sub_mode == 0x0B:  # Segments
                self._mode = 0x0B
                _LOGGER.debug("MockH7015: segment rgb(%d,%d,%d)", data[3], data[4], data[5])

        elif cmd == 0x14:  # Gradient
            _LOGGER.debug("MockH7015: gradient=%s", bool(data[2]))

    async def read_gatt_char(self, char_uuid: str) -> bytes:
        """Return a state packet mimicking the real device's read characteristic."""
        if not self._connected:
            raise ConnectionError("not connected")
        if char_uuid != READ_CHAR_UUID:
            return b""

        # Build a state response based on current mode
        if self._mode == 0x02:  # manual
            raw = bytes([0x33, 0x05, 0x02, *self._rgb]) + b"\x00" * 13
        elif self._mode == 0x04:  # scene
            raw = bytes([0x33, 0x05, 0x04, 0x00]) + b"\x00" * 15
        else:
            raw = bytes([0x33, 0x01, 0x01 if self._power else 0x00]) + b"\x00" * 16

        # Add checksum
        checksum = 0
        for b in raw:
            checksum ^= b
        raw += bytes([checksum])

        _LOGGER.debug("MockH7015: TX %s", raw.hex())
        return raw

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
