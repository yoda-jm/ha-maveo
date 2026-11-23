"""Diagnostics download, with credentials and location redacted."""

from __future__ import annotations

import json

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .fakes import DEVICE_ID, EMAIL, PASSWORD, FakeMaveoApi


async def test_diagnostics_redact_secrets(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    entry: ConfigEntry,
    cloud: FakeMaveoApi,
) -> None:
    cloud.guests.append(
        {
            "userid": "u-1",
            "token": "guest-secret",
            "rights": "0",
            "ttl": "4102444800",
            "nametag1": "Alice's phone",
        }
    )
    await entry.runtime_data.devices[DEVICE_ID].guests.async_refresh()

    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    text = json.dumps(diag)
    for secret in (
        EMAIL,
        PASSWORD,
        entry.data["refresh_token"],
        "guest-secret",
        "Alice's phone",
        "SN0001",
        "51.5",
        "192.168.0.50",
    ):
        assert secret not in text

    device = _obj(_obj(diag["devices"])[DEVICE_ID])
    assert _obj(device["device"])["name"] == "Garage"
    assert _obj(device["state"])["door_position"] == 4
    guests = device["guests"]
    assert isinstance(guests, list)
    assert _obj(guests[0])["user_id"] == "u-1"


def _obj(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value
