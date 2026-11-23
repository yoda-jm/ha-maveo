"""Maveo sensor entities — device sensors and one sensor per guest key."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import GuestUser
from .const import DOMAIN
from .coordinator import MaveoGuestCoordinator
from .data import MaveoConfigEntry, MaveoDevice
from .entity import MaveoEntity, maveo_device_info

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MaveoSensorDescription(SensorEntityDescription):
    data_key: str
    availability_key: str | None = None  # coordinator data key that must be truthy


DEVICE_SENSORS: tuple[MaveoSensorDescription, ...] = (
    MaveoSensorDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="firmware",
    ),
    MaveoSensorDescription(
        key="ttc",
        translation_key="ttc",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        data_key="ttc_minutes",
    ),
    MaveoSensorDescription(
        key="rssi",
        translation_key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        data_key="wifi_rssi",
    ),
    MaveoSensorDescription(
        key="buzzer",
        translation_key="buzzer",
        device_class=SensorDeviceClass.ENUM,
        options=["on", "off"],
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="buzzer_on",
    ),
    MaveoSensorDescription(
        key="stick_type",
        translation_key="stick_type",
        device_class=SensorDeviceClass.ENUM,
        options=["bluefi", "connect"],
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        data_key="is_bluefi",
    ),
    # Outdoor weather (requires GPS to be configured on the stick)
    MaveoSensorDescription(
        key="weather_temperature",
        translation_key="weather_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        data_key="weather_temperature",
        availability_key="has_gps",
    ),
    MaveoSensorDescription(
        key="weather_humidity",
        translation_key="weather_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        data_key="weather_humidity",
        availability_key="has_gps",
    ),
    # H+T sensor status entity (always visible, metadata as attributes)
    MaveoSensorDescription(
        key="ht_sensor",
        translation_key="ht_sensor",
        device_class=SensorDeviceClass.ENUM,
        options=["paired", "not_paired"],
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="ht_sensor_paired",
    ),
    # Indoor H+T sensor readings (requires sensor to be paired)
    MaveoSensorDescription(
        key="indoor_temperature",
        translation_key="indoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        data_key="ht_temperature",
        availability_key="ht_sensor_paired",
    ),
    MaveoSensorDescription(
        key="indoor_humidity",
        translation_key="indoor_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        data_key="ht_humidity",
        availability_key="ht_sensor_paired",
    ),
    MaveoSensorDescription(
        key="indoor_battery",
        translation_key="indoor_battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="ht_battery",
        availability_key="ht_sensor_paired",
    ),
)

# Coordinator keys exposed as attributes of the H+T sensor status entity.
_HT_ATTRIBUTES = (
    ("ht_temperature", "temperature"),
    ("ht_humidity", "humidity"),
    ("ht_battery", "battery"),
    ("ht_last_update", "last_update"),
    ("ht_name", "name"),
    ("ht_manufacturer", "manufacturer"),
    ("ht_model", "model"),
    ("ht_serial", "serial"),
    ("ht_firmware_rev", "firmware_rev"),
    ("ht_software_rev", "software_rev"),
    ("ht_hardware_rev", "hardware_rev"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaveoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    @callback
    def _add(device: MaveoDevice) -> None:
        async_add_entities(MaveoDeviceSensor(device, desc) for desc in DEVICE_SENSORS)
        _track_guests(hass, device, async_add_entities)

    entry.async_on_unload(entry.runtime_data.async_subscribe_devices(_add))


@callback
def _track_guests(
    hass: HomeAssistant,
    device: MaveoDevice,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a sensor per guest key and remove it when the key is gone."""
    tracked: set[str] = set()
    coordinator = device.guests

    @callback
    def _on_update() -> None:
        if not coordinator.last_update_success:
            return
        current = {g.user_id for g in coordinator.data or []}
        new = current - tracked
        if new:
            async_add_entities(
                MaveoGuestSensor(device, coordinator, user_id) for user_id in new
            )
            tracked.update(new)
        registry = er.async_get(hass)
        for user_id in tracked - current:
            entity_id = registry.async_get_entity_id(
                "sensor", DOMAIN, _guest_unique_id(device.info.id, user_id)
            )
            if entity_id is not None:
                registry.async_remove(entity_id)
            tracked.discard(user_id)

    device.async_on_remove(coordinator.async_add_listener(_on_update))
    _on_update()


def _guest_unique_id(device_id: str, user_id: str) -> str:
    return f"{device_id}_guest_{user_id}"


class MaveoDeviceSensor(MaveoEntity, SensorEntity):
    """A single device sensor."""

    entity_description: MaveoSensorDescription

    def __init__(
        self, device: MaveoDevice, description: MaveoSensorDescription
    ) -> None:
        super().__init__(device, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        av_key = self.entity_description.availability_key
        return super().available and (av_key is None or bool(self.data.get(av_key)))

    @property
    def native_value(self) -> Any:
        key = self.entity_description.key
        value = self.data.get(self.entity_description.data_key)
        if value is None:
            return None
        if key == "buzzer":
            return "on" if value else "off"
        if key == "stick_type":
            return "bluefi" if value else "connect"
        if key == "ht_sensor":
            return "paired" if value else "not_paired"
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        key = self.entity_description.key
        if key == "rssi":
            return {
                attr: self.data[src]
                for src, attr in (
                    ("wifi_ssid", "ssid"),
                    ("wifi_ip", "ip"),
                    ("wifi_mac", "mac"),
                )
                if self.data.get(src) is not None
            }
        if key == "ht_sensor":
            return {
                attr: self.data[src]
                for src, attr in _HT_ATTRIBUTES
                if self.data.get(src) is not None
            }
        return None


class MaveoGuestSensor(CoordinatorEntity[MaveoGuestCoordinator], SensorEntity):
    """Remaining validity of one guest key. The token is never exposed."""

    _attr_has_entity_name = True
    _attr_translation_key = "guest"

    def __init__(
        self, device: MaveoDevice, coordinator: MaveoGuestCoordinator, user_id: str
    ) -> None:
        super().__init__(coordinator)
        self.user_id = user_id
        self._attr_unique_id = _guest_unique_id(device.info.id, user_id)
        self._attr_translation_placeholders = {"guest": user_id[:8]}
        self._attr_device_info = maveo_device_info(device)

    def _get_guest(self) -> GuestUser | None:
        return next(
            (g for g in (self.coordinator.data or []) if g.user_id == self.user_id),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self._get_guest() is not None

    @property
    def native_value(self) -> str | None:
        guest = self._get_guest()
        if guest is None:
            return None
        if not guest.ttl.isdigit():
            return "expired"
        remaining = int(guest.ttl) - int(time.time())
        if remaining <= 0:
            return "expired"
        hours, rem = divmod(remaining, 3600)
        minutes = rem // 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        guest = self._get_guest()
        if guest is None:
            return {}
        attrs: dict[str, Any] = {
            "user_id": guest.user_id,
            "rights": "admin" if guest.rights == "1" else "restricted",
            "claimed": guest.is_claimed,
        }
        if guest.nametag1:
            attrs["app_name"] = guest.nametag1
        if guest.nametag2:
            attrs["os"] = guest.nametag2
        if guest.nametag3:
            attrs["locale"] = guest.nametag3
        if guest.ttl.isdigit():
            attrs["expires_at"] = datetime.fromtimestamp(
                int(guest.ttl), tz=UTC
            ).isoformat()
        return attrs
