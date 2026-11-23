"""Maveo guest deep links."""

from __future__ import annotations

import base64
import os
import time
from urllib.parse import urlencode

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .client import GuestUser

# Fixed AES-256 key from libmaveo-app_armeabi-v7a.so (QML property 'deepLinkKey').
# All Maveo apps share this key; it is used directly (no PBKDF2).
_DEEP_LINK_KEY = base64.b64decode("zbH/cSqJIcgIta9NEhfJ8GSuT79dTQNDB2AcPBfLxyo=")
_DEEP_LINK_BASE_URL = "https://deeplink.marantec-cloud.de"


def build_guest_link(
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
    ttl_ms = int(guest.ttl) * 1000 if guest.ttl.isdigit() else int(time.time() * 1000)

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
    ).encode()

    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(payload) + padder.finalize()
    iv = os.urandom(16)
    encryptor = Cipher(algorithms.AES(_DEEP_LINK_KEY), modes.CBC(iv)).encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()

    data_param = base64.b64encode(iv).decode() + base64.b64encode(ct).decode()
    return f"{_DEEP_LINK_BASE_URL}?data={data_param}"
