# Investigations — What Was Tried and Why It Failed

This document records all non-working paths explored during reverse-engineering
of the Maveo protocol, with exact outcomes.  The goal is to avoid repeating
dead ends and to guide future investigation.

---

## 1. IoT SUBSCRIBE / PUBLISH — Cognito credentials insufficient

### Hypothesis
Owner Cognito credentials (AWS `AccessKeyId` / `SecretKey` / `SessionToken`
from `GetCredentialsForIdentity`) should be sufficient to Subscribe and Publish
on the device's MQTT topics.

### What was tried
```python
async with MaveoIoTClient(auth, config, session_uuid, device_id) as iot:
    await iot.subscribe()   # → WebSocket closes 1005
```

Also tried:
- Explicit topic variants: `<session>/rsp`, `<session>/#`, `#`
- Guest Cognito credentials (obtained via `get_advuser_access` flow)
- Different `client_id` values (device_id, random UUID, identity_id)

### Exact outcome
Every SUBSCRIBE attempt causes the WebSocket to close with code **1005**
(RFC 6455: "No Status Received").  The closure happens within milliseconds of
sending the SUBSCRIBE packet — the broker rejects it before sending a SUBACK.

### Root cause (hypothesis)
The Cognito Identity Pool's **authenticated role** IAM policy only grants
`iot:Connect`.  The `iot:Subscribe` and `iot:Publish` actions are not in the
policy.  This is a common pattern in AWS IoT deployments where the broker
enforces topic-level authorization via a separate IoT Policy attached to
principals — the Cognito role alone is insufficient.

The device itself connects with its X.509 certificate (see
`get_device_certificate`), which would have a full IoT policy.  Human clients
may need a different credential path.

### What might unlock it
- Device X.509 certificate + private key used as MQTT client cert (TLS mutual
  auth, not WebSocket SigV4) — see section 4 below
- A BlueFi access key with a dedicated IoT policy (see section 3)
- A different Cognito pool or role that includes Subscribe/Publish

---

## 2. Guest IoT credentials — same identity, same failure

### Hypothesis
Guest users authenticated through the `refresh_token` → `get_advuser_access` →
Cognito Identity Pool chain might have a different IAM role with broader IoT
permissions.

### What was tried
Full 3-step guest auth flow:
1. `POST /user {"command": "refresh_token", ...}` → new token + `cognitouserid`
2. `POST /user {"command": "get_advuser_access", ...}` → `IdToken` JWT
3. `cognito-identity.get_id(Logins={provider: guest_id_token})` → `identity_id`
4. `get_credentials_for_identity(identity_id, Logins=...)` → AWS creds
5. `MaveoIoTClient` with guest creds → CONNACK 0 → SUBSCRIBE → 1005

### Exact outcome
The `identity_id` returned in step 3 is **identical** to the owner's
`identity_id` (`eu-central-1:90fdae04-5dd7-c740-f1d3-46a0d9153738`).
The resulting AWS credentials have the same permissions as the owner path.
SUBSCRIBE fails identically with 1005.

### Conclusion
Guest tokens are resolved to the owner's Cognito identity server-side.
Guest → IoT access does not go through a distinct Cognito role.

---

## 3. BlueFi access key commands — command strings unknown

### Hypothesis
The decompiled native library references a `BlueFiAccessKey` class and
`BlueFiAccessKeyStorage`.  The dispatch table contains `case 0x24:
addBlueFiAccessKey(...)`.  BlueFi access keys likely have their own IoT policy
that allows Subscribe/Publish.

### What was tried
Every plausible command string on `POST /admin`:

| Command tried | HTTP response |
|---|---|
| `add_bluefi_access_key` | 400 "Failed to execute command" |
| `addBlueFiAccessKey` | 400 "Failed to execute command" |
| `get_bluefi_access_key` | 400 "Failed to execute command" |
| `list_bluefi_access_keys` | 400 "Failed to execute command" |
| `get_mqtt_credentials` | 400 "Failed to execute command" |
| `get_iot_credentials` | 400 "Failed to execute command" |
| `getMqttPolicies` | 400 "Failed to execute command" |
| `get_mqtt_policy` | 400 "Failed to execute command" |

