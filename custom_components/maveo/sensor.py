"""Maveo sensor entities — device sensors and dynamic guest sensors."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import GuestUser
from .const import DOMAIN
from .coordinator import MaveoDeviceCoordinator
from .guest_coordinator import MaveoGuestCoordinator


# ---------------------------------------------------------------------------
# Device sensors
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MaveoSensorDescription(SensorEntityDescription):
    data_key: str = ""
    availability_key: str | None = None  # coordinator data key that must be truthy


DEVICE_SENSORS: tuple[MaveoSensorDescription, ...] = (
    MaveoSensorDescription(
        key="firmware",
        translation_key="firmware",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="firmware",
    ),
    MaveoSensorDescription(
        key="ttc",
        translation_key="ttc",
        icon="mdi:timer",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="ttc_minutes",
    ),
    MaveoSensorDescription(
        key="rssi",
        translation_key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="wifi_ssid",  # special: handled in extra_state_attributes
    ),
    MaveoSensorDescription(
        key="buzzer",
        translation_key="buzzer",
        icon="mdi:bell",
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="buzzer_on",
    ),
    MaveoSensorDescription(
        key="stick_type",
        translation_key="stick_type",
        icon="mdi:help-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="is_bluefi",
    ),
    # Outdoor weather (requires GPS to be configured on the stick)
    MaveoSensorDescription(
        key="weather_temperature",
        translation_key="weather_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement="°C",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="weather_temperature",
        availability_key="has_gps",
    ),
    MaveoSensorDescription(
        key="weather_humidity",
        translation_key="weather_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="weather_humidity",
        availability_key="has_gps",
    ),
    # H+T sensor status entity (always visible, metadata as attributes)
    MaveoSensorDescription(
        key="ht_sensor",
        translation_key="ht_sensor",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="ht_sensor_paired",
    ),
    # Indoor H+T sensor readings (requires sensor to be paired)
    MaveoSensorDescription(
        key="indoor_temperature",
        translation_key="indoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement="°C",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="ht_temperature",
        availability_key="ht_sensor_paired",
    ),
    MaveoSensorDescription(
        key="indoor_humidity",
        translation_key="indoor_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        data_key="ht_humidity",
        availability_key="ht_sensor_paired",
    ),
    MaveoSensorDescription(
        key="indoor_battery",
        translation_key="indoor_battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="ht_battery",
        availability_key="ht_sensor_paired",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    edata = hass.data[DOMAIN][entry.entry_id]

    # Static device sensors
    entities: list[SensorEntity] = []
    for device_id, coord in edata["coordinators"].items():
        device = edata["devices"][device_id]
        for desc in DEVICE_SENSORS:
            entities.append(MaveoDeviceSensor(coord, device, desc))
    async_add_entities(entities)

    # Dynamic guest sensors — one per guest, created as they appear
    for device_id, guest_coord in edata["guest_coordinators"].items():
        device = edata["devices"][device_id]
        _setup_guest_sensor_tracking(hass, entry, guest_coord, device_id, device, async_add_entities)


def _setup_guest_sensor_tracking(
    hass: HomeAssistant,
    entry: ConfigEntry,
    guest_coord: MaveoGuestCoordinator,
    device_id: str,
    device,
    async_add_entities: AddEntitiesCallback,
) -> None:
    tracked: set[str] = set()

    @callback
    def _on_update() -> None:
        guests: list[GuestUser] = guest_coord.data or []
        new = [
            MaveoGuestSensor(guest_coord, g.user_id, device_id, device)
            for g in guests
            if g.user_id not in tracked
        ]
        for e in new:
            tracked.add(e.user_id)
        if new:
            async_add_entities(new)

    entry.async_on_unload(guest_coord.async_add_listener(_on_update))
    _on_update()


# ---------------------------------------------------------------------------
# Device sensor entity
# ---------------------------------------------------------------------------

class MaveoDeviceSensor(CoordinatorEntity[MaveoDeviceCoordinator], SensorEntity):
    """A single device diagnostic sensor."""

    entity_description: MaveoSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MaveoDeviceCoordinator,
        device,
        description: MaveoSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_id)},
            "name": device.name,
            "manufacturer": "Marantec",
            "model": "Maveo",
        }

    @property
    def available(self) -> bool:
        data = self.coordinator.data or {}
        if not data.get("online"):
            return False
        av_key = self.entity_description.availability_key
        if av_key is not None:
            return bool(data.get(av_key))
        return True

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        key = self.entity_description.data_key

        if self.entity_description.key == "rssi":
            return data.get("wifi_rssi")
        if self.entity_description.key == "buzzer":
            val = data.get("buzzer_on")
            return "on" if val else "off" if val is not None else None
        if self.entity_description.key == "stick_type":
            is_bluefi = data.get("is_bluefi")
            if is_bluefi is None:
                return None
            return "BlueFi" if is_bluefi else "Connect"
        if self.entity_description.key == "ht_sensor":
            paired = data.get("ht_sensor_paired")
            if paired is None:
                return None
            return "paired" if paired else "not paired"
        return data.get(key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        if self.entity_description.key == "rssi":
            attrs: dict[str, Any] = {}
            if data.get("wifi_ssid") is not None:
                attrs["ssid"] = data["wifi_ssid"]
            if data.get("wifi_ip") is not None:
                attrs["ip"] = data["wifi_ip"]
            if data.get("wifi_mac") is not None:
                attrs["mac"] = data["wifi_mac"]
            return attrs
        if self.entity_description.key == "ht_sensor":
            attrs = {}
            for src_key, attr_name in (
                ("ht_temperature",  "temperature"),
                ("ht_humidity",     "humidity"),
                ("ht_battery",      "battery"),
                ("ht_last_update",  "last_update"),
                ("ht_name",         "name"),
                ("ht_manufacturer", "manufacturer"),
                ("ht_model",        "model"),
                ("ht_serial",       "serial"),
                ("ht_firmware_rev", "firmware_rev"),
                ("ht_software_rev", "software_rev"),
                ("ht_hardware_rev", "hardware_rev"),
            ):
                val = data.get(src_key)
                if val is not None:
                    attrs[attr_name] = val
            return attrs
        return {}


# ---------------------------------------------------------------------------
# Guest sensor entity
# ---------------------------------------------------------------------------

class MaveoGuestSensor(CoordinatorEntity[MaveoGuestCoordinator], SensorEntity):
    """Sensor entity for a single guest key — shows TTL and metadata."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-key"

    def __init__(
        self,
        coordinator: MaveoGuestCoordinator,
        user_id: str,
        device_id: str,
        device,
    ) -> None:
        super().__init__(coordinator)
        self.user_id = user_id
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_guest_{user_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": device.name,
            "manufacturer": "Marantec",
            "model": "Maveo",
        }

    def _get_guest(self) -> GuestUser | None:
        return next(
            (g for g in (self.coordinator.data or []) if g.user_id == self.user_id),
            None,
        )

    @property
    def available(self) -> bool:
        return self._get_guest() is not None

    @property
    def name(self) -> str:
        guest = self._get_guest()
        if guest and guest.nametag1:
            return f"Guest: {guest.nametag1}"
        return f"Guest {self.user_id[:8]}"

    @property
    def native_value(self) -> str:
        guest = self._get_guest()
        if guest is None:
            return "unavailable"
        if guest.ttl == "token expired" or not guest.ttl.isdigit():
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
            import datetime
            attrs["expires_at"] = datetime.datetime.fromtimestamp(
                int(guest.ttl), tz=datetime.timezone.utc
            ).isoformat()
        return attrs
