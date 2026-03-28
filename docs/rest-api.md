# REST API

**Status: working**

All API calls are JSON POST requests against two endpoints:

| Endpoint | Purpose |
|---|---|
| `/admin` | Owner-level device management |
| `/user` | Guest-level token operations |

Both endpoints live under the same regional base URL, e.g.
`https://eu-central-1.api-prod.marantec-cloud.de`.

---

## Common request headers

```
Content-Type: application/json
Authorization: Bearer <cognito_id_token>
x-client-id: <cognito_client_id>
User-Agent: MaveoApp/2.6.0
```

The `Authorization` header carries the Cognito **IdToken** (JWT), not the
AccessToken.

---

## /admin endpoint — owner commands

All requests are `POST /admin` with a JSON body containing at minimum
`{"command": "..."}`.

### list_device

```json
// request
{"owner": "<identity_id>", "command": "list_device"}

// response — array of device objects
[
  {"id": "<device_id>", "name": "My Garage", "devicetype": 1}
]
```

### status

Returns current cloud connectivity state and the MQTT session UUID needed for
IoT commands.

```json
// request
{"deviceid": "<device_id>", "command": "status"}

// response
{
  "device":  "CONNECTED",    // or "DISCONNECTED"
  "mobile":  "DISCONNECTED",
  "session": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

The `session` UUID is the MQTT topic prefix: commands go to `<session>/cmd`,
responses arrive on `<session>/rsp`.  It changes each time the device
reconnects to the cloud.

### set_device_name

```json
// request
{"deviceid": "<device_id>", "command": "set_device_name", "name": "New Name"}

// response: 200 OK (body varies, no fields required)
```

### list_user

Returns all guest users associated with a device.

```json
// request
{"deviceid": "<device_id>", "command": "list_user"}

// response — array
[
  {
    "userid":   "6e582a6a-7874-31d0-98a1-c5be1ed38398",
    "token":    "<64 hex chars>",
    "rights":   "...",
    "ttl":      "3600",        // seconds remaining, or "token expired"
    "nametag1": "",
    "nametag2": "",
    "nametag3": ""
  }
]
```

### add_user

Creates a new guest user.  Returns **HTTP 201** (not 200) on success.

`rights`: `0` = restricted (geofence-enforced in app, min 250 m radius), `1` = admin (no restriction).

```json
// request
{"deviceid": "<device_id>", "command": "add_user", "ttl": 3600, "rights": 0}

// response (HTTP 201)
{
  "userid":   "<uuid>",
  "token":    "<64 hex chars>",
  "rights":   "0",
  "ttl":      "<unix timestamp string>",
  "nametag1": "",
  "nametag2": "",
  "nametag3": ""
}
```

The `token` is a 64-character hex string used in all subsequent `/user`
guest operations.

**Claimed vs unclaimed**: nametag fields are empty when the key is first created.
They are populated by the **guest's app** the first time the guest imports and
activates the key.  The owner can detect installation by checking `nametag1 != ""`.
The app refuses to show the shareable link once the key is claimed.

Typical nametag content (set by the guest app):
- `nametag1`: device/app name chosen by the guest
- `nametag2`: OS ("Android" / "iOS")
- `nametag3`: locale ("fr", "en", etc.)

### edit

Edit mutable fields of an existing guest user.  Returns `"Edit success"`.

```json
// request — only include fields to change
{
  "deviceid": "<device_id>",
  "command":  "edit",
  "userid":   "<guest_uuid>",
  "rights":   1,
  "nametag1": "Alice's Phone",
  "nametag2": "Android",
  "nametag3": "en"
}

// response: 200 "Edit success"
```

### remove_user

```json
// request
{"deviceid": "<device_id>", "command": "remove_user", "userid": "<uuid>"}

// response: 200 OK
```

---

## Note on serial number and X.509 certificate

The device serial number and X.509 certificate/private key are **not** available
via the cloud REST API.  The binary contains internal commands
`AwsServiceCommandRetrieveDeviceSerial` and `AwsServiceCommandRetrieveDeviceCertificate`
which are sent over **Bluetooth Low Energy** during initial device setup via the
`BtWiFiSetupBlueFi` GATT service — not over HTTP.

Commands `get_device_serial`, `get_device_certificate`, `get_device_private_key`
all return HTTP 400 "Failed to execute command".

---

## /user endpoint — guest commands

These calls are made with the **same owner JWT** in the `Authorization` header,
but operate on behalf of a guest user.  They use the guest `userid` and `token`
obtained from `add_user`.

See [guest-flow.md](guest-flow.md) for the full guest authentication sequence.

### refresh_token

Refreshes a guest token.  The old token is consumed; use the returned one.

```json
// request
{
  "command":  "refresh_token",
  "userid":   "<guest_uuid>",
  "token":    "<64 hex>",
  "deviceid": "<device_id>"
}

// response
{
  "token":         "<new 64 hex>",
  "cognitouserid": "<uuid>"
}
```

### get_advuser_access

Exchanges a guest token for a Cognito `IdToken` JWT.

```json
// request
{
  "command":  "get_advuser_access",
  "userid":   "<guest_uuid>",
  "token":    "<64 hex>",
  "deviceid": "<device_id>"
}

// response
{"IdToken": "eyJ..."}
```

The returned JWT has the same issuer/audience as the owner token.  It can be
passed to `cognito-identity.get_id` + `get_credentials_for_identity` to obtain
temporary AWS credentials under the guest identity.

### get_guest_access_info

Returns TTL info for a guest token.  Does **not** consume the token.

```json
// request
{
  "command":  "get_guest_access_info",
  "userid":   "<guest_uuid>",
  "token":    "<64 hex>",
  "deviceid": "<device_id>"
}

// response
{"ttl": 3543, "tokenRefreshed": false}
```
