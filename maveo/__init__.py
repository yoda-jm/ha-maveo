"""Maveo Python library — Home Assistant integration foundation."""

from .auth import AuthResult, AuthError, authenticate
from .client import APIError, Device, DeviceStatus, MaveoClient
from .config import Config, Region, get_config

__all__ = [
    "authenticate",
    "AuthError",
    "AuthResult",
    "APIError",
    "Config",
    "Device",
    "DeviceStatus",
    "get_config",
    "MaveoClient",
    "Region",
]
