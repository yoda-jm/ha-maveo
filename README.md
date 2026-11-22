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

## Features

| Entity | Description |
|--------|-------------|
| **Cover** — Garage door | Open, close, stop; live position (open / closed / opening / closing) |
| **Light** — Garage light | Turn on/off, live state |
| **Binary sensor** — Connectivity | Cloud connection status |
| **Sensor** — Firmware | Stick firmware version |
| **Sensor** — Time-to-close | Auto-close timer in minutes |
| **Sensor** — WiFi signal | RSSI in dBm + SSID attribute |
| **Sensor** — Buzzer | Buzzer state |
| **Device tracker** — Location | GPS coordinates shown on the HA map |
| **Sensor** — Guest key ×N | One per guest: TTL countdown, rights, claimed status, app name |

Guest entities are created and removed automatically as guest keys are added or revoked.

---

## Installation via HACS

1. In HACS (or the HA Marketplace) → three-dot menu → **Custom repositories**
2. Add `https://github.com/markwallsgrove/ha-maveo` — category **Integration**
3. Install **Maveo** and restart Home Assistant
4. **Settings → Integrations → Add** → search **Maveo**
5. Enter your Maveo email, password, and region (EU / US)

Credentials renew with the Cognito refresh token. When Cognito rejects the refresh
token, the integration signs in again with the stored password. Home Assistant only asks
for the password (reauth) when Maveo rejects it, e.g. after a password change.

Home Assistant has no encrypted secret store: the password and refresh token are kept in
plain text in `.storage/core.config_entries`, like other cloud integrations.

---

## Services

### `maveo.create_guest`

Admin only. Creates a time-limited guest key for a device and returns it in the action
response: `user_id`, `link` (the Maveo share link) and `expires_at`. Call it with
"return response" enabled, or store it with `response_variable` in a script.
The link grants access to the garage, so share it only with the guest.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `device_id` | ✓ | — | Numeric device ID (from sensor attributes) |
| `ttl_hours` | — | 24 | Validity in hours (1–720) |
| `admin` | — | false | Full remote access without geofence restriction |

### `maveo.remove_guest`

Admin only. Revokes a guest key immediately.

| Field | Required | Description |
|-------|----------|-------------|
| `device_id` | ✓ | Numeric device ID |
| `user_id` | ✓ | Guest UUID (shown in the guest sensor's attributes) |

---

## Update frequency

| Data | Interval |
|------|----------|
| Device state (door, light, WiFi…) | 30 s — MQTT burst-poll |
| Guest key list | 60 s — REST |
| After any user command | Immediate refresh (2 s delay) |

---

## Protocol

- **Authentication**: AWS Cognito USER_PASSWORD_AUTH (setup) / REFRESH_TOKEN_AUTH → Identity Pool → temp AWS credentials
- **Device control**: MQTT 3.1.1 over WebSocket (SigV4 header auth) to AWS IoT Core
- **Management**: Marantec REST API (`/admin`, `/user` endpoints)

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

Tests run Home Assistant against fakes at the network boundary: moto for Cognito, a
local HTTP server for the REST API, and a fake MQTT stick for AWS IoT. Protocol code
also has property-based tests (Hypothesis).

---

## Disclaimer

This integration is reverse-engineered from the Maveo Android app and is not affiliated
with or endorsed by Marantec. Use at your own risk.
