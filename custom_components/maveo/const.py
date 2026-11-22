"""Constants for the Maveo integration."""

from homeassistant.const import Platform

DOMAIN = "maveo"

CONF_REGION = "region"
CONF_REFRESH_TOKEN = "refresh_token"

PLATFORMS = [
    Platform.COVER,
    Platform.LIGHT,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.DEVICE_TRACKER,
]

# Poll intervals (seconds)
DEVICE_POLL_INTERVAL = 30
GUEST_POLL_INTERVAL = 60

# Service names
SERVICE_CREATE_GUEST = "create_guest"
SERVICE_REMOVE_GUEST = "remove_guest"