### Exact outcome
All returned `HTTP 400` with body `{"message": "Failed to execute command"}`.
This is the standard error for an unrecognized command — the server recognized
the route but not the `command` field value.

### State of investigation
The correct command string was not found.  Binary string scanning around the
`addBlueFiAccessKey` symbol found the class name and storage class but not
the API command string itself (which is constructed at runtime via Qt string
concatenation or PC-relative loads in Thumb2 code).

### Next steps
- Disassemble `addBlueFiAccessKey` (dispatch case 0x24) and trace the
  exact string passed to the network layer
- Look for strings between the admin URL and nearby function symbols in
  the `.rodata` / data segment around offset `0x220000–0x240000`

---

## 4. Device X.509 certificate — direct MQTT/TLS (not yet attempted)

### Hypothesis
`get_device_certificate` + `get_device_private_key` return a full X.509
client certificate and RSA private key for the device.  AWS IoT Core supports
mutual TLS authentication using client certificates on port 8883 (MQTT) or
port 443 (WebSocket with ALPN `mqtt`).  The device certificate's IoT policy
likely includes `iot:Subscribe` and `iot:Publish`.

### What was tried
Not yet attempted.  Certificate and key were retrieved successfully via the
REST API but not yet used for a TLS connection.

### Risk
Using the device's own certificate to control the device may confuse the
device's cloud connection (it may show as "device online" from two endpoints
simultaneously).  Test with device disconnected from cloud first.

### How to attempt
```python
import ssl
import websockets

ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_ctx.load_cert_chain(certfile="device.crt", keyfile="device.key")
ssl_ctx.load_verify_locations(cafile="AmazonRootCA1.pem")

ws = await websockets.connect(
    f"wss://{config.iot_hostname}/mqtt",
    subprotocols=["mqtt"],
    ssl=ssl_ctx,
)
```

---

## 5. get_device_serial / get_device_certificate — not REST API commands

### What was tried
```json
POST /admin {"deviceid": "...", "command": "get_device_serial"}
POST /admin {"deviceid": "...", "command": "get_device_certificate"}
POST /admin {"deviceid": "...", "command": "get_device_private_key"}
```

### Exact outcome
All three return `HTTP 400` — "Failed to execute command"

### Root cause
The binary strings `AwsServiceCommandRetrieveDeviceSerial`,
`AwsServiceCommandRetrieveDeviceCertificate`, and
`AwsServiceCommandRetrieveDevicePrivateKey` are enum values in the
`BtWiFiSetupBlueFi` class.  They are sent over **Bluetooth Low Energy**
GATT characteristics to the device during initial Wi-Fi setup — not via
the cloud REST API.  The REST API simply has no equivalent commands for these.

### Conclusion
Device serial and X.509 credentials can only be obtained via direct BLE
connection to the device.  The cloud API does not expose them.

---

## 7. `get_advuser_access` on /admin — wrong endpoint

### What was tried
```json
POST /admin
{"deviceid": "...", "command": "get_advuser_access", "userid": "...", "token": "..."}
```

### Exact outcome
`HTTP 400` — "Failed to execute command"

### Conclusion
This command belongs to the `/user` endpoint, not `/admin`.  Moving it to
`POST /user` with the same body returns HTTP 200 with `{"IdToken": "eyJ..."}`.

---

## 8. SigV4 query-parameter signing — wrong auth method

### What was tried
Initial WebSocket connection attempts used AWS SigV4 query-parameter signing
(presigned URL approach), which is documented as one of the two AWS IoT
WebSocket auth methods.

### Exact outcome
`HTTP 403 Forbidden` during WebSocket upgrade.

### Fix
Switched to SigV4 **header-based** signing.  The service name `iotdata`
(not `iotdevicegateway` or `execute-api`) was determined empirically.
CONNACK 0 received after this change.

---

## 9. ARM Thumb2 PC-relative string resolution — partial success

During binary analysis of `libmaveo-app_armeabi-v7a.so`, the function
`userAccessGuestControl` was truncated in all decompiler outputs.  Capstone
disassembly was used to read the full machine code.

