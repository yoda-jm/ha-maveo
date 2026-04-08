"""Maveo HTTP API client."""

import base64
import os
from dataclasses import dataclass
from urllib.parse import urlencode, unquote_plus

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from .auth import AuthResult
from .config import Config

# Fixed AES-256 key embedded in libmaveo-app_armeabi-v7a.so (QML property 'deepLinkKey').
# Stored as a UTF-16LE string at SO data offset 0x23fc00.
# All Maveo apps share this key; it is used directly (no PBKDF2).
_DEEP_LINK_KEY = base64.b64decode("zbH/cSqJIcgIta9NEhfJ8GSuT79dTQNDB2AcPBfLxyo=")
_DEEP_LINK_BASE_URL = "https://deeplink.marantec-cloud.de"


@dataclass
class Device:
    id: str
    name: str
    device_type: int


@dataclass
class DeviceStatus:
    device: str   # cloud connectivity state ("CONNECTED" / "new" / "DISCONNECTED")
    mobile: str   # mobile app connection state
    session: str  # UUID used as MQTT topic prefix for IoT commands

    @property
    def is_online(self) -> bool:
        return self.device in DEVICE_ONLINE_STATES


# Cloud status values that indicate the device is reachable.
# "new" is returned for freshly provisioned devices that are connected.
DEVICE_ONLINE_STATES: frozenset[str] = frozenset({"CONNECTED", "new"})


RIGHTS_RESTRICTED = 0   # geofence-limited (client-side, min 250 m radius)
RIGHTS_ADMIN      = 1   # unrestricted remote access


@dataclass
class GuestUser:
    user_id: str
    token: str
    rights: str       # "0" = restricted (geofence), "1" = admin (remote)
    ttl: str          # unix timestamp string, or "token expired"
    nametag1: str = ""   # set by guest app on first activation (device/app name)
    nametag2: str = ""   # set by guest app (OS, e.g. "Android" / "iOS")
    nametag3: str = ""   # set by guest app (locale, e.g. "fr")

    @property
    def is_claimed(self) -> bool:
        """True if the key has been imported into a guest app (nametag1 is set)."""
        return bool(self.nametag1)


class APIError(Exception):
    pass


