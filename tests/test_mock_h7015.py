"""Tests using the mock H7015 client — no real hardware needed.

These tests verify the full coordinator → BLE → mock device round-trip
without any real Bluetooth hardware. The mock simulates the H7015's
behavior: it tracks state and responds to reads/writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "standalone"))


# Import mock client
from tests.mock_h7015 import MockH7015Client


async def test_mock_client_connect_disconnect() -> None:
    """Mock client should connect and disconnect."""
    client = MockH7015Client()
    assert not client.is_connected
    await client.connect()
    assert client.is_connected
    await client.disconnect()
    assert not client.is_connected


async def test_mock_client_power_on() -> None:
    """Writing a power-on packet should update the mock's power state."""
    client = MockH7015Client()
    await client.connect()

    # Write power-on packet: 33 01 01 00..00 33
    pkt = bytes([0x33, 0x01, 0x01]) + b"\x00" * 16 + bytes([0x33])
    await client.write_gatt_char("00010203-0405-0607-0809-0a0b0c0d2b11", pkt, response=True)

    assert client.mock_power is True


async def test_mock_client_power_off() -> None:
    """Writing a power-off packet should update the mock's power state."""
    client = MockH7015Client()
    await client.connect()

    pkt = bytes([0x33, 0x01, 0x00]) + b"\x00" * 16 + bytes([0x32])
    await client.write_gatt_char("00010203-0405-0607-0809-0a0b0c0d2b11", pkt, response=True)

    assert client.mock_power is False


async def test_mock_client_set_color() -> None:
    """Writing a color packet should update the mock's RGB state."""
    client = MockH7015Client()
    await client.connect()

    # Build a red color packet
    pkt = bytes([0x33, 0x05, 0x02, 0xFF, 0x00, 0x00]) + b"\x00" * 13
    # Compute checksum
    checksum = 0
    for b in pkt:
        checksum ^= b
    pkt += bytes([checksum])

    await client.write_gatt_char("00010203-0405-0607-0809-0a0b0c0d2b11", pkt, response=True)

    assert client.mock_rgb == (255, 0, 0)


async def test_mock_client_keepalive_ignored() -> None:
    """Keepalive packets should not change device state."""
    client = MockH7015Client()
    await client.connect()

    # Keepalive: AA 01 00..00 AB
    pkt = bytes([0xAA, 0x01]) + b"\x00" * 17 + bytes([0xAB])
    await client.write_gatt_char("00010203-0405-0607-0809-0a0b0c0d2b11", pkt, response=False)

    # State should be unchanged (power stays False from init)
    assert client.mock_power is False
    assert client.mock_write_count == 1


async def test_mock_client_notify_delivers_frames_and_has_no_read_char() -> None:
    """Notifications reach the subscriber; there is no readable state characteristic."""
    client = MockH7015Client()
    await client.connect()
    got: list[bytes] = []
    await client.start_notify(
        "00010203-0405-0607-0809-0a0b0c0d2b11", lambda _c, d: got.append(bytes(d))
    )
    frame = bytes([0xAB]) + b"\x00" * 19
    client.notify(frame)
    assert got == [frame]
    assert not hasattr(client, "read_gatt_char")


async def test_mock_client_write_count() -> None:
    """The mock should track the total number of writes."""
    client = MockH7015Client()
    await client.connect()

    assert client.mock_write_count == 0

    # Write 3 packets
    for _ in range(3):
        pkt = bytes([0xAA, 0x01]) + b"\x00" * 17 + bytes([0xAB])
        await client.write_gatt_char("00010203-0405-0607-0809-0a0b0c0d2b11", pkt, response=False)

    assert client.mock_write_count == 3


async def test_mock_client_not_connected_raises() -> None:
    """Writing when not connected should raise."""
    client = MockH7015Client()

    with pytest.raises(ConnectionError):
        await client.write_gatt_char(
            "00010203-0405-0607-0809-0a0b0c0d2b11", b"\x00" * 20, response=True
        )


async def test_mock_client_disconnect_then_write_raises() -> None:
    """Writing after disconnect should raise."""
    client = MockH7015Client()
    await client.connect()
    await client.disconnect()

    with pytest.raises(ConnectionError):
        await client.write_gatt_char(
            "00010203-0405-0607-0809-0a0b0c0d2b11", b"\x00" * 20, response=True
        )
