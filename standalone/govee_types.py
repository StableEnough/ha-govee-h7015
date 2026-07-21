"""Type-safe primitives for the Govee H7015 protocol.

Uses NewType to prevent stringly-typed MAC addresses and raw bytes from
being mixed up, and a Protocol for the BLE client so the coordinator is
testable without a real radio.

Note: NewType provides compile-time type safety only — no runtime validation.
For runtime-validated models, see models.py (pydantic).
"""

from __future__ import annotations

from typing import NewType, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# NewType — compile-time type safety (no runtime validation)
# ---------------------------------------------------------------------------
MacAddress = NewType("MacAddress", str)
"""A Bluetooth MAC address in AA:BB:CC:DD:EE:FF form.

Note: NewType provides NO runtime validation. Use DeviceConfig in models.py
for validated MAC addresses.
"""

RawPacket = NewType("RawPacket", bytes)
"""A 20-byte Govee protocol packet.

Note: NewType provides NO runtime validation. Use validate_packet() in
protocol.py to verify the checksum before constructing a RawPacket.
"""


# ---------------------------------------------------------------------------
# Protocol — the BLE client interface the coordinator depends on
# ---------------------------------------------------------------------------
@runtime_checkable
class BleClient(Protocol):
    """Minimal BLE client interface.

    This lets us mock the coordinator in tests without importing bleak.
    """

    @property
    def is_connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def write_gatt_char(self, char_uuid: str, data: bytes, *, response: bool) -> None: ...

    async def read_gatt_char(self, char_uuid: str) -> bytes: ...


# ---------------------------------------------------------------------------
# Type aliases (PEP 695 syntax, Python 3.12+)
# ---------------------------------------------------------------------------
type RGB = tuple[int, int, int]
"""An (r, g, b) triple, each 0..255."""

type BulbIndex = int
"""A bulb index 0..14 on the H7015 string."""
