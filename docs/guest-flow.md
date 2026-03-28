# Guest User Flow

## Overview

A guest user is a time-limited credential set tied to a specific device.
The owner creates it; the guest uses a token (64-char hex) to authenticate.

### Rights levels

| `rights` | Level | Enforcement |
|---|---|---|
| `0` | Restricted | App-side geofence (min 250 m radius, OS geofence API). **Not server-enforced.** |
| `1` | Admin | No location restriction, full remote access |

The geofence is implemented entirely in the app (QML `PlatformHelper.addGeofence`).
Any client that bypasses the app can send commands regardless of the rights value.

### Claimed vs unclaimed keys

- **Unclaimed**: created by owner, `nametag1/2/3` are all empty
- **Claimed**: guest has imported the key into their app; `nametag1` is set
- The app detects a claimed key and **does not show the shareable link again**
- The owner can check claim status by testing `nametag1 != ""`

Nametag values are written by the guest app on first activation:
- `nametag1`: app/device name (user-visible label)
- `nametag2`: OS ("Android" / "iOS")
- `nametag3`: locale ("fr", "en", …)

The owner can also set nametags manually via the `edit` command.

### The guest flow has two layers:
1. **REST guest operations** — working fully
2. **IoT access via guest credentials** — partially working (CONNECT ok, SUBSCRIBE fails)

---

## Lifecycle — owner side

### Create a guest user

```
POST /admin
{"deviceid": "<device_id>", "command": "add_user", "ttl": <seconds>}

→ HTTP 201
{"userid": "<uuid>", "token": "<64 hex>", "rights": "...", "ttl": "<seconds>"}
```

Distribute the `userid` + `token` to the guest out-of-band (QR code, link, etc.).

### List / remove guest users

```
POST /admin {"deviceid": "...", "command": "list_user"}
POST /admin {"deviceid": "...", "command": "remove_user", "userid": "..."}
```

---

## Guest authentication to IoT (3-step flow)

Discovered by reverse-engineering `libmaveo-app_armeabi-v7a.so` (app 2.6.0),
specifically the `userAccessGuestControl` function and its call chain.
The three sub-functions map to dispatch table cases 0x2b, 0x2d, then Cognito SDK.

All three `/user` calls below require the **owner's** JWT in `Authorization`.

### Step 1 — refresh_token (case 0x2b: `userAccessRefreshToken`)

Refreshes and activates the guest token.  The old token is consumed; the new
one must be used for all subsequent calls.

```json
POST /user
{"command": "refresh_token", "userid": "<guest_uuid>", "token": "<old 64 hex>", "deviceid": "<device_id>"}

→ {"token": "<new 64 hex>", "cognitouserid": "<cognito_sub_uuid>"}
```

### Step 2 — get_advuser_access (case 0x2d: `userAccessGetAdvUserAccess`)

Exchanges the refreshed guest token for a Cognito IdToken JWT.

```json
POST /user
{"command": "get_advuser_access", "userid": "<guest_uuid>", "token": "<new 64 hex>", "deviceid": "<device_id>"}

→ {"IdToken": "eyJ..."}
```

The JWT has the same issuer and audience as the owner's token:
```
iss: https://cognito-idp.eu-central-1.amazonaws.com/eu-central-1_ozbW8rTAj
aud: 34eruqhvvnniig5bccrre6s0ck
```

### Step 3 — Cognito Identity Pool → AWS credentials

```python
logins = {
    "cognito-idp.eu-central-1.amazonaws.com/eu-central-1_ozbW8rTAj": guest_id_token
}
identity_id = cognito_identity.get_id(IdentityPoolId=..., Logins=logins)["IdentityId"]
creds = cognito_identity.get_credentials_for_identity(IdentityId=identity_id, Logins=logins)
```

Outcome: returns the **same** `identity_id` as the owner
(`eu-central-1:90fdae04-5dd7-c740-f1d3-46a0d9153738`), suggesting guest tokens
are resolved back to the owner's Cognito identity on the server side.

---

## IoT result with guest credentials

- MQTT CONNECT with `device_id` as client_id → **CONNACK 0** (success)
- MQTT SUBSCRIBE to `<session>/rsp` → **WebSocket close 1005** (same as owner)

The guest IoT auth path does not unlock additional IoT permissions beyond what
the owner Cognito role already has.

---

## Auxiliary guest call — get_guest_access_info

Non-destructive: checks TTL without consuming the token.

```json
POST /user
{"command": "get_guest_access_info", "userid": "...", "token": "...", "deviceid": "..."}

→ {"ttl": 3543, "tokenRefreshed": false}
```

`tokenRefreshed: true` is returned when the server automatically rotated the
token (appears to happen when TTL is low).
