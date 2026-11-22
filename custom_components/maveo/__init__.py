"""Maveo Home Assistant integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .auth import AuthError, CloudError
from .client import APIError
from .config import Region, get_config
from .const import CONF_REGION, DOMAIN, PLATFORMS
from .coordinator import MaveoDeviceCoordinator
from .data import MaveoConfigEntry, MaveoData
from .guest_coordinator import MaveoGuestCoordinator
from .services import async_register_services
from .session import MaveoSession

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the Maveo services."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MaveoConfigEntry) -> bool:
    """Set up Maveo from a config entry."""
    config = get_config(Region(entry.data.get(CONF_REGION, Region.EU)))
    session = MaveoSession(hass, entry, config)

    try:
        await session.async_ensure_valid()
    except AuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except CloudError as err:
        raise ConfigEntryNotReady(str(err)) from err

    try:
        devices = await hass.async_add_executor_job(session.client.list_devices)
    except APIError as err:
        raise ConfigEntryNotReady(f"Failed to list devices: {err}") from err

    if not devices:
        _LOGGER.warning("No Maveo devices found for %s", entry.title)

    data = MaveoData(session=session, devices={d.id: d for d in devices})
    for device in devices:
        coord = MaveoDeviceCoordinator(hass, entry, session, device.id)
        await coord.async_config_entry_first_refresh()
        data.coordinators[device.id] = coord

        guest_coord = MaveoGuestCoordinator(hass, entry, session, device.id)
        await guest_coord.async_config_entry_first_refresh()
        data.guest_coordinators[device.id] = guest_coord

    entry.runtime_data = data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MaveoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
