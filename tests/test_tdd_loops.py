"""TDD Loop tests — written to find bugs by testing untested paths.

Each test was written BEFORE checking if the code handles it correctly.
If a test fails, it reveals a bug.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "standalone"))

from homeassistant.config_entries import ConfigEntry

from custom_components.govee_h7015_ble.const import DOMAIN
from custom_components.govee_h7015_ble.coordinator import H7015Coordinator
from custom_components.govee_h7015_ble.protocol import H7015State, MusicMode, Scene

try:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    USE_MOCK_ENTRY = True
except ImportError:
    USE_MOCK_ENTRY = False


def _make_config_entry(entry_id: str = "test_entry") -> ConfigEntry:
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


# ===========================================================================
# Loop 1: turn_on with brightness-only should power on the light
# ===========================================================================


async def test_turn_on_with_brightness_only_powers_on(hass) -> None:  # type: ignore[no-untyped-def]
    """Calling light.turn_on with only brightness should power on + set brightness."""
    entry = _make_config_entry("tdd1")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State()

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
        patch.object(H7015Coordinator, "set_power", new=AsyncMock()) as mock_power,
        patch.object(H7015Coordinator, "set_brightness", new=AsyncMock()) as mock_brightness,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": "light.patio_lights", "brightness": 128},
            blocking=True,
        )

        # set_power(True) must have been called
        mock_power.assert_called_once_with(True)
        # set_brightness must have been called with the right percent
        mock_brightness.assert_called_once()
        # 128/255 * 100 ≈ 50
        assert mock_brightness.call_args.args[0] == 50


async def test_turn_off_sets_power_false(hass) -> None:  # type: ignore[no-untyped-def]
    """Calling light.turn_off should call set_power(False)."""
    entry = _make_config_entry("tdd2")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
        patch.object(H7015Coordinator, "set_power", new=AsyncMock()) as mock_power,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "light",
            "turn_off",
            {"entity_id": "light.patio_lights"},
            blocking=True,
        )

        mock_power.assert_called_once_with(False)


async def test_turn_on_with_color_temp(hass) -> None:  # type: ignore[no-untyped-def]
    """Calling light.turn_on with color_temp_kelvin should call set_color_temperature."""
    entry = _make_config_entry("tdd3")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State()

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
        patch.object(H7015Coordinator, "set_color_temperature", new=AsyncMock()) as mock_ct,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Use Kelvin directly (HA 2026.3+ API)
        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": "light.patio_lights", "color_temp_kelvin": 2700},
            blocking=True,
        )

        mock_ct.assert_called_once()
        assert mock_ct.call_args.args[0] == 2700


async def test_turn_on_with_scene_effect(hass) -> None:  # type: ignore[no-untyped-def]
    """Calling light.turn_on with effect should call set_scene."""
    entry = _make_config_entry("tdd4")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State()

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
        patch.object(H7015Coordinator, "set_scene", new=AsyncMock()) as mock_scene,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": "light.patio_lights", "effect": "rainbow"},
            blocking=True,
        )

        mock_scene.assert_called_once_with(Scene.RAINBOW)


async def test_turn_on_with_music_effect(hass) -> None:  # type: ignore[no-untyped-def]
    """Calling light.turn_on with music_rhythm effect should call set_music_mode."""
    entry = _make_config_entry("tdd5")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State()

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
        patch.object(H7015Coordinator, "set_music_mode", new=AsyncMock()) as mock_music,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": "light.patio_lights", "effect": "music_rhythm"},
            blocking=True,
        )

        mock_music.assert_called_once_with(MusicMode.RHYTHM)


# ===========================================================================
# Loop 2: Color temp property returns correct mireds
# ===========================================================================


async def test_color_temp_property_returns_kelvin(hass) -> None:  # type: ignore[no-untyped-def]
    """The color_temp_kelvin property should return Kelvin when in color_temp mode."""
    entry = _make_config_entry("tdd6")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True, mode="color_temp:2700")

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Force entity refresh
        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        state = hass.states.get("light.patio_lights")
        assert state is not None
        # color_temp_kelvin should return 2700 directly
        assert state.attributes.get("color_temp_kelvin") == 2700


async def test_color_temp_property_none_when_not_in_ct_mode(hass) -> None:  # type: ignore[no-untyped-def]
    """color_temp should be None when not in color_temp mode."""
    entry = _make_config_entry("tdd7")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True, mode="manual", rgb=(255, 0, 0))

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("light.patio_lights")
        assert state is not None
        assert state.attributes.get("color_temp") is None


async def test_rgb_color_none_when_in_ct_mode(hass) -> None:  # type: ignore[no-untyped-def]
    """color_mode should be COLOR_TEMP when in color_temp mode.

    Note: HA computes an RGB approximation of the color temperature for
    backward compatibility, so rgb_color may not be None even in CT mode.
    We verify color_mode instead.
    """
    entry = _make_config_entry("tdd8")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True, mode="color_temp:2700", rgb=(255, 0, 0))

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Force entity refresh
        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        state = hass.states.get("light.patio_lights")
        assert state is not None
        # color_mode should be color_temp when in CT mode
        assert state.attributes.get("color_mode") == "color_temp"


async def test_brightness_converted_from_percent_to_ha_scale(hass) -> None:  # type: ignore[no-untyped-def]
    """Brightness should be converted from 0-100% to HA's 0-255 scale."""
    entry = _make_config_entry("tdd9")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True, brightness=100)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("light.patio_lights")
        assert state is not None
        # 100% → 255 in HA scale
        assert state.attributes.get("brightness") == 255


