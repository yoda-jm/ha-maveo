"""Diagnostics for Maveo, with credentials and location redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_REFRESH_TOKEN
from .data import MaveoConfigEntry

TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    "token",
    "serial",
    "ht_serial",
    "gps_lat",
    "gps_lng",
    "wifi_ssid",
    "wifi_ip",
    "wifi_mac",
    "nametag1",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MaveoConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "devices": {
            device_id: {
                "device": asdict(device.info),
                "state": async_redact_data(device.state.data or {}, TO_REDACT),
                "guests": [
                    async_redact_data(asdict(guest), TO_REDACT)
                    for guest in device.guests.data or []
                ],
            }
            for device_id, device in data.devices.items()
        },
    }
