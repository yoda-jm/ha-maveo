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
| [investigations.md](investigations.md) | Non-working paths with exact error outcomes |

## Quick status

### Working
- Full owner authentication (Cognito → Identity Pool → AWS creds)
- REST: list devices, device status + session UUID
- REST: guest user create (with rights level) / list / edit / remove
- REST: guest token refresh + Cognito IdToken exchange
- IoT WebSocket: SigV4 header auth, MQTT CONNECT → CONNACK 0
- Guest rights levels: restricted (geofence, client-side only) vs admin (remote)

### Blocked
- IoT SUBSCRIBE / PUBLISH → WebSocket 1005 (Cognito role policy too restrictive)
- BlueFi access key creation → correct command string not yet found
- Device X.509 cert MQTT auth → not yet attempted (promising next step)