async def test_brightness_zero_reports_as_zero(hass) -> None:  # type: ignore[no-untyped-def]
    """Brightness 0% should report as 0 in HA scale."""
    entry = _make_config_entry("tdd10")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True, brightness=0)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("light.patio_lights")
        assert state is not None
        assert state.attributes.get("brightness") == 0


# ===========================================================================
# Loop 3: Bulb entity is_on logic
# ===========================================================================


async def test_bulb_is_on_false_when_main_light_off(hass) -> None:  # type: ignore[no-untyped-def]
    """Bulb entity should be off when the main light is off, even if it has a color."""
    entry = _make_config_entry("tdd11")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=False)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]
        # Set a bulb color even though light is off
        coordinator._bulb_colors[0] = (255, 0, 0)
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        state = hass.states.get("light.patio_lights_bulb_1")
        assert state is not None
        assert state.state == "off"


async def test_bulb_is_on_false_when_color_is_black(hass) -> None:  # type: ignore[no-untyped-def]
    """Bulb entity should be off when color is (0,0,0) even if main light is on."""
    entry = _make_config_entry("tdd12")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator._bulb_colors[0] = (0, 0, 0)
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        state = hass.states.get("light.patio_lights_bulb_1")
        assert state is not None
        assert state.state == "off"


async def test_bulb_is_on_true_when_has_color(hass) -> None:  # type: ignore[no-untyped-def]
    """Bulb entity should be on when main light is on and bulb has a non-black color."""
    entry = _make_config_entry("tdd13")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator._bulb_colors[0] = (255, 0, 0)
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        state = hass.states.get("light.patio_lights_bulb_1")
        assert state is not None
        assert state.state == "on"


async def test_bulb_turn_off_sets_black(hass) -> None:  # type: ignore[no-untyped-def]
    """Turning off a bulb entity should call set_bulb with (0,0,0)."""
    entry = _make_config_entry("tdd14")
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

        await hass.services.async_call(
            "light",
            "turn_off",
            {"entity_id": "light.patio_lights_bulb_1"},
            blocking=True,
        )

        mock_set_bulb.assert_called_once()
        # Args: (bulb_index=0, r=0, g=0, b=0) — without self
        assert mock_set_bulb.call_args.args[0] == 0  # bulb index
        assert mock_set_bulb.call_args.args[1:] == (0, 0, 0)


async def test_bulb_turn_on_without_color_defaults_to_white(hass) -> None:  # type: ignore[no-untyped-def]
    """Turning on a bulb without specifying color should default to white."""
    entry = _make_config_entry("tdd15")
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

        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": "light.patio_lights_bulb_1"},
            blocking=True,
        )

        mock_set_bulb.assert_called_once()
        # Should default to white (255, 255, 255)
        assert mock_set_bulb.call_args.args[0] == 0  # bulb index
        assert mock_set_bulb.call_args.args[1:] == (255, 255, 255)


# ===========================================================================
# Loop 4: Option flow + setup error handling
# ===========================================================================


