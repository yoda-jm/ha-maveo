"""Maveo HTTP API client."""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from .auth import AuthResult
from .config import Config

# Fixed AES-256 key from libmaveo-app_armeabi-v7a.so (QML property 'deepLinkKey').
# All Maveo apps share this key; it is used directly (no PBKDF2).
_DEEP_LINK_KEY = base64.b64decode("zbH/cSqJIcgIta9NEhfJ8GSuT79dTQNDB2AcPBfLxyo=")
_DEEP_LINK_BASE_URL = "https://deeplink.marantec-cloud.de"

_TIMEOUT_SECONDS = 10

RIGHTS_RESTRICTED = 0  # geofence-limited (client-side, min 250 m radius)
RIGHTS_ADMIN = 1  # unrestricted remote access


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    device_type: int


@dataclass(frozen=True)
class GuestUser:
    user_id: str
    token: str = field(repr=False)
    rights: str  # "0" = restricted (geofence), "1" = admin (remote)
    ttl: str  # unix timestamp string, or "token expired"
    nametag1: str = ""  # set by guest app on first activation (device/app name)
    nametag2: str = ""  # set by guest app (OS, e.g. "Android" / "iOS")
    nametag3: str = ""  # set by guest app (locale, e.g. "fr")

    @property
    def is_claimed(self) -> bool:
        """True if the key has been imported into a guest app (nametag1 is set)."""
        return bool(self.nametag1)


class APIError(Exception):
    """A REST call failed. Messages never include request or response bodies."""


def _guest_from_json(data: dict[str, Any]) -> GuestUser:
    return GuestUser(
        user_id=data["userid"],
        token=data["token"],
        rights=data["rights"],
        ttl=data["ttl"],
        nametag1=data.get("nametag1", ""),
        nametag2=data.get("nametag2", ""),
        nametag3=data.get("nametag3", ""),
    )


class MaveoClient:
    """Client for the Maveo cloud REST API."""

    _HEADERS = {
        "Content-Type": "application/json",
        "User-Agent": "MaveoApp/2.6.0",
    }

    def __init__(self, auth: AuthResult, config: Config) -> None:
        self._auth = auth
        self._config = config
        self._session = requests.Session()
        self._session.headers.update(self._HEADERS)
        self._session.headers["Authorization"] = f"Bearer {auth.id_token}"
        self._session.headers["x-client-id"] = config.client_id

    def list_devices(self) -> list[Device]:
        """Return all devices owned by the authenticated user."""
        data = self._post(
            {"owner": self._auth.identity_id, "command": "list_device"},
            expected_status=200,
        )
        return [
            Device(id=d["id"], name=d["name"], device_type=d["devicetype"])
            for d in data
        ]

    def list_guest_users(self, device_id: str) -> list[GuestUser]:
        """Return all guest users for a device."""
        data = self._post(
            {"deviceid": device_id, "command": "list_user"}, expected_status=200
        )
        return [_guest_from_json(u) for u in data]

    def add_guest_user(
        self, device_id: str, ttl_seconds: int, rights: int = RIGHTS_RESTRICTED
    ) -> GuestUser:
        """Create a temporary guest user and return it, including its token."""
        data = self._post(
            {
                "deviceid": device_id,
                "command": "add_user",
                "ttl": ttl_seconds,
                "rights": rights,
            },
            expected_status=201,
        )
        return _guest_from_json(data)

    def remove_guest_user(self, device_id: str, user_id: str) -> None:
        """Delete a guest user."""
        self._post(
            {"deviceid": device_id, "command": "remove_user", "userid": user_id},
            expected_status=200,
        )

    def generate_guest_link(
        self,
        guest: GuestUser,
        device_id: str,
        device_name: str,
        *,
        location_name: str = "",
        latitude: float = 0.0,
        longitude: float = 0.0,
    ) -> str:
        """
        Return a Maveo deep link that imports the guest key into the Maveo app.

        The payload is AES-256-CBC encrypted with the app's fixed key.  The
        base64 IV is followed directly by the base64 ciphertext in `data`.
        A guest TTL of "token expired" is sent as the current time.
        """
        ttl_ms = (
            int(guest.ttl) * 1000 if guest.ttl.isdigit() else int(time.time() * 1000)
        )

        payload = urlencode(
            {
                "userid": guest.user_id,
                "token": guest.token,
                "rights": guest.rights,
                "ttl": ttl_ms,
                "garagename": device_name,
                "garageid": device_id,
                "nametag1": guest.nametag1,
                "nametag2": guest.nametag2,
                "nametag3": guest.nametag3,
                "locationname": location_name,
                "latitude": latitude,
                "longitude": longitude,
            }
        )

        iv = os.urandom(16)
        cipher = AES.new(_DEEP_LINK_KEY, AES.MODE_CBC, iv)
        ct = cipher.encrypt(pad(payload.encode(), 16))

        data_param = base64.b64encode(iv).decode() + base64.b64encode(ct).decode()
        return f"{_DEEP_LINK_BASE_URL}?data={data_param}"

    def _post(self, payload: dict[str, Any], *, expected_status: int) -> Any:
        """POST to the admin API and return the decoded JSON body."""
        command = payload["command"]
        try:
            resp = self._session.post(
                self._config.api_admin_url, json=payload, timeout=_TIMEOUT_SECONDS
            )
        except requests.RequestException as err:
            raise APIError(f"{command}: request failed ({type(err).__name__})") from err

        if resp.status_code != expected_status:
            raise APIError(f"{command}: unexpected HTTP {resp.status_code}")

        try:
            return resp.json()
        except ValueError as err:
            raise APIError(f"{command}: response is not JSON") from err
