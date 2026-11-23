"""Tests for credential renewal, secret handling and privileged actions."""

from __future__ import annotations

import base64
from datetime import timedelta
from urllib.parse import parse_qs

import pytest
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from homeassistant.auth.models import User
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.util import dt as dt_util
from hypothesis import given
from hypothesis import strategies as st
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.maveo.api import GuestUser

from .fakes import DEVICE_ID, EMAIL, PASSWORD, CognitoPool, FakeMaveoApi

_KEY = base64.b64decode("zbH/cSqJIcgIta9NEhfJ8GSuT79dTQNDB2AcPBfLxyo=")


def _state(entry: ConfigEntry) -> ConfigEntryState:
    """Read the state through a call so mypy does not keep an earlier narrowing."""
    return entry.state


async def _reload_with_revoked_refresh_token(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "refresh_token": "revoked"}
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_rejected_refresh_token_signs_in_with_stored_password(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    await _reload_with_revoked_refresh_token(hass, entry)

    assert _state(entry) is ConfigEntryState.LOADED
    assert not hass.config_entries.flow.async_progress_by_handler("maveo")
    assert entry.data["refresh_token"] != "revoked"


def _sign_out_everywhere(cognito: CognitoPool, new_password: str | None = None) -> None:
    """Revoke all refresh tokens, optionally after changing the password."""
    idp = cognito.idp()
    if new_password is not None:
        idp.admin_set_user_password(
            UserPoolId=cognito.user_pool_id,
            Username=EMAIL,
            Password=new_password,
            Permanent=True,
        )
    idp.admin_user_global_sign_out(UserPoolId=cognito.user_pool_id, Username=EMAIL)


async def _poll(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_refresh_token_revoked_while_running_signs_in_again(
    hass: HomeAssistant, entry: ConfigEntry, cognito: CognitoPool
) -> None:
    revoked = entry.data["refresh_token"]
    _sign_out_everywhere(cognito)

    await _poll(hass)

    assert _state(entry) is ConfigEntryState.LOADED
    assert not hass.config_entries.flow.async_progress_by_handler("maveo")
    assert entry.data["refresh_token"] != revoked


async def test_password_changed_while_running_starts_reauth(
    hass: HomeAssistant, entry: ConfigEntry, cognito: CognitoPool
) -> None:
    _sign_out_everywhere(cognito, new_password="Changed-password-3")

    await _poll(hass)

    flows = hass.config_entries.flow.async_progress_by_handler("maveo")
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_changed_password_starts_reauth(
    hass: HomeAssistant, entry: ConfigEntry, cognito: CognitoPool
) -> None:
    new_password = "Changed-password-2"
    cognito.idp().admin_set_user_password(
        UserPoolId=cognito.user_pool_id,
        Username=EMAIL,
        Password=new_password,
        Permanent=True,
    )
    await _reload_with_revoked_refresh_token(hass, entry)

    assert _state(entry) is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler("maveo")
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]

    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {CONF_PASSWORD: PASSWORD}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {CONF_PASSWORD: new_password}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert _state(entry) is ConfigEntryState.LOADED
    assert entry.data[CONF_PASSWORD] == new_password
    assert entry.data["refresh_token"] != "revoked"


async def test_new_refresh_token_is_accepted_by_cognito(
    hass: HomeAssistant, entry: ConfigEntry, cognito: CognitoPool
) -> None:
    idp = cognito.idp()
    result = idp.initiate_auth(
        ClientId=cognito.client_id,
        AuthFlow="REFRESH_TOKEN_AUTH",
        AuthParameters={"REFRESH_TOKEN": entry.data["refresh_token"]},
    )
    assert "AuthenticationResult" in result
    assert entry.title == EMAIL


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("create_guest", {"device_id": DEVICE_ID}),
        ("remove_guest", {"device_id": DEVICE_ID, "user_id": "u-1"}),
    ],
)
async def test_guest_services_are_admin_only(
    hass: HomeAssistant,
    entry: ConfigEntry,
    cloud: FakeMaveoApi,
    hass_read_only_user: User,
    service: str,
    data: dict[str, str],
) -> None:
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "maveo",
            service,
            data,
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
            return_response=service == "create_guest",
        )
    assert not {"add_user", "remove_user"} & set(cloud.commands())


async def test_create_guest_returns_link_to_caller(
    hass: HomeAssistant, entry: ConfigEntry, cloud: FakeMaveoApi, garage_device_id: str
) -> None:
    response = await hass.services.async_call(
        "maveo",
        "create_guest",
        {"device_id": garage_device_id, "ttl_hours": 1},
        blocking=True,
        return_response=True,
    )
    assert response is not None
    guest = cloud.guests[0]
    assert response["user_id"] == guest["userid"]
    assert response["expires_at"] == "2100-01-01T00:00:00+00:00"

    raw = str(response["link"]).split("?data=", 1)[1]
    cipher = AES.new(_KEY, AES.MODE_CBC, base64.b64decode(raw[:24]))
    plain = unpad(cipher.decrypt(base64.b64decode(raw[24:])), 16).decode()
    assert parse_qs(plain)["token"] == [guest["token"]]

    # The link is not broadcast to every user as a notification.
    assert not hass.states.async_entity_ids("persistent_notification")


async def test_api_errors_do_not_leak_response_body(
    hass: HomeAssistant, entry: ConfigEntry, cloud: FakeMaveoApi, garage_device_id: str
) -> None:
    cloud.fail_with = 500
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "maveo",
            "remove_guest",
            {"device_id": garage_device_id, "user_id": "u-1"},
            blocking=True,
        )
    assert "HTTP 500" in str(err.value)
    assert "secret-guest-token-in-error-body" not in str(err.value)


@given(token=st.text(min_size=1).map(lambda t: f"tok-{t}"))
def test_guest_repr_hides_token(token: str) -> None:
    guest = GuestUser(user_id="u-1", token=token, rights="0", ttl="0")
    assert token not in repr(guest)
