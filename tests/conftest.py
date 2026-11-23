"""Shared fixtures: moto Cognito server and a local Maveo REST/MQTT server."""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from aiohttp import web
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from moto.core.base_backend import BackendDict
from moto.server import ThreadedMotoServer

from custom_components.maveo.api import config as maveo_config
from custom_components.maveo.const import DOMAIN

from .fakes import (
    AWS_REGION,
    DEVICE_ID,
    EMAIL,
    PASSWORD,
    CognitoPool,
    FakeMaveoApi,
    FakeStick,
    create_app,
    create_cognito_pool,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/maveo in every test."""


@pytest.fixture
def cognito(
    monkeypatch: pytest.MonkeyPatch, socket_enabled: None
) -> Iterator[CognitoPool]:
    """A fresh moto Cognito server; HA's harness blocks sockets unless enabled."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    try:
        yield create_cognito_pool(endpoint)
    finally:
        server.stop()
        BackendDict.reset()


@pytest.fixture
def maveo_api() -> FakeMaveoApi:
    return FakeMaveoApi()


@pytest.fixture
def stick() -> FakeStick:
    return FakeStick()


@pytest.fixture
async def maveo_server(
    socket_enabled: None, maveo_api: FakeMaveoApi, stick: FakeStick
) -> AsyncIterator[str]:
    """Base URL of the local REST + MQTT-over-WebSocket server."""
    runner = web.AppRunner(create_app(maveo_api, stick))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    assert runner.addresses
    host, port = runner.addresses[0][:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        await runner.cleanup()


@pytest.fixture
def cloud(
    monkeypatch: pytest.MonkeyPatch,
    cognito: CognitoPool,
    maveo_api: FakeMaveoApi,
    maveo_server: str,
) -> FakeMaveoApi:
    """Point the EU region at the fake Cognito, REST and MQTT servers."""
    eu = maveo_config.Region.EU
    configs: dict[Any, maveo_config.Config] = dict(maveo_config._CONFIGS)
    configs[eu] = dataclasses.replace(
        configs[eu],
        aws_region=AWS_REGION,
        client_id=cognito.client_id,
        user_pool_id=cognito.user_pool_id,
        identity_pool_id=cognito.identity_pool_id,
        api_admin_url=f"{maveo_server}/admin",
        iot_hostname="iot.maveo.test",
        cognito_idp_url=f"{cognito.endpoint_url}/",
        cognito_identity_url=f"{cognito.endpoint_url}/",
        iot_url=f"{maveo_server.replace('http', 'ws', 1)}/mqtt",
    )
    monkeypatch.setattr(maveo_config, "_CONFIGS", configs)
    return maveo_api


async def add_entry_via_flow(
    hass: HomeAssistant, password: str = PASSWORD, email: str = EMAIL
) -> dict[str, Any]:
    """Run the user config flow the way the UI does."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_EMAIL: email, CONF_PASSWORD: password, "region": "EU"},
    )
    await hass.async_block_till_done()
    return dict(result)


@pytest.fixture
async def entry(hass: HomeAssistant, cloud: FakeMaveoApi) -> ConfigEntry:
    """A Maveo entry created through the config flow and fully set up."""
    result = await add_entry_via_flow(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    return entries[0]


@pytest.fixture
async def entry_all_enabled(hass: HomeAssistant, entry: ConfigEntry) -> ConfigEntry:
    """The Maveo entry with entities disabled by default enabled, as a user would."""
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.disabled_by is not None:
            registry.async_update_entity(reg_entry.entity_id, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
def garage_device_id(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Home Assistant device registry ID of the fake garage stick."""
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, DEVICE_ID), entry.entry_id
    )
    assert device is not None
    return device.id
