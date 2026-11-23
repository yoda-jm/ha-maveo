"""Maveo cloud REST client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .auth import AuthResult
from .config import Config
from .exceptions import APIError

_TIMEOUT = aiohttp.ClientTimeout(total=10)

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

    def __init__(
        self, session: aiohttp.ClientSession, auth: AuthResult, config: Config
    ) -> None:
        self._session = session
        self._auth = auth
        self._config = config
        self._headers = {
            "User-Agent": "MaveoApp/2.6.0",
            "Authorization": f"Bearer {auth.id_token}",
            "x-client-id": config.client_id,
        }

    async def list_devices(self) -> list[Device]:
        """Return all devices owned by the authenticated user."""
        data = await self._post(
            {"owner": self._auth.identity_id, "command": "list_device"},
            expected_status=200,
        )
        return [
            Device(id=str(d["id"]), name=d["name"], device_type=d["devicetype"])
            for d in data
        ]

    async def list_guest_users(self, device_id: str) -> list[GuestUser]:
        """Return all guest users for a device."""
        data = await self._post(
            {"deviceid": device_id, "command": "list_user"}, expected_status=200
        )
        return [_guest_from_json(u) for u in data]

    async def add_guest_user(
        self, device_id: str, ttl_seconds: int, rights: int = RIGHTS_RESTRICTED
    ) -> GuestUser:
        """Create a temporary guest user and return it, including its token."""
        data = await self._post(
            {
                "deviceid": device_id,
                "command": "add_user",
                "ttl": ttl_seconds,
                "rights": rights,
            },
            expected_status=201,
        )
        return _guest_from_json(data)

    async def remove_guest_user(self, device_id: str, user_id: str) -> None:
        """Delete a guest user."""
        await self._post(
            {"deviceid": device_id, "command": "remove_user", "userid": user_id},
            expected_status=200,
        )

    async def _post(self, payload: dict[str, Any], *, expected_status: int) -> Any:
        """POST to the admin API and return the decoded JSON body."""
        command = payload["command"]
        try:
            async with self._session.post(
                self._config.api_admin_url,
                json=payload,
                headers=self._headers,
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status != expected_status:
                    raise APIError(f"{command}: unexpected HTTP {resp.status}")
                return await resp.json(content_type=None)
        except ValueError as err:
            raise APIError(f"{command}: response is not JSON") from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise APIError(f"{command}: request failed ({type(err).__name__})") from err
