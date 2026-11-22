"""Maveo connectivity binary sensor."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
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
        MaveoConnectivity(coord, edata.devices[device_id])
        for device_id, coord in edata.coordinators.items()
    )


class MaveoConnectivity(CoordinatorEntity[MaveoDeviceCoordinator], BinarySensorEntity):
    """Maveo cloud connectivity sensor."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_translation_key = "connectivity"

    def __init__(self, coordinator: MaveoDeviceCoordinator, device: Device) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_connectivity"
        self._attr_device_info = maveo_device_info(coordinator.device_id, device.name)

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.get("online"))
