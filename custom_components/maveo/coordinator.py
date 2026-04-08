"""Device state coordinator — MQTT burst-poll every 30 s."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .auth import authenticate, AuthResult
from .client import MaveoClient
from .const import DOMAIN, DEVICE_POLL_INTERVAL
from .iot import Command, MaveoIoTClient

_LOGGER = logging.getLogger(__name__)

_READ_COMMANDS = [
    ("door_position", Command.STATUS,      "StoA_s"),
    ("firmware",      Command.VERSION,     "StoA_v"),
    ("light_on",      Command.LIGHT_READ,  "StoA_l_r"),
    ("serial",        Command.SERIAL,      "StoA_serial"),
    ("device_name",   Command.NAME_READ,   "StoA_name_r"),
    ("ttc_minutes",   Command.TTC_READ,    "StoA_ttc_r"),
    ("buzzer_on",     Command.BUZZER_READ, "StoA_buzzer_r"),
    ("gps",           Command.GPS_READ,      None),
    ("wifi",          Command.WIFI_READ,     None),
    ("ime",           Command.IME_LEARN_READ, None),
]

_EMPTY: dict[str, Any] = {
    "online":              False,
    "is_bluefi":           None,
    "door_position":       None,
    "light_on":            None,
    "firmware":            None,
    "serial":              None,
    "device_name":         None,
    "ttc_minutes":         None,
    "buzzer_on":           None,
    "gps_lat":             None,
    "gps_lng":             None,
    "has_gps":             False,
    "wifi_ssid":           None,
    "wifi_ip":             None,
    "wifi_mac":            None,
    "wifi_rssi":           None,
    "ime_open":            None,
    "ime_close":           None,
    "ht_sensor_paired":    None,
    "ht_temperature":      None,
    "ht_humidity":         None,
    "ht_battery":          None,
    "ht_name":             None,
    "ht_manufacturer":     None,
    "ht_model":            None,
    "ht_serial":           None,
    "ht_firmware_rev":     None,
    "ht_software_rev":     None,
    "ht_hardware_rev":     None,
    "ht_last_update":      None,
    "weather_temperature": None,
    "weather_humidity":    None,
}


class MaveoDeviceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for a single Maveo device — MQTT burst-poll."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"Maveo device {device_id}",
            update_interval=timedelta(seconds=DEVICE_POLL_INTERVAL),
        )
        self._entry = entry
        self.device_id = device_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _edata(self) -> dict:
        return self.hass.data[DOMAIN][self._entry.entry_id]

    async def _refresh_auth_if_needed(self) -> None:
        auth: AuthResult = self._edata()["auth"]
        expiry = auth.expiration
        if not expiry.tzinfo:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry < datetime.now(timezone.utc) + timedelta(minutes=10):
            edata = self._edata()
            _LOGGER.debug("Refreshing Maveo AWS credentials")
            new_auth = await self.hass.async_add_executor_job(
                authenticate, edata["email"], edata["password"], edata["config"]
            )
            edata["auth"] = new_auth
            edata["client"] = MaveoClient(new_auth, edata["config"])

    # ------------------------------------------------------------------
    # DataUpdateCoordinator
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            await self._refresh_auth_if_needed()
        except Exception as err:
            raise UpdateFailed(f"Auth refresh failed: {err}") from err

        edata = self._edata()
        client: MaveoClient = edata["client"]

        try:
            status = await self.hass.async_add_executor_job(
                client.get_device_status, self.device_id
            )
        except Exception as err:
            raise UpdateFailed(f"Status check failed: {err}") from err

        result = dict(_EMPTY)
        result["online"] = status.is_online

        if not result["online"]:
            return result

        try:
            result.update(
                await self._fetch_mqtt_state(edata["auth"], edata["config"])
            )
        except Exception as err:
            _LOGGER.warning(
                "MQTT state fetch failed for %s: %s", self.device_id, err
            )

        return result

    async def _fetch_mqtt_state(self, auth: AuthResult, config) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        async with MaveoIoTClient(auth, config, self.device_id) as iot:
            await iot.subscribe()
            for key, cmd, response_key in _READ_COMMANDS:
                await iot.send(cmd)

                if key == "door_position":
                    # BlueFi sends a full state dump before StoA_s (which arrives last).
                    # Connect stick sends only StoA_s.
                    # Detect stick type by whether we receive any non-StoA_s packet first.
                    is_bluefi = False
                    for _ in range(15):
                        pkt = await iot.receive(timeout=3.0)
                        if not pkt or "json" not in pkt:
                            break
                        d = pkt["json"]
                        if "StoA_s" in d:
                            updates["door_position"] = d["StoA_s"]
                            break
                        is_bluefi = True
                    updates["is_bluefi"] = is_bluefi
                    continue

                pkt = await iot.receive(timeout=3.0)
                if not pkt or "json" not in pkt:
                    continue
                d = pkt["json"]

                if key == "gps":
                    if d.get("StoA_gps") == 0:
                        updates["gps_lat"] = d.get("lat")
                        updates["gps_lng"] = d.get("lng")
                        if updates["gps_lat"] is not None:
                            updates["has_gps"] = True
                elif key == "wifi":
                    updates["wifi_ssid"] = d.get("ssid")
                    updates["wifi_ip"]   = d.get("ip")
                    updates["wifi_mac"]  = d.get("mac")
                    updates["wifi_rssi"] = d.get("rssi")
                elif key == "ime":
                    if "StoA_ime_learn" in d:
                        updates["ime_open"]  = bool(d.get("open"))
                        updates["ime_close"] = bool(d.get("close"))
                elif key == "light_on":
                    val = d.get(response_key)
                    if val is not None:
                        updates["light_on"] = bool(val)
                elif key == "buzzer_on":
                    val = d.get(response_key)
                    if val is not None:
                        updates["buzzer_on"] = bool(val)
                elif response_key and response_key in d:
                    updates[key] = d[response_key]

            # H+T sensor — detect presence first, then fetch readings if paired
            await iot.send(Command.SENSOR_PRESENCE)
            pkt = await iot.receive(timeout=3.0)
            if pkt and "json" in pkt:
                d = pkt["json"]
                paired = (
                    d.get("StoA_sensor") == 0
                    and d.get("command") == 0
                    and d.get("error") == 0
                )
                updates["ht_sensor_paired"] = paired
                if paired:
                    # SENSOR_FULL returns readings + metadata in one shot
                    await iot.send(Command.SENSOR_FULL)
                    # Two responses arrive: data packet then {"state":9} — stop at data
                    for _ in range(2):
                        pkt = await iot.receive(timeout=3.0)
                        if pkt and "json" in pkt:
                            d = pkt["json"]
                            if "temperature_val" in d:
                                updates["ht_temperature"] = d["temperature_val"] / 100.0
                                updates["ht_humidity"] = d["humidity_val"] / 100.0
                                updates["ht_battery"] = d.get("battery_val")
                                updates["ht_last_update"] = d.get("last_update")
                                updates["ht_name"] = d.get("name") or None
                                updates["ht_manufacturer"] = d.get("manufacturer") or None
                                updates["ht_model"] = d.get("model") or None
                                updates["ht_serial"] = d.get("serial_num") or None
                                updates["ht_firmware_rev"] = d.get("firmware_rev") or None
                                updates["ht_software_rev"] = d.get("software_rev") or None
                                updates["ht_hardware_rev"] = d.get("hardware_rev") or None
                                break

            # Outdoor weather — only meaningful with GPS coordinates
            if updates.get("has_gps"):
                weather_cmd = {
                    "AtoS_weather": 0,
                    "lat": updates["gps_lat"],
                    "lng": updates["gps_lng"],
                }
                await iot.send(weather_cmd)
                pkt = await iot.receive(timeout=3.0)
                if pkt and "json" in pkt:
                    d = pkt["json"]
                    if d.get("StoA_weather") == 0:
                        temp = d.get("temperature")
                        hum = d.get("humidity")
                        if temp is not None:
                            updates["weather_temperature"] = temp / 100.0
                        if hum is not None:
                            updates["weather_humidity"] = hum / 100.0

        return updates

    # ------------------------------------------------------------------
    # Command helper
    # ------------------------------------------------------------------

    async def async_send_command(self, command: dict) -> None:
        """Send an IoT command then schedule a coordinator refresh."""
        edata = self._edata()
        auth: AuthResult = edata["auth"]
        config = edata["config"]

        async with MaveoIoTClient(auth, config, self.device_id) as iot:
            await iot.subscribe()
            await iot.send(command)
            await iot.receive(timeout=1.0)  # drain any immediate response

        await asyncio.sleep(2)
        await self.async_request_refresh()
