"""Base entity for Maveo."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MaveoDeviceCoordinator
from .data import MaveoDevice


def maveo_device_info(device: MaveoDevice) -> DeviceInfo:
    """Device registry entry shared by all entities of one Maveo stick."""
    data: dict[str, Any] = device.state.data or {}
    return DeviceInfo(
        identifiers={(DOMAIN, device.info.id)},
        name=device.info.name,
        manufacturer="Marantec",
        model="Maveo",
        sw_version=data.get("firmware"),
        serial_number=data.get("serial"),
    )


class MaveoEntity(CoordinatorEntity[MaveoDeviceCoordinator]):
    """Entity backed by a device's state coordinator."""

    _attr_has_entity_name = True

    def __init__(self, device: MaveoDevice, key: str) -> None:
        super().__init__(device.state)
        self._attr_unique_id = f"{device.info.id}_{key}"
        self._attr_device_info = maveo_device_info(device)

    @property
    def data(self) -> dict[str, Any]:
        return self.coordinator.data or {}

    @property
    def available(self) -> bool:
        return super().available and bool(self.data.get("online"))
