"""Maveo garage location entity — shows the stick's GPS on the HA map."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
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
        MaveoGarageLocation(coord, edata["devices"][device_id])
        for device_id, coord in edata["coordinators"].items()
        # Only create location entity if GPS data will be available (optimistic)
    )


class MaveoGarageLocation(CoordinatorEntity[MaveoDeviceCoordinator], TrackerEntity):
    """Device tracker for the garage location."""

    _attr_has_entity_name = True
    _attr_translation_key = "location"
    _attr_icon = "mdi:garage"
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: MaveoDeviceCoordinator, device) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_location"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_id)},
            "name": device.name,
            "manufacturer": "Marantec",
            "model": "Maveo",
        }

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

    @property
    def battery_level(self) -> int | None:
        return None
