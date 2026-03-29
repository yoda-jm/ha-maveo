"""Maveo Home Assistant integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .auth import authenticate, AuthError
from .client import MaveoClient, APIError
from .config import Region, get_config
from .const import DOMAIN, PLATFORMS, SERVICE_CREATE_GUEST, SERVICE_REMOVE_GUEST
from .coordinator import MaveoDeviceCoordinator
from .guest_coordinator import MaveoGuestCoordinator
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Maveo from a config entry."""
    email = entry.data["email"]
    password = entry.data["password"]
    region = Region(entry.data.get("region", "EU"))
    config = get_config(region)

    try:
        auth = await hass.async_add_executor_job(
            authenticate, email, password, config
        )
    except AuthError as err:
        raise ConfigEntryNotReady(f"Authentication failed: {err}") from err

    client = MaveoClient(auth, config)

    try:
        devices = await hass.async_add_executor_job(client.list_devices)
    except APIError as err:
        raise ConfigEntryNotReady(f"Failed to list devices: {err}") from err

    if not devices:
        _LOGGER.warning("No Maveo devices found for account %s", email)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "auth":              auth,
        "email":             email,
        "password":          password,
        "config":            config,
        "client":            client,
        "devices":           {d.id: d for d in devices},
        "coordinators":      {},
        "guest_coordinators": {},
    }

    for device in devices:
        coord = MaveoDeviceCoordinator(hass, entry, device.id)
        await coord.async_config_entry_first_refresh()
        hass.data[DOMAIN][entry.entry_id]["coordinators"][device.id] = coord

        guest_coord = MaveoGuestCoordinator(hass, entry, device.id)
        await guest_coord.async_config_entry_first_refresh()
        hass.data[DOMAIN][entry.entry_id]["guest_coordinators"][device.id] = guest_coord

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
