"""Maveo garage location entity — shows the stick's GPS on the HA map."""

from __future__ import annotations

from homeassistant.components.device_tracker.const import SourceType
from homeassistant.components.device_tracker.entity import TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import Device
from .coordinator import MaveoDeviceCoordinator
from .data import MaveoConfigEntry
from .entity import maveo_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaveoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    edata = entry.runtime_data
    async_add_entities(
        MaveoGarageLocation(coord, edata.devices[device_id])
        for device_id, coord in edata.coordinators.items()
        # Only create location entity if GPS data will be available (optimistic)
    )


class MaveoGarageLocation(CoordinatorEntity[MaveoDeviceCoordinator], TrackerEntity):
    """Device tracker for the garage location."""

    _attr_has_entity_name = True
    _attr_translation_key = "location"
    _attr_icon = "mdi:garage"
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: MaveoDeviceCoordinator, device: Device) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_location"
        self._device_info = maveo_device_info(coordinator.device_id, device.name)

    @property
    def device_info(self) -> DeviceInfo:
        # TrackerEntity types _attr_device_info as None, so expose it here.
        return self._device_info

    @property
    def available(self) -> bool:
        data = self.coordinator.data or {}
        return data.get("gps_lat") is not None and data.get("gps_lng") is not None

    @property
    def latitude(self) -> float | None:
        return (self.coordinator.data or {}).get("gps_lat")

    @property
    def longitude(self) -> float | None:
        return (self.coordinator.data or {}).get("gps_lng")

    @property
    def location_accuracy(self) -> int:
        return 0