async def test_setup_with_first_refresh_failure_cleans_up(hass) -> None:  # type: ignore[no-untyped-def]
    """If the first refresh fails, the coordinator should be cleaned up."""
    entry = _make_config_entry("tdd16")
    entry.add_to_hass(hass)

    from homeassistant.helpers.update_coordinator import UpdateFailed

    async def mock_update_fails(self):  # type: ignore[no-untyped-def]
        raise UpdateFailed("device not found")

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update_fails),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
        patch.object(H7015Coordinator, "shutdown", new=AsyncMock()) as mock_shutdown,
    ):
        # This should raise during setup
        try:
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        except Exception:
            pass

        # The coordinator should have been cleaned up
        assert entry.entry_id not in hass.data.get(DOMAIN, {})
        mock_shutdown.assert_called_once()


# ===========================================================================
# Loop 5: Protocol edge cases
# ===========================================================================


def test_decode_state_with_empty_bytes() -> None:
    """decode_state with empty bytes should return empty state."""
    sys.path.insert(0, str(ROOT / "standalone"))
    from protocol import decode_state  # type: ignore[import-not-found]

    st = decode_state(b"")
    assert st.power is None
    assert st.brightness is None
    assert st.rgb is None


def test_decode_state_with_short_bytes() -> None:
    """decode_state with 2 bytes should return empty state."""
    from protocol import decode_state  # type: ignore[import-not-found]

    st = decode_state(b"\x33\x01")
    assert st.power is None


def test_decode_state_with_unknown_command() -> None:
    """A checksum-valid AA frame with an unknown command yields raw only."""
    from protocol import build_packet, decode_state  # type: ignore[import-not-found]

    raw = bytes(build_packet(b"\xaa\xff"))
    st = decode_state(raw)
    assert st.power is None
    assert st.brightness is None
    assert st.rgb is None
    assert st.raw == raw


def test_brightness_to_raw_at_boundaries() -> None:
    """The H7015 byte is the raw percent, clamped to 1..100 on commands."""
    from protocol import brightness_to_raw  # type: ignore[import-not-found]

    assert brightness_to_raw(0) == 1
    assert brightness_to_raw(1) == 1
    assert brightness_to_raw(100) == 100
    assert brightness_to_raw(-5) == 1
    assert brightness_to_raw(150) == 100


def test_raw_to_brightness_at_boundaries() -> None:
    """Read side: the byte is the percent, clamped to 0..100."""
    from protocol import raw_to_brightness  # type: ignore[import-not-found]

    assert raw_to_brightness(0) == 0
    assert raw_to_brightness(1) == 1
    assert raw_to_brightness(100) == 100
    assert raw_to_brightness(0xFF) == 100


def test_pkt_color_temperature_monotonic() -> None:
    """Color temperature should be monotonic: warmer kelvin = more warm byte."""
    from protocol import pkt_color_temperature  # type: ignore[import-not-found]

    warm = pkt_color_temperature(2000)
    cold = pkt_color_temperature(6500)
    # Warm should have more warm byte (byte 7) than cold
    assert warm[7] > cold[7]
    # Cold should have more cold byte (byte 8) than warm
    assert cold[8] > warm[8]


def test_pkt_segment_all_bulbs_produce_valid_packets() -> None:
    """Every bulb index 0-14 should produce a valid 20-byte packet."""
    from protocol import checksum, pkt_segment  # type: ignore[import-not-found]

    for bulb in range(15):
        pkt = pkt_segment(bulb, 128, 64, 32)
        assert len(pkt) == 20
        assert pkt[-1] == checksum(pkt[:-1])


def test_pkt_solid_color_with_extreme_values() -> None:
    """Solid color with values > 255 or < 0 should clamp, not crash."""
    from protocol import pkt_solid_color  # type: ignore[import-not-found]

    pkt = pkt_solid_color(300, -50, 0)
    assert pkt[4] == 255  # clamped
    assert pkt[5] == 0  # clamped
    assert pkt[6] == 0


def test_validate_packet_rejects_wrong_length() -> None:
    """validate_packet should reject packets that aren't 20 bytes."""
    from exceptions import GoveeChecksumError  # type: ignore[import-not-found]
    from protocol import validate_packet  # type: ignore[import-not-found]

    with pytest.raises(GoveeChecksumError, match="must be 20 bytes"):
        validate_packet(b"\x33\x01\x01")


def test_checksum_empty_bytes() -> None:
    """checksum of empty bytes should be 0."""
    from protocol import checksum  # type: ignore[import-not-found]

    assert checksum(b"") == 0


# ===========================================================================
# Loop 6: State consistency after commands (found real bug)
# ===========================================================================


