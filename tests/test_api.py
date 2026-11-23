"""API package error handling against a server returning crafted responses."""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import aiohttp
import pytest
from aiohttp import web

from custom_components.maveo.api import (
    APIError,
    AuthError,
    AuthResult,
    CloudError,
    Command,
    Config,
    MaveoClient,
    MaveoIoTClient,
    Region,
    get_config,
    login,
    refresh,
)

_AUTH = AuthResult(
    id_token="id",
    refresh_token="refresh",
    identity_id="identity",
    access_key_id="AKIA",
    secret_key="secret",
    session_token="session",
    expiration=datetime(2100, 1, 1, tzinfo=UTC),
)


@dataclass
class Crafted:
    """Responses served in order, by AWS target or path."""

    responses: dict[str, list[web.Response]] = field(default_factory=dict)

    async def handle(self, request: web.Request) -> web.StreamResponse:
        key = request.headers.get("X-Amz-Target", request.path)
        queue = self.responses.get(key.rsplit(".", 1)[-1], [])
        if not queue:
            return web.Response(status=599)
        return queue.pop(0)

    async def text_frame(self, request: web.Request) -> web.StreamResponse:
        ws = web.WebSocketResponse(protocols=("mqtt",))
        await ws.prepare(request)
        await ws.receive()
        await ws.send_str("not mqtt")
        await ws.close()
        return ws


@dataclass
class Env:
    http: aiohttp.ClientSession
    config: Config
    server: Crafted


@pytest.fixture
async def env(socket_enabled: None) -> AsyncIterator[Env]:
    crafted = Crafted()
    app = web.Application()
    app.router.add_post("/{tail:.*}", crafted.handle)
    app.router.add_get("/mqtt", crafted.text_frame)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    base = f"http://{host}:{port}"
    config = dataclasses.replace(
        get_config(Region.EU),
        cognito_idp_url=f"{base}/",
        cognito_identity_url=f"{base}/",
        api_admin_url=f"{base}/admin",
        iot_url=f"ws://{host}:{port}/mqtt",
    )
    async with aiohttp.ClientSession() as http:
        yield Env(http, config, crafted)
    await runner.cleanup()


def _json(body: object, status: int = 200) -> web.Response:
    return web.json_response(body, status=status)


_TOKENS = {"AuthenticationResult": {"IdToken": "id", "RefreshToken": "r"}}


async def test_unsupported_challenge_is_auth_error(env: Env) -> None:
    env.server.responses["InitiateAuth"] = [
        _json({"ChallengeName": "SMS_MFA", "Session": "s"})
    ]
    with pytest.raises(AuthError, match="SMS_MFA"):
        await login(env.http, "a@b.c", "pw", env.config)


@pytest.mark.parametrize(
    ("type_", "error"),
    [
        ("com.amazonaws#NotAuthorizedException", AuthError),
        ("PasswordResetRequiredException", AuthError),
        ("TooManyRequestsException", CloudError),
    ],
)
async def test_cognito_error_codes(
    env: Env, type_: str, error: type[Exception]
) -> None:
    env.server.responses["InitiateAuth"] = [
        _json({"__type": type_, "message": "nope"}, status=400)
    ]
    with pytest.raises(error):
        await refresh(env.http, "token", env.config)


@pytest.mark.parametrize(
    "response",
    [
        web.Response(text="<html>", status=502),
        web.Response(text="[1, 2]", content_type="application/json"),
        _json({"AuthenticationResult": {"RefreshToken": "r"}}),
    ],
    ids=["not-json", "not-object", "missing-id-token"],
)
async def test_malformed_cognito_response_is_cloud_error(
    env: Env, response: web.Response
) -> None:
    env.server.responses["InitiateAuth"] = [response]
    with pytest.raises(CloudError):
        await login(env.http, "a@b.c", "pw", env.config)


@pytest.mark.parametrize(
    "credentials",
    [
        {},
        {"Credentials": {"AccessKeyId": "a", "SecretKey": "s", "SessionToken": "t"}},
    ],
    ids=["no-credentials", "no-expiration"],
)
async def test_incomplete_credentials_are_cloud_error(
    env: Env, credentials: dict[str, object]
) -> None:
    env.server.responses["InitiateAuth"] = [_json(_TOKENS)]
    env.server.responses["GetId"] = [_json({"IdentityId": "eu-central-1:x"})]
    env.server.responses["GetCredentialsForIdentity"] = [_json(credentials)]
    with pytest.raises(CloudError):
        await login(env.http, "a@b.c", "pw", env.config)


async def test_refresh_keeps_token_when_not_rotated(env: Env) -> None:
    env.server.responses["InitiateAuth"] = [
        _json({"AuthenticationResult": {"IdToken": "id"}})
    ]
    env.server.responses["GetId"] = [_json({"IdentityId": "eu-central-1:x"})]
    env.server.responses["GetCredentialsForIdentity"] = [
        _json(
            {
                "Credentials": {
                    "AccessKeyId": "a",
                    "SecretKey": "s",
                    "SessionToken": "t",
                    "Expiration": 4102444800,
                }
            }
        )
    ]
    result = await refresh(env.http, "original", env.config)
    assert result.refresh_token == "original"
    assert result.expiration == datetime(2100, 1, 1, tzinfo=UTC)


async def test_unreachable_cognito_is_cloud_error(
    env: Env, unused_tcp_port: int
) -> None:
    config = dataclasses.replace(
        env.config, cognito_idp_url=f"http://127.0.0.1:{unused_tcp_port}/"
    )
    with pytest.raises(CloudError, match="ClientConnectorError"):
        await login(env.http, "a@b.c", "pw", config)


async def test_rest_non_json_is_api_error(env: Env) -> None:
    env.server.responses["/admin"] = [web.Response(text="<html>")]
    with pytest.raises(APIError, match="not JSON"):
        await MaveoClient(env.http, _AUTH, env.config).list_devices()


async def test_rest_unreachable_is_api_error(env: Env, unused_tcp_port: int) -> None:
    config = dataclasses.replace(
        env.config, api_admin_url=f"http://127.0.0.1:{unused_tcp_port}/admin"
    )
    with pytest.raises(APIError, match="request failed"):
        await MaveoClient(env.http, _AUTH, config).list_devices()


async def test_iot_send_before_connect_fails(env: Env) -> None:
    client = MaveoIoTClient(env.http, _AUTH, env.config, "1001")
    with pytest.raises(ConnectionError):
        await client.send(Command.STATUS)


async def test_iot_text_frame_is_connect_failure(env: Env) -> None:
    client = MaveoIoTClient(env.http, _AUTH, env.config, "1001")
    with pytest.raises(CloudError, match="ConnectionError"):
        await client.connect()
