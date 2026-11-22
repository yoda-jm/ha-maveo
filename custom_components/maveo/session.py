"""Cloud session shared by all coordinators of one config entry."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .auth import AuthError, AuthResult, login, refresh
from .client import MaveoClient
from .config import Config
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

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, config: Config) -> None:
        self._hass = hass
        self._entry = entry
        self._lock = asyncio.Lock()
        self.config = config
        self._auth: AuthResult | None = None
        self._client: MaveoClient | None = None

    @property
    def auth(self) -> AuthResult:
        if self._auth is None:
            raise RuntimeError("Maveo session has not signed in")
        return self._auth

    @property
    def client(self) -> MaveoClient:
        if self._client is None:
            raise RuntimeError("Maveo session has not signed in")
        return self._client

    async def async_ensure_valid(self) -> None:
        """Sign in or renew credentials close to expiry.

        Raises AuthError when no stored credential is accepted, or CloudError.
        """
        async with self._lock:
            if (
                self._auth is not None
                and self._auth.expiration - _RENEW_MARGIN > datetime.now(UTC)
            ):
                return
            refresh_token = (
                self._auth.refresh_token
                if self._auth is not None
                else self._entry.data.get(CONF_REFRESH_TOKEN)
            )
            auth = await self._hass.async_add_executor_job(
                self._sign_in,
                refresh_token,
                self._entry.data.get(CONF_EMAIL),
                self._entry.data.get(CONF_PASSWORD),
            )
            self._auth = auth
            self._client = MaveoClient(auth, self.config)
            if self._entry.data.get(CONF_REFRESH_TOKEN) != auth.refresh_token:
                self._hass.config_entries.async_update_entry(
                    self._entry,
                    data={**self._entry.data, CONF_REFRESH_TOKEN: auth.refresh_token},
                )

    def _sign_in(
        self, refresh_token: str | None, email: str | None, password: str | None
    ) -> AuthResult:
        if refresh_token:
            try:
                return refresh(refresh_token, self.config)
            except AuthError:
                if not (email and password):
                    raise
                _LOGGER.info("Maveo refresh token rejected; signing in with password")
        if not (email and password):
            raise AuthError("No stored Maveo credentials")
        return login(email, password, self.config)
