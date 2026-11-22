"""Characterization tests: entity states and commands seen through Home Assistant."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from .conftest import add_entry_via_flow
from .fakes import DEVICE_ID, FakeMaveoApi, FakeStick


def _state(hass: HomeAssistant, platform: str, unique_id: str) -> State:
    entity_id = er.async_get(hass).async_get_entity_id(platform, "maveo", unique_id)
    assert entity_id is not None, f"no {platform} entity {unique_id}"
    state = hass.states.get(entity_id)
    assert state is not None
    return state


async def test_entry_loads(entry: ConfigEntry) -> None:
    assert entry.state is ConfigEntryState.LOADED
    assert entry.title == "owner@example.com"


async def test_cover_reports_closed_door(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    state = _state(hass, "cover", f"{DEVICE_ID}_cover")
    assert state.state == "closed"
    assert state.attributes["position_name"] == "Closed"
    assert state.attributes["intermediate_open_configured"] is True
    assert state.attributes["intermediate_close_configured"] is False


async def test_light_and_connectivity(hass: HomeAssistant, entry: ConfigEntry) -> None:
    assert _state(hass, "light", f"{DEVICE_ID}_light").state == "on"
    assert _state(hass, "binary_sensor", f"{DEVICE_ID}_connectivity").state == "on"


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("firmware", "1.2.0"),
        ("ttc", "5"),
        ("rssi", "-61"),
        ("buzzer", "off"),
        ("stick_type", "Connect"),
        ("ht_sensor", "not paired"),
        ("weather_temperature", "12.34"),
        ("weather_humidity", "56.0"),
    ],
)
async def test_device_sensors(
    hass: HomeAssistant, entry: ConfigEntry, key: str, expected: str
) -> None:
    assert _state(hass, "sensor", f"{DEVICE_ID}_{key}").state == expected


async def test_rssi_attributes(hass: HomeAssistant, entry: ConfigEntry) -> None:
    attrs = _state(hass, "sensor", f"{DEVICE_ID}_rssi").attributes
    assert attrs["ssid"] == "home"
    assert attrs["ip"] == "192.168.0.50"
    assert attrs["mac"] == "aa:bb"


async def test_location(hass: HomeAssistant, entry: ConfigEntry) -> None:
    state = _state(hass, "device_tracker", f"{DEVICE_ID}_location")
    assert state.attributes["latitude"] == 51.5
    assert state.attributes["longitude"] == -0.12


async def test_unknown_door_when_stick_silent(
    hass: HomeAssistant, cloud: FakeMaveoApi, stick: FakeStick
) -> None:
    stick.replies = {}
    await add_entry_via_flow(hass)
    assert _state(hass, "cover", f"{DEVICE_ID}_cover").state == "unavailable"


@pytest.mark.parametrize(
    ("domain", "service", "unique_id", "command"),
    [
        ("cover", "open_cover", f"{DEVICE_ID}_cover", {"AtoS_g": 1}),
        ("cover", "close_cover", f"{DEVICE_ID}_cover", {"AtoS_g": 2}),
        ("light", "turn_on", f"{DEVICE_ID}_light", {"AtoS_l": 1}),
        ("light", "turn_off", f"{DEVICE_ID}_light", {"AtoS_l": 0}),
    ],
)
async def test_actions_send_mqtt_command(
    hass: HomeAssistant,
    entry: ConfigEntry,
    stick: FakeStick,
    domain: str,
    service: str,
    unique_id: str,
    command: dict[str, Any],
) -> None:
    entity_id = _state(hass, domain, unique_id).entity_id
    stick.commands.clear()
    await hass.services.async_call(
        domain, service, {"entity_id": entity_id}, blocking=True
    )
    assert stick.commands[0] == command


async def test_guest_sensor(
    hass: HomeAssistant, cloud: FakeMaveoApi, stick: FakeStick
) -> None:
    cloud.guests.append(
        {
            "userid": "abcdef12-0000-0000-0000-000000000000",
            "token": "guesttoken",
            "rights": "1",
            "ttl": "4102444800",
            "nametag1": "Pixel",
            "nametag2": "Android",
            "nametag3": "en",
        }
    )
    await add_entry_via_flow(hass)

    state = _state(
        hass, "sensor", f"{DEVICE_ID}_guest_abcdef12-0000-0000-0000-000000000000"
    )
    assert state.attributes["rights"] == "admin"
    assert state.attributes["claimed"] is True
    assert state.attributes["app_name"] == "Pixel"
    assert state.attributes["os"] == "Android"
    assert state.attributes["locale"] == "en"
    assert state.attributes["expires_at"] == "2100-01-01T00:00:00+00:00"
    assert "token" not in state.attributes
    assert "guesttoken" not in str(state.attributes)


async def test_rest_calls_carry_cognito_id_token(
    hass: HomeAssistant, entry: ConfigEntry, cloud: FakeMaveoApi
) -> None:
    assert cloud.commands()[:2] == ["list_device", "list_user"]
    assert all(a.startswith("Bearer ey") for a in cloud.authorizations)


async def test_mqtt_connection_is_sigv4_signed(
    hass: HomeAssistant, entry: ConfigEntry, stick: FakeStick
) -> None:
    headers = stick.connect_headers[0]
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=")
    assert "X-Amz-Security-Token" in headers


async def test_unload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_every_entity_has_a_distinct_name(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    entries = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    states = [hass.states.get(e.entity_id) for e in entries]
    names = [state.name for state in states if state is not None]
    assert len(names) == len(entries)
    assert len(names) == len(set(names)), sorted(names)
    assert "Garage" not in names
