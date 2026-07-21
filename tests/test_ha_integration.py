"""Real Home Assistant integration tests.

These use pytest-homeassistant-custom-component to test the actual HA
integration code: config flow, light entity, service registration.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make the integration importable BEFORE any HA fixtures run.
# The project root must be on sys.path for `import custom_components` to work.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "standalone"))

# Import at module level so collection fails fast if paths are wrong
from custom_components.govee_h7015_ble import (  # noqa: E402
    async_setup_entry,
    async_unload_entry,
)
from custom_components.govee_h7015_ble import config_flow as govee_config_flow  # noqa: E402
from custom_components.govee_h7015_ble.const import DOMAIN  # noqa: E402
from custom_components.govee_h7015_ble.coordinator import H7015Coordinator  # noqa: E402
from custom_components.govee_h7015_ble.protocol import H7015State  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402

# Use the test framework's MockConfigEntry if available
try:
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    USE_MOCK_ENTRY = True
except ImportError:
    USE_MOCK_ENTRY = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
# Note: auto_enable_custom_integrations is provided by
# pytest-homeassistant-custom-component. No need to define it here.


@pytest.fixture
def mock_ble_device() -> MagicMock:
    """A fake BLE device that HA's Bluetooth framework would discover."""
    device = MagicMock()
    device.address = "AA:BB:CC:DD:EE:FF"
    device.name = "H7015_1234"
    return device


@pytest.fixture
def mock_bluetooth_info() -> MagicMock:
    """A fake BluetoothServiceInfo for the H7015."""
    info = MagicMock()
    info.address = "AA:BB:CC:DD:EE:FF"
    info.name = "H7015_1234"
    info.service_data = {}
    info.service_uuids = ["00010203-0405-0607-0809-0a0b0c0d1910"]
    return info


# ---------------------------------------------------------------------------
# Config flow tests — use HA's async_test_config_flow helper
# ---------------------------------------------------------------------------
async def test_config_flow_user_manual_mac(hass) -> None:  # type: ignore[no-untyped-def]
    """Test manual MAC entry via the user step."""
    with patch(
        "custom_components.govee_h7015_ble.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
        assert result["type"] == "form"
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"mac": "AA:BB:CC:DD:EE:FF", "name": "Patio Lights"},
        )
    assert result["type"] == "create_entry"
    assert result["title"] == "Patio Lights"
    assert result["data"]["mac"] == "AA:BB:CC:DD:EE:FF"
    assert result["data"]["name"] == "Patio Lights"


async def test_config_flow_rejects_invalid_mac(hass) -> None:  # type: ignore[no-untyped-def]
    """Invalid MAC addresses should show an error, not crash."""
    with patch(
        "custom_components.govee_h7015_ble.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"mac": "not-a-mac", "name": "Test"},
        )
    assert result["type"] == "form"
    assert result["errors"]["mac"] == "invalid_mac"


async def test_config_flow_normalizes_mac(hass) -> None:  # type: ignore[no-untyped-def]
    """MACs without colons should be normalized to AA:BB:CC:DD:EE:FF form."""
    with patch(
        "custom_components.govee_h7015_ble.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"mac": "aabbccddeeff", "name": "Test"},
        )
    assert result["type"] == "create_entry"
    assert result["data"]["mac"] == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# Setup entry tests (mock the BLE layer)
# ---------------------------------------------------------------------------
def _make_config_entry(entry_id: str = "test_entry") -> ConfigEntry:
    """Create a mock ConfigEntry for testing."""
    entry_data = {
        "mac": "AA:BB:CC:DD:EE:FF",
        "name": "Patio Lights",
    }
    if USE_MOCK_ENTRY:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Patio Lights",
            data=entry_data,
            entry_id=entry_id,
            unique_id="AA:BB:CC:DD:EE:FF",
        )
        # MockConfigEntry needs to be added to hass
        return entry  # type: ignore[return-value]
    return ConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Patio Lights",
        data=entry_data,
        source="user",
        entry_id=entry_id,
        unique_id="AA:BB:CC:DD:EE:FF",
        minor_version=1,
        discovery_keys={},
    )


