# Home Assistant Integration Plan

## Repository structure

```
ha-maveo/
├── hacs.json                              ← HACS metadata
├── custom_components/
│   └── maveo/
│       ├── manifest.json                  ← HA integration manifest
│       ├── const.py                       ← constants, platform list
│       ├── __init__.py                    ← setup / unload entry
│       ├── config_flow.py                 ← UI setup: email / password / region
│       ├── coordinator.py                 ← device state via MQTT burst-poll (30 s)
│       ├── guest_coordinator.py           ← guest list via REST poll (60 s)
│       ├── cover.py                       ← garage door (open / close / stop)
│       ├── light.py                       ← garage light (on / off)
│       ├── binary_sensor.py               ← cloud connectivity
│       ├── sensor.py                      ← firmware, TTC, RSSI, buzzer + guest entities
│       ├── device_tracker.py              ← GPS location (HA map)
│       ├── camera.py                      ← guest QR codes (one per guest)
│       ├── services.py                    ← create_guest / remove_guest
│       ├── services.yaml                  ← service schema
│       ├── strings.json                   ← UI strings
│       ├── translations/en.json           ← English labels
│       ├── auth.py                        ┐
│       ├── client.py                      │
│       ├── config.py                      │  bundled library (same files as maveo/)
│       ├── iot.py                         │
│       ├── maveopro.py                    │
│       └── firebase.py                    ┘
├── maveo/                                 ← kept for CLI (unchanged)
├── cli.py
└── docs/
```

The library files are duplicated into `custom_components/maveo/` so that HACS
installs are self-contained.  The root `maveo/` package remains for the CLI.

---

## Entities per physical device

| Platform        | Entity                  | State                              | Update source  |
|-----------------|-------------------------|------------------------------------|----------------|
| `cover`         | Garage door             | open / closed / opening / closing  | Device coord.  |
| `light`         | Garage light            | on / off                           | Device coord.  |
| `binary_sensor` | Cloud connectivity      | connected / disconnected           | Device coord.  |
| `sensor`        | Firmware version        | version string                     | Device coord.  |
| `sensor`        | Time-to-close           | minutes (0 = off)                  | Device coord.  |
| `sensor`        | WiFi RSSI               | dBm                                | Device coord.  |
| `sensor`        | Buzzer                  | on / off                           | Device coord.  |
| `device_tracker`| Garage location         | GPS on HA map                      | Device coord.  |

### Guest entities (one set per guest key, dynamic)

| Platform  | Entity               | State                          | Update source   |
|-----------|----------------------|--------------------------------|-----------------|
| `sensor`  | Guest `<name/id>`    | TTL remaining / expired        | Guest coord.    |
| `camera`  | Guest `<name/id>` QR | JPEG QR code of the share link | On demand       |

Guest entities are created automatically when a guest appears and become
unavailable when removed.  The sensor shows TTL countdown with attributes:
rights, claimed status, app name (nametag1), OS, locale.  The camera entity
renders the encrypted deep link as a scannable QR code — point the Maveo app
at it on mobile to import the key.

---

## Coordinators

### Device coordinator (`MaveoDeviceCoordinator`) — 30 s

1. REST `status` → check `CONNECTED / DISCONNECTED`
2. If online: open MQTT WebSocket, send all 9 read commands, collect responses, close
3. If offline: return cached state with `online = False`
4. Auto-refresh AWS temp credentials (via re-auth) when they expire within 10 min

The MQTT session is open for ~3 s × 9 commands, then closed so the stick
reclaims its own session.  After every command sent by the user, a 2 s wait
is inserted before the next coordinator refresh.

### Guest coordinator (`MaveoGuestCoordinator`) — 60 s

REST `list_user` per device.  Guest entities register a listener on this
coordinator via `async_add_listener`; new entities are added as new guests
appear.  Removed guests show as unavailable.

---

## Services

| Service              | Fields                                      | Effect                                           |
|----------------------|---------------------------------------------|--------------------------------------------------|
| `maveo.create_guest` | `device_id`, `ttl_hours`, `admin`           | Creates guest, refreshes coordinator, fires HA event + persistent notification with link |
| `maveo.remove_guest` | `device_id`, `user_id`                      | Removes guest, refreshes coordinator             |

---

## Config flow

```
Step 1 (user):
  email + password + region (EU / US)
  → authenticate() → if OK, create entry
  → unique ID = email (blocks duplicate accounts)
```

Credentials are stored in the HA config entry (encrypted at rest by HA).
Token refresh: AWS temp credentials are renewed transparently in the coordinator;
Cognito refresh token (~30 d) is used if available, falling back to
email+password re-auth.

---

## Implementation phases

| Phase | Scope                                               |
|-------|-----------------------------------------------------|
| 1     | Skeleton: `hacs.json`, manifest, const, `__init__`, config flow, library bundle |
| 2     | Device coordinator + cover, light, binary_sensor, sensor (device), device_tracker |
| 3     | Guest coordinator + guest sensor entities + camera (QR) |
| 4     | Services: create_guest, remove_guest                |
| 5     | Polish: strings, translations, service schema, README |
