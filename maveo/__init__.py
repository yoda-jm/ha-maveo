"""Maveo Python library — Home Assistant integration foundation."""

from .auth import AuthResult, AuthError, authenticate
from .client import (APIError, Device, DeviceStatus, GuestUser, MaveoClient,
                      RIGHTS_ADMIN, RIGHTS_RESTRICTED, decode_guest_link)
from .iot import (Command, MaveoIoTClient,
                   DOOR_UNKNOWN, DOOR_OPENING, DOOR_CLOSING, DOOR_OPEN,
                   DOOR_CLOSED, DOOR_INTERMEDIATE_OPEN, DOOR_INTERMEDIATE_CLOSED,
                   DOOR_POSITION_NAMES)
from .config import Config, Region, get_config
from .firebase import FirebaseError, FirebaseToken, get_installation_token, fetch_remote_config
from .maveopro import MaveoProClient, MaveoProCustomer, MaveoProDevice, MaveoProError

__all__ = [
    "authenticate",
    "AuthError",
    "AuthResult",
    "APIError",
    "Command",
    "DOOR_UNKNOWN",
    "DOOR_OPENING",
    "DOOR_CLOSING",
    "DOOR_OPEN",
    "DOOR_CLOSED",
    "DOOR_INTERMEDIATE_OPEN",
    "DOOR_INTERMEDIATE_CLOSED",
    "DOOR_POSITION_NAMES",
    "fetch_remote_config",
    "FirebaseError",
    "FirebaseToken",
    "get_installation_token",
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
    "MaveoProClient",
    "MaveoProCustomer",
    "MaveoProDevice",
    "MaveoProError",
    "Region",
]
