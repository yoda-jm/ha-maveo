"""Characterization tests for the user config flow."""

from __future__ import annotations

import boto3
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import add_entry_via_flow
from .fakes import AWS_REGION, PASSWORD, CognitoPool, FakeMaveoApi


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
    idp = boto3.client("cognito-idp", region_name=AWS_REGION)
    idp.admin_create_user(
        UserPoolId=cognito.user_pool_id, Username=second, MessageAction="SUPPRESS"
    )
    idp.admin_set_user_password(
        UserPoolId=cognito.user_pool_id,
        Username=second,
        Password=PASSWORD,
        Permanent=True,
    )

    assert (await add_entry_via_flow(hass))["type"] is FlowResultType.CREATE_ENTRY
    result = await add_entry_via_flow(hass, email=second)
    assert result["type"] is FlowResultType.CREATE_ENTRY

    states = {e.state for e in hass.config_entries.async_entries("maveo")}
    assert states == {ConfigEntryState.LOADED}
    assert len(hass.config_entries.async_entries("maveo")) == 2
