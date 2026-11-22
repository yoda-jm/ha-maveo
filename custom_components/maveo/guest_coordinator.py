"""Guest list coordinator — REST poll every 60 s."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .auth import AuthError, CloudError
from .client import APIError, GuestUser
from .const import GUEST_POLL_INTERVAL
from .session import MaveoSession

_LOGGER = logging.getLogger(__name__)


class MaveoGuestCoordinator(DataUpdateCoordinator[list[GuestUser]]):
    """Coordinator for the guest list of a single Maveo device."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        session: MaveoSession,
        device_id: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Maveo guests {device_id}",
            update_interval=timedelta(seconds=GUEST_POLL_INTERVAL),
        )
        self._session = session
        self.device_id = device_id

    async def _async_update_data(self) -> list[GuestUser]:
        try:
            await self._session.async_ensure_valid()
            return await self.hass.async_add_executor_job(
                self._session.client.list_guest_users, self.device_id
            )
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (CloudError, APIError) as err:
            raise UpdateFailed(
                f"Failed to fetch guests for {self.device_id}: {err}"
            ) from err
