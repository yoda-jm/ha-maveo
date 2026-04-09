"""Constants for the Maveo integration."""

DOMAIN = "maveo"

CONF_REGION = "region"
CONF_COMMAND_MODE = "command_mode"
COMMAND_MODE_DIRECT = "direct"
COMMAND_MODE_TOGGLE = "toggle"

PLATFORMS = [
    "cover",
    "light",
    "binary_sensor",
    "sensor",
    "device_tracker",
    "camera",
]

# Poll intervals (seconds)
DEVICE_POLL_INTERVAL = 30
GUEST_POLL_INTERVAL = 60

# Service names
SERVICE_CREATE_GUEST = "create_guest"
SERVICE_REMOVE_GUEST = "remove_guest"
