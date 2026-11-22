"""Characterization tests for the guest key services."""

from __future__ import annotations

from typing import Any

import probatio
import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .fakes import DEVICE_ID, FakeMaveoApi


async def _create_guest(hass: HomeAssistant, data: dict[str, Any]) -> None:
    supports = hass.services.supports_response("maveo", "create_guest")
    await hass.services.async_call(
        "maveo",
        "create_guest",
        data,
        blocking=True,
        return_response=supports is not SupportsResponse.NONE,
    )


@pytest.mark.parametrize(("admin", "rights"), [(False, 0), (True, 1)])
async def test_create_guest_adds_user(
    hass: HomeAssistant,
    entry: ConfigEntry,
    cloud: FakeMaveoApi,
    admin: bool,
    rights: int,
) -> None:
    await _create_guest(hass, {"device_id": DEVICE_ID, "ttl_hours": 2, "admin": admin})
    add = [r for r in cloud.requests if r["command"] == "add_user"]
    assert add == [
        {"deviceid": DEVICE_ID, "command": "add_user", "ttl": 7200, "rights": rights}
    ]


async def test_created_guest_gets_a_sensor(
    hass: HomeAssistant, entry: ConfigEntry, cloud: FakeMaveoApi
) -> None:
    await _create_guest(hass, {"device_id": DEVICE_ID})
    await hass.async_block_till_done()
    user_id = cloud.guests[0]["userid"]
    assert er.async_get(hass).async_get_entity_id(
        "sensor", "maveo", f"{DEVICE_ID}_guest_{user_id}"
    )


async def test_remove_guest(
    hass: HomeAssistant, entry: ConfigEntry, cloud: FakeMaveoApi
) -> None:
    cloud.guests.append(
        {"userid": "u-1", "token": "t", "rights": "0", "ttl": "4102444800"}
    )
    await hass.services.async_call(
        "maveo",
        "remove_guest",
        {"device_id": DEVICE_ID, "user_id": "u-1"},
        blocking=True,
    )
    assert cloud.guests == []
    assert {"deviceid": DEVICE_ID, "command": "remove_user", "userid": "u-1"} in (
        cloud.requests
    )


async def test_ttl_hours_out_of_range_rejected(
    hass: HomeAssistant, entry: ConfigEntry, cloud: FakeMaveoApi
) -> None:
    with pytest.raises((ServiceValidationError, probatio.Invalid)):
        await hass.services.async_call(
            "maveo",
            "create_guest",
            {"device_id": DEVICE_ID, "ttl_hours": 721},
            blocking=True,
        )
    assert "add_user" not in cloud.commands()