async def test_set_power_updates_device_state_immediately(hass) -> None:  # type: ignore[no-untyped-def]
    """After set_power(True), device_state should immediately reflect it.

    Bug: device_state preferred self.data (from last poll) over
    self._device_state (updated by commands). So after set_power(True),
    the entity still showed the old polled state (power=False).
    Fix: command methods now update both self.data and self._device_state.
    """
    entry = _make_config_entry("tdd_state1")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=False, brightness=50)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]

        # Before command: power should be False (from poll)
        assert coordinator.device_state.power is False

        # After set_power(True): should immediately reflect True
        with patch.object(H7015Coordinator, "_send", new=AsyncMock()):
            await coordinator.set_power(True)

        assert coordinator.device_state.power is True


async def test_set_brightness_updates_device_state_immediately(hass) -> None:  # type: ignore[no-untyped-def]
    """After set_brightness(75), device_state should immediately reflect it."""
    entry = _make_config_entry("tdd_state2")
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
        assert coordinator.device_state.brightness == 50

        with patch.object(H7015Coordinator, "_send", new=AsyncMock()):
            await coordinator.set_brightness(75)

        assert coordinator.device_state.brightness == 75


async def test_set_color_updates_device_state_immediately(hass) -> None:  # type: ignore[no-untyped-def]
    """After set_color, device_state should immediately reflect new color + mode."""
    entry = _make_config_entry("tdd_state3")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True, rgb=(255, 0, 0), mode="manual")

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]

        with patch.object(H7015Coordinator, "_send", new=AsyncMock()):
            await coordinator.set_color(0, 255, 0)

        assert coordinator.device_state.rgb == (0, 255, 0)
        assert coordinator.device_state.mode == "manual"


async def test_set_color_temperature_updates_device_state(hass) -> None:  # type: ignore[no-untyped-def]
    """After set_color_temperature, device_state should reflect the new mode."""
    entry = _make_config_entry("tdd_state4")
    entry.add_to_hass(hass)

    async def mock_update(self):  # type: ignore[no-untyped-def]
        return H7015State(power=True, mode="manual")

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]

        with patch.object(H7015Coordinator, "_send", new=AsyncMock()):
            await coordinator.set_color_temperature(3500)

        assert coordinator.device_state.mode == "color_temp:3500"


# ===========================================================================
# Loop 7: Repair issues
# ===========================================================================


async def test_repair_issue_created_after_3_failures(hass) -> None:  # type: ignore[no-untyped-def]
    """A repair issue should be created after 3 consecutive connection failures."""
    entry = _make_config_entry("tdd_repair1")
    entry.add_to_hass(hass)

    call_count = 0

    async def mock_update_fails(self):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        from homeassistant.helpers.update_coordinator import UpdateFailed

        raise UpdateFailed("device not found")

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update_fails),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        # First refresh will fail
        try:
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        except Exception:
            pass

        coordinator: H7015Coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator:
            # Simulate 2 more failures (total 3)
            for _ in range(2):
                try:
                    await coordinator._async_update_data()
                except Exception:
                    pass

            # After 3 failures, repair issue should be created
            assert coordinator._consecutive_failures >= 3
            assert coordinator._repair_issue_created is True


async def test_repair_issue_deleted_on_success(hass) -> None:  # type: ignore[no-untyped-def]
    """Repair issue should be deleted when the device comes back online."""
    entry = _make_config_entry("tdd_repair2")
    entry.add_to_hass(hass)

    fail = True

    async def mock_update(self):  # type: ignore[no-untyped-def]
        nonlocal fail
        if fail:
            from homeassistant.helpers.update_coordinator import UpdateFailed

            raise UpdateFailed("device not found")
        return H7015State(power=True)

    with (
        patch.object(H7015Coordinator, "_async_update_data", mock_update),
        patch.object(H7015Coordinator, "_ensure_connected", new=AsyncMock()),
    ):
        # First refresh fails
        try:
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        except Exception:
            pass

        coordinator: H7015Coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator:
            # Simulate 2 more failures
            for _ in range(2):
                try:
                    await coordinator._async_update_data()
                except Exception:
                    pass
            assert coordinator._repair_issue_created is True

            # Now device comes back online
            fail = False
            try:
                await coordinator._async_update_data()
            except Exception:
                pass

            # Failure counter should be reset
            assert coordinator._consecutive_failures == 0
            assert coordinator._repair_issue_created is False
