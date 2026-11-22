"""Config flow for the Maveo integration.

The entry stores the password and the Cognito refresh token. The refresh token
renews credentials; the password signs in again when the refresh token is
rejected. Reauth asks for the password only when Cognito rejects it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from .auth import AuthError, AuthResult, CloudError, login
from .config import Region, get_config
from .const import CONF_REFRESH_TOKEN, CONF_REGION, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_EMAIL): str,
        probatio.Required(CONF_PASSWORD): str,
        probatio.Optional(CONF_REGION, default=Region.EU.value): probatio.In(
            [r.value for r in Region]
        ),
    }
)

STEP_REAUTH_SCHEMA = probatio.Schema({probatio.Required(CONF_PASSWORD): str})


class MaveoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Maveo."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            email: str = user_input[CONF_EMAIL]
            region = Region(user_input[CONF_REGION])
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            password: str = user_input[CONF_PASSWORD]
            auth = await self._async_login(email, password, region, errors)
            if auth is not None:
                return self.async_create_entry(
                    title=email,
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                        CONF_REGION: region.value,
                        CONF_REFRESH_TOKEN: auth.refresh_token,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        email: str = entry.data[CONF_EMAIL]

        if user_input is not None:
            region = Region(entry.data.get(CONF_REGION, Region.EU))
            password: str = user_input[CONF_PASSWORD]
            auth = await self._async_login(email, password, region, errors)
            if auth is not None:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                        CONF_REGION: region.value,
                        CONF_REFRESH_TOKEN: auth.refresh_token,
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            description_placeholders={CONF_EMAIL: email},
            errors=errors,
        )

    async def _async_login(
        self, email: str, password: str, region: Region, errors: dict[str, str]
    ) -> AuthResult | None:
        """Sign in, recording a form error and returning None on failure."""
        try:
            return await self.hass.async_add_executor_job(
                login, email, password, get_config(region)
            )
        except AuthError:
            errors["base"] = "invalid_auth"
        except CloudError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error during Maveo sign-in")
            errors["base"] = "unknown"
        return None
