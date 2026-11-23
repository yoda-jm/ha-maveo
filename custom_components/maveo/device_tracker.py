"""Maveo garage location entity — shows the stick's GPS on the HA map."""

from __future__ import annotations

from homeassistant.components.device_tracker.const import SourceType
from homeassistant.components.device_tracker.entity import TrackerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .data import MaveoConfigEntry, MaveoDevice
from .entity import MaveoEntity, maveo_device_info

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaveoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    @callback
    def _add(device: MaveoDevice) -> None:
        async_add_entities([MaveoGarageLocation(device)])

    entry.async_on_unload(entry.runtime_data.async_subscribe_devices(_add))


class MaveoGarageLocation(MaveoEntity, TrackerEntity):
    """Device tracker for the garage location."""

    _attr_translation_key = "location"
    _attr_source_type = SourceType.GPS

    def __init__(self, device: MaveoDevice) -> None:
        super().__init__(device, "location")
        self._device_info = maveo_device_info(device)

    @property
    def device_info(self) -> DeviceInfo:
        # TrackerEntity types _attr_device_info as None, so expose it here.
        return self._device_info

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.data.get("gps_lat") is not None
            and self.data.get("gps_lng") is not None
        )

    @property
    def latitude(self) -> float | None:
        value = self.data.get("gps_lat")
        return float(value) if value is not None else None

    @property
    def longitude(self) -> float | None:
        value = self.data.get("gps_lng")
        return float(value) if value is not None else None

    @property
    def location_accuracy(self) -> int:
        return 0
