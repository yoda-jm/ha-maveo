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
    """One garage stick and the coordinators that poll it.

    A device is active until it leaves the account or the entry unloads;
    removing it runs its teardown callbacks once.
    """

    info: Device
    state: MaveoDeviceCoordinator
    guests: MaveoGuestCoordinator
    _teardown: list[CALLBACK_TYPE] = field(default_factory=list)
    removed: bool = False

    @callback
    def async_on_remove(self, func: CALLBACK_TYPE) -> None:
        """Run `func` when the device is removed."""
        self._teardown.append(func)

    @callback
    def async_remove(self) -> None:
        if self.removed:
            return
        self.removed = True
        while self._teardown:
            self._teardown.pop()()


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

    @callback
    def async_device_removed(self, device_id: str) -> None:
        self.devices.pop(device_id).async_remove()

    @callback
    def async_remove_all(self) -> None:
        for device in self.devices.values():
            device.async_remove()


type MaveoConfigEntry = ConfigEntry[MaveoData]
