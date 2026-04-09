"""Config flow for the Maveo integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .auth import authenticate, AuthError
from .config import Region, get_config
from .const import DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
        vol.Optional("region", default="EU"): vol.In(["EU", "US"]),
    }
)


class MaveoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Maveo."""

    VERSION = 1

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
