"""Shared fixtures: moto Cognito, local REST server, fake MQTT stick."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Any

import pytest
import websockets
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from moto import mock_aws
from pytest_httpserver import HTTPServer

from custom_components.maveo import config as maveo_config
from custom_components.maveo.const import DOMAIN

from .fakes import (
    AWS_REGION,
    EMAIL,
    PASSWORD,
    CognitoPool,
    FakeMaveoApi,
    FakeStick,
    create_cognito_pool,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/maveo in every test."""


@pytest.fixture
def httpserver(socket_enabled: None) -> Iterator[HTTPServer]:
    """Local REST server; HA's harness blocks sockets unless enabled."""
    server = HTTPServer(host="127.0.0.1", port=0)
    server.start()
    yield server
    server.clear()
    server.stop()


@pytest.fixture
def cognito(monkeypatch: pytest.MonkeyPatch) -> Iterator[CognitoPool]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        yield create_cognito_pool()


@pytest.fixture
def maveo_api(httpserver: HTTPServer) -> FakeMaveoApi:
    api = FakeMaveoApi()
    httpserver.expect_request("/admin", method="POST").respond_with_handler(api.handle)
    return api


@pytest.fixture
def stick(monkeypatch: pytest.MonkeyPatch) -> FakeStick:
    fake = FakeStick()
    monkeypatch.setattr(websockets, "connect", fake.connect)
    return fake


@pytest.fixture
def cloud(
    monkeypatch: pytest.MonkeyPatch,
    cognito: CognitoPool,
    maveo_api: FakeMaveoApi,
    stick: FakeStick,
    httpserver: HTTPServer,
) -> FakeMaveoApi:
    """Point the EU region at the fake Cognito pool and local REST server."""
    eu = maveo_config.Region.EU
    configs: dict[Any, maveo_config.Config] = dict(maveo_config._CONFIGS)
    configs[eu] = dataclasses.replace(
        configs[eu],
        aws_region=AWS_REGION,
        client_id=cognito.client_id,
        user_pool_id=cognito.user_pool_id,
        identity_pool_id=cognito.identity_pool_id,
        api_admin_url=httpserver.url_for("/admin"),
        iot_hostname="iot.maveo.test",
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
