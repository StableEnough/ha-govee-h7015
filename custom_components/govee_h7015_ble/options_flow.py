"""Options flow for the Govee H7015 BLE integration.

Lets users change the poll interval from the UI without deleting and
re-adding the integration.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode

from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL


class H7015OptionsFlow(OptionsFlow):
    """Options flow for Govee H7015 BLE."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        current_interval = self.config_entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)

        if user_input is not None:
            return self.async_create_entry(
                title="", data={CONF_POLL_INTERVAL: user_input[CONF_POLL_INTERVAL]}
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=current_interval,
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=5,
                        max=3600,
                        step=5,
                        unit_of_measurement="seconds",
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
