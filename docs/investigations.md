# Investigations — Dead Ends and Open Questions

Non-working paths explored during reverse-engineering, with outcomes.
Resolved items are kept for historical reference.

---

## RESOLVED — IoT SUBSCRIBE / PUBLISH (wrong topic prefix)

### What failed
Every SUBSCRIBE attempt closed the WebSocket with code **1005** within milliseconds.

Tried: topic variants using the `session` UUID from the `status` REST call
(`<session>/rsp`, `<session>/#`, `#`), with both owner and guest credentials,
with multiple `client_id` values.

### Root cause
The `session` UUID from the `status` endpoint is **not** the topic prefix.
The correct topics are `{device_id}/cmd` and `{device_id}/rsp`, where `device_id`
is the numeric ID from `list_device`.  The AWS IoT policy also enforces
`client_id == device_id` — any other client_id is rejected before CONNACK.

### Fix
Use `MaveoIoTClient(auth, config, device_id)`.  Fully working since 2026-03-28.

---

## RESOLVED — MaveoPro API `x-api-key`

### What failed
`GET /api/free-customers/<email>` returned HTTP 702 "Access denied" without the
correct `x-api-key`.  All guesses failed.

### Root cause
Both credentials are hardcoded in the binary static initializer
`_GLOBAL__sub_I_maveoproconnection_cpp` (Ghidra line 135546):

| Header | Value |
|---|---|
| `x-api-key` | `QJykAohmC8TA7KG46yFsaz2i` |
| `x-client-id` | `maveoapp` |

Note: `x-client-id` must be `"maveoapp"`, not the Cognito pool client ID.

### Result
`GET /api/free-customers/<email>` returns customer profile and device list.
The Nymea `serverUuid` is **not** in the response — see open question below.

---

## RESOLVED — SigV4 signing method

### What failed
Initial WebSocket connections used SigV4 **query-parameter** signing → HTTP 403.

### Fix
Switch to SigV4 **header-based** signing, service name `iotdata`.
Implemented in `maveo/iot.py::_sigv4_headers()`.

---

## RESOLVED — Light command payload format

### What failed
`{"AtoS_l": true}` (JSON boolean) — device silently ignored it.

### Fix
Device expects integers: `{"AtoS_l": 1}` / `{"AtoS_l": 0}`.
Confirmed via live test: response `{"StoA_l_r": 1}`.

---

## OPEN — Nymea `serverUuid` (remote proxy blocked)

The nymea-remoteproxy at `wss://api.yourgateway.io` requires the stick's Nymea
`serverUuid` to establish a tunnel.  This UUID is **not** in the MaveoPro REST
response or any known cloud API endpoint.

Known facts:
- `api.yourgateway.io` resolves to `maveopro.azurefd.net` (Azure Front Door)
- HTTP GET on any path → 404; WebSocket upgrade → 404
- `maveopro.azurefd.net` directly → 503 (backend unhealthy or not running)
- The `serverUuid` is assigned to the stick during BLE provisioning

Possible sources of the UUID:
1. **mDNS**: the stick advertises `_ws._tcp.local.` — TXT records may contain it
2. **BLE**: `TunnelProxyServerConfiguration` is pushed to the stick over BLE during setup
3. **Live app intercept**: capture the actual `TunnelProxy.RegisterClient` call

The remote proxy path may be decommissioned (service returns 503/404 consistently).
The MQTT path (iot-mqtt.md) already provides full device control so the Nymea
path is low priority.

---

## OPEN — BlueFi access key cloud command

The binary references `BlueFiAccessKey` and `addBlueFiAccessKey` (dispatch case 0x24).
This would allow creating a Nymea auth token via the cloud API.  The exact command
string sent to `POST /admin` was not found — candidates like `add_bluefi_access_key`,
`addBlueFiAccessKey`, `get_bluefi_access_key` all return HTTP 400.

Low priority: MQTT path provides equivalent control without this.

---

## OPEN — Device X.509 certificate (MQTT mutual TLS)

`AwsServiceCommandRetrieveDeviceCertificate` / `RetrieveDevicePrivateKey` are BLE
GATT commands sent during Wi-Fi setup — **not** available via REST API.  The device
certificate would allow MQTT authentication via mutual TLS on port 8883 rather than
SigV4 WebSocket.

Not attempted.  The SigV4 WebSocket path (iot-mqtt.md) is fully working.

---

## CLOSED — `get_advuser_access` on /admin

Returns HTTP 400.  This command belongs to `/user`, not `/admin`.

---

## CLOSED — Serial / certificate via REST

`get_device_serial`, `get_device_certificate`, `get_device_private_key` all return
HTTP 400.  These operations are BLE-only (see above).
