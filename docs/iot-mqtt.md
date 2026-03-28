# IoT / MQTT over WebSocket

## Summary

| Step | Status | Notes |
|---|---|---|
| WebSocket upgrade (SigV4) | **working** | CONNACK 0 received |
| MQTT CONNECT | **working** | client_id = device_id required |
| MQTT SUBSCRIBE | **failing** | WebSocket closes 1005 immediately |
| MQTT PUBLISH | **untested** | blocked by subscribe failure |

---

## Transport

The device communicates via **MQTT 3.1.1 over WebSocket** (subprotocol `mqtt`)
against:

```
wss://<region>.iot-prod.marantec-cloud.de/mqtt
```

AWS IoT Core is the broker.

---

## Authentication — SigV4 headers

The WebSocket upgrade request is authenticated with AWS SigV4 **header-based**
signing (not query-parameter signing).  Service name: `iotdata`.

Headers added to the upgrade request:

```
Host:                 <region>.iot-prod.marantec-cloud.de
X-Amz-Date:           20250101T120000Z
X-Amz-Security-Token: <session_token>
Authorization:        AWS4-HMAC-SHA256 Credential=<access_key>/<date>/<region>/iotdata/aws4_request,
                      SignedHeaders=host;x-amz-date;x-amz-security-token,
                      Signature=<sig>
User-Agent:           MaveoApp/2.6.0
```

The canonical request is:
```
GET
/mqtt
<empty query string>
host:<hostname>\nx-amz-date:<amz_date>\nx-amz-security-token:<token>\n
host;x-amz-date;x-amz-security-token
<sha256 of empty body>
```

The signing key derivation follows the standard SigV4 chain:
`HMAC(HMAC(HMAC(HMAC("AWS4"+secret, date), region), "iotdata"), "aws4_request")`

---

## MQTT CONNECT packet

After the WebSocket is open, a standard MQTT 3.1.1 CONNECT packet is sent:

```
Fixed header:  0x10
Protocol:      "MQTT" (3.1.1, level 0x04)
Connect flags: 0x02 (clean session)
Keep-alive:    60 s
Client ID:     <device_id>
```

The client ID **must** be the device ID string.  AWS IoT policies enforce this
binding.  Using any other client ID results in a CONNACK with return code ≠ 0
or an immediate connection drop.

CONNACK response (4 bytes: `0x20 0x02 0x00 0x00`):
- Return code `0x00` = Connection Accepted ✓

---

## MQTT topics

| Topic | Direction | Purpose |
|---|---|---|
| `<session>/cmd` | client → broker → device | Send commands to the device |
| `<session>/rsp` | device → broker → client | Receive device responses |

`<session>` is the UUID from `GET /admin status` (`DeviceStatus.session`).
It changes each time the device reconnects; always fetch a fresh status before
connecting.

---

## Commands (from decompiled libmaveo-app)

Commands are JSON payloads published to `<session>/cmd`:

| Action | Payload |
|---|---|
| Light ON | `{"AtoS_l": true}` |
| Light OFF | `{"AtoS_l": false}` |
| Garage OPEN | `{"AtoS_g": 1}` |
| Garage CLOSE | `{"AtoS_g": 0}` |
| Garage STOP | `{"AtoS_g": 2}` |
| Request status | `{"AtoS_s": 0}` |

These constants were found by reverse-engineering the Java layer and the native
library of app version 2.6.0.

---

## Observed protocol sequence (from PCAP)

The real app follows this exact sequence after WebSocket upgrade:

1. Send MQTT CONNECT (client_id = device_id)
2. Wait for CONNACK
3. Send MQTT SUBSCRIBE to `<session>/rsp` (QoS 0, packet_id = 1)
4. Wait for SUBACK
5. Send MQTT PUBLISH to `<session>/cmd` with the command JSON

This sequence is reproduced in `maveo/iot.py` (`MaveoIoTClient`).

---

## PINGREQ / keepalive

Keep-alive interval is 60 s (set in CONNECT).  PINGREQ is two bytes:
`0xC0 0x00`.  PINGRESP is two bytes: `0xD0 0x00`.

---

## Current blocker — SUBSCRIBE fails

Despite a successful CONNACK, sending a SUBSCRIBE packet causes the WebSocket
to close immediately with code **1005** (no status code / no reason).

This happens with:
- Owner Cognito credentials
- Guest Cognito credentials obtained via the `get_advuser_access` flow

Both produce the same `identity_id` (`eu-central-1:90fdae04-…`), suggesting
the Cognito authenticated role's IoT policy only grants `iot:Connect` and
does **not** grant `iot:Subscribe` or `iot:Publish`.

See [investigations.md](investigations.md) for full details of what was tried.
