"""Runtime data stored on a Maveo config entry."""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry

from .client import Device
from .coordinator import MaveoDeviceCoordinator
from .guest_coordinator import MaveoGuestCoordinator
from .session import MaveoSession


@dataclass
class MaveoData:
    session: MaveoSession
    devices: dict[str, Device]
    coordinators: dict[str, MaveoDeviceCoordinator] = field(default_factory=dict)
    guest_coordinators: dict[str, MaveoGuestCoordinator] = field(default_factory=dict)


type MaveoConfigEntry = ConfigEntry[MaveoData]
