"""Config flow for the Govee H7015 BLE integration."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Final, override

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_MAC, CONF_NAME

from homeassistant import config_entries

from .const import DEFAULT_NAME, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

_LOGGER = logging.getLogger(__name__)

# Accept AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, or AABBCCDDEEFF (case-insensitive)
_MAC_RE: Final = re.compile(r"^[A-F0-9]{2}([:-]?[A-F0-9]{2}){5}$", re.IGNORECASE)


def _is_h7015(service_info: BluetoothServiceInfoBleak) -> bool:
    """Match H7015 by name pattern only.

    We deliberately do NOT match on SERVICE_UUID alone because the Govee
    RGBIC BLE service UUID (00010203-...) is shared across the entire Govee
    RGBIC family (H6054, H6113, H6127, H617A, H7015, H7020, etc.). Matching
    on UUID would offer non-H7015 devices in the discovery list, and the
    H7015 protocol may not work correctly on other models.
    """
    name = (service_info.name or "").upper()
    return name.startswith("H7015")


def _normalize_mac(mac: str) -> str:
    """Return MAC in AA:BB:CC:DD:EE:FF form.

    Raises ValueError on bad format. Called from the config flow, which
    surfaces the error as a validation error to the user.
    """
    mac = mac.strip().upper().replace("-", ":")
    if ":" not in mac and len(mac) == 12:
        mac = ":".join(mac[i : i + 2] for i in range(0, 12, 2))
    if not _MAC_RE.match(mac):
        raise ValueError(f"invalid MAC address: {mac!r}")
    return mac


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Govee H7015 BLE."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    @override
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle discovery via Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        if not _is_h7015(discovery_info):
            return self.async_abort(reason="not_supported")

        name = discovery_info.name or DEFAULT_NAME
        self._discovered[discovery_info.address] = discovery_info
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm discovery."""
        address = self.unique_id or ""
        name = self._discovered[address].name if address in self._discovered else DEFAULT_NAME
        if user_input is not None:
            return self.async_create_entry(
                title=name,
                data={CONF_MAC: address, CONF_NAME: name},
            )
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": name, "address": address},
        )

    @override
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manual setup when no discovery happened."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                mac = _normalize_mac(user_input[CONF_MAC])
            except ValueError:
                errors[CONF_MAC] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, DEFAULT_NAME),
                    data={
                        CONF_MAC: mac,
                        CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
                    },
                )

        # Build a list of discovered devices that match the H7015 pattern.
        for service_info in async_discovered_service_info(self.hass):
            if service_info.address in self._discovered:
                continue
            if _is_h7015(service_info):
                self._discovered[service_info.address] = service_info

        if self._discovered and not errors:
            choices = {addr: f"{info.name} ({addr})" for addr, info in self._discovered.items()}
            data_schema = vol.Schema(
                {
                    vol.Required(CONF_MAC): vol.In(choices),
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                }
            )
        else:
            data_schema = vol.Schema(
                {
                    vol.Required(CONF_MAC): str,
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                }
            )
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow reconfiguring the MAC address without removing the entry.

        Useful if the H7015 is replaced (new MAC) or if the MAC was
        entered incorrectly during initial setup.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                mac = _normalize_mac(user_input[CONF_MAC])
            except ValueError:
                errors[CONF_MAC] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data_updates={
                        CONF_MAC: mac,
                        CONF_NAME: user_input.get(CONF_NAME, DEFAULT_NAME),
                    },
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_MAC): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=data_schema, errors=errors)
