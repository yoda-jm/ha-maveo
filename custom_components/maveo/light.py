"""Maveo garage light entity."""
from __future__ import annotations

from homeassistant.components.light import LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MaveoDeviceCoordinator
from .iot import Command


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    edata = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        MaveoGarageLight(coord, edata["devices"][device_id])
        for device_id, coord in edata["coordinators"].items()
    )


class MaveoGarageLight(CoordinatorEntity[MaveoDeviceCoordinator], LightEntity):
    """Maveo garage light."""

    _attr_has_entity_name = True
    _attr_translation_key = "garage_light"
    _attr_icon = "mdi:lightbulb"

    def __init__(self, coordinator: MaveoDeviceCoordinator, device) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_light"
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
    def is_on(self) -> bool | None:
        val = (self.coordinator.data or {}).get("light_on")
        return bool(val) if val is not None else None

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_send_command(Command.LIGHT_ON)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_send_command(Command.LIGHT_OFF)
