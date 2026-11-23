"""Characterization tests for the user config flow."""

from __future__ import annotations

import dataclasses

import aiohttp
import pytest
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
)
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.maveo import config_flow
from custom_components.maveo.api import AuthResult, Config
from custom_components.maveo.api import config as maveo_config

from .conftest import add_entry_via_flow
from .fakes import EMAIL, PASSWORD, CognitoPool, FakeMaveoApi


async def test_wrong_password_shows_invalid_auth(
    hass: HomeAssistant, cloud: FakeMaveoApi
) -> None:
    result = await add_entry_via_flow(hass, password="wrong-password")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_same_account_twice_aborts(
    hass: HomeAssistant, cloud: FakeMaveoApi
) -> None:
    assert (await add_entry_via_flow(hass))["type"] is FlowResultType.CREATE_ENTRY
    result = await add_entry_via_flow(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_two_accounts_load_side_by_side(
    hass: HomeAssistant, cloud: FakeMaveoApi, cognito: CognitoPool
) -> None:
    second = "second@example.com"
    cognito.add_user(second)

    assert (await add_entry_via_flow(hass))["type"] is FlowResultType.CREATE_ENTRY
    result = await add_entry_via_flow(hass, email=second)
    assert result["type"] is FlowResultType.CREATE_ENTRY

    states = {e.state for e in hass.config_entries.async_entries("maveo")}
    assert states == {ConfigEntryState.LOADED}
    assert len(hass.config_entries.async_entries("maveo")) == 2


async def test_reconfigure_updates_password(
    hass: HomeAssistant, entry: ConfigEntry, cognito: CognitoPool
) -> None:
    new_password = "Changed-password-2"
    cognito.idp().admin_set_user_password(
        UserPoolId=cognito.user_pool_id,
        Username=EMAIL,
        Password=new_password,
        Permanent=True,
    )
    result = await hass.config_entries.flow.async_init(
        "maveo", context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD, "region": "EU"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: new_password, "region": "EU"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PASSWORD] == new_password
    assert entry.state is ConfigEntryState.LOADED


async def test_unreachable_cloud_shows_cannot_connect(
    hass: HomeAssistant,
    cloud: FakeMaveoApi,
    monkeypatch: pytest.MonkeyPatch,
    unused_tcp_port: int,
) -> None:
    eu = maveo_config.Region.EU
    configs = dict(maveo_config._CONFIGS)
    configs[eu] = dataclasses.replace(
        configs[eu], cognito_idp_url=f"http://127.0.0.1:{unused_tcp_port}/"
    )
    monkeypatch.setattr(maveo_config, "_CONFIGS", configs)

    result = await add_entry_via_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_unexpected_error_shows_unknown(
    hass: HomeAssistant, cloud: FakeMaveoApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nothing at the network boundary raises a non-Maveo error, so the sign-in
    # call is replaced with one of the same signature that does.
    async def _broken_login(
        session: aiohttp.ClientSession, username: str, password: str, config: Config
    ) -> AuthResult:
        raise RuntimeError("bug")

    monkeypatch.setattr(config_flow, "login", _broken_login)

    result = await add_entry_via_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}
