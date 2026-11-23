"""Runtime data stored on a Maveo config entry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, callback

from .api import Device
from .coordinator import (
    MaveoAccountCoordinator,
    MaveoDeviceCoordinator,
    MaveoGuestCoordinator,
)
from .session import MaveoSession


@dataclass
class MaveoDevice:
    """One garage stick and the coordinators that poll it."""

    info: Device
    state: MaveoDeviceCoordinator
    guests: MaveoGuestCoordinator


@dataclass
class MaveoData:
    session: MaveoSession
    account: MaveoAccountCoordinator
    devices: dict[str, MaveoDevice] = field(default_factory=dict)
    _listeners: list[Callable[[MaveoDevice], None]] = field(default_factory=list)

    @callback
    def async_subscribe_devices(
        self, add: Callable[[MaveoDevice], None]
    ) -> CALLBACK_TYPE:
        """Call `add` for every current device and each device added later."""
        for device in self.devices.values():
            add(device)
        self._listeners.append(add)

        @callback
        def _unsubscribe() -> None:
            self._listeners.remove(add)

        return _unsubscribe

    @callback
    def async_device_added(self, device: MaveoDevice) -> None:
        self.devices[device.info.id] = device
        for add in list(self._listeners):
            add(device)


type MaveoConfigEntry = ConfigEntry[MaveoData]
