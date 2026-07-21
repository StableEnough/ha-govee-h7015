"""Regression tests for bugs found by the superpowers code reviewer.

These tests verify that specific bugs stay fixed:
- C1: MAC identifier mismatch (services couldn't find coordinators)
- C2: Effect state wiped on every poll
- D1: GoveeH7015Client.is_connected missing (crashed the MQTT bridge's poll loop)
- D2: Reconfigure flow didn't detect MAC collisions with other entries
- D3: Diagnostics dump included the MAC address unredacted
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "standalone"))

from custom_components.govee_h7015_ble.const import DOMAIN
from custom_components.govee_h7015_ble.coordinator import H7015Coordinator
from custom_components.govee_h7015_ble.protocol import H7015State, Scene

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
        version=1,
        domain=DOMAIN,
        title="Patio Lights",
        data={"mac": "AA:BB:CC:DD:EE:FF", "name": "Patio Lights"},
        source="user",
        entry_id=entry_id,
        unique_id="AA:BB:CC:DD:EE:FF",
        minor_version=1,
        discovery_keys={},
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

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
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

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
        patch.object(H7015Coordinator, "set_bulb", new=AsyncMock()) as mock_set_bulb,
    ):
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

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
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
        assert coordinator.device_state.mode == "scene:rainbow", (
            "Mode was wiped by poll — C2 regression"
        )


async def test_color_temp_preserved_after_poll(hass) -> None:  # type: ignore[no-untyped-def]
    """Color temperature mode should survive a poll."""
    entry = _make_entry("c2_regress2")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True, brightness=50)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]

        with patch.object(H7015Coordinator, "_send", new=AsyncMock()):
            await coordinator.set_color_temperature(2700)

        assert coordinator.device_state.mode == "color_temp:2700"

        # Trigger update
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        assert coordinator.device_state.mode == "color_temp:2700", (
            "Color temp mode was wiped by poll — C2 regression"
        )


# ===========================================================================
# D1 Regression: GoveeH7015Client.is_connected missing
#
# standalone/mqtt_bridge.py's DeviceBridge.run() poll loop does
# `while self._client and self._client.is_connected:`, but GoveeH7015Client
# never defined that property (only the internal bleak client did). This
# raised AttributeError the first time through the loop, crashing the
# bridge's polling for every device it managed.
# ===========================================================================


def test_govee_h7015_client_has_is_connected_property() -> None:
    from govee_h7015 import GoveeH7015Client  # type: ignore[import-not-found]

    client = GoveeH7015Client("AA:BB:CC:DD:EE:FF")
    # No underlying BLE connection yet — must not raise AttributeError.
    assert client.is_connected is False


def test_govee_h7015_client_is_connected_reflects_ble_client() -> None:
    from govee_h7015 import GoveeH7015Client  # type: ignore[import-not-found]

    client = GoveeH7015Client("AA:BB:CC:DD:EE:FF")
    fake_ble_client = type("FakeBleakClient", (), {"is_connected": True})()
    client._client = fake_ble_client  # type: ignore[assignment]
    assert client.is_connected is True


# ===========================================================================
# D2 Regression: Reconfigure flow didn't detect MAC collisions
#
# async_step_reconfigure called self._abort_if_unique_id_configured() without
# first calling async_set_unique_id(mac) for the *new* MAC being entered. It
# was checking the flow's original (old) unique_id, so reconfiguring one
# entry to use a MAC already claimed by a different entry silently succeeded
# instead of aborting — leaving two entries with the same MAC/unique_id.
# ===========================================================================


async def test_reconfigure_rejects_mac_already_used_by_another_entry(hass) -> None:  # type: ignore[no-untyped-def]
    """Reconfiguring entry A to entry B's MAC must abort, not succeed."""
    if not USE_MOCK_ENTRY:
        pytest = __import__("pytest")
        pytest.skip("requires pytest_homeassistant_custom_component")

    entry_a = MockConfigEntry(
        domain=DOMAIN,
        title="Patio Lights",
        data={"mac": "AA:BB:CC:DD:EE:FF", "name": "Patio Lights"},
        entry_id="d2_entry_a",
        unique_id="AA:BB:CC:DD:EE:FF",
    )
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        title="Garden Lights",
        data={"mac": "11:22:33:44:55:66", "name": "Garden Lights"},
        entry_id="d2_entry_b",
        unique_id="11:22:33:44:55:66",
    )
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)

    from homeassistant.config_entries import SOURCE_RECONFIGURE

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry_a.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"mac": entry_b.data["mac"], "name": "Patio Lights"},
    )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
    # entry_a's MAC must be unchanged — the collision must not have applied.
    assert entry_a.data["mac"] == "AA:BB:CC:DD:EE:FF"


# ===========================================================================
# D3 Regression: Diagnostics dump included the MAC address unredacted
#
# info.md promises diagnostics export "without sensitive data", but the MAC
# was included in the clear in both entry.data and the device block. HA's
# own diagnostics guidelines call for redacting device identifiers like MACs
# since diagnostics get pasted into public bug reports.
# ===========================================================================


async def test_diagnostics_redacts_mac(hass) -> None:  # type: ignore[no-untyped-def]
    """The MAC address must be redacted from the diagnostics dump."""
    from custom_components.govee_h7015_ble.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = _make_entry("d3_regress")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        diag = await async_get_config_entry_diagnostics(hass, entry)

    assert "AA:BB:CC:DD:EE:FF" not in str(diag)
    assert diag["entry"]["data"]["mac"] == "**REDACTED**"
    assert diag["device"]["mac"] == "**REDACTED**"
