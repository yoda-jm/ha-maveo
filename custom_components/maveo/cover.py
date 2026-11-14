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
    DOOR_INTERMEDIATE_CLOSED,
    DOOR_INTERMEDIATE_OPEN,
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
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )
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
    def assumed_state(self) -> bool:
        """Allow both directions when stopped between the end positions."""
        pos = (self.coordinator.data or {}).get("door_position")
        return pos in (
            DOOR_STOPPED,
            DOOR_INTERMEDIATE_OPEN,
            DOOR_INTERMEDIATE_CLOSED,
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
        data = self.coordinator.data or {}
        position_name = DOOR_POSITION_NAMES.get(
            data.get("door_position"), "unknown"
        )

        position_labels = {
            "Closed": "Geschlossen",
            "Open": "Vollständig geöffnet",
            "Opening": "Öffnet",
            "Closing": "Schließt",
            "Stopped": "Gestoppt",
            "IntermediateClosed": "Lüftungsposition",
            "IntermediateOpen": "Obere Zwischenposition",
            "unknown": "Unbekannt",
        }

        attrs = {
            "position_name": position_name,
            "position_display": position_labels.get(
                position_name, "Unbekannt"
            ),
        }

        if data.get("ime_open") is not None:
            attrs["intermediate_open_configured"] = data["ime_open"]
            attrs["intermediate_close_configured"] = data["ime_close"]

        return attrs

    async def async_open_cover(self, **kwargs) -> None:
        await self.coordinator.async_send_command(Command.GARAGE_OPEN)

    async def async_close_cover(self, **kwargs) -> None:
        await self.coordinator.async_send_command(Command.GARAGE_CLOSE)

    async def async_stop_cover(self, **kwargs) -> None:
        """Stop the garage door."""
        await self.coordinator.async_send_command(Command.GARAGE_STOP)
