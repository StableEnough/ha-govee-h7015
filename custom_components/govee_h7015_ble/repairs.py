"""Repair issues for the Govee H7015 BLE integration.

Creates HA repair issues when the device hasn't been seen or connected
for an extended period, giving users actionable guidance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

ISSUE_DEVICE_UNREACHABLE = "device_unreachable"


def create_unreachable_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create a repair issue when the H7015 hasn't been reachable.

    Uses translation_key so the issue text is defined in strings.json.
    """
    mac = entry.data.get("mac", "")
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{ISSUE_DEVICE_UNREACHABLE}_{entry.entry_id}",
        data={"entry_id": entry.entry_id, "mac": mac},
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="device_unreachable",
        translation_placeholders={"mac": mac},
    )
    _LOGGER.info("Created unreachable repair issue for %s", entry.entry_id)


def delete_unreachable_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the repair issue when the device comes back online."""
    ir.async_delete_issue(
        hass,
        DOMAIN,
        f"{ISSUE_DEVICE_UNREACHABLE}_{entry.entry_id}",
    )
    _LOGGER.info("Deleted unreachable repair issue for %s", entry.entry_id)
