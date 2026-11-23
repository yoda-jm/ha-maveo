"""Maveo regional configuration."""

from dataclasses import dataclass
from enum import StrEnum


class Region(StrEnum):
    EU = "EU"
    US = "US"


@dataclass(frozen=True)
class Config:
    client_id: str
    aws_region: str
    identity_pool_id: str
    user_pool_id: str
    api_admin_url: str
    iot_hostname: str
    cognito_idp_url: str
    cognito_identity_url: str
    iot_url: str


def _config(
    *,
    aws_region: str,
    client_id: str,
    identity_pool_id: str,
    user_pool_id: str,
) -> Config:
    iot_hostname = f"{aws_region}.iot-prod.marantec-cloud.de"
    return Config(
        client_id=client_id,
        aws_region=aws_region,
        identity_pool_id=identity_pool_id,
        user_pool_id=user_pool_id,
        api_admin_url=f"https://{aws_region}.api-prod.marantec-cloud.de/admin",
        iot_hostname=iot_hostname,
        cognito_idp_url=f"https://cognito-idp.{aws_region}.amazonaws.com/",
        cognito_identity_url=f"https://cognito-identity.{aws_region}.amazonaws.com/",
        iot_url=f"wss://{iot_hostname}/mqtt",
    )


_CONFIGS = {
    Region.EU: _config(
        aws_region="eu-central-1",
        client_id="34eruqhvvnniig5bccrre6s0ck",
        identity_pool_id="eu-central-1:b3ebe605-53c9-463e-8738-70ae01b042ee",
        user_pool_id="eu-central-1_ozbW8rTAj",
    ),
    Region.US: _config(
        aws_region="us-west-2",
        client_id="6uf5ra21th645p7c2o6ih65pit",
        identity_pool_id="us-west-2:a982cd04-863c-4fd4-8397-47deb11c8ec0",
        user_pool_id="us-west-2_6Ni2Wq0tP",
    ),
}


def get_config(region: Region = Region.EU) -> Config:
    return _CONFIGS[region]
