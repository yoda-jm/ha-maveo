"""Maveo garage door cover entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import Command
from .api.iot import (
    DOOR_CLOSED,
    DOOR_CLOSING,
    DOOR_OPENING,
    DOOR_POSITION_NAMES,
    DOOR_STOPPED,
)
from .data import MaveoConfigEntry, MaveoDevice
from .entity import MaveoEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaveoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    @callback
    def _add(device: MaveoDevice) -> None:
        async_add_entities([MaveoGarageDoor(device)])

    entry.async_on_unload(entry.runtime_data.async_subscribe_devices(_add))


class MaveoGarageDoor(MaveoEntity, CoverEntity):
    """Maveo garage door."""

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
    _attr_translation_key = "garage_door"

    def __init__(self, device: MaveoDevice) -> None:
        super().__init__(device, "cover")

    @property
    def is_closed(self) -> bool | None:
        pos = self.data.get("door_position")
        if pos is None or pos == DOOR_STOPPED:
            return None
        return bool(pos == DOOR_CLOSED)

    @property
    def is_opening(self) -> bool:
        return bool(self.data.get("door_position") == DOOR_OPENING)

    @property
    def is_closing(self) -> bool:
        return bool(self.data.get("door_position") == DOOR_CLOSING)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pos = self.data.get("door_position")
        attrs: dict[str, Any] = {
            "position_name": DOOR_POSITION_NAMES.get(pos, "unknown")
            if isinstance(pos, int)
            else "unknown"
        }
        if self.data.get("ime_open") is not None:
            attrs["intermediate_open_configured"] = self.data["ime_open"]
            attrs["intermediate_close_configured"] = self.data["ime_close"]
        return attrs

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(Command.GARAGE_OPEN)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(Command.GARAGE_CLOSE)
