"""MaveoPro REST API client.

This API runs at https://api.yourgateway.io and provides access to the
customer profile (registered devices, contact info) used by the nymea-remoteproxy
integration.

Auth (both values hardcoded in libmaveo-app_armeabi-v7a.so static initializer):
  x-api-key:   QJykAohmC8TA7KG46yFsaz2i
  x-client-id: maveoapp   ← the appId, NOT the Cognito client ID
"""

from dataclasses import dataclass, field

import requests

from .auth import AuthResult

MAVEOPROAPI_BASE = "https://api.yourgateway.io"

# Hardcoded in _GLOBAL__sub_I_maveoproconnection_cpp (Ghidra line 135546/135548)
_API_KEY  = "QJykAohmC8TA7KG46yFsaz2i"
_APP_ID   = "maveoapp"


@dataclass
class MaveoProDevice:
    serial_number: str
    device_type: str         # e.g. "BlueFi"
    free_customer_id: str    # the email address


@dataclass
class MaveoProCustomer:
    email: str
    full_name: str
    company_name: str
    salutation: str
    phone: str
    address_formatted: str
    note: str
    created: str
    updated: str
    devices: list[MaveoProDevice] = field(default_factory=list)


class MaveoProError(Exception):
    pass


class MaveoProClient:
    """
    Client for the MaveoPro REST API at api.yourgateway.io.

    Requires a valid AuthResult from maveo.auth.authenticate().
    The email used to authenticate is also the customer ID for this API.
    """

    def __init__(self, auth: AuthResult, email: str,
                 base_url: str = MAVEOPROAPI_BASE):
        self._auth = auth
        self._email = email
        self._base = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "x-api-key":    _API_KEY,
            "x-client-id":  _APP_ID,
            "Authorization": f"Bearer {auth.id_token}",
            "Content-Type": "application/json",
        })

    def get_customer(self) -> MaveoProCustomer:
        """
        Return the MaveoPro customer profile for the authenticated user.

        The profile contains the list of registered devices with their serial
        numbers and types, but does NOT include the Nymea server UUID.
        """
        resp = self._session.get(
            f"{self._base}/api/free-customers/{self._email}",
            timeout=10,
        )
        data = self._check(resp)
        payload = data.get("payload", {})

        devices = [
            MaveoProDevice(
                serial_number=d.get("serialNumber", ""),
                device_type=d.get("type", ""),
                free_customer_id=d.get("freeCustomerId", ""),
            )
            for d in payload.get("devices", [])
        ]

        addr = payload.get("address", {})
        return MaveoProCustomer(
            email=payload.get("email", ""),
            full_name=payload.get("fullName", ""),
            company_name=payload.get("companyName", ""),
            salutation=payload.get("salutation", ""),
            phone=payload.get("phone", ""),
            address_formatted=addr.get("formatted", ""),
            note=payload.get("note", ""),
            created=payload.get("created", ""),
            updated=payload.get("updated", ""),
            devices=devices,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check(self, resp: requests.Response) -> dict:
        try:
            data = resp.json()
        except Exception as e:
            raise MaveoProError(f"Non-JSON response {resp.status_code}: {resp.text[:200]}") from e
        code = data.get("code", "")
        if code != "200":
            msg = data.get("message", "unknown")
            raise MaveoProError(f"API error {code}: {msg}")
        return data
