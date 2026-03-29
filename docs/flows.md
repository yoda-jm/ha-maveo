# Protocol Flows — Credentials and Tokens

Complete map of every credential, token, and ID used in the Maveo protocol:
where it comes from, what it unlocks, and how long it lasts.

---

## Credential map

```
email + password  (user-provided)
    │
    ▼  POST cognito-idp / InitiateAuth (USER_PASSWORD_AUTH)
    │
    ├─► IdToken (JWT, 1 h)          ── REST API Authorization header
    │                                   Guest token exchange (/user endpoint)
    │
    ├─► RefreshToken (long-lived)   ── Re-auth without password (REFRESH_TOKEN_AUTH)
    │
    └─► AccessToken                 ── Cognito user operations only (not used in library)
            │
            ▼  cognito-identity / GetId + GetCredentialsForIdentity
            │  using IdToken as Logins proof
            │
            ├─► identity_id                  ── REST /admin "owner" field
            │   (eu-central-1:xxxxxxxx-…)
            │
            └─► AWS temp credentials (1 h)   ── IoT WebSocket SigV4 signing
                ├─ AccessKeyId
                ├─ SecretKey
                └─ SessionToken
                        │
                        ▼  GET wss://<region>.iot-prod.marantec-cloud.de/mqtt
                           SigV4 header auth (service=iotdata)
                           MQTT CONNECT  client_id = device_id  (AWS IoT policy)
                           MQTT SUBSCRIBE  {device_id}/rsp
                           MQTT PUBLISH    {device_id}/cmd
```

---

## Flow 1 — Authentication

**Input:** email, password
**Output:** `IdToken` (JWT), `identity_id`, AWS temp credentials

```
POST https://cognito-idp.<region>.amazonaws.com/
X-Amz-Target: AWSCognitoIdentityProviderService.InitiateAuth

{
  "ClientId":      "<cognito_client_id>",   // hardcoded per region (see below)
  "AuthFlow":      "USER_PASSWORD_AUTH",
  "AuthParameters": {"USERNAME": "<email>", "PASSWORD": "<password>"}
}

→ AuthenticationResult.IdToken        (JWT, 1 h)
→ AuthenticationResult.RefreshToken   (long-lived)
```

Then exchange the IdToken for AWS credentials:

```python
# Step A — resolve identity
identity_id = cognito_identity.get_id(
    IdentityPoolId = "<identity_pool_id>",    # hardcoded per region
    Logins = {"cognito-idp.<region>.amazonaws.com/<user_pool_id>": id_token}
)["IdentityId"]
# → "eu-central-1:90fdae04-…"

# Step B — get temporary AWS credentials
creds = cognito_identity.get_credentials_for_identity(
    IdentityId = identity_id,
    Logins = {same dict}
)["Credentials"]
# → AccessKeyId, SecretKey, SessionToken  (expire in ~1 h)
```

Implemented in `maveo/auth.py::authenticate()`.

---

## Flow 2 — List devices and get device_id

**Input:** IdToken, identity_id
**Output:** `device_id` (numeric string), device name

```
POST https://<region>.api-prod.marantec-cloud.de/admin
Authorization: Bearer <IdToken>
x-client-id:   <cognito_client_id>

{"owner": "<identity_id>", "command": "list_device"}

→ [{"id": "<device_id>", "name": "...", "devicetype": 1}]
```

The `device_id` (e.g. `60031747810096039`) is the central identifier used in
MQTT topics and all subsequent `/admin` commands.

Implemented in `maveo/client.py::MaveoClient.list_devices()`.

---

## Flow 3 — Device control via MQTT

**Input:** AWS temp credentials, device_id
**Output:** real-time device state, command execution

```
1. SigV4 WebSocket upgrade
   GET wss://<region>.iot-prod.marantec-cloud.de/mqtt
   Headers: Host, X-Amz-Date, X-Amz-Security-Token, Authorization (AWS4-HMAC-SHA256)
   Service name: iotdata  (not iotdevicegateway)
   Subprotocol: mqtt

2. MQTT CONNECT
   client_id = <device_id>        ← AWS IoT policy enforces this exact value
   clean_session = true
   keep_alive = 60 s
   → CONNACK return_code=0

   WARNING: connecting with device_id kicks the stick's own MQTT session.
   The stick reconnects automatically within seconds.

3. MQTT SUBSCRIBE
   topic = {device_id}/rsp        ← device → app responses
   QoS 0
   → SUBACK granted_qos=[0]

4. MQTT PUBLISH
   topic = {device_id}/cmd        ← app → device commands
   payload = JSON

5. Receive responses on {device_id}/rsp
```

**Key insight:** the `session` UUID from the `/admin status` REST call is **not**
used in MQTT topics.  It only shows whether the device is currently online.

Implemented in `maveo/iot.py::MaveoIoTClient`.

### Command format

Actions (no response):
```json
{"AtoS_l": 1}    // light on
{"AtoS_l": 0}    // light off
{"AtoS_g": 1}    // garage open
{"AtoS_g": 0}    // garage close
{"AtoS_g": 2}    // garage stop
```

