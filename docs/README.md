# Maveo Protocol Documentation

Reverse-engineered from the Maveo Android app (version 2.6.0),
native library `libmaveo-app_armeabi-v7a.so`, and live traffic analysis.

## Documents

| File | Contents |
|---|---|
| [flows.md](flows.md) | **Start here** — all working flows with credentials, tokens, and IDs |
| [authentication.md](authentication.md) | AWS Cognito USER_PASSWORD_AUTH + Identity Pool credential flow |
| [rest-api.md](rest-api.md) | All working REST API commands (`/admin` and `/user` endpoints) |
| [iot-mqtt.md](iot-mqtt.md) | MQTT-over-WebSocket protocol, SigV4 signing, MQTT packet format |
| [guest-flow.md](guest-flow.md) | Guest user lifecycle: create, authenticate, IoT access |
| [nymea-proxy.md](nymea-proxy.md) | Nymea remote proxy architecture (partially blocked — low priority) |
| [investigations.md](investigations.md) | Dead ends, resolved issues, open questions |
| [uuids.md](uuids.md) | UUID catalog extracted from binary |

## Status

### Working

| Feature | Notes |
|---|---|
| Authentication | Cognito USER_PASSWORD_AUTH → Identity Pool → AWS creds |
| REST: list devices | Returns `device_id` (numeric string) |
| REST: device online status | `status` command — `CONNECTED` / `DISCONNECTED` |
| REST: device rename | `set_device_name` |
| REST: guest CRUD | create / list / edit / remove guest users |
| REST: guest token exchange | `refresh_token` → `get_advuser_access` → AWS creds |
| REST: MaveoPro customer profile | `GET /api/free-customers/<email>` with hardcoded API key |
| IoT: WebSocket connect | SigV4 header auth, service `iotdata` |
| IoT: MQTT CONNECT | `client_id = device_id` (AWS IoT policy requirement) |
| IoT: subscribe + publish | topics `{device_id}/rsp` and `{device_id}/cmd` |
| IoT: all read commands | door, firmware, light, GPS, WiFi, serial, name, TTC, buzzer |
| IoT: action commands | light on/off (`int 1/0`), garage open/close/stop |
| Guest deep link | AES-256-CBC, global hardcoded key, fully documented |

### Blocked / not attempted

| Feature | Blocker |
|---|---|
| Nymea remote proxy | `serverUuid` not in any cloud API; `api.yourgateway.io` returns 404 |
| Nymea JSON-RPC auth | BlueFi access key token source unknown |
| Device X.509 cert MQTT auth | Cert only accessible via BLE during provisioning |
