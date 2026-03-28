# Nymea Remote Proxy — Device-Side Protocol

## Overview

Device configuration (firmware version, hardware revision, WiFi SSID, door/light
state, GPS location) is **not** stored in the Maveo AWS cloud.  It lives on the
Maveo stick itself, which runs a [nymea](https://nymea.io) IoT framework instance.

Remote access is provided by the open-source
[nymea-remoteproxy](https://github.com/nymea/nymea-remoteproxy) service running
at `wss://api.yourgateway.io`.  The stick and the mobile app both connect to this
WebSocket relay; the proxy tunnels a full JSON-RPC 2.0 session between them.

---

## Architecture

```
Mobile App
    │
    │  wss://api.yourgateway.io   (nymea-remoteproxy, open-source)
    │  TunnelProxy.RegisterClient(serverUuid=<stick-uuid>)
    │
    ▼
nymea-remoteproxy  ←→  Maveo Stick (nymea, JSON-RPC 2.0 server)
                         ├── Integrations.GetThings  → firmware, SSID, states
                         ├── Integrations.ExecuteAction → open/close/light
                         └── Tags.GetTags           → location metadata
```

A "server" in nymea-remoteproxy terminology is the **stick** (it registers first).
A "client" is the **mobile app** (it connects second and requests a tunnel to the
server's UUID).  Once the proxy establishes the tunnel, all subsequent JSON-RPC
messages are forwarded transparently.

---

## MaveoPro API — UUID lookup

Before connecting to the proxy, the app resolves the device's Nymea `serverUuid`
via a secondary Azure-hosted API.

### Base URL

```
https://maveoproadmin-test.azurewebsites.net
```

### Required headers

```
x-api-key:    QJykAohmC8TA7KG46yFsaz2i
x-client-id:  maveoapp
Authorization: Bearer <cognito_id_token>
```

Both `x-api-key` and `x-client-id` are hardcoded in the `.so` binary static
initializer `_GLOBAL__sub_I_maveoproconnection_cpp` (Ghidra decompile line 135546):

```c
QByteArray::QByteArray((QByteArray *)&apiKey, "QJykAohmC8TA7KG46yFsaz2i", -1);
QByteArray::QByteArray((QByteArray *)&appId,  "maveoapp", -1);
```

**Important:** `x-client-id` must be `"maveoapp"` (the app identifier), **not** the
Cognito pool client ID (`34eruqhvvnniig5bccrre6s0ck`).  Sending the Cognito client
ID here causes HTTP 702.

### GET /api/free-customers/{email}

Returns the customer profile and registered devices.

```
GET /api/free-customers/<email_address>
```

Note: the customer ID is the **email address**, not the AWS `identity_id`.

**Response (HTTP 200):**
```json
{
  "code": "200",
  "message": "success",
  "payload": {
    "fullName": "...",
    "email": "user@example.com",
    "phone": "...",
    "address": {"formatted": "..."},
    "devices": [
      {
        "freeCustomerId": "user@example.com",
        "type": "BlueFi",
        "serialNumber": "<device_serial>"
      }
    ],
    "created": "...",
    "updated": "..."
  }
}
```

**Note:** The device objects contain `serialNumber` and `type` but **no Nymea UUID**.
The `serverUuid` needed for `TunnelProxy.RegisterClient` is not exposed by this endpoint.
It must be obtained via mDNS service discovery (`_ws._tcp`) on the local network.

**Known error responses:**
- `HTTP 200 / code 702` — wrong `x-client-id` or `x-api-key`
- `HTTP 200 / code 855` — customer not found (wrong email format or not registered)

---

## Nymea Remote Proxy — WebSocket connection

### Endpoint

```
wss://api.yourgateway.io
```

Port 443, path `/` (the nymea-remoteproxy default).  Plain HTTP requests return
`HTTP 404` because the proxy only speaks WebSocket upgrade.

### Step 1 — RegisterClient

After the WebSocket handshake, send:

```json
{
  "id": 1,
  "method": "TunnelProxy.RegisterClient",
  "params": {
    "clientUuid": "<random-uuid>",
    "clientName": "nymea-app",
    "serverUuid": "<stick-uuid-from-maveoproapi>"
  }
}
```

**Response on success:**
```json
{
  "id": 1,
  "status": "success",
  "params": {"tunnelEstablished": true}
}
```

**Response when server not available:**
```json
{
  "id": 1,
  "status": "error",
  "error": "ServerNotFound"
}
```

Once `tunnelEstablished: true` is received, the connection is a transparent
pipe to the Nymea JSON-RPC server on the stick.  All subsequent messages follow
the Nymea JSON-RPC 2.0 protocol.

---

## Nymea JSON-RPC session

### Step 2 — Hello

```json
{"id": 2, "method": "JSONRPC.Hello"}
```

Response contains server version, protocol version, and available API namespaces.

### Step 3 — Authenticate

```json
{
  "id": 3,
  "method": "JSONRPC.Authenticate",
  "params": {
    "token": "<bluefi-access-key-token>",
    "clientDescription": "nymea-app"
  }
}
```

The BlueFi access key token is a separate credential obtained during BLE setup
or via the Maveo cloud API (command string not yet found — see investigations.md §3).

### Step 4 — GetThings

Returns the full device state including firmware, hardware revision, WiFi SSID,
door position, and light state.

```json
{"id": 4, "method": "Integrations.GetThings"}
```

**Response structure (partial):**
```json
{
  "params": {
    "things": [
      {
        "id": "<thing-uuid>",
        "thingClassId": "ca6baab8-3708-4478-8ca2-7d4d6d542937",
        "name": "My Garage",
        "params": [
          {"paramTypeId": "...", "value": "1.2.3"},
          {"paramTypeId": "...", "value": "WiFi-SSID"}
        ],
        "states": [
          {"stateTypeId": "...", "value": "open"},
          {"stateTypeId": "...", "value": false}
        ]
      }
    ]
  }
}
```

### Step 5 — GetTags (location metadata)

Location is stored as Nymea tags, not in thing parameters.

```json
{"id": 5, "method": "Tags.GetTags"}
```

Tag keys for location data (extracted from binary string scan):

| Tag key | Content |
|---|---|
| `garage-location-name` | Display name of the location |
| `garage-location-latitude` | Latitude (float string) |
| `garage-location-longitude` | Longitude (float string) |

### ExecuteAction (door / light control)

```json
{
  "id": 6,
  "method": "Integrations.ExecuteAction",
  "params": {
    "thingId": "<thing-uuid>",
    "actionTypeId": "<action-type-uuid>",
    "params": []
  }
}
```

---

## ThingClass UUIDs

Hardcoded in `libmaveo-app_armeabi-v7a.so` as QML properties:

| Property | UUID |
|---|---|
| `maveoStickThingClassId` | `ca6baab8-3708-4478-8ca2-7d4d6d542937` |
| `mfzStickThingClassId`   | `68d5ed34-c78e-4fe7-8472-b49bbb8ca663` |

---

## Firebase projects

Two Firebase projects are referenced in the app:

### 1. App SDK project (`p2168-maveo-app`)

Used by the Firebase SDK (FCM, Analytics, Installations).

| Parameter | Value |
|---|---|
| Project number | `448702651802` |
| Firebase API key | `AIzaSyCMf8dvTS800zmF5YRQ9UaSkQCShx6LsT4` |
| Project ID | `p2168-maveo-app` |
| Storage bucket | `p2168-maveo-app.appspot.com` |
| App ID (Android) | `1:448702651802:android:ab65c496ebe5a3785eee23` |
| OAuth client | `448702651802-b6i6bnoe8q73gv739e19tlfn22vegjm5.apps.googleusercontent.com` |

Firebase Installations API is accessible with these credentials:

```python
POST https://firebaseinstallations.googleapis.com/v1/projects/p2168-maveo-app/installations
x-goog-api-key: AIzaSyCMf8dvTS800zmF5YRQ9UaSkQCShx6LsT4
Content-Type: application/json

{
  "appId": "1:448702651802:android:ab65c496ebe5a3785eee23",
  "authVersion": "FIS_v2",
  "sdkVersion": "a:17.2.0"
}

# → HTTP 200: {"fid": "<id>", "refreshToken": "...", "authToken": {"token": "<jwt>", "expiresIn": "604800s"}}
```

**Remote Config status:** `NO_TEMPLATE` — this Firebase project has no Remote Config
template configured.  The MaveoPro `x-api-key` does **not** come from this project.

### 2. Native library project

Used by the native C++ layer (found via binary string scan of `libmaveo-app_armeabi-v7a.so`).

| Parameter | Value |
|---|---|
| Project number | `746496830881` |
| Firebase API key | `AIzaSyAamudrefuCRkrKckUTL_TK6Y7T51cmH1s` |

Remote Config API is **disabled** for this project (HTTP 403 when attempting to fetch).
This key is used for something else in the native code (likely FCM notification handling
or Analytics), not for fetching the MaveoPro `x-api-key`.

### MaveoPro auth — **RESOLVED** (2026-03-28)

Both credentials are hardcoded in the binary:

| Header | Value | Source |
|---|---|---|
| `x-api-key` | `QJykAohmC8TA7KG46yFsaz2i` | Binary static initializer `_GLOBAL__sub_I_maveoproconnection_cpp`, Ghidra line 135546 |
| `x-client-id` | `maveoapp` | Same initializer (`appId` variable, line 135548) |

`GET /api/free-customers/<email>` returns HTTP 200 with customer profile and device list.

See investigations.md §11 for the (now outdated) dead-end search history.

---

## Known ThingClass parameter/state type UUIDs

Extracted from binary data segment (partial, not yet mapped to semantic names):

| UUID | Context |
|---|---|
| `997936b5-d2cd-4c57-b41b-c6048320cd2b` | near `guhRpcURL`, `hostAddress` — likely a connection param type |
| `e081fec*` range | ThingClass action/state type IDs (prefix seen repeatedly) |
| `ef6d66*` range | ThingClass action/state type IDs (prefix seen repeatedly) |

Full mapping requires a live `Integrations.GetThingClasses` call or inspection
of the nymea plugin binary on the device.

---

## `api.yourgateway.io` — connection investigation

`api.yourgateway.io` resolves via DNS to `maveopro.azurefd.net` (Azure Front Door).
Both the proxy service and the MaveoPro REST API are hosted behind the same AFD instance.

### HTTP / WebSocket probing results

| Host | Path | Method | Result |
|---|---|---|---|
| `api.yourgateway.io` | `/` (and 10 other paths) | GET | HTTP 404 (Azure FD custom error page, 266KB) |
| `api.yourgateway.io` | `/` | WebSocket upgrade | HTTP 404 |
| `api.yourgateway.io` | `/` | WS + `Upgrade: websocket` + subprotocol `remoteproxy` | HTTP 404 |
| `maveopro.azurefd.net` | `/` (and all paths) | WebSocket upgrade | HTTP 503 |

**Key observation:** `maveopro.azurefd.net` returns **503** (backend service reachable but
unhealthy/not running) while `api.yourgateway.io` returns **404** (Azure FD routing rule
explicitly returns 404 for unmatched routes).  This suggests the nymea-remoteproxy
backend exists in the AFD configuration but is currently not serving requests.

### Possible causes
1. The nymea-remoteproxy service is not running (scaled to zero or decommissioned)
2. The service requires the device's Nymea `serverUuid` to be present somewhere in the
   request before accepting WebSocket upgrades (non-standard routing)
3. The real proxy URL is different and supplied at runtime via Firebase Remote Config
   (the binary hardcodes `api.yourgateway.io` but Remote Config could override it)

### Next step
Intercept a live app session to observe the actual WebSocket upgrade request headers
and path used by the nymea-app when connecting to the remote proxy.

---

## Local mDNS discovery

The app also discovers the stick on the local network using Zeroconf (mDNS).
Service type: `_ws._tcp.local.`

Discovered TXT record keys (from binary string scan): `friendlyName`, `secure`.
The server UUID used for `TunnelProxy.RegisterClient` is likely in the TXT record as well.

Python example:
```python
from zeroconf import Zeroconf, ServiceBrowser

class Handler:
    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        print(f"Found: {name} @ {info.parsed_addresses()}:{info.port}")
        print(f"  TXT: {info.properties}")

zc = Zeroconf()
b = ServiceBrowser(zc, "_ws._tcp.local.", Handler())
# Keep open to receive discoveries
```

---

## Current status

| Step | Status |
|---|---|
| MaveoPro API — `x-api-key` / `x-client-id` | **Resolved** — `QJykAohmC8TA7KG46yFsaz2i` / `maveoapp` |
| MaveoPro API — GET customer profile | **Working** — returns profile + device list |
| MaveoPro API — get Nymea `serverUuid` | **Blocked** — not in `/api/free-customers/<email>` response |
| `api.yourgateway.io` WebSocket (remote) | **Unknown** — HTTP 404 on root; path for WS unknown |
| Local mDNS (`_ws._tcp`) discovery | **Documented**, not yet tested from this machine |
| Firebase Installations token | **Working** — can obtain FIS auth token |
| Firebase Remote Config | **No template** — `p2168-maveo-app` has no RC config |
| `TunnelProxy.RegisterClient` | Documented (from open-source spec), not yet tested |
| `JSONRPC.Authenticate` — BlueFi token | **Blocked** — token source unknown |
| `Integrations.GetThings` | Expected to return all device state once connected |
| `Tags.GetTags` — location | Expected to return GPS coords once connected |
