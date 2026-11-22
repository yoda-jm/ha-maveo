"""Maveo garage light entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import LightEntity
from homeassistant.components.light.const import ColorMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import Device
from .coordinator import MaveoDeviceCoordinator
from .data import MaveoConfigEntry
from .entity import maveo_device_info
from .iot import Command


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaveoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    edata = entry.runtime_data
    async_add_entities(
        MaveoGarageLight(coord, edata.devices[device_id])
        for device_id, coord in edata.coordinators.items()
    )


class MaveoGarageLight(CoordinatorEntity[MaveoDeviceCoordinator], LightEntity):
    """Maveo garage light."""

    _attr_has_entity_name = True
    _attr_translation_key = "garage_light"
    _attr_icon = "mdi:lightbulb"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, coordinator: MaveoDeviceCoordinator, device: Device) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_light"
        self._attr_device_info = maveo_device_info(coordinator.device_id, device.name)

    @property
    def available(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.get("online"))

    @property
    def is_on(self) -> bool | None:
        val = (self.coordinator.data or {}).get("light_on")
        return bool(val) if val is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(Command.LIGHT_ON)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(Command.LIGHT_OFF)
