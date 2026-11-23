"""Async client for the Marantec Maveo cloud (Cognito, REST and AWS IoT MQTT).

This package has no Home Assistant imports so it can be published on its own.
"""

from .auth import AuthResult, login, refresh
from .client import RIGHTS_ADMIN, RIGHTS_RESTRICTED, Device, GuestUser, MaveoClient
from .config import Config, Region, get_config
from .exceptions import APIError, AuthError, CloudError, MaveoError
from .guest_link import build_guest_link
from .iot import Command, MaveoIoTClient

__all__ = [
    "RIGHTS_ADMIN",
    "RIGHTS_RESTRICTED",
    "APIError",
    "AuthError",
    "AuthResult",
    "CloudError",
    "Command",
    "Config",
    "Device",
    "GuestUser",
    "MaveoClient",
    "MaveoError",
    "MaveoIoTClient",
    "Region",
    "build_guest_link",
    "get_config",
    "login",
    "refresh",
]
