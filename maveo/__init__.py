"""Maveo Python library — Home Assistant integration foundation."""

from .auth import AuthResult, AuthError, authenticate
from .client import (APIError, Device, DeviceStatus, GuestUser, MaveoClient,
                      RIGHTS_ADMIN, RIGHTS_RESTRICTED, decode_guest_link)
from .iot import Command, MaveoIoTClient
from .config import Config, Region, get_config

__all__ = [
    "authenticate",
    "AuthError",
    "AuthResult",
    "APIError",
    "Command",
    "RIGHTS_ADMIN",
    "RIGHTS_RESTRICTED",
    "Config",
    "decode_guest_link",
    "Device",
    "DeviceStatus",
    "get_config",
    "GuestUser",
    "MaveoClient",
    "MaveoIoTClient",
    "Region",
]
