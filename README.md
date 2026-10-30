# Maveo — Home Assistant Integration

Control your Marantec Maveo Connect garage door stick from Home Assistant.

> Cloud integration — requires an active internet connection and a Maveo
> account. All commands and state updates go through the Marantec cloud
> (AWS IoT + Cognito). The integration cannot operate offline or if the
> Marantec cloud is unreachable.

## About this fork

This fork is based on the original
[yoda-jm/ha-maveo](https://github.com/yoda-jm/ha-maveo) project.

It adds a Home Assistant action for the programmed lower ventilation position
and includes tested cover stop support.

### Lower ventilation position

The `maveo.ventilate` action moves the garage door to its programmed
lower ventilation position.

This position is called:

- English: Intermediate Closed
- German: Untere Lüftungsposition
- Reported `position_name` attribute: `IntermediateClosed`

The existing position attribute can be used to detect when the door reports
that position, for example for dashboard indicators and automations.

### Stop button

This fork adds `CoverEntityFeature.STOP` and an `async_stop_cover()` method
to the cover implementation used as its starting point.

The stop action uses the existing `Command.GARAGE_STOP` command and makes
the Stop control available to compatible Home Assistant cover controls,
including the tile card's `cover-open-close` feature.

### Tested functionality

The following has been tested successfully on my installation:

- Calling `maveo.ventilate` with `data: {}` automatically selects the single
  available device and moves the door to the lower ventilation position.
- In that position, the cover reports
  `position_name: IntermediateClosed`.
- The cover Stop button stops the moving garage door.

Multi-device operation and compatibility with other opener models or
firmware versions have not yet been verified.

The original project remains the upstream source. These additions do not
imply endorsement by the original author or Marantec.

## Features

| Entity / action | Description |
|---|---|
| Cover — Garage door | Open, close and stop; reported door position and movement state |
| Action — Ventilate | Move to the programmed lower ventilation position |
| Cover attribute — Position | `position_name`, including `IntermediateClosed` for the lower ventilation position |
| Light — Garage light | Turn on/off, live state |
| Binary sensor — Connectivity | Cloud connection status |
| Sensor — Firmware | Stick firmware version |
| Sensor — Time-to-close | Auto-close timer in minutes |
| Sensor — WiFi signal | RSSI in dBm and SSID attribute |
| Sensor — Buzzer | Buzzer state |
| Device tracker — Location | GPS coordinates shown on the Home Assistant map |
| Sensor — Guest key ×N | One per guest: TTL countdown, rights, claimed status and app name |
| Camera — Guest QR ×N | Scannable QR code per guest for the Maveo mobile app |

Guest entities are created and removed automatically as guest keys are added
or revoked.

## Installation via HACS

To install this fork:

1. In HACS, open the three-dot menu and select Custom repositories.
2. Add `https://github.com/nilbaer/ha-maveo`
   with the category Integration.
3. Install Maveo and restart Home Assistant.
4. Open Settings → Devices & services → Add integration and search for Maveo.
5. Enter your Maveo email, password and region (EU / US).

The original upstream repository is available at:

https://github.com/yoda-jm/ha-maveo

## Services / actions

### maveo.ventilate

Moves the garage door to the programmed lower ventilation position
(Intermediate Closed / Untere Lüftungsposition).

The target position must be programmed on the Marantec opener.

| Field | Required | Description |
|---|---|---|
| `device_id` | Only when multiple devices are available | Device ID used internally by the integration |

When exactly one device coordinator is available, it is selected automatically:

```yaml
action: maveo.ventilate
data: {}
```

When multiple devices are available, specify the device:

```yaml
action: maveo.ventilate
data:
  device_id: "YOUR_MAVEO_DEVICE_ID"
```

The device ID must match a device coordinator key used by the integration.
It is not the Home Assistant device-registry ID.

The action returns an explanatory error if:

- No device coordinator is available.
- Multiple devices are available and no `device_id` is supplied.
- The supplied `device_id` cannot be found.

The implementation uses the existing
`Command.GARAGE_VENTILATE` command and the coordinators stored in:

```python
hass.data[DOMAIN][entry_id]["coordinators"]
```

A completed service call does not, by itself, confirm that the door has
reached the target position. Use the reported position to check this.

### cover.stop_cover

Stops the moving garage door through the standard Home Assistant cover action:

```yaml
action: cover.stop_cover
target:
  entity_id: cover.garagentor_garage_door
```

Replace the example entity ID with your own garage-door cover.

The Stop control is also available in compatible dashboard cover controls.

### maveo.create_guest

Creates a time-limited guest key for a device. A persistent notification
appears with the share link, and the guest QR camera entity updates
automatically.

| Field | Required | Default | Description |
|---|---|---|---|
| `device_id` | Yes | — | Numeric Maveo device ID |
| `ttl_hours` | No | 24 | Validity in hours (1–720) |
| `admin` | No | false | Full remote access without geofence restriction |

### maveo.remove_guest

Revokes a guest key immediately.

| Field | Required | Description |
|---|---|---|
| `device_id` | Yes | Numeric Maveo device ID |
| `user_id` | Yes | Guest UUID shown in the guest sensor's attributes |

The existing guest services are preserved.

## Detect the lower ventilation position

The integration already exposes the reported position through the cover's
`position_name` attribute.

In the lower ventilation position, it reports:

```yaml
position_name: IntermediateClosed
```

The exact attribute value is `IntermediateClosed`, without a space.
“Intermediate Closed” is the human-readable name.

### Template check

```jinja
{{ state_attr('cover.garagentor_garage_door', 'position_name') == 'IntermediateClosed' }}
```

Replace the cover entity ID with your own.

### Optional template binary sensor

This sensor can be used for a dashboard indicator or as an automation condition:

```yaml
template:
  - binary_sensor:
      - name: "Garage lower ventilation position"
        unique_id: garage_lower_ventilation_position
        icon: mdi:weather-windy
        availability: >-
          {{ states('cover.garagentor_garage_door')
             not in ['unknown', 'unavailable'] }}
        state: >-
          {{ state_attr('cover.garagentor_garage_door', 'position_name')
             == 'IntermediateClosed' }}
```

If your configuration already contains a `template:` section, add the sensor
to that section instead of creating a second top-level `template:` key.

The sensor reflects the reported position rather than remembering the last
ventilation command. It becomes inactive when a different position is reported.

The position attribute is an existing integration feature; this fork makes
use of it rather than introducing a new position-reporting mechanism.

## Dashboard example

The standard tile card can display Open, Stop and Close controls:

```yaml
type: tile
entity: cover.garagentor_garage_door
vertical: false
features:
  - type: cover-open-close
features_position: bottom
```

The ventilation action can be called separately from a dashboard button,
script or automation.

## Update frequency

| Data | Interval |
|---|---|
| Device state: door, light, WiFi, etc. | 30 seconds — MQTT burst-poll |
| Guest key list | 60 seconds — REST |
| After a user command | Immediate refresh with a 2-second delay |

Position indicators follow the latest status received by the integration.
They are not an independent physical position sensor.

## Protocol

- Authentication: AWS Cognito `USER_PASSWORD_AUTH` → Identity Pool →
  temporary AWS credentials.
- Device control: MQTT 3.1.1 over WebSocket with SigV4 header authentication
  to AWS IoT Core.
- Management: Marantec REST API (`/admin` and `/user` endpoints).

Full protocol documentation, including reverse-engineering notes, is
available in `docs/`.

## Development / CLI

```bash
git clone [https://github.com/YOUR_GITHUB_USERNAME/ha-maveo](https://github.com/YOUR_GITHUB_USERNAME/ha-maveo)
cd ha-maveo

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python cli.py configure
python cli.py devices

python cli.py info <device_id>
python cli.py share-guest <device_id> <user_id>

python cli.py bugreport
python cli.py bugreport <device_id>

python cli.py bugreport --verbose
python cli.py bugreport --no-redact
```

`configure` saves credentials to the OS keychain.

`devices` lists the devices associated with the account.

### Reporting a bug

Run:

```bash
python cli.py bugreport
```

Include the output in your GitHub issue.

Sensitive fields such as serial number, MAC address, IP address, GPS
coordinates and session UUID are redacted by default.

Use `--no-redact` only if you understand the consequences of sharing those
values. Always review logs and diagnostic output before publishing them.
Never publish passwords or authentication tokens.

For problems with the additions in this fork, include:

- Home Assistant version.
- Maveo connect stick firmware version.
- Marantec opener model.
- Whether standard open, close and stop actions work.
- Whether the ventilation action moves the door.
- The reported `position_name` value.
- Relevant error messages with sensitive information removed.

## Credits

Original project, Python library, CLI and integration:
[yoda-jm/ha-maveo](https://github.com/yoda-jm/ha-maveo).

This fork adds the lower ventilation-position action, documents the existing
position feedback and includes tested cover stop support.

Please retain the original project's LICENSE file and applicable notices.

## Disclaimer

This integration is reverse-engineered from the Maveo Android app and is not
affiliated with or endorsed by Marantec. Use at your own risk.

Garage-door actions cause physical movement. Ensure the doorway is clear
and the opener's safety equipment is operational before testing or using
remote control.
