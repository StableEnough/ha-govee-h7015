"""Light platform for the Govee H7015 BLE integration.

Provides:
- One main light entity (H7015Light) that controls the whole string
- 15 per-bulb light entities (H7015BulbLight) for individual bulb control
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final, override

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    LightEntity,
)
from homeassistant.components.light.const import ColorMode, LightEntityFeature
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MAC, CONF_NAME, DOMAIN, EFFECTS
from .coordinator import H7015Coordinator
from .protocol import BULB_COUNT, MusicMode, Scene

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

# The H7015 only accepts one BLE connection at a time, and all 16 light
# entities (main + 15 bulbs) share that single connection through the
# coordinator. Cap HA's own concurrent service-call dispatch to 1 so calls
# queue predictably instead of piling up behind the coordinator's internal
# lock. See: https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/parallel-updates/
PARALLEL_UPDATES = 1

# Lookup tables for effect name -> enum
SCENE_BY_NAME: Final = {s.name.lower(): s for s in Scene}
MUSIC_BY_NAME: Final = {m.name.lower(): m for m in MusicMode}

# Legacy white-mode UI range; the H7015 wire encoding remains unverified.
MIN_KELVIN = 2000  # warmest
MAX_KELVIN = 6500  # coldest


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the light platform — main entity + 15 per-bulb entities."""
    coordinator: H7015Coordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[LightEntity] = [H7015Light(coordinator, entry)]

    # Add one light entity per bulb for individual control.
    # These are marked as EntityCategory.CONFIG so they don't clutter the
    # main device view but are still available for dashboards and scenes.
    entities.extend(H7015BulbLight(coordinator, entry, i) for i in range(BULB_COUNT))

    async_add_entities(entities)


class H7015Light(CoordinatorEntity[H7015Coordinator], LightEntity):
    """Main light entity controlling the whole H7015 string."""

    _attr_has_entity_name = True
    _attr_assumed_state = True
    _attr_name = None  # Use device name
    _attr_translation_key = "string"
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_supported_color_modes = {ColorMode.RGB, ColorMode.COLOR_TEMP}
    _attr_effect_list = EFFECTS
    _attr_min_color_temp_kelvin = MIN_KELVIN
    _attr_max_color_temp_kelvin = MAX_KELVIN

    def __init__(self, coordinator: H7015Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._mac: str = entry.data[CONF_MAC]
        self._attr_unique_id = f"{DOMAIN}_{self._mac.replace(':', '').lower()}"
        # Use MAC without colons for device identifier — matches what
        # _find_coordinator_for_device expects.
        mac_id = self._mac.replace(":", "").upper()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac_id)},
            name=entry.data.get(CONF_NAME, "Govee H7015"),
            manufacturer="Govee",
            model="H7015 Outdoor String Lights",
            sw_version="reverse-engineered",
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    @property
    @override
    def is_on(self) -> bool | None:
        return self._coordinator.device_state.power

    @property
    @override
    def brightness(self) -> int | None:
        b = self._coordinator.device_state.brightness
        if b is None:
            return None
        return int(b * 255 / 100)

    @property
    @override
    def rgb_color(self) -> tuple[int, int, int] | None:
        mode = self._coordinator.device_state.mode
        # Only report RGB color when in manual/RGB mode, not color_temp mode
        if mode and mode.startswith("color_temp:"):
            return None
        return self._coordinator.device_state.rgb

    @property
    @override
    def color_mode(self) -> ColorMode:
        mode = self._coordinator.device_state.mode
        if mode and mode.startswith("color_temp:"):
            return ColorMode.COLOR_TEMP
        return ColorMode.RGB

    @property
    @override
    def color_temp_kelvin(self) -> int | None:
        mode = self._coordinator.device_state.mode
        if not mode or not mode.startswith("color_temp:"):
            return None
        try:
            kelvin = int(mode.split(":", 1)[1])
            if kelvin <= 0:
                return None
            return kelvin
        except (ValueError, IndexError):
            return None

    @property
    @override
    def effect(self) -> str | None:
        mode = self._coordinator.device_state.mode
        if not mode:
            return None
        if mode.startswith("scene:"):
            return mode.split(":", 1)[1]
        if mode.startswith("music:"):
            return f"music_{mode.split(':', 1)[1]}"
        return None

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        if kwargs.get(ATTR_BRIGHTNESS) == 0:
            await self.async_turn_off()
            return

        await self._coordinator.set_power(True)

        if ATTR_EFFECT in kwargs:
            await self._apply_effect(kwargs[ATTR_EFFECT])
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            # Color temperature takes precedence over RGB
            kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            if kelvin <= 0:
                _LOGGER.warning("Invalid color temperature: %s K", kelvin)
            else:
                await self._coordinator.set_color_temperature(kelvin)
        elif ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            await self._coordinator.set_color(r, g, b)

        if ATTR_BRIGHTNESS in kwargs:
            ha_b = kwargs[ATTR_BRIGHTNESS]
            await self._coordinator.set_brightness(max(1, round(ha_b * 100 / 255)))

        self.async_write_ha_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._coordinator.set_power(False)
        self.async_write_ha_state()

    async def _apply_effect(self, effect: str) -> None:
        if effect.startswith("music_"):
            mode_name = effect[len("music_") :]
            if mode_name in MUSIC_BY_NAME:
                await self._coordinator.set_music_mode(MUSIC_BY_NAME[mode_name])
            else:
                _LOGGER.warning("Unknown music effect: %s", effect)
        elif effect in SCENE_BY_NAME:
            await self._coordinator.set_scene(SCENE_BY_NAME[effect])
        else:
            _LOGGER.warning("Unknown effect: %s", effect)