def decode_guest_link(url: str) -> dict:
    """
    Decrypt a Maveo guest deep link and return the payload as a dict.

    Raises ValueError if the URL format is invalid or decryption fails.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    # Extract the raw 'data' value without URL-decoding '+' as space.
    # Base64 uses '+' literally; parse_qs would wrongly convert it to ' '.
    raw = None
    for part in parsed.query.split("&"):
        if part.startswith("data="):
            raw = part[5:]
            break
    if raw is None:
        raise ValueError("No 'data' parameter in URL")
    # Split at the '==' terminator of the 24-char base64 IV block
    eq_pos = raw.index("==")
    iv_b64 = raw[:eq_pos + 2]
    ct_b64 = raw[eq_pos + 2:]

    try:
        iv = base64.b64decode(iv_b64)
        ct = base64.b64decode(ct_b64)
    except Exception as e:
        raise ValueError(f"Base64 decode failed: {e}") from e

    if len(iv) != 16:
        raise ValueError(f"Expected 16-byte IV, got {len(iv)}")

    try:
        cipher = AES.new(_DEEP_LINK_KEY, AES.MODE_CBC, iv)
        plaintext = unpad(cipher.decrypt(ct), 16).decode()
    except Exception as e:
        raise ValueError(f"Decryption failed: {e}") from e

    result = {}
    for part in plaintext.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k] = unquote_plus(v)
    return result


class MaveoClient:
    """
    High-level client for the Maveo cloud API.
    Requires a valid AuthResult from maveo.auth.authenticate().
    """

    _HEADERS = {
        "Content-Type": "application/json",
        "User-Agent": "MaveoApp/2.6.0",
    }

    def __init__(self, auth: AuthResult, config: Config):
        self._auth = auth
        self._config = config
        self._session = requests.Session()
        self._session.headers.update(self._HEADERS)
        self._session.headers["Authorization"] = f"Bearer {auth.id_token}"
        self._session.headers["x-client-id"] = config.client_id

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def list_devices(self) -> list[Device]:
        """Return all devices owned by the authenticated user."""
        data = self._post(
            self._config.api_admin_url,
            {"owner": self._auth.identity_id, "command": "list_device"},
        )
        return [
            Device(id=d["id"], name=d["name"], device_type=d["devicetype"])
            for d in data
        ]

    def get_device_status(self, device_id: str) -> DeviceStatus:
        """
        Return the current cloud status of a device.
        The session UUID is required to send IoT commands.
        """
        data = self._post(
            self._config.api_admin_url,
            {"deviceid": device_id, "command": "status"},
        )
        return DeviceStatus(
            device=data.get("device", ""),
            mobile=data.get("mobile", ""),
            session=data.get("session", ""),
        )

    def set_device_name(self, device_id: str, name: str) -> None:
        """Rename a device."""
        self._post(
            self._config.api_admin_url,
            {"deviceid": device_id, "command": "set_device_name", "name": name},
        )

    # ------------------------------------------------------------------
    # Guest users
    # ------------------------------------------------------------------

    def list_guest_users(self, device_id: str) -> list[GuestUser]:
        """Return all guest users for a device."""
        data = self._post(
            self._config.api_admin_url,
            {"deviceid": device_id, "command": "list_user"},
        )
        return [
            GuestUser(
                user_id=u["userid"],
                token=u["token"],
                rights=u["rights"],
                ttl=u["ttl"],
                nametag1=u.get("nametag1", ""),
                nametag2=u.get("nametag2", ""),
                nametag3=u.get("nametag3", ""),
            )
            for u in data
        ]

    def add_guest_user(self, device_id: str, ttl_seconds: int,
                       rights: int = RIGHTS_RESTRICTED) -> GuestUser:
        """
        Create a temporary guest user.
        rights: RIGHTS_RESTRICTED (0, default) or RIGHTS_ADMIN (1).
        Returns the new user including their token.
        Note: HTTP 201 on success.
        """
        data = self._post_201(
            self._config.api_admin_url,
            {"deviceid": device_id, "command": "add_user",
             "ttl": ttl_seconds, "rights": rights},
        )
        return GuestUser(
            user_id=data["userid"],
            token=data["token"],
            rights=data["rights"],
            ttl=data["ttl"],
            nametag1=data.get("nametag1", ""),
            nametag2=data.get("nametag2", ""),
            nametag3=data.get("nametag3", ""),
        )

    def edit_guest_user(self, device_id: str, user_id: str, *,
                        rights: int | None = None,
                        nametag1: str | None = None,
                        nametag2: str | None = None,
                        nametag3: str | None = None) -> None:
        """
        Update mutable fields of a guest user.
        Only fields that are not None are sent.
        """
        payload: dict = {"deviceid": device_id, "command": "edit", "userid": user_id}
        if rights is not None:
            payload["rights"] = rights
        if nametag1 is not None:
            payload["nametag1"] = nametag1
        if nametag2 is not None:
            payload["nametag2"] = nametag2
        if nametag3 is not None:
            payload["nametag3"] = nametag3
        self._post(self._config.api_admin_url, payload)

    def remove_guest_user(self, device_id: str, user_id: str) -> None:
        """Delete a guest user."""
        self._post(
            self._config.api_admin_url,
            {"deviceid": device_id, "command": "remove_user", "userid": user_id},
        )

    def generate_guest_link(
        self,
        guest: "GuestUser",
        device_id: str,
        device_name: str,
        *,
        location_name: str = "",
        latitude: float = 0.0,
        longitude: float = 0.0,
    ) -> str:
        """
        Generate a Maveo deep link for a guest user.

        The link can be shared out-of-band (QR code, SMS, etc.).  Opening it
        on a phone with the Maveo app installed will import the guest key.

        The TTL field in the URL payload is derived from guest.ttl.  If the
        TTL is a unix timestamp (digits only), it is converted to milliseconds.
        If it is "token expired", the current time is used (link will appear
        expired in the app).

        Encryption: AES-256-CBC with a fixed key embedded in the Maveo app
        binary.  The 16-byte random IV is base64-encoded and prepended to the
        base64-encoded ciphertext; the two blocks are concatenated (no
        separator) as the `data` query parameter.

        Returns the full URL string.
        """
        # Derive TTL in milliseconds
        if guest.ttl.isdigit():
            ttl_ms = int(guest.ttl) * 1000
        else:
            import time
            ttl_ms = int(time.time() * 1000)

        payload = urlencode({
            "userid":       guest.user_id,
            "token":        guest.token,
            "rights":       guest.rights,
            "ttl":          ttl_ms,
            "garagename":   device_name,
            "garageid":     device_id,
            "nametag1":     guest.nametag1,
            "nametag2":     guest.nametag2,
            "nametag3":     guest.nametag3,
            "locationname": location_name,
            "latitude":     latitude,
            "longitude":    longitude,
        })

        iv = os.urandom(16)
        cipher = AES.new(_DEEP_LINK_KEY, AES.MODE_CBC, iv)
        ct = cipher.encrypt(pad(payload.encode(), 16))

        data_param = base64.b64encode(iv).decode() + base64.b64encode(ct).decode()
        return f"{_DEEP_LINK_BASE_URL}?data={data_param}"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _post(self, url: str, payload: dict) -> dict | list:
        try:
            resp = self._session.post(url, json=payload, timeout=10)
        except requests.RequestException as e:
            raise APIError(f"Request failed: {e}") from e

        if not resp.ok:
            raise APIError(f"HTTP {resp.status_code}: {resp.text}")

        return resp.json()

    def _post_201(self, url: str, payload: dict) -> dict:
        """POST expecting HTTP 201 Created."""
        try:
            resp = self._session.post(url, json=payload, timeout=10)
        except requests.RequestException as e:
            raise APIError(f"Request failed: {e}") from e

        if resp.status_code != 201:
            raise APIError(f"HTTP {resp.status_code}: {resp.text}")

        return resp.json()
