"""Maveo garage door cover entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import Device
from .coordinator import MaveoDeviceCoordinator
from .data import MaveoConfigEntry
from .entity import maveo_device_info
from .iot import (
    DOOR_CLOSED,
    DOOR_CLOSING,
    DOOR_OPENING,
    DOOR_POSITION_NAMES,
    DOOR_STOPPED,
    Command,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaveoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    edata = entry.runtime_data
    async_add_entities(
        MaveoGarageDoor(coord, edata.devices[device_id])
        for device_id, coord in edata.coordinators.items()
    )


class MaveoGarageDoor(CoordinatorEntity[MaveoDeviceCoordinator], CoverEntity):
    """Maveo garage door."""

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
    _attr_has_entity_name = True
    _attr_translation_key = "garage_door"

    def __init__(self, coordinator: MaveoDeviceCoordinator, device: Device) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_cover"
        self._attr_device_info = maveo_device_info(coordinator.device_id, device.name)

    @property
    def available(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.get("online"))

    @property
    def is_closed(self) -> bool | None:
        pos = (self.coordinator.data or {}).get("door_position")
        if pos is None or pos == DOOR_STOPPED:
            return None
        return bool(pos == DOOR_CLOSED)

    @property
    def is_opening(self) -> bool:
        return (self.coordinator.data or {}).get("door_position") == DOOR_OPENING

    @property
    def is_closing(self) -> bool:
        return (self.coordinator.data or {}).get("door_position") == DOOR_CLOSING

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        pos = data.get("door_position")
        attrs: dict[str, Any] = {
            "position_name": DOOR_POSITION_NAMES.get(pos, "unknown")
            if isinstance(pos, int)
            else "unknown"
        }
        if data.get("ime_open") is not None:
            attrs["intermediate_open_configured"] = data["ime_open"]
            attrs["intermediate_close_configured"] = data["ime_close"]
        return attrs

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(Command.GARAGE_OPEN)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(Command.GARAGE_CLOSE)
