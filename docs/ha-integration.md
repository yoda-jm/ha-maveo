# Home Assistant Integration

## Repository structure

```
ha-maveo/
├── hacs.json                              ← HACS / Marketplace metadata
├── custom_components/maveo/
│   ├── manifest.json                      ← HA integration manifest
│   ├── const.py                           ← constants, platform list
│   ├── __init__.py                        ← setup / unload entry, registers services
│   ├── config_flow.py                     ← UI setup (email / password / region) + reauth
│   ├── data.py                            ← typed runtime data on the config entry
│   ├── session.py                         ← shared credentials, renewed with the refresh token
│   ├── coordinator.py                     ← device state via MQTT burst-poll (30 s)
│   ├── guest_coordinator.py               ← guest list via REST poll (60 s)
│   ├── entity.py                          ← shared device info
│   ├── cover.py / light.py / binary_sensor.py / sensor.py / device_tracker.py
│   ├── services.py / services.yaml        ← admin-only create_guest / remove_guest
│   ├── strings.json / translations/en.json
│   ├── auth.py                            ← Cognito sign-in and refresh
│   ├── client.py                          ← REST client + guest deep link
│   ├── config.py                          ← regional constants
│   └── iot.py                             ← MQTT over WebSocket (SigV4)
├── tests/                                 ← pytest + Hypothesis
└── docs/
```

---

## Entities per physical device

| Platform        | Entity                  | State                              | Update source  |
|-----------------|-------------------------|------------------------------------|----------------|
| `cover`         | Garage door             | open / closed / opening / closing  | Device coord.  |
| `light`         | Garage light            | on / off                           | Device coord.  |
| `binary_sensor` | Cloud connectivity      | connected / disconnected           | Device coord.  |
| `sensor`        | Firmware, TTC, RSSI, buzzer, stick type, weather, H+T | see `sensor.py` | Device coord. |
| `device_tracker`| Garage location         | GPS on HA map                      | Device coord.  |
| `sensor`        | Guest `<name/id>` (one per guest key) | TTL remaining / expired | Guest coord. |

Guest sensors are created when a guest appears and become unavailable when
removed.  Attributes: rights, claimed status, app name, OS, locale, expiry.
The guest token is never exposed as an attribute.

---

## Credentials

- The config flow signs in with email + password (Cognito `USER_PASSWORD_AUTH`)
  and stores email, password, region and the Cognito **refresh token**.  Home
  Assistant writes config entries as plain JSON; it has no encrypted secret store.
- `MaveoSession` renews the ID token and AWS credentials with
  `REFRESH_TOKEN_AUTH` 10 minutes before they expire.  If Cognito rotates the
  refresh token, the new one is written back to the config entry.
- When Cognito rejects the refresh token, `MaveoSession` signs in again with the
  stored password, so the user is not prompted when the refresh token expires.
- When Cognito rejects the password, setup or the coordinators raise
  `ConfigEntryAuthFailed` and Home Assistant starts the reauth flow.
- `AuthResult` and `GuestUser` hide tokens and keys from `repr()`.
- REST errors include the command and HTTP status only, never request or
  response bodies (the `add_user` response contains the guest token).

---

## Services

| Service              | Fields                            | Effect |
|----------------------|-----------------------------------|--------|
| `maveo.create_guest` | `device_id`, `ttl_hours`, `admin` | Admin only. Creates a guest key and returns `user_id`, `link`, `expires_at` in the action response |
| `maveo.remove_guest` | `device_id`, `user_id`            | Admin only. Revokes a guest key |

The share link grants access to the garage, so it is only returned to the
caller.

---

## Coordinators

### Device coordinator (`MaveoDeviceCoordinator`) — 30 s

Opens an MQTT WebSocket, sends all read commands, collects responses and
closes, so the stick reclaims its own session.  A real MQTT response marks the
device online.  After a user command, a refresh follows after 2 s.

### Guest coordinator (`MaveoGuestCoordinator`) — 60 s

REST `list_user` per device.  Guest sensors listen on this coordinator and are
added as new guests appear.