Read commands (response on rsp topic):
```json
// send                        // response key
{"AtoS_s":          0}  →  StoA_s          // door position (int, see below)
{"AtoS_v":          0}  →  StoA_v          // firmware version string
{"AtoS_l_r":        0}  →  StoA_l_r        // light state (0/1)
{"AtoS_name_r":     0}  →  StoA_name_r     // device name
{"AtoS_get_serial": 0}  →  StoA_serial     // serial number string
{"AtoS_ttc_r":      0}  →  StoA_ttc_r      // time-to-close minutes (0=disabled)
{"AtoS_buzzer_r":   0}  →  StoA_buzzer_r   // buzzer state
{"AtoS_gps_req":    0}  →  StoA_gps + lat/lng
{"AtoS_wifi_ap":    0}  →  StoA_wifi_ap + ssid/ip/mac/rssi
```

Door position codes (`StoA_s`):

| Value | Meaning |
|---|---|
| 0 | Unknown |
| 1 | Opening |
| 2 | Closing |
| 3 | Open |
| 4 | Closed *(confirmed live)* |
| 5 | IntermediateOpen |
| 6 | IntermediateClosed |

CLI shortcut: `python cli.py info <device_id>` — fetches all read commands and
displays them formatted.

---

## Flow 4 — Check device online status

**Input:** IdToken, device_id
**Output:** `CONNECTED` / `DISCONNECTED`

```
POST /admin
{"deviceid": "<device_id>", "command": "status"}

→ {"device": "CONNECTED", "mobile": "DISCONNECTED", "session": "<uuid>"}
```

Use `device == "CONNECTED"` to confirm the stick is reachable before opening
an MQTT session.  The `session` UUID can be ignored.

---

## Flow 5 — Guest user management

**Input:** owner IdToken, device_id
**Output:** guest token (64-char hex), shareable deep link

```
# Create guest
POST /admin
{"deviceid": "<device_id>", "command": "add_user", "ttl": <seconds>, "rights": 0}
→ HTTP 201  {"userid": "<uuid>", "token": "<64 hex>", "rights": "0", "ttl": "..."}

# Share — generate encrypted deep link
python cli.py share-guest <device_id> <user_id> "Garage" --latitude X --longitude Y
→ https://deeplink.marantec-cloud.de?data=<encrypted>

# Revoke
POST /admin {"deviceid": "...", "command": "remove_user", "userid": "..."}
```

The deep link is AES-256-CBC encrypted with a **global hardcoded key** extracted
from the binary.  It contains the `userid` + `token` in plaintext after decryption.
Geofence (`rights=0`) is enforced by the app only — not by the server.

Guest tokens can be promoted to full IoT access via a 3-step exchange:
`refresh_token` → `get_advuser_access` → Cognito Identity Pool
(returns same `identity_id` as owner — guest and owner share the same IoT permissions).

See `guest-flow.md` for the full sequence.

---

## Flow 6 — MaveoPro customer profile

**Input:** IdToken
**Output:** customer profile, registered device serial numbers

```
GET https://maveoproadmin-test.azurewebsites.net/api/free-customers/<email>
Authorization: Bearer <IdToken>
x-api-key:    QJykAohmC8TA7KG46yFsaz2i     ← hardcoded in binary
x-client-id:  maveoapp                       ← hardcoded in binary (not the Cognito client ID)

→ {"payload": {"fullName": "...", "email": "...", "devices": [...]}}
```

Note: the response contains the device serial number and type but **not** a Nymea
`serverUuid`.  The Nymea remote proxy path remains blocked (see investigations.md).

---

## Regional constants

All constants extracted from `libmaveo-app_armeabi-v7a.so` (app 2.6.0).

| Parameter | EU | US |
|---|---|---|
| `aws_region` | `eu-central-1` | `us-west-2` |
| Cognito `client_id` | `34eruqhvvnniig5bccrre6s0ck` | `6uf5ra21th645p7c2o6ih65pit` |
| `user_pool_id` | `eu-central-1_ozbW8rTAj` | `us-west-2_6Ni2Wq0tP` |
| `identity_pool_id` | `eu-central-1:b3ebe605-…` | `us-west-2:a982cd04-…` |
| REST base URL | `https://eu-central-1.api-prod.marantec-cloud.de` | `https://us-west-2.api-prod.marantec-cloud.de` |
| IoT hostname | `eu-central-1.iot-prod.marantec-cloud.de` | `us-west-2.iot-prod.marantec-cloud.de` |

---

## Token lifetimes

| Token | Lifetime | Refresh |
|---|---|---|
| Cognito IdToken | 1 hour | Use RefreshToken with `REFRESH_TOKEN_AUTH` |
| Cognito RefreshToken | ~30 days | Re-authenticate with password |
| AWS temp credentials | ~1 hour | Re-run `GetCredentialsForIdentity` with fresh IdToken |
| Guest token (hex) | set by owner (`ttl` seconds) | `refresh_token` command consumes and rotates it |
