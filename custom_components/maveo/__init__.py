"""Maveo Home Assistant integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .api import AuthError, CloudError, Device, Region, get_config
from .const import CONF_REGION, DOMAIN, PLATFORMS
from .coordinator import (
    MaveoAccountCoordinator,
    MaveoDeviceCoordinator,
    MaveoGuestCoordinator,
)
from .data import MaveoConfigEntry, MaveoData, MaveoDevice
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

    try:
        session = await MaveoSession.async_sign_in(hass, entry, config)
    except AuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    except CloudError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cloud_unreachable",
            translation_placeholders={"error": str(err)},
        ) from err

    account = MaveoAccountCoordinator(hass, entry, session)
    await account.async_config_entry_first_refresh()

    data = MaveoData(session=session, account=account)
    for device in account.data.values():
        data.devices[device.id] = await _async_create_device(
            hass, entry, session, device, first_setup=True
        )
    entry.runtime_data = data

    if not data.devices:
        _LOGGER.warning("No Maveo devices found for %s", entry.title)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _account_updated() -> None:
        hass.async_create_task(_async_sync_devices(hass, entry), eager_start=True)

    entry.async_on_unload(account.async_add_listener(_account_updated))
    entry.async_on_unload(data.async_remove_all)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MaveoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MaveoConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing a device that is no longer on the Maveo account."""
    return not any(
        domain == DOMAIN and device_id in entry.runtime_data.devices
        for domain, device_id in device_entry.identifiers
    )


async def _async_create_device(
    hass: HomeAssistant,
    entry: MaveoConfigEntry,
    session: MaveoSession,
    device: Device,
    *,
    first_setup: bool,
) -> MaveoDevice:
    state = MaveoDeviceCoordinator(hass, entry, session, device.id)
    guests = MaveoGuestCoordinator(hass, entry, session, device.id)
    if first_setup:
        await state.async_config_entry_first_refresh()
        await guests.async_config_entry_first_refresh()
    else:
        await state.async_refresh()
        await guests.async_refresh()
    return MaveoDevice(info=device, state=state, guests=guests)


async def _async_sync_devices(hass: HomeAssistant, entry: MaveoConfigEntry) -> None:
    """Add sticks that joined the account and remove those that left it."""
    data = entry.runtime_data
    if not data.account.last_update_success:
        return
    account_devices = data.account.data

    for device_id in account_devices.keys() - data.devices.keys():
        device = await _async_create_device(
            hass, entry, data.session, account_devices[device_id], first_setup=False
        )
        data.async_device_added(device)

    registry = dr.async_get(hass)
    for device_id in data.devices.keys() - account_devices.keys():
        data.async_device_removed(device_id)
        device_entry = registry.async_get_device_by_identifier(
            (DOMAIN, device_id), entry.entry_id
        )
        if device_entry is not None:
            registry.async_update_device(
                device_entry.id, remove_config_entry_id=entry.entry_id
            )
