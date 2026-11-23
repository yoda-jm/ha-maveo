"""Maveo garage light entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import LightEntity
from homeassistant.components.light.const import ColorMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import Command
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
        async_add_entities([MaveoGarageLight(device)])

    entry.async_on_unload(entry.runtime_data.async_subscribe_devices(_add))


class MaveoGarageLight(MaveoEntity, LightEntity):
    """Maveo garage light."""

    _attr_translation_key = "garage_light"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, device: MaveoDevice) -> None:
        super().__init__(device, "light")

    @property
    def is_on(self) -> bool | None:
        val = self.data.get("light_on")
        return bool(val) if val is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(Command.LIGHT_ON)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(Command.LIGHT_OFF)
