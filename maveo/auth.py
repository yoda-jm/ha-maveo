"""AWS Cognito authentication for Maveo."""

from dataclasses import dataclass
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

from .config import Config


@dataclass
class AuthResult:
    """All credentials returned after a successful login."""
    access_token: str
    id_token: str
    refresh_token: str
    identity_id: str       # Used as "owner" in API calls
    access_key_id: str     # AWS credentials for IoT SigV4
    secret_key: str
    session_token: str
    expiration: datetime


class AuthError(Exception):
    pass


def authenticate(username: str, password: str, config: Config) -> AuthResult:
    """
    Full Maveo authentication flow:
    1. Cognito USER_PASSWORD_AUTH -> tokens
    2. Cognito Identity Pool -> identity_id + AWS credentials
    """
    cognito_idp = boto3.client("cognito-idp", region_name=config.aws_region)

    try:
        response = cognito_idp.initiate_auth(
            ClientId=config.client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": username,
                "PASSWORD": password,
            },
        )
    except ClientError as e:
        raise AuthError(f"Login failed: {e.response['Error']['Message']}") from e

    if "AuthenticationResult" not in response:
        raise AuthError(f"Unexpected challenge: {response.get('ChallengeName')}")

    auth = response["AuthenticationResult"]
    id_token = auth["IdToken"]

    # Exchange ID token for federated AWS credentials
    cognito_identity = boto3.client("cognito-identity", region_name=config.aws_region)
    user_pool_provider = (
        f"cognito-idp.{config.aws_region}.amazonaws.com/{config.user_pool_id}"
    )
    logins = {user_pool_provider: id_token}

    try:
        identity_resp = cognito_identity.get_id(
            IdentityPoolId=config.identity_pool_id,
            Logins=logins,
        )
        identity_id = identity_resp["IdentityId"]

        creds_resp = cognito_identity.get_credentials_for_identity(
            IdentityId=identity_id,
            Logins=logins,
        )
    except ClientError as e:
        raise AuthError(
            f"Failed to get AWS credentials: {e.response['Error']['Message']}"
        ) from e

    creds = creds_resp["Credentials"]
    return AuthResult(
        access_token=auth["AccessToken"],
        id_token=id_token,
        refresh_token=auth.get("RefreshToken", ""),
        identity_id=identity_id,
        access_key_id=creds["AccessKeyId"],
        secret_key=creds["SecretKey"],
        session_token=creds["SessionToken"],
        expiration=creds["Expiration"],
    )
