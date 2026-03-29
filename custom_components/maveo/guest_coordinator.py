"""Guest list coordinator — REST poll every 60 s."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import GuestUser
from .const import DOMAIN, GUEST_POLL_INTERVAL

_LOGGER = logging.getLogger(__name__)


class MaveoGuestCoordinator(DataUpdateCoordinator[list[GuestUser]]):
    """Coordinator for the guest list of a single Maveo device."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"Maveo guests {device_id}",
            update_interval=timedelta(seconds=GUEST_POLL_INTERVAL),
        )
        self._entry = entry
        self.device_id = device_id

    async def _async_update_data(self) -> list[GuestUser]:
        client = self.hass.data[DOMAIN][self._entry.entry_id]["client"]
        try:
            return await self.hass.async_add_executor_job(
                client.list_guest_users, self.device_id
            )
        except Exception as err:
            raise UpdateFailed(f"Failed to fetch guests for {self.device_id}: {err}") from err
