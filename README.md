# Maveo — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2026.3%2B-blue)](https://www.home-assistant.io/)
[![IoT Class](https://img.shields.io/badge/IoT%20class-Cloud%20Polling-yellow)](https://developers.home-assistant.io/docs/creating_integration_manifest#iot-class)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

Control your **Marantec Maveo** garage door stick from Home Assistant.

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
| **Camera** — Guest QR ×N | Scannable QR code per guest — point the Maveo app at it on mobile |

Guest entities are created and removed automatically as guest keys are added or revoked.

---

## Installation via HACS

1. In HACS → **Integrations** → three-dot menu → **Custom repositories**
2. Add `https://github.com/yoda-jm/ha-maveo` — category **Integration**
3. Install **Maveo** and restart Home Assistant
4. **Settings → Integrations → Add** → search **Maveo**
5. Enter your Maveo email, password, and region (EU / US)

> After install, add the following topics to the GitHub repo so it appears in HACS searches:
> `hacs`, `home-assistant`, `home-assistant-integration`, `maveo`, `garage-door`, `marantec`

---

## Services

### `maveo.create_guest`

Creates a time-limited guest key for a device. A persistent notification appears with
the share link, and the guest QR camera entity updates automatically.

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `device_id` | ✓ | — | Numeric device ID (from sensor attributes) |
| `ttl_hours` | — | 24 | Validity in hours (1–720) |
| `admin` | — | false | Full remote access without geofence restriction |

### `maveo.remove_guest`

Revokes a guest key immediately.

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

- **Authentication**: AWS Cognito USER_PASSWORD_AUTH → Identity Pool → temp AWS credentials
- **Device control**: MQTT 3.1.1 over WebSocket (SigV4 header auth) to AWS IoT Core
- **Management**: Marantec REST API (`/admin`, `/user` endpoints)

Full protocol documentation is in [`docs/`](docs/), including reverse-engineering notes.

---

## Development / CLI

```bash
git clone https://github.com/yoda-jm/ha-maveo && cd ha-maveo
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python cli.py configure          # save credentials to OS keychain
python cli.py devices            # list devices
python cli.py info <device_id>   # query all IoT sensors
python cli.py share-guest <device_id> <user_id>  # generate guest QR link
```

---

## Disclaimer

This integration is reverse-engineered from the Maveo Android app and is not affiliated
with or endorsed by Marantec. Use at your own risk.
