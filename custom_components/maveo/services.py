"""Maveo services — create and remove guest keys."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .client import RIGHTS_ADMIN, RIGHTS_RESTRICTED
from .const import DOMAIN, SERVICE_CREATE_GUEST, SERVICE_REMOVE_GUEST

_LOGGER = logging.getLogger(__name__)

_CREATE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Optional("ttl_hours", default=24): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=720)
        ),
        vol.Optional("admin", default=False): cv.boolean,
    }
)

_REMOVE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("user_id"): cv.string,
    }
)


def _find_entry_data(hass: HomeAssistant, device_id: str) -> dict | None:
    for entry_id, data in hass.data.get(DOMAIN, {}).items():
        if device_id in data.get("devices", {}):
            return data
    return None


def async_register_services(hass: HomeAssistant) -> None:
    """Register Maveo services (idempotent — safe to call on each entry setup)."""

    if hass.services.has_service(DOMAIN, SERVICE_CREATE_GUEST):
        return

    async def _create_guest(call: ServiceCall) -> None:
        device_id = call.data["device_id"]
        ttl_hours = call.data["ttl_hours"]
        admin = call.data["admin"]

        edata = _find_entry_data(hass, device_id)
        if edata is None:
            _LOGGER.error("create_guest: device %s not found", device_id)
            return

        client = edata["client"]
        rights = RIGHTS_ADMIN if admin else RIGHTS_RESTRICTED

        try:
            guest = await hass.async_add_executor_job(
                client.add_guest_user, device_id, ttl_hours * 3600, rights
            )
        except Exception as err:
            _LOGGER.error("create_guest failed: %s", err)
            return

        # Build share link (GPS + name from device coordinator)
        device_coord = edata["coordinators"].get(device_id)
        device_data = (device_coord.data or {}) if device_coord else {}
        lat = device_data.get("gps_lat") or 0.0
        lng = device_data.get("gps_lng") or 0.0
        name = device_data.get("device_name") or edata["devices"][device_id].name

        try:
            link = await hass.async_add_executor_job(
                lambda: client.generate_guest_link(
                    guest, device_id, name,
                    location_name=name, latitude=lat, longitude=lng,
                )
            )
        except Exception as err:
            _LOGGER.error("Guest link generation failed: %s", err)
            link = ""

        # Persistent notification with the link
        rights_label = "admin" if admin else "restricted"
        message = (
            f"Guest key created for **{name}**\n\n"
            f"- Rights: {rights_label}\n"
            f"- Valid: {ttl_hours} hour(s)\n"
            f"- User ID: `{guest.user_id}`\n\n"
            f"Share link:\n```\n{link}\n```\n\n"
            f"The QR code is available in the camera entity for this guest."
        )
        hass.components.persistent_notification.async_create(
            message,
            title="Maveo — Guest key created",
            notification_id=f"maveo_guest_{guest.user_id[:8]}",
        )

        # Refresh guest coordinator so new entities appear
        guest_coord = edata["guest_coordinators"].get(device_id)
        if guest_coord:
            await guest_coord.async_request_refresh()

        _LOGGER.info(
            "Guest key created for device %s: user_id=%s rights=%s ttl=%dh",
            device_id, guest.user_id, rights_label, ttl_hours,
        )

    async def _remove_guest(call: ServiceCall) -> None:
        device_id = call.data["device_id"]
        user_id = call.data["user_id"]

        edata = _find_entry_data(hass, device_id)
        if edata is None:
            _LOGGER.error("remove_guest: device %s not found", device_id)
            return

        client = edata["client"]
        try:
            await hass.async_add_executor_job(
                client.remove_guest_user, device_id, user_id
            )
        except Exception as err:
            _LOGGER.error("remove_guest failed: %s", err)
            return

        guest_coord = edata["guest_coordinators"].get(device_id)
        if guest_coord:
            await guest_coord.async_request_refresh()

        _LOGGER.info("Guest %s removed from device %s", user_id, device_id)

    hass.services.async_register(
        DOMAIN, SERVICE_CREATE_GUEST, _create_guest, schema=_CREATE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_GUEST, _remove_guest, schema=_REMOVE_SCHEMA
    )
