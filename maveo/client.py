"""Maveo HTTP API client."""

from dataclasses import dataclass
from typing import Optional

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
    device: str   # device operational state
    mobile: str   # mobile connection status
    session: str  # UUID used for IoT commands


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
        """Return the current status of a device (includes IoT session UUID)."""
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
