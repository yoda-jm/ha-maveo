"""Cloud session shared by all coordinators of one config entry."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthError, AuthResult, Config, MaveoClient, login, refresh
from .const import CONF_REFRESH_TOKEN

_LOGGER = logging.getLogger(__name__)

# AWS credentials are renewed this long before they expire.
_RENEW_MARGIN = timedelta(minutes=10)


class MaveoSession:
    """Current credentials and REST client for one config entry.

    Credentials are renewed with the refresh token. When Cognito rejects it,
    the session signs in again with the stored password, so the user is only
    asked to reauthenticate when the password itself is rejected.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        config: Config,
        http: aiohttp.ClientSession,
        auth: AuthResult,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._lock = asyncio.Lock()
        self.config = config
        self.http = http
        self.auth = auth
        self.client = MaveoClient(http, auth, config)
        self._store_refresh_token()

    @classmethod
    async def async_sign_in(
        cls, hass: HomeAssistant, entry: ConfigEntry, config: Config
    ) -> MaveoSession:
        """Sign in with the stored credentials. Raises AuthError or CloudError."""
        http = async_get_clientsession(hass)
        auth = await _async_sign_in(
            http, config, entry.data.get(CONF_REFRESH_TOKEN), entry
        )
        return cls(hass, entry, config, http, auth)

    async def async_ensure_valid(self) -> None:
        """Renew credentials close to expiry. Raises AuthError or CloudError."""
        async with self._lock:
            if self.auth.expiration - _RENEW_MARGIN > datetime.now(UTC):
                return
            self.auth = await _async_sign_in(
                self.http, self.config, self.auth.refresh_token, self._entry
            )
            self.client = MaveoClient(self.http, self.auth, self.config)
            self._store_refresh_token()

    def _store_refresh_token(self) -> None:
        """Persist the refresh token when Cognito has issued a new one."""
        if self._entry.data.get(CONF_REFRESH_TOKEN) != self.auth.refresh_token:
            self._hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, CONF_REFRESH_TOKEN: self.auth.refresh_token},
            )


async def _async_sign_in(
    http: aiohttp.ClientSession,
    config: Config,
    refresh_token: str | None,
    entry: ConfigEntry,
) -> AuthResult:
    """Use the refresh token, falling back to the stored password.

    Entries made before refresh tokens were stored have none, so they start
    with the password.
    """
    if refresh_token:
        try:
            return await refresh(http, refresh_token, config)
        except AuthError:
            _LOGGER.info("Maveo refresh token rejected; signing in with password")
    email: str = entry.data[CONF_EMAIL]
    password: str = entry.data[CONF_PASSWORD]
    return await login(http, email, password, config)
