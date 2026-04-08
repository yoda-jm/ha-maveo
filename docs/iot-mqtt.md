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

### Actions

All garage commands return `{"StoA_g_r": 1}` as an acknowledgement (not an error).

| Action | Payload | Notes |
|---|---|---|
| Light ON | `{"AtoS_l": 1}` | |
| Light OFF | `{"AtoS_l": 0}` | |
| Garage OPEN | `{"AtoS_g": 1}` | **confirmed live** |
| Garage CLOSE | `{"AtoS_g": 2}` | **confirmed live** — was incorrectly documented as 0 |
| Garage STOP | `{"AtoS_g": 0}` | **confirmed live** — was incorrectly documented as 2 |
| Garage VENTILATE | `{"AtoS_g": 3}` | from binary (`ventilateGarageDoor`), not yet tested live |

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

### STATUS behaviour depends on stick type

`{"AtoS_s": 0}` behaviour differs by hardware:

| Stick type | STATUS response |
|---|---|
| **maveo connect** (Wi-Fi stick, standalone) | `StoA_s` only |
| **maveo BlueFi** (plugged into Marantec Comfort 360) | Full state dump — see below |

The full dump observed on a BlueFi device (status `"new"`, confirmed 2026-04-08):

| Response key | Notes |
|---|---|
| `StoA_ventilation` (command 0) | Ventilation runtime state — sent **twice** |
| `StoA_weather` | Outdoor weather (see below) |
| `StoA_sensor` (command 0) | HT sensor presence / BT address |
| `StoA_ventilation` (command 1) | Ventilation config / schedule |
| `StoA_sensor` (command 5) | Sensor update interval |
| `StoA_gps` | GPS coordinates |
| `StoA_wifi_ap` | Wi-Fi info |
| `StoA_ime_learn` | IME learned open/close positions |
| `StoA_s` | Door position — always **last** |

### Standalone read commands (confirmed 2026-04-08)

All of these work on both stick types via explicit request:

| Command | Payload | Response | Notes |
|---|---|---|---|
| Ventilation state | `{"AtoS_ventilation": 0, "command": 0}` | `StoA_ventilation` (command 0) | `mode:0` = disabled |
| Ventilation config | `{"AtoS_ventilation": 0, "command": 1}` | `StoA_ventilation` (command 1) | Full schedule fields |
| Sensor presence | `{"AtoS_sensor": 0, "command": 0}` | `StoA_sensor` (command 0) | `error:2` = no HT sensor paired |
| Sensor update interval | `{"AtoS_sensor": 0, "command": 5}` | `StoA_sensor` (command 5) | Returns interval even without sensor |
| Sensor metadata | `{"AtoS_sensor": 0, "command": 6}` | `StoA_sensor` (command 6) | `name`, `manufacturer`, `model`, `serial_num`, `firmware_rev`, `software_rev`, `hardware_rev` |
| Sensor readings | `{"AtoS_sensor": 0, "command": 7}` | `StoA_sensor` (command 7) | `temperature_val`, `humidity_val`, `battery_val`, `last_update` — **use this for live readings** |
| Sensor readings + metadata | `{"AtoS_sensor": 0, "command": 8}` | `StoA_sensor` (command 8) | Combined fields of commands 6 and 7 |
| IME positions | `{"AtoS_req_ime_learn": 0}` | `StoA_ime_learn` | `open`/`close`: 0=not learned, 1=learned |
| Weather | `{"AtoS_weather": 0}` | `StoA_weather` | lat/lng optional — see below |

**Feature detection via error field:**
`{"AtoS_sensor": 0, "command": 0}` → `error:0` = HT sensor paired, `error:2` = no sensor.
Commands 6/7/8 always respond with `error:0` regardless of sensor presence — use command 0 to detect pairing.
Ventilation always responds (even if unconfigured) — use `mode:0` to detect disabled.

**H+T sensor commands produce two responses:** the data packet followed by `{"StoA_sensor":0,"command":N,"error":0,"state":9}` — meaning of `state:9` unknown, discard it.

**H+T sensor units** (unconfirmed — all-zero response when no sensor paired, assumed same as weather):
`temperature_val`: 0.01 °C. `humidity_val`: 0.01 %. `battery_val`: likely 0–100 %.

**`AtoS_vent_state` does not exist as a request** — `StoA_vent_state` is only pushed in the BlueFi STATUS dump, never requestable.

### Weather command

`{"AtoS_weather": 0}` — lat/lng are optional:
- Without coordinates (or `lat:0, lng:0`): returns the **last cached weather value** from a previous fetch — likely not weather at 0°N 0°E
- With real GPS coordinates: fetches outdoor weather for that location from the cloud and caches the result

The weather data is used by the ventilation logic to decide whether to open the door.
Temperature unit: 0.01 °C (e.g. `2900` = 29.00 °C). Humidity unit: 0.01 % (e.g. `6600` = 66.00 %).

### Additional write commands (from binary, not yet tested live)

