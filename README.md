# ha-maveo

Python library for the [Marantec Maveo](https://www.marantec.com/) smart garage door system, intended as the foundation for a Home Assistant integration.

## Quick start

```bash
git clone <this-repo> ha-maveo && cd ha-maveo
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python cli.py configure            # save credentials to OS keychain once
python cli.py devices              # list your devices
```

## Structure

```
ha-maveo/
├── maveo/
│   ├── __init__.py      # public API
│   ├── config.py        # EU / US region constants
│   ├── auth.py          # Cognito login → AuthResult
│   └── client.py        # MaveoClient — device listing & status
├── cli.py               # command-line tool for development / testing
└── requirements.txt
```

## How it works

Authentication is a two-step AWS Cognito flow:

1. **`initiate_auth`** (USER_PASSWORD_AUTH) against the Maveo Cognito User Pool → `id_token`, `access_token`, `refresh_token`
2. **`get_id` + `get_credentials_for_identity`** against the Cognito Identity Pool → `identity_id` (used as the device owner key) + temporary AWS credentials (for future IoT/WebSocket use)

All HTTP API calls use the `id_token` as a `Bearer` token.

## Requirements

- Python 3.11+
- Dependencies: `boto3`, `requests`, `keyring`

## Credentials

The CLI resolves credentials in this order — the first source that provides both email and password wins:

| Priority | Source | How |
|----------|--------|-----|
| 1 | Environment variables | `MAVEO_EMAIL` + `MAVEO_PASSWORD` |
| 2 | OS keychain | after running `python cli.py configure` |
| 3 | Interactive prompt | fallback, asks at runtime |

The OS keychain backend is provided by [`keyring`](https://github.com/jaraco/keyring) and uses whatever the system offers: macOS Keychain, GNOME Keyring, KWallet, Windows Credential Store.

## CLI

```bash
# First-time setup — saves to OS keychain
python cli.py configure

# Test login — shows identity_id and token expiry
python cli.py login

# List all devices owned by the account
python cli.py devices

# Get the current status of a specific device
python cli.py status <device_id>

# Rename a device
python cli.py rename <device_id> "New Name"

# Use the US region instead of EU (default)
python cli.py --region US devices

# Remove credentials from keychain
python cli.py logout

# CI / scripts — skip keychain entirely
MAVEO_EMAIL=user@example.com MAVEO_PASSWORD=secret python cli.py devices
```

Example output:

```
$ python cli.py devices
Authenticating as user@example.com...
Found 1 device(s):
  [<device_id>]  My Garage  (type=0)

$ python cli.py status <device_id>
Device  : CONNECTED
Mobile  : disconnected
Session : xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

## Library usage

```python
from maveo import authenticate, get_config, MaveoClient, Region

config = get_config(Region.EU)
auth = authenticate("user@example.com", "password", config)

client = MaveoClient(auth, config)

devices = client.list_devices()
for d in devices:
    print(d.id, d.name, d.device_type)

status = client.get_device_status(devices[0].id)
print(status.device)   # "CONNECTED"
print(status.session)  # UUID used for IoT commands
```

## Region support

| Region | AWS region    | Status        |
|--------|---------------|---------------|
| EU     | eu-central-1  | Tested, works |
| US     | us-west-2     | Config present, untested |

## What's next

- [ ] IoT / WebSocket control (open/close garage, toggle light) using the `session` UUID returned by `get_device_status`
- [ ] Token refresh (avoid re-authenticating on every call)
- [ ] Home Assistant `ConfigEntry` + `Entity` wrappers
