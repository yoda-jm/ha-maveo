"""AWS Cognito authentication for Maveo."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .config import Config

if TYPE_CHECKING:
    from mypy_boto3_cognito_idp.literals import AuthFlowTypeType
    from mypy_boto3_cognito_idp.type_defs import AuthenticationResultTypeTypeDef

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


class AuthError(Exception):
    """The Maveo cloud rejected the credentials; the user must sign in again."""


class CloudError(Exception):
    """The Maveo cloud could not be reached or returned an unexpected error."""


def login(username: str, password: str, config: Config) -> AuthResult:
    """Sign in with email and password (Cognito USER_PASSWORD_AUTH)."""
    tokens = _initiate_auth(
        config, "USER_PASSWORD_AUTH", {"USERNAME": username, "PASSWORD": password}
    )
    if "RefreshToken" not in tokens:
        raise CloudError("Cognito did not return a refresh token")
    return _federate(tokens, tokens["RefreshToken"], config)


def refresh(refresh_token: str, config: Config) -> AuthResult:
    """Get fresh credentials from a refresh token (Cognito REFRESH_TOKEN_AUTH)."""
    tokens = _initiate_auth(
        config, "REFRESH_TOKEN_AUTH", {"REFRESH_TOKEN": refresh_token}
    )
    # Cognito only returns a new refresh token when token rotation is enabled.
    return _federate(tokens, tokens.get("RefreshToken", refresh_token), config)


def _initiate_auth(
    config: Config, flow: AuthFlowTypeType, parameters: Mapping[str, str]
) -> AuthenticationResultTypeTypeDef:
    try:
        cognito_idp = boto3.client("cognito-idp", region_name=config.aws_region)
        response = cognito_idp.initiate_auth(
            ClientId=config.client_id, AuthFlow=flow, AuthParameters=parameters
        )
    except ClientError as err:
        raise _map_client_error(err, "Sign-in failed") from err
    except BotoCoreError as err:
        raise CloudError(f"Sign-in failed: {err}") from err

    if "AuthenticationResult" not in response:
        raise AuthError(
            f"Unsupported sign-in challenge: {response.get('ChallengeName')}"
        )
    return response["AuthenticationResult"]


def _federate(
    tokens: AuthenticationResultTypeTypeDef, refresh_token: str, config: Config
) -> AuthResult:
    """Exchange the Cognito ID token for an identity ID and AWS credentials."""
    id_token = tokens["IdToken"]
    provider = f"cognito-idp.{config.aws_region}.amazonaws.com/{config.user_pool_id}"
    logins = {provider: id_token}

    try:
        cognito_identity = boto3.client(
            "cognito-identity", region_name=config.aws_region
        )
        identity_id = cognito_identity.get_id(
            IdentityPoolId=config.identity_pool_id, Logins=logins
        )["IdentityId"]
        creds = cognito_identity.get_credentials_for_identity(
            IdentityId=identity_id, Logins=logins
        )["Credentials"]
    except ClientError as err:
        raise _map_client_error(err, "Failed to get AWS credentials") from err
    except BotoCoreError as err:
        raise CloudError(f"Failed to get AWS credentials: {err}") from err

    expiration = creds["Expiration"]
    if expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=UTC)

    return AuthResult(
        id_token=id_token,
        refresh_token=refresh_token,
        identity_id=identity_id,
        access_key_id=creds["AccessKeyId"],
        secret_key=creds["SecretKey"],
        session_token=creds["SessionToken"],
        expiration=expiration,
    )


def _map_client_error(err: ClientError, context: str) -> AuthError | CloudError:
    error = err.response.get("Error", {})
    message = f"{context}: {error.get('Message', 'unknown error')}"
    if error.get("Code") in _REJECTED_CODES:
        return AuthError(message)
    return CloudError(message)