| Command | Payload | Notes |
|---|---|---|
| Buzzer write | `{"AtoS_buzzer_w": 0\|1}` | Set buzzer enabled/disabled |
| GPS write | `{"AtoS_gps_write": {...}}` | Set GPS coordinates |
| Name set | `{"AtoS_name_s": "..."}` | Set device name |
| TTC write | `{"AtoS_ttc_w": N}` | Set time-to-close minutes |
| Garage ventilate | `{"AtoS_g": 3}` | Open to ventilation position (partial open) |
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
| `5` | `DoorPositionIntermediateOpen` | Door stopped at the learned **Intermediate position OPEN** |
| `6` | `DoorPositionIntermediateClosed` | Door stopped at the learned **Intermediate position CLOSED** |

The original binary enum name for `0` is `DoorPositionUnknown` but live testing
confirms it is sent when the door is stopped mid-travel.

Values 5 and 6 correspond to the **Intermediate position** feature of compatible
Marantec drives. Two additional stops can be taught alongside the standard Open/Closed
endpoints:

```
Fully Closed — Intermediate Closed — Intermediate Open — Fully Open
     4                 6                     5                3
```

Both must be explicitly assigned to a remote or stick button to be triggered — they are
not automatically accessible just because the drive knows them. Only one coordinate per
type is stored (most recently taught wins).

`AtoS_g:3` (`ventilateGarageDoor`) moves to one of the intermediate positions. The maveo
app labels this "ventilate". **Which intermediate position is targeted is unknown —
Marantec documentation is conflicting on this point.**

Feature presence: `StoA_ime_learn` → `open:1, close:1` = both positions taught;
`open:0, close:0` = not configured. `ime_pos_valid` in `StoA_ventilation` carries the
same information.

---

## Live device data

### Confirmed 2026-03-28 — individual read commands

Responses from a live BlueFi device (status `"CONNECTED"`):

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

### Confirmed 2026-04-08 — BlueFi STATUS dump (device status `"new"`)

All of the following arrived in a single burst after sending `{"AtoS_s": 0}` on a BlueFi stick:

```json
{"StoA_ventilation":0,"command":0,"error":0,"mode":2,"active":0,"ime_pos_valid":1,"blocked":0,"manual_vent":0,"test_mode":0,"debug":0}
{"StoA_weather":0,"humidity":4800,"temperature":700,"last_update":1775628089}
{"StoA_sensor":0,"command":0,"error":0,"bt_addr":[33,102,3,246,88,240]}
{"StoA_ventilation":0,"command":1,"error":0,"mode":2,"test_mode":0,"temp_low":10,"temp_high":30,"threshold":65,"vent_duration":30,"block_time":120,"dew_point_diff":0,"weather_update_interval":18,"end_time":"17:00","start_time":"06:00","weekdays":127,"time_based_time":"00:00-00:00","time_based_weekdays":0}
{"StoA_sensor":0,"command":5,"error":0,"update_interval":15}
{"StoA_gps":0,"lat":<lat>,"lng":<lng>}
{"StoA_wifi_ap":0,"ssid":"<ssid>","ip":"<ip>","mac":"<mac>","rssi":-65,"error":0}
{"StoA_ventilation":0,"command":0,...}
{"StoA_ime_learn":"0","open":1,"close":1}
{"StoA_s":3}
```

Note: `StoA_ventilation` command:0 is sent twice (device behaviour).

### Confirmed 2026-04-08 — standalone read commands (maveo connect / Wi-Fi stick, status `"CONNECTED"`)

```json
// {"AtoS_s": 0} → only door status, no dump
{"StoA_s": 4}

// {"AtoS_ventilation": 0, "command": 0} → ventilation disabled (mode:0)
{"StoA_ventilation":0,"command":0,"error":0,"mode":0,"active":0,"ime_pos_valid":0,"blocked":0,"manual_vent":0,"test_mode":0,"debug":0}

// {"AtoS_ventilation": 0, "command": 1} → config (all defaults/zeros = not configured)
{"StoA_ventilation":0,"command":1,"error":0,"mode":0,"test_mode":0,"temp_low":0,"temp_high":0,"threshold":0,"vent_duration":15,"block_time":120,"dew_point_diff":0,"weather_update_interval":18,"end_time":"00:00","start_time":"00:00","weekdays":0,"time_based_time":"00:00-00:00","time_based_weekdays":0}

// {"AtoS_sensor": 0, "command": 0} → error:2 = no HT sensor paired
{"StoA_sensor":0,"command":0,"error":2}

// {"AtoS_sensor": 0, "command": 5} → update interval (succeeds even without sensor)
{"StoA_sensor":0,"command":5,"error":0,"update_interval":5}

// {"AtoS_req_ime_learn": 0} → open:0, close:0 = positions not learned
{"StoA_ime_learn":"0","open":0,"close":0}

// {"AtoS_weather": 0} or {"AtoS_weather": 0, "lat": 0, "lng": 0} → cached/local value
{"StoA_weather":0,"humidity":6600,"temperature":2900,"last_update":1775649457}

// {"AtoS_weather": 0, "lat": <lat>, "lng": <lng>} → outdoor weather for that GPS location
{"StoA_weather":0,"humidity":4200,"temperature":2000,"last_update":1775649569}

// {"AtoS_vent_state": 0} → no response (not a valid request key)
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
