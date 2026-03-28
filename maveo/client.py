"""Maveo HTTP API client."""

from dataclasses import dataclass

import requests

from .auth import AuthResult
from .config import Config


@dataclass
class Device:
    id: str
    name: str
    device_type: int


@dataclass
class DeviceStatus:
    device: str   # cloud connectivity state ("CONNECTED" / "DISCONNECTED")
    mobile: str   # mobile app connection state
    session: str  # UUID used as MQTT topic prefix for IoT commands


@dataclass
class GuestUser:
    user_id: str
    token: str
    rights: str
    ttl: str          # seconds as string, or "token expired"
    nametag1: str = ""
    nametag2: str = ""
    nametag3: str = ""


class APIError(Exception):
    pass


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

    def add_guest_user(self, device_id: str, ttl_seconds: int) -> GuestUser:
        """
        Create a temporary guest user.
        Returns the new user including their token (needed for IoT guest control).
        Note: HTTP 201 is expected on success.
        """
        data = self._post_201(
            self._config.api_admin_url,
            {"deviceid": device_id, "command": "add_user", "ttl": ttl_seconds},
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

    def remove_guest_user(self, device_id: str, user_id: str) -> None:
        """Delete a guest user."""
        self._post(
            self._config.api_admin_url,
            {"deviceid": device_id, "command": "remove_user", "userid": user_id},
        )

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
