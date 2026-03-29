"""Maveo regional configuration."""

from dataclasses import dataclass
from enum import Enum


class Region(str, Enum):
    EU = "EU"
    US = "US"


@dataclass(frozen=True)
class Config:
    client_id: str
    aws_region: str
    identity_pool_id: str
    user_pool_id: str
    api_admin_url: str
    api_user_url: str
    iot_hostname: str


_CONFIGS = {
    Region.EU: Config(
        client_id="34eruqhvvnniig5bccrre6s0ck",
        aws_region="eu-central-1",
        identity_pool_id="eu-central-1:b3ebe605-53c9-463e-8738-70ae01b042ee",
        user_pool_id="eu-central-1_ozbW8rTAj",
        api_admin_url="https://eu-central-1.api-prod.marantec-cloud.de/admin",
        api_user_url="https://eu-central-1.api-prod.marantec-cloud.de/user",
        iot_hostname="eu-central-1.iot-prod.marantec-cloud.de",
    ),
    Region.US: Config(
        client_id="6uf5ra21th645p7c2o6ih65pit",
        aws_region="us-west-2",
        identity_pool_id="us-west-2:a982cd04-863c-4fd4-8397-47deb11c8ec0",
        user_pool_id="us-west-2_6Ni2Wq0tP",
        api_admin_url="https://us-west-2.api-prod.marantec-cloud.de/admin",
        api_user_url="https://us-west-2.api-prod.marantec-cloud.de/user",
        iot_hostname="us-west-2.iot-prod.marantec-cloud.de",
    ),
}


def get_config(region: Region = Region.EU) -> Config:
    return _CONFIGS[region]
