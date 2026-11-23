"""AWS Cognito authentication for Maveo.

Calls the Cognito user pool and identity pool JSON APIs directly; none of the
calls used here need AWS request signing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import aiohttp

from .config import Config
from .exceptions import AuthError, CloudError

_TIMEOUT = aiohttp.ClientTimeout(total=15)
_IDP_TARGET = "AWSCognitoIdentityProviderService"
_IDENTITY_TARGET = "AWSCognitoIdentityService"

# Cognito error codes meaning the password or refresh token is no longer accepted.
_REJECTED_CODES = frozenset(
    {
        "NotAuthorizedException",
        "UserNotFoundException",
        "UserNotConfirmedException",
        "PasswordResetRequiredException",
    }
)


@dataclass(frozen=True)
class AuthResult:
    """Cognito tokens and the federated AWS credentials derived from them."""

    id_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    identity_id: str  # Used as "owner" in API calls
    access_key_id: str  # AWS credentials for IoT SigV4
    secret_key: str = field(repr=False)
    session_token: str = field(repr=False)
    expiration: datetime


async def login(
    session: aiohttp.ClientSession, username: str, password: str, config: Config
) -> AuthResult:
    """Sign in with email and password (Cognito USER_PASSWORD_AUTH)."""
    tokens = await _initiate_auth(
        session,
        config,
        "USER_PASSWORD_AUTH",
        {"USERNAME": username, "PASSWORD": password},
    )
    return await _federate(session, tokens, _str(tokens, "RefreshToken"), config)


async def refresh(
    session: aiohttp.ClientSession, refresh_token: str, config: Config
) -> AuthResult:
    """Get fresh credentials from a refresh token (Cognito REFRESH_TOKEN_AUTH)."""
    tokens = await _initiate_auth(
        session, config, "REFRESH_TOKEN_AUTH", {"REFRESH_TOKEN": refresh_token}
    )
    # Cognito only returns a new refresh token when token rotation is enabled.
    rotated = tokens.get("RefreshToken")
    new_token = rotated if isinstance(rotated, str) and rotated else refresh_token
    return await _federate(session, tokens, new_token, config)


async def _initiate_auth(
    session: aiohttp.ClientSession,
    config: Config,
    flow: str,
    parameters: Mapping[str, str],
) -> dict[str, Any]:
    response = await _call(
        session,
        config.cognito_idp_url,
        f"{_IDP_TARGET}.InitiateAuth",
        {"ClientId": config.client_id, "AuthFlow": flow, "AuthParameters": parameters},
    )
    result = response.get("AuthenticationResult")
    if not isinstance(result, dict):
        raise AuthError(
            f"Unsupported sign-in challenge: {response.get('ChallengeName')}"
        )
    return result


async def _federate(
    session: aiohttp.ClientSession,
    tokens: Mapping[str, Any],
    refresh_token: str,
    config: Config,
) -> AuthResult:
    """Exchange the Cognito ID token for an identity ID and AWS credentials."""
    id_token = _str(tokens, "IdToken")
    provider = f"cognito-idp.{config.aws_region}.amazonaws.com/{config.user_pool_id}"
    logins = {provider: id_token}

    identity = await _call(
        session,
        config.cognito_identity_url,
        f"{_IDENTITY_TARGET}.GetId",
        {"IdentityPoolId": config.identity_pool_id, "Logins": logins},
    )
    identity_id = _str(identity, "IdentityId")
    response = await _call(
        session,
        config.cognito_identity_url,
        f"{_IDENTITY_TARGET}.GetCredentialsForIdentity",
        {"IdentityId": identity_id, "Logins": logins},
    )
    creds = response.get("Credentials")
    if not isinstance(creds, dict):
        raise CloudError("GetCredentialsForIdentity: no credentials returned")
    expiration = creds.get("Expiration")
    if not isinstance(expiration, int | float):
        raise CloudError("GetCredentialsForIdentity: no expiration returned")

    return AuthResult(
        id_token=id_token,
        refresh_token=refresh_token,
        identity_id=identity_id,
        access_key_id=_str(creds, "AccessKeyId"),
        secret_key=_str(creds, "SecretKey"),
        session_token=_str(creds, "SessionToken"),
        expiration=datetime.fromtimestamp(expiration, UTC),
    )


async def _call(
    session: aiohttp.ClientSession, url: str, target: str, body: Mapping[str, Any]
) -> dict[str, Any]:
    """POST an AWS JSON 1.1 request and return the decoded response."""
    action = target.rsplit(".", 1)[-1]
    try:
        async with session.post(
            url,
            data=json.dumps(body),
            headers={
                "X-Amz-Target": target,
                "Content-Type": "application/x-amz-json-1.1",
            },
            timeout=_TIMEOUT,
        ) as resp:
            status = resp.status
            text = await resp.text()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise CloudError(f"{action}: request failed ({type(err).__name__})") from err

    try:
        data = json.loads(text) if text else {}
    except ValueError as err:
        raise CloudError(f"{action}: response is not JSON") from err
    if not isinstance(data, dict):
        raise CloudError(f"{action}: unexpected response")

    if status != 200:
        code = str(data.get("__type", "")).rsplit("#", 1)[-1]
        if code in _REJECTED_CODES:
            message = data.get("message") or data.get("Message") or code
            raise AuthError(f"{action}: {message}")
        raise CloudError(f"{action}: HTTP {status} {code}".rstrip())
    return data


def _str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise CloudError(f"Missing {key} in Cognito response")
    return value
