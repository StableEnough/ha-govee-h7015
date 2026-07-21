"""Regression tests for bugs found by the superpowers code reviewer.

These tests verify that specific bugs stay fixed:
- C1: MAC identifier mismatch (services couldn't find coordinators)
- C2: Effect state wiped on every poll
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "standalone"))

from custom_components.govee_h7015_ble import async_setup_entry  # noqa: E402
from custom_components.govee_h7015_ble.const import DOMAIN  # noqa: E402
from custom_components.govee_h7015_ble.coordinator import H7015Coordinator  # noqa: E402
from custom_components.govee_h7015_ble.protocol import H7015State, Scene  # noqa: E402

try:
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    USE_MOCK_ENTRY = True
except ImportError:
    USE_MOCK_ENTRY = False


def _make_entry(entry_id: str = "regress") -> object:
    if USE_MOCK_ENTRY:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Patio Lights",
            data={"mac": "AA:BB:CC:DD:EE:FF", "name": "Patio Lights"},
            entry_id=entry_id,
            unique_id="AA:BB:CC:DD:EE:FF",
        )
        return entry
    from homeassistant.config_entries import ConfigEntry
    return ConfigEntry(
        version=1, domain=DOMAIN, title="Patio Lights",
        data={"mac": "AA:BB:CC:DD:EE:FF", "name": "Patio Lights"},
        source="user", entry_id=entry_id, unique_id="AA:BB:CC:DD:EE:FF",
        minor_version=1, discovery_keys={},
    )


# ===========================================================================
# C1 Regression: MAC identifier mismatch
# The device identifier must use MAC without colons so that
# _find_coordinator_for_device can match it.
# ===========================================================================

async def test_device_identifier_has_no_colons(hass) -> None:  # type: ignore[no-untyped-def]
    """Device identifier must be MAC without colons, not with colons.

    Bug: light.py used self._mac.upper() (with colons) for the device
    identifier, but __init__.py's _find_coordinator_for_device strips
    colons before comparing. These never matched.
    """
    entry = _make_entry("c1_regress")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True)

    with patch.object(H7015Coordinator, "_async_update_data", mock_update), \
         patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Check the device registry — the identifier should NOT have colons
        from homeassistant.helpers import device_registry as dr
        dev_reg = dr.async_get(hass)
        devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
        assert len(devices) == 1
        device = devices[0]

        # Find our domain's identifier
        our_id = None
        for ident in device.identifiers:
            if ident[0] == DOMAIN:
                our_id = ident[1]
                break

        assert our_id is not None, "No device identifier for our domain"
        assert ":" not in our_id, f"Identifier has colons: {our_id}"
        assert our_id == "AABBCCDDEEFF", f"Expected AABBCCDDEEFF, got {our_id}"


async def test_set_bulb_finds_coordinator_with_real_device_id(hass) -> None:  # type: ignore[no-untyped-def]
    """set_bulb service must find the coordinator using the real device ID.

    This test does NOT pre-create the device registry entry — it lets
    light.py create it naturally, then calls the service. This is the
    scenario that was broken before the fix.
    """
    entry = _make_entry("c1_regress2")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True)

    with patch.object(H7015Coordinator, "_async_update_data", mock_update), \
         patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()), \
         patch.object(H7015Coordinator, "set_bulb", new=AsyncMock()) as mock_set_bulb:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Find the device that light.py created (not pre-created by the test)
        from homeassistant.helpers import device_registry as dr
        dev_reg = dr.async_get(hass)
        devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
        assert len(devices) == 1
        device = devices[0]

        # Call set_bulb with the REAL device ID
        await hass.services.async_call(
            DOMAIN,
            "set_bulb",
            {"bulb": 0, "rgb": [255, 0, 0], "device_id": [device.id]},
            blocking=True,
        )

        # If the MAC bug is present, this raises HomeAssistantError.
        # If fixed, set_bulb is called.
        mock_set_bulb.assert_called_once()


# ===========================================================================
# C2 Regression: Effect state preserved after poll
# ===========================================================================

async def test_effect_preserved_after_poll(hass) -> None:  # type: ignore[no-untyped-def]
    """After a poll, the effect (mode) should NOT be wiped to None.

    Bug: _async_update_data did self._device_state = decode_state(raw),
    which replaced the entire state. decode_state never sets mode, so
    mode was reset to None after every 60s poll.
    """
    entry = _make_entry("c2_regress")
    entry.add_to_hass(hass)

    poll_count = 0

    async def mock_update(self):  # type: ignore[no-untyped-def]
        nonlocal poll_count
        poll_count += 1
        # Return a state packet that has power + brightness but no mode info
        return H7015State(power=True, brightness=50)

    with patch.object(H7015Coordinator, "_async_update_data", mock_update), \
         patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]

        # Set a scene — this sets mode to "scene:rainbow"
        with patch.object(H7015Coordinator, "_send", new=AsyncMock()):
            await coordinator.set_scene(Scene.RAINBOW)

        assert coordinator.device_state.mode == "scene:rainbow"

        # Trigger another poll — this should NOT wipe mode
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        # Mode should still be "scene:rainbow" after the update
        assert coordinator.device_state.mode == "scene:rainbow", \
            "Mode was wiped by poll — C2 regression"


async def test_color_temp_preserved_after_poll(hass) -> None:  # type: ignore[no-untyped-def]
    """Color temperature mode should survive a poll."""
    entry = _make_entry("c2_regress2")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True, brightness=50)

    with patch.object(H7015Coordinator, "_async_update_data", mock_update), \
         patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]

        with patch.object(H7015Coordinator, "_send", new=AsyncMock()):
            await coordinator.set_color_temperature(2700)

        assert coordinator.device_state.mode == "color_temp:2700"

        # Trigger update
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        assert coordinator.device_state.mode == "color_temp:2700", \
            "Color temp mode was wiped by poll — C2 regression"
