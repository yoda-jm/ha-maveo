# Maveo Protocol Documentation

Reverse-engineered from the Maveo Android app (version 2.6.0),
native library `libmaveo-app_armeabi-v7a.so`, and live traffic analysis.

## Documents

| File | Contents |
|---|---|
| [authentication.md](authentication.md) | AWS Cognito USER_PASSWORD_AUTH + Identity Pool credential flow |
| [rest-api.md](rest-api.md) | All working REST API commands (`/admin` and `/user` endpoints) |
| [iot-mqtt.md](iot-mqtt.md) | MQTT-over-WebSocket protocol, SigV4 signing, MQTT packet format |
| [guest-flow.md](guest-flow.md) | Guest user lifecycle: create, authenticate, IoT access |
| [nymea-proxy.md](nymea-proxy.md) | Nymea remote proxy architecture, MaveoPro API, device-side JSON-RPC |
| [investigations.md](investigations.md) | Non-working paths with exact error outcomes |

## Quick status

### Working
- Full owner authentication (Cognito → Identity Pool → AWS creds)
- REST: list devices, device status + session UUID
- REST: guest user create (with rights level) / list / edit / remove
- REST: guest token refresh + Cognito IdToken exchange
- IoT WebSocket: SigV4 header auth, MQTT CONNECT → CONNACK 0
- Guest rights levels: restricted (geofence, client-side only) vs admin (remote)
- Guest deep link: generate + decode (AES-256-CBC, fixed global key, fully documented)

### Documented (not yet tested / blocked)
- **Nymea remote proxy architecture**: device config lives on the stick, accessed via
  `wss://api.yourgateway.io` (open-source nymea-remoteproxy).  Full protocol documented
  in [nymea-proxy.md](nymea-proxy.md).
- **MaveoPro API** (`https://maveoproadmin-test.azurewebsites.net`): maps AWS device ID
  to Nymea `serverUuid` needed for proxy tunnel.  Currently blocked — `x-api-key` from
  Firebase Remote Config not yet obtained (investigations.md §11).
- **`api.yourgateway.io`**: returns HTTP 404 for all HTTP paths; WebSocket not yet
  reachable (investigations.md §12).

### Blocked
- IoT SUBSCRIBE / PUBLISH → WebSocket 1005 (Cognito role policy too restrictive)
- BlueFi access key creation → correct command string not yet found
- Device X.509 cert MQTT auth → not yet attempted (promising next step)
- MaveoPro `x-api-key` → requires Firebase Remote Config instance token
