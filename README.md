# Maveo — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2026.10%2B-blue)](https://www.home-assistant.io/)
[![IoT Class](https://img.shields.io/badge/IoT%20class-Cloud%20Polling-yellow)](https://developers.home-assistant.io/docs/creating_integration_manifest#iot-class)
[![License: MIT](https://img.shields.io/github/license/markwallsgrove/ha-maveo)](https://opensource.org/license/mit)
[![hassfest](https://github.com/markwallsgrove/ha-maveo/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/markwallsgrove/ha-maveo/actions/workflows/hassfest.yaml)
[![HACS validation](https://github.com/markwallsgrove/ha-maveo/actions/workflows/hacs.yaml/badge.svg)](https://github.com/markwallsgrove/ha-maveo/actions/workflows/hacs.yaml)
[![Ruff](https://github.com/markwallsgrove/ha-maveo/actions/workflows/lint.yaml/badge.svg)](https://github.com/markwallsgrove/ha-maveo/actions/workflows/lint.yaml)

Control your **Marantec Maveo** garage door stick from Home Assistant.

Vendored fork of [yoda-jm/ha-maveo](https://github.com/yoda-jm/ha-maveo) with unused code removed,
tighter secret handling and a test suite.

> **Cloud integration** — requires an active internet connection and a Maveo account.
> All commands and state updates go through the Marantec cloud (AWS IoT + Cognito).
> The integration cannot operate offline or if the Marantec cloud is unreachable.

---

## Supported devices

- Marantec **Maveo Connect** stick
- Marantec **Maveo BlueFi** stick, including the optional indoor temperature/humidity (H+T) sensor

Any stick on your Maveo account is added. Sticks added to or removed from the account
later are picked up within 10 minutes, without a restart.

## Supported functions

| Entity | Description |
|--------|-------------|
| **Cover** — Garage door | Open, close; live position (open / closed / opening / closing) |
| **Light** — Garage light | Turn on/off, live state |
| **Binary sensor** — Cloud connectivity | Whether the stick answers (diagnostic) |
| **Sensor** — Firmware | Stick firmware version (diagnostic) |
| **Sensor** — Time to close | Auto-close timer in minutes |
| **Sensor** — WiFi signal | RSSI in dBm, with SSID/IP/MAC attributes (diagnostic, disabled by default) |
| **Sensor** — Buzzer | Buzzer state (diagnostic) |
| **Sensor** — Stick type | `bluefi` or `connect` (diagnostic, disabled by default) |
| **Sensor** — Outdoor temperature / humidity | Weather at the stick's GPS location |
| **Sensor** — Indoor sensor, temperature, humidity, battery | Paired H+T sensor |
| **Device tracker** — Location | Stick GPS coordinates on the map |
| **Sensor** — Guest ×N | One per guest key: remaining time, rights, claimed status, app name |

Guest sensors are created and removed automatically as guest keys are added or revoked.
The device page offers **Download diagnostics** with credentials, serials, network
details and location redacted.

## Use cases

- See whether the garage is open from anywhere, and close it from the dashboard.
- Close the garage automatically at night or when everybody leaves.
- Give a visitor or tradesperson a time-limited key from a script.

---

## Installation via HACS

1. In HACS (or the HA Marketplace) → three-dot menu → **Custom repositories**
2. Add `https://github.com/markwallsgrove/ha-maveo` — category **Integration**
3. Install **Maveo** and restart Home Assistant
4. **Settings → Devices & services → Add integration** → search **Maveo**

### Configuration parameters

| Parameter | Description |
|-----------|-------------|
| Email | The email address of your Maveo account |
| Password | Your Maveo password |
| Region | `EU` (Europe) or `US` (North America): where your account was created |

Change the password or region later with **Reconfigure** on the integration entry.
There are no other options.

Credentials renew with the Cognito refresh token. When Cognito rejects the refresh
token, the integration signs in again with the stored password. Home Assistant only asks
for the password (reauth) when Maveo rejects it, e.g. after a password change.

Home Assistant has no encrypted secret store: the password and refresh token are kept in
plain text in `.storage/core.config_entries`, like other cloud integrations.

### Removal

1. **Settings → Devices & services → Maveo** → three-dot menu → **Delete**.
2. Optionally uninstall **Maveo** in HACS and restart Home Assistant.

Deleting the entry does not change anything on your Maveo account. Guest keys stay
valid until they expire or you revoke them in the Maveo app.

---

## Actions

Both actions are admin only and take the garage **device** (device picker in the UI).

### `maveo.create_guest`

Creates a time-limited guest key and returns it in the action response: `user_id`,
`link` (the Maveo share link) and `expires_at`. The link grants access to the garage,
so share it only with the guest.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `device_id` | ✓ | — | The Maveo garage device |
| `ttl_hours` | — | 24 | Validity in hours (1–720) |
| `admin` | — | false | Full remote access without geofence restriction |

### `maveo.remove_guest`

Revokes a guest key immediately.

| Field | Required | Description |
|-------|----------|-------------|
| `device_id` | ✓ | The Maveo garage device |
| `user_id` | ✓ | Guest UUID (`user_id` attribute of the guest sensor) |

## Examples

Close the garage at 22:00 if it is open:

```yaml
automation:
  - alias: Close garage at night
    triggers:
      - trigger: time
        at: "22:00:00"
    conditions:
      - condition: state
        entity_id: cover.garage_garage_door
        state: open
    actions:
      - action: cover.close_cover
        target:
          entity_id: cover.garage_garage_door
```

Create a 4-hour guest key and send the link to your phone:

```yaml
script:
  garage_guest_key:
    sequence:
      - action: maveo.create_guest
        data:
          device_id: YOUR_DEVICE_ID  # pick the device in the UI editor
          ttl_hours: 4
        response_variable: guest
      - action: notify.mobile_app_my_phone
        data:
          message: "Garage key: {{ guest.link }} (valid until {{ guest.expires_at }})"
```

---

## Data updates

| Data | Interval |
|------|----------|
| Device state (door, light, WiFi…) | 30 s — MQTT burst-poll |
| Guest key list | 60 s — REST |
| Sticks on the account | 10 min — REST |
| After any user command | Refresh after 2 s |

## Known limitations

- Cloud only: nothing works when the Marantec cloud or your internet is down.
- State is polled, so a door moved with the remote shows up within about 30 s.
- Each poll takes over the stick's MQTT session for a moment; the stick reconnects by
  itself within a few seconds.
- Accounts with multi-factor sign-in are not supported.
- Outdoor weather needs GPS coordinates set on the stick.
- The H+T sensor units are inferred from the app and not yet confirmed on a live sensor.

## Troubleshooting

- **Asked to sign in again**: Maveo rejected the stored password. Enter the current one.
- **Entities unavailable**: the cloud or the stick did not answer. This is logged once
  and again when it recovers. Check the stick's WiFi and the Maveo app.
- **Cloud connectivity is off**: the stick is reachable through the cloud but does not
  answer; power-cycle the stick.
- For more detail, enable debug logging and attach the diagnostics download to an issue:

```yaml
logger:
  logs:
    custom_components.maveo: debug
```

## Upgrading from 0.x

1.0 has breaking changes:

- `sensor.*_stick_type` reports `bluefi` / `connect`, and the indoor sensor reports
  `paired` / `not_paired` (both are translated in the UI).
- `maveo.create_guest` and `maveo.remove_guest` take a Home Assistant device instead of the
  numeric Maveo device ID.
- The WiFi signal and stick type sensors are disabled by default for new installs.

---

## Protocol

- **Authentication**: AWS Cognito USER_PASSWORD_AUTH (setup) / REFRESH_TOKEN_AUTH → Identity Pool → temp AWS credentials
- **Device control**: MQTT 3.1.1 over WebSocket (SigV4 header auth) to AWS IoT Core
- **Management**: Marantec REST API (`/admin` endpoint)

Full protocol documentation is in [`docs/`](docs/), including reverse-engineering notes.

---

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check custom_components tests
.venv/bin/mypy
.venv/bin/pytest -q
```

Tests run Home Assistant against fakes at the network boundary: a moto server for
Cognito, and a local aiohttp server for the REST API and the stick's MQTT-over-WebSocket
endpoint. Protocol code also has property-based tests (Hypothesis).

`custom_components/maveo/api` is the async cloud client. It has no Home Assistant
imports and uses the `aiohttp` session passed to it.

---

## Disclaimer

This integration is reverse-engineered from the Maveo Android app and is not affiliated
with or endorsed by Marantec. Use at your own risk.
