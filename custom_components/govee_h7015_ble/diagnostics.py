"""Diagnostics platform for the Govee H7015 BLE integration.

Lets users download diagnostic data for bug reports via
Settings → Devices & Services → Govee H7015 BLE → Download diagnostics.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import DOMAIN
from .coordinator import H7015Coordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: H7015Coordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )

    data: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
            "version": entry.version,
        },
    }

    if coordinator:
        state = coordinator.device_state
        data["device"] = {
            "mac": coordinator.mac,
            "name": coordinator.name,
            "state": {
                "power": state.power,
                "brightness": state.brightness,
                "rgb": state.rgb,
                "mode": state.mode,
                "raw": state.raw.hex() if state.raw else None,
            },
            "connected": coordinator.is_connected,
            "keepalive_running": coordinator.keepalive_running,
        }

    return data


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a device."""
    return await async_get_config_entry_diagnostics(hass, entry)
