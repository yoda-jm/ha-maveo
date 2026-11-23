"""Maveo admin services — create and remove guest keys.

A guest link grants access to the garage door, so both services are
admin-only and the link is only returned in the service response.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import probatio
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service import async_register_admin_service

from .api import (
    RIGHTS_ADMIN,
    RIGHTS_RESTRICTED,
    APIError,
    AuthError,
    CloudError,
    build_guest_link,
)
from .const import DOMAIN, SERVICE_CREATE_GUEST, SERVICE_REMOVE_GUEST
from .data import MaveoData, MaveoDevice

_LOGGER = logging.getLogger(__name__)

ATTR_DEVICE_ID = "device_id"

_CREATE_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_DEVICE_ID): cv.string,
        probatio.Optional("ttl_hours", default=24): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1, max=720)
        ),
        probatio.Optional("admin", default=False): cv.boolean,
    }
)

_REMOVE_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_DEVICE_ID): cv.string,
        probatio.Required("user_id"): cv.string,
    }
)


def _find_device(
    hass: HomeAssistant, ha_device_id: str
) -> tuple[MaveoData, MaveoDevice]:
    """Resolve a Home Assistant device ID to its loaded Maveo device."""
    device_entry = dr.async_get(hass).async_get(ha_device_id)
    if device_entry is not None:
        maveo_ids = {i for d, i in device_entry.identifiers if d == DOMAIN}
        for entry in hass.config_entries.async_entries(DOMAIN):
            if (
                entry.state is not ConfigEntryState.LOADED
                or entry.entry_id not in device_entry.config_entries
            ):
                continue
            data: MaveoData = entry.runtime_data
            for maveo_id in maveo_ids:
                if maveo_id in data.devices:
                    return data, data.devices[maveo_id]
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="device_not_found",
        translation_placeholders={"device_id": ha_device_id},
    )


async def _async_ensure_session(data: MaveoData) -> None:
    try:
        await data.session.async_ensure_valid()
    except (AuthError, CloudError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="cloud_unreachable",
            translation_placeholders={"error": str(err)},
        ) from err


def async_register_services(hass: HomeAssistant) -> None:
    """Register the Maveo admin services."""

    async def _create_guest(call: ServiceCall) -> ServiceResponse:
        ttl_hours: int = call.data["ttl_hours"]
        rights = RIGHTS_ADMIN if call.data["admin"] else RIGHTS_RESTRICTED

        data, device = _find_device(hass, call.data[ATTR_DEVICE_ID])
        await _async_ensure_session(data)
        device_id = device.info.id

        try:
            guest = await data.session.client.add_guest_user(
                device_id, ttl_hours * 3600, rights
            )
        except APIError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="guest_create_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        # Share link carries the garage name and GPS from the device coordinator
        state = device.state.data or {}
        lat: float = state.get("gps_lat") or 0.0
        lng: float = state.get("gps_lng") or 0.0
        name: str = state.get("device_name") or device.info.name
        link = build_guest_link(
            guest, device_id, name, location_name=name, latitude=lat, longitude=lng
        )

        await device.guests.async_request_refresh()

        _LOGGER.info(
            "Guest key %s created for device %s (rights=%s, ttl=%dh)",
            guest.user_id,
            device_id,
            rights,
            ttl_hours,
        )
        expires_at = (
            datetime.fromtimestamp(int(guest.ttl), tz=UTC).isoformat()
            if guest.ttl.isdigit()
            else None
        )
        return {"user_id": guest.user_id, "link": link, "expires_at": expires_at}

    async def _remove_guest(call: ServiceCall) -> None:
        user_id: str = call.data["user_id"]

        data, device = _find_device(hass, call.data[ATTR_DEVICE_ID])
        await _async_ensure_session(data)

        try:
            await data.session.client.remove_guest_user(device.info.id, user_id)
        except APIError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="guest_remove_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        await device.guests.async_request_refresh()
        _LOGGER.info("Guest key %s removed from device %s", user_id, device.info.id)

    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_CREATE_GUEST,
        _create_guest,
        schema=_CREATE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    async_register_admin_service(
        hass, DOMAIN, SERVICE_REMOVE_GUEST, _remove_guest, schema=_REMOVE_SCHEMA
    )