`LDR Rn, [PC, #offset]` + `ADD Rn, PC` patterns in Thumb2 code load
pointer-to-pointer values from a literal pool, which then point into `.rodata`.
Computing the final string address requires:
1. `lit_pool_addr = (instruction_PC & ~3) + 4 + offset`  (PC aligned to 4 bytes, +4 pipeline)
2. `string_ptr = u32_at(lit_pool_addr)` (load the pointer stored there)
3. The string is at `string_ptr` in the mapped image

Attempts to resolve these using raw file offsets (without knowing the ELF load
address) yielded addresses that pointed into the middle of existing strings.
The ELF `PT_LOAD` segments would need to be parsed to map virtual addresses
back to file offsets correctly.

The approach was abandoned in favor of a simpler text scan: grep all
null-terminated strings in the data section directly by byte offset and search
for candidate command strings by pattern.

---

## 11. MaveoPro API — `x-api-key` from Firebase Remote Config

### Hypothesis
`https://maveoproadmin-test.azurewebsites.net/api/free-customers/<identity_id>`
returns the Nymea `serverUuid` needed to open a nymea-remoteproxy tunnel to the
device.  The endpoint requires an `x-api-key` header in addition to the Cognito
`Authorization: Bearer` token.

### What was tried
All combinations of:
- `x-api-key` omitted → `HTTP 702` "Access denied"
- `x-api-key: use-YOUR-1mag1nat1on` (placeholder string found in binary) → `HTTP 702`
- Various other guesses → `HTTP 702`

### Exact outcome
`HTTP 702 {"message": "Access denied"}` for every request without a valid key.
`HTTP 401` when `Authorization` header is omitted entirely.

### Root cause
The `x-api-key` is fetched at app startup from **Firebase Remote Config** (project
`746496830881`, Firebase API key `AIzaSyAamudrefuCRkrKckUTL_TK6Y7T51cmH1s`).
Client-side Remote Config access requires a Firebase **instance ID token** (a JWT
generated by the Firebase SDK running on an enrolled device).  This token is not
derivable from the Firebase API key alone, and the Remote Config REST API requires
OAuth2 credentials for admin/server access.

### What might unlock it
- Intercept a live app session and capture the `x-api-key` from the outgoing request
  headers (network proxy / mitmproxy on a rooted device or emulator)
- Obtain a valid Firebase instance ID token from the app (e.g., via Frida hook on
  `FirebaseInstanceId.getToken()`)
- Decompile the Firebase SDK initialization in the app to find if the key is
  passed as a build config constant (BuildConfig field inspection)

---

## 12. `api.yourgateway.io` WebSocket — HTTP 404

### Hypothesis
The nymea-remoteproxy service at `wss://api.yourgateway.io` should accept a
WebSocket upgrade on the root path `/`.

### What was tried
- `GET https://api.yourgateway.io/` → `HTTP 404`
- Various paths: `/ws`, `/proxy`, `/remoteproxy`, `/nymea`, `/tunnel` → all `HTTP 404`
- Ports `2212` and `2213` (default nymea-remoteproxy ports) → connection refused
- Only ports `80` and `443` are open (Azure FrontDoor)

WebSocket upgrade was not attempted yet (blocked by HTTP 404 suggesting the service
may not be reachable on this URL, or the path is different).

### Possible causes
1. The actual proxy URL is different from `api.yourgateway.io` and is supplied
   at runtime from Firebase Remote Config (same source as `x-api-key`)
2. Azure FrontDoor routing requires a specific Host header or SNI to reach the
   backend WebSocket service
3. The service requires a valid `serverUuid` in some pre-negotiation step before
   accepting the WebSocket upgrade (non-standard nymea-remoteproxy behavior)

### Current state
Cannot test `TunnelProxy.RegisterClient` until either the correct URL is known
(from Firebase Remote Config) or the HTTP 404 is resolved.

---

## 10. `userAccessGuestControl` decompiler truncation

All three decompiler outputs (Ghidra / RetDec / jadx native) truncate the
function body of `userAccessGuestControl` at the first `QDebug::operator<<`
call (`"Guest control:"`).  The function is 700+ bytes long per the Capstone
disassembly but the decompilers fail to analyze the control flow past that
point.

Likely cause: complex exception-handling or function-pointer dispatch via
Qt's signal/slot mechanism confuses the decompiler's CFG reconstruction.

The actual command strings sent by this function were found by a different
route: scanning all strings near the `/user` URL in the data segment and
then testing them empirically.
