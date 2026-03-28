# UUID Catalog

All UUIDs extracted from `libmaveo-app_armeabi-v7a.so` (app 2.6.0) with
inferred purpose from surrounding string context.

---

## Known / confirmed

| UUID | Name | Source |
|---|---|---|
| `ca6baab8-3708-4478-8ca2-7d4d6d542937` | `maveoStickThingClassId` | QML `MaveoConstants.qml` literal |
| `68d5ed34-c78e-4fe7-8472-b49bbb8ca663` | `mfzStickThingClassId` | QML `MaveoConstants.qml` literal |
| `b3ebe605-53c9-463e-8738-70ae01b042ee` | EU Cognito Identity Pool ID | `config.py` + binary (`eu-central-1:` prefix) |
| `a982cd04-863c-4fd4-8397-47deb11c8ec0` | US Cognito Identity Pool ID | `config.py` + binary (`us-west-2:` prefix) |

---

## Connection / network param types (Nymea)

These are Nymea `paramTypeId` / `stateTypeId` values for the maveo/mfz stick
thing classes.  They appear in groups near MQTT, cloud connection, and Cognito
log strings.

The `f757` family likely maps to the **Maveo stick** thing class; the `1111`
family may map to the **MFZ stick** or a second plugin variant.

| UUID | Inferred purpose | Context strings |
|---|---|---|
| `e081fec0-f757-4449-b9c9-bfa83133f7fc` | Door state / light barrier | "Received door status", "Light barrier state received", `X-AMZ-Security-Token` |
| `e081fec1-f757-4449-b9c9-bfa83133f7fc` | Cloud connection state | "AWS login response", "Received cognito identity id" |
| `e081fec2-f757-4449-b9c9-bfa83133f7fc` | BT address / ventilation config | "bt_addr", "requestVentilationConfig", "GUEST tokens are expired" |
| `e081fec3-f757-4449-b9c9-bfa83133f7fc` | MQTT / stick connection | "MQTT client not initialized", "No stick id set. not connecting" |
| `e081fec4-f757-4449-b9c9-bfa83133f7fc` | Weather humidity or guest token | "GUEST: Advanced user token error", `weather_humidity` |
| `e081fec5-f757-4449-b9c9-bfa83133f7fc` | Power / energy production | "totalProduction", "thingPowerLogEntries", "ports" |
| `e081fed0-f757-4449-b9c9-bfa83133f7fc` | Hardware revision / weather interval | "hardware_rev", "MQTT connection state changed", `weather_update_interval` |
| `e081fed1-f757-4449-b9c9-bfa83133f7fc` | Weather humidity (f757 variant) | `weather_humidity`, `X-Amz-SignedHeaders` |
| `e081fed2-f757-4449-b9c9-bfa83133f7fc` | Nametag2 / host param | "nameTag2", "host", "GUEST: Error parsing json reply for GetId" |
| `e081fed0-1111-1449-b9c9-bfa83133f7fc` | Weekly schedule / region | "weekdays", "region" |
| `e081fed1-1111-1449-b9c9-bfa83133f7fc` | IoT data / guest credentials | "iotdata", "Guest access info status reply", "GUEST: Registered for push" |
| `e081fed2-1111-1449-b9c9-bfa83133f7fc` | Sensor / AtoS | `AtoS_sensor`, "SensorCmdGetSettings: Response error" |
| `e081fed3-1111-1449-b9c9-bfa83133f7fc` | Cloud environment | **"cloudEnv"**, "Authorization" |
| `e081fed4-1111-1449-b9c9-bfa83133f7fc` | Stick ID / BlueFi controller | "stickId", "Creating bluefi controller", "cognito id" |

---

## Guest / auth token type IDs (Nymea)

| UUID | Inferred purpose | Context strings |
|---|---|---|
| `ef6d6610-b8af-49e0-9eca-ab343513641c` | AWS credentials / token refresh | "AWS Credentials for Identity received", "tokenRefreshed", `AtoS_l_r` |
| `ef6d6611-b8af-49e0-9eca-ab343513641c` | Stick name / GPS request | "Received stick name", `AtoS_gps_req`, "Old and new stick id are identical" |
| `ef6d6612-b8af-49e0-9eca-ab343513641c` | Sensor / door state (ef6d family) | `AtoS_sensor`, "Light barrier state received", "Received door status" |
| `ef6d6613-b8af-49e0-9eca-ab343513641c` | BlueFi status | "BlueFi status request error", "Guest BlueFi status request error" |
| `ef6d6614-b8af-49e0-9eca-ab343513641c` | Sensor config | `AtoS_sensor`, "SensorCmdGetSettings" |
| `ef6d6615-b8af-49e0-9eca-ab343513641c` | MQTT / stick (ef6d variant) | "MQTT client not initialized", "No stick id set. not connecting" |

---

## Interface / ThingClass type IDs (Nymea)

| UUID | Inferred purpose | Context strings |
|---|---|---|
| `997936b5-d2cd-4c57-b41b-c6048320cd2b` | Closable / light interface IDs | "colorTemperature", "Color lights", "daylight", "doorbellPressed", "skipNext" |

---

## Other / uncertain

| UUID | Inferred purpose | Context strings |
|---|---|---|
| `91b51fae-6590-4452-9154-b5daf4ca745e` | Second US Cognito Identity Pool (?) | Preceded by `us-west-2:` in binary |
| `8df252e3-f2bf-4a3a-a9d7-ca225758da74` | Unclear — near flatbuffers error strings | "us-west-2", flatbuffers internal error messages |
| `0d837fcf-b569-4135-a3e3-e6b143977cdf` | IoT data / ventilation mode (?) | In curly braces: `{0d837fcf-...}`, near "iotdata", "disableVentilationTestMode", "Guest access info status reply" |

---

## Notes

- UUIDs with the `e081fec*` / `ef6d66*` prefix pattern are Nymea **param/state/action type IDs**
  for the maveo/mfz thing classes.  They are used in `Integrations.GetThings` responses and
  `Integrations.ExecuteAction` requests.
- The `1111` vs `f757` distinction in the `e081fed*` family likely separates the Maveo Connect
  Stick thing class from the MFZ Stick thing class.
- `e081fed3-1111-1449-b9c9-bfa83133f7fc` is particularly interesting: it is adjacent to
  "cloudEnv" and "Authorization" strings, suggesting it is the param type ID for the cloud
  environment setting on the stick (EU vs US).
- `{0d837fcf-b569-4135-a3e3-e6b143977cdf}` uses curly-brace notation — typical of Qt/Windows
  GUID formatting — and appears near IoT data strings.  It was tested as a Firebase App Check
  debug token but rejected (HTTP 403 "App attestation failed").
