"""Config flow for the Maveo integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .auth import authenticate, AuthError
from .config import Region, get_config
from .const import COMMAND_MODE_DIRECT, COMMAND_MODE_TOGGLE, CONF_COMMAND_MODE, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
        vol.Optional("region", default="EU"): vol.In(["EU", "US"]),
    }
)


class MaveoOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Maveo — one command_mode setting per garage door device."""

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        devices = self.hass.data[DOMAIN][self.config_entry.entry_id]["devices"]
        # devices: {device_id: Device}

        if user_input is not None:
            # user_input keys are device names; map back to device_id for storage
            name_to_id = {d.name: d.id for d in devices.values()}
            new_options = {
                name_to_id[name]: {CONF_COMMAND_MODE: mode}
                for name, mode in user_input.items()
            }
            return self.async_create_entry(data=new_options)

        schema_dict = {}
        for device in devices.values():
            current = self.config_entry.options.get(device.id, {}).get(
                CONF_COMMAND_MODE, COMMAND_MODE_DIRECT
            )
            schema_dict[vol.Optional(device.name, default=current)] = vol.In(
                [COMMAND_MODE_DIRECT, COMMAND_MODE_TOGGLE]
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
        )


class MaveoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Maveo."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> MaveoOptionsFlow:
        return MaveoOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                config = get_config(Region(user_input["region"]))
                await self.hass.async_add_executor_job(
                    authenticate,
                    user_input["email"],
                    user_input["password"],
                    config,
                )
            except AuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input["email"].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input["email"],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