async def test_setup_entry_creates_light(hass) -> None:  # type: ignore[no-untyped-def]
    """Setting up a config entry should create a light entity."""
    entry = _make_config_entry("test_entry_1")
    entry.add_to_hass(hass)

    # Mock the coordinator's _async_update_data so it doesn't try real BLE
    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True, brightness=50, rgb=(255, 0, 0))

    with patch.object(H7015Coordinator, "_async_update_data", mock_update), \
         patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()):
        # Use HA's async_setup_entry through the proper entry setup path
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state.value == "loaded"  # type: ignore[attr-defined]

        # Verify the coordinator was registered
        assert entry.entry_id in hass.data[DOMAIN]

        # Verify the service was registered
        assert hass.services.has_service(DOMAIN, "set_bulb")


async def test_unload_entry_cleans_up(hass) -> None:  # type: ignore[no-untyped-def]
    """Unloading an entry should remove the coordinator and service."""
    entry = _make_config_entry("test_entry_2")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State()

    with patch.object(H7015Coordinator, "_async_update_data", mock_update), \
         patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.entry_id in hass.data[DOMAIN]

        # Now unload
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.entry_id not in hass.data.get(DOMAIN, {})


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------
async def test_set_bulb_service_routes_to_coordinator(hass) -> None:  # type: ignore[no-untyped-def]
    """The set_bulb service should call the coordinator's set_bulb method."""
    entry = _make_config_entry("test_entry_3")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State()

    with patch.object(H7015Coordinator, "_async_update_data", mock_update), \
         patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()), \
         patch.object(H7015Coordinator, "set_bulb", new=AsyncMock()) as mock_set_bulb:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # The service now requires a target device. We need to register
        # a device in the device registry that maps to our coordinator,
        # then pass its device_id as the target.
        from homeassistant.helpers import device_registry as dr
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "AABBCCDDEEFF")},
            name="Patio Lights",
        )

        # Call the service with a target device
        await hass.services.async_call(
            DOMAIN,
            "set_bulb",
            {"bulb": 0, "rgb": [255, 0, 0], "device_id": [device.id]},
            blocking=True,
        )

        # Verify the coordinator's set_bulb was called
        mock_set_bulb.assert_called_once()


async def test_set_bulb_service_requires_target(hass) -> None:  # type: ignore[no-untyped-def]
    """The set_bulb service should raise an error if no target is specified."""
    entry = _make_config_entry("test_entry_4")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State()

    with patch.object(H7015Coordinator, "_async_update_data", mock_update), \
         patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()), \
         patch.object(H7015Coordinator, "set_bulb", new=AsyncMock()) as mock_set_bulb:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Call the service WITHOUT a target — should raise
        from homeassistant.core import HomeAssistantError

        with pytest.raises(HomeAssistantError, match="requires a target"):
            await hass.services.async_call(
                DOMAIN,
                "set_bulb",
                {"bulb": 0, "rgb": [255, 0, 0]},
                blocking=True,
            )

        # Verify set_bulb was NOT called
        mock_set_bulb.assert_not_called()


async def test_per_bulb_entities_created(hass) -> None:  # type: ignore[no-untyped-def]
    """Setup should create 1 main light + 15 per-bulb light entities."""
    entry = _make_config_entry("test_entry_5")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True, brightness=50)

    with patch.object(H7015Coordinator, "_async_update_data", mock_update), \
         patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Should have 1 main entity + 15 bulb entities = 16 total
        light_entities = hass.states.async_entity_ids("light")
        assert len(light_entities) == 16, f"expected 16 light entities, got {light_entities}"

        # Bulb entities are named 1-15 (1-indexed for user friendliness)
        # HA generates entity_id from the device name + entity name
        for i in range(1, 16):
            bulb_entity_id = f"light.patio_lights_bulb_{i}"
            assert bulb_entity_id in light_entities, f"missing {bulb_entity_id}"


