"""The Govee H7015 BLE integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Final

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, HomeAssistantError, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import (
    ATTR_BULB,
    ATTR_RGB,
    ATTR_SCENE_NAME,
    CONF_MAC,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    SERVICE_SET_BULB,
    SERVICE_SNAPSHOT_SCENE,
)
from .coordinator import H7015Coordinator
from .options_flow import H7015OptionsFlow

_LOGGER = logging.getLogger(__name__)

PLATFORMS: Final = (Platform.LIGHT,)

SET_BULB_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_BULB): vol.All(vol.Coerce(int), vol.Range(min=0, max=14)),
        vol.Required(ATTR_RGB): vol.All(
            vol.ExactSequence([vol.Coerce(int)] * 3),
            vol.All(lambda v: [max(0, min(255, x)) for x in v]),
        ),
        vol.Optional("device_id"): vol.Any(str, [str]),
    }
)

SNAPSHOT_SCENE_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_SCENE_NAME): str,
        vol.Optional("device_id"): vol.Any(str, [str]),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    coordinator = H7015Coordinator(
        hass,
        mac=entry.data[CONF_MAC],
        name=entry.data.get(CONF_NAME, DEFAULT_NAME),
        poll_interval=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        entry_id=entry.entry_id,
        config_entry=entry,
    )

    # Store the coordinator BEFORE the first refresh so that
    # async_unload_entry can find and clean it up if the refresh fails.
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # First refresh failed — clean up the coordinator we just stored
        # so we don't leak the BLE connection / keepalive task.
        hass.data[DOMAIN].pop(entry.entry_id, None)
        await coordinator.shutdown()
        raise

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once for all entries.
    if not hass.services.has_service(DOMAIN, SERVICE_SET_BULB):
        hass.services.async_register(
            DOMAIN, SERVICE_SET_BULB, _handle_set_bulb, schema=SET_BULB_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SNAPSHOT_SCENE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SNAPSHOT_SCENE,
            _handle_snapshot_scene,
            schema=SNAPSHOT_SCENE_SCHEMA,
        )

    # Reload entry when options change
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_get_options_flow(
    config_entry: ConfigEntry,
) -> H7015OptionsFlow:
    """Get the options flow for this integration."""
    return H7015OptionsFlow()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coord = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coord:
            await coord.shutdown()
    # Only remove services when the last entry is unloaded.
    if not hass.data.get(DOMAIN):
        if hass.services.has_service(DOMAIN, SERVICE_SET_BULB):
            hass.services.async_remove(DOMAIN, SERVICE_SET_BULB)
        if hass.services.has_service(DOMAIN, SERVICE_SNAPSHOT_SCENE):
            hass.services.async_remove(DOMAIN, SERVICE_SNAPSHOT_SCENE)
    return unload_ok


async def _handle_set_bulb(call: ServiceCall) -> None:
    """Handle the set_bulb service call.

    Routes to the correct coordinator(s) based on the call's target device IDs.
    Requires a target — if no target is specified, raises an error (rather than
    silently applying to ALL configured H7015s, which is almost never intended).
    """
    bulb: int = call.data[ATTR_BULB]
    rgb: list[int] = call.data[ATTR_RGB]
    r, g, b = rgb[0], rgb[1], rgb[2]

    hass = call.hass
    coordinators: dict[str, H7015Coordinator] = hass.data.get(DOMAIN, {})

    # Determine target device IDs — require at least one target.
    target_device_ids = getattr(call, "target_device_ids", None)
    if not target_device_ids:
        raw = call.data.get("device_id", [])
        target_device_ids = [raw] if isinstance(raw, str) else list(raw)

    if not target_device_ids:
        raise HomeAssistantError(
            "set_bulb requires a target device. Specify which H7015 to control "
            "via the service call target."
        )

    # Map target device IDs back to coordinators via the device registry.
    dev_reg = dr.async_get(hass)
    target_coordinators: list[H7015Coordinator] = []
    for dev_id in target_device_ids:
        dev = dev_reg.async_get(dev_id)
        if dev is None:
            continue
        coord = _find_coordinator_for_device(dev, coordinators)
        if coord:
            target_coordinators.append(coord)

    if not target_coordinators:
        raise HomeAssistantError(
            f"No Govee H7015 coordinator found for target device(s): {target_device_ids}"
        )

    # Apply to all target coordinators in parallel, catching per-device errors
    # so one failure doesn't prevent the others from updating.
    async def _safe_set_bulb(coord: H7015Coordinator) -> None:
        try:
            await coord.set_bulb(bulb, r, g, b)
            # Notify listeners so per-bulb entities refresh their state.
            # Without this, the bulb entity UI won't update until the next poll.
            coord.async_update_listeners()
        except Exception as exc:
            _LOGGER.error("set_bulb failed for %s: %s", coord.mac, exc)

    await asyncio.gather(
        *[_safe_set_bulb(c) for c in target_coordinators],
    )


async def _handle_snapshot_scene(call: ServiceCall) -> None:
    """Handle the snapshot_scene service call.

    Snapshots the current per-bulb colors and creates a HA scene using
    the built-in scene.create service. The scene can then be activated
    from the dashboard, automations, or voice commands.

    Requires a target device (same as set_bulb) and a scene name.
    """
    scene_name: str = call.data[ATTR_SCENE_NAME]

    hass = call.hass
    coordinators: dict[str, H7015Coordinator] = hass.data.get(DOMAIN, {})

    # Determine target device IDs — require at least one target.
    target_device_ids = getattr(call, "target_device_ids", None)
    if not target_device_ids:
        raw = call.data.get("device_id", [])
        target_device_ids = [raw] if isinstance(raw, str) else list(raw)

    if not target_device_ids:
        raise HomeAssistantError(
            "snapshot_scene requires a target device. Specify which H7015 to "
            "snapshot via the service call target."
        )

    # Map target device IDs to coordinators
    dev_reg = dr.async_get(hass)
    target_coordinators: list[H7015Coordinator] = []
    for dev_id in target_device_ids:
        dev = dev_reg.async_get(dev_id)
        if dev is None:
            continue
        coord = _find_coordinator_for_device(dev, coordinators)
        if coord:
            target_coordinators.append(coord)

    if not target_coordinators:
        raise HomeAssistantError(
            f"No Govee H7015 coordinator found for target device(s): {target_device_ids}"
        )

    # Build the entities dict for scene.create.
    # We look up actual entity IDs from the entity registry rather than
    # guessing, because HA generates entity_id from the device name (e.g.
    # "Patio Lights" → light.patio_lights), not from the unique_id.
    from homeassistant.helpers import entity_registry as er

    ent_reg = er.async_get(hass)
    entities: dict[str, dict[str, object]] = {}

    for coord in target_coordinators:
        # Find all entities for this config entry
        entry_entities = er.async_entries_for_config_entry(ent_reg, coord.entry_id)

        # Find the main light entity and bulb entities
        main_entity_id: str | None = None
        bulb_entity_ids: dict[int, str] = {}  # bulb_index -> entity_id

        for ent in entry_entities:
            if not ent.domain == "light":
                continue
            # Bulb entities have "_bulb_" in their unique_id
            if "_bulb_" in ent.unique_id:
                # Extract bulb index from unique_id (0-indexed)
                try:
                    idx = int(ent.unique_id.rsplit("_bulb_", 1)[1])
                    bulb_entity_ids[idx] = ent.entity_id
                except (ValueError, IndexError):
                    continue
            else:
                main_entity_id = ent.entity_id

        # Main light entity — ensure it's on
        if main_entity_id:
            entities[main_entity_id] = {"state": "on"}

        # Per-bulb entities
        bulb_colors = coord.get_all_bulb_colors()
        for bulb_index, entity_id in bulb_entity_ids.items():
            rgb = bulb_colors.get(bulb_index)
            if rgb is None or rgb == (0, 0, 0):
                entities[entity_id] = {"state": "off"}
            else:
                entities[entity_id] = {
                    "state": "on",
                    "rgb_color": list(rgb),
                }

    # Create the scene via HA's built-in scene.create service
    await hass.services.async_call(
        "scene",
        "create",
        {
            "name": scene_name,
            "entities": entities,
        },
        blocking=True,
    )

    _LOGGER.info(
        "Created HA scene %r from %d H7015 device(s) with %d entities",
        scene_name,
        len(target_coordinators),
        len(entities),
    )


def _find_coordinator_for_device(
    dev: dr.DeviceEntry, coordinators: dict[str, H7015Coordinator]
) -> H7015Coordinator | None:
    """Find the coordinator whose MAC matches a device registry entry."""
    for ident_set in dev.identifiers:
        if len(ident_set) != 2 or ident_set[0] != DOMAIN:
            continue
        mac_id = ident_set[1]  # uppercased, no colons
        for coord in coordinators.values():
            if coord.mac.replace(":", "").upper() == mac_id:
                return coord
    return None
