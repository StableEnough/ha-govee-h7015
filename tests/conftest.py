"""Pytest configuration for HA integration tests.

The root conftest.py handles sys.path setup. This file only adds the
auto_enable_custom_integrations fixture required by HA test framework.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in HA test mode.

    Autouse is required for HA integration tests to find custom_components.
    This conftest is in tests/ so it applies to all test files in tests/.
    Pure-Python tests (test_protocol.py, test_protocol_property.py, etc.)
    don't use the `hass` fixture so the `enable_custom_integrations` dep
    is never triggered for them.
    """
    return


@pytest.fixture(autouse=True)
def isolate_bluetooth_hardware(mock_bluetooth: None) -> Iterator[None]:
    """Keep HA's Bluetooth manager on its no-local-management fallback."""
    with patch(
        "habluetooth.channels.bluez.MGMTBluetoothCtl.setup",
        new=AsyncMock(side_effect=PermissionError("Bluetooth management disabled in tests")),
    ):
        yield