async def test_per_bulb_entity_turn_on_sets_color(hass) -> None:  # type: ignore[no-untyped-def]
    """Turning on a per-bulb entity should call coordinator.set_bulb."""
    entry = _make_config_entry("test_entry_6")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True)

    with patch.object(H7015Coordinator, "_async_update_data", mock_update), \
         patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()), \
         patch.object(H7015Coordinator, "set_bulb", new=AsyncMock()) as mock_set_bulb:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Turn on bulb 1 (entity_id is 1-indexed, but coordinator uses 0-indexed)
        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": "light.patio_lights_bulb_1", "rgb_color": [255, 0, 0]},
            blocking=True,
        )

        # Verify set_bulb was called with bulb=0 (0-indexed), rgb=(255,0,0)
        # When patch.object replaces an instance method, the mock receives
        # args without self: (bulb_index, r, g, b)
        mock_set_bulb.assert_called_once()
        call_args = mock_set_bulb.call_args
        assert call_args.args[0] == 0  # bulb index (0-indexed)
        assert call_args.args[1:] == (255, 0, 0)  # r, g, b


async def test_coordinator_tracks_bulb_colors(hass) -> None:  # type: ignore[no-untyped-def]
    """The coordinator should track the last-commanded color per bulb."""
    entry = _make_config_entry("test_entry_7")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True)

    with patch.object(H7015Coordinator, "_async_update_data", mock_update), \
         patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]

        # Before any set_bulb, colors should be empty
        assert coordinator.get_bulb_color(0) is None
        assert coordinator.get_all_bulb_colors() == {}

        # Set bulb 0 to red
        await coordinator.set_bulb(0, 255, 0, 0)
        assert coordinator.get_bulb_color(0) == (255, 0, 0)

        # Set bulb 5 to blue
        await coordinator.set_bulb(5, 0, 0, 255)
        assert coordinator.get_bulb_color(5) == (0, 0, 255)

        # All colors should be a snapshot dict
        all_colors = coordinator.get_all_bulb_colors()
        assert all_colors[0] == (255, 0, 0)
        assert all_colors[5] == (0, 0, 255)
        assert len(all_colors) == 2


async def test_snapshot_scene_service(hass) -> None:  # type: ignore[no-untyped-def]
    """The snapshot_scene service should call scene.create with bulb colors."""
    entry = _make_config_entry("test_entry_8")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True)

    with patch.object(H7015Coordinator, "_async_update_data", mock_update), \
         patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]

        # Set some bulb colors
        await coordinator.set_bulb(0, 255, 0, 0)  # red
        await coordinator.set_bulb(1, 0, 255, 0)  # green

        # Register a device in the device registry
        from homeassistant.helpers import device_registry as dr
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "AABBCCDDEEFF")},
            name="Patio Lights",
        )

        # Register a mock scene.create service that records calls
        scene_create_calls: list[dict] = []

        async def mock_scene_create(call):  # type: ignore[no-untyped-def]
            scene_create_calls.append(dict(call.data))

        hass.services.async_register("scene", "create", mock_scene_create)

        # Call the snapshot_scene service
        await hass.services.async_call(
            DOMAIN,
            "snapshot_scene",
            {"scene_name": "Test Scene", "device_id": [device.id]},
            blocking=True,
        )

        # Verify scene.create was called with the right data
        assert len(scene_create_calls) == 1
        scene_data = scene_create_calls[0]
        assert scene_data["name"] == "Test Scene"

        # Check that bulb entities are in the scene.
        # Entity IDs come from the entity registry, which uses the device
        # name ("Patio Lights") for the main entity and "Bulb N" for bulbs.
        entities = scene_data["entities"]

        # The main entity should be light.patio_lights
        assert "light.patio_lights" in entities
        assert entities["light.patio_lights"]["state"] == "on"

        # Bulb entities should be light.patio_lights_bulb_1 through bulb_15
        # (1-indexed by HA's entity registry)
        bulb_1_id = "light.patio_lights_bulb_1"
        assert bulb_1_id in entities, f"missing {bulb_1_id} in {list(entities.keys())}"
        # Bulb 0 (entity_id bulb_1) was set to red
        assert entities[bulb_1_id]["state"] == "on"
        assert entities[bulb_1_id]["rgb_color"] == [255, 0, 0]

        # Bulb 1 (entity_id bulb_2) was set to green
        bulb_2_id = "light.patio_lights_bulb_2"
        assert bulb_2_id in entities
        assert entities[bulb_2_id]["state"] == "on"
        assert entities[bulb_2_id]["rgb_color"] == [0, 255, 0]
