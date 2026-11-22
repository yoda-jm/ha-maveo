"""Property-based tests (Hypothesis) for the pure protocol code."""

from __future__ import annotations

import base64
import json
from dataclasses import fields
from datetime import UTC, datetime
from urllib.parse import parse_qs

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from hypothesis import given
from hypothesis import strategies as st

from custom_components.maveo import iot
from custom_components.maveo.auth import AuthResult
from custom_components.maveo.client import GuestUser, MaveoClient
from custom_components.maveo.config import Region, get_config

_KEY = base64.b64decode("zbH/cSqJIcgIta9NEhfJ8GSuT79dTQNDB2AcPBfLxyo=")

_text = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), max_size=40)
_ttl = st.one_of(
    st.integers(min_value=0, max_value=4102444800).map(str),
    st.just("token expired"),
)


def _client() -> MaveoClient:
    # Built from the dataclass fields so it also fits the original AuthResult.
    values: dict[str, object] = {f.name: f.name for f in fields(AuthResult)}
    values["expiration"] = datetime(2100, 1, 1, tzinfo=UTC)
    auth = AuthResult(**values)  # type: ignore[arg-type]
    return MaveoClient(auth, get_config(Region.EU))


_CLIENT = _client()


def _decrypt(link: str) -> dict[str, str]:
    raw = link.split("?data=", 1)[1]
    iv = base64.b64decode(raw[:24])
    ct = base64.b64decode(raw[24:])
    plain = unpad(AES.new(_KEY, AES.MODE_CBC, iv).decrypt(ct), 16).decode()
    return {k: v[0] for k, v in parse_qs(plain, keep_blank_values=True).items()}


@given(
    user_id=_text.filter(bool),
    token=st.text(alphabet="0123456789abcdef", min_size=1, max_size=64),
    rights=st.sampled_from(["0", "1"]),
    ttl=_ttl,
    device_id=st.text(alphabet="0123456789", min_size=1, max_size=12),
    name=_text,
    lat=st.floats(min_value=-90, max_value=90, allow_nan=False),
    lng=st.floats(min_value=-180, max_value=180, allow_nan=False),
)
def test_guest_link_round_trips(
    user_id: str,
    token: str,
    rights: str,
    ttl: str,
    device_id: str,
    name: str,
    lat: float,
    lng: float,
) -> None:
    guest = GuestUser(user_id=user_id, token=token, rights=rights, ttl=ttl)
    link = _CLIENT.generate_guest_link(
        guest, device_id, name, location_name=name, latitude=lat, longitude=lng
    )

    assert link.startswith("https://deeplink.marantec-cloud.de?data=")
    fields = _decrypt(link)
    assert fields["userid"] == user_id
    assert fields["token"] == token
    assert fields["rights"] == rights
    assert fields["garageid"] == device_id
    assert fields["garagename"] == name
    assert float(fields["latitude"]) == lat
    assert float(fields["longitude"]) == lng
    if ttl.isdigit():
        assert fields["ttl"] == str(int(ttl) * 1000)


@given(length=st.integers(min_value=0, max_value=268_435_455))
def test_mqtt_remaining_length_round_trips(length: int) -> None:
    encoded = b"\x30" + iot._encode_remaining_length(length)
    assert iot._decode_remaining_length(encoded) == (length, len(encoded) - 1)


@given(
    device_id=st.text(alphabet="0123456789", min_size=1, max_size=12),
    payload=st.dictionaries(
        st.text(min_size=1, max_size=20),
        st.one_of(st.integers(), st.text(max_size=50), st.booleans()),
        max_size=10,
    ),
)
def test_mqtt_publish_round_trips(device_id: str, payload: dict[str, object]) -> None:
    body = json.dumps(payload).encode()
    packet = iot._parse_mqtt_packet(iot._mqtt_publish_packet(f"{device_id}/cmd", body))
    assert packet["type"] == "PUBLISH"
    assert packet["topic"] == f"{device_id}/cmd"
    assert packet["json"] == payload


@given(topic=st.text(alphabet="0123456789/abcdefrsp", min_size=1, max_size=40))
def test_mqtt_subscribe_is_well_formed(topic: str) -> None:
    packet = iot._mqtt_subscribe_packet(topic, packet_id=1)
    length, size = iot._decode_remaining_length(packet)
    assert packet[0] == 0x82
    assert len(packet) == 1 + size + length
