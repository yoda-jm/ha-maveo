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
2. **IoT access via guest credentials** — fully working (guest tokens resolve to owner identity, so IoT access is the same as owner)

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

Guest tokens resolve to the same `identity_id` as the owner on the server side, so
the resulting AWS credentials are identical.  IoT access works the same way as owner
access (see iot-mqtt.md): connect with `client_id = device_id`, subscribe to
`{device_id}/rsp`, publish to `{device_id}/cmd`.

---

---

## Guest deep link format

**Status: fully reverse-engineered and implemented.**

### URL structure

```
https://deeplink.marantec-cloud.de?data=<iv_b64><ct_b64>
```

- `<iv_b64>` — standard Base64 of a random 16-byte IV (always ends with `==`, so 24 chars)
- `<ct_b64>` — standard Base64 of the AES-256-CBC ciphertext (PKCS7 padding, no separator)

The two Base64 blocks are concatenated with no separator.  The split point is
the `==` terminator of the IV block.

### Encryption

| Parameter | Value |
|---|---|
| Algorithm | AES-256-CBC / PKCS7 padding |
| Key | Fixed, app-wide (32 bytes, see below) |
| IV | Random 16 bytes, prepended as Base64 |

The key is a **hardcoded constant** stored as the QML property `deepLinkKey`
(UTF-16LE string) in `libmaveo-app_armeabi-v7a.so` at data offset `0x23fc00`:

```
Base64: zbH/cSqJIcgIta9NEhfJ8GSuT79dTQNDB2AcPBfLxyo=
Hex:    cdb1ff712a8921c808b5af4d1217c9f064ae4fbf5d4d034307601c3c17cbc72a
```

This single key is shared by all Maveo installations worldwide.  No PBKDF2
or per-user derivation is performed.

### Plaintext payload

A URL-encoded query string with exactly 12 parameters (the app validates this):

```
userid=<guest_uuid>
&token=<64_hex_chars>
&rights=<0|1>
&ttl=<unix_timestamp_milliseconds>
&garagename=<device_name>
&garageid=<device_id>
&nametag1=<empty_on_creation>
&nametag2=<empty_on_creation>
&nametag3=<empty_on_creation>
&locationname=<location_display_name>
&latitude=<float>
&longitude=<float>
```

`ttl` is a Unix timestamp in **milliseconds** (unlike the REST API which uses seconds).
`nametag1/2/3` are empty when the key is first shared; they are set by the guest app on activation.

### Security note

Because the AES key is the same for every app installation, **any link can be
decrypted by anyone who has extracted the key from the binary**.  The link
contains the guest token in plaintext after decryption, so link confidentiality
depends entirely on keeping the URL itself secret — not on the encryption.

The geofence (`rights=0`) is enforced only by the app, not the server.

### Library usage

```python
from maveo import decode_guest_link
payload = decode_guest_link(url)

# Generate a link (requires a valid GuestUser object):
link = client.generate_guest_link(guest, device_id, "My Garage",
                                   location_name="Home",
                                   latitude=48.858, longitude=2.294)
```

### CLI usage

```
python cli.py decode-link <url>
python cli.py share-guest <device_id> <user_id>                     # all values auto-fetched from device
python cli.py share-guest <device_id> <user_id> --name "My Garage"  # override name, GPS still auto
python cli.py share-guest <device_id> <user_id> --name "My Garage" --location Home --latitude 48.858 --longitude 2.294
```

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
