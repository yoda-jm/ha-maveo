# IoT / MQTT over WebSocket

## Summary

| Step | Status | Notes |
|---|---|---|
| WebSocket upgrade (SigV4) | **working** | |
| MQTT CONNECT | **working** | client_id = device_id required |
| MQTT SUBSCRIBE | **working** | topic = `{device_id}/rsp` |
| MQTT PUBLISH | **working** | topic = `{device_id}/cmd` |
| All read commands | **working** | see command table below |

---

## Transport

The device communicates via **MQTT 3.1.1 over WebSocket** (subprotocol `mqtt`)
against:

```
wss://<region>.iot-prod.marantec-cloud.de/mqtt
```

AWS IoT Core is the broker.

---

## Authentication — SigV4 headers

The WebSocket upgrade request is authenticated with AWS SigV4 **header-based**
signing (not query-parameter signing).  Service name: `iotdata`.

Headers added to the upgrade request:

```
Host:                 <region>.iot-prod.marantec-cloud.de
X-Amz-Date:           20250101T120000Z
X-Amz-Security-Token: <session_token>
Authorization:        AWS4-HMAC-SHA256 Credential=<access_key>/<date>/<region>/iotdata/aws4_request,
                      SignedHeaders=host;x-amz-date;x-amz-security-token,
                      Signature=<sig>
User-Agent:           MaveoApp/2.6.0
```

The canonical request is:
```
GET
/mqtt
<empty query string>
host:<hostname>\nx-amz-date:<amz_date>\nx-amz-security-token:<token>\n
host;x-amz-date;x-amz-security-token
<sha256 of empty body>
```

---

## MQTT CONNECT packet

After the WebSocket is open, a standard MQTT 3.1.1 CONNECT packet is sent:

```
Fixed header:  0x10
Protocol:      "MQTT" (3.1.1, level 0x04)
Connect flags: 0x02 (clean session)
Keep-alive:    60 s
Client ID:     <device_id>
```

The client ID **must** be the device ID string (numeric, e.g. `<device_id>`).
AWS IoT policies enforce this — any other client ID results in an immediate
connection drop before CONNACK.

CONNACK response (4 bytes: `0x20 0x02 0x00 0x00`):
- Return code `0x00` = Connection Accepted ✓

**Note:** Connecting with device_id as client_id temporarily displaces the stick's
own MQTT session (same client_id conflict). The stick reconnects automatically
within a few seconds. This is the same behaviour as the real app.

---

## MQTT topics

**Confirmed via live testing (2026-03-28):**

| Topic | Direction | Purpose |
|---|---|---|
| `{device_id}/cmd` | client → broker → device | Send commands to the device |
| `{device_id}/rsp` | device → broker → client | Receive device responses |

The `{device_id}` is the numeric device ID from `list_device`.

**Important:** The session UUID from `GET /admin status` (`DeviceStatus.session`) is
**NOT** used in MQTT topics. It only indicates whether the device is currently
online. The previous (incorrect) assumption that session UUID was the topic prefix
caused all subscribe attempts to fail.

Source: `BlueFiController::sendCommand()` in `libmaveo-app_armeabi-v7a.so` —
topic template is `"%1/cmd"` where `%1 = this + 0x1c` (the stickId, set from the
numeric device ID).

---

## Command reference

All commands are JSON payloads published to `{device_id}/cmd`.
Responses arrive on `{device_id}/rsp`.

### Actions (no response expected)

| Action | Payload |
|---|---|
| Light ON | `{"AtoS_l": 1}` |
| Light OFF | `{"AtoS_l": 0}` |
| Garage OPEN | `{"AtoS_g": 1}` |
| Garage CLOSE | `{"AtoS_g": 0}` |
| Garage STOP | `{"AtoS_g": 2}` |

### Read commands (response on rsp topic)

