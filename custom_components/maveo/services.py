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
from homeassistant.helpers.service import async_register_admin_service

from .auth import AuthError, CloudError
from .client import RIGHTS_ADMIN, RIGHTS_RESTRICTED, APIError
from .const import DOMAIN, SERVICE_CREATE_GUEST, SERVICE_REMOVE_GUEST
from .data import MaveoData

_LOGGER = logging.getLogger(__name__)

_CREATE_SCHEMA = probatio.Schema(
    {
        probatio.Required("device_id"): cv.string,
        probatio.Optional("ttl_hours", default=24): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1, max=720)
        ),
        probatio.Optional("admin", default=False): cv.boolean,
    }
)

_REMOVE_SCHEMA = probatio.Schema(
    {
        probatio.Required("device_id"): cv.string,
        probatio.Required("user_id"): cv.string,
    }
)


def _find_entry_data(hass: HomeAssistant, device_id: str) -> MaveoData:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        data: MaveoData = entry.runtime_data
        if device_id in data.devices:
            return data
    raise ServiceValidationError(f"Maveo device {device_id} not found")


async def _async_ensure_session(data: MaveoData) -> None:
    try:
        await data.session.async_ensure_valid()
    except (AuthError, CloudError) as err:
        raise HomeAssistantError(f"Maveo sign-in failed: {err}") from err


def async_register_services(hass: HomeAssistant) -> None:
    """Register the Maveo admin services."""

    async def _create_guest(call: ServiceCall) -> ServiceResponse:
        device_id: str = call.data["device_id"]
        ttl_hours: int = call.data["ttl_hours"]
        rights = RIGHTS_ADMIN if call.data["admin"] else RIGHTS_RESTRICTED

        data = _find_entry_data(hass, device_id)
        await _async_ensure_session(data)
        client = data.session.client

        try:
            guest = await hass.async_add_executor_job(
                client.add_guest_user, device_id, ttl_hours * 3600, rights
            )
        except APIError as err:
            raise HomeAssistantError(f"Failed to create guest key: {err}") from err

        # Share link carries the garage name and GPS from the device coordinator
        device_coord = data.coordinators.get(device_id)
        device_data = (device_coord.data or {}) if device_coord else {}
        lat: float = device_data.get("gps_lat") or 0.0
        lng: float = device_data.get("gps_lng") or 0.0
        name: str = device_data.get("device_name") or data.devices[device_id].name

        link = client.generate_guest_link(
            guest, device_id, name, location_name=name, latitude=lat, longitude=lng
        )

        guest_coord = data.guest_coordinators.get(device_id)
        if guest_coord:
            await guest_coord.async_request_refresh()

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
        device_id: str = call.data["device_id"]
        user_id: str = call.data["user_id"]

        data = _find_entry_data(hass, device_id)
        await _async_ensure_session(data)

        try:
            await hass.async_add_executor_job(
                data.session.client.remove_guest_user, device_id, user_id
            )
        except APIError as err:
            raise HomeAssistantError(f"Failed to remove guest key: {err}") from err

        guest_coord = data.guest_coordinators.get(device_id)
        if guest_coord:
            await guest_coord.async_request_refresh()

        _LOGGER.info("Guest key %s removed from device %s", user_id, device_id)

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
