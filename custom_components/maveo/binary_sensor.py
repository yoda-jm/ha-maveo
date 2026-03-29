"""Maveo connectivity binary sensor."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MaveoDeviceCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    edata = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        MaveoConnectivity(coord, edata["devices"][device_id])
        for device_id, coord in edata["coordinators"].items()
    )


class MaveoConnectivity(CoordinatorEntity[MaveoDeviceCoordinator], BinarySensorEntity):
    """Maveo cloud connectivity sensor."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_translation_key = "connectivity"

    def __init__(self, coordinator: MaveoDeviceCoordinator, device) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_connectivity"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_id)},
            "name": device.name,
            "manufacturer": "Marantec",
            "model": "Maveo",
        }

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.get("online"))