| Command | Payload | Response key | Example value |
|---|---|---|---|
| Door status | `{"AtoS_s": 0}` | `StoA_s` | `4` (closed) |
| Firmware version | `{"AtoS_v": 0}` | `StoA_v` | `"1.2.0"` |
| Light state | `{"AtoS_l_r": 0}` | `StoA_l_r` | `0` (off) / `1` (on) |
| Serial number | `{"AtoS_get_serial": 0}` | `StoA_serial` | `"<device_id>"` |
| Device name | `{"AtoS_name_r": 0}` | `StoA_name_r` | `"<device-name>"` |
| Time-to-close | `{"AtoS_ttc_r": 0}` | `StoA_ttc_r` | `0` (disabled) |
| Buzzer state | `{"AtoS_buzzer_r": 0}` | `StoA_buzzer_r` | `"0"` |
| GPS location | `{"AtoS_gps_req": 0}` | `StoA_gps` + `lat` + `lng` | `{"StoA_gps": 0, "lat": <lat>, "lng": <lng>}` |
| WiFi info | `{"AtoS_wifi_ap": 0}` | `StoA_wifi_ap` + fields | `{"StoA_wifi_ap": 0, "ssid": "<ssid>", "ip": "<ip>", "mac": "<mac>", "rssi": -73, "error": 0}` |

### Additional commands (found in binary, not yet tested)

| Command | Payload | Notes |
|---|---|---|
| Buzzer write | `{"AtoS_buzzer_w": ...}` | Set buzzer enabled/disabled |
| GPS write | `{"AtoS_gps_write": {...}}` | Set GPS coordinates |
| Name set | `{"AtoS_name_s": "..."}` | Set device name |
| TTC write | `{"AtoS_ttc_w": N}` | Set time-to-close minutes |
| Sensor read | `{"AtoS_sensor": ...}` | → `StoA_sensor` |
| Ventilation | `{"AtoS_ventilation": ...}` | → `StoA_ventilation`, `StoA_vent_state` |
| Weather | `{"AtoS_weather": ...}` | → `StoA_weather` |
| IME learn | `{"AtoS_req_ime_learn": ...}` | → `StoA_ime_learn` |
| Brake | `{"AtoS_b": ...}` | → `StoA_b` |

### Door status codes (`StoA_s`)

Full `DoorPosition` enum extracted from binary string table (sequential, starts at 0):

| Value | Name | Description |
|---|---|---|
| `0` | `DoorPositionStopped` | Stopped mid-course (**confirmed live**) |
| `1` | `DoorPositionOpening` | Door is moving open (**confirmed live**) |
| `2` | `DoorPositionClosing` | Door is moving closed (**confirmed live**) |
| `3` | `DoorPositionOpen` | Door is fully open (**confirmed live**) |
| `4` | `DoorPositionClosed` | Door is fully closed (**confirmed live**) |
| `5` | `DoorPositionIntermediateOpen` | Unknown — from binary enum, never observed |
| `6` | `DoorPositionIntermediateClosed` | Unknown — from binary enum, never observed |

The original binary enum name for `0` is `DoorPositionUnknown` but live testing
confirms it is sent when the door is stopped mid-travel. Values 5 and 6 exist in the
binary string table but have not been observed in practice — their exact meaning is unknown.

---

## Live device data (confirmed 2026-03-28)

Responses from a live BlueFi device:

```json
{"StoA_v":    "1.2.0"}
{"StoA_s":    4}
{"StoA_l_r":  0}
{"StoA_serial": "<device_id>"}
{"StoA_name_r": "<device-name>"}
{"StoA_ttc_r":  0}
{"StoA_buzzer_r": "0"}
{"StoA_gps": 0, "lat": <lat>, "lng": <lng>}
{"StoA_wifi_ap": 0, "ssid": "<ssid>", "ip": "<stick-ip>", "mac": "<mac>", "rssi": -73, "error": 0}
```

---

## Protocol sequence

1. Send MQTT CONNECT (client_id = device_id)
2. Wait for CONNACK (return_code = 0)
3. Send MQTT SUBSCRIBE to `{device_id}/rsp` (QoS 0, packet_id = 1)
4. Wait for SUBACK (granted_qos = [0])
5. Send MQTT PUBLISH to `{device_id}/cmd` with command JSON
6. Receive MQTT PUBLISH on `{device_id}/rsp` with response JSON

Implemented in `maveo/iot.py` (`MaveoIoTClient`).

---

## PINGREQ / keepalive

Keep-alive interval is 60 s (set in CONNECT).  PINGREQ is two bytes:
`0xC0 0x00`.  PINGRESP is two bytes: `0xD0 0x00`.

---

## Previous investigation dead-end

Earlier attempts subscribed to `{session_uuid}/rsp` where `session_uuid` came
from `DeviceStatus.session`. This caused immediate 1005 WebSocket close because
the AWS IoT policy denies subscriptions to unknown topic filters. The correct
topic prefix is the **device_id**, not the session UUID.
