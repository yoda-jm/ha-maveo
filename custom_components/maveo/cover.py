"""Maveo garage door cover entity."""
from __future__ import annotations

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MaveoDeviceCoordinator
from .iot import (
    DOOR_CLOSED,
    DOOR_CLOSING,
    DOOR_OPENING,
    DOOR_POSITION_NAMES,
    DOOR_STOPPED,
    Command,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    edata = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        MaveoGarageDoor(coord, edata["devices"][device_id])
        for device_id, coord in edata["coordinators"].items()
    )


class MaveoGarageDoor(CoordinatorEntity[MaveoDeviceCoordinator], CoverEntity):
    """Maveo garage door."""

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
    _attr_has_entity_name = True
    _attr_translation_key = "garage_door"

    def __init__(self, coordinator: MaveoDeviceCoordinator, device) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_cover"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_id)},
            "name": device.name,
            "manufacturer": "Marantec",
            "model": "Maveo",
        }

    @property
    def available(self) -> bool:
        return bool(
            self.coordinator.data and self.coordinator.data.get("online")
        )

    @property
    def is_closed(self) -> bool | None:
        pos = (self.coordinator.data or {}).get("door_position")
        if pos is None or pos == DOOR_STOPPED:
            return None
        return pos == DOOR_CLOSED

    @property
    def is_opening(self) -> bool:
        return (self.coordinator.data or {}).get("door_position") == DOOR_OPENING

    @property
    def is_closing(self) -> bool:
        return (self.coordinator.data or {}).get("door_position") == DOOR_CLOSING

    @property
    def extra_state_attributes(self) -> dict:
        pos = (self.coordinator.data or {}).get("door_position")
        return {"position_name": DOOR_POSITION_NAMES.get(pos, "unknown")}

    async def async_open_cover(self, **kwargs) -> None:
        await self.coordinator.async_send_command(Command.GARAGE_OPEN)

    async def async_close_cover(self, **kwargs) -> None:
        # BlueFi supports a dedicated CLOSE command (AtoS_g:2).
        # Connect stick uses the toggle command (AtoS_g:0) which cycles the drive.
        is_bluefi = (self.coordinator.data or {}).get("is_bluefi", False)
        cmd = Command.GARAGE_CLOSE if is_bluefi else Command.GARAGE_STOP
        await self.coordinator.async_send_command(cmd)