class H7015BulbLight(CoordinatorEntity[H7015Coordinator], LightEntity):
    """Per-bulb light entity — controls a single bulb on the H7015 string.

    These entities are marked as EntityCategory.CONFIG so they don't
    clutter the main device view. They're primarily useful for:
    - Individual bulb control from dashboards
    - Creating HA scenes that snapshot per-bulb colors
    - Automation scripts that set specific bulbs

    Per-bulb colors and relative brightness are last-commanded state, not
    decoded hardware readback. Govee app changes may leave these entities stale.
    """

    _attr_has_entity_name = True
    _attr_assumed_state = True
    _attr_translation_key = "bulb"
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: H7015Coordinator,
        entry: ConfigEntry,
        bulb_index: int,
    ) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._mac: str = entry.data[CONF_MAC]
        self._bulb_index = bulb_index
        # Display name is 1-indexed (Bulb 1, Bulb 2, ...) for user-friendliness
        self._attr_name = f"Bulb {bulb_index + 1}"
        # Unique ID uses 0-indexed (bulb_0, bulb_1, ...) for programmer-friendliness
        self._attr_unique_id = f"{DOMAIN}_{self._mac.replace(':', '').lower()}_bulb_{bulb_index}"
        mac_id = self._mac.replace(":", "").upper()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac_id)},
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    @property
    @override
    def is_on(self) -> bool | None:
        """A bulb is "on" if the main light is on and has a non-black color set."""
        if not self._coordinator.device_state.power:
            return False
        color = self._coordinator.get_bulb_color(self._bulb_index)
        if color is None:
            return False
        # (0, 0, 0) = black = off
        return color != (0, 0, 0)

    @property
    @override
    def rgb_color(self) -> tuple[int, int, int] | None:
        return self._coordinator.get_bulb_color(self._bulb_index)

    @property
    @override
    def brightness(self) -> int | None:
        percent = self._coordinator.get_bulb_brightness(self._bulb_index)
        return int(percent * 255 / 100) if percent is not None else None

    @property
    @override
    def color_mode(self) -> ColorMode:
        return ColorMode.RGB

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        if kwargs.get(ATTR_BRIGHTNESS) == 0:
            await self.async_turn_off()
            return

        # Ensure the main light is on first
        if not self._coordinator.device_state.power:
            await self._coordinator.set_power(True)

        if ATTR_RGB_COLOR in kwargs or ATTR_BRIGHTNESS not in kwargs or not self.is_on:
            r, g, b = kwargs.get(
                ATTR_RGB_COLOR, self._coordinator.get_bulb_restore_color(self._bulb_index)
            )
            await self._coordinator.set_bulb(self._bulb_index, r, g, b)

        if ATTR_BRIGHTNESS in kwargs:
            percent = max(1, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255))
            await self._coordinator.set_bulb_brightness(self._bulb_index, percent)
        self.async_write_ha_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        # "Turning off" a single bulb = set it to black (0,0,0)
        await self._coordinator.set_bulb(self._bulb_index, 0, 0, 0)
        self.async_write_ha_state()
